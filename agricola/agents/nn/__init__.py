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

- `encoder` — input-vector encoder. Today: only `ENCODING_VERSION`
  (the version constant). The encoder itself is TBD pending
  architecture decisions. Future PyTorch dependency.

- (future) `model` — PyTorch `nn.Module` value-function model.
- (future) `agent` — Agent-protocol wrapper using the model as a
  1-turn-lookahead evaluator.

The public surface is re-exported here for import-path stability —
external code can keep importing `from agricola.agents.nn import X`
even as the internal file layout evolves.
"""

from agricola.agents.nn.encoder import ENCODING_VERSION
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
    "DataVersionMismatch",
    "DecisionSnapshot",
    "GameRecord",
    "compute_winner",
    "load_game_records",
    "play_recording_game",
]
