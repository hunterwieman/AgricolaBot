from enum import Enum, auto

from agricola.resources import Resources


class Phase(Enum):
    WORK = auto()
    RETURN_HOME = auto()
    PREPARATION = auto()
    HARVEST_FIELD = auto()
    HARVEST_FEED = auto()
    HARVEST_BREED = auto()
    BEFORE_SCORING = auto()


class HouseMaterial(Enum):
    WOOD = auto()
    CLAY = auto()
    STONE = auto()


class CellType(Enum):
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

# Combined set of all accumulation space IDs — derived, never duplicated:
ACCUMULATION_SPACES = frozenset(BUILDING_ACCUMULATION_RATES) | frozenset(FOOD_ANIMAL_ACCUMULATION_RATES)

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
