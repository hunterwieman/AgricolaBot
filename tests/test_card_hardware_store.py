"""Hardware Store (minor C82): "Each time after you use the 'Day Laborer' action
space, you can pay 2 food total to buy 1 wood, 1 clay, 1 reed, and 1 stone."

An optional, paid `after_action_space` trigger on the atomic Day Laborer space (so it
needs the action-space host hook), routing its 2-food cost through the shared
liquidation path (FOOD_PAYMENT_DESIGN.md §8/§9) and granting flat goods.

Covered: registration; the host hook on Day Laborer; the after-phase FireTrigger drive
(direct pay + via-liquidation); the goods grant (+1 each wood/clay/reed/stone for 2
food); eligibility gating only on 2-food payability (offered when liquidatable, not when
truly unaffordable); optionality (decline via Stop, no goods); once-per-use scoping; the
Family-game inertness (no card points).
"""
import agricola.cards.hardware_store  # noqa: F401

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.agents.base import RandomAgent, play_game
from agricola.cards.specs import MINORS, FOOD_PAYMENT_RESUMES
from agricola.cards.triggers import CARDS, TRIGGERS, should_host_space
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingFoodPayment
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("hardware_store",) + tuple(f"m{i}" for i in range(20)),
)

CARD_ID = "hardware_store"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost.resources == Resources(wood=1, clay=1)
    # The trigger is registered on after_action_space and as a food-payment resume.
    assert CARD_ID in CARDS
    assert CARDS[CARD_ID].event == "after_action_space"
    assert any(e.card_id == CARD_ID for e in TRIGGERS["after_action_space"])
    assert CARD_ID in FOOD_PAYMENT_RESUMES


def test_hosts_day_laborer():
    s, _env = setup_env(5, card_pool=_POOL)
    s = _own_minor(s, 0, CARD_ID)
    # Owner's Day Laborer placement is hosted; a non-owner's is not.
    assert should_host_space(s, "day_laborer", 0)
    assert not should_host_space(s, "day_laborer", 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _day_laborer_after_phase(seed=5, *, food=0, grain=0, own=True):
    """Card-mode state: P0 active, (optionally) owning Hardware Store, driven through a
    Day Laborer placement to the after-phase where the after_action_space trigger is
    surfaced."""
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    if own:
        s = _own_minor(s, 0, CARD_ID)
    s = with_resources(s, 0, food=food, grain=grain)
    s = step(s, PlaceWorker(space="day_laborer"))
    # before-phase singleton [Proceed] applies the +2 food primary, flips to after.
    s = step(s, Proceed())
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "after"
    return s


# ---------------------------------------------------------------------------
# Eligibility gating (only the 2-food payment gates)
# ---------------------------------------------------------------------------

def test_offered_when_food_on_hand():
    s = _day_laborer_after_phase(food=2)   # plus the +2 from Day Laborer = 4 on hand
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_offered_via_liquidation_true_shortfall():
    # True shortfall: strip the Day Laborer food bank so 0 food is on hand at the trigger,
    # with 2 grain convertible to the 2 food.  The gate's liquidation branch must offer it.
    s = _day_laborer_after_phase(food=0, grain=2)
    p = fast_replace(s.players[0], resources=fast_replace(s.players[0].resources, food=0))
    s = fast_replace(s, players=(p, s.players[1]))
    assert s.players[0].resources.food == 0          # below the 2-food cost on hand
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_when_unaffordable():
    # < 2 food on hand and nothing convertible (no grain/veg/animals) -> not offered, only Stop.
    s = _day_laborer_after_phase(food=0, grain=0)
    p = fast_replace(s.players[0], resources=fast_replace(s.players[0].resources, food=1))
    s = fast_replace(s, players=(p, s.players[1]))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Stop() in legal_actions(s)


def test_not_offered_when_not_owned():
    # Without owning the card, Day Laborer is not hosted at all: PlaceWorker resolves it
    # atomically (the +2 food applied, no host frame), so there is no after-phase and no
    # trigger is ever surfaced.
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    s = with_resources(s, 0, food=5)
    assert not should_host_space(s, "day_laborer", 0)
    food0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="day_laborer"))
    # Atomic resolution: no host frame pushed; +2 food primary applied; turn done.
    assert all(not isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert s.players[0].resources.food == food0 + 2


# ---------------------------------------------------------------------------
# Effect: direct pay
# ---------------------------------------------------------------------------

def test_direct_pay_grants_goods():
    s = _day_laborer_after_phase(food=2)   # +2 from Day Laborer -> 4 food on hand
    r0 = s.players[0].resources
    s = step(s, FireTrigger(card_id=CARD_ID))
    # No food-payment frame needed; goods granted directly, back in after-phase.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    r1 = s.players[0].resources
    assert r1.food == r0.food - 2
    assert r1.wood == r0.wood + 1
    assert r1.clay == r0.clay + 1
    assert r1.reed == r0.reed + 1
    assert r1.stone == r0.stone + 1


# ---------------------------------------------------------------------------
# Effect: pay via liquidation
# ---------------------------------------------------------------------------

def test_liquidation_pay_grants_goods():
    from agricola.actions import CommitFoodPayment
    # Strip the Day Laborer food bank so the 2-food cost is a true shortfall raised from grain.
    s = _day_laborer_after_phase(food=0, grain=2)
    p = fast_replace(s.players[0], resources=fast_replace(s.players[0].resources, food=0))
    s = fast_replace(s, players=(p, s.players[1]))
    r0 = s.players[0].resources
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 2 and top.resume_kind == CARD_ID
    # Raise 2 food from 2 grain (no hearth needed for grain).
    want = CommitFoodPayment(grain=2, veg=0, sheep=0, boar=0, cattle=0)
    assert want in legal_actions(s)
    s = step(s, want)
    # Resume grants the goods; back in the after-phase.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    r1 = s.players[0].resources
    assert r1.food == 0          # 0 + 2 raised - 2 paid
    assert r1.grain == r0.grain - 2
    assert r1.wood == r0.wood + 1
    assert r1.clay == r0.clay + 1
    assert r1.reed == r0.reed + 1
    assert r1.stone == r0.stone + 1


# ---------------------------------------------------------------------------
# Optionality + once-per-use scoping
# ---------------------------------------------------------------------------

def test_decline_via_stop_grants_nothing():
    s = _day_laborer_after_phase(food=5)
    r0 = s.players[0].resources
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, Stop())                 # decline: pop the host, no buy
    r1 = s.players[0].resources
    assert r1.food == r0.food
    assert r1.wood == r0.wood
    assert r1.clay == r0.clay


def test_fires_once_per_use():
    s = _day_laborer_after_phase(food=6)
    s = step(s, FireTrigger(card_id=CARD_ID))    # buy once, back in after-phase
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    # Already fired this use: not re-offered even with food to spare; only Stop remains.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Stop() in legal_actions(s)


# ---------------------------------------------------------------------------
# Family-game inertness
# ---------------------------------------------------------------------------

def test_family_game_card_points_zero():
    s, env = setup_env(9)
    final, _ = play_game(s, (RandomAgent(seed=1), RandomAgent(seed=2)), dealer=env.resolve)
    for i in (0, 1):
        _t, bd = score(final, i)
        assert bd.card_points == 0


def test_kept_minor_scores_printed_vp():
    s = setup(0)
    base, _ = score(s, 0)
    s1 = _own_minor(s, 0, CARD_ID)
    t1, bd1 = score(s1, 0)
    assert bd1.card_points == 1
    assert t1 == base + 1
