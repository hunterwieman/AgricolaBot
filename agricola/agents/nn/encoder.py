"""Input-vector encoder for the first NN value function.

`encode_state(state, player_idx) -> np.ndarray` translates a `GameState`
into the flat ~170-feature vector specified in FIRST_NN.md §4. The output
is a `float32` numpy array — NOT a torch tensor. Keeping the encoder
numpy-only lets the whole `agricola.agents.nn` package stay torch-free
(only the eventual `model.py` imports torch); the training pipeline
converts with `torch.from_numpy(arr)` at the model boundary.

`ENCODING_VERSION` guards the output schema (shape + feature ordering +
semantics). Bump whenever `encode_state` would produce a different output
for the same input state. See FIRST_NN.md §11.4 for the bump policy.

Feature layout (see FIRST_NN.md §4):
- own-player block (54) + opponent block (54) = 108
- shared / board state (54)
- mid-action singletons (8)
- total: 170

Terminal states (`phase == BEFORE_SCORING`) are handled per §4.5: a
`game_end_indicator` bit flips on and a fixed set of next-decision
features is forced to zero.
"""

from __future__ import annotations

import numpy as np

from agricola.agents.base import decider_of
from agricola.constants import (
    HARVEST_ROUNDS,
    NUM_MAJOR_IMPROVEMENTS,
    CellType,
    HouseMaterial,
    Phase,
    SPACE_IDS,
)
from agricola.helpers import can_accommodate, cooking_rates, enclosed_cells, extract_slots
from agricola.pending import (
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildMajor,
    PendingBuildRooms,
    PendingBuildStables,
    PendingClayOven,
    PendingCultivation,
    PendingFarmExpansion,
    PendingFarmland,
    PendingFarmRedevelopment,
    PendingFencing,
    PendingGrainUtilization,
    PendingHarvestFeed,
    PendingHouseRedevelopment,
    PendingMajorMinorImprovement,
    PendingPlow,
    PendingSideJob,
    PendingSow,
    PendingStoneOven,
)
from agricola.state import GameState, PlayerState, get_space

# ---------------------------------------------------------------------------
# Version + dimension
# ---------------------------------------------------------------------------

ENCODING_VERSION: int = 2
"""Input-vector schema version. Stamped into model metadata sidecars at
training time. Bump on any change to `encode_state`'s output for the same
input. See FIRST_NN.md §10.4.

Changelog:
- v2: `current_player_is_own` now uses `decider_of(state)` (the pending-
  stack-aware decider rule) instead of raw `state.current_player`. The
  raw value is stale during harvest sub-phases (FEED, BREED) and during
  any out-of-turn trigger frame, so v1 silently encoded the wrong
  "whose turn is it" signal for ~15% of training snapshots.
- v1: initial encoder per FIRST_NN.md §4."""

ENCODED_DIM: int = 170
"""Length of the vector `encode_state` returns. Asserted at the end of
every call to catch off-by-N feature bugs immediately."""


# ---------------------------------------------------------------------------
# Constants for sub-vectors
# ---------------------------------------------------------------------------

# The 7 sub-action categories for `subaction_available` (FIRST_NN.md §4.3).
_SUBACTION_CATEGORIES: tuple[str, ...] = (
    "build_rooms", "build_stables", "plow", "bake_bread",
    "sow", "build_fences", "build_major",
)

# The 10 accumulation spaces, in a fixed order (FIRST_NN.md §4.2).
_ACCUMULATION_SPACES: tuple[str, ...] = (
    "forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry",
    "fishing", "meeting_place", "sheep_market", "pig_market", "cattle_market",
)

# The 14 stage-card spaces are SPACE_IDS after the 11 permanent spaces.
# (PERMANENT_ACTION_SPACES has 11 entries; the remaining 14 are stage cards.)
_STAGE_CARD_IDS: tuple[str, ...] = SPACE_IDS[11:]

_HARVEST_PHASES = frozenset({
    Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED,
})

# Feature names (own-/opp-prefixed where per-player) whose values are forced
# to zero at terminal states (FIRST_NN.md §4.5). `subaction_avail_*` and
# `space_available_*` are handled by prefix below.
_TERMINAL_ZERO_NAMES: frozenset = frozenset({
    "own_family_left", "opp_family_left",
    "own_food_owed", "opp_food_owed",
    "own_has_fed", "opp_has_fed",
    "own_future_food", "opp_future_food",
    "current_player_is_own",
    "in_harvest",
    "rounds_until_next_harvest",
    "stop_is_legal",
})


# ---------------------------------------------------------------------------
# Per-player block
# ---------------------------------------------------------------------------

def _player_features(
    state: GameState, p: PlayerState, player_idx: int,
) -> list[tuple[str, float]]:
    """Build the 54-feature per-player block as (name, value) pairs.
    Names are bare (no own_/opp_ prefix); the caller prefixes them."""
    feats: list[tuple[str, float]] = []

    # --- Resources (5) ---
    r = p.resources
    feats += [
        ("wood", float(r.wood)), ("clay", float(r.clay)),
        ("reed", float(r.reed)), ("stone", float(r.stone)),
        ("food", float(r.food)),
    ]

    # --- Granular crop encoding (cells) ---
    grain3 = grain2 = grain1 = veg2 = veg1 = empty_plowed = 0
    for row in p.farmyard.grid:
        for cell in row:
            if cell.cell_type is not CellType.FIELD:
                continue
            if cell.grain > 0:
                if cell.grain >= 3:
                    grain3 += 1
                elif cell.grain == 2:
                    grain2 += 1
                else:
                    grain1 += 1
            elif cell.veg > 0:
                if cell.veg >= 2:
                    veg2 += 1
                else:
                    veg1 += 1
            else:
                empty_plowed += 1
    feats += [
        ("grain_fields_3", float(grain3)),
        ("grain_fields_2", float(grain2)),
        ("grain_fields_1", float(grain1)),
        ("veg_fields_2", float(veg2)),
        ("veg_fields_1", float(veg1)),
        ("empty_plowed_fields", float(empty_plowed)),
    ]

    # --- Supply crops (2) ---
    feats += [("grain_supply", float(r.grain)), ("veg_supply", float(r.veg))]

    # --- Pasture capacities (5, sorted desc, pad 0) + wildcards (1) ---
    caps, flex = extract_slots(p)
    caps_sorted = sorted(caps, reverse=True)[:5]
    caps_padded = (caps_sorted + [0, 0, 0, 0, 0])[:5]
    feats += [(f"pasture_cap_{i}", float(caps_padded[i])) for i in range(5)]
    feats.append(("animal_slot_wildcards", float(flex)))

    # --- Fenced stables (1) ---
    n_fenced = sum(past.num_stables for past in p.farmyard.pastures)
    feats.append(("fenced_stables", float(n_fenced)))

    # --- Animals (3) ---
    s, b, c = p.animals.sheep, p.animals.boar, p.animals.cattle
    feats += [("sheep", float(s)), ("boar", float(b)), ("cattle", float(c))]

    # --- Rooms split (3) ---
    n_rooms = sum(
        1 for row in p.farmyard.grid for cell in row
        if cell.cell_type is CellType.ROOM
    )
    feats += [
        ("wood_rooms", float(n_rooms if p.house_material is HouseMaterial.WOOD else 0)),
        ("clay_rooms", float(n_rooms if p.house_material is HouseMaterial.CLAY else 0)),
        ("stone_rooms", float(n_rooms if p.house_material is HouseMaterial.STONE else 0)),
    ]

    # --- People / family / food_owed (3) ---
    family_left = p.people_home if state.phase is Phase.WORK else 0
    if state.round_number in HARVEST_ROUNDS:
        food_owed = 2 * p.people_total - p.newborns
    else:
        food_owed = 2 * p.people_total
    feats += [
        ("people", float(p.people_total)),
        ("family_left", float(family_left)),
        ("food_owed", float(food_owed)),
    ]

    # --- Begging markers (1) + unused cells (1) ---
    feats.append(("begging_markers", float(p.begging_markers)))
    enc = enclosed_cells(p.farmyard)
    n_unused = 0
    for ri, row in enumerate(p.farmyard.grid):
        for ci, cell in enumerate(row):
            if cell.cell_type is CellType.EMPTY and (ri, ci) not in enc:
                n_unused += 1
    feats.append(("unused_cells", float(n_unused)))

    # --- Cooking rates (4) ---
    sr, br, cr, vr = cooking_rates(state, player_idx)
    feats += [
        ("cook_sheep", float(sr)), ("cook_boar", float(br)),
        ("cook_cattle", float(cr)), ("cook_veg", float(vr)),
    ]

    # --- Majors owned (10) ---
    owners = state.board.major_improvement_owners
    for mi in range(NUM_MAJOR_IMPROVEMENTS):
        feats.append((f"major_{mi}", 1.0 if owners[mi] == player_idx else 0.0))

    # --- Breeding-pair indicators (3, INDEPENDENT per FIRST_NN.md §4.1) ---
    # Each type checked as if it's the only one breeding: 2+ of that type AND
    # the farm can accommodate one more of it (its 2 parents + 1 newborn).
    feats += [
        ("breed_sheep", 1.0 if (s >= 2 and can_accommodate(caps, flex, s + 1, b, c)) else 0.0),
        ("breed_boar", 1.0 if (b >= 2 and can_accommodate(caps, flex, s, b + 1, c)) else 0.0),
        ("breed_cattle", 1.0 if (c >= 2 and can_accommodate(caps, flex, s, b, c + 1)) else 0.0),
    ]

    # --- Harvest-conversions-used (3) ---
    hcu = p.harvest_conversions_used
    feats += [
        ("conv_joinery", 1.0 if "joinery" in hcu else 0.0),
        ("conv_pottery", 1.0 if "pottery" in hcu else 0.0),
        ("conv_basketmaker", 1.0 if "basketmaker" in hcu else 0.0),
    ]

    # --- is_starting_player (1) ---
    feats.append(("is_starting_player", 1.0 if state.starting_player == player_idx else 0.0))

    # --- has_fed (1) ---
    if state.phase is Phase.HARVEST_BREED:
        has_fed = 1.0
    elif state.phase is Phase.HARVEST_FEED:
        still_to_feed = any(
            isinstance(f, PendingHarvestFeed) and f.player_idx == player_idx
            for f in state.pending_stack
        )
        has_fed = 0.0 if still_to_feed else 1.0
    else:
        has_fed = 0.0
    feats.append(("has_fed", has_fed))

    # --- future_food_from_round_spaces (1) ---
    # future_resources entries are cleared on collection (engine prep phase),
    # so summing the food across all entries gives the still-pending total.
    feats.append(("future_food", float(sum(fr.food for fr in p.future_resources))))

    return feats


# ---------------------------------------------------------------------------
# Shared / board block
# ---------------------------------------------------------------------------

def _accum_amount(space_state) -> int:
    """Scalar goods on an accumulation space. Building spaces store a
    Resources (single resource type nonzero); food/animal spaces use the
    scalar `accumulated_amount`. A space uses one or the other, so summing
    both gives the right total."""
    res = space_state.accumulated
    res_total = (res.wood + res.clay + res.reed + res.stone
                 + res.food + res.grain + res.veg)
    return res_total + space_state.accumulated_amount


def _shared_features(state: GameState, player_idx: int) -> list[tuple[str, float]]:
    """Build the 54-feature shared/board block as (name, value) pairs."""
    feats: list[tuple[str, float]] = []
    board = state.board
    rn = state.round_number

    feats.append(("round_number", float(rn)))
    # `decider_of(state)` (top-of-stack `player_idx` if non-empty, else
    # `state.current_player`) is the canonical "who is to act now?" query.
    # Using raw `state.current_player` here is wrong during harvest
    # sub-phases — `_initiate_harvest_feed` / `_initiate_harvest_breed`
    # push pendings whose `player_idx` reflects the FEED/BREED order but
    # leave `state.current_player` stale from the last WORK action.
    feats.append(("current_player_is_own", 1.0 if decider_of(state) == player_idx else 0.0))
    feats.append(("in_harvest", 1.0 if state.phase in _HARVEST_PHASES else 0.0))

    # rounds_until_next_harvest: 0 on a harvest round, else distance to next.
    upcoming = [h - rn for h in HARVEST_ROUNDS if h >= rn]
    feats.append(("rounds_until_next_harvest", float(min(upcoming)) if upcoming else 0.0))

    # Accumulation amounts (10).
    for sid in _ACCUMULATION_SPACES:
        feats.append((f"accum_{sid}", float(_accum_amount(get_space(board, sid)))))

    # Stage cards revealed (14): round_revealed <= current round.
    for sid in _STAGE_CARD_IDS:
        sp = get_space(board, sid)
        feats.append((f"revealed_{sid}", 1.0 if sp.round_revealed <= rn else 0.0))

    # Space available now (25): revealed AND not occupied this round.
    for sid in SPACE_IDS:
        sp = get_space(board, sid)
        revealed = sp.round_revealed <= rn  # round_revealed=0 (permanent) always passes
        unoccupied = sum(sp.workers) == 0
        feats.append((f"space_avail_{sid}", 1.0 if (revealed and unoccupied) else 0.0))

    # Game-end indicator (1).
    feats.append(("game_end_indicator", 1.0 if state.phase is Phase.BEFORE_SCORING else 0.0))

    return feats


# ---------------------------------------------------------------------------
# Mid-action block
# ---------------------------------------------------------------------------

def _frame_subaction_categories(frame) -> list[str]:
    """Which of the 7 sub-action categories this pending frame contributes
    (FIRST_NN.md §4.3). Parent pendings contribute their UNCHOSEN
    categories; sub-action pendings contribute their own (still-resolving)
    category. Renovate / family-growth / animal-market / harvest pendings
    contribute nothing (see §4.3 exclusions).

    **Singleton-skip and "dead-in-practice" branches.** Some parent
    pendings host only one sub-action (`PendingFarmland` → plow only,
    `PendingFencing` → build_fences only). For these, the
    `ChooseSubAction` is a singleton and is resolved by the
    `HeuristicAgent` / MCTS singleton-skip wrapper without ever invoking
    the agent — so by the time any agent decision involves these
    parents, their `*_chosen` flag is already `True`. The
    `else "plow"` / `else "build_fences"` branches here are therefore
    UNREACHABLE in any singleton-skip-aware caller (training data,
    MCTS leaves, NNAgent inference). They're kept in the dispatch
    because the encoder is a structural `state -> vector` function
    and shouldn't bake in caller-side singleton-skip assumptions —
    hand-constructed test states or future non-singleton-skip callers
    would otherwise get a structurally wrong answer.

    **Forward-compatibility caveat for cards (out of scope today).**
    The "renovate" and "family_growth" exclusions assume those
    sub-actions auto-resolve before the agent decides — true in the
    current Family-game flow (`PendingRenovate` is always preceded by
    a mandatory parent's renovate-first contract; family-growth
    commits are singletons). When cards introduce "before renovate"
    or "before family growth" triggers, those parents become visible
    to the agent with their flags `False`, and these categories may
    need to be added to the tracked list and dispatched here.
    Adding card support is a separate phase (FIRST_NN.md §1.2);
    when it lands the encoder is expected to be revised — likely as
    a new `ENCODING_VERSION` and a parallel encoder module, not as
    in-place edits to this function.
    """
    # --- Parent pendings: unchosen categories ---
    if isinstance(frame, PendingGrainUtilization):
        out = []
        if not frame.sow_chosen:
            out.append("sow")
        if not frame.bake_chosen:
            out.append("bake_bread")
        return out
    if isinstance(frame, PendingFarmExpansion):
        out = []
        if not frame.room_chosen:
            out.append("build_rooms")
        if not frame.stable_chosen:
            out.append("build_stables")
        return out
    if isinstance(frame, PendingFarmland):
        return [] if frame.plow_chosen else ["plow"]
    if isinstance(frame, PendingCultivation):
        out = []
        if not frame.plow_chosen:
            out.append("plow")
        if not frame.sow_chosen:
            out.append("sow")
        return out
    if isinstance(frame, PendingSideJob):
        out = []
        if not frame.stable_chosen:
            out.append("build_stables")
        if not frame.bake_chosen:
            out.append("bake_bread")
        return out
    if isinstance(frame, PendingHouseRedevelopment):
        # renovate excluded (mandatory-first); optional second part can be a major.
        return [] if frame.improvement_chosen else ["build_major"]
    if isinstance(frame, PendingFarmRedevelopment):
        # renovate excluded; optional second part is Build Fences.
        return [] if frame.build_fences_chosen else ["build_fences"]
    if isinstance(frame, PendingMajorMinorImprovement):
        return [] if frame.major_chosen else ["build_major"]
    if isinstance(frame, (PendingClayOven, PendingStoneOven)):
        return [] if frame.bake_chosen else ["bake_bread"]
    if isinstance(frame, PendingFencing):
        return [] if frame.build_fences_chosen else ["build_fences"]
    # --- Sub-action pendings: own action (mid-resolving) ---
    if isinstance(frame, PendingSow):
        return ["sow"]
    if isinstance(frame, PendingBakeBread):
        return ["bake_bread"]
    if isinstance(frame, PendingPlow):
        return ["plow"]
    if isinstance(frame, PendingBuildStables):
        return ["build_stables"]
    if isinstance(frame, PendingBuildRooms):
        return ["build_rooms"]
    if isinstance(frame, PendingBuildMajor):
        return ["build_major"]
    if isinstance(frame, PendingBuildFences):
        return ["build_fences"]
    # PendingRenovate, market pendings, harvest pendings: nothing.
    return []


def _midaction_features(state: GameState) -> list[tuple[str, float]]:
    """Build the 8-feature mid-action block: `subaction_available` (7) +
    `stop_is_legal` (1). OR-ed across the full pending stack (§4.3)."""
    bits = dict.fromkeys(_SUBACTION_CATEGORIES, 0.0)
    for frame in state.pending_stack:
        for cat in _frame_subaction_categories(frame):
            bits[cat] = 1.0
    feats = [(f"subaction_avail_{cat}", bits[cat]) for cat in _SUBACTION_CATEGORIES]

    # stop_is_legal: deferred legality import to avoid an import cycle
    # (legality imports widely across the engine).
    from agricola.legality import legal_actions
    from agricola.actions import Stop
    stop_legal = any(isinstance(a, Stop) for a in legal_actions(state))
    feats.append(("stop_is_legal", 1.0 if stop_legal else 0.0))
    return feats


# ---------------------------------------------------------------------------
# Public assembly
# ---------------------------------------------------------------------------

def _assemble(state: GameState, player_idx: int) -> list[tuple[str, float]]:
    """Assemble the full (name, value) feature list in canonical order.
    Applies terminal-state zeroing (§4.5)."""
    own = state.players[player_idx]
    opp = state.players[1 - player_idx]

    pairs: list[tuple[str, float]] = []
    pairs += [(f"own_{n}", v) for n, v in _player_features(state, own, player_idx)]
    pairs += [(f"opp_{n}", v) for n, v in _player_features(state, opp, 1 - player_idx)]
    pairs += _shared_features(state, player_idx)
    pairs += _midaction_features(state)

    if state.phase is Phase.BEFORE_SCORING:
        # Zero next-decision features; game_end_indicator stays 1.
        zeroed = []
        for name, val in pairs:
            if name in _TERMINAL_ZERO_NAMES or name.startswith("subaction_avail_"):
                zeroed.append((name, 0.0))
            else:
                zeroed.append((name, val))
        pairs = zeroed

    return pairs


def encode_state(state: GameState, player_idx: int) -> np.ndarray:
    """Encode `state` from `player_idx`'s perspective into a flat
    `float32` feature vector of length `ENCODED_DIM` (FIRST_NN.md §4).

    The own-player block reflects `player_idx`; the opponent block
    reflects `1 - player_idx`. Shared features that are perspective-
    relative (e.g., `current_player_is_own`, `is_starting_player`) are
    computed against `player_idx`.

    Returns a numpy array (NOT a torch tensor); the training pipeline
    converts with `torch.from_numpy`.
    """
    pairs = _assemble(state, player_idx)
    vec = np.fromiter((v for _, v in pairs), dtype=np.float32, count=len(pairs))
    assert vec.shape[0] == ENCODED_DIM, (
        f"encode_state produced {vec.shape[0]} features, expected "
        f"{ENCODED_DIM}. Feature-list drift — update ENCODED_DIM and bump "
        f"ENCODING_VERSION if this is an intentional schema change."
    )
    return vec


def feature_names(state: GameState | None = None) -> list[str]:
    """Return the ordered feature names (length `ENCODED_DIM`). Useful for
    debugging, golden tests, and feature-importance analysis. Names are
    structural (independent of state values); pass any state, or omit to
    build from a fresh `setup(0)`."""
    if state is None:
        from agricola.setup import setup
        state = setup(0)
    return [name for name, _ in _assemble(state, 0)]
