"""Tests for Turnwrest Plow (minor D20): a Farmland/Cultivation multi-shot granted plow.

  - "Place 2 field tiles on this card. Each time you use the 'Farmland' or 'Cultivation'
    action space, you can also plow up to 2 fields from this card."

Covers: registration; the up-to-2 grant on BOTH Farmland and Cultivation; the per-use cap
of 2; the lifetime tile depletion (2 then exhausted); enforce-first on Farmland; the
cell-level stranding guard on Farmland; that Cultivation uses the looser `_can_plow` guard
(no must_preserve_base); and the not-owned / opponent negatives.
"""
import agricola.cards.turnwrest_plow  # noqa: F401

from agricola.actions import (
    ChooseSubAction,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_grid

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("turnwrest_plow",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    # Reveal Cultivation so it is a legal placement.
    sp = fast_replace(get_space(s.board, "cultivation"), revealed=True, workers=(0, 0))
    return fast_replace(s, board=with_space(s.board, "cultivation", sp))


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5) if g[r][c].cell_type == CellType.FIELD)


def _tiles(state, idx):
    return state.players[idx].card_state.get("turnwrest_plow")


def _fresh_turn_same_player(state, idx, space):
    sp = fast_replace(get_space(state.board, space), workers=(0, 0))
    state = fast_replace(state, board=with_space(state.board, space, sp))
    p = fast_replace(state.players[idx], used_this_turn=frozenset(),
                     people_home=max(1, state.players[idx].people_home))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return fast_replace(state, current_player=idx)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    spec = MINORS["turnwrest_plow"]
    assert spec.cost.resources == Resources(wood=3)
    assert spec.min_occupations == 2


# ---------------------------------------------------------------------------
# Grant on Farmland
# ---------------------------------------------------------------------------

def test_grants_two_on_farmland():
    s = _own(_state(), 0, "turnwrest_plow")
    f0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="turnwrest_plow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="turnwrest_plow"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlow) and top.max_plows == 2 and top.must_preserve_base
    for _ in range(2):
        commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
        s = step(s, commits[0])
    s = step(s, Stop())
    assert _num_fields(s, 0) == f0 + 2
    assert _tiles(s, 0) == 0                        # 2 − 2, pool exhausted


# ---------------------------------------------------------------------------
# Grant on Cultivation (looser guard, no must_preserve_base)
# ---------------------------------------------------------------------------

def test_grants_two_on_cultivation():
    s = _own(_state(), 0, "turnwrest_plow")
    f0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="cultivation"))
    assert FireTrigger(card_id="turnwrest_plow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="turnwrest_plow"))
    top = s.pending_stack[-1]
    # Cultivation now uses the same restriction as Farmland (must_preserve_base=True; loss-less).
    assert isinstance(top, PendingPlow) and top.max_plows == 2 and top.must_preserve_base
    for _ in range(2):
        commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
        s = step(s, commits[0])
    s = step(s, Stop())
    assert _num_fields(s, 0) == f0 + 2
    assert _tiles(s, 0) == 0


def test_single_plowable_cell_suppresses_grant_on_both_spaces():
    """A single plowable cell would strand a second plow, so `_can_plow_twice` suppresses the
    grant on BOTH Farmland and Cultivation. Cultivation uses the same restriction now — it's
    loss-less, since the FREE base plow takes that one cell instead of spending a card tile."""
    s = _own(_state(), 0, "turnwrest_plow")
    overrides = {(r, c): Cell(cell_type=CellType.ROOM)
                 for r in range(3) for c in range(5) if (r, c) != (0, 0)}
    s = with_grid(s, 0, overrides)
    sf = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="turnwrest_plow") not in legal_actions(sf)
    sc = step(s, PlaceWorker(space="cultivation"))
    assert FireTrigger(card_id="turnwrest_plow") not in legal_actions(sc)


# ---------------------------------------------------------------------------
# Per-use cap + lifetime depletion across uses (Farmland then Cultivation)
# ---------------------------------------------------------------------------

def test_per_use_cap_two_and_pool_depletes_across_spaces():
    """First Farmland use plows 1 (early Stop via the after-flip path), leaving 1 tile;
    the second use (Cultivation) can then plow only 1 (pool has 1 left → max_plows=1)."""
    s = _own(_state(), 0, "turnwrest_plow")
    # Use 1: Farmland, fire grant, plow exactly one then finish early via Proceed.
    from agricola.actions import Proceed
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="turnwrest_plow"))
    commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, commits[0])
    s = step(s, Proceed())                          # finish early after 1
    s = step(s, Stop())                             # pop granted plow
    assert _tiles(s, 0) == 1                         # 2 − 1
    # Wrap up the Farmland base plow + host.
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, [a for a in legal_actions(s) if isinstance(a, CommitPlow)][0])
    s = step(s, Stop())
    s = step(s, Stop())

    # Use 2: Cultivation — pool has 1, so the grant caps at 1 (max_plows=min(2,1)).
    s = _fresh_turn_same_player(s, 0, "cultivation")
    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, FireTrigger(card_id="turnwrest_plow"))
    assert s.pending_stack[-1].max_plows == 1
    commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, commits[0])
    assert s.pending_stack[-1].phase == "after"     # capped at 1 (pool drained)
    s = step(s, Stop())
    assert _tiles(s, 0) == 0

    # Use 3: pool exhausted → no grant.
    s = _fresh_turn_same_player(s, 0, "cultivation")
    s = step(s, PlaceWorker(space="cultivation"))
    assert FireTrigger(card_id="turnwrest_plow") not in legal_actions(s)


# ---------------------------------------------------------------------------
# Stranding guard on Farmland
# ---------------------------------------------------------------------------

def test_farmland_not_offered_when_grant_would_strand_base():
    s = _own(_state(), 0, "turnwrest_plow")
    overrides = {(r, c): Cell(cell_type=CellType.ROOM)
                 for r in range(3) for c in range(5) if (r, c) != (0, 0)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    la = legal_actions(s)
    assert FireTrigger(card_id="turnwrest_plow") not in la
    assert ChooseSubAction(name="plow") in la


def test_farmland_granted_plow_excludes_stranding_cell():
    s = _own(_state(), 0, "turnwrest_plow")
    empties = {(0, 0), (0, 1), (0, 3)}
    overrides = {(r, c): (Cell(cell_type=CellType.EMPTY) if (r, c) in empties
                          else Cell(cell_type=CellType.ROOM))
                 for r in range(3) for c in range(5)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="turnwrest_plow"))
    cells = {(a.row, a.col) for a in legal_actions(s) if isinstance(a, CommitPlow)}
    assert cells == {(0, 0), (0, 1)}


# ---------------------------------------------------------------------------
# Negatives
# ---------------------------------------------------------------------------

def test_not_offered_when_not_owned():
    s = _state()
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="turnwrest_plow") not in legal_actions(s)


def test_not_offered_to_opponents_use():
    s = _own(_state(), 1, "turnwrest_plow")
    s = step(s, PlaceWorker(space="cultivation"))   # current_player == 0
    assert FireTrigger(card_id="turnwrest_plow") not in legal_actions(s)
