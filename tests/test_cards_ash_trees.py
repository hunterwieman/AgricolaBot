"""Ash Trees (minor E74): the persistent on-card free-fence POOL (COST_MODIFIER_DESIGN.md §9).

On play, up to 5 fences move from the supply pile onto the card (a CardStore pool); building
spends them free — the THIRD free-fence source, after positional frees and the per-action
budget. The pieces stay part of the player's 15 (buildable_fences counts them), so the total
never exceeds 15; pool pieces come from the card, so the supply pile is not drawn for them.
"""
from __future__ import annotations

from agricola.actions import ChooseSubAction, CommitBuildPasture, PlaceWorker, Proceed, Stop
from agricola.cards.ash_trees import CARD_ID, POOL_KEY
from agricola.cards.hedge_keeper import CARD_ID as HEDGE_KEEPER_ID
from agricola.constants import CellType, GameMode
from agricola.engine import step
from agricola.helpers import buildable_fences
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.state import Cell

from tests.factories import with_grid
from tests.test_fencing import _fencing_setup, _with_initial_pasture

_PRE_1x1 = [(0, 2)]
_TOP_1x2_34 = frozenset({(0, 3), (0, 4)})    # 5 new edges, adjacent to the pre-1x1 at (0,2)
_INTERIOR_1x1 = frozenset({(1, 1)})          # a fresh 1x1: 4 edges, no perimeter/field


def _own(state, idx, *card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_supply_pool(state, idx, *, supply, pool):
    p = state.players[idx]
    p = fast_replace(p, fences_in_supply=supply, card_state=p.card_state.set(POOL_KEY, pool))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _cards(*, wood, supply, pool, pre_pasture=None, also=()):
    """Cards-mode fencing state owning Ash Trees (+ `also`), with the supply pile + pool set
    consistently (supply + pool must equal 15 - fences_built)."""
    state = fast_replace(_fencing_setup(wood=wood), mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    state = _own(state, 0, CARD_ID, *also)
    return _set_supply_pool(state, 0, supply=supply, pool=pool)


def _enter(state):
    state = step(state, PlaceWorker(space="fencing"))
    return step(state, ChooseSubAction(name="build_fences"))


def _wood(s, i=0): return s.players[i].resources.wood
def _supply(s, i=0): return s.players[i].fences_in_supply
def _pool(s, i=0): return s.players[i].card_state.get(POOL_KEY, 0)
def _finish(s):
    s = step(s, Proceed()); s = step(s, Stop()); return step(s, Stop())


# ---------------------------------------------------------------------------
# Registration + the "planted = sown" prerequisite
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.specs import MINORS
    assert CARD_ID in MINORS


def test_prereq_two_planted_fields_means_sown():
    from agricola.cards.specs import MINORS, prereq_met
    spec = MINORS[CARD_ID]
    s = _fencing_setup(wood=1)
    assert not prereq_met(spec, s, 0)                                   # no fields
    # Two PLOWED but unsown fields do NOT count ("planted" = sown).
    plowed = with_grid(s, 0, {(0, 3): Cell(cell_type=CellType.FIELD),
                              (0, 4): Cell(cell_type=CellType.FIELD)})
    assert not prereq_met(spec, plowed, 0)
    # Two fields each with a crop DO count.
    sown = with_grid(s, 0, {(0, 3): Cell(cell_type=CellType.FIELD, grain=1),
                            (0, 4): Cell(cell_type=CellType.FIELD, veg=1)})
    assert prereq_met(spec, sown, 0)
    # Only one planted -> not enough.
    one = with_grid(s, 0, {(0, 3): Cell(cell_type=CellType.FIELD, grain=1),
                           (0, 4): Cell(cell_type=CellType.FIELD)})
    assert not prereq_met(spec, one, 0)


def test_prereq_counts_planted_card_fields():
    """Ruling 45 (2026-07-12): a card-field is a field, so a PLANTED card-field
    joins the "2 planted fields" count. A wood-planted Wood Field counts (it is
    a planted field — its own text says "plant"); an owned but EMPTY card-field
    does not (unplanted)."""
    from agricola.cards.card_fields import stacks_to_store
    from agricola.cards.specs import MINORS, prereq_met
    spec = MINORS[CARD_ID]
    s = _fencing_setup(wood=1)

    def _set_stacks(state, idx, cid, stacks):
        p = state.players[idx]
        p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
        return fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))

    # Met ONLY via card-fields (the old grid-only count saw 0): a veg-planted
    # Beanfield + a wood-planted Wood Field, zero grid fields.
    cs = _own(s, 0, "beanfield", "wood_field")
    cs = _set_stacks(cs, 0, "beanfield", ((0, 2, 0, 0),))
    cs = _set_stacks(cs, 0, "wood_field", ((0, 0, 3, 0), (0, 0, 0, 0)))
    assert prereq_met(spec, cs, 0)
    # One planted grid field + one planted card-field also reaches 2.
    one_grid = with_grid(s, 0, {(0, 3): Cell(cell_type=CellType.FIELD, grain=1)})
    mixed = _set_stacks(_own(one_grid, 0, "beanfield"), 0,
                        "beanfield", ((0, 2, 0, 0),))
    assert prereq_met(spec, mixed, 0)
    # An owned but EMPTY card-field is not planted -> still only 1 of 2.
    assert not prereq_met(spec, _own(one_grid, 0, "beanfield"), 0)


# ---------------------------------------------------------------------------
# on_play moves fences supply -> pool
# ---------------------------------------------------------------------------

def test_on_play_moves_five_supply_to_pool():
    from agricola.cards.specs import MINORS
    s = fast_replace(_fencing_setup(wood=1), mode=GameMode.CARDS)       # fresh: supply 15
    s2 = MINORS[CARD_ID].on_play(s, 0)
    assert _supply(s2) == 10        # 15 - 5
    assert _pool(s2) == 5


def test_on_play_moves_min_when_supply_low():
    from agricola.cards.specs import MINORS
    s = fast_replace(_fencing_setup(wood=1), mode=GameMode.CARDS)
    s = _set_supply_pool(s, 0, supply=3, pool=0)                        # only 3 in supply
    s2 = MINORS[CARD_ID].on_play(s, 0)
    assert _supply(s2) == 0 and _pool(s2) == 3                          # moved min(5, 3)


# ---------------------------------------------------------------------------
# The pool counts toward buildable (total never exceeds 15) and funds free builds
# ---------------------------------------------------------------------------

def test_buildable_counts_pool_total_stays_15():
    state = _cards(wood=0, supply=10, pool=5)                           # fresh, owned
    assert buildable_fences(state.players[0]) == 15                     # 10 supply + 5 pool


def test_pool_funds_a_build_for_free():
    # 0 wood; the pool covers a fresh 1x1's 4 edges -> free, pool 5->1, supply untouched
    # (pool pieces come from the card, not the supply pile).
    state = _cards(wood=0, supply=10, pool=5)
    state = _enter(state)
    state = step(state, CommitBuildPasture(cells=_INTERIOR_1x1))
    top = state.pending_stack[-1]
    assert top.accrued_cost.wood == 0
    assert _supply(state) == 10        # no supply pieces drawn
    assert _pool(state) == 1           # 5 - 4
    state = _finish(state)
    assert _wood(state) == 0           # nothing paid at settle


def test_pool_enables_zero_wood_build():
    # With the pool, a 0-wood player is offered the 1x1; without it (no Ash Trees) not.
    state = _enter(_cards(wood=0, supply=10, pool=5))
    commits = {a.cells for a in legal_actions(state) if isinstance(a, CommitBuildPasture)}
    assert _INTERIOR_1x1 in commits

    no_pool = fast_replace(_fencing_setup(wood=0), mode=GameMode.CARDS)
    placements = [a for a in legal_actions(no_pool)
                  if isinstance(a, PlaceWorker) and a.space == "fencing"]
    assert not placements, "0 wood, no pool -> nothing buildable -> Fencing not offered"


def test_pool_spent_after_per_action_budget():
    # Greedy order (§9.4): positional -> per-action budget -> persistent pool. With Hedge
    # Keeper (budget 3) + Ash Trees (pool 5), a 5-edge build pays 0: budget covers 3 (drawn
    # from supply, wood waived), the pool covers the remaining 2 (drawn from the card). So
    # supply_drawn = 3 (the budget edges), pool 5 -> 3.
    state = _cards(wood=0, supply=6, pool=5, pre_pasture=_PRE_1x1, also=(HEDGE_KEEPER_ID,))
    # built = 4 (pre-1x1); supply 6 + pool 5 = 11 = 15 - 4 (consistent).
    state = _enter(state)
    assert state.pending_stack[-1].free_fence_budget == 3               # Hedge Keeper seeded
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))          # 5 new edges
    top = state.pending_stack[-1]
    assert top.accrued_cost.wood == 0          # 3 budget + 2 pool = all 5 free
    assert _pool(state) == 3                     # 5 - 2 (pool covered the post-budget 2)
    assert _supply(state) == 3                   # 6 - 3 (the 3 budget edges drew supply pieces)
    state = _finish(state)
    assert _wood(state) == 0
