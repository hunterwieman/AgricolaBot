"""NN value-function infrastructure for AgricolaBot.

This subpackage is the home of the NN-based value function described
in `FIRST_NN.md`. Today it contains the data schema and recording
driver. The encoder, model, and agent wrapper will land as separate
modules in subsequent commits.

Submodules:

- `schema` — on-disk record types (`DecisionSnapshot`, `GameRecord`),
  the data-version protocol (`DATA_VERSION`, `DataVersionMismatch`,
  `load_game_records`), and the winner helper (`compute_winner`).
  No PyTorch dependency.

- `recording` — single-game recording driver (`play_recording_game`).
  Depends only on the engine + `Agent` protocol. No PyTorch dependency.

- `encoder` — input-vector encoder. `encode_state(state, player_idx)
  -> np.ndarray` (float32, length `ENCODED_DIM`), `ENCODING_VERSION`,
  `feature_names()`. Numpy-only (no torch); the training pipeline
  converts via `torch.from_numpy`.

- `dataset` — training-dataset builder. `build_datasets`,
  `build_datasets_from_games`, `AgricolaValueDataset`, `NormStats`.
  **Imports torch.** Not re-exported here (eager import would pull
  torch into the data-generation path); explicit import required:
  `from agricola.agents.nn.dataset import build_datasets, NormStats`.

- `model` — PyTorch model + normalization wrapper. `ConfigurableMLP`
  (parameterized MLP, composable as a sub-encoder via `output_dim`),
  `NormalizedValueModel` (wraps a net with fixed normalization
  buffers; `forward` returns normalized output, `predict_margin`
  returns margin units), `EncodingVersionMismatch`, `NET_REGISTRY`.
  **Imports torch.** Not re-exported here; explicit import required:
  `from agricola.agents.nn.model import ConfigurableMLP, NormalizedValueModel`.

- `training` — training-loop library. `train(...)` programmatic entry,
  `train_one_epoch`, `evaluate`, `setup_seeds`, `make_run_id`, plot
  helpers. CLI wrapper at `scripts/nn/train_first.py`.
  **Imports torch.** Not re-exported here; explicit import required:
  `from agricola.agents.nn.training import train`.

- `agent` — `NNAgent` (EvaluatorAgent-based 1-turn lookahead backed by
  a trained NN) + evaluator functions (`nn_evaluator`,
  `nn_evaluator_differential`).
  **Imports torch.** Not re-exported here; explicit import required:
  `from agricola.agents.nn.agent import NNAgent`.

- (future) `model` — PyTorch `nn.Module` value-function model.
- (future) `agent` — Agent-protocol wrapper using the model as a
  1-turn-lookahead evaluator.

The public surface is re-exported here for import-path stability —
external code can keep importing `from agricola.agents.nn import X`
even as the internal file layout evolves.
"""

from agricola.agents.nn.encoder import (
    ENCODED_DIM,
    ENCODING_VERSION,
    encode_state,
    feature_names,
)
from agricola.agents.nn.recording import play_recording_game
from agricola.agents.nn.schema import (
    DATA_VERSION,
    DataVersionMismatch,
    DecisionSnapshot,
    GameRecord,
    compute_winner,
    load_game_records,
)

__all__ = [
    "DATA_VERSION",
    "ENCODING_VERSION",
    "ENCODED_DIM",
    "DataVersionMismatch",
    "DecisionSnapshot",
    "GameRecord",
    "compute_winner",
    "load_game_records",
    "play_recording_game",
    "encode_state",
    "feature_names",
]
