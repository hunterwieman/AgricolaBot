"""Tests for Cultivator (occupation, D104; Consul Dirigens Expansion).

Card text: "For each new field tile you get, you also get 1 wood and 1 food."

Implemented as an `after_plow` automatic effect: every PendingPlow commit (one
per field tile acquired) gives the plowing player +1 wood +1 food. Drives the
reward through the real engine plow flow (Farmland / Cultivation placement →
ChooseSubAction("plow") → CommitPlow), not by poking frames.
"""
import agricola.cards.cultivator  # noqa: F401  (registers the card)

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
    assert "cultivator" in ids


# --------------------------------------------------------------------------- #
# The effect via a real plow flow
# --------------------------------------------------------------------------- #

def test_plow_gives_wood_and_food():
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("cultivator",))
    before = s.players[0].resources

    s = _plow_via_farmland(s, 0, 2)

    # The plowed cell became a FIELD, and the owner gained exactly +1 wood +1 food.
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD
    assert s.players[0].resources.wood == before.wood + 1
    assert s.players[0].resources.food == before.food + 1


def test_two_field_tiles_give_two_rewards():
    """The card is per FIELD TILE, not per action — two plowed fields = +2 wood +2 food.

    Two separate plow actions (Farmland, then Cultivation) each take one field tile
    and fire after_plow once, so the reward accrues per field, not per turn.
    """
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("cultivator",))
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

    assert s.players[0].resources.wood == before.wood + 2
    assert s.players[0].resources.food == before.food + 2


# --------------------------------------------------------------------------- #
# Eligibility boundaries
# --------------------------------------------------------------------------- #

def test_non_owner_plow_gives_nothing():
    """A player who does NOT own the card gets no bonus from their own plow."""
    s = fast_replace(_card_state(), current_player=0)
    # Player 0 does NOT own cultivator.
    before = s.players[0].resources

    s = _plow_via_farmland(s, 0, 2)

    assert s.players[0].resources.wood == before.wood
    assert s.players[0].resources.food == before.food


def test_only_plowing_owner_is_rewarded():
    """Owner-gated (any_player=False): only the player who actually plows is paid.

    Player 1 owns Cultivator; player 0 (a non-owner) plows. Neither should gain:
    player 0 isn't an owner, and player 1 didn't act.
    """
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 1, occupations=("cultivator",))
    p0_before = s.players[0].resources
    p1_before = s.players[1].resources

    s = _plow_via_farmland(s, 0, 2)

    assert s.players[0].resources == p0_before
    assert s.players[1].resources == p1_before


def test_no_plow_no_reward():
    """A non-plow turn (placing on a different space) gives no bonus."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("cultivator",))
    before = s.players[0].resources

    # Clay Pit is an atomic clay-accumulation space — no plow, no field tile
    # (and unlike Forest, it grants neither wood nor food, the card's rewards).
    s = step(s, PlaceWorker(space="clay_pit"))
    while s.pending_stack:
        s = step(s, Stop())

    assert s.players[0].resources.wood == before.wood
    assert s.players[0].resources.food == before.food


def test_multishot_granted_plow_pays_per_tile():
    """A multi-shot granted plow (Wheel/Swing/Turnwrest shape: one PendingPlow,
    max_plows=2, ONE after_plow flip) must pay per TILE, not per flip — the
    2026-07-14 per-tile fix."""
    from agricola.actions import CommitPlow
    from agricola.pending import PendingPlow
    from agricola.replace import fast_replace
    from agricola.setup import setup
    from agricola.engine import step
    from agricola.legality import legal_actions
    from tests.factories import with_pending_stack

    s = setup(0)
    p = fast_replace(s.players[0], occupations=frozenset({"cultivator"}))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    s = with_pending_stack(s, (PendingPlow(
        player_idx=0, initiated_by_id="card:test_grant", max_plows=2),))
    wood0 = s.players[0].resources.wood
    food0 = s.players[0].resources.food

    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])          # budget spent -> deferred flip fires the auto

    assert s.players[0].resources.wood == wood0 + 2
    assert s.players[0].resources.food == food0 + 2
