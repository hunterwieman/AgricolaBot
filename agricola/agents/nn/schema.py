"""On-disk schema for the NN training dataset.

This module defines the dataclasses that constitute a recorded game,
the data-version protocol that guards them against silent breakage,
the pickle loader that enforces the version check, and the winner
helper used by the recording driver.

Public surface (re-exported from `agricola.agents.nn`):

- `DATA_VERSION` — guards the on-disk dataset schema. Bump whenever
  the `GameRecord` or `DecisionSnapshot` shape changes.
- `DecisionSnapshot` / `GameRecord` — frozen-dataclass record types
  written to per-worker pickle files during data generation.
- `DataVersionMismatch` — raised when a loaded record's version
  doesn't match the current `DATA_VERSION`.
- `load_game_records(path)` — pickle-load helper that enforces the
  `DATA_VERSION` check.
- `compute_winner(s0, s1, tb0, tb1)` — score+tiebreaker → winner index
  (or None for true tie).

See `FIRST_NN.md` §7.1.2 (snapshot semantics) and §10.4 (schema
versioning) for the design rationale.

This module has no PyTorch dependency — usable from data-generation
scripts, validators, and analytics code without importing torch.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from agricola.actions import Action
from agricola.state import GameState


# ---------------------------------------------------------------------------
# Schema-version constant
# ---------------------------------------------------------------------------
#
# Bump policy (see FIRST_NN.md §10.4):
#
#   DATA_VERSION: bump when `GameRecord` or `DecisionSnapshot` schema
#   changes in any way that affects on-disk shape — adding a field,
#   renaming, reordering, changing field meaning. Pure refactors that
#   preserve numerical / structural output do not bump.
#
# Checked HARD-FAIL at load time. Mismatches raise `DataVersionMismatch`.
#
# Version history:
#   1 -> 2: hidden-information refactor (commit 69f393f) replaced
#           ActionSpaceState.round_revealed: int with revealed: bool,
#           changing the GameState embedded in every record. The refactor
#           originally shipped without a bump, so v1 spans BOTH schemas on
#           disk; pre-refactor v1 data is quarantined under
#           runs/stale_data_version_1/ and the post-refactor records were
#           restamped to v2. See HIDDEN_INFO_DESIGN.md.

DATA_VERSION: int = 2
"""On-disk dataset schema version. Stamped onto every `GameRecord`;
verified at load time. See FIRST_NN.md §10.4."""


# ---------------------------------------------------------------------------
# Record dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionSnapshot:
    """One decision point in a recorded game.

    Recorded BEFORE the agent's action is applied — `state` is the
    state the agent was given, `chosen_action` is what it returned.

    Snapshot inclusion rule (see FIRST_NN.md §7.1.2): a snapshot is
    saved only when the agent faced a non-singleton decision. States
    where `len(filter_implemented(legal_actions_fn(state))) == 1`
    are not recorded — they carry no decision and would inflate the
    dataset with correlated trivia.
    """

    state: GameState
    chosen_action: Action
    decider_idx: int  # 0 or 1. Cached copy of decider_of(state) at snapshot time.


@dataclass(frozen=True)
class GameRecord:
    """One complete game's snapshots + final scoring, written to disk.

    Per-game metadata (configs, seed, temperatures) is referenced rather
    than embedded — config files are versioned artifacts already, and
    embedding them would bloat every record. See FIRST_NN.md §7.1.2.

    `data_version` is stamped from the module-level `DATA_VERSION` at
    construction time; loaders compare against the current constant.
    """

    data_version: int
    game_idx: int        # Position in the run's plan (0..planned_games-1)
    seed: int            # Passed to setup(seed) and to per-agent RNG construction

    p0_config_path: str  # Path to agent config (or sentinel for built-in constants like "v1_t2")
    p1_config_path: str
    p0_temperature: float  # Drawn independently per agent for broader state coverage
    p1_temperature: float  # (see FIRST_NN.md §7.1.1).

    p0_final_score: int
    p1_final_score: int
    winner: int | None   # 0 = P0 wins, 1 = P1 wins, None = true tie
                         # (true tie = scores equal AND tiebreaker equal).
                         # Derivable from `terminal_state` but stored explicitly
                         # for convenience and to avoid re-running scoring code
                         # at every analysis pass.

    terminal_state: GameState   # phase = Phase.BEFORE_SCORING. Stored once per
                                 # game (not per decision). Two purposes:
                                 #   1. Source of truth for any game-end-
                                 #      derivable quantity (score breakdowns,
                                 #      tiebreakers, audit).
                                 #   2. Used as an additional training example
                                 #      at DataLoader time — one (terminal_state,
                                 #      terminal_margin) pair per game, in
                                 #      addition to the per-decision pairs.
                                 # See FIRST_NN.md §5.

    decisions: tuple[DecisionSnapshot, ...]


# ---------------------------------------------------------------------------
# Pickle load helper (enforces DATA_VERSION)
# ---------------------------------------------------------------------------


class DataVersionMismatch(Exception):
    """Raised when a loaded `GameRecord` has a `data_version` that does
    not match the current module-level `DATA_VERSION`. Hard-fail per
    FIRST_NN.md §10.4 — silent skipping or coercion would defeat the
    whole point of the version check."""


def load_game_records(path: str | Path) -> list[GameRecord]:
    """Load a worker pickle file (a `list[GameRecord]`) and verify every
    record's `data_version` matches the current `DATA_VERSION`.

    Raises `DataVersionMismatch` on the first record whose version is
    out of date — names that record and indicates the version gap so
    the caller knows whether to regenerate or update the code.

    Returns the loaded list unchanged when all records pass.
    """
    path = Path(path)
    with path.open("rb") as f:
        records: Sequence[GameRecord] = pickle.load(f)

    for i, rec in enumerate(records):
        if not isinstance(rec, GameRecord):
            raise TypeError(
                f"{path}: entry {i} is {type(rec).__name__}, expected GameRecord"
            )
        if rec.data_version != DATA_VERSION:
            raise DataVersionMismatch(
                f"{path}: record {i} (game_idx={rec.game_idx}) has "
                f"data_version={rec.data_version}, current DATA_VERSION="
                f"{DATA_VERSION}. Regenerate the dataset, or roll the code "
                f"back to a DATA_VERSION={rec.data_version} commit."
            )

    return list(records)


# ---------------------------------------------------------------------------
# Winner helper
# ---------------------------------------------------------------------------


def compute_winner(
    p0_score: int, p1_score: int, p0_tiebreaker: int, p1_tiebreaker: int,
) -> int | None:
    """Return the winning player index (0 or 1), or None for a true tie.

    Tiebreaker is the second criterion (per RULES.md "Tiebreaker"). A
    return of None means scores AND tiebreakers are equal — extremely
    rare in practice but mechanically possible.

    Mirrors `scripts/play_match._winner` — duplicated here to avoid
    importing from scripts/. If a third caller appears, lift to
    `agricola.scoring` instead of triplicating.
    """
    if p0_score > p1_score:
        return 0
    if p1_score > p0_score:
        return 1
    if p0_tiebreaker > p1_tiebreaker:
        return 0
    if p1_tiebreaker > p0_tiebreaker:
        return 1
    return None
