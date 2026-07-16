import agricola.cards.kindling_gatherer  # noqa: F401

"""Kindling Gatherer (occupation, E118): "Each time you get food from an
action space, you get 1 additional wood."

Fires as an after-window automatic (Refactor A) on the two food-yielding action
spaces of the 2-player game — Day Laborer and Fishing (user ruling 2026-07-14:
fixed hook list; card-provided food never triggers it). Eligibility reads the
food swept into the player across the take (`taken.food >= 1`). Flat +1 wood per
use, never per unit of food; Fishing must actually hold food. (The separate
Sugar Baker deposit stays a before-window auto — that food is on the non-atomic
Grain Utilization space, not an atomic take, so there is no `taken` to read.)
"""
import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD = "kindling_gatherer"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=(), minors=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations),
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_fishing(state, amount):
    sp = get_space(state.board, "fishing")
    return fast_replace(state, board=with_space(
        state.board, "fishing", fast_replace(sp, accumulated_amount=amount)))


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, Proceed (primary effect), Stop."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    from agricola.cards.specs import OCCUPATIONS
    assert CARD in OCCUPATIONS
    # The main "food from a space" reward is an AFTER-window auto (reads taken.food).
    after_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert CARD in after_ids
    # The Sugar Baker deposit interaction stays a BEFORE-window auto.
    before_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD in before_ids
    # Hooks both atomic food spaces (subset checks, never exact-set).
    assert CARD in OWN_ACTION_HOOK_CARDS["day_laborer"]
    assert CARD in OWN_ACTION_HOOK_CARDS["fishing"]


def test_hosting_decision():
    s = _own(_card_state(), 0, occupations=(CARD,))
    assert should_host_space(s, "day_laborer", 0)
    assert should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "forest", 0)
    assert not should_host_space(s, "day_laborer", 1)   # opponent doesn't own it


# ---------------------------------------------------------------------------
# The effect, through the real engine flow
# ---------------------------------------------------------------------------

def test_plus_one_wood_on_fishing():
    s = _own(_card_state(), 0, occupations=(CARD,))
    s = fast_replace(s, current_player=0)
    accumulated = get_space(s.board, "fishing").accumulated_amount
    assert accumulated >= 1                              # round-1 refill
    before_food = s.players[0].resources.food
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "fishing")
    assert out.players[0].resources.food == before_food + accumulated
    assert out.players[0].resources.wood == before_wood + 1


def test_plus_one_wood_on_day_laborer():
    s = _own(_card_state(), 0, occupations=(CARD,))
    s = fast_replace(s, current_player=0)
    before_food = s.players[0].resources.food
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "day_laborer")
    assert out.players[0].resources.food == before_food + 2   # Day Laborer's 2 food
    assert out.players[0].resources.wood == before_wood + 1


def test_exactly_one_wood_not_per_food_unit():
    # Fishing stocked with 3 food → still exactly +1 wood.
    s = _own(_card_state(), 0, occupations=(CARD,))
    s = fast_replace(s, current_player=0)
    s = _set_fishing(s, 3)
    before_food = s.players[0].resources.food
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "fishing")
    assert out.players[0].resources.food == before_food + 3
    assert out.players[0].resources.wood == before_wood + 1


def test_no_wood_when_fishing_empty():
    # Fishing holding 0 food yields no food → the card pays nothing.
    s = _own(_card_state(), 0, occupations=(CARD,))
    s = fast_replace(s, current_player=0)
    s = _set_fishing(s, 0)
    before_wood = s.players[0].resources.wood
    out = _play_hosted_space(s, "fishing")   # still hosted (card owned), auto ineligible
    assert out.players[0].resources.wood == before_wood


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space,gain", [("forest", "wood"), ("grain_seeds", "grain")])
def test_nothing_on_non_food_spaces(space, gain):
    # Forest / Grain Seeds aren't hooked → atomic path, no host, no extra wood.
    s = _own(_card_state(), 0, occupations=(CARD,))
    s = fast_replace(s, current_player=0)
    before_wood = s.players[0].resources.wood
    out = step(s, PlaceWorker(space=space))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    expected = before_wood + (get_space(s.board, "forest").accumulated.wood
                              if space == "forest" else 0)
    assert out.players[0].resources.wood == expected


def test_opponent_use_pays_nothing():
    # Player 0 owns the card; player 1 uses Fishing → atomic path, no wood anywhere.
    s = _own(_card_state(), 0, occupations=(CARD,))
    s = fast_replace(s, current_player=1)
    p0_wood = s.players[0].resources.wood
    p1_wood = s.players[1].resources.wood
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == p0_wood
    assert out.players[1].resources.wood == p1_wood


def test_hand_only_card_is_inert():
    # In hand (not played) → no hosting, no wood.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations | {CARD})
    s = fast_replace(s, players=(p, s.players[1]), current_player=0)
    assert not should_host_space(s, "fishing", 0)
    before_wood = s.players[0].resources.wood
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == before_wood


def test_sugar_baker_deposit_pays_wood_at_grain_utilization():
    """The hard-coded Sugar Baker interaction (user-approved 2026-07-14): the
    deposit Sugar Baker placed on Grain Utilization is food ON the space, so
    the next visitor who owns Kindling Gatherer gets +1 wood — read via the
    order=-1 auto before Sugar Baker's collection clears the debt."""
    import agricola.cards.sugar_baker  # noqa: F401
    from agricola.actions import PlaceWorker
    from agricola.engine import step
    from agricola.replace import fast_replace
    from agricola.resources import Resources
    from agricola.setup import CardPool, setup_env
    from agricola.state import get_space, with_space

    pool = CardPool(occupations=("kindling_gatherer", "sugar_baker")
                    + tuple(f"o{i}" for i in range(18)),
                    minors=tuple(f"m{i}" for i in range(20)))
    cs, _env = setup_env(0, card_pool=pool)
    cp = cs.current_player
    opp = 1 - cp
    # The OPPONENT owns Sugar Baker with an outstanding deposit; the acting
    # player owns Kindling Gatherer and visits Grain Utilization.
    p_act = fast_replace(cs.players[cp],
                         occupations=cs.players[cp].occupations | {"kindling_gatherer"},
                         resources=cs.players[cp].resources + Resources(grain=1))
    p_opp = fast_replace(cs.players[opp],
                         occupations=cs.players[opp].occupations | {"sugar_baker"})
    p_opp = fast_replace(p_opp, card_state=p_opp.card_state.set("sugar_baker_owed", 1))
    cs = fast_replace(cs, players=tuple(p_act if i == cp else p_opp for i in range(2)))
    sp = fast_replace(get_space(cs.board, "grain_utilization"),
                      revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "grain_utilization", sp))
    wood0 = cs.players[cp].resources.wood
    food0 = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="grain_utilization"))

    # At the host push: the deposit food was collected AND the wood paid.
    assert cs.players[cp].resources.food == food0 + 1
    assert cs.players[cp].resources.wood == wood0 + 1
    assert cs.players[opp].card_state.get("sugar_baker_owed", 0) == 0


def test_no_wood_at_grain_utilization_without_deposit():
    import agricola.cards.sugar_baker  # noqa: F401
    from agricola.actions import PlaceWorker
    from agricola.engine import step
    from agricola.replace import fast_replace
    from agricola.resources import Resources
    from agricola.setup import CardPool, setup_env
    from agricola.state import get_space, with_space

    pool = CardPool(occupations=("kindling_gatherer",) + tuple(f"o{i}" for i in range(19)),
                    minors=tuple(f"m{i}" for i in range(20)))
    cs, _env = setup_env(0, card_pool=pool)
    cp = cs.current_player
    p_act = fast_replace(cs.players[cp],
                         occupations=cs.players[cp].occupations | {"kindling_gatherer"},
                         resources=cs.players[cp].resources + Resources(grain=1))
    cs = fast_replace(cs, players=tuple(p_act if i == cp else cs.players[i] for i in range(2)))
    sp = fast_replace(get_space(cs.board, "grain_utilization"),
                      revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "grain_utilization", sp))
    wood0 = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="grain_utilization"))
    assert cs.players[cp].resources.wood == wood0
