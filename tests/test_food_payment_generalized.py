"""Seam tests for the GENERALIZED food-payment frontier (rulings 34/37/39,
2026-07-12 — the converter cluster's core; CARD_DEFERRED_PLANS.md):

- `span_converters`: once-per-harvest BINARY building-resource converters
  enumerated as subsets around the cached crop/animal core — the return shape
  becomes ((g, v, s, b, c, wood, clay, reed, stone) remaining, fired ids).
- `animal_floors`: ruling 39's stateless post-breed cooking floor, applied by
  supply clipping + translation (no cache-key change).
- The legacy path (no converters, zero floors) is byte-identical.
"""
import pytest

from agricola import opt_config
from agricola.helpers import food_payment_frontier
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

RATES = (2, 2, 3, 2)   # sheep 2, boar 2, cattle 3, veg 2
# (conversion_id, (grain, veg, wood, clay, reed, stone) input, food_out,
# frontier_group) — ruling 77 widened the input to a 6-tuple (crop inputs
# live in positions 0-1; building converters leave grain=veg=0). The group
# (ruling 76 item 1: a bundle fires at most one member of a non-None group;
# None = ungrouped single-conversion card/major).
JOINERY = ("joinery", (0, 0, 1, 0, 0, 0), 2, None)
STONE_CARVER = ("stone_carver", (0, 0, 0, 0, 0, 1), 3, None)
# A crop-input converter (ruling 77): Schnapps Distiller — 1 veg -> 5 food.
SCHNAPPS = ("schnapps_distiller", (0, 1, 0, 0, 0, 0), 5, None)


def _player(**kw):
    p = setup(3).players[0]
    res = {k: v for k, v in kw.items() if k in ("wood", "clay", "reed", "stone",
                                                "food", "grain", "veg")}
    ani = {k: v for k, v in kw.items() if k in ("sheep", "boar", "cattle")}
    p = fast_replace(p, resources=Resources(**res))
    if ani:
        p = fast_replace(p, animals=fast_replace(p.animals, **ani))
    return p


def test_legacy_shape_unchanged_without_extensions():
    p = _player(grain=2, wood=5)
    assert food_payment_frontier(p, 1, RATES) == [(1, 0, 0, 0, 0)]
    # Zero floors are the no-op default.
    assert food_payment_frontier(p, 1, RATES, animal_floors=(0, 0, 0)) == [
        (1, 0, 0, 0, 0)]


def test_converters_extend_the_space_and_return_shape():
    p = _player(grain=1, wood=2, stone=1)
    rows = food_payment_frontier(
        p, 2, RATES, span_converters=(JOINERY, STONE_CARVER))
    assert ((1, 0, 0, 0, 0, 1, 0, 0, 1), ("joinery",)) in rows
    assert ((1, 0, 0, 0, 0, 2, 0, 0, 0), ("stone_carver",)) in rows
    # Firing both is dominated by either single fire (same crops, fewer
    # building resources) — never offered.
    assert all(len(fired) <= 1 for _vec, fired in rows)


def test_converter_infeasible_without_input_good():
    p = _player(grain=2, wood=0)
    rows = food_payment_frontier(p, 2, RATES, span_converters=(JOINERY,))
    # Only the crops config survives (joinery unaffordable): grain pays.
    assert rows == [((0, 0, 0, 0, 0, 0, 0, 0, 0), ())]


def test_no_fires_offered_at_zero_owed():
    p = _player(grain=1, wood=2)
    rows = food_payment_frontier(p, 0, RATES, span_converters=(JOINERY,))
    assert rows == [((1, 0, 0, 0, 0, 2, 0, 0, 0), ())]


def test_overshoot_banked_not_a_dim():
    # Stone Carver's 3 food for owe=1: keeps the grain — incomparable with
    # paying the grain (different goods), so BOTH survive; surplus food is
    # never a Pareto dim.
    p = _player(grain=1, stone=1)
    rows = food_payment_frontier(p, 1, RATES, span_converters=(STONE_CARVER,))
    assert ((1, 0, 0, 0, 0, 0, 0, 0, 0), ("stone_carver",)) in rows
    assert ((0, 0, 0, 0, 0, 0, 0, 0, 1), ()) in rows


def test_floor_protects_animals():
    # 3 sheep at floor 3: none cookable — the grain alone can't cover owe 2,
    # so the frontier is EMPTY (the caller's feasibility gate must pre-check).
    p = _player(grain=1, sheep=3)
    assert food_payment_frontier(p, 2, RATES, animal_floors=(3, 3, 3)) == []
    # Unfloored: cooking a sheep pays.
    assert food_payment_frontier(p, 2, RATES) == [(1, 0, 2, 0, 0)]
    # 4 sheep at floor 3: exactly one is cookable.
    p4 = _player(grain=0, sheep=4)
    assert food_payment_frontier(p4, 2, RATES, animal_floors=(3, 3, 3)) == [
        (0, 0, 3, 0, 0)]


def test_floor_below_count_does_not_bind():
    # 2 sheep with floor 3: the floor only protects a type AT OR ABOVE it
    # (ruling 39's shorthand) — both sheep stay cookable.
    p = _player(grain=0, sheep=2)
    assert food_payment_frontier(p, 2, RATES, animal_floors=(3, 3, 3)) == [
        (0, 0, 1, 0, 0)]


def test_floors_and_converters_compose():
    p = _player(grain=0, sheep=3, wood=1)
    rows = food_payment_frontier(
        p, 2, RATES, span_converters=(JOINERY,), animal_floors=(3, 3, 3))
    # The sheep are protected; joinery is the only payment.
    assert rows == [((0, 0, 3, 0, 0, 0, 0, 0, 0), ("joinery",))]


def test_group_excludes_within_bundle_cofire():
    """Ruling 76 item 1 (2026-07-21, Studio): variants of ONE card share ONE
    once-per-harvest budget, so a bundle fires at most one member of a
    frontier_group. The scenario is chosen so the co-fire would SURVIVE the
    Pareto pass if enumerated (owe 3 with grain on hand: firing both keeps
    all 3 grain — incomparable with every single fire), proving the group
    skip is doing the work, not dominance."""
    w = ("studio_wood", (0, 0, 1, 0, 0, 0), 2, "studio")
    c = ("studio_clay", (0, 0, 0, 1, 0, 0), 2, "studio")
    p = _player(grain=3, wood=1, clay=1)
    rows = food_payment_frontier(p, 3, RATES, span_converters=(w, c))
    assert all(len(fired) <= 1 for _vec, fired in rows)
    # Each variant is still offered as THE single fire (a choice, not a ban).
    fired_sets = {fired for _vec, fired in rows}
    assert ("studio_wood",) in fired_sets
    assert ("studio_clay",) in fired_sets


def test_ungrouped_cofire_still_offered():
    """Control for the group skip: DIFFERENT cards (group None) co-fire in
    one bundle exactly as before — only same-group pairs are excluded."""
    p = _player(grain=3, wood=1, stone=1)
    rows = food_payment_frontier(
        p, 4, RATES, span_converters=(JOINERY, STONE_CARVER))
    assert ("joinery", "stone_carver") in {fired for _vec, fired in rows}


def test_grouped_with_ungrouped_cofire_offered():
    """A grouped variant co-fires with an UNGROUPED same-type converter: the
    greedy sequence's second wood conversion ("joinery first, then Studio")
    must stay expressible in one bundle — ruling 76 item 1's guidance is an
    ordering preference, never a ban on using both."""
    w = ("studio_wood", (0, 0, 1, 0, 0, 0), 2, "studio")
    p = _player(grain=2, wood=2)
    rows = food_payment_frontier(p, 4, RATES, span_converters=(JOINERY, w))
    assert ("joinery", "studio_wood") in {fired for _vec, fired in rows}


def test_tiebreak_prefers_ungrouped_on_exact_vec_ties():
    """The STRUCTURAL greedy-restricted-first tie-break (ruling 76 item 1,
    user verbatim: "a player who chooses to convert a wood to food should
    use the joinery over the studio if they have both and both are
    available"): on an identical remaining-goods vector, the bundle firing
    the ungrouped (restricted single-type) converter wins over the grouped
    (flexible multi-variant) one. The ids are ADVERSARIAL — the grouped id
    sorts lexicographically first — so id ordering cannot produce the pass
    (the pre-hardening rank would have kept the grouped fire)."""
    grouped = ("aaa_flex_wood", (0, 0, 1, 0, 0, 0), 2, "aaa_flex")
    restricted = ("zzz_restricted_wood", (0, 0, 1, 0, 0, 0), 2, None)
    p = _player(grain=2, wood=1)
    rows = food_payment_frontier(
        p, 2, RATES, span_converters=(grouped, restricted))
    fired_sets = {fired for _vec, fired in rows}
    assert ("zzz_restricted_wood",) in fired_sets
    assert ("aaa_flex_wood",) not in fired_sets


# ---------------------------------------------------------------------------
# Crop-input converters (ruling 77 item 1, 2026-07-21) — the greedy tiering
# ---------------------------------------------------------------------------

def test_crop_converter_greedy_tiering():
    """Ruling 77 item 1 (user, verbatim): "if we have Schnapps Distiller and are
    converting N>1 veggies to food during the feeding phase, we should use
    Schnapps Distiller for the first veggie and our smaller rate for the
    remaining N-1." owe 8 at veg rate 2, veg the only fuel: firing Schnapps
    (1 veg -> 5 premium) then base-cooking 2 more veg (-> 4) pays 9 with 3 veg
    total, leaving 2 — strictly better than all-base (4 veg -> 8, leaving 1). The
    Schnapps config DOMINATES the all-base one, so the frontier surfaces exactly
    it: premium first, base rate for the rest."""
    p = _player(veg=5)   # grain 0, no animals
    rows = food_payment_frontier(p, 8, RATES, span_converters=(SCHNAPPS,))
    assert ((0, 2, 0, 0, 0, 0, 0, 0, 0), ("schnapps_distiller",)) in rows
    # The all-base config (veg_rem 1) is dominated and dropped; every surviving
    # config fires Schnapps.
    assert all(fired == ("schnapps_distiller",) for _v, fired in rows)
    assert not any(vec[1] <= 1 for vec, _f in rows)


def test_crop_converter_optionality_at_exact_owe():
    """At an owe met by ONE base-cooked veg, firing Schnapps overshoots (5 vs 2)
    for the SAME veg spend, so both configs share the remaining-goods vector and
    the grouped-count/size tie-break keeps the UNFIRED one — the once-per-harvest
    budget is preserved (Foundations' optionality rule; ruling 77's greedy is
    about N>1)."""
    p = _player(veg=3)
    rows = food_payment_frontier(p, 2, RATES, span_converters=(SCHNAPPS,))
    fired_sets = {fired for _v, fired in rows}
    assert () in fired_sets
    assert ("schnapps_distiller",) not in fired_sets


def test_crop_converter_infeasible_without_veg():
    """A veg converter needing 1 veg is never fired when the player has none —
    the crop sufficiency check (need6[1] > v) skips the subset, exactly as the
    building check skips an unaffordable wood converter."""
    p = _player(grain=5)   # grain only, no veg
    rows = food_payment_frontier(p, 2, RATES, span_converters=(SCHNAPPS,))
    assert all(fired == () for _v, fired in rows)


def test_beer_tap_group_excludes_cofire():
    """Beer Tap's three grain tiers are ONE card / ONE budget (ruling 77 uses
    the Studio group mechanism): a single payment bundle fires at most one tier
    — co-firing two would use the card twice in one harvest.

    owe 9 with 9 grain and span (beer_tap_2, beer_tap_3) is DISCRIMINATING: the
    co-fire (2+3 grain -> 3+6 = 9 food, owe fully covered) keeps 4 grain, which
    strictly DOMINATES every single fire (beer_tap_3 alone leaves only 3: 3 grain
    to the tier + 3 base-cooked). If the group did nothing, the co-fire would win
    the Pareto pass; its absence — the best config keeps only 3 grain — is the
    group skip doing the work, not dominance. (beer_tap_2 alone, less grain-
    efficient, is itself dominated by beer_tap_3 and never surfaces — an
    efficiency fact, unrelated to the group.)"""
    t2 = ("beer_tap_2", (2, 0, 0, 0, 0, 0), 3, "beer_tap")
    t3 = ("beer_tap_3", (3, 0, 0, 0, 0, 0), 6, "beer_tap")
    p = _player(grain=9)
    rows = food_payment_frontier(p, 9, RATES, span_converters=(t2, t3))
    assert all(sum(1 for c in fired if c.startswith("beer_tap")) <= 1
               for _v, fired in rows)
    assert ("beer_tap_3",) in {fired for _v, fired in rows}
    # The excluded co-fire would have kept 4 grain; the best surviving keeps 3.
    assert max(vec[0] for vec, _f in rows) == 3


def test_crop_and_building_converters_compose():
    """A crop converter (Schnapps, veg) and a building converter (Joinery,
    wood) co-fire in one bundle — their inputs land in different Pareto dims
    (veg in dim 1, wood_rem in dim 5) and both fire together with no group
    conflict."""
    p = _player(veg=3, wood=1)
    rows = food_payment_frontier(
        p, 7, RATES, span_converters=(SCHNAPPS, JOINERY))
    assert ("joinery", "schnapps_distiller") in {fired for _v, fired in rows}


def test_cross_level_equivalence(monkeypatch):
    """The converter wrap + floor translation sit OUTSIDE the level-dispatched
    core, so the generalized frontier must be SET-identical across opt levels
    (the FRONTIER_OPT_DESIGN.md cross-level pattern). A crop converter (Schnapps)
    is included so the ruling-77 crop-fold path is exercised at both levels."""
    p = _player(grain=2, veg=3, sheep=4, wood=2, stone=1)
    results = {}
    for level in (0, 1):
        monkeypatch.setattr(opt_config, "PARETO_OPT_LEVEL", level)
        results[level] = sorted(food_payment_frontier(
            p, 3, RATES, span_converters=(JOINERY, STONE_CARVER, SCHNAPPS),
            animal_floors=(3, 0, 0)))
    assert results[0] == results[1]
    assert all(vec[2] >= 3 for vec, _f in results[0])    # sheep floor holds


# ---------------------------------------------------------------------------
# The raise-frame wiring (enumerator + executor) — rulings 34/37/39
# ---------------------------------------------------------------------------

from agricola.actions import CommitFoodPayment
from agricola.cards.harvest_windows import (
    available_span_converters,
    in_conversion_span,
    post_breed_floors,
    sentinel_position,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES
from agricola.constants import Phase
from agricola.resources import Cost
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment
from agricola.state import GameState

from tests.factories import with_majors, with_phase

# A synthetic resume so a hand-built frame can be stepped through the
# executor (registered once; only frames naming it ever reach it).
FOOD_PAYMENT_RESUMES["_test_fpg_resume"] = lambda state, idx: state


def _in_span_state(*, sheep=0, wood=0, stone=0, food=0, owe=2,
                   cursor=None, phase=Phase.HARVEST_BREED, joinery=True):
    state = setup(3)
    state = fast_replace(state, starting_player=0)
    if joinery:
        state = with_majors(state, owner_by_idx={7: 0})
    p = state.players[0]
    p = fast_replace(
        p,
        resources=Resources(wood=wood, stone=stone, food=food),
        animals=fast_replace(p.animals, sheep=sheep, boar=0, cattle=0),
    )
    frame = PendingFoodPayment(
        player_idx=0, food_needed=food + owe,
        resume_kind="_test_fpg_resume", reserved=Cost())
    # Post-both-breed-passes by default (cursor past after_breeding pass 1).
    cur = cursor if cursor is not None else sentinel_position("after_breeding", 1)
    return fast_replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)),
        phase=phase, pending_stack=(frame,), harvest_cursor=cur)


def test_span_derivations():
    s = _in_span_state()
    assert in_conversion_span(s, 0)
    assert available_span_converters(s, 0) == (("joinery", (0, 0, 1, 0, 0, 0), 2, None),)
    # WORK phase: never in span.
    s2 = with_phase(s, Phase.WORK)
    assert not in_conversion_span(s2, 0)
    assert available_span_converters(s2, 0) == ()
    # Fresh FIELD entry (cursor None): pre-span.
    s3 = fast_replace(s, phase=Phase.HARVEST_FIELD, harvest_cursor=None)
    assert not in_conversion_span(s3, 0)


def test_post_breed_floors_by_cursor():
    s = _in_span_state(sheep=3)
    assert post_breed_floors(s, 0) == (3, 3, 3)        # own pass resolved
    # Before the player's breeding sentinel: no floor.
    pre = fast_replace(s, harvest_cursor=sentinel_position("breeding", 0))
    assert post_breed_floors(pre, 0) == (0, 0, 0)
    # FEED phase: never floored (feeding precedes breeding per-player).
    feed = fast_replace(s, phase=Phase.HARVEST_FEED)
    assert post_breed_floors(feed, 0) == (0, 0, 0)


def test_raise_frame_offers_converter_fire():
    s = _in_span_state(wood=1, owe=2)
    opts = legal_actions(s)
    assert opts == [CommitFoodPayment(
        grain=0, veg=0, sheep=0, boar=0, cattle=0, conversions=("joinery",))]


def test_raise_frame_budget_shared_with_feed_seam():
    s = _in_span_state(wood=1, owe=2)
    p = s.players[0]
    p = fast_replace(p, resources=fast_replace(p.resources, grain=2),
                     harvest_conversions_used=frozenset({"joinery"}))
    s = fast_replace(s, players=tuple(
        p if i == 0 else s.players[i] for i in range(2)))
    assert available_span_converters(s, 0) == ()       # budget spent
    opts = legal_actions(s)
    assert all(a.conversions == () for a in opts)      # grain pays instead
    assert any(a.grain == 2 for a in opts)


def test_raise_frame_floor_shapes_offers():
    # 3 sheep post-breed (floored) + 1 wood: only the joinery fire pays.
    s = _in_span_state(sheep=3, wood=1, owe=2)
    opts = legal_actions(s)
    assert opts == [CommitFoodPayment(
        grain=0, veg=0, sheep=0, boar=0, cattle=0, conversions=("joinery",))]


def test_executor_fires_conversion_and_marks_budget():
    s = _in_span_state(wood=1, owe=2)
    nxt = step(s, legal_actions(s)[0])
    p = nxt.players[0]
    assert p.resources.wood == 0
    assert p.resources.food == 2                       # joinery's 2 food raised
    assert "joinery" in p.harvest_conversions_used
    # The frame popped and the resume ran; with an empty stack the walk
    # completed the harvest (cursor 23 was the last band pause).
    assert not any(isinstance(f, PendingFoodPayment) for f in nxt.pending_stack)
