"""Tests for Wheel Plow (minor A18): a once-per-game, first-worker, 2-field granted plow.

  - "Once this game, when you use the 'Farmland' or 'Cultivation' action space with the
    first person you place in a round, you can plow 2 additional fields."

Covers: registration; the 2-field grant on Farmland and Cultivation; the FIRST-worker gate
(2nd-or-later placement is excluded); the once-per-game gate (after one use the trigger is
never offered again); enforce-first on Farmland; the cell-level stranding guard; and the
not-owned / opponent negatives.
"""
import agricola.cards.wheel_plow  # noqa: F401

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
from agricola.state import Cell, CardStore, get_space, with_space
from tests.factories import with_grid

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("wheel_plow",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
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


def _set_people(state, idx, home, total):
    p = fast_replace(state.players[idx], people_home=home, people_total=total)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _used(state, idx):
    return state.players[idx].card_state.get("wheel_plow", False)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    spec = MINORS["wheel_plow"]
    assert spec.cost.resources == Resources(wood=2)
    assert spec.min_occupations == 2


# ---------------------------------------------------------------------------
# The 2-field grant, with the first-worker gate satisfied
# ---------------------------------------------------------------------------

def test_grants_two_on_farmland_first_worker():
    """A fresh round (both workers home → first placement) grants up to 2 fields, plus
    the mandatory base plow."""
    s = _own(_state(), 0, "wheel_plow")
    f0 = _num_fields(s, 0)
    assert s.players[0].people_home == s.players[0].people_total   # round start
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="wheel_plow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="wheel_plow"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlow) and top.max_plows == 2 and top.must_preserve_base
    assert _used(s, 0) is True                      # latched on fire
    for _ in range(2):
        commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
        s = step(s, commits[0])
    s = step(s, Stop())                             # pop granted plow
    assert _num_fields(s, 0) == f0 + 2
    # Finish the mandatory base plow + host.
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, [a for a in legal_actions(s) if isinstance(a, CommitPlow)][0])
    s = step(s, Stop())
    s = step(s, Stop())
    assert _num_fields(s, 0) == f0 + 3              # 2 granted + 1 base


def test_grants_two_on_cultivation_first_worker():
    s = _own(_state(), 0, "wheel_plow")
    f0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="cultivation"))
    assert FireTrigger(card_id="wheel_plow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="wheel_plow"))
    top = s.pending_stack[-1]
    assert top.max_plows == 2 and top.must_preserve_base   # cells restricted on Cultivation too
    for _ in range(2):
        commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
        s = step(s, commits[0])
    s = step(s, Stop())
    assert _num_fields(s, 0) == f0 + 2


def test_may_plow_fewer_than_two():
    s = _own(_state(), 0, "wheel_plow")
    f0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, FireTrigger(card_id="wheel_plow"))
    commits = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, commits[0])
    s = step(s, Proceed())                          # finish after one
    s = step(s, Stop())
    assert _num_fields(s, 0) == f0 + 1


# ---------------------------------------------------------------------------
# First-worker gate
# ---------------------------------------------------------------------------

def test_not_offered_on_second_placement():
    """A second-or-later placement (one worker already placed: people_home ==
    people_total − 2 here, i.e. NOT first) does not offer the grant. Simulate a
    3-worker family with one already placed this round."""
    s = _own(_state(), 0, "wheel_plow")
    s = _set_people(s, 0, home=2, total=3)          # 1 of 3 already placed → not first
    s = step(s, PlaceWorker(space="farmland"))      # this placement is the 2nd
    assert FireTrigger(card_id="wheel_plow") not in legal_actions(s)


def test_offered_on_first_of_a_multi_worker_family():
    """A 3-worker family at round start: the first placement DOES offer the grant
    (people_home becomes total − 1 = 2 after the placing worker leaves home)."""
    s = _own(_state(), 0, "wheel_plow")
    s = _set_people(s, 0, home=3, total=3)
    s = step(s, PlaceWorker(space="farmland"))      # first placement → home 3→2 == total−1
    assert FireTrigger(card_id="wheel_plow") in legal_actions(s)


# ---------------------------------------------------------------------------
# Once-per-game gate
# ---------------------------------------------------------------------------

def test_once_per_game_not_offered_after_use():
    """The `used` latch (set on fire) makes the grant a single lifetime use: a later
    first-worker placement does not re-offer it."""
    s = _own(_state(), 0, "wheel_plow")
    # Already used this game.
    p = fast_replace(s.players[0], card_state=CardStore().set("wheel_plow", True))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    s = step(s, PlaceWorker(space="farmland"))      # a fresh first-worker placement
    assert _used(s, 0) is True
    assert FireTrigger(card_id="wheel_plow") not in legal_actions(s)


# ---------------------------------------------------------------------------
# Stranding guard on Farmland
# ---------------------------------------------------------------------------

def test_farmland_not_offered_when_grant_would_strand_base():
    s = _own(_state(), 0, "wheel_plow")
    overrides = {(r, c): Cell(cell_type=CellType.ROOM)
                 for r in range(3) for c in range(5) if (r, c) != (0, 0)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    la = legal_actions(s)
    assert FireTrigger(card_id="wheel_plow") not in la
    assert ChooseSubAction(name="plow") in la


def test_farmland_granted_plow_excludes_stranding_cell():
    s = _own(_state(), 0, "wheel_plow")
    empties = {(0, 0), (0, 1), (0, 3)}
    overrides = {(r, c): (Cell(cell_type=CellType.EMPTY) if (r, c) in empties
                          else Cell(cell_type=CellType.ROOM))
                 for r in range(3) for c in range(5)}
    s = with_grid(s, 0, overrides)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, FireTrigger(card_id="wheel_plow"))
    cells = {(a.row, a.col) for a in legal_actions(s) if isinstance(a, CommitPlow)}
    assert cells == {(0, 0), (0, 1)}


# ---------------------------------------------------------------------------
# Negatives
# ---------------------------------------------------------------------------

def test_not_offered_when_not_owned():
    s = _state()
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="wheel_plow") not in legal_actions(s)


def test_not_offered_to_opponents_use():
    s = _own(_state(), 1, "wheel_plow")
    s = step(s, PlaceWorker(space="cultivation"))   # current_player == 0
    assert FireTrigger(card_id="wheel_plow") not in legal_actions(s)
