"""Policy consumer surface — the prior PUCT reads (POLICY_HEAD.md §10).

`policy_prior(state, model)` returns a probability distribution over the legal
actions the model's head owns at `state`, as `{action: prob}`. The head is taken
from the model (`model.head_name`, set at training) unless one is passed
explicitly. For any decision the head does **not** own — a different decision
type, a nature-node reveal (`decider_of` is None), or a terminal state — it
returns the explicit `NO_PRIOR` sentinel, leaving the fallback to PUCT.

Keys are the actual legal `Action` instances (frozen-dataclass value-equal to
what the engine enumerates), so PUCT looks priors up by the action objects it
already holds.

Imports torch; not re-exported from `agricola.agents.nn.__init__`.
"""

from __future__ import annotations

import numpy as np
import torch

from agricola.actions import Action
from agricola.agents.base import LegalActionsFn, decider_of
from agricola.agents.nn.encoder import encode_state
from agricola.agents.nn.policy_heads import HEADS, DecisionHead
from agricola.agents.nn.policy_model import NormalizedPolicyModel
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import Phase
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
    x = torch.from_numpy(encode_state(state, decider_of(state))).unsqueeze(0)
    device = next(model.parameters()).device
    probs = model.policy_probs(x.to(device), mask.to(device))[0].cpu()
    return {a: float(probs[i]) for a, i in candidates}
