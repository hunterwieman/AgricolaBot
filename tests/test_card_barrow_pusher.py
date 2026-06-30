"""Tests for Barrow Pusher (occupation, A105; Artifex Expansion).

Card text: "For each new field tile you get, you also get 1 clay and 1 food."

Implemented as an `after_plow` automatic effect: every PendingPlow commit (one
per field tile acquired) gives the plowing player +1 clay +1 food. Drives the
reward through the real engine plow flow (Farmland / Cultivation placement →
ChooseSubAction("plow") → CommitPlow), not by poking frames.
"""
import agricola.cards.barrow_pusher  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlow, PlaceWorker, Proceed, Stop
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    """A card-mode round-1 WORK state."""
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _plow_via_farmland(state, row, col):
    """One full Farmland plow turn (place → choose plow → commit → pop both)."""
    return run_actions(state, [
        PlaceWorker(space="farmland"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=row, col=col),
        Stop(),   # pop PendingPlow's after-phase
        Stop(),   # pop the parent
    ])


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registers_after_plow_auto():
    ids = [e.card_id for e in AUTO_EFFECTS.get("after_plow", ())]
    assert "barrow_pusher" in ids


# --------------------------------------------------------------------------- #
# The effect via a real plow flow
# --------------------------------------------------------------------------- #

def test_plow_gives_clay_and_food():
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("barrow_pusher",))
    before = s.players[0].resources

    s = _plow_via_farmland(s, 0, 2)

    # The plowed cell became a FIELD, and the owner gained exactly +1 clay +1 food.
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD
    assert s.players[0].resources.clay == before.clay + 1
    assert s.players[0].resources.food == before.food + 1


def test_two_field_tiles_give_two_rewards():
    """The card is per FIELD TILE, not per action — two plowed fields = +2 clay +2 food.

    Two separate plow actions (Farmland, then Cultivation) each take one field tile
    and fire after_plow once, so the reward accrues per field, not per turn.
    """
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("barrow_pusher",))
    # Reveal Cultivation so a second plow placement is legal in round 1.
    s = fast_replace(s, board=with_space(s.board, "cultivation", fast_replace(
        get_space(s.board, "cultivation"), revealed=True)))
    before = s.players[0].resources

    s = _plow_via_farmland(s, 0, 2)
    # Reset to player 0 for a second placement (Farmland is occupied now); plow a
    # second field via Cultivation to take another field tile.
    s = fast_replace(s, current_player=0)
    s = run_actions(s, [
        PlaceWorker(space="cultivation"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=3),
        Stop(),      # pop PendingPlow's after-phase
        Proceed(),   # flip the Cultivation parent to its after-phase
        Stop(),      # pop the parent
    ])

    assert s.players[0].resources.clay == before.clay + 2
    assert s.players[0].resources.food == before.food + 2


# --------------------------------------------------------------------------- #
# Eligibility boundaries
# --------------------------------------------------------------------------- #

def test_non_owner_plow_gives_nothing():
    """A player who does NOT own the card gets no bonus from their own plow."""
    s = fast_replace(_card_state(), current_player=0)
    # Player 0 does NOT own barrow_pusher.
    before = s.players[0].resources

    s = _plow_via_farmland(s, 0, 2)

    assert s.players[0].resources.clay == before.clay
    assert s.players[0].resources.food == before.food


def test_only_plowing_owner_is_rewarded():
    """Owner-gated (any_player=False): only the player who actually plows is paid.

    Player 1 owns Barrow Pusher; player 0 (a non-owner) plows. Neither should gain:
    player 0 isn't an owner, and player 1 didn't act.
    """
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 1, occupations=("barrow_pusher",))
    p0_before = s.players[0].resources
    p1_before = s.players[1].resources

    s = _plow_via_farmland(s, 0, 2)

    assert s.players[0].resources == p0_before
    assert s.players[1].resources == p1_before


def test_no_plow_no_reward():
    """A non-plow turn (placing on a different space) gives no bonus."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("barrow_pusher",))
    before = s.players[0].resources

    # Forest is an atomic wood-accumulation space — no plow, no field tile.
    s = step(s, PlaceWorker(space="forest"))
    while s.pending_stack:
        s = step(s, Stop())

    assert s.players[0].resources.clay == before.clay
    assert s.players[0].resources.food == before.food
