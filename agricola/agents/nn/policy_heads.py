"""Per-decision-type policy head specs (POLICY_HEAD.md §3).

A `DecisionHead` factors the policy into one head per *type* of decision. Each
head declares:

- **`owns(state)`** — does this head own the decision at `state`? (a predicate on
  the pending-stack top, matching the engine's stack-typed decision points).
- **`vocab`** — the ordered output class labels (index = class id).
- **`target_index(action)`** — map a recorded `chosen_action` to its class index
  (or `None` if the action isn't one of this head's classes).
- **`legal_mask(state, legal_actions_fn)`** — the bool mask over `vocab` of the
  classes that are legal at `state`.

The dataset / model / training / inference code is driven by a head spec, so
adding a head is *data* (a new head object), not new modules.

**Fixed-vocab heads** (`DecisionHead`, in `HEADS`):

- **`PLACEMENT_HEAD`** — the empty-stack worker-placement decision (25-way over
  `SPACE_IDS`).
- **`CHOOSE_SUBACTION_HEAD`** — the parent-pending "which sub-action, or stop?"
  decision (8-way). `build_stable` merged into `build_stables`; `Stop` is a class
  (`STOP_LABEL`); `build_major`/`renovate` excluded (structurally singleton);
  `plow`/`build_rooms` included since the forced-ordering filters were dropped.
- **`COMMIT_BUILD_MAJOR_HEAD`** — "which major to buy" (14-way).
- **`COMMIT_SOW_HEAD`** — sow `(grain, veg)` amount (104-way, `1 ≤ g+v ≤ 13`).
- **`COMMIT_BAKE_HEAD`** — bake `grain` amount (6-way, `grain ∈ 1..6`).
- **`FENCING_HEAD`** — which pasture shape to build, or Stop (110-way: the 109
  RESTRICTED fence-universe shapes + Stop). Spatially blind (see its section).
- **`BUILD_STOP_HEAD`** — learned `P(stop)` at multi-shot Build Rooms / Build
  Stables (2-way build-vs-stop; `policy.py`'s combiner expands `build` onto the
  cell-priority cell). NOT routed through the generic fixed-head path.

**Pointer heads** (`PointerHead`, in `POINTER_HEADS`) — for the variable-
cardinality Pareto-frontier commits, where a fixed vocab doesn't apply:

- **`ANIMAL_FRONTIER_HEAD`** — `CommitBreed` (harvest) + `CommitAccommodate`
  (animal markets); scores each `(sheep, boar, cattle, food_gained)` frontier point.
- **`HARVEST_FEED_HEAD`** — `CommitConvert` + `CommitHarvestConversion` (the
  heterogeneous feed set); 10-dim tagged-union Δ. See each head's section below.

Torch-free; imported by the (torch-using) dataset/model/policy modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitSow,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.fences import UNIVERSE_RESTRICTED_ENTRIES
from agricola.agents.base import decider_of
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import (
    COOKING_HEARTH_INDICES,
    FIREPLACE_INDICES,
    MAJOR_IMPROVEMENT_COSTS,
    SPACE_IDS,
    Phase,
)
from agricola.pending import (
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildMajor,
    PendingBuildRooms,
    PendingBuildStables,
    PendingCattleMarket,
    PendingCultivation,
    PendingFarmExpansion,
    PendingFarmRedevelopment,
    PendingGrainUtilization,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingHouseRedevelopment,
    PendingPigMarket,
    PendingSheepMarket,
    PendingSideJob,
    PendingSow,
)
from tests.test_utils import filter_implemented

# Parent pendings whose decision is "pick a ChooseSubAction category, or Stop".
_PARENT_PENDINGS = (
    PendingGrainUtilization,
    PendingCultivation,
    PendingSideJob,
    PendingFarmExpansion,
    PendingHouseRedevelopment,
    PendingFarmRedevelopment,
)

# Normalize the `build_stable` alias into `build_stables` (POLICY_HEAD.md §5).
_SUBACTION_ALIAS = {"build_stable": "build_stables"}

# The `Stop` option as a class label in the ChooseSubAction head.
STOP_LABEL = "__stop__"


@dataclass(frozen=True)
class DecisionHead:
    """A factored policy head over one decision type. See module docstring."""

    name: str
    vocab: tuple[str, ...]
    owns: Callable                  # (state) -> bool
    _label_of_action: Callable      # (action) -> str | None
    _legal_labels: Callable         # (state, legal_actions_fn) -> set[str]
    _index: dict = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_index", {lab: i for i, lab in enumerate(self.vocab)})

    @property
    def num_classes(self) -> int:
        return len(self.vocab)

    def target_index(self, action: Action) -> int | None:
        """Class index for a recorded `chosen_action`, or None if not ours."""
        lab = self._label_of_action(action)
        return None if lab is None else self._index.get(lab)

    def legal_mask(
        self, state, legal_actions_fn=restricted_legal_actions,
    ) -> np.ndarray:
        """Bool mask over `vocab` of the classes legal at `state`."""
        mask = np.zeros(self.num_classes, dtype=bool)
        for lab in self._legal_labels(state, legal_actions_fn):
            i = self._index.get(lab)
            if i is not None:
                mask[i] = True
        return mask


# ---------------------------------------------------------------------------
# Placement head
# ---------------------------------------------------------------------------


def _placement_owns(state) -> bool:
    return (
        state.phase != Phase.BEFORE_SCORING
        and not state.pending_stack
        and decider_of(state) is not None
    )


def _placement_label(action: Action) -> str | None:
    return action.space if isinstance(action, PlaceWorker) else None


def _placement_legal_labels(state, legal_actions_fn) -> set[str]:
    return {
        a.space for a in filter_implemented(legal_actions_fn(state))
        if isinstance(a, PlaceWorker)
    }


PLACEMENT_HEAD = DecisionHead(
    name="placement",
    vocab=tuple(SPACE_IDS),
    owns=_placement_owns,
    _label_of_action=_placement_label,
    _legal_labels=_placement_legal_labels,
)


# ---------------------------------------------------------------------------
# ChooseSubAction head
# ---------------------------------------------------------------------------

CHOOSE_SUBACTION_VOCAB = (
    "sow",
    "bake_bread",
    "build_stables",
    "build_rooms",
    "plow",
    "build_fences",
    "improvement",
    STOP_LABEL,
)


def _subaction_owns(state) -> bool:
    return bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], _PARENT_PENDINGS
    )


def _subaction_label(action: Action) -> str | None:
    if isinstance(action, ChooseSubAction):
        return _SUBACTION_ALIAS.get(action.name, action.name)
    # Proceed-as-Stop alias (SPACE_HOST_REFACTOR.md §9): the and/or & and-then
    # parents now end their before-phase with Proceed instead of Stop. Both are
    # the "done with this space" action and never co-legal, so mapping Proceed to
    # the head's STOP_LABEL slot keeps pre- and post-refactor data aligned (no
    # relabel/retrain) and lets the MCTS prior treat Proceed exactly as Stop.
    if isinstance(action, (Stop, Proceed)):
        return STOP_LABEL
    return None


def _subaction_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        if isinstance(a, ChooseSubAction):
            labels.add(_SUBACTION_ALIAS.get(a.name, a.name))
        elif isinstance(a, (Stop, Proceed)):   # Proceed-as-Stop alias (§9)
            labels.add(STOP_LABEL)
    return labels


CHOOSE_SUBACTION_HEAD = DecisionHead(
    name="choose_subaction",
    vocab=CHOOSE_SUBACTION_VOCAB,
    owns=_subaction_owns,
    _label_of_action=_subaction_label,
    _legal_labels=_subaction_legal_labels,
)


# ---------------------------------------------------------------------------
# CommitBuildMajor head
# ---------------------------------------------------------------------------
#
# "Which major improvement to buy." A class per distinct (major_idx,
# return_fireplace_idx) — the 8 non-Cooking-Hearth majors pay full
# (return_fireplace=None), and the 2 Cooking Hearths (COOKING_HEARTH_INDICES)
# may pay full OR return either Fireplace (FIREPLACE_INDICES) for a discount.
# 10 majors + 2 hearths × 2 return options = 14 classes.


def _major_label(action: Action) -> str | None:
    if not isinstance(action, CommitBuildMajor):
        return None
    if action.return_fireplace_idx is None:
        return f"m{action.major_idx}"
    return f"m{action.major_idx}_rf{action.return_fireplace_idx}"


def _build_major_vocab() -> tuple[str, ...]:
    labels: list[str] = []
    for mi in range(len(MAJOR_IMPROVEMENT_COSTS)):
        labels.append(f"m{mi}")
        if mi in COOKING_HEARTH_INDICES:
            for fp in FIREPLACE_INDICES:
                labels.append(f"m{mi}_rf{fp}")
    return tuple(labels)


COMMIT_BUILD_MAJOR_VOCAB = _build_major_vocab()


def _major_owns(state) -> bool:
    return bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], PendingBuildMajor
    )


def _major_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        lab = _major_label(a)
        if lab is not None:
            labels.add(lab)
    return labels


COMMIT_BUILD_MAJOR_HEAD = DecisionHead(
    name="commit_build_major",
    vocab=COMMIT_BUILD_MAJOR_VOCAB,
    owns=_major_owns,
    _label_of_action=_major_label,
    _legal_labels=_major_legal_labels,
)


# ---------------------------------------------------------------------------
# CommitSow head — (grain, veg) amount at PendingSow
# ---------------------------------------------------------------------------
#
# Fixed vocab over `(grain, veg)` pairs with 1 ≤ grain+veg ≤ 13. The bound is
# provably comprehensive: a player always has ≥2 rooms ⇒ ≤13 field cells ⇒
# grain+veg ≤ empty_fields ≤ 13 (legality.py). (Observed data max is only 4, so
# the vocab is sparse but the high-sum classes are simply never legal/selected.)

SOW_MAX_SUM = 13


def _sow_vocab() -> tuple[str, ...]:
    return tuple(
        f"g{g}v{s - g}" for s in range(1, SOW_MAX_SUM + 1) for g in range(s + 1)
    )


COMMIT_SOW_VOCAB = _sow_vocab()       # 104 classes


def _sow_owns(state) -> bool:
    return bool(state.pending_stack) and isinstance(state.pending_stack[-1], PendingSow)


def _sow_label(action: Action) -> str | None:
    if isinstance(action, CommitSow) and 1 <= action.grain + action.veg <= SOW_MAX_SUM:
        return f"g{action.grain}v{action.veg}"
    return None


def _sow_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        lab = _sow_label(a)
        if lab is not None:
            labels.add(lab)
    return labels


COMMIT_SOW_HEAD = DecisionHead(
    name="commit_sow",
    vocab=COMMIT_SOW_VOCAB,
    owns=_sow_owns,
    _label_of_action=_sow_label,
    _legal_labels=_sow_legal_labels,
)


# ---------------------------------------------------------------------------
# CommitBake head — grain amount at PendingBakeBread
# ---------------------------------------------------------------------------
#
# Fixed vocab over `grain ∈ 1..6`. NOT provably comprehensive (with an uncapped
# oven the legal max is the grain supply), but the observed data max is 5 and
# baking >6 is essentially never correct (grain scores points), so a rare
# grain>6 option simply gets pruned at inference (prior 0).

COMMIT_BAKE_MAX = 6
COMMIT_BAKE_VOCAB = tuple(f"n{n}" for n in range(1, COMMIT_BAKE_MAX + 1))


def _bake_owns(state) -> bool:
    return bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], PendingBakeBread
    )


def _bake_label(action: Action) -> str | None:
    if isinstance(action, CommitBake) and 1 <= action.grain <= COMMIT_BAKE_MAX:
        return f"n{action.grain}"
    return None


def _bake_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        lab = _bake_label(a)
        if lab is not None:
            labels.add(lab)
    return labels


COMMIT_BAKE_HEAD = DecisionHead(
    name="commit_bake",
    vocab=COMMIT_BAKE_VOCAB,
    owns=_bake_owns,
    _label_of_action=_bake_label,
    _legal_labels=_bake_legal_labels,
)


# ---------------------------------------------------------------------------
# Fencing head — which pasture shape to build (or Stop) at PendingBuildFences
# ---------------------------------------------------------------------------
#
# A fixed head over the RESTRICTED fence universe (the engine's default active
# universe, `fences.py`): 109 pasture-shape classes + a Stop class = 110. NOTE:
# the output classes are spatial (specific cell-sets) but the encoder carries NO
# spatial features, so this is an experiment in whether a spatially-blind head can
# still pick reasonable shapes — it leans on the legal mask + learned canonical-
# shape preferences. Trained with FULL legality (no restricted/strict wrapper), so
# the head considers every farm-legal shape, not the wrapper-narrowed subset.
# Stop is a class so the head also learns *when to stop* fencing (multi-shot).

_FENCE_SHAPES = tuple(e.cells for e in UNIVERSE_RESTRICTED_ENTRIES)   # 109 frozensets
_FENCE_INDEX = {cells: i for i, cells in enumerate(_FENCE_SHAPES)}
FENCING_VOCAB = tuple(f"p{i}" for i in range(len(_FENCE_SHAPES))) + (STOP_LABEL,)  # 110


def _fencing_owns(state) -> bool:
    return bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], PendingBuildFences
    )


def _fencing_label(action: Action) -> str | None:
    if isinstance(action, CommitBuildPasture):
        i = _FENCE_INDEX.get(action.cells)
        return None if i is None else f"p{i}"
    if isinstance(action, Stop):
        return STOP_LABEL
    return None


def _fencing_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        lab = _fencing_label(a)
        if lab is not None:
            labels.add(lab)
    return labels


FENCING_HEAD = DecisionHead(
    name="fencing",
    vocab=FENCING_VOCAB,
    owns=_fencing_owns,
    _label_of_action=_fencing_label,
    _legal_labels=_fencing_legal_labels,
)


# ---------------------------------------------------------------------------
# build_stop head — learned P(stop) at multi-shot Build Rooms / Build Stables
# ---------------------------------------------------------------------------
#
# At PendingBuildRooms / PendingBuildStables with `num_built >= 1` (⟺ Stop is
# legal), the decision is "build another, or stop". The *which cell* part has no
# encoder signal (handled by cell-priority uniform), but *when to stop* IS
# learnable from the non-spatial state (current rooms/stables, resources, round —
# and the encoder's `subaction_avail_build_rooms/stables` flags distinguish the
# two). So this 2-class head learns P(build) vs P(stop), replacing the crude
# uniform 50/50 the cell-priority fallback gives. `policy.py`'s combiner expands
# the `build` class onto the cell-priority cell: {cell: P(build), Stop: P(stop)}.
# NOTE: fencing is intentionally NOT covered here — it keeps its own 110-class head.

BUILD_LABEL = "__build__"
BUILD_STOP_VOCAB = (BUILD_LABEL, STOP_LABEL)
_BUILD_STOP_PENDINGS = (PendingBuildRooms, PendingBuildStables)


def _build_stop_owns(state) -> bool:
    if not state.pending_stack:
        return False
    top = state.pending_stack[-1]
    return isinstance(top, _BUILD_STOP_PENDINGS) and top.num_built >= 1


def _build_stop_label(action: Action) -> str | None:
    if isinstance(action, (CommitBuildRoom, CommitBuildStable)):
        return BUILD_LABEL
    if isinstance(action, Stop):
        return STOP_LABEL
    return None


def _build_stop_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        lab = _build_stop_label(a)
        if lab is not None:
            labels.add(lab)
    return labels


BUILD_STOP_HEAD = DecisionHead(
    name="build_stop",
    vocab=BUILD_STOP_VOCAB,
    owns=_build_stop_owns,
    _label_of_action=_build_stop_label,
    _legal_labels=_build_stop_legal_labels,
)


# Registry — name → head, for the dataset/training/CLI dispatch.
HEADS: dict[str, DecisionHead] = {
    PLACEMENT_HEAD.name: PLACEMENT_HEAD,
    CHOOSE_SUBACTION_HEAD.name: CHOOSE_SUBACTION_HEAD,
    COMMIT_BUILD_MAJOR_HEAD.name: COMMIT_BUILD_MAJOR_HEAD,
    COMMIT_SOW_HEAD.name: COMMIT_SOW_HEAD,
    COMMIT_BAKE_HEAD.name: COMMIT_BAKE_HEAD,
    FENCING_HEAD.name: FENCING_HEAD,
    BUILD_STOP_HEAD.name: BUILD_STOP_HEAD,
}


# ---------------------------------------------------------------------------
# Pointer heads — score-the-legal-set, for variable-cardinality frontiers
# ---------------------------------------------------------------------------
#
# The Pareto-frontier commits (CommitBreed / CommitAccommodate / CommitConvert)
# don't map to a fixed vocabulary: the legal set is a different, state-dependent
# list of frontier points each time. So instead of classifying into a fixed
# vocab, a PointerHead featurizes EACH enumerated legal commit (a small
# action-delta) and the model scores each candidate, softmaxing over the legal
# set (POLICY_HEAD.md §11). The decision-relevant context (current supply /
# animals / capacity / food need) rides along in the shared state encoding the
# scorer also sees, so the per-candidate features only carry what *differs*
# between options.
#
# Interface (vs DecisionHead's fixed `vocab` / `target_index` / `legal_mask`):
#   - `owns(state)`                  — same role (pending-top predicate).
#   - `enumerate_candidates(state)`  — [(action, feature_vec)] in a STABLE order,
#                                      one entry per legal commit (must match the
#                                      engine's enumerator order so positions are
#                                      well-defined).
#   - `candidate_dim`                — width of each feature_vec.
#   - `candidates` / `candidate_features` / `target_position` derive from it.


@dataclass(frozen=True)
class PointerHead:
    """A score-the-legal-set policy head over one variable-cardinality decision
    type. See the section docstring."""

    name: str
    candidate_dim: int
    owns: Callable                  # (state) -> bool
    _enumerate: Callable            # (state) -> list[(Action, np.ndarray[candidate_dim])]

    def enumerate_candidates(self, state) -> list:
        """`[(action, feature_vec)]` for every legal commit, in stable order."""
        return self._enumerate(state)

    def candidates(self, state) -> list:
        return [a for a, _ in self._enumerate(state)]

    def candidate_features(self, state) -> np.ndarray:
        """`(K, candidate_dim)` float32 — the per-candidate feature rows."""
        feats = [f for _, f in self._enumerate(state)]
        if not feats:
            return np.zeros((0, self.candidate_dim), dtype=np.float32)
        return np.stack(feats).astype(np.float32)

    def target_position(self, state, action: Action) -> int | None:
        """Index of `action` among the legal candidates, or None if not present."""
        for i, (a, _) in enumerate(self._enumerate(state)):
            if a == action:
                return i
        return None


# ---- animal_frontier: CommitBreed (harvest) + CommitAccommodate (markets) ----
#
# Both hold (sheep, boar, cattle) POST-event counts (kept / remaining), and both
# come from a (config, food_gained) frontier helper. One shared featurizer:
#   [sheep_kept, boar_kept, cattle_kept, food_gained]
# The kept counts are the raw commit fields (NOT a delta — the pre-counts are in
# the shared state encoding, so subtracting would be redundant); food_gained is
# the exchange axis (food from the animals not kept / eaten), recomputed from the
# same frontier helper the legality enumerator uses, so the candidate set and
# ordering match what MCTS enumerates.

_ANIMAL_MARKET_PENDINGS = (PendingSheepMarket, PendingPigMarket, PendingCattleMarket)


def _animal_owns(state) -> bool:
    if state.phase == Phase.BEFORE_SCORING or not state.pending_stack:
        return False
    if decider_of(state) is None:
        return False
    top = state.pending_stack[-1]
    if isinstance(top, PendingHarvestBreed):
        return not top.breed_chosen          # post-commit only Stop is left
    return isinstance(top, _ANIMAL_MARKET_PENDINGS)


def _animal_feats(sheep: int, boar: int, cattle: int, food: int) -> np.ndarray:
    return np.array([sheep, boar, cattle, food], dtype=np.float32)


def _animal_frontier_enumerate(state) -> list:
    from agricola.helpers import breeding_frontier, cooking_rates, pareto_frontier
    from agricola.resources import Animals

    top = state.pending_stack[-1]
    pidx = top.player_idx
    p = state.players[pidx]
    rates3 = cooking_rates(state, pidx)[:3]

    if isinstance(top, PendingHarvestBreed):
        return [
            (CommitBreed(sheep=cfg.sheep, boar=cfg.boar, cattle=cfg.cattle),
             _animal_feats(cfg.sheep, cfg.boar, cfg.cattle, food))
            for (cfg, food) in breeding_frontier(p, rates3)
        ]

    if isinstance(top, PendingSheepMarket):
        gained = Animals(sheep=top.gained)
    elif isinstance(top, PendingPigMarket):
        gained = Animals(boar=top.gained)
    elif isinstance(top, PendingCattleMarket):
        gained = Animals(cattle=top.gained)
    else:
        return []
    return [
        (CommitAccommodate(sheep=cfg.sheep, boar=cfg.boar, cattle=cfg.cattle),
         _animal_feats(cfg.sheep, cfg.boar, cfg.cattle, food))
        for (cfg, food) in pareto_frontier(p, gained, rates3)
    ]


ANIMAL_FRONTIER_HEAD = PointerHead(
    name="animal_frontier",
    candidate_dim=4,                 # (sheep_kept, boar_kept, cattle_kept, food_gained)
    owns=_animal_owns,
    _enumerate=_animal_frontier_enumerate,
)


# ---- harvest_feed: CommitConvert (pay feeding) + CommitHarvestConversion (craft) ----
#
# At PendingHarvestFeed (before conversion_done) the legal set is HETEROGENEOUS:
# the craft "fire it" toggles (CommitHarvestConversion — `use=False` was removed
# from the engine, so there is no decline action) AND every CommitConvert
# Pareto-frontier point (how to pay the feeding cost). One head scores the mixed
# set with a tagged-union Δ (candidate_dim = 10):
#   [is_toggle, joinery, pottery, basketmaker,            # craft toggle slots
#    consumed_grain, consumed_veg, consumed_sheep,        # CommitConvert: goods paid
#    consumed_boar, consumed_cattle, begging]             #   + begging incurred
# Candidates come straight from `legal_actions(state)` (so the set + order match
# the engine exactly); the per-convert begging is recovered from the same
# `harvest_feed_frontier` the enumerator uses. After `conversion_done` only Stop
# is legal (a singleton) — `owns` excludes it.

_CRAFT_ORDER = ("joinery", "pottery", "basketmaker")
_CRAFT_INDEX = {c: i for i, c in enumerate(_CRAFT_ORDER)}
_HARVEST_FEED_DIM = 10


def _harvest_feed_owns(state) -> bool:
    if state.phase == Phase.BEFORE_SCORING or not state.pending_stack:
        return False
    if decider_of(state) is None:
        return False
    top = state.pending_stack[-1]
    return isinstance(top, PendingHarvestFeed) and not top.conversion_done


def _toggle_feats(conversion_id: str) -> np.ndarray:
    f = np.zeros(_HARVEST_FEED_DIM, dtype=np.float32)
    f[0] = 1.0                                    # is_toggle
    j = _CRAFT_INDEX.get(conversion_id)
    if j is not None:
        f[1 + j] = 1.0                            # which craft (one-hot×3)
    return f


def _convert_feats(grain, veg, sheep, boar, cattle, begging) -> np.ndarray:
    f = np.zeros(_HARVEST_FEED_DIM, dtype=np.float32)
    f[4:9] = (grain, veg, sheep, boar, cattle)    # consumed goods
    f[9] = begging
    return f


def _harvest_feed_enumerate(state) -> list:
    from agricola.helpers import cooking_rates, harvest_feed_frontier
    from agricola.legality import legal_actions

    top = state.pending_stack[-1]
    pidx = top.player_idx
    p = state.players[pidx]
    legal = legal_actions(state)                   # exact engine set (toggles + converts)

    # Per-CommitConvert begging, recovered from the frontier (consumed → begging).
    begging_by_consumed: dict = {}
    if any(isinstance(a, CommitConvert) for a in legal):
        rates = cooking_rates(state, pidx)
        food_owed = max(0, 2 * p.people_total - p.newborns - p.resources.food)
        g0, v0 = p.resources.grain, p.resources.veg
        s0, b0, c0 = p.animals.sheep, p.animals.boar, p.animals.cattle
        for ((g_rem, v_rem, s_rem, b_rem, c_rem), begging) in harvest_feed_frontier(
            p, food_owed, rates,
        ):
            begging_by_consumed[(g0 - g_rem, v0 - v_rem, s0 - s_rem,
                                 b0 - b_rem, c0 - c_rem)] = begging

    out = []
    for a in legal:
        if isinstance(a, CommitHarvestConversion):
            out.append((a, _toggle_feats(a.conversion_id)))
        elif isinstance(a, CommitConvert):
            beg = begging_by_consumed.get((a.grain, a.veg, a.sheep, a.boar, a.cattle), 0)
            out.append((a, _convert_feats(a.grain, a.veg, a.sheep, a.boar, a.cattle, beg)))
    return out


HARVEST_FEED_HEAD = PointerHead(
    name="harvest_feed",
    candidate_dim=_HARVEST_FEED_DIM,
    owns=_harvest_feed_owns,
    _enumerate=_harvest_feed_enumerate,
)


# Registry — name → pointer head, parallel to HEADS (fixed-vocab heads).
POINTER_HEADS: dict[str, PointerHead] = {
    ANIMAL_FRONTIER_HEAD.name: ANIMAL_FRONTIER_HEAD,
    HARVEST_FEED_HEAD.name: HARVEST_FEED_HEAD,
}
