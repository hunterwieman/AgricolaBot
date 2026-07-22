import agricola.cards.studio  # noqa: F401
# Tests for Studio (minor improvement, C55; Corbarius Expansion).
#
# Card text: "In the feeding phase of each harvest, you can use this card to turn
# exactly 1 wood/clay/stone into 2/2/3 food."
# Cost 1 clay + 1 reed. VPs: 1. No prereq.
#
# Three HarvestConversionSpec entries (studio_wood/clay/stone) — each turns 1 of
# that resource into 2/2/3 food. Used at most once per harvest (a CHOICE of which
# resource, not three independent fires). No banked points; the 1 vp is printed.
#
# Mirrors tests/test_card_beer_keg.py / test_harvest_feed.py's craft-firing flow.

import dataclasses

import agricola.cards.plow_builder   # noqa: F401  (integration-chain trigger)
import agricola.cards.rocky_terrain  # noqa: F401  (integration-chain trigger)

from agricola.actions import (
    CommitConvert,
    CommitFieldTake,
    CommitFoodPayment,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.studio import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    available_span_converters,
    sentinel_position,
)
from agricola.cards.plow_builder import CARD_ID as PLOW_BUILDER, JOINERY_IDX
from agricola.cards.rocky_terrain import CARD_ID as ROCKY_TERRAIN
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, MINORS, prereq_met
from agricola.constants import GameMode, Phase
from agricola.engine import _advance_until_decision, _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestWindow,
    PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState
from agricola.setup import CardPool, setup, setup_env

from tests.factories import (
    with_majors,
    with_minors,
    with_phase,
    with_resources,
)


# --- Helpers ----------------------------------------------------------------

def _feed_state(*, wood=0, clay=0, reed=0, stone=0, food=0, studio=True) -> GameState:
    """A HARVEST_FEED state with player 0 owning Studio, given resources, and
    player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if studio:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, wood=wood, clay=clay, reed=reed, stone=stone, food=food)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _studio_actions(state):
    return sorted(
        (a.conversion_id for a in legal_actions(state)
         if isinstance(a, CommitHarvestConversion) and a.conversion_id.startswith(CARD_ID))
    )


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(clay=1, reed=1)
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.prereq is None
    # Three conversion entries.
    for name in ("wood", "clay", "stone"):
        assert f"{CARD_ID}_{name}" in HARVEST_CONVERSIONS


def test_no_prereq():
    """Studio has no prerequisite — playable at any state (occupation-count
    bounds default to 0/None and no custom predicate)."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert prereq_met(spec, state, 0) is True


def test_conversion_outputs_match_text():
    """Each entry: spend exactly 1 of its resource, produce 2/2/3 food."""
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_wood"].input_cost == Resources(wood=1)
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_wood"].food_out == 2
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_clay"].input_cost == Resources(clay=1)
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_clay"].food_out == 2
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_stone"].input_cost == Resources(stone=1)
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_stone"].food_out == 3
    # No banked-point side effect.
    for name in ("wood", "clay", "stone"):
        assert HARVEST_CONVERSIONS[f"{CARD_ID}_{name}"].side_effect_fn is None


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """Variants offered iff the player owns Studio."""
    owned = _feed_state(wood=1, clay=1, stone=1, studio=True)
    assert _studio_actions(owned) == ["studio_clay", "studio_stone", "studio_wood"]

    unowned = _feed_state(wood=1, clay=1, stone=1, studio=False)
    assert _studio_actions(unowned) == []


def test_offered_variants_gated_by_affordable_resource():
    """Only variants whose single-resource cost is affordable are offered."""
    # Only wood -> only studio_wood.
    assert _studio_actions(_feed_state(wood=1)) == ["studio_wood"]
    # Only stone -> only studio_stone.
    assert _studio_actions(_feed_state(stone=1)) == ["studio_stone"]
    # No building resources -> none affordable.
    assert _studio_actions(_feed_state()) == []
    # wood + clay -> studio_wood, studio_clay (not stone).
    assert _studio_actions(_feed_state(wood=1, clay=1)) == ["studio_clay", "studio_wood"]


# --- Real-flow effect -------------------------------------------------------

def test_fire_wood_variant_spends_wood_adds_two_food():
    state = _feed_state(wood=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="studio_wood"))
    p = state.players[0]
    assert p.resources.wood == 1   # 2 - 1 spent
    assert p.resources.food == 2   # +2 food
    assert "studio_wood" in p.harvest_conversions_used


def test_fire_clay_variant_spends_clay_adds_two_food():
    state = _feed_state(clay=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="studio_clay"))
    p = state.players[0]
    assert p.resources.clay == 1
    assert p.resources.food == 2
    assert "studio_clay" in p.harvest_conversions_used


def test_fire_stone_variant_spends_stone_adds_three_food():
    state = _feed_state(stone=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="studio_stone"))
    p = state.players[0]
    assert p.resources.stone == 1
    assert p.resources.food == 3   # stone yields 3, not 2
    assert "studio_stone" in p.harvest_conversions_used


# --- Once-per-harvest: choosing ONE variant suppresses the others -----------

def test_once_per_harvest_choice():
    """After firing one variant, no studio variant is offered again this harvest
    (a single use, choosing which resource — not three independent fires)."""
    state = _feed_state(wood=5, clay=5, stone=5, food=0)
    assert _studio_actions(state) == ["studio_clay", "studio_stone", "studio_wood"]

    state = step(state, CommitHarvestConversion(conversion_id="studio_wood"))
    # Even though plenty of wood/clay/stone remains, the card is spent this harvest.
    assert _studio_actions(state) == []


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    resources untouched."""
    state = _feed_state(wood=1, clay=1, stone=1, food=10)  # plenty of food
    # CommitConvert with no consumption ends the feed without firing the studio.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.wood == 1
    assert p.resources.clay == 1
    assert p.resources.stone == 1
    assert not any(c.startswith(CARD_ID) for c in p.harvest_conversions_used)


# ---------------------------------------------------------------------------
# The payment-frontier surface — ruling 76 item 1 (2026-07-21): "its 3
# conversions are offered at the same time the craft majors' conversions are
# offered, and additionally any PendingFoodPayment frame resolved DURING the
# feeding phase can and should offer Studio's conversions." Driver reading:
# Studio stays feeding-phase-scoped — the feed seam above stands, plus
# feeding-phase payment-frontier participation; NO span windows outside the
# feeding phase.
# ---------------------------------------------------------------------------

# A synthetic resume so hand-built raise frames can be stepped through the
# executor (mirrors test_food_payment_generalized's pattern).
FOOD_PAYMENT_RESUMES["_test_studio_resume"] = lambda state, idx: state


def _payment_state(*, owe, phase=Phase.HARVEST_FEED, cursor=None, wood=0,
                   clay=0, stone=0, grain=0, joinery=False,
                   joinery_used=False) -> GameState:
    """A hand-built harvest state with a raise-only PendingFoodPayment for P0
    (food 0, so the shortfall equals `owe`), P0 owning Studio and optionally
    the Joinery major (its harvest budget optionally already spent). A None
    `cursor` is the legacy bare mid-phase shape (in span for FEED/BREED);
    FIELD-band states pass a walk position."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_minors(state, 0, frozenset({CARD_ID}))
    if joinery:
        state = with_majors(state, owner_by_idx={JOINERY_IDX: 0})
    p = state.players[0]
    p = fast_replace(
        p,
        resources=Resources(wood=wood, clay=clay, stone=stone, grain=grain),
        harvest_conversions_used=(frozenset({"joinery"}) if joinery_used
                                  else frozenset()),
    )
    frame = PendingFoodPayment(
        player_idx=0, food_needed=owe,
        resume_kind="_test_studio_resume", reserved=Cost())
    return dataclasses.replace(
        state,
        players=tuple(p if i == 0 else state.players[i] for i in range(2)),
        phase=phase, pending_stack=(frame,), harvest_cursor=cursor)


def _fired_sets(state):
    return {a.conversions for a in legal_actions(state)
            if isinstance(a, CommitFoodPayment)}


def test_feeding_frame_offers_studio_singletons_and_excludes_cofire():
    """A feeding-phase raise frame offers each affordable Studio variant as a
    singleton fire — and NEVER two variants in one bundle. owe 3 with grain
    on hand is the discriminating scenario: the {wood, clay} co-fire would
    keep all 3 grain and SURVIVE the Pareto pass if enumerated, so its
    absence is the frontier_group exclusion (the printed "exactly 1" — one
    budget, within a single bundle too), not dominance."""
    s = _payment_state(owe=3, wood=1, clay=1, grain=3)
    fired = _fired_sets(s)
    assert ("studio_wood",) in fired
    assert ("studio_clay",) in fired
    assert () in fired                     # the pure-crops route stays offered
    assert all(sum(1 for c in f if c.startswith(CARD_ID)) <= 1 for f in fired)


def test_frontier_fire_marks_shared_budget():
    """A raise-frame fire debits the variant's input, banks its food, and
    marks the exact variant id in harvest_conversions_used — the SAME budget
    entry every other surface checks."""
    s = _payment_state(owe=2, wood=1, grain=2)
    target = next(a for a in legal_actions(s)
                  if isinstance(a, CommitFoodPayment)
                  and a.conversions == ("studio_wood",))
    nxt = step(s, target)
    p = nxt.players[0]
    assert p.resources.wood == 0
    assert p.resources.grain == 2          # the fire covered the owe; crops kept
    assert p.resources.food == 2           # +2 raised; the test resume debits 0
    assert "studio_wood" in p.harvest_conversions_used


def test_budget_shared_frontier_to_feed_seam():
    """Frontier -> feed seam: with a raise-frame fire recorded (the exact id
    the executor marks), the feed frame offers no Studio variant for the
    rest of the harvest (the prefix guard)."""
    state = _feed_state(wood=1, clay=1, stone=1)
    p = state.players[0]
    p = fast_replace(p, harvest_conversions_used=frozenset({"studio_stone"}))
    state = dataclasses.replace(state, players=(p, state.players[1]))
    assert _studio_actions(state) == []


def test_budget_shared_feed_seam_to_frontier():
    """Feed seam -> frontier: a real feed-frame fire suppresses the
    payment-frontier surface for the rest of the harvest."""
    state = _feed_state(wood=2, clay=1)
    assert len(available_span_converters(state, 0)) == 3   # all pre-fire
    state = step(state, CommitHarvestConversion(conversion_id="studio_wood"))
    assert available_span_converters(state, 0) == ()


def test_field_band_in_span_frame_offers_majors_not_studio():
    """The driver reading's scoping: an IN-SPAN raise frame outside the
    feeding phase (a FIELD-band position; a BREED-phase frame likewise)
    offers the craft majors' conversions but never Studio's."""
    s = _payment_state(owe=2, wood=1, grain=2, joinery=True,
                       phase=Phase.HARVEST_FIELD,
                       cursor=sentinel_position("end_of_field_phase", 0))
    assert available_span_converters(s, 0) == (
        ("joinery", (0, 0, 1, 0, 0, 0), 2, None),)
    fired = _fired_sets(s)
    assert ("joinery",) in fired
    assert not any(any(c.startswith(CARD_ID) for c in f) for f in fired)
    # BREED phase: same scoping (the span continues, Studio does not).
    b = _payment_state(owe=2, wood=1, grain=2, joinery=True,
                       phase=Phase.HARVEST_BREED,
                       cursor=sentinel_position("after_breeding", 1))
    cids = [cid for cid, _inp, _out, _grp in available_span_converters(b, 0)]
    assert "joinery" in cids
    assert not any(cid.startswith(CARD_ID) for cid in cids)


def test_greedy_joinery_preferred_over_studio_wood_on_tie():
    """The user's concrete case (ruling 76 item 1, verbatim): "a player who
    chooses to convert a wood to food should use the joinery over the studio
    if they have both and both are available." One wood, both budgets
    unused: the single wood conversion surfaces as the JOINERY fire — the
    Studio duplicate produces the identical remaining-goods vector and the
    grouped-count tie-break collapses it (structural; see
    test_food_payment_generalized's adversarial-id test)."""
    s = _payment_state(owe=3, wood=1, grain=2, joinery=True)
    fired = _fired_sets(s)
    assert ("joinery",) in fired
    assert ("studio_wood",) not in fired


def test_greedy_sequence_double_wood_bundle_retained():
    """Loss-less-ness of the preference (an ordering, not a ban): TWO wood
    conversions in one payment — the greedy sequence "joinery first, then
    Studio" — stays expressible as the bundle firing both (distinct goods
    vector, no collapse)."""
    s = _payment_state(owe=4, wood=2, grain=2, joinery=True)
    assert ("joinery", "studio_wood") in _fired_sets(s)


# ---------------------------------------------------------------------------
# The REACHABLE feeding-phase raise frame (real flow): Plow Builder's
# standalone pay-1-food plow at the after_feeding window (FEED band ->
# Phase.HARVEST_FEED) pushes PendingPlow; Rocky Terrain's before_plow buy,
# fired food-short, pushes the raise-only PendingFoodPayment — resolved
# DURING the feeding phase, where Studio's conversions must be offered.
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _neutral(state):
    """Advance the harvest walk without firing any card surface."""
    acts = legal_actions(state)
    for kind in (CommitFieldTake, CommitConvert):
        for a in acts:
            if isinstance(a, kind):
                return a
    for a in acts:
        if isinstance(a, (Proceed, Stop)):
            return a
    return next(a for a in acts
                if not isinstance(a, (FireTrigger, CommitHarvestConversion)))


def test_reachable_feeding_phase_frame_offers_studio():
    cs, _env = setup_env(5, card_pool=_POOL)
    assert cs.mode is GameMode.CARDS
    cs = with_phase(cs, Phase.HARVEST_FIELD)
    cs = dataclasses.replace(
        cs, starting_player=0, pending_stack=(), harvest_cursor=None)
    cs = with_majors(cs, owner_by_idx={JOINERY_IDX: 0})
    cs = with_minors(cs, 0, frozenset({CARD_ID, ROCKY_TERRAIN}))
    p = cs.players[0]
    p = dataclasses.replace(p, occupations=p.occupations | {PLOW_BUILDER})
    cs = dataclasses.replace(cs, players=(p, cs.players[1]))
    # Tuned so P0 exits their feed payment with exactly 1 food (feeding owes
    # 4 for two adults): 3 on hand + Joinery's 2 - 4 = 1 — enough for the
    # standalone plow's printed 1 food, leaving 0 at Rocky Terrain's buy.
    cs = with_resources(cs, 0, food=3, wood=2, grain=1)
    cs = with_resources(cs, 1, food=99)

    # Drive the real walk to P0's after_feeding window, using the Joinery at
    # P0's feed frame (the standalone plow requires its budget spent).
    cs = _advance_until_decision(cs)
    for _ in range(300):
        top = cs.pending_stack[-1] if cs.pending_stack else None
        if (isinstance(top, PendingHarvestWindow) and top.player_idx == 0
                and top.window_id == "after_feeding"):
            break
        if (isinstance(top, PendingHarvestFeed) and top.player_idx == 0
                and not top.conversion_done):
            if "joinery" not in cs.players[0].harvest_conversions_used:
                cs = step(cs, CommitHarvestConversion(conversion_id="joinery"))
            else:
                cs = step(cs, CommitConvert(0, 0, 0, 0, 0))
            continue
        cs = step(cs, _neutral(cs))
    else:
        raise AssertionError("never reached P0's after_feeding window")

    assert cs.phase is Phase.HARVEST_FEED
    assert cs.players[0].resources.food == 1

    # The standalone pay-1-food plow (ruling 76 item 3) — Joinery used, latch
    # unused, exactly the printed 1 food on hand.
    cs = step(cs, FireTrigger(card_id=PLOW_BUILDER))
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    assert cs.players[0].resources.food == 0

    # Rocky Terrain's buy, food-short: the raise-only frame, mid-feeding.
    assert FireTrigger(card_id=ROCKY_TERRAIN) in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id=ROCKY_TERRAIN))
    assert isinstance(cs.pending_stack[-1], PendingFoodPayment)
    assert cs.phase is Phase.HARVEST_FEED

    # Studio's singleton fire is offered (the ruled surface); the Joinery is
    # not (budget spent); the pure-crops route remains.
    fired = _fired_sets(cs)
    assert ("studio_wood",) in fired
    assert ("joinery",) not in fired
    assert () in fired

    # Fire it: wood debited, budget marked, the raised food pays the buy.
    cs = step(cs, next(a for a in legal_actions(cs)
                       if isinstance(a, CommitFoodPayment)
                       and a.conversions == ("studio_wood",)))
    p = cs.players[0]
    assert p.resources.wood == 0            # 2 - joinery - studio
    assert p.resources.stone == 1           # Rocky Terrain's buy resolved
    assert p.resources.food == 1            # +2 raised, -1 for the stone
    assert p.resources.grain == 1           # crops untouched
    assert {"joinery", "studio_wood"} <= p.harvest_conversions_used
    assert isinstance(cs.pending_stack[-1], PendingPlow)   # the plow resumes
