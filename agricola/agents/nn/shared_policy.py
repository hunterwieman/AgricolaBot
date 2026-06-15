"""Joint inference adapter for `SharedTrunkModel` (Stage B consumption).

`make_joint_fns(model)` returns the `(value_fn, policy_fn)` pair MCTS/PUCT
consumes — both reading off the **one** shared trunk. The win over the separate
value-net + 9-policy-head setup is that the trunk forward is computed **once per
node** instead of once for value and again for policy:

  * both value and policy are evaluated from the **decider's perspective**, so
    they share a single embedding (`model.embed(encode(state, decider))`);
  * the value is then sign-flipped into the P0 frame (the MCTS leaf contract:
    `evaluator_fn -> P0-frame margin`), exactly as `nn_evaluator` returns;
  * the embedding is memoized per `(state, perspective)`, so the value call and
    the policy call for the same leaf hit one forward — `mcts.py` is unchanged
    (no reordering needed; the memo does it).

The `policy_fn` mirrors `policy.make_policy_fn`'s dispatch exactly (fixed head /
pointer head / build_stop / cell-priority uniform / full-legal uniform) — same
fallbacks, same ownership — but reads each head off the shared embedding via the
`SharedTrunkModel` head methods instead of nine standalone models. Decision types
whose learned head is unreliable (e.g. bake) can still be served by the head; the
caller may instead route them to uniform by omitting that head — see POLICY_HEAD.md.

Note: sharing the forward means the value comes from the decider's frame
sign-flipped (single-pass), not the two-pass differential — i.e. it trades the
differential's exact antisymmetry for the one-forward saving. That matches the
single-pass `nn_evaluator` used in production self-play.

Imports torch; not re-exported from `agricola.agents.nn.__init__`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable

import numpy as np
import torch

from agricola.actions import Action, CommitBuildRoom, CommitBuildStable, Stop
from agricola.agents.base import decider_of
from agricola.agents.nn.encoder import ENCODER_V2, ENCODERS, begging_margin
from agricola.agents.nn.model import model_device
from agricola.agents.nn.policy import (
    _CELL_PRIORITY_SPECS,
    _uniform,
)
from agricola.agents.nn.policy_heads import (
    BUILD_LABEL,
    BUILD_STOP_HEAD,
    HEADS,
    POINTER_HEADS,
    STOP_LABEL,
)
from agricola.agents.nn.shared_model import SharedTrunkModel
from agricola.agents.restricted import (
    ROOM_PRIORITY,
    STABLE_PRIORITY,
    _filter_cell_priority,
)
from agricola.constants import Phase
from agricola.legality import legal_actions as full_legal_actions
from agricola.pending import PendingBuildRooms
from agricola.scoring import score
from tests.test_utils import filter_implemented

# Fixed heads excluding build_stop (handled specially, like make_policy_fn).
_FIXED_OWNERS = [h for name, h in HEADS.items() if name != BUILD_STOP_HEAD.name]
_POINTER_OWNERS = list(POINTER_HEADS.values())


def _masked_softmax(logits: torch.Tensor, mask_bool: torch.Tensor) -> torch.Tensor:
    """Softmax over legal classes; all-illegal row → treat as all-legal (guards a
    NaN softmax), matching NormalizedPolicyModel.predict_logits."""
    if not bool(mask_bool.any()):
        mask_bool = torch.ones_like(mask_bool)
    masked = logits.masked_fill(~mask_bool, float("-inf"))
    return torch.softmax(masked, dim=-1)


def make_joint_fns(
    model: SharedTrunkModel,
    *,
    legal_actions_fn=full_legal_actions,
    embed_cache_size: int = 4096,
) -> tuple[Callable, Callable]:
    """Return `(value_fn, policy_fn)` for `model` sharing one trunk forward per
    node. `value_fn(state, player_idx, config) -> P0-frame margin`;
    `policy_fn(state, legal) -> {action: prior}` (full-legal dispatch)."""
    model.eval()
    device = model_device(model)
    target_std = float(model.target_std)
    # Pick the encoder this model was trained with (tag recorded on the
    # checkpoint). A candidate also stripped begging from the value target, so we
    # add the current begging margin back here (P0 frame). v2 → no-op.
    tag = getattr(model, "encoding_tag", "") or ENCODER_V2.tag
    encoder = next((e for e in ENCODERS.values() if e.tag == tag), ENCODER_V2)
    strip_begging = encoder.strip_begging

    @lru_cache(maxsize=embed_cache_size)
    def _embed(state, persp: int) -> torch.Tensor:
        x = torch.from_numpy(
            encoder.encode_for_inference(state, persp)).unsqueeze(0).to(device)
        return model.embed(x)                       # (1, E)

    @torch.no_grad()
    def value_fn(state, player_idx=0, config=None) -> float:
        if state.phase == Phase.BEFORE_SCORING:     # terminal: exact, not an NN guess
            own, _ = score(state, 0)
            opp, _ = score(state, 1)
            return float(own - opp)                 # P0-frame margin (begging incl.)
        d = decider_of(state)
        if d is None:                               # nature node (defensive)
            d = 0
        v = float(model.value_from_embedding(_embed(state, d))[0]) * target_std
        v = v if d == 0 else -v                     # decider-frame → P0 frame
        if strip_begging:                           # add the stripped current begging back
            v += begging_margin(state, 0)
        return v

    @torch.no_grad()
    def _fixed_prior(head, state, emb):
        legal = filter_implemented(legal_actions_fn(state))
        cands = [(a, head.target_index(a)) for a in legal]
        cands = [(a, i) for a, i in cands if i is not None]
        if not cands:
            return None
        mask = torch.from_numpy(head.legal_mask(state, legal_actions_fn)).to(device)
        logits = model.fixed_logits_from_embedding(emb, head.name)[0]
        probs = _masked_softmax(logits, mask).cpu()
        return {a: float(probs[i]) for a, i in cands}

    @torch.no_grad()
    def _pointer_prior(head, state, emb):
        pairs = head.enumerate_candidates(state)
        if not pairs:
            return None
        cand = torch.from_numpy(
            np.stack([f for _, f in pairs]).astype(np.float32)).to(device)
        emb_rows = emb.expand(cand.shape[0], -1)    # repeat the one embedding
        scores = model.pointer_scores_from_embedding(head.name, emb_rows, cand)
        probs = torch.softmax(scores, dim=-1).cpu()
        return {a: float(probs[i]) for i, (a, _) in enumerate(pairs)}

    @torch.no_grad()
    def _build_stop(state, emb, legal):
        mask = torch.from_numpy(
            BUILD_STOP_HEAD.legal_mask(state, legal_actions_fn)).to(device)
        logits = model.fixed_logits_from_embedding(emb, BUILD_STOP_HEAD.name)[0]
        probs = _masked_softmax(logits, mask).cpu()
        p_build = float(probs[BUILD_STOP_HEAD._index[BUILD_LABEL]])
        p_stop = float(probs[BUILD_STOP_HEAD._index[STOP_LABEL]])
        top = state.pending_stack[-1]
        if isinstance(top, PendingBuildRooms):
            priority, commit_class = ROOM_PRIORITY, CommitBuildRoom
        else:
            priority, commit_class = STABLE_PRIORITY, CommitBuildStable
        kept = _filter_cell_priority(list(legal), priority, commit_class)
        build_opts = [a for a in kept if isinstance(a, commit_class)]
        stop_opts = [a for a in kept if isinstance(a, Stop)]
        out: dict[Action, float] = {}
        if build_opts and p_build > 0:
            for a in build_opts:
                out[a] = p_build / len(build_opts)
        if stop_opts and p_stop > 0:
            out[stop_opts[0]] = p_stop
        total = sum(out.values())
        return {a: p / total for a, p in out.items()} if total > 0 else _uniform(kept)

    @torch.no_grad()
    def policy_fn(state, legal: list[Action]) -> dict[Action, float]:
        if state.phase == Phase.BEFORE_SCORING or decider_of(state) is None:
            return _uniform(list(legal))
        emb = _embed(state, decider_of(state))      # shared with value_fn

        owning = next((h for h in _FIXED_OWNERS if h.owns(state)), None)
        if owning is not None:
            pri = _fixed_prior(owning, state, emb)
            if pri:
                return pri

        powning = next((h for h in _POINTER_OWNERS if h.owns(state)), None)
        if powning is not None:
            pri = _pointer_prior(powning, state, emb)
            if pri:
                return pri

        if BUILD_STOP_HEAD.owns(state):
            return _build_stop(state, emb, list(legal))

        top = state.pending_stack[-1] if state.pending_stack else None
        spec = _CELL_PRIORITY_SPECS.get(type(top))
        if spec is not None:
            priority, commit_class = spec
            return _uniform(_filter_cell_priority(list(legal), priority, commit_class))

        return _uniform(list(legal))

    return value_fn, policy_fn
