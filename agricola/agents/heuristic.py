"""Heuristic agent evaluators and agent classes.

Two evaluator variants of differing sophistication share the
`HeuristicAgent` infrastructure from `agricola/agents/base.py`:

- `evaluate_simple` powering `SimpleHeuristic` — MVP. Uses `score(state)`
  as the base, adds small linear resource bonuses, and adds a food-shortage
  penalty that accounts for cookable convertibles. The simplest reasonable
  thing that plays a coherent (if not strong) game; few hundred lines of
  total logic.

- `evaluate_hubris` powering `HubrisHeuristic` — faithful-to-spec. Adds
  per-round-decay family-member value, empty-room anticipation, the
  breeding-opportunity counter, context-dependent resource values
  (wood→fence, first-room bonuses, clay-after-cookware, reed-first-2),
  round-13/14 resource decay, major-improvement override values, the
  Pottery/Basketmaker resource boost, stage-dependent food values, and a
  begging penalty scaled by moves-remaining. Implements the user's
  session-message spec with small documented simplifications where the
  spec was loose.

Both evaluators are pure functions: `(state, player_idx, config) -> float`.
They live here rather than as agent methods so they can be reused (e.g.
as MCTS rollout policies, as v0 NN value-head training targets). The
agent classes at the bottom are thin wrappers around `HeuristicAgent`
that bake in the evaluator choice.

Coefficients live on `HeuristicConfig` so they can be tuned (eventually
by self-play). Defaults match the user's spec where the spec gave a
number; otherwise reasonable hand-picks. Both evaluators share one
`HeuristicConfig` — fields not used by Simple are ignored.

Action-selection semantics live in `base.HeuristicAgent`; this module
contributes only the evaluator and its config.
"""

from __future__ import annotations

from dataclasses import dataclass

from agricola.agents.base import HeuristicAgent
from agricola.constants import (
    CellType,
    HARVEST_ROUNDS,
    HouseMaterial,
    NUM_ROUNDS,
    Phase,
)
from agricola.helpers import (
    cooking_rates,
    extract_slots,
    harvest_feed_frontier,
    stables_in_supply,
)
from agricola.scoring import (
    _score_boar,
    _score_cattle,
    _score_grain,
    _score_sheep,
    _score_veg,
    score,
)
from agricola.state import GameState, PlayerState


# ---------------------------------------------------------------------------
# HeuristicConfig — all coefficients in one place
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HeuristicConfig:
    """All tunable coefficients for both evaluators in one frozen object.

    Defaults match the user's session-message spec where the spec gave a
    number; otherwise reasonable hand-picks. The Simple evaluator only
    reads a handful of these (the resource / food / penalty fields);
    Hubris reads the rest.

    Tuning approach (future, not v1): grid-search or CMA-ES over a held-out
    set of match-ups; this dataclass is what you'd vary.
    """

    # --- Simple resource values (Hubris overrides via context-aware terms) ---
    simple_wood_value:  float = 0.5
    simple_clay_value:  float = 0.5
    simple_reed_value:  float = 0.5
    simple_stone_value: float = 0.5
    simple_grain_value: float = 0.2
    simple_veg_value:   float = 0.2

    # --- Food (shared by both evaluators with the same semantics) ---
    # Food up to need is worth `food_at_need_value` per token; beyond that,
    # `food_value` per token (less, since excess only contributes via the
    # next harvest's surplus).
    food_value:           float = 0.5
    food_at_need_value:   float = 1.0
    # Begging-marker shadow rate: extra penalty per food still short after
    # counting all cookable convertibles. Hubris overrides this with a
    # moves-remaining-aware scale.
    simple_begging_per_food:    float = -2.0

    # --- Hubris: family-member future value ---
    # `family_per_round[k]` = per-future-round rate for the k-th family
    # member (3, 4, or 5). Spec values; 1st and 2nd family members are the
    # starting pair and don't need a "marginal value" term beyond score().
    family_per_round: tuple[float, float, float] = (2.5, 2.0, 1.5)  # 3rd, 4th, 5th

    # --- Hubris: empty rooms ---
    empty_room_rate_pre_basic_wish:  float = 2.5  # uses range round 7..12
    empty_room_rate_post_basic_wish: float = 2.5  # uses range (now+2)..12

    # --- Hubris: stables ---
    hubris_unfenced_stable_value_early: float = 0.4  # rounds < 9
    # Fenced stable is already worth 1 pt via score(); no override.

    # --- Hubris: breeding opportunity value per future harvest ---
    breed_active_has_cooking:    float = 1.0
    breed_active_can_afford:     float = 0.8
    breed_active_cannot_afford:  float = 0.6
    breed_passive:               float = 0.3

    # --- Hubris: field location bonus ---
    field_center_bonus: float = 0.1  # for cells (0,1),(0,2),(1,1),(1,2)
    # --- Hubris: pasture location bonus ---
    # Per-enclosed-cell bonus for pasture cells with c >= 2 (right 9
    # cells of the farmyard). Rationale: leaves the left columns clear
    # for room expansion. A 3-cell pasture in that region credits 3 ×
    # this value. Default kept small (0.05) per the user's "similar
    # (small)" phrasing.
    pasture_location_bonus: float = 0.05

    # --- Hubris: renovation step bonus ---
    # Each completed renovation (Wood→Clay, Clay→Stone) credits a small
    # bonus. Larger in late stages so the agent doesn't sit on a wood
    # house with hoarded clay forever. Per the user's reframe of C: the
    # bonus exceeds the per-resource value just enough to make renovation
    # marginally +EV, rather than lowering the per-resource rates globally.
    renovation_bonus_per_step_early: float = 0.75  # stages 1-4
    renovation_bonus_per_step_late:  float = 1.5   # stages 5-6

    # --- Hubris: starting-player bonus ---
    # Holding the SP token grants priority in the next WORK phase.
    # Strategic value is modest but real; defaults to 1pt per user's range.
    starting_player_bonus: float = 1.0

    # --- Hubris: crop+unplowed-field pair bonus ---
    crop_field_pair_early: float = 0.6   # rounds < 12
    crop_field_pair_mid:   float = 0.4   # rounds 12, 13
    crop_field_pair_late:  float = 0.0   # round 14

    # --- Hubris: context-aware resource values ---
    # Wood is tiered to prevent hoarded wood from outvaluing actual
    # building. The original spec's "wood-up-to-fences-left at .8" gave
    # 15-wood holdings the same per-unit value as 5-wood — but a player
    # rarely spends all 15 fence-wood; remaining game-time and action
    # budget caps actual realizable wood spend.
    # Tier 1 (fence-rate): min(wood_tier1_cap, fences_left)  at wood_per_fence_owed
    # Tier 2 (secondary):  wood_tier2_cap                    at wood_secondary
    # Tier 3 (excess):     remaining wood                    at wood_excess
    wood_per_fence_owed:    float = 0.8
    wood_tier1_cap:         int   = 6    # ~typical first-pasture fence count
    wood_secondary:         float = 0.5
    wood_tier2_cap:         int   = 5    # ~additional fences / a room's worth
    wood_excess:            float = 0.15 # hoarded beyond plausible spend
    wood_first5_no_room:    float = 1.5  # first 5 wood, if no room built (overlays tier 1)
    # Clay is similarly tiered when no cookware owned (incentivizes
    # buying the cooking implement instead of hoarding clay forever).
    clay_no_cookware:        float = 1.0
    clay_no_cookware_cap:    int   = 5   # first ~5 clay at high rate (enough for Hearth)
    clay_no_cookware_excess: float = 0.3
    clay_per_wood_room:      float = 0.8  # clay × num_wood_rooms (after cookware)
    clay_excess:             float = 0.3  # clay beyond num_wood_rooms (after cookware)
    pottery_clay_bonus:      float = 0.5  # added to clay value if Pottery owned, up to pottery_bonus_cap
    pottery_bonus_cap:       int   = 7    # actual end-game bonus tops at 3 pts for 7 clay; extra clay gives no more
    basketmaker_bonus_cap:   int   = 5    # actual end-game bonus tops at 3 pts for 5 reed; extra reed gives no more
    # Reed values are tiered by whether a room has been built yet.
    # When a room HAS been built: first 2 reed at `reed_first2`, beyond
    # at `reed_excess`.
    # When NO ROOM has been built: per-reed tiering — the 1st reed is
    # worth `reed_first_no_room`, the 2nd is worth `reed_second_no_room`,
    # and beyond uses `reed_excess_no_room`. (The 1st < 2nd ordering
    # reflects: 1 reed alone can't build anything, but the 2nd completes
    # the pair needed for a room cost.) All three values are subject to
    # the stage-1 inflation / round-13-14 deflation multipliers.
    reed_first2:             float = 0.8
    reed_excess:             float = 0.3
    reed_first_no_room:      float = 1.0
    reed_second_no_room:     float = 2.0
    reed_excess_no_room:     float = 0.7
    basketmaker_reed_bonus:  float = 0.5  # added to reed value if BMW owned
    # Stone tiered as well; major and stone-room costs cap at ~5 per
    # major (Well: 3, Stone Oven: 3, Joinery/Pottery/BMW: 2). Beyond
    # 5-7 stone is rarely spent.
    stone_value:             float = 0.8
    stone_tier_cap:          int   = 5
    stone_excess:            float = 0.3

    # --- Hubris: resource value multipliers by stage ---
    # Stage 1 (rounds 1-4): resources are more valuable than mid-game
    # because they're the foundation for the first room / cookware / fences.
    # Round 13-14: resources are less valuable because there's little time
    # to convert them into scoring leaves. Applied to the raw resource
    # value totals (wood + clay + reed + stone) before the Pottery/BMW
    # craft bonus is added — that bonus reflects end-game craft conversion
    # and isn't time-discounted.
    stage1_resource_mult:  float = 1.5
    round13_resource_mult: float = 0.75
    round14_resource_mult: float = 0.5

    # --- Hubris: major improvement override values ---
    # These REPLACE score()'s major contribution (we subtract score's
    # major term and add this back). Reflects "value of owning" rather
    # than printed VP only.
    #
    # Cooking improvement values are PRIMARY-only: a player gets the
    # utility value for their SINGLE best cooking implement (Hearth
    # always beats Fireplace; a 4-clay Hearth beats a 5-clay Hearth only
    # if both owned, since both fire identically). Any second cooking
    # implement contributes only its printed VP (1 pt) — having two
    # Fireplaces or both Hearth+Fireplace doesn't unlock more cooking
    # utility, just adds a redundant kitchen.
    #
    # Bonus value declines by round bucket (the cookware's instrumental
    # value is already captured by the food-conversion comparison; the
    # remaining "bonus" reflects how much future cooking it enables):
    #   rounds 1-11: full value
    #   rounds 12-13: half value
    #   round 14:    just printed VP (1pt)
    fireplace_value:       float = 4.0  # rounds 1-11
    fireplace_value_mid:   float = 2.0  # rounds 12-13 (halved)
    fireplace_value_late:  float = 1.0  # round 14 (printed VP only)
    hearth_value:          float = 6.0  # rounds 1-11
    hearth_value_mid:      float = 3.0  # rounds 12-13 (halved)
    hearth_value_late:     float = 1.0  # round 14 (printed VP only)
    cooking_secondary_vp:  float = 1.0  # printed VP for the non-primary cooking improvement
    well_value:            float = 4.0
    well_food_per_future:  float = 0.4
    clay_oven_value:       float = 2.0  # ~ printed VP
    stone_oven_value:      float = 3.0
    joinery_value:         float = 2.0
    pottery_value:         float = 2.0
    basketmaker_value:     float = 2.0

    # --- Hubris: stage-dependent food values ---
    # Triple of (rate_up_to_need, rate_beyond_need) per stage 1..6.
    # Stage 1 (rounds 1..4): (1.0, 0.5); stage 2 (5..7): (0.75, 0.5);
    # stages 3..6 (8..14): (0.6, 0.3). Single-source-of-truth for the
    # food-value triple Hubris uses; Simple uses the flat fields above.
    hubris_food_by_stage: tuple[tuple[float, float], ...] = (
        (1.00, 0.5),  # stage 1
        (0.75, 0.5),  # stage 2
        (0.60, 0.3),  # stage 3
        (0.60, 0.3),  # stage 4
        (0.60, 0.3),  # stage 5
        (0.60, 0.3),  # stage 6
    )

    # --- Hubris: begging penalty by moves-remaining ---
    # The "moves remaining before next harvest" is approximated by
    # (people_home) + (rounds_remaining_before_harvest * people_total).
    # Penalty per food short (after counting convertibles), keyed by bucket:
    #   0 moves: -3   (cost of begging marker)
    #   1-2 moves: -2
    #   3-4 moves: -1
    #   5+ moves: -0.5
    hubris_begging_by_moves: tuple[float, ...] = (-3.0, -2.0, -2.0, -1.0, -1.0, -0.5)


DEFAULT_CONFIG = HeuristicConfig()


# ---------------------------------------------------------------------------
# Small derived-quantity helpers
# ---------------------------------------------------------------------------

def _next_harvest_round(round_number: int) -> int | None:
    """Round number of the next harvest at or after `round_number`, or None
    if no harvest remains. Harvests occur at rounds 4, 7, 9, 11, 13, 14."""
    for h in sorted(HARVEST_ROUNDS):
        if h >= round_number:
            return h
    return None


def _stage_of_round(round_number: int) -> int:
    """1..6 stage index for a round (1..14). Out-of-range round returns 6."""
    # Stage 1: 1-4; stage 2: 5-7; stage 3: 8-9; stage 4: 10-11; stage 5: 12-13; stage 6: 14
    if round_number <= 4:  return 1
    if round_number <= 7:  return 2
    if round_number <= 9:  return 3
    if round_number <= 11: return 4
    if round_number <= 13: return 5
    return 6


def _count_cells_of_type(p: PlayerState, cell_type: CellType) -> int:
    grid = p.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == cell_type
    )


def _empty_unenclosed_cells(p: PlayerState) -> int:
    """Cells that are EMPTY and not inside a pasture — eligible to host
    future rooms, fields, or stables."""
    grid = p.farmyard.grid
    enclosed = {cell for past in p.farmyard.pastures for cell in past.cells}
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY and (r, c) not in enclosed
    )


def _count_unfenced_stables(p: PlayerState) -> int:
    """Stables built but not inside any pasture (still hold 1 animal each)."""
    total_built = 4 - stables_in_supply(p.farmyard)
    in_pastures = sum(past.num_stables for past in p.farmyard.pastures)
    return total_built - in_pastures


def _moves_left_before_harvest(state: GameState, p: PlayerState) -> int:
    """Approximate "moves I have remaining before the next harvest."

    Defined as (people not yet placed this round) + (people_total *
    rounds remaining before the next harvest, excluding the current
    round). Lower bound; doesn't model Family Growth happening between
    now and harvest (which would increase the count).
    """
    h = _next_harvest_round(state.round_number)
    if h is None:
        return 0
    rounds_after = max(0, h - state.round_number)
    return p.people_home + rounds_after * p.people_total


def _feeding_need(state: GameState, p: PlayerState) -> int:
    """Food owed at the next harvest (2 per adult, 1 per same-round newborn).

    Returns 0 if no harvest remains. Same-round newborns count for 1 only
    if the harvest is at the END of the current round (i.e. h == state.round_number);
    in all other cases newborns will have been promoted to adults by the
    time the next harvest fires.
    """
    h = _next_harvest_round(state.round_number)
    if h is None:
        return 0
    if h == state.round_number and p.newborns > 0:
        adults = p.people_total - p.newborns
        return 2 * adults + 1 * p.newborns
    return 2 * p.people_total


def _max_convertible_food(state: GameState, p: PlayerState, player_idx: int) -> int:
    """Total food the player could produce by converting everything
    convertible at current cooking rates. Grain is always 1:1; veg uses
    `vR` (3 with Hearth, 2 with Fireplace, 1 fallback). Animals use
    sheep/boar/cattle rates from `cooking_rates` (0 each without cookware)."""
    sR, bR, cR, vR = cooking_rates(state, player_idx)
    return (
        p.animals.sheep  * sR
        + p.animals.boar   * bR
        + p.animals.cattle * cR
        + p.resources.grain
        + p.resources.veg  * vR
    )


def _has_cooking(state: GameState, player_idx: int) -> bool:
    """True if the player owns a Fireplace (idx 0/1) or Cooking Hearth (idx 2/3)."""
    owners = state.board.major_improvement_owners
    return any(owners[i] == player_idx for i in (0, 1, 2, 3))


def _can_afford_cooking(state: GameState, p: PlayerState) -> bool:
    """True if the player could afford the cheapest available cooking
    improvement (a Fireplace at 2 clay), and at least one Fireplace remains
    unowned. We don't check Cooking Hearth here (it's strictly an upgrade
    path; valuing the cheaper option is the right granularity for the
    breeding-value tier)."""
    owners = state.board.major_improvement_owners
    any_fireplace_free = any(owners[i] is None for i in (0, 1))
    return any_fireplace_free and p.resources.clay >= 2


def _basic_wish_revealed_round(state: GameState) -> int | None:
    """Round at which `basic_wish_for_children` is/was revealed, or None
    if it's not in the round_card_order (shouldn't happen — it's always
    a stage-2 card). Round is 1-indexed."""
    order = state.board.round_card_order
    for i, card in enumerate(order):
        if card == "basic_wish_for_children":
            return i + 1
    return None


def _num_breeding_opportunities_from_farm(p: PlayerState) -> int:
    """Max number of animal types where the farm could host 3 of each.

    Each pasture holds one type (up to its capacity). Flex slots (house
    pet + standalone stables) each hold 1 of any type. We sort pastures
    ascending by capacity and greedily assign just enough flex slots to
    reach 3 per pasture-group, then check if remaining flex can support
    one additional type on its own (≥3 flex remaining). Capped at 3 (the
    number of animal types in the game).

    Greedy by smallest-first is optimal here: a pasture already at ≥3
    needs no flex; a pasture below 3 needs `3 - cap` flex. Saving flex
    by skipping a smaller pasture in favor of a larger one is never
    strictly better, since the only alternative use for flex is a
    standalone-flex group needing ≥3, and supporting two distinct types
    is always better than supporting one.
    """
    caps, flex = extract_slots(p)
    caps = sorted(caps)
    types = 0
    for cap in caps:
        deficit = max(0, 3 - cap)
        if flex >= deficit:
            flex -= deficit
            types += 1
    if flex >= 3:
        types += 1
    return min(types, 3)


def _types_with_2_plus_animals(p: PlayerState) -> int:
    return (
        (1 if p.animals.sheep  >= 2 else 0)
        + (1 if p.animals.boar   >= 2 else 0)
        + (1 if p.animals.cattle >= 2 else 0)
    )


# Future-harvest "available animal types" by harvest index (1..6).
# Maps the harvest round to the number of animal types plausibly acquirable
# by that harvest (treating "possibly" as "yes" per the user's spec —
# Sheep Market in stage 1 might be 4th-card-revealed, but we count it).
_HARVEST_AVAILABLE_TYPES: dict[int, int] = {
    4:  1,  # sheep maybe
    7:  1,  # sheep yes
    9:  2,  # sheep yes, pigs maybe
    11: 3,  # sheep yes, pigs yes, cows maybe
    13: 3,
    14: 3,
}


def _future_harvest_rounds(round_number: int) -> list[int]:
    """All harvest rounds at or after `round_number`."""
    return [h for h in sorted(HARVEST_ROUNDS) if h >= round_number]


# ---------------------------------------------------------------------------
# Feeding/food terms (shared base used by both evaluators)
# ---------------------------------------------------------------------------

def _food_term_simple(
    state: GameState, p: PlayerState, player_idx: int, cfg: HeuristicConfig,
) -> float:
    """Food + begging contribution for the Simple evaluator. Splits food
    into "covers need" (worth `food_at_need_value`) and "excess" (worth
    `food_value`), then penalizes any post-convertible shortfall at
    `simple_begging_per_food`."""
    need = _feeding_need(state, p)
    food = p.resources.food
    food_at_need = min(food, need)
    food_excess  = max(0, food - need)
    pts = food_at_need * cfg.food_at_need_value + food_excess * cfg.food_value

    convertible = _max_convertible_food(state, p, player_idx)
    shortfall = max(0, need - food - convertible)
    pts += shortfall * cfg.simple_begging_per_food
    return pts


def _food_term_hubris(
    state: GameState, p: PlayerState, player_idx: int, cfg: HeuristicConfig,
) -> float:
    """Stage-dependent food value + moves-remaining-aware begging penalty."""
    stage = _stage_of_round(state.round_number)
    rate_at_need, rate_excess = cfg.hubris_food_by_stage[stage - 1]
    need = _feeding_need(state, p)
    food = p.resources.food
    food_at_need = min(food, need)
    food_excess  = max(0, food - need)
    pts = food_at_need * rate_at_need + food_excess * rate_excess

    convertible = _max_convertible_food(state, p, player_idx)
    shortfall = max(0, need - food - convertible)
    if shortfall > 0:
        moves = _moves_left_before_harvest(state, p)
        bucket = min(moves, len(cfg.hubris_begging_by_moves) - 1)
        pts += shortfall * cfg.hubris_begging_by_moves[bucket]
    return pts


# ---------------------------------------------------------------------------
# Simple evaluator
# ---------------------------------------------------------------------------

def evaluate_simple(
    state: GameState, player_idx: int, config: HeuristicConfig = DEFAULT_CONFIG,
) -> float:
    """MVP evaluator: `score(state)` + linear resource bonuses + food term.

    Strategy: trust `score(state)` to capture all the leaf scoring
    (animals, crops, fields, rooms, fenced stables, people, majors,
    begging, unused cells, craft bonuses); add small per-unit bonuses for
    resources that score() can't see contributing yet; add a food/begging
    term that accounts for convertibles.

    Doesn't model: future family growth, breeding opportunity, context-
    dependent resource value, round-end decay. These all live in Hubris.
    """
    if state.phase == Phase.BEFORE_SCORING:
        # Game-over evaluation: just the true score.
        total, _ = score(state, player_idx)
        return float(total)

    p = state.players[player_idx]
    total, _ = score(state, player_idx)
    pts = float(total)

    # Linear resource bonuses (grain and veg also get scored by score(),
    # so the bonuses here are small additive nuance).
    r = p.resources
    pts += r.wood  * config.simple_wood_value
    pts += r.clay  * config.simple_clay_value
    pts += r.reed  * config.simple_reed_value
    pts += r.stone * config.simple_stone_value
    pts += r.grain * config.simple_grain_value
    pts += r.veg   * config.simple_veg_value

    # Food + begging.
    pts += _food_term_simple(state, p, player_idx, config)

    return pts


# ---------------------------------------------------------------------------
# Hubris evaluator
# ---------------------------------------------------------------------------

def _hubris_family_value(state: GameState, p: PlayerState, cfg: HeuristicConfig) -> float:
    """Per-round-remaining bonus for the 3rd/4th/5th family member.
    The +3 scoring contribution is already in score().

    Each bonus-eligible member is worth `rate × remaining_plays`. Remaining
    plays per member type:

      - At-home non-newborn: current round + future rounds = NUM_ROUNDS − round_number + 1
      - Placed-this-round or newborn: future rounds only = NUM_ROUNDS − round_number

    `people_home` excludes newborns by engine invariant (newborns aren't
    "available to place this round"), so `min(people_home, bonus_eligible)`
    counts only at-home non-newborn bonus members.

    The earlier formula (rate × rounds_future for all members) treats
    everyone as future-only, undercounting at-home members by one play
    each. This version adds the missing current-round play."""
    rates = cfg.family_per_round
    bonus_eligible = max(0, p.people_total - 2)
    if bonus_eligible == 0:
        return 0.0

    total_rate = sum(rates[min(i, len(rates) - 1)] for i in range(bonus_eligible))
    avg_rate = total_rate / bonus_eligible

    rounds_future = max(0, NUM_ROUNDS - state.round_number)
    # Number of bonus members at home and able to play in the current round.
    # We don't track per-ordinal location, so use min() — generous (assumes
    # at-home members are bonus-eligible whenever possible). The error is
    # at most avg_rate per misassignment, which is small.
    bonus_at_home = min(p.people_home, bonus_eligible)

    return total_rate * rounds_future + avg_rate * bonus_at_home


def _hubris_empty_room_value(state: GameState, p: PlayerState, cfg: HeuristicConfig) -> float:
    """Anticipated value of empty rooms (rooms beyond current people_total).
    Before basic_wish is revealed: rooms will fill around basic_wish's
    round. After: rooms will fill ~2 rounds out. Cap fill round at 12 so
    the bonus dies off near the end of the game.
    """
    if p.people_total >= 5:
        return 0.0
    num_rooms = _count_cells_of_type(p, CellType.ROOM)
    num_empty = max(0, num_rooms - p.people_total)
    if num_empty == 0:
        return 0.0

    basic_wish = _basic_wish_revealed_round(state)
    if basic_wish is not None and state.round_number < basic_wish:
        fill_round = basic_wish
        rate = cfg.empty_room_rate_pre_basic_wish
    else:
        fill_round = min(12, state.round_number + 2)
        rate = cfg.empty_room_rate_post_basic_wish

    # Capped at 12 — a room first filled in round 13 or 14 mostly just
    # scores +3 with negligible action contribution. Matches the user's
    # "rounds 7-12" / "2 rounds from now to round 12" framing.
    rounds_active = max(0, 12 - fill_round)
    # +3 for the future scoring contribution, plus per-round rate.
    return num_empty * (3.0 + rate * rounds_active)


def _hubris_unfenced_stable_value(state: GameState, p: PlayerState, cfg: HeuristicConfig) -> float:
    """Pre-round-9: unfenced stables are worth `hubris_unfenced_stable_value_early`
    each. From round 9 onward, score()'s fenced-stable term + the
    breeding-opportunity value capture their contribution and the explicit
    term becomes 0 to avoid double-counting."""
    if state.round_number >= 9:
        return 0.0
    return _count_unfenced_stables(p) * cfg.hubris_unfenced_stable_value_early


def _hubris_breeding_value(state: GameState, p: PlayerState, player_idx: int, cfg: HeuristicConfig) -> float:
    """Per-future-harvest breeding-opportunity value.

    For each future harvest:
      farm_opps = num_breeding_opportunities_from_farm(p)
      types_avail = available types at this harvest (sheep/pig/cow timing)
      types_with_2 = animal types the player has ≥2 of right now
      per_harvest_opps = min(farm_opps, types_avail)
      active = min(types_with_2, per_harvest_opps)
      passive = per_harvest_opps - active

    `active` is worth `breed_active_*` per-breed (rate depends on
    cooking-implement state); `passive` is worth `breed_passive` per-breed.
    Sum across future harvests.

    Approximation: types_with_2_plus is computed from CURRENT animals,
    not future-projected. A player without animals today still gets
    `passive` value per opportunity, reflecting future potential.
    """
    farm_opps = _num_breeding_opportunities_from_farm(p)
    if farm_opps == 0:
        return 0.0

    types_with_2 = _types_with_2_plus_animals(p)
    if _has_cooking(state, player_idx):
        active_rate = cfg.breed_active_has_cooking
    elif _can_afford_cooking(state, p):
        active_rate = cfg.breed_active_can_afford
    else:
        active_rate = cfg.breed_active_cannot_afford
    passive_rate = cfg.breed_passive

    pts = 0.0
    for h in _future_harvest_rounds(state.round_number):
        types_avail = _HARVEST_AVAILABLE_TYPES[h]
        per_harvest = min(farm_opps, types_avail)
        active  = min(types_with_2, per_harvest)
        passive = per_harvest - active
        pts += active * active_rate + passive * passive_rate
    return pts


_FIELD_BONUS_CELLS: tuple[tuple[int, int], ...] = ((0, 1), (0, 2), (1, 1), (1, 2))
# Pasture bonus applies to the right half of the farmyard — all (r, c)
# with c >= 2. Per user spec; rationale is presumably that pastures on
# the right keep the left columns (closer to the starting rooms) free
# for room expansion and field placement.
_PASTURE_BONUS_CELLS: tuple[tuple[int, int], ...] = tuple(
    (r, c) for r in range(3) for c in range(2, 5)
)


def _hubris_field_location_bonus(p: PlayerState, cfg: HeuristicConfig) -> float:
    """+`field_center_bonus` per field on (0,1),(0,2),(1,1),(1,2)."""
    grid = p.farmyard.grid
    return cfg.field_center_bonus * sum(
        1 for (r, c) in _FIELD_BONUS_CELLS if grid[r][c].cell_type == CellType.FIELD
    )


def _hubris_pasture_location_bonus(p: PlayerState, cfg: HeuristicConfig) -> float:
    """+`pasture_location_bonus` per enclosed pasture cell with c >= 2
    (the right 9 cells of the 3×5 farmyard). Per-cell granularity —
    a 3-cell pasture occupying (0,2),(0,3),(0,4) credits 3× the bonus."""
    pasture_cells = {cell for past in p.farmyard.pastures for cell in past.cells}
    return cfg.pasture_location_bonus * sum(
        1 for cell in _PASTURE_BONUS_CELLS if cell in pasture_cells
    )


def _hubris_renovation_bonus(state: GameState, p: PlayerState, cfg: HeuristicConfig) -> float:
    """Post-renovation bonus: each renovation step (Wood→Clay = 1 step,
    Clay→Stone = 2 steps) credits `renovation_bonus_per_step_*` based on
    the current stage. This makes renovation actions strictly +EV without
    needing to lower the raw resource values.

    The bonus attaches to the renovated STATE (so the post-renovation
    state evaluates higher than the pre-rent state), which is what the
    agent compares at decision time."""
    if p.house_material == HouseMaterial.CLAY:
        steps = 1
    elif p.house_material == HouseMaterial.STONE:
        steps = 2
    else:
        return 0.0
    stage = _stage_of_round(state.round_number)
    per_step = (
        cfg.renovation_bonus_per_step_late
        if stage >= 5
        else cfg.renovation_bonus_per_step_early
    )
    return steps * per_step


def _hubris_starting_player_bonus(state: GameState, player_idx: int, cfg: HeuristicConfig) -> float:
    """Small bonus when holding the starting-player token. The token
    grants placement priority in the next WORK phase; value is hard to
    quantify but consistently nonzero, so a flat bonus is the right shape."""
    return cfg.starting_player_bonus if state.starting_player == player_idx else 0.0


def _hubris_crop_field_pair_bonus(state: GameState, p: PlayerState, cfg: HeuristicConfig) -> float:
    """Each (crop-in-supply, plowed-empty-field) pair is worth a small
    bonus, decaying by round: 0.6 (rounds <12) / 0.4 (12-13) / 0.0 (14).

    Crops = grain + veg in personal supply. Plowed-empty-fields = grid
    cells with `cell_type == FIELD` and `grain == 0 and veg == 0` (i.e.
    field tiles ready to receive crops via a sow action). Earlier
    implementation counted any empty unenclosed cell, which was a bug —
    the player can only sow into plowed fields, so a crop-in-supply has
    no immediate sowing partner if there's no plowed empty field."""
    if state.round_number >= 14:
        return 0.0
    rate = cfg.crop_field_pair_early if state.round_number < 12 else cfg.crop_field_pair_mid
    crops = p.resources.grain + p.resources.veg
    grid = p.farmyard.grid
    plowed_empty = sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
    )
    return rate * min(crops, plowed_empty)


def _three_tier(amount: int, cap1: int, cap2: int, rate1: float, rate2: float, rate3: float) -> float:
    """Apply a 3-tier piecewise linear valuation.

    First `cap1` units at `rate1`, next `cap2` units at `rate2`, remainder
    at `rate3`. Used by the resource-value helpers to model diminishing
    returns: hoarded resources beyond what's plausibly spendable in the
    remaining game contribute less per unit. Caps clamp at 0 if the
    request is non-positive (defensive)."""
    t1 = min(amount, max(0, cap1))
    t2 = min(max(0, amount - cap1), max(0, cap2))
    t3 = max(0, amount - cap1 - cap2)
    return t1 * rate1 + t2 * rate2 + t3 * rate3


def _hubris_resource_value(state: GameState, p: PlayerState, player_idx: int, cfg: HeuristicConfig) -> float:
    """Context-aware resource valuation with diminishing-returns tiers.

    Each resource is valued via a piecewise function — early units are
    "high-yield" (fund the building the resource is for), later units are
    "excess" (worth less since they're unlikely to be spent before the
    game ends). The tiers prevent the hoarding failure mode where a
    player with many of a resource scores higher than an equivalent
    player who already spent the resource on the thing it enables.

    Wood:  tiered by (fence_tier_cap, secondary_cap, excess), each tier
           at its own rate. Tier 1 cap = min(wood_tier1_cap, fences_left)
           so a player who already built most fences gets less "fence
           tier" credit. First 5 wood get the no-room-built bonus rate
           if the house still has only its 2 starting rooms.

    Clay:  no cookware → first `clay_no_cookware_cap` at high rate, rest
           at low (incentivizes BUYING the cookware rather than hoarding).
           With cookware → first (num_wood_rooms) at renovation rate, rest
           at excess. Pottery adds a flat per-clay bonus (always, all tiers).

    Reed:  first 2 at high rate, rest at excess. No-room-built bumps
           first 2 to a still-higher rate. Basketmaker adds a flat bonus.

    Stone: tiered. Major-improvement costs cap at ~5 stone (Well: 3,
           Stone Oven: 3, the 2-stone crafts); beyond ~5 stone is rarely
           spent in a single major.

    Round-13/14 multiplier applies to the raw resource value (NOT to the
    Pottery/BMW per-resource bonus — that bonus reflects late-game craft
    conversion at scoring time, which is independent of remaining rounds)."""
    r = p.resources

    # Determine "no room built yet" state — starting state is 2 wood rooms.
    num_rooms = _count_cells_of_type(p, CellType.ROOM)
    no_room_built = (num_rooms <= 2) and (p.house_material == HouseMaterial.WOOD)

    owners = state.board.major_improvement_owners
    has_cookware = _has_cooking(state, player_idx)
    has_pottery     = owners[8] == player_idx  # idx 8 = Pottery
    has_basketmaker = owners[9] == player_idx  # idx 9 = Basketmaker's

    # --- Wood ---
    # Fences-left caps the high-rate tier: a player with most fences
    # already built can't realistically convert more wood into fences.
    fences_left = 15 - sum(
        sum(row) for row in p.farmyard.horizontal_fences
    ) - sum(
        sum(row) for row in p.farmyard.vertical_fences
    )
    w = r.wood
    tier1_cap = min(cfg.wood_tier1_cap, max(0, fences_left))
    if no_room_built:
        # First 5 wood at the no-room-built bonus rate, then tiered.
        first5 = min(w, 5)
        remaining = w - first5
        wood_pts = first5 * cfg.wood_first5_no_room + _three_tier(
            remaining,
            cap1=tier1_cap, cap2=cfg.wood_tier2_cap,
            rate1=cfg.wood_per_fence_owed,
            rate2=cfg.wood_secondary,
            rate3=cfg.wood_excess,
        )
    else:
        wood_pts = _three_tier(
            w,
            cap1=tier1_cap, cap2=cfg.wood_tier2_cap,
            rate1=cfg.wood_per_fence_owed,
            rate2=cfg.wood_secondary,
            rate3=cfg.wood_excess,
        )

    # --- Clay ---
    c = r.clay
    if not has_cookware:
        # First N at "buy cookware" rate, rest at excess.
        tier1 = min(c, cfg.clay_no_cookware_cap)
        excess = c - tier1
        clay_pts = tier1 * cfg.clay_no_cookware + excess * cfg.clay_no_cookware_excess
    else:
        num_wood_rooms = num_rooms if p.house_material == HouseMaterial.WOOD else 0
        tier1 = min(c, num_wood_rooms)
        tier2 = c - tier1
        clay_pts = tier1 * cfg.clay_per_wood_room + tier2 * cfg.clay_excess

    # --- Reed ---
    re = r.reed
    if no_room_built:
        # Per-reed tiering: 1st < 2nd reflects "1 reed alone is useless,
        # 2nd reed completes the room's reed requirement."
        reed_pts = 0.0
        if re >= 1: reed_pts += cfg.reed_first_no_room
        if re >= 2: reed_pts += cfg.reed_second_no_room
        if re > 2:  reed_pts += (re - 2) * cfg.reed_excess_no_room
    else:
        first2 = min(re, 2)
        rest   = re - first2
        reed_pts = first2 * cfg.reed_first2 + rest * cfg.reed_excess

    # --- Stone ---
    s = r.stone
    s_tier1 = min(s, cfg.stone_tier_cap)
    s_excess = s - s_tier1
    stone_pts = s_tier1 * cfg.stone_value + s_excess * cfg.stone_excess

    # Stage-1 inflation / end-game decay (applies only to the raw resource
    # value tiers; the Pottery/BMW bonus is added below at full rate
    # because that bonus reflects end-game craft conversion and is
    # time-independent).
    raw_total = wood_pts + clay_pts + reed_pts + stone_pts
    if state.round_number == 13:
        raw_total *= cfg.round13_resource_mult
    elif state.round_number == 14:
        raw_total *= cfg.round14_resource_mult
    elif state.round_number <= 4:  # stage 1
        raw_total *= cfg.stage1_resource_mult

    # Pottery / BMW craft-resource bonus. Capped because the actual
    # end-game craft bonus tops out at 3 pts (7 clay for Pottery, 5 reed
    # for BMW); resources beyond that contribute no extra bonus.
    if has_pottery:
        raw_total += min(c, cfg.pottery_bonus_cap) * cfg.pottery_clay_bonus
    if has_basketmaker:
        raw_total += min(re, cfg.basketmaker_bonus_cap) * cfg.basketmaker_reed_bonus

    return raw_total


def _hubris_major_value(state: GameState, player_idx: int, cfg: HeuristicConfig) -> float:
    """Value of owned major improvements — REPLACES score()'s major term.

    Cooking-improvement valuation: only the SINGLE primary cooking
    implement gets utility value. Hearth always beats Fireplace
    (strictly better rates and bigger Bake yield); among multiple Hearths
    or multiple Fireplaces the duplicate is redundant. The non-primary
    cooking improvement(s) contribute only their printed VP
    (`cooking_secondary_vp`). Without this rule a player holding both a
    Hearth and a Fireplace would be credited 6+4=10 for cooking, when
    really the Fireplace is dead weight (1 printed VP).

    Well's value depends on how many future-food deposits it will still
    drop. Ovens/Joinery/Pottery/BMW are valued near their printed VP."""
    owners = state.board.major_improvement_owners
    pts = 0.0

    # --- Cooking implements: primary gets utility, rest get printed VP ---
    # Primary value tiered by round bucket (full / mid / late). See
    # HeuristicConfig comment for the rationale.
    has_hearth_indices    = [i for i in (2, 3) if owners[i] == player_idx]
    has_fireplace_indices = [i for i in (0, 1) if owners[i] == player_idx]
    num_cooking_owned     = len(has_hearth_indices) + len(has_fireplace_indices)
    r = state.round_number

    if has_hearth_indices:
        if r >= 14:    pts += cfg.hearth_value_late
        elif r >= 12:  pts += cfg.hearth_value_mid
        else:          pts += cfg.hearth_value
        pts += (num_cooking_owned - 1) * cfg.cooking_secondary_vp
    elif has_fireplace_indices:
        if r >= 14:    pts += cfg.fireplace_value_late
        elif r >= 12:  pts += cfg.fireplace_value_mid
        else:          pts += cfg.fireplace_value
        pts += (num_cooking_owned - 1) * cfg.cooking_secondary_vp

    # Well (idx 4): printed 4 + 0.4 per future scheduled food deposit.
    if owners[4] == player_idx:
        # `future_resources[i]` is the i-th future round's promised goods.
        # Count future entries with food > 0; cap at 5 (Well places food on
        # the next 5 round spaces at purchase time).
        upcoming = sum(
            1 for r in state.players[player_idx].future_resources if r.food > 0
        )
        pts += cfg.well_value + cfg.well_food_per_future * min(upcoming, 5)

    if owners[5] == player_idx:  pts += cfg.clay_oven_value
    if owners[6] == player_idx:  pts += cfg.stone_oven_value
    if owners[7] == player_idx:  pts += cfg.joinery_value
    if owners[8] == player_idx:  pts += cfg.pottery_value
    if owners[9] == player_idx:  pts += cfg.basketmaker_value

    return pts


def evaluate_hubris_v1(
    state: GameState, player_idx: int, config: HeuristicConfig = DEFAULT_CONFIG,
) -> float:
    """Hubris v1: the first stable Hubris evaluator. See module docstring
    and HeuristicConfig for the meaning of each term.

    Composition: starts from `score(state)`, then:
      - REPLACES major-improvement contribution with Hubris's override
        (`_hubris_major_value`).
      - ADDS the Hubris-specific terms: family-future, empty rooms,
        unfenced stables, breeding opportunity, field-location bonus,
        crop+field pair bonus, context-aware resources, food/begging.

    Known limitation in v1 (addressed in v2): the food/begging term
    treats convertible goods as IF they were converted to food (reducing
    the shortfall penalty), but `score()` simultaneously credits those
    goods at their full direct value — a double-count. See
    `evaluate_hubris_v2` for the fix.

    All other ADD terms are designed to not double-count score()'s leaves
    — e.g., score() already counts current people at 3 pts each, so the
    family-future term only adds the per-round-remaining rate. Score()
    counts each pasture at 1 pt; the breeding term adds value for the
    pasture's role in enabling future breeding (not the pasture itself).
    """
    if state.phase == Phase.BEFORE_SCORING:
        total, _ = score(state, player_idx)
        return float(total)

    p = state.players[player_idx]
    total, bd = score(state, player_idx)
    pts = float(total)

    # Replace score's major term with Hubris's override.
    pts -= bd.major_improvement_points
    pts += _hubris_major_value(state, player_idx, config)

    # Hubris-only additive terms.
    pts += _hubris_family_value(state, p, config)
    pts += _hubris_empty_room_value(state, p, config)
    pts += _hubris_unfenced_stable_value(state, p, config)
    pts += _hubris_breeding_value(state, p, player_idx, config)
    pts += _hubris_field_location_bonus(p, config)
    pts += _hubris_pasture_location_bonus(p, config)
    pts += _hubris_crop_field_pair_bonus(state, p, config)
    pts += _hubris_resource_value(state, p, player_idx, config)
    # Renovation bonus deferred per user feedback (2026-05-22): the
    # helper and config fields remain defined so this can be re-enabled
    # by uncommenting the line below if/when we decide to add it.
    # pts += _hubris_renovation_bonus(state, p, config)
    pts += _hubris_starting_player_bonus(state, player_idx, config)
    pts += _food_term_hubris(state, p, player_idx, config)

    return pts


# ---------------------------------------------------------------------------
# Hubris v2 — joint goods-or-food optimization via harvest_feed_frontier
# ---------------------------------------------------------------------------

def _grain_on_fields(p: PlayerState) -> int:
    """Total grain currently planted on field tiles (not in supply)."""
    grid = p.farmyard.grid
    return sum(
        grid[r][c].grain
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )


def _veg_on_fields(p: PlayerState) -> int:
    grid = p.farmyard.grid
    return sum(
        grid[r][c].veg
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )


def _food_and_goods_term_v2(
    state: GameState, p: PlayerState, player_idx: int, cfg: HeuristicConfig,
) -> float:
    """v2 replacement for `_food_term_hubris`.

    Enumerates the Pareto-optimal feeding configurations via
    `harvest_feed_frontier` and returns the maximum value over them. Each
    configuration's value comprises:

      - Score-leaf contributions for the POST-conversion goods
        (grain/veg/sheep/boar/cattle), using the same score functions as
        `score()` so the result is directly comparable.
      - Food-supply contribution (food at-need + excess at the stage's
        rates).
      - Begging penalty for any shortfall this strategy incurs.

    The caller (`evaluate_hubris_v2`) MUST subtract `score()`'s
    contributions for `grain / vegetables / sheep / boar / cattle` before
    calling this — those are re-supplied here at the optimal-feeding
    counts.

    No-harvest case (need == 0): return goods score + food at the excess
    rate. Skips frontier enumeration.

    Performance: each evaluator call may issue one frontier enumeration.
    Frontier size is small in early game (few convertible goods) and
    grows in late game; the cost is dominated by the 5-dimensional
    Pareto filter inside `harvest_feed_frontier` (already optimized).
    """
    stage = _stage_of_round(state.round_number)
    rate_at_need, rate_excess = cfg.hubris_food_by_stage[stage - 1]
    need = _feeding_need(state, p)
    food = p.resources.food

    # Field grain/veg can't be converted at harvest (they're stuck on the
    # field until harvested); they score directly. Add their score-leaf
    # contribution to every option uniformly. We compute the leaf using
    # supply + field totals as score() does.
    grain_field = _grain_on_fields(p)
    veg_field   = _veg_on_fields(p)

    if need == 0:
        # No upcoming harvest (game over or post-final-harvest). Goods at
        # direct value; food at excess rate.
        return (
            _score_grain(p.resources.grain + grain_field)
            + _score_veg(p.resources.veg + veg_field)
            + _score_sheep(p.animals.sheep)
            + _score_boar(p.animals.boar)
            + _score_cattle(p.animals.cattle)
            + food * rate_excess
        )

    # Begging penalty rate (per food short), based on moves remaining.
    moves = _moves_left_before_harvest(state, p)
    bucket = min(moves, len(cfg.hubris_begging_by_moves) - 1)
    begging_per_food = cfg.hubris_begging_by_moves[bucket]  # negative

    # If direct food covers need, no conversion is needed at all — the
    # optimal strategy is "keep all goods, pay food, no begging."
    if food >= need:
        food_pts = need * rate_at_need + (food - need) * rate_excess
        return (
            _score_grain(p.resources.grain + grain_field)
            + _score_veg(p.resources.veg + veg_field)
            + _score_sheep(p.animals.sheep)
            + _score_boar(p.animals.boar)
            + _score_cattle(p.animals.cattle)
            + food_pts
        )

    # Direct food insufficient; enumerate frontier of (remaining-goods,
    # begging) configurations for the shortfall.
    food_owed = need - food
    rates = cooking_rates(state, player_idx)
    options = harvest_feed_frontier(p, food_owed, rates)

    # Food paid via direct supply is `food` (always max-used when shortfall
    # exists — direct food is "free" relative to converting goods).
    # Food remaining in supply after payment: 0.
    food_pts = food * rate_at_need  # all direct food goes to "at-need"

    best = float("-inf")
    for (remaining, begging) in options:
        g_rem, v_rem, s_rem, b_rem, c_rem = remaining
        # Score-leaf contributions with post-conversion goods.
        goods_pts = (
            _score_grain(g_rem + grain_field)
            + _score_veg(v_rem + veg_field)
            + _score_sheep(s_rem)
            + _score_boar(b_rem)
            + _score_cattle(c_rem)
        )
        begging_pts = begging * begging_per_food  # negative
        total = goods_pts + food_pts + begging_pts
        if total > best:
            best = total
    return best


def evaluate_hubris_v2(
    state: GameState, player_idx: int, config: HeuristicConfig = DEFAULT_CONFIG,
) -> float:
    """Hubris v2: fixes the v1 double-count of convertible goods.

    v1's `_food_term_hubris` reduced the begging penalty by assuming all
    convertibles got converted, while `score()` still credited those same
    goods at full direct value. v2 resolves this by computing the OPTIMAL
    feeding strategy via `harvest_feed_frontier` and using the
    post-conversion score leaves directly. Each good is valued at the max
    of (direct goods value) or (food-conversion value), jointly across
    all goods.

    Implementation: same composition as v1, but
      - score()'s grain/veg/sheep/boar/cattle leaves are SUBTRACTED
        (re-supplied at the optimal-feeding counts), and
      - the v1 `_food_term_hubris` call is replaced with
        `_food_and_goods_term_v2`.

    All other terms (family-future, empty rooms, breeding-opportunity,
    location bonuses, resource value, majors override, starting-player,
    crop+field pair) are unchanged. The pair-bonus fix (plowed-empty
    fields) landed in v1 too.
    """
    if state.phase == Phase.BEFORE_SCORING:
        total, _ = score(state, player_idx)
        return float(total)

    p = state.players[player_idx]
    total, bd = score(state, player_idx)
    pts = float(total)

    # Replace score's major term with Hubris's override.
    pts -= bd.major_improvement_points
    pts += _hubris_major_value(state, player_idx, config)

    # Remove score's food-relevant leaf contributions; re-add via the joint
    # goods-or-food maximization below. `bd.begging_markers` is PAST
    # begging (already incurred), distinct from the anticipated begging
    # the food term computes — keep it.
    pts -= bd.grain
    pts -= bd.vegetables
    pts -= bd.sheep
    pts -= bd.boar
    pts -= bd.cattle

    # Hubris-only additive terms (same as v1).
    pts += _hubris_family_value(state, p, config)
    pts += _hubris_empty_room_value(state, p, config)
    pts += _hubris_unfenced_stable_value(state, p, config)
    pts += _hubris_breeding_value(state, p, player_idx, config)
    pts += _hubris_field_location_bonus(p, config)
    pts += _hubris_pasture_location_bonus(p, config)
    pts += _hubris_crop_field_pair_bonus(state, p, config)
    pts += _hubris_resource_value(state, p, player_idx, config)
    # Renovation bonus deferred (see v1 comment).
    # pts += _hubris_renovation_bonus(state, p, config)
    pts += _hubris_starting_player_bonus(state, player_idx, config)

    # The combined food-leaves + food-supply + begging term, max over
    # Pareto-optimal feeding configurations.
    pts += _food_and_goods_term_v2(state, p, player_idx, config)

    return pts


# Backward-compatibility alias: the unversioned name resolves to v1.
# When v2 has been benched and promoted to "default Hubris", flip this
# to evaluate_hubris_v2.
evaluate_hubris = evaluate_hubris_v1


# ---------------------------------------------------------------------------
# Agent classes — thin wrappers binding evaluator into HeuristicAgent
# ---------------------------------------------------------------------------

class SimpleHeuristic(HeuristicAgent):
    """Heuristic agent using `evaluate_simple`. Defaults to 1-turn
    lookahead with singleton-skip; see `HeuristicAgent` for the full
    action-selection semantics."""

    def __init__(
        self,
        *,
        temperature: float = 0.0,
        seed: int = 0,
        config: HeuristicConfig = DEFAULT_CONFIG,
        lookahead: str = "turn",
    ):
        super().__init__(
            evaluator=evaluate_simple,
            config=config,
            temperature=temperature,
            seed=seed,
            lookahead=lookahead,
        )


class HubrisHeuristicV1(HeuristicAgent):
    """Hubris v1 agent — the first stable Hubris evaluator. Uses
    `evaluate_hubris_v1`. See `HeuristicAgent` for action-selection
    semantics.

    Snapshot taken when v2 was introduced; v1 stays available so v1-vs-v2
    matchups can be run and v1 can serve as a fixed baseline."""

    def __init__(
        self,
        *,
        temperature: float = 0.0,
        seed: int = 0,
        config: HeuristicConfig = DEFAULT_CONFIG,
        lookahead: str = "turn",
    ):
        super().__init__(
            evaluator=evaluate_hubris_v1,
            config=config,
            temperature=temperature,
            seed=seed,
            lookahead=lookahead,
        )


class HubrisHeuristicV2(HeuristicAgent):
    """Hubris v2 agent — fixes v1's convertible-goods double-count by
    using `harvest_feed_frontier` for joint goods-or-food optimization.
    Uses `evaluate_hubris_v2`. See `HeuristicAgent` for action-selection
    semantics.

    Slightly more expensive per evaluator call (one frontier enumeration
    when food < need); see `_food_and_goods_term_v2` for details."""

    def __init__(
        self,
        *,
        temperature: float = 0.0,
        seed: int = 0,
        config: HeuristicConfig = DEFAULT_CONFIG,
        lookahead: str = "turn",
    ):
        super().__init__(
            evaluator=evaluate_hubris_v2,
            config=config,
            temperature=temperature,
            seed=seed,
            lookahead=lookahead,
        )


# Backward-compatibility alias: the unversioned name resolves to v1.
# When v2 is promoted, flip this to HubrisHeuristicV2.
HubrisHeuristic = HubrisHeuristicV1
