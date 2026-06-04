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
adding a head is *data* (a new `DecisionHead`), not new modules. Two heads are
defined here:

- **`PLACEMENT_HEAD`** — the empty-stack worker-placement decision (25-way over
  `SPACE_IDS`). The v1 head.
- **`CHOOSE_SUBACTION_HEAD`** — the parent-pending "which sub-action, or stop?"
  decision (8-way). `build_stable` is merged into `build_stables`; `Stop` is a
  class (`STOP_LABEL`). `build_major`/`renovate` are excluded (always
  structurally singleton). `plow`/`build_rooms` are included now that the
  forced-ordering filters are dropped from `restricted.py`.

Torch-free; imported by the (torch-using) dataset/model/policy modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitBuildMajor,
    PlaceWorker,
    Stop,
)
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
    PendingBuildMajor,
    PendingCultivation,
    PendingFarmExpansion,
    PendingFarmRedevelopment,
    PendingGrainUtilization,
    PendingHouseRedevelopment,
    PendingSideJob,
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
    if isinstance(action, Stop):
        return STOP_LABEL
    return None


def _subaction_legal_labels(state, legal_actions_fn) -> set[str]:
    labels: set[str] = set()
    for a in filter_implemented(legal_actions_fn(state)):
        if isinstance(a, ChooseSubAction):
            labels.add(_SUBACTION_ALIAS.get(a.name, a.name))
        elif isinstance(a, Stop):
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


# Registry — name → head, for the dataset/training/CLI dispatch.
HEADS: dict[str, DecisionHead] = {
    PLACEMENT_HEAD.name: PLACEMENT_HEAD,
    CHOOSE_SUBACTION_HEAD.name: CHOOSE_SUBACTION_HEAD,
    COMMIT_BUILD_MAJOR_HEAD.name: COMMIT_BUILD_MAJOR_HEAD,
}
