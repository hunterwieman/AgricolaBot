"""Tests for Swing Plow (minor C19): a Farmland-only multi-shot granted plow.

  - "Place 4 field tiles on this card. Each time you use the 'Farmland' action space,
    you can also plow up to 2 fields from this card."

Covers: registration; the up-to-2 grant on Farmland; the per-use cap of 2; the lifetime
tile depletion across uses; enforce-first (the base plow is still mandatory); the
cell-level stranding guard; and the not-owned / opponent negatives.
"""
import agricola.cards.swing_plow  # noqa: F401

from agricola.actions import (
    ChooseSubAction,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Proceed,
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
    minors=("swing_plow",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5) if g[r][c].cell_type == CellType.FIELD)


def _tiles(state, idx):
    return state.players[idx].card_state.get("swing_plow")


def _fresh_turn_same_player(state, idx):
    sp = fast_replace(get_space(state.board, "farmland"), workers=(0, 0))
    state = fast_replace(state, board=with_space(state.board, "farmland", sp))
    p = fast_replace(state.players[idx], used_this_turn=frozenset(),
                     people_home=max(1, state.players[idx].people_home))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return fast_replace(state, current_player=idx)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    spec = MINORS["swing_plow"]
    assert spec.cost.resources == Resources(wood=3)
    assert spec.min_occupations == 3


# ---------------------------------------------------------------------------
# The grant: up to 2 fields on Farmland, plus the mandatory base plow
# ---------------------------------------------------------------------------

def test_grants_two_plus_base_plow():
    """One Farmland use: fire the grant (2 fields) before the mandatory base plow (1)
    → +3 fields, and the lifetime pool drops 4 → 2."""
    s = _own(_state(), 0, "swing_plow")
    assert _tiles(s, 0) is None  # defaults to 4
    f0 = _num_fields(s, 0)

    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="swing_plow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="swing_plow"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlow) and top.max_plows == 2

    # Two granted plows.
    for _ in range(2):
        commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
        s = step(s, commits[0])
    assert s.pending_stack[-1].phase == "after"   # budget spent → flipped to after
    s = step(s, Stop())                           # pop granted plow
    assert _num_fields(s, 0) == f0 + 2
    assert _tiles(s, 0) == 2                       # 4 − 2 plowed

    # The mandatory base plow is still required (the grant did NOT satisfy it).
    s = step(s, ChooseSubAction(name="plow"))
    base = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, base[0])
    s = step(s, Stop())                           # pop base plow's after
    s = step(s, Stop())                           # pop the Farmland host
    assert not s.pending_stack
    assert _num_fields(s, 0) == f0 + 3            # 2 granted + 1 base


def test_per_use_cap_is_two():
    """The grant offers at most 2 fields per Farmland use even with tiles + cells to
    spare: after 2 commits the frame is in its after-phase (no further CommitPlow)."""
    s = _own(_state(), 0, "swing_plow")
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="swing_plow"))
    for _ in range(2):
        commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
        s = step(s, commits[0])
    la = legal_actions(s)
    assert not any(isinstance(a, CommitPlow) for a in la)   # capped at 2
    assert Stop() in la and s.pending_stack[-1].phase == "after"


def test_can_finish_grant_early_via_proceed():
    """The player may plow fewer than 2 — Proceed (offered once num_plowed >= 1)
    finishes the grant; only the fields actually plowed are debited."""
    s = _own(_state(), 0, "swing_plow")
    f0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="swing_plow"))
    commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, commits[0])                       # one granted plow
    assert Proceed() in legal_actions(s)
    s = step(s, Proceed())                        # finish early
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert _num_fields(s, 0) == f0 + 1
    assert _tiles(s, 0) == 3                       # only 1 tile spent


# ---------------------------------------------------------------------------
# Lifetime tile depletion across two uses
# ---------------------------------------------------------------------------

def _use_farmland_grant_full(state):
    """Fire the grant, plow 2, then do the mandatory base plow; return after host pops."""
    state = step(state, PlaceWorker(space="farmland"))
    state = step(state, FireTrigger(card_id="swing_plow"))
    for _ in range(2):
        commits = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
        state = step(state, commits[0])
    state = step(state, Stop())                   # pop granted plow
    state = step(state, ChooseSubAction(name="plow"))
    base = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    state = step(state, base[0])
    state = step(state, Stop())                   # base plow after
    return step(state, Stop())                    # Farmland host


def test_lifetime_tiles_deplete_across_two_uses():
    s = _own(_state(), 0, "swing_plow")
    s = _use_farmland_grant_full(s)
    assert _tiles(s, 0) == 2                       # 4 − 2

    s = _fresh_turn_same_player(s, 0)
    s = _use_farmland_grant_full(s)
    assert _tiles(s, 0) == 0                       # 2 − 2

    # Third use: pool exhausted → no grant offered, but the base plow still works.
    s = _fresh_turn_same_player(s, 0)
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="swing_plow") not in legal_actions(s)
    assert ChooseSubAction(name="plow") in legal_actions(s)


# ---------------------------------------------------------------------------
# Stranding guard
# ---------------------------------------------------------------------------

def test_not_offered_when_grant_would_strand_base_plow():
    """A single isolated empty cell → firing the grant would consume it and leave the
    mandatory base plow with no target → the grant is suppressed (base plow still legal)."""
    s = _own(_state(), 0, "swing_plow")
    overrides = {(r, c): Cell(cell_type=CellType.ROOM)
                 for r in range(3) for c in range(5) if (r, c) != (0, 0)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    la = legal_actions(s)
    assert FireTrigger(card_id="swing_plow") not in la
    assert ChooseSubAction(name="plow") in la


def test_granted_plow_excludes_stranding_cell():
    """0-field board: (0,0)&(0,1) adjacent empties (a safe pair) + (0,3) isolated empty.
    The granted plow must exclude the isolated cell (plowing it would strand the base
    plow), per CommitPlow."""
    s = _own(_state(), 0, "swing_plow")
    empties = {(0, 0), (0, 1), (0, 3)}
    overrides = {(r, c): (Cell(cell_type=CellType.EMPTY) if (r, c) in empties
                          else Cell(cell_type=CellType.ROOM))
                 for r in range(3) for c in range(5)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="swing_plow"))
    cells = {(a.row, a.col) for a in legal_actions(s) if isinstance(a, CommitPlow)}
    assert cells == {(0, 0), (0, 1)}              # isolated (0,3) excluded


def test_stranding_rechecked_per_commit():
    """0-field board with exactly two adjacent empties (0,0),(0,1) and the rest ROOM:
    the FIRST granted plow is offered (a safe two-plow pair exists), but after taking it
    the grant must STOP — plowing the second would leave the mandatory base plow no cell.
    So num_plowed flips to after at 1 even though max_plows is 2."""
    s = _own(_state(), 0, "swing_plow")
    empties = {(0, 0), (0, 1)}
    overrides = {(r, c): (Cell(cell_type=CellType.EMPTY) if (r, c) in empties
                          else Cell(cell_type=CellType.ROOM))
                 for r in range(3) for c in range(5)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="swing_plow"))
    commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, commits[0])                       # plow one of the safe pair
    # Only one empty cell remains; it must be reserved for the mandatory base plow, so the
    # grant is forced into its after-phase (no second granted plow).
    assert s.pending_stack[-1].phase == "after"
    assert not any(isinstance(a, CommitPlow) for a in legal_actions(s))
    assert _tiles(s, 0) == 3                       # only one tile spent


# ---------------------------------------------------------------------------
# Negatives: not owned / opponent
# ---------------------------------------------------------------------------

def test_not_offered_when_not_owned():
    s = _state()                                   # nobody owns swing_plow
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="swing_plow") not in legal_actions(s)


def test_not_offered_to_opponents_use():
    """Player 1 owns it; player 0 uses Farmland → no grant for player 0."""
    s = _own(_state(), 1, "swing_plow")
    s = step(s, PlaceWorker(space="farmland"))     # current_player == 0
    assert FireTrigger(card_id="swing_plow") not in legal_actions(s)
