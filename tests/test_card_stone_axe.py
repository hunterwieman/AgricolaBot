import agricola.cards.stone_axe  # noqa: F401  (registers the card)

"""Tests for Stone Axe (minor improvement, Ephipparius E75).

Card text: "Each time you use a wood accumulation space, you can return 1 stone to
the general supply to get an additional 3 wood."

An OPTIONAL plain ``before_action_space`` trigger on the (hooked, atomic) Forest
host: a single ``FireTrigger("stone_axe")`` offered when the owner holds >=1 stone,
the host's Proceed as the decline, the host's ``triggers_resolved`` giving
once-per-use. Firing returns 1 stone and grants 3 wood. Covers: registration; the
exchange; the affordability gate (no stone -> no offer); once-per-use; the decline
path; and hand-only inertness.
"""
from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS, should_host_space
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_minors

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("stone_axe",) + tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id="stone_axe")


def _set_resources(state, idx, **kw):
    p = fast_replace(state.players[idx], resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _owned_state(idx=0, **resources):
    s, _env = setup_env(5, card_pool=_POOL)
    s = with_current_player(s, idx)
    s = with_minors(s, idx, frozenset({"stone_axe"}))
    s = _set_resources(s, idx, **resources)
    return s


def _at_forest(idx=0, **resources):
    s = _owned_state(idx=idx, **resources)
    return step(s, PlaceWorker(space="forest")), idx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration_and_hook():
    assert "stone_axe" in MINORS
    spec = MINORS["stone_axe"]
    assert spec.cost == Cost(resources=Resources(wood=1, clay=1))
    assert spec.min_occupations == 2
    assert spec.vps == 1
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert "stone_axe" in bas
    assert "stone_axe" in OWN_ACTION_HOOK_CARDS.get("forest", set())


def test_prereq_two_occupations():
    spec, s = MINORS["stone_axe"], _owned_state(stone=1)
    p1 = fast_replace(s.players[0], occupations=frozenset({"a"}))          # 1
    assert not prereq_met(spec, fast_replace(s, players=(p1, s.players[1])), 0)
    p2 = fast_replace(s.players[0], occupations=frozenset({"a", "b"}))     # 2
    assert prereq_met(spec, fast_replace(s, players=(p2, s.players[1])), 0)


# ---------------------------------------------------------------------------
# The exchange: return 1 stone -> get 3 wood
# ---------------------------------------------------------------------------

def test_offered_and_exchanges_stone_for_wood():
    s, ap = _at_forest(stone=2)
    assert should_host_space(_owned_state(stone=2), "forest", 0)
    assert _FIRE in legal_actions(s)
    before = s.players[ap].resources
    s = step(s, _FIRE)
    after = s.players[ap].resources
    assert after.stone == before.stone - 1
    assert after.wood == before.wood + 3     # the accumulated wood lands at Proceed
    # Nothing else moved.
    for other in ("clay", "reed", "food", "grain", "veg"):
        assert getattr(after, other) == getattr(before, other)


def test_not_offered_without_stone():
    # 0 stone -> the exchange is unaffordable, so the trigger is not offered; the
    # host is still pushed (card owned), so only its Proceed is legal.
    s, ap = _at_forest()   # no stone
    assert legal_actions(s) == [Proceed()]


def test_only_once_per_use():
    s, ap = _at_forest(stone=3)
    s = step(s, _FIRE)
    # Plenty of stone left, but triggers_resolved blocks a second exchange.
    la = legal_actions(s)
    assert not any(isinstance(a, FireTrigger) for a in la)
    assert Proceed() in la


# ---------------------------------------------------------------------------
# Decline path + full lifecycle
# ---------------------------------------------------------------------------

def test_decline_via_proceed_keeps_stone_and_takes_wood():
    s = _owned_state(stone=1)
    accumulated = get_space(s.board, "forest").accumulated.wood
    assert accumulated > 0
    s = step(s, PlaceWorker(space="forest"))
    before = s.players[0].resources
    s = step(s, Proceed())     # decline; Forest still pays its accumulated wood
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack
    after = s.players[0].resources
    assert after.stone == before.stone                 # kept the stone
    assert after.wood == before.wood + accumulated     # only the accumulated wood


def test_fire_then_proceed_takes_accumulated_wood_too():
    s = _owned_state(stone=1)
    accumulated = get_space(s.board, "forest").accumulated.wood
    s = step(s, PlaceWorker(space="forest"))
    before = s.players[0].resources
    s = step(s, _FIRE)          # +3 wood, -1 stone
    s = step(s, Proceed())      # + the accumulated wood
    s = step(s, Stop())
    assert not s.pending_stack
    after = s.players[0].resources
    assert after.stone == before.stone - 1
    assert after.wood == before.wood + 3 + accumulated


def test_hand_only_card_is_inert():
    s, _env = setup_env(5, card_pool=_POOL)
    s = with_current_player(s, 0)
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | frozenset({"stone_axe"}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = _set_resources(s, 0, stone=2)
    assert not should_host_space(s, "forest", 0)
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
