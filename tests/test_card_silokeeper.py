import agricola.cards.silokeeper  # noqa: F401  (registers the card)

"""Tests for Silokeeper (occupation, Bubulcus B112).

Card text: "Each time you use the action space card that has been revealed right
before the most recent harvest, you also get 1 grain."
Clarification: "The action space card is Round 4, 7, 9, 11, or 13."

A ``before_action_space`` automatic effect that fires on the single space whose
``revealed_round`` equals the most-recent-completed harvest round
(max of {4,7,9,11,13} strictly below the current round). Covers: the target-round
boundary logic; the +1 grain on the target across its active rounds; no grain
off-target or before any harvest; the atomic-hook case (Vegetable Seeds); and the
not-owned no-op.
"""
import pytest

from agricola.actions import PlaceWorker
from agricola.cards.silokeeper import _HARVEST_REVEAL_ROUNDS, _target_reveal_round
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_round, with_space

_POOL = CardPool(
    occupations=("silokeeper",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return with_current_player(s, 0)


def _own(state, idx=0):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {"silokeeper"})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration + the target-round boundary logic
# ---------------------------------------------------------------------------

def test_registration_and_hook():
    assert "silokeeper" in OCCUPATIONS
    autos = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert "silokeeper" in autos
    assert _HARVEST_REVEAL_ROUNDS == (4, 7, 9, 11, 13)   # 14 excluded
    for atomic in ("western_quarry", "vegetable_seeds", "eastern_quarry",
                   "urgent_wish_for_children"):
        assert "silokeeper" in OWN_ACTION_HOOK_CARDS.get(atomic, set())


@pytest.mark.parametrize("round_number,target", [
    (1, None), (2, None), (3, None), (4, None),   # no completed harvest yet
    (5, 4), (6, 4), (7, 4),                        # round-4 card is the target
    (8, 7), (9, 7),                                # round-7 card
    (10, 9), (11, 9),                              # round-9 card
    (12, 11), (13, 11),                            # round-11 card
    (14, 13),                                      # round-13 card
])
def test_target_reveal_round(round_number, target):
    assert _target_reveal_round(round_number) == target


# ---------------------------------------------------------------------------
# The +1 grain on the target space (a round-4 card, via Sheep Market)
# ---------------------------------------------------------------------------

def _sheep_market_r4(round_number):
    """Sheep Market as the round-4 card, at the given current round; owned."""
    s = with_space(_state(), "sheep_market", revealed=True,
                   revealed_round=4, accumulated_amount=1)
    return _own(with_round(s, round_number))


@pytest.mark.parametrize("round_number", [5, 6, 7])
def test_grants_grain_on_target_across_active_rounds(round_number):
    s = _sheep_market_r4(round_number)
    before = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.grain == before + 1


def test_no_grain_once_target_advances():
    # By round 8 the target is the round-7 card; the round-4 Sheep Market is stale.
    s = _sheep_market_r4(8)
    before = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.grain == before


def test_no_grain_before_any_harvest():
    # Round 4: no harvest has completed -> no target -> no grain.
    s = _sheep_market_r4(4)
    before = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.grain == before


# ---------------------------------------------------------------------------
# Atomic target: Vegetable Seeds as the round-9 card (exercises the hook)
# ---------------------------------------------------------------------------

def test_grants_grain_on_atomic_target_vegetable_seeds():
    s = with_space(_state(), "vegetable_seeds", revealed=True, revealed_round=9)
    s = _own(with_round(s, 10))     # round 10 -> target is the round-9 card
    before = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="vegetable_seeds"))
    # Hooked -> hosted; the before-auto fired at the push (+1 grain). The veg from
    # the space lands later at Proceed, so grain is isolated here.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[0].resources.grain == before + 1


def test_not_owned_no_grain():
    s = with_space(_state(), "sheep_market", revealed=True,
                   revealed_round=4, accumulated_amount=1)
    s = with_round(s, 5)     # target is the round-4 card, but nobody owns Silokeeper
    before = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.grain == before
