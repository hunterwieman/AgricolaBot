import agricola.cards.barn_shed  # noqa: F401  (registers the card)

"""Tests for Barn Shed (minor improvement, Ephipparius E66).

Card text: "Each time another player (or, in a solo game, you) uses the 'Forest'
accumulation space, you get 1 grain."

An ``any_player`` automatic effect on ``before_action_space`` that fires for its
OWNER only when the OTHER player uses Forest (own use excluded). Forest is atomic,
hosted via ``register_action_space_hook(..., any_player=True)``. Covers the
opponent-use payout to the owner, the own-use exclusion, and the not-owned no-op.
"""
from agricola.actions import PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    should_host_space,
)
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_minors, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("barn_shed",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    # Ensure Forest is revealed + stocked so either player can use it.
    return with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))


def _own(state, owner):
    return with_minors(state, owner, frozenset({"barn_shed"}))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "barn_shed" in MINORS
    spec = MINORS["barn_shed"]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 3            # "3 Occupations" prereq
    autos = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert "barn_shed" in autos
    # any-player hook on Forest (so the host is pushed on the opponent's turn).
    assert "barn_shed" in ANY_PLAYER_HOOK_CARDS.get("forest", set())


def test_prereq_three_occupations():
    spec, s = MINORS["barn_shed"], _state()
    p = fast_replace(s.players[0], occupations=frozenset({"a", "b"}))       # 2
    s2 = fast_replace(s, players=(p, s.players[1]))
    assert not prereq_met(spec, s2, 0)
    p = fast_replace(s.players[0], occupations=frozenset({"a", "b", "c"}))  # 3
    s3 = fast_replace(s, players=(p, s.players[1]))
    assert prereq_met(spec, s3, 0)


# ---------------------------------------------------------------------------
# The payout: owner gains 1 grain on ANOTHER player's Forest use
# ---------------------------------------------------------------------------

def test_owner_gains_grain_on_opponents_forest_use():
    # P0 owns Barn Shed; P1 (active) uses Forest.
    s = with_current_player(_own(_state(), 0), 1)
    assert should_host_space(s, "forest", 1)     # hosted on the opponent's turn
    g0, g1 = s.players[0].resources.grain, s.players[1].resources.grain
    s = step(s, PlaceWorker(space="forest"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    # Fires for the OWNER (P0 +1 grain); the acting player (P1) gains nothing.
    assert s.players[0].resources.grain == g0 + 1
    assert s.players[1].resources.grain == g1


def test_no_payout_on_owners_own_forest_use():
    # P0 owns Barn Shed and uses Forest itself -> "another player" excludes it.
    s = with_current_player(_own(_state(), 0), 0)
    g0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="forest"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)   # still hosted...
    assert s.players[0].resources.grain == g0                    # ...but no grain


def test_not_owned_no_payout():
    # Neither player owns it -> Forest stays atomic, no grain for anyone.
    s = with_current_player(_state(), 1)
    g0, g1 = s.players[0].resources.grain, s.players[1].resources.grain
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[0].resources.grain == g0
    assert s.players[1].resources.grain == g1
