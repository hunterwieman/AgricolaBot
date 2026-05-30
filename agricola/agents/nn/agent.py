"""NNAgent — agent backed by a trained NN value function.

Slots into the existing `HeuristicAgent` infrastructure (1-turn
lookahead + singleton-skip + softmax action selection) by supplying an
NN-backed evaluator function. Two evaluator variants are exposed:

- `nn_evaluator(state, player_idx, model)` — single forward pass.
  Returns the model's margin estimate from `player_idx`'s perspective.
- `nn_evaluator_differential(state, player_idx, model)` — the
  differential inference wrapper (D) we agreed on in FIRST_NN.md §8.
  Computes `V(encode(s, 0)) − V(encode(s, 1))` (batched as one forward
  pass for efficiency), then signs the result for `player_idx`'s frame.
  Exact antisymmetry by construction; ~2× the per-call cost of the
  simple evaluator (one batched forward pass over 2 inputs).

`NNAgent` is a thin `HeuristicAgent` subclass that picks the evaluator
based on a `differential` flag. Beyond the evaluator choice, behavior
matches every other heuristic agent: it works with `play_match.py`,
`play_game`, the per-seat restricted/strict flags, etc.

Performance notes:
- The evaluator runs under `@torch.no_grad()` to skip autograd overhead.
- `model.eval()` is set once at construction (no-op for our LayerNorm +
  dropout=0 architecture, but the idiom catches future BN/dropout adds).
- The model's device is queried once via `next(model.parameters()).device`
  so the encoded input lands on the same device. CPU-default for now.
"""

from __future__ import annotations

import numpy as np
import torch

from agricola.agents.base import HeuristicAgent, LegalActionsFn
from agricola.agents.nn.encoder import encode_state
from agricola.agents.nn.model import NormalizedValueModel


# ---------------------------------------------------------------------------
# Evaluator functions
# ---------------------------------------------------------------------------


@torch.no_grad()
def nn_evaluator(state, player_idx: int, model: NormalizedValueModel) -> float:
    """Single forward pass. Returns the model's margin estimate from
    `player_idx`'s perspective, in margin units (points).

    The NN is queried once on `encode_state(state, player_idx)`. Because
    we trained with dual-perspective augmentation (A), the model should
    handle either perspective; this evaluator just takes its word for it.
    """
    features = encode_state(state, player_idx)
    x = torch.from_numpy(features).unsqueeze(0)  # (1, 170)
    device = next(model.parameters()).device
    if x.device != device:
        x = x.to(device)
    return float(model.predict_margin(x).item())


@torch.no_grad()
def nn_evaluator_differential(
    state, player_idx: int, model: NormalizedValueModel,
) -> float:
    """Differential (D) evaluator from FIRST_NN.md §8.

    Computes `V_diff = V(encode(s, 0)) − V(encode(s, 1))`, which is
    exactly antisymmetric by construction (no reliance on the model
    learning antisymmetry perfectly). Returns `V_diff` for player 0,
    `−V_diff` for player 1 — i.e., the perspective-frame margin.

    Implementation: encodes both perspectives, stacks into a single
    batch-of-2 tensor, runs ONE forward pass (not two). For small CPU
    inference the savings are modest; on a GPU the batched form
    materially helps.
    """
    f0 = encode_state(state, 0)
    f1 = encode_state(state, 1)
    x = torch.from_numpy(np.stack([f0, f1], axis=0))  # (2, 170)
    device = next(model.parameters()).device
    if x.device != device:
        x = x.to(device)
    margins = model.predict_margin(x)  # shape (2,) — margin in P0 / P1 frames
    v_diff_p0 = float((margins[0] - margins[1]).item())
    return v_diff_p0 if player_idx == 0 else -v_diff_p0


# ---------------------------------------------------------------------------
# NNAgent
# ---------------------------------------------------------------------------


class NNAgent(HeuristicAgent):
    """Agent backed by a trained `NormalizedValueModel`.

    Uses the same `HeuristicAgent` lookahead + softmax-action-selection
    machinery as `HubrisHeuristicV1` / `V3`. The only differences:

    - The evaluator is one of `nn_evaluator` / `nn_evaluator_differential`
      depending on the `differential` flag.
    - `model.eval()` is called once at construction (puts dropout/BN
      submodules — none in our default architecture — into eval mode).

    Drop-in compatibility: anywhere a `HubrisHeuristicV3` is accepted
    (e.g., `scripts/play_match.py`, `scripts/play_mcts_match.py` as the
    leaf evaluator-using opponent, `play_game`), an `NNAgent` works the
    same way.

    Parameters
    ----------
    model
        A trained `NormalizedValueModel`. Will be put in eval mode.
    differential
        Apply the D inference wrapper (FIRST_NN.md §8 / §3.4). True by
        default — exact antisymmetry, two encodings per evaluator call.
        Set to False for single-pass evaluation (simpler/faster but the
        antisymmetry property is only approximate, depending on how well
        the model learned it via A augmentation).
    temperature
        Action-selection temperature (0 = argmax with random tiebreak;
        > 0 = softmax sampling). Default 0.
    seed
        RNG seed for tiebreaks and softmax sampling. Default 0.
    lookahead
        `"turn"` (default — 1-turn greedy rollout) or `"action"`
        (1-action lookahead). See `HeuristicAgent` docstring.
    legal_actions_fn
        Optional override for the legality function. Default = the
        engine's `legal_actions` (full unrestricted). Pass
        `restricted_legal_actions` for the action-pruned variant.
    """

    def __init__(
        self,
        model: NormalizedValueModel,
        *,
        differential: bool = True,
        temperature: float = 0.0,
        seed: int = 0,
        lookahead: str = "turn",
        legal_actions_fn: LegalActionsFn | None = None,
    ):
        model.eval()
        self.model = model
        self.differential = differential

        evaluator = (
            nn_evaluator_differential if differential else nn_evaluator
        )
        kwargs = dict(
            evaluator=evaluator,
            config=model,           # passed as the 3rd evaluator arg
            temperature=temperature,
            seed=seed,
            lookahead=lookahead,
        )
        if legal_actions_fn is not None:
            kwargs["legal_actions_fn"] = legal_actions_fn
        super().__init__(**kwargs)
