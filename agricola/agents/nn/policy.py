"""Policy consumer surface — the prior PUCT reads (POLICY_HEAD.md §10).

Surfaces:

- **`policy_prior(state, model)`** — single fixed-head prior: a distribution over
  the legal actions *one* model's head owns at `state`, as `{action: prob}`.
  Returns the `NO_PRIOR` sentinel off that head's decision points (other type,
  nature-node reveal, terminal).
- **`pointer_prior(state, model)`** — the same for a *pointer* head (softmax over
  the head's enumerated frontier candidates), else `NO_PRIOR`.
- **`make_policy_fn(models)`** — the full `policy_fn(state, legal_actions) ->
  {action: prior}` MCTS/PUCT consumes (`load_policy_fn(checkpoints)` is the
  load-from-disk variant). The policy works over the **full** legal set (MCTS
  enumerates everything; no `restricted_legal_actions` in enumeration) and is the
  sole source of the prior. It dispatches by decision type (the pending-stack top):
    - **fixed head** (placement / choose_subaction / commit_build_major /
      commit_sow / commit_bake / fencing) → its masked-softmax over full legal;
    - **pointer head** (animal_frontier / harvest_feed) → its score-the-set softmax;
    - **`build_stop`** (multi-shot Build Rooms / Build Stables, Stop legal) →
      learned `P(stop)` + cell-priority build cell;
    - **cell commits** (plow / first-build rooms & stables) → uniform over the
      cell-priority-filtered set (no encoder signal for *which* cell);
    - **anything else** → uniform over the full legal set.
  Any legal action the returned dict omits is read as prior 0 (`priors.get(a, 0.0)`
  in `mcts.py`), so the search stays generic and every prior/prune decision is a
  property of the policy alone.

Keys are the actual legal `Action` instances (frozen-dataclass value-equal to
what the engine enumerates), so PUCT looks priors up by the action objects it
already holds.

Imports torch; not re-exported from `agricola.agents.nn.__init__`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import torch

from agricola.actions import (
    Action,
    CommitBuildRoom,
    CommitBuildStable,
    CommitPlow,
    Proceed,
    Stop,
)
from agricola.agents.base import LegalActionsFn, decider_of
from agricola.agents.nn.encoder import encode_for_inference
from agricola.agents.nn.policy_heads import (
    BUILD_LABEL,
    BUILD_STOP_HEAD,
    HEADS,
    POINTER_HEADS,
    STOP_LABEL,
    DecisionHead,
)
from agricola.agents.nn.model import model_device
from agricola.agents.nn.policy_model import NormalizedPolicyModel
from agricola.agents.restricted import (
    PLOW_PRIORITY,
    ROOM_PRIORITY,
    STABLE_PRIORITY,
    _filter_cell_priority,
    restricted_legal_actions,
)
from agricola.constants import Phase
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildRooms,
    PendingBuildStables,
    PendingPlow,
)
from tests.test_utils import filter_implemented

# Explicit "this state has no prior from this head" sentinel.
NO_PRIOR = None


@torch.no_grad()
def policy_prior(
    state,
    model: NormalizedPolicyModel,
    *,
    head: DecisionHead | None = None,
    legal_actions_fn: LegalActionsFn = restricted_legal_actions,
) -> dict[Action, float] | None:
    """Prior over the legal actions the head owns at `state`, or `NO_PRIOR`.

    `head` defaults to the head the model was trained for (`model.head_name`).
    Returns `{action: prob}` (masked softmax over the head's legal classes,
    summing to 1) when the head owns the decision; `NO_PRIOR` otherwise.
    """
    if head is None:
        head = HEADS.get(model.head_name) if model.head_name else None
    if head is None:
        raise ValueError(
            "policy_prior: no head — pass head=, or load a head-labelled model."
        )

    if state.phase == Phase.BEFORE_SCORING:
        return NO_PRIOR
    if not head.owns(state):
        return NO_PRIOR
    if decider_of(state) is None:           # nature node — defensive
        return NO_PRIOR

    legal = filter_implemented(legal_actions_fn(state))
    candidates = [(a, head.target_index(a)) for a in legal]
    candidates = [(a, i) for a, i in candidates if i is not None]
    if not candidates:
        return NO_PRIOR

    mask = torch.from_numpy(head.legal_mask(state, legal_actions_fn)).unsqueeze(0)
    x = torch.from_numpy(encode_for_inference(state, decider_of(state))).unsqueeze(0)
    device = model_device(model)
    probs = model.policy_probs(x.to(device), mask.to(device))[0].cpu()
    return {a: float(probs[i]) for a, i in candidates}


@torch.no_grad()
def pointer_prior(
    state,
    model,
    *,
    head=None,
) -> dict[Action, float] | None:
    """Prior over the legal frontier commits a **pointer** head owns, or NO_PRIOR.

    `head` defaults to the model's head (`model.head_name` in `POINTER_HEADS`).
    The candidates ARE the legal set (the head re-derives the engine frontier), so
    there's no separate legality argument; returns `{action: prob}` (softmax over
    the per-candidate scores) when the head owns the decision, else `NO_PRIOR`.
    """
    if head is None:
        head = POINTER_HEADS.get(model.head_name) if model.head_name else None
    if head is None:
        raise ValueError(
            "pointer_prior: no head — pass head=, or load a head-labelled model."
        )

    if state.phase == Phase.BEFORE_SCORING:
        return NO_PRIOR
    if not head.owns(state):
        return NO_PRIOR
    if decider_of(state) is None:
        return NO_PRIOR

    pairs = head.enumerate_candidates(state)
    if not pairs:
        return NO_PRIOR

    state_enc = encode_for_inference(state, decider_of(state))
    cand = np.stack([f for _, f in pairs]).astype(np.float32)
    device = model_device(model)
    probs = model.candidate_probs(
        torch.from_numpy(state_enc).to(device),
        torch.from_numpy(cand).to(device),
    ).cpu()
    return {a: float(probs[i]) for i, (a, _) in enumerate(pairs)}


# Type of the policy_fn MCTS/PUCT consumes.
PolicyFn = Callable[[object, list], "dict[Action, float]"]

# Cell-commit decisions: the encoder is count-based, not spatial (POLICY_HEAD.md
# §3/§11), so a learned head has no signal to pick *which* cell. Instead the policy
# puts uniform mass over the cell-priority-filtered set — restricted.py's hand-coded
# spatial prior — applying ONLY `_filter_cell_priority` (NOT the room cap, which is a
# strategic restriction we deliberately keep out of the prior). Keyed by the
# pending-stack-top type; mirrors restricted.py's own dispatch.
_CELL_PRIORITY_SPECS: dict[type, tuple[tuple, type]] = {
    PendingPlow: (PLOW_PRIORITY, CommitPlow),
    PendingBuildStables: (STABLE_PRIORITY, CommitBuildStable),
    PendingBuildRooms: (ROOM_PRIORITY, CommitBuildRoom),
}


def _uniform(actions: list[Action]) -> dict[Action, float]:
    """Uniform distribution over `actions` (empty dict if empty)."""
    if not actions:
        return {}
    p = 1.0 / len(actions)
    return {a: p for a in actions}


@torch.no_grad()
def _build_stop_probs(state, model, legal_actions_fn) -> tuple[float, float]:
    """(p_build, p_stop) from the 2-class build_stop model — masked softmax over
    {build, stop} at a multi-shot Build Rooms / Build Stables decision."""
    head = BUILD_STOP_HEAD
    mask = torch.from_numpy(head.legal_mask(state, legal_actions_fn)).unsqueeze(0)
    x = torch.from_numpy(encode_for_inference(state, decider_of(state))).unsqueeze(0)
    device = model_device(model)
    probs = model.policy_probs(x.to(device), mask.to(device))[0].cpu()
    return float(probs[head._index[BUILD_LABEL]]), float(probs[head._index[STOP_LABEL]])


def _build_stop_distribution(state, model, legal, legal_actions_fn):
    """`{build_cell: P(build), Stop: P(stop)}` — learned P(stop) with the cell
    chosen by cell-priority (no encoder signal for *which* cell). Renormalized."""
    p_build, p_stop = _build_stop_probs(state, model, legal_actions_fn)
    top = state.pending_stack[-1]
    if isinstance(top, PendingBuildRooms):
        priority, commit_class = ROOM_PRIORITY, CommitBuildRoom
    else:
        priority, commit_class = STABLE_PRIORITY, CommitBuildStable
    kept = _filter_cell_priority(list(legal), priority, commit_class)
    build_opts = [a for a in kept if isinstance(a, commit_class)]
    # Proceed-as-Stop alias (§9): the multi-shot builder's before-phase "stop"
    # action is now Proceed (the work-complete flip), not Stop — assign p_stop to it.
    stop_opts = [a for a in kept if isinstance(a, (Stop, Proceed))]
    out: dict[Action, float] = {}
    if build_opts and p_build > 0:
        share = p_build / len(build_opts)
        for a in build_opts:
            out[a] = share
    if stop_opts and p_stop > 0:
        out[stop_opts[0]] = p_stop
    total = sum(out.values())
    return {a: p / total for a, p in out.items()} if total > 0 else _uniform(kept)


def make_policy_fn(
    models: Iterable[NormalizedPolicyModel],
    *,
    legal_actions_fn: LegalActionsFn = legal_actions,
) -> PolicyFn:
    """Build the PUCT ``policy_fn(state, legal_actions) -> {action: prior}``.

    The policy works over the **full** legal action set — MCTS enumerates every
    legal action (no `restricted_legal_actions` in enumeration), and this function
    is the sole source of the prior. It dispatches by decision type (the
    pending-stack top), each type handled per its own design:

    - **A fixed-vocab head owns it** (placement / choose_subaction /
      commit_build_major / future commit_sow) → the head's masked-softmax
      distribution over the **full** legal set (no restriction; `build_rooms` stays
      offered at the room cap, etc.). Heads own **disjoint** decision points.
    - **A pointer head owns it** (`animal_frontier`: CommitBreed / CommitAccommodate)
      → the head's softmax over its enumerated frontier candidates (which ARE the
      legal set). Trained pointer models route here via `pointer_prior`.
    - **A multi-shot Build Rooms / Build Stables with Stop legal** (a `build_stop`
      model is loaded) → learned `P(stop)` on Stop and `1−P(stop)` on the
      cell-priority build cell, replacing the crude uniform 50/50 the cell path
      gives. Only rooms/stables (fencing keeps its own head).
    - **A cell commit** (`CommitPlow` / `CommitBuildStable` / `CommitBuildRoom`) →
      **uniform over the cell-priority-filtered set only** (the spatial prior; the
      room cap is intentionally NOT applied — see `_CELL_PRIORITY_SPECS`).
    - **Everything else** (fencing / convert / accommodate / breed / bake / renovate)
      → uniform over the full legal set. These are the as-yet-unhandled decision
      types (POLICY_HEAD.md §11); they get a flat prior until their heads land.

    Keys are value-equal to the engine's action objects, so PUCT looks them up
    directly; any legal action the returned dict omits is read as prior 0.
    """
    fixed_by_head: dict[str, tuple] = {}      # name -> (DecisionHead, model)
    pointer_by_head: dict[str, tuple] = {}    # name -> (PointerHead, model)
    build_stop_model = None                    # handled specially (class→action expansion)
    for m in models:
        # Inference mode: the head models are loaded in TRAIN mode (load() does
        # not eval), so dropout would fire on every prior query — making the
        # PUCT priors NON-DETERMINISTic (same state → different prior each call,
        # ~0.05 swings) and the search noisily wrong. Assembling the policy_fn
        # is an inference action, so eval() the models here. (The value-net leaf
        # is eval'd by its caller, e.g. play_mcts_match / NNAgent.)
        m.eval()
        name = getattr(m, "head_name", None)
        if name == BUILD_STOP_HEAD.name:
            build_stop_model = m
        elif name in HEADS:
            fixed_by_head[name] = (HEADS[name], m)
        elif name in POINTER_HEADS:
            pointer_by_head[name] = (POINTER_HEADS[name], m)
        else:
            raise ValueError(
                f"make_policy_fn: model has unknown/missing head_name {name!r}; "
                f"expected one of {sorted(HEADS) + sorted(POINTER_HEADS)}."
            )

    @torch.no_grad()
    def policy_fn(state, legal: list[Action]) -> dict[Action, float]:
        # 1. Fixed-vocab head over the FULL legal set (disjoint ownership → ≤1).
        owning = next(
            ((h, m) for h, m in fixed_by_head.values() if h.owns(state)), None
        )
        if owning is not None:
            head, model = owning
            pri = policy_prior(
                state, model, head=head, legal_actions_fn=legal_actions_fn,
            )
            if pri:                      # not NO_PRIOR and non-empty
                return pri
            # Head abstained (shouldn't happen when owns() is True) — fall through.

        # 1b. Pointer head over its frontier (the candidates ARE the legal set).
        powning = next(
            ((h, m) for h, m in pointer_by_head.values() if h.owns(state)), None
        )
        if powning is not None:
            head, model = powning
            pri = pointer_prior(state, model, head=head)
            if pri:
                return pri

        # 1c. build_stop: multi-shot Build Rooms / Build Stables with Stop legal —
        #     learned P(stop) + cell-priority build cell (takes precedence over the
        #     crude uniform cell path below; only when a build_stop model is loaded).
        if build_stop_model is not None and BUILD_STOP_HEAD.owns(state):
            return _build_stop_distribution(
                state, build_stop_model, list(legal), legal_actions_fn,
            )

        # 2. Cell commit → uniform over the cell-priority-filtered set only.
        top = state.pending_stack[-1] if state.pending_stack else None
        spec = _CELL_PRIORITY_SPECS.get(type(top))
        if spec is not None:
            priority, commit_class = spec
            return _uniform(_filter_cell_priority(list(legal), priority, commit_class))

        # 3. Unhandled decision type → uniform over the full legal set.
        return _uniform(list(legal))

    return policy_fn


def _load_head_model(path: str | Path):
    """Load a fixed (`NormalizedPolicyModel`) or pointer (`NormalizedPointerModel`)
    checkpoint, dispatched on the meta sidecar's `model_kind`."""
    path = Path(path)
    meta = json.loads(path.with_suffix(".meta.json").read_text())
    kind = meta.get("model_kind")
    if kind == "policy_pointer":
        from agricola.agents.nn.policy_pointer_model import NormalizedPointerModel
        return NormalizedPointerModel.load(path)
    if kind == "policy":
        return NormalizedPolicyModel.load(path)
    raise ValueError(f"{path}: unexpected model_kind {kind!r} (want policy/policy_pointer)")


def load_policy_fn(
    checkpoints: Iterable[str | Path],
    *,
    legal_actions_fn: LegalActionsFn = legal_actions,
) -> PolicyFn:
    """Assemble the combined `policy_fn` from a list of head checkpoints.

    Each entry is a checkpoint stem (e.g. `nn_models/policy_placement_v2_unweighted/best`);
    fixed vs pointer heads are auto-detected per checkpoint. Decision types with no
    loaded head fall back per `make_policy_fn` (cell-priority uniform / full-legal
    uniform). This is the one-call constructor for the full multi-head policy PUCT
    consumes.
    """
    return make_policy_fn(
        [_load_head_model(p) for p in checkpoints], legal_actions_fn=legal_actions_fn,
    )
