import agricola.cards.stone_clearing  # noqa: F401
"""Stone Clearing (C6) — the on-play placement + registration.

Card text: "Immediately place 1 stone on each of your empty fields. Harvest
them during the next field phase. These fields are considered planted until
then." ERRATA: "harvest the fields with stone normally, and the fields are
considered planted until the stone is gone." Cost 1 Food, no prereq, no VPs,
traveling (passed to the opponent after execution).

User rulings (2026-07-20): the code must never perceive a stoned field as
empty (sowing, card prerequisites, effects); "each of your empty fields"
covers empty card-fields too — 1 stone per CARD ("wood field would get 1
stone not 2"), sow restrictions notwithstanding (the veg-only Beanfield still
receives stone).

The engine half (Cell.stone, the field_empty/field_planted predicates, the
field-phase stone take) is pinned by tests/test_stone_fields.py; these tests
pin the card's OWN facts: registration, the on-play placement over board and
card-fields, the real sow/placement legality effects, the real harvest walk,
cost + passing through the real play-minor flow, the legal null-effect play,
and the re-play (traveling return) behavior.
"""
import agricola.cards.beanfield  # noqa: F401 — card-field scope tests
import agricola.cards.wood_field  # noqa: F401 — card-field scope tests

from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.card_fields import (
    CARD_FIELDS,
    EMPTY_STACK,
    card_field_stacks,
    stacks_to_store,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import _can_sow, legal_actions
from agricola.pending import PendingPlayMinor, PendingSow
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_fields,
    with_grid,
    with_pending_stack,
    with_phase,
    with_resources,
    with_space,
)
from tests.test_utils import sole_play_minor

CARD = "stone_clearing"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD,) + tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, cid, stacks):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _on_play(state, idx=0):
    return MINORS[CARD].on_play(state, idx)


# ---------------------------------------------------------------------------
# Registration facts
# ---------------------------------------------------------------------------

def test_registration():
    spec = MINORS[CARD]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.prereq is None                    # no prerequisite (null-effect legal)
    assert spec.vps == 0
    assert spec.passing_left is True              # traveling card
    # A pure on-play minor: not itself a card-field, no trigger machinery.
    assert CARD not in CARD_FIELDS
    for entries in TRIGGERS.values():
        assert CARD not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# on_play — board placement: every empty field, ONLY empty fields
# ---------------------------------------------------------------------------

def test_on_play_stones_every_empty_field_and_only_empty_fields():
    s = with_grid(setup(0), 0, {
        (0, 0): Cell(cell_type=CellType.FIELD),             # empty -> stone
        (0, 1): Cell(cell_type=CellType.FIELD),             # empty -> stone
        (0, 2): Cell(cell_type=CellType.FIELD, grain=2),    # planted -> untouched
        (0, 3): Cell(cell_type=CellType.FIELD, veg=1),      # planted -> untouched
        (0, 4): Cell(cell_type=CellType.FIELD, stone=1),    # already stoned -> stays 1
    })
    s = with_fields(s, 1, [(0, 0)])                         # opponent's empty field
    out = _on_play(s, 0)
    grid = out.players[0].farmyard.grid
    assert grid[0][0].stone == 1 and grid[0][1].stone == 1
    assert grid[0][2] == Cell(cell_type=CellType.FIELD, grain=2)
    assert grid[0][3] == Cell(cell_type=CellType.FIELD, veg=1)
    assert grid[0][4].stone == 1                            # 1, never 2
    # Non-field cells never receive stone.
    assert all(cell.stone == 0
               for r, row in enumerate(grid) for c, cell in enumerate(row)
               if cell.cell_type != CellType.FIELD)
    # The opponent is untouched.
    assert out.players[1] == s.players[1]


def test_replay_stones_only_newly_empty_fields():
    # The traveling card can return and be played again: fields stoned by the
    # first play are NOT empty (field_empty is the single predicate), so a
    # re-play touches only fields plowed empty since.
    s = with_fields(setup(0), 0, [(0, 0), (0, 1)])
    s = _on_play(s, 0)                                      # first play
    grid = s.players[0].farmyard.grid
    assert grid[0][0].stone == 1 and grid[0][1].stone == 1
    s = with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})   # newly plowed
    out = _on_play(s, 0)                                    # re-play
    grid = out.players[0].farmyard.grid
    assert grid[0][0].stone == 1 and grid[0][1].stone == 1  # untouched, not 2
    assert grid[0][2].stone == 1                            # only the new field


# ---------------------------------------------------------------------------
# The stoned field is not empty: sowing (real flows) + planted readers
# ---------------------------------------------------------------------------

def test_stoned_field_blocks_grain_utilization_placement():
    # Real placement legality: grain in supply and ONE field. Empty field ->
    # Grain Utilization is placeable (sow possible); after Stone Clearing
    # stones it, nothing is sowable (and no oven to bake) -> not placeable.
    s = with_current_player(setup(0), 0)
    s = with_space(s, "grain_utilization", revealed=True)
    s = with_resources(s, 0, grain=1)
    s = with_fields(s, 0, [(0, 0)])
    place = PlaceWorker(space="grain_utilization")
    assert place in legal_actions(s)
    stoned = _on_play(s, 0)
    assert place not in legal_actions(stoned)


def test_sow_enumeration_excludes_the_stoned_cell():
    # 1 stoned field + 1 empty field, 2 grain: only ONE board sow fits (the
    # stoned cell is not a sow target).
    s = with_fields(setup(0), 0, [(0, 0), (0, 1)])
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, stone=1)})
    s = with_resources(s, 0, grain=2)
    s = with_pending_stack(s, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(s) if isinstance(a, CommitSow)]
    assert CommitSow(grain=1, veg=0) in sows
    assert CommitSow(grain=2, veg=0) not in sows


def test_stoned_field_reads_planted_for_reader_cards():
    # "These fields are considered planted until then" — the field-level
    # reader status. Garden Claw's planted-field count is a live reader.
    from agricola.cards.garden_claw import _planted_fields
    s = with_fields(setup(0), 0, [(0, 0), (0, 1)])
    assert _planted_fields(s, 0) == 0
    out = _on_play(s, 0)
    assert _planted_fields(out, 0) == 2


# ---------------------------------------------------------------------------
# The harvest — a REAL field phase yields the stone; the field re-empties
# ---------------------------------------------------------------------------

def test_real_field_phase_harvests_stone_then_field_is_sowable_again():
    s = with_fields(setup(0), 0, [(0, 0)])
    s = _on_play(s, 0)
    for idx in (0, 1):
        s = with_resources(s, idx, food=10, grain=1)
    stone0 = s.players[0].resources.stone
    s = with_phase(s, Phase.HARVEST_FIELD)
    s = _advance_until_decision(s)                          # the real walk
    assert s.phase in (Phase.HARVEST_FEED, Phase.HARVEST_BREED,
                       Phase.PREPARATION, Phase.WORK), s.phase
    assert s.players[0].resources.stone == stone0 + 1       # harvested normally
    cell = s.players[0].farmyard.grid[0][0]
    assert cell.stone == 0 and cell.field_empty             # stone gone -> empty
    assert _can_sow(s.players[0])                           # sowable again


def test_field_take_manifest_carries_a_stone_cell_entry():
    s = with_fields(setup(0), 0, [(0, 0)])
    s = _on_play(s, 0)
    nxt, occasion = field_take(s, 0)
    by_source = {e.source: e for e in occasion.entries}
    e = by_source["cell:0,0"]
    assert (e.crop, e.amount, e.emptied) == ("stone", 1, True)
    assert nxt.players[0].resources.stone == s.players[0].resources.stone + 1


# ---------------------------------------------------------------------------
# Card-fields (user ruling 2026-07-20: empty card-fields receive stone too)
# ---------------------------------------------------------------------------

def test_empty_beanfield_receives_stone_despite_veg_only_sow_restriction():
    s = _own(setup(0), 0, ["beanfield"])
    out = _on_play(s, 0)
    assert card_field_stacks(out.players[0], "beanfield") == ((0, 0, 0, 1),)


def test_beanfield_stone_is_harvested_in_the_field_phase_via_card_entry():
    s = _own(setup(0), 0, ["beanfield"])
    s = _on_play(s, 0)
    stone0 = s.players[0].resources.stone
    nxt, occasion = field_take(s, 0)
    entries = [e for e in occasion.entries if e.source == "card:beanfield"]
    assert len(entries) == 1
    assert (entries[0].crop, entries[0].amount, entries[0].emptied) == ("stone", 1, True)
    assert nxt.players[0].resources.stone == stone0 + 1
    assert card_field_stacks(nxt.players[0], "beanfield") == (EMPTY_STACK,)


def test_empty_wood_field_receives_exactly_one_stone_total():
    # "wood field would get 1 stone not 2" (user ruling 2026-07-20): one stone
    # into one stack, the other stack stays empty.
    s = _own(setup(0), 0, ["wood_field"])
    out = _on_play(s, 0)
    assert card_field_stacks(out.players[0], "wood_field") == (
        (0, 0, 0, 1), EMPTY_STACK)


def test_wood_field_other_stack_remains_wood_sowable():
    # DRIVER-ADOPTED READING, flagged for user confirmation (stone_clearing.py
    # docstring): stone in one stack leaves the OTHER stack sowable exactly as
    # a half-wood-planted Wood Field's is — the machinery's established
    # per-stack sowability; "considered planted" is the field-LEVEL reader
    # status, not a per-stack sow block.
    s = _own(setup(0), 0, ["wood_field"])
    s = _on_play(s, 0)
    s = with_resources(s, 0, wood=2)
    s = with_pending_stack(s, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(s) if isinstance(a, CommitSow)]
    single = CommitSow(grain=0, veg=0, card_sows=(("wood_field", "wood"),))
    double = CommitSow(grain=0, veg=0,
                       card_sows=(("wood_field", "wood"), ("wood_field", "wood")))
    assert single in sows                     # the empty stack is sowable
    assert double not in sows                 # only ONE stack is empty


def test_half_planted_wood_field_receives_nothing():
    # A card holding anything in any stack is NOT empty (the
    # unplanted-card-field semantics) -> no stone.
    s = _own(setup(0), 0, ["wood_field"])
    s = _set_stacks(s, 0, "wood_field", [(0, 0, 3, 0), EMPTY_STACK])
    out = _on_play(s, 0)
    assert card_field_stacks(out.players[0], "wood_field") == (
        (0, 0, 3, 0), EMPTY_STACK)


# ---------------------------------------------------------------------------
# The real play-minor flow: cost debits, effect fires, the card passes left
# ---------------------------------------------------------------------------

def test_play_flow_costs_one_food_places_stone_and_passes():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = with_space(cs, "major_improvement", revealed=True)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_resources(cs, cp, food=1)
    cs = with_fields(cs, cp, [(0, 0)])

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD))

    pl = cs.players[cp]
    assert pl.resources.food == 0                           # 1-food cost debited
    assert pl.farmyard.grid[0][0].stone == 1                # effect fired
    assert CARD not in pl.minor_improvements                # never kept
    assert CARD not in pl.hand_minors
    assert CARD in cs.players[1 - cp].hand_minors           # passed left


def test_null_effect_play_is_legal():
    # No fields anywhere (board or card): still a legal play — a legal +0
    # (the Garden Claw precedent), no invented prerequisite.
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_resources(cs, cp, food=1)
    store_before = cs.players[cp].card_state
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, CARD))
    pl = cs.players[cp]
    assert pl.resources.food == 0                           # cost paid
    assert all(cell.stone == 0 for row in pl.farmyard.grid for cell in row)
    assert pl.card_state == store_before                    # no card-field touched
    assert CARD in cs.players[1 - cp].hand_minors           # still passes
