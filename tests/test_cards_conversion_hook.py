"""Tests for Category 10 (bounded-hook wood->food conversion): Mushroom Collector
and Basket. These are OPTIONAL FireTriggers on a wood space's after_action_space
phase, with the faithful "place the exchanged wood back on the accumulation space"
clause (the spent wood returns to Forest, not the general supply).

Exercises the optional-trigger path of the atomic action-space host (step 4a) with
real cards, including decline (Stop without firing), the once-per-use gate, and
the wood-return board mutation.
"""
from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state_owning(card_id, *, occupation=True, forest_wood=None):
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    p = s.players[0]
    if occupation:
        p = fast_replace(p, occupations=p.occupations | {card_id})
    else:
        p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    s = fast_replace(s, players=(p, s.players[1]))
    if forest_wood is not None:
        sp = get_space(s.board, "forest")
        s = fast_replace(s, board=with_space(s.board, "forest",
                                             fast_replace(sp, accumulated=Resources(wood=forest_wood))))
    return s


def _place_and_proceed(state):
    """Place on Forest and Proceed; return the after-phase state (host on top)."""
    state = step(state, PlaceWorker(space="forest"))
    state = step(state, Proceed())
    return state


def test_mushroom_collector_exchange_and_wood_return():
    s = _state_owning("mushroom_collector", forest_wood=3)
    w0 = s.players[0].resources.wood
    f0 = s.players[0].resources.food
    s = _place_and_proceed(s)
    # Took 3 accumulated wood; the after-phase offers the optional exchange + Stop.
    assert s.players[0].resources.wood == w0 + 3
    la = legal_actions(s)
    assert FireTrigger(card_id="mushroom_collector") in la
    assert Stop() in la

    s = step(s, FireTrigger(card_id="mushroom_collector"))
    assert s.players[0].resources.wood == w0 + 3 - 1     # spent 1 wood
    assert s.players[0].resources.food == f0 + 2         # gained 2 food
    # The spent wood went back onto Forest (Proceed had emptied it).
    assert get_space(s.board, "forest").accumulated.wood == 1
    # Once per use: no longer offered.
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack


def test_mushroom_collector_decline_leaves_state_unchanged():
    s = _state_owning("mushroom_collector", forest_wood=3)
    w0 = s.players[0].resources.wood
    f0 = s.players[0].resources.food
    s = _place_and_proceed(s)
    # Decline: Stop without firing — no exchange, no wood returned.
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.players[0].resources.wood == w0 + 3
    assert s.players[0].resources.food == f0
    assert get_space(s.board, "forest").accumulated.wood == 0


def test_basket_exchange_two_wood_for_three_food():
    s = _state_owning("basket", occupation=False, forest_wood=4)
    w0 = s.players[0].resources.wood
    f0 = s.players[0].resources.food
    s = _place_and_proceed(s)
    s = step(s, FireTrigger(card_id="basket"))
    assert s.players[0].resources.wood == w0 + 4 - 2
    assert s.players[0].resources.food == f0 + 3
    assert get_space(s.board, "forest").accumulated.wood == 2
    s = step(s, Stop())
    assert not s.pending_stack


def test_basket_not_offered_without_enough_wood():
    # Forest holds only 1 wood and the player has none → after Proceed wood == 1 < 2.
    s = _state_owning("basket", occupation=False, forest_wood=1)
    s = fast_replace(s, players=(
        fast_replace(s.players[0], resources=fast_replace(s.players[0].resources, wood=0)),
        s.players[1]))
    s = _place_and_proceed(s)
    assert s.players[0].resources.wood == 1
    assert legal_actions(s) == [Stop()]                  # Basket ineligible (needs 2)
