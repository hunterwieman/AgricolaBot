from enum import Enum, auto

from agricola.resources import Resources


class Phase(Enum):
    DRAFT = auto()
    WORK = auto()
    RETURN_HOME = auto()
    PREPARATION = auto()
    HARVEST_FIELD = auto()
    HARVEST_FEED = auto()
    HARVEST_BREED = auto()
    BEFORE_SCORING = auto()


class GameMode(Enum):
    """Which Agricola variant a GameState belongs to.

    FAMILY is the cardless 2-player game — the engine's original and default mode.
    CARDS is the full game with occupation / minor-improvement hand cards. The mode
    is chosen at setup and read wherever the two variants diverge (placement
    legality, the action board, Meeting Place / Lessons). Defaulting
    GameState.mode to FAMILY keeps every existing family state unchanged in shape.
    See CARD_IMPLEMENTATION_PLAN.md I.1.
    """
    FAMILY = auto()
    CARDS = auto()


class HouseMaterial(Enum):
    WOOD = auto()
    CLAY = auto()
    STONE = auto()


class CellType(Enum):
    # NOTE: there is deliberately no PASTURE value. A pasture is derived from the
    # Farmyard fence arrays, not stored on the cell, so a fenced-but-empty pasture
    # cell keeps cell_type == EMPTY. Any "is this space used / empty?" check must
    # also consult helpers.enclosed_cells(farmyard) — never cell_type alone. (See
    # big_country._all_farmyard_spaces_used and CARD_AUTHORING_GUIDE.md §2.)
    EMPTY = auto()
    ROOM = auto()
    FIELD = auto()
    STABLE = auto()


# Action space IDs (strings used as dict keys in BoardState)
# Permanent spaces (always available):
PERMANENT_ACTION_SPACES = [
    "farm_expansion",       # Build Rooms and/or Build Stables
    "meeting_place",        # Become SP + food accumulation (Family game)
    "grain_seeds",          # Get 1 Grain
    "farmland",             # Plow 1 Field
    "lessons",              # Play Occupation (unusable in Family game, but space exists)
    "day_laborer",          # Get 2 Food
    "forest",               # Accum: +3 Wood/round
    "clay_pit",             # Accum: +1 Clay/round
    "reed_bank",            # Accum: +1 Reed/round
    "fishing",              # Accum: +1 Food/round
    "side_job",             # Build 1 Stable (1 wood) and/or Bake Bread (Family game addition)
]

# Stage card IDs grouped by stage (order within each stage is randomised at setup):
STAGE_CARDS = {
    1: ["major_improvement", "fencing", "grain_utilization", "sheep_market"],
    2: ["basic_wish_for_children", "house_redevelopment", "western_quarry"],
    3: ["vegetable_seeds", "pig_market"],
    4: ["cattle_market", "eastern_quarry"],
    5: ["urgent_wish_for_children", "cultivation"],
    6: ["farm_redevelopment"],
}


def _build_stage_of_round() -> dict:
    """Map each round (1–14) to its stage (1–6), derived from STAGE_CARDS
    sizes (4, 3, 2, 2, 2, 1): rounds 1–4 → 1, 5–7 → 2, 8–9 → 3, 10–11 → 4,
    12–13 → 5, 14 → 6."""
    out: dict = {}
    r = 1
    for stage in sorted(STAGE_CARDS):
        for _ in STAGE_CARDS[stage]:
            out[r] = stage
            r += 1
    return out


# Round (1–14) → stage (1–6). Used by the reveal enumerator
# (legality._enumerate_pending_reveal) to find the candidate cards for the
# round being entered.
STAGE_OF_ROUND: dict = _build_stage_of_round()


def stage_of_round(round_number: int) -> int:
    """Stage (1–6) that `round_number` (1–14) belongs to."""
    return STAGE_OF_ROUND[round_number]


# Canonical ordering of all 25 action space IDs. Used to index
# BoardState.action_spaces (a tuple). Permanent spaces first in the order
# they appear in PERMANENT_ACTION_SPACES, then stage cards in stage order.
# The order is fixed across all games — the per-game stage-card shuffle lives
# in the Environment, not in BoardState — so two states reached by different
# paths can compare equal and hash to the same bucket.
SPACE_IDS: tuple[str, ...] = tuple(PERMANENT_ACTION_SPACES) + tuple(
    card_id
    for stage in sorted(STAGE_CARDS)
    for card_id in STAGE_CARDS[stage]
)
SPACE_INDEX: dict[str, int] = {sid: i for i, sid in enumerate(SPACE_IDS)}

# Room costs by current house material. Same shape as MAJOR_IMPROVEMENT_COSTS:
# a static lookup of Resources costs, consumed by both `_can_afford_room`
# (legality) and `_choose_subaction_farm_expansion` (resolution).
ROOM_COSTS: dict[HouseMaterial, Resources] = {
    HouseMaterial.WOOD:  Resources(wood=5,  reed=2),
    HouseMaterial.CLAY:  Resources(clay=5,  reed=2),
    HouseMaterial.STONE: Resources(stone=5, reed=2),
}


# Major improvement indices (0-based, length 10):
# 0: Fireplace (2 clay)
# 1: Fireplace (3 clay)
# 2: Cooking Hearth (4 clay, or return a Fireplace)
# 3: Cooking Hearth (5 clay, or return a Fireplace)
# 4: Well (3 stone + 1 wood)
# 5: Clay Oven (3 clay + 1 stone)
# 6: Stone Oven (1 clay + 3 stone)
# 7: Joinery (2 wood + 2 stone)
# 8: Pottery (2 clay + 2 stone)
# 9: Basketmaker's Workshop (2 reed + 2 stone)
NUM_MAJOR_IMPROVEMENTS = 10

# Major improvement costs, indexed by major_idx (0-9).
# Cooking Hearths (idx 2, 3) have an alternate payment: return a Fireplace.
# That alternate is handled in resolution code, not encoded here.
MAJOR_IMPROVEMENT_COSTS: tuple[Resources, ...] = (
    Resources(clay=2),                # 0: Fireplace (cheap)
    Resources(clay=3),                # 1: Fireplace (expensive)
    Resources(clay=4),                # 2: Cooking Hearth (cheap)
    Resources(clay=5),                # 3: Cooking Hearth (expensive)
    Resources(stone=3, wood=1),       # 4: Well
    Resources(clay=3, stone=1),       # 5: Clay Oven
    Resources(clay=1, stone=3),       # 6: Stone Oven
    Resources(wood=2, stone=2),       # 7: Joinery
    Resources(clay=2, stone=2),       # 8: Pottery
    Resources(reed=2, stone=2),       # 9: Basketmaker's Workshop
)

# Per-action Bake Bread specs by major_idx. (max_grain_per_action, food_per_grain).
# A None cap means "any amount" (Fireplace / Cooking Hearth).
BAKING_IMPROVEMENT_SPECS: dict[int, tuple] = {
    0: (None, 2), 1: (None, 2),       # Fireplaces
    2: (None, 3), 3: (None, 3),       # Cooking Hearths
    5: (1, 5),                         # Clay Oven (exactly 1 grain)
    6: (2, 4),                         # Stone Oven (up to 2 grain)
}

FIREPLACE_INDICES: tuple = (0, 1)
COOKING_HEARTH_INDICES: tuple = (2, 3)
# Migrated here from legality.py for centralized constants.
BAKING_IMPROVEMENTS: frozenset = frozenset(BAKING_IMPROVEMENT_SPECS.keys())

# Building-resource accumulation spaces: maps space_id -> Resources added per round.
# These spaces store accumulated: Resources on ActionSpaceState.
# Cards like the Geologist can override these rates (e.g. adding stone to clay_pit).
BUILDING_ACCUMULATION_RATES: dict[str, Resources] = {
    "forest":         Resources(wood=3),
    "clay_pit":       Resources(clay=1),
    "reed_bank":      Resources(reed=1),
    "western_quarry": Resources(stone=1),
    "eastern_quarry": Resources(stone=1),
}

# Food/animal accumulation spaces: maps space_id -> (field_name, rate_per_round).
# These spaces store accumulated_amount: int on ActionSpaceState (scalar).
# They are never modified by cards in the same way as building-resource spaces.
FOOD_ANIMAL_ACCUMULATION_RATES: dict[str, tuple] = {
    "fishing":       ("food",   1),
    "meeting_place": ("food",   1),   # Family game only
    "sheep_market":  ("sheep",  1),
    "pig_market":    ("boar",   1),
    "cattle_market": ("cattle", 1),
}

# The set of accumulation spaces that card effects count over (Wood Pile, Hand
# Truck, Steam Machine). This is the CARD-game set, which deliberately EXCLUDES
# meeting_place (user ruling 2026-07-02: the exclusion is the owner's edit and is
# correct): in the card game Meeting Place gives no goods (it is become-SP +
# an optional minor), so it is not an accumulation space there. meeting_place IS
# a food-accumulation space in the FAMILY game (see FOOD_ANIMAL_ACCUMULATION_RATES);
# the Family refill machinery iterates the rate dicts directly, never this set, so
# this set has only card-mode consumers — there is nothing to mode-switch at
# runtime. ACCUMULATION_SPACES_FAMILY carries the Family-true set for completeness.
ACCUMULATION_SPACES = (
    frozenset(BUILDING_ACCUMULATION_RATES) | frozenset(FOOD_ANIMAL_ACCUMULATION_RATES)
) - {"meeting_place"}
ACCUMULATION_SPACES_FAMILY = ACCUMULATION_SPACES | {"meeting_place"}

PERMANENT_ACTION_SPACES_SET = frozenset(PERMANENT_ACTION_SPACES)

HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}
NUM_ROUNDS = 14

# Stage boundary: maps stage number -> (first_round, last_round) inclusive
STAGE_ROUNDS = {
    1: (1,  4),
    2: (5,  7),
    3: (8,  9),
    4: (10, 11),
    5: (12, 13),
    6: (14, 14),
}
