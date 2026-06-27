"""Tests for the atomic action-space host hook (CARD_IMPLEMENTATION_PLAN.md II.2,
build-order step 4a) and the first cards that use it (Category 3 automatic income).

The hook hosts an otherwise-atomic space (Forest, Grain Seeds, quarries, …) with a
generic PendingActionSpace frame ONLY when a card could fire there, then runs the
lifecycle before-auto/triggers → Proceed (primary effect) → after-auto/triggers →
Stop. The Family game never owns such a card, so the host frame is never pushed and
play is byte-identical (covered by the C++ differential gates; an explicit check
here too).

Cards exercised: Wood Cutter (occ, +1 wood @ Forest), Geologist (occ, +1 clay @
Forest/Reed Bank), Corn Scoop (minor, +1 grain @ Grain Seeds), Stone Tongs (minor,
+1 stone @ quarries), Pitchfork (minor, conditional +3 food @ Grain Seeds).
"""
import pytest

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards import triggers
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    """A card-mode round-1 WORK state."""
    s, env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=(), minors=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations),
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _occupy(state, space_id, player=1):
    """Mark `space_id` occupied (for Pitchfork's Farmland-occupied condition)."""
    sp = get_space(state.board, space_id)
    workers = (0, 1) if player == 1 else (1, 0)
    from agricola.state import with_space
    return fast_replace(state, board=with_space(state.board, space_id,
                                                fast_replace(sp, workers=workers)))


def test_all_action_space_host_frames_expose_space_id():
    """CONTRACT: every action-space host frame (PENDING_ID in
    ACTION_SPACE_PENDING_IDS) must expose a `space_id` property.

    18 cards read `state.pending_stack[-1].space_id` in their before/after-
    action_space eligibility WITHOUT an isinstance guard, so a host frame that
    omits the property crashes legal_actions / step for any action-space-hook
    owner — the Meeting Place (seed 11583) and Farm Expansion / House
    Redevelopment (seed 63519) web locks. This introspects EVERY host frame, so
    it catches all current and future omissions at once."""
    import dataclasses
    import inspect

    import agricola.pending as P
    from agricola.legality import ACTION_SPACE_PENDING_IDS

    offenders = []
    for name, obj in vars(P).items():
        if not (inspect.isclass(obj) and dataclasses.is_dataclass(obj)):
            continue
        pid = getattr(obj, "PENDING_ID", None)
        fields = {f.name for f in dataclasses.fields(obj)}
        if pid in ACTION_SPACE_PENDING_IDS and "initiated_by_id" in fields:
            if not isinstance(inspect.getattr_static(obj, "space_id", None), property):
                offenders.append(name)
    assert not offenders, f"action-space host frames missing space_id: {offenders}"


def test_andor_host_with_action_space_hook_owner_no_crash():
    """Regression for the seed-63519 web lock. The player owned Wood Cutter (an
    occupation whose `before_action_space` eligibility reads `top.space_id`).
    Placing on Farm Expansion pushed PendingFarmExpansion — an and/or Proceed-host
    that was missing `space_id` — so firing the before-automatics raised
    AttributeError and the worker placement silently failed (the UI let you click
    Farm Expansion endlessly with no effect). Drives that exact path."""
    from agricola.actions import ChooseSubAction

    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("wood_cutter",))
    # Afford a stable so Farm Expansion is a legal placement.
    p0 = fast_replace(s.players[0], resources=Resources(wood=10, reed=5))
    s = fast_replace(s, players=(p0, s.players[1]))

    assert PlaceWorker(space="farm_expansion") in legal_actions(s)
    s = step(s, PlaceWorker(space="farm_expansion"))   # pre-fix: AttributeError
    acts = legal_actions(s)
    assert any(isinstance(a, ChooseSubAction) for a in acts), acts


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, then auto-skip Proceed and Stop.
    Returns the state after the turn (asserting the singleton lifecycle shape)."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    # No triggers in these automatic-only cases → before-phase is a singleton Proceed.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack            # host popped, turn ended
    return state


# ---------------------------------------------------------------------------
# Hosting decision + Family byte-identity
# ---------------------------------------------------------------------------

def test_should_host_space_false_without_card():
    s = _card_state()
    assert not should_host_space(s, "forest", s.current_player)


def test_should_host_space_true_with_owned_hook_card():
    s = _own(_card_state(), 0, occupations=("wood_cutter",))
    assert should_host_space(s, "forest", 0)
    assert not should_host_space(s, "clay_pit", 0)      # wood_cutter doesn't hook clay_pit


def test_hand_card_does_not_trigger_hosting():
    # A card in HAND (not played) must not host — only played cards fire.
    s = _card_state()
    p = fast_replace(s.players[0], hand_occupations=s.players[0].hand_occupations | {"wood_cutter"})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "forest", 0)


def test_family_forest_not_hosted():
    s = setup(0)
    s = step(s, PlaceWorker(space="forest"))
    # Family: atomic fast path, no host frame, turn already advanced.
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Wood Cutter (occupation) — the canonical automatic effect
# ---------------------------------------------------------------------------

def test_wood_cutter_adds_one_wood_on_forest():
    s = _own(_card_state(), 0, occupations=("wood_cutter",))
    s = fast_replace(s, current_player=0)
    accumulated = get_space(s.board, "forest").accumulated.wood
    before = s.players[0].resources.wood
    out = _play_hosted_space(s, "forest")
    # gained the accumulated wood (Proceed) + 1 (Wood Cutter, before-phase)
    assert out.players[0].resources.wood == before + accumulated + 1


def test_wood_cutter_does_not_fire_on_non_wood_space():
    s = _own(_card_state(), 0, occupations=("wood_cutter",))
    s = fast_replace(s, current_player=0)
    # Clay Pit is not a wood space and wood_cutter doesn't hook it → atomic path.
    before_wood = s.players[0].resources.wood
    accumulated_clay = get_space(s.board, "clay_pit").accumulated.clay
    out = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == before_wood          # no +1 wood
    assert out.players[0].resources.clay == s.players[0].resources.clay + accumulated_clay


# ---------------------------------------------------------------------------
# Geologist (occupation) — multi-space hook
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space", ["forest", "reed_bank"])
def test_geologist_adds_one_clay_on_its_spaces(space):
    s = _own(_card_state(), 0, occupations=("geologist",))
    s = fast_replace(s, current_player=0)
    before_clay = s.players[0].resources.clay
    out = _play_hosted_space(s, space)
    assert out.players[0].resources.clay == before_clay + 1


# ---------------------------------------------------------------------------
# Automatic-income minors
# ---------------------------------------------------------------------------

def test_corn_scoop_adds_grain_on_grain_seeds():
    s = _own(_card_state(), 0, minors=("corn_scoop",))
    s = fast_replace(s, current_player=0)
    before = s.players[0].resources.grain
    out = _play_hosted_space(s, "grain_seeds")
    # Grain Seeds gives 1 grain (primary) + 1 (Corn Scoop)
    assert out.players[0].resources.grain == before + 1 + 1


def test_pitchfork_pays_only_when_farmland_occupied():
    # Farmland free → no payout (atomic-equivalent: just the 1 grain).
    s = _own(_card_state(), 0, minors=("pitchfork",))
    s = fast_replace(s, current_player=0)
    before_food = s.players[0].resources.food
    before_grain = s.players[0].resources.grain
    out = _play_hosted_space(s, "grain_seeds")
    assert out.players[0].resources.food == before_food          # not occupied → no +3
    assert out.players[0].resources.grain == before_grain + 1

    # Farmland occupied → +3 food.
    s2 = _own(_card_state(), 0, minors=("pitchfork",))
    s2 = fast_replace(s2, current_player=0)
    s2 = _occupy(s2, "farmland", player=1)
    bf = s2.players[0].resources.food
    out2 = _play_hosted_space(s2, "grain_seeds")
    assert out2.players[0].resources.food == bf + 3


def test_stone_tongs_adds_stone_on_a_quarry():
    # Quarries are Stage 2/4 spaces (not up at round 1); reveal + stock one.
    from agricola.state import with_space
    s = _own(_card_state(), 0, minors=("stone_tongs",))
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "western_quarry")
    s = fast_replace(s, board=with_space(s.board, "western_quarry",
                                         fast_replace(sp, revealed=True,
                                                      accumulated=Resources(stone=2))))
    before = s.players[0].resources.stone
    out = _play_hosted_space(s, "western_quarry")
    assert out.players[0].resources.stone == before + 2 + 1   # 2 accumulated + 1 Stone Tongs


def test_all_category3_cards_registered():
    from agricola.cards.specs import MINORS, OCCUPATIONS
    for cid in ("wood_cutter", "geologist"):
        assert cid in OCCUPATIONS
    for cid in ("corn_scoop", "stone_tongs", "pitchfork"):
        assert cid in MINORS
    # Each registered an automatic effect on before_action_space and a hosting index.
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    for cid in ("wood_cutter", "geologist", "corn_scoop", "stone_tongs", "pitchfork"):
        assert cid in auto_ids
    assert "wood_cutter" in OWN_ACTION_HOOK_CARDS["forest"]
    assert "stone_tongs" in OWN_ACTION_HOOK_CARDS["western_quarry"]
    assert "stone_tongs" in OWN_ACTION_HOOK_CARDS["eastern_quarry"]


# ---------------------------------------------------------------------------
# Synthetic FireTrigger card — validates the optional-trigger path at the host
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_registries():
    saved = (
        {e: list(v) for e, v in TRIGGERS.items()},
        {e: list(v) for e, v in AUTO_EFFECTS.items()},
        {k: set(v) for k, v in OWN_ACTION_HOOK_CARDS.items()},
        {k: set(v) for k, v in ANY_PLAYER_HOOK_CARDS.items()},
        dict(triggers.CARDS),
    )
    try:
        yield
    finally:
        for reg, snap in ((TRIGGERS, saved[0]), (AUTO_EFFECTS, saved[1]),
                          (OWN_ACTION_HOOK_CARDS, saved[2]), (ANY_PLAYER_HOOK_CARDS, saved[3])):
            reg.clear(); reg.update(snap)
        triggers.CARDS.clear(); triggers.CARDS.update(saved[4])


def test_optional_trigger_surfaces_and_fires_at_host(clean_registries):
    # A test card: optional FireTrigger on before_action_space @ Forest, +5 food.
    def _elig(state, idx, resolved):
        return state.pending_stack[-1].space_id == "forest" and "tcard" not in resolved

    def _apply(state, idx):
        p = fast_replace(state.players[idx],
                         resources=state.players[idx].resources + Resources(food=5))
        return fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))

    triggers.register("before_action_space", "tcard", _elig, _apply)
    triggers.register_action_space_hook("tcard", ("forest",))

    s = _own(_card_state(), 0, occupations=("tcard",))
    s = fast_replace(s, current_player=0)
    before_food = s.players[0].resources.food

    s = step(s, PlaceWorker(space="forest"))
    # before-phase host: the FireTrigger is offered alongside Proceed.
    la = legal_actions(s)
    assert FireTrigger(card_id="tcard") in la
    assert Proceed() in la

    # Fire it → +5 food, recorded in triggers_resolved, no push/pop.
    s = step(s, FireTrigger(card_id="tcard"))
    assert s.players[0].resources.food == before_food + 5
    assert "tcard" in s.pending_stack[-1].triggers_resolved
    # Now it is no longer offered (once per host-visit); only Proceed remains.
    assert legal_actions(s) == [Proceed()]

    s = step(s, Proceed())
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack
