"""Tests for Wood Cart (minor C76, Corbarius).

Card text: "Each time you use a wood accumulation space, you get 2 additional wood."
Cost 3 Wood; prereq 3 Occupations; no VP; not passing.

The +2 wood is a `before_action_space` automatic effect on the `forest` space (the
only wood accumulation space on the 2-player board). `forest` is atomic, so the
card hosts it. The "3 Occupations" prerequisite is a play-time HAVE-check on the
owner's occupation count (min_occupations=3), never spent.
"""
import agricola.cards.wood_cart  # noqa: F401  (registers the card; not in cards/__init__.py)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space

CARD_ID = "wood_cart"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own(state, idx, *, occupations=(), minors=(CARD_ID,)):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations),
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=3))
    assert spec.min_occupations == 3       # "3 Occupations" prerequisite
    assert spec.vps == 0
    assert spec.passing_left is False


def test_registered_as_before_hook_on_forest():
    # Hosts the forest space (atomic), and the auto effect is on before_action_space.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["forest"]
    events = {event for event, entries in AUTO_EFFECTS.items()
              if any(e.card_id == CARD_ID for e in entries)}
    assert events == {"before_action_space"}


def test_auto_effect_is_owner_only_not_any_player():
    # "each time YOU use" — must fire for the acting owner only (any_player=False).
    entries = [e for e in AUTO_EFFECTS["before_action_space"] if e.card_id == CARD_ID]
    assert len(entries) == 1
    assert entries[0].any_player is False


# ---------------------------------------------------------------------------
# 3-occupation prerequisite (play-time gate)
# ---------------------------------------------------------------------------

def test_prereq_requires_three_occupations():
    spec = MINORS[CARD_ID]
    s = _card_state()
    # 0 occupations → prereq fails.
    assert not prereq_met(spec, s, 0)
    # exactly 2 → still fails (< 3).
    s2 = _own(s, 0, occupations=("oa", "ob"))
    assert not prereq_met(spec, s2, 0)
    # exactly 3 → met.
    s3 = _own(s, 0, occupations=("oa", "ob", "oc"))
    assert prereq_met(spec, s3, 0)
    # 4 → still met (it is a >= bound).
    s4 = _own(s, 0, occupations=("oa", "ob", "oc", "od"))
    assert prereq_met(spec, s4, 0)


# ---------------------------------------------------------------------------
# The effect via a real forest placement
# ---------------------------------------------------------------------------

def test_grants_two_extra_wood_on_forest():
    s = _own(_card_state(), 0)
    accumulated = get_space(s.board, "forest").accumulated.wood
    assert accumulated > 0                       # forest has wood waiting
    before_wood = s.players[0].resources.wood

    # Drive the hosted lifecycle: place → before-phase (auto fires) → Proceed → Stop.
    s = step(s, PlaceWorker(space="forest"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    # The +2 wood is a choiceless auto applied at hosting → before-phase is a
    # singleton Proceed (no FireTrigger surfaced).
    assert legal_actions(s) == [Proceed()]
    s = step(s, Proceed())
    s = step(s, Stop())
    assert not s.pending_stack

    # The normal forest take PLUS the card's +2 wood.
    assert s.players[0].resources.wood == before_wood + accumulated + 2


def test_does_not_fire_on_non_wood_accumulation_space():
    # Clay Pit / Reed Bank etc. are accumulation spaces but NOT wood spaces.
    s = _own(_card_state(), 0)
    before_wood = s.players[0].resources.wood
    accumulated_clay = get_space(s.board, "clay_pit").accumulated.clay

    out = step(s, PlaceWorker(space="clay_pit"))
    # wood_cart does not hook clay_pit → atomic fast path, no host frame.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    # Player gains the clay (not wood); no +2 wood from the card.
    assert out.players[0].resources.wood == before_wood
    assert out.players[0].resources.clay == s.players[0].resources.clay + accumulated_clay


# ---------------------------------------------------------------------------
# Hosting / ownership scoping
# ---------------------------------------------------------------------------

def test_should_host_forest_only_when_owned():
    s = _card_state()
    assert not should_host_space(s, "forest", 0)         # not owned yet
    s = _own(s, 0)
    assert should_host_space(s, "forest", 0)             # owned → hosts forest
    assert not should_host_space(s, "clay_pit", 0)       # but not other wood-less spaces


def test_does_not_fire_for_non_owner():
    # P1 owns Wood Cart; P0 (who does not own it) uses the forest → no +2 wood.
    s = _own(_card_state(), 1)
    before_wood_p0 = s.players[0].resources.wood
    accumulated = get_space(s.board, "forest").accumulated.wood

    # P0 placing on forest is NOT hosted (P0 doesn't own the card, P1's hook is
    # own-action only, not any_player) → atomic fast path.
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == before_wood_p0 + accumulated  # no +2
