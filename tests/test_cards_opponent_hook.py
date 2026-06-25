"""Tests for Category 9 (opponent-action hook): Milk Jug — the first card that
fires on ANOTHER player's action, via the any-player automatic-effect path on the
non-atomic Cattle Market's after-phase (step 4b).
"""
from agricola.actions import CommitAccommodate, PlaceWorker, Stop
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingCattleMarket
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cattle_market_state(owner_of_milk_jug):
    """Card-mode state with Cattle Market revealed + stocked with 1 cattle, and
    `owner_of_milk_jug` owning Milk Jug. P0 is the active player."""
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "cattle_market")
    s = fast_replace(s, board=with_space(s.board, "cattle_market",
                                         fast_replace(sp, revealed=True, accumulated_amount=1)))
    p = fast_replace(s.players[owner_of_milk_jug],
                     minor_improvements=s.players[owner_of_milk_jug].minor_improvements | {"milk_jug"})
    s = fast_replace(s, players=tuple(
        p if i == owner_of_milk_jug else s.players[i] for i in range(2)))
    return s


def test_milk_jug_fires_on_opponent_cattle_market_use():
    # P1 owns Milk Jug; P0 (active) uses Cattle Market.
    s = _cattle_market_state(owner_of_milk_jug=1)
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food

    s = step(s, PlaceWorker(space="cattle_market"))
    s = step(s, CommitAccommodate(sheep=0, boar=0, cattle=1))   # keep the cattle (house pet)
    # After-phase: Milk Jug fired for its OWNER (P1 +3), the other player (P0) +1.
    assert s.players[1].resources.food == f1 + 3
    assert s.players[0].resources.food == f0 + 1
    assert isinstance(s.pending_stack[-1], PendingCattleMarket)
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack


def test_milk_jug_fires_for_self_when_owner_acts():
    # P0 owns Milk Jug and uses Cattle Market itself ("including you").
    s = _cattle_market_state(owner_of_milk_jug=0)
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food
    s = step(s, PlaceWorker(space="cattle_market"))
    s = step(s, CommitAccommodate(sheep=0, boar=0, cattle=1))
    assert s.players[0].resources.food == f0 + 3   # owner
    assert s.players[1].resources.food == f1 + 1   # the other player


def test_no_milk_jug_no_payout():
    # Neither player owns it -> the after-phase is a bare singleton Stop, no food.
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "cattle_market")
    s = fast_replace(s, board=with_space(s.board, "cattle_market",
                                         fast_replace(sp, revealed=True, accumulated_amount=1)))
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food
    s = step(s, PlaceWorker(space="cattle_market"))
    s = step(s, CommitAccommodate(sheep=0, boar=0, cattle=1))
    assert s.players[0].resources.food == f0
    assert s.players[1].resources.food == f1
    assert legal_actions(s) == [Stop()]
