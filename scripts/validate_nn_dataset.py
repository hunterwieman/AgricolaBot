"""Post-generation validation for NN training datasets.

Loads `GameRecord`s from a run directory and asserts the invariants
specified in FIRST_NN.md §6.6. Failing checks are reported with the
specific game_idx and snapshot index, so you can locate the offending
record for investigation.

CLI usage:

    # Validate a complete run (all games):
    python scripts/validate_nn_dataset.py --run-dir data/nn_training/runs/<run-id>

    # Validate a random sample (faster for huge datasets):
    python scripts/validate_nn_dataset.py --run-dir <run-dir> --sample-size 100

    # Quiet mode (just exit code, no per-check output):
    python scripts/validate_nn_dataset.py --run-dir <run-dir> --quiet

Exit codes:
    0  All checks passed.
    1  One or more checks failed.
    2  Run directory invalid / missing files.

Invariants checked (per FIRST_NN.md §6.6):

1. **`data_version`** matches the loader's current `DATA_VERSION`.
   (Already checked HARD-FAIL by `load_game_records`; we exercise it
   by loading. This check guards against schema drift.)
2. **`chosen_action ∈ legal_actions(state)`** for every snapshot.
   Engine consistency — the recorded action must be a legal action at
   the recorded state. If this fails, either the recording driver has
   a state-bind bug, or the engine has changed since recording.
3. **`len(filter_implemented(legal_actions(state))) > 1`** for every
   snapshot. The snapshot inclusion rule (§6.2) excludes singleton
   states. A failure here means a singleton state was incorrectly
   recorded.
4. **`state.phase != BEFORE_SCORING`** for every snapshot. Terminal
   states should be in `terminal_state`, not in `decisions`.
5. **`len(decisions) > 0`** for every game. Catches "I produced an
   empty game" bugs (shouldn't happen given the game must have at
   least one non-singleton state).
6. **Final scores match `score(terminal_state)`** for both players.
   Catches drift between recording and labeling — e.g. if the scoring
   code changed between the recording session and the validation
   session, the stored scores won't match. (For the initial dataset
   right after generation, this is essentially a no-op — but valuable
   for catching post-hoc engine changes.)
7. **`decider_idx == decider_of(state)`** for every snapshot. Catches
   bugs in the recording driver where the cached decider_idx
   diverged from what the state implies.
8. **`terminal_state.phase == BEFORE_SCORING`** for every game.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# Make `agricola` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.base import decider_of  # noqa: E402
from agricola.agents.nn import (  # noqa: E402
    DATA_VERSION,
    GameRecord,
    load_game_records,
)
from agricola.constants import Phase  # noqa: E402
from agricola.legality import legal_actions  # noqa: E402
from agricola.scoring import score  # noqa: E402
from tests.test_utils import filter_implemented  # noqa: E402


# ---------------------------------------------------------------------------
# Failure tracking
# ---------------------------------------------------------------------------

class ValidationFailure:
    """One check failure, with enough context to locate the bad record."""

    def __init__(self, check: str, game_idx: int, detail: str,
                 snap_idx: int | None = None, pkl_path: Path | None = None):
        self.check = check
        self.game_idx = game_idx
        self.snap_idx = snap_idx  # None for game-level failures
        self.detail = detail
        self.pkl_path = pkl_path

    def __str__(self) -> str:
        loc = f"game_idx={self.game_idx}"
        if self.snap_idx is not None:
            loc += f", snap_idx={self.snap_idx}"
        if self.pkl_path is not None:
            loc += f", in {self.pkl_path.name}"
        return f"[{self.check}] {loc}: {self.detail}"


# ---------------------------------------------------------------------------
# Per-record check
# ---------------------------------------------------------------------------

def check_record(rec: GameRecord, pkl_path: Path | None = None) -> list[ValidationFailure]:
    """Run all per-record invariants. Returns the (possibly empty)
    list of failures. Continues past individual failures so the full
    report shows everything wrong with the record, not just the first.
    """
    failures: list[ValidationFailure] = []

    # Game-level checks
    if rec.data_version != DATA_VERSION:
        # Shouldn't fire if load_game_records was used (it would have
        # raised first), but defensive.
        failures.append(ValidationFailure(
            check="data_version",
            game_idx=rec.game_idx,
            detail=f"record has data_version={rec.data_version}, "
                    f"current DATA_VERSION={DATA_VERSION}",
            pkl_path=pkl_path,
        ))
        # Don't continue — most other checks would chain failures.
        return failures

    if len(rec.decisions) == 0:
        failures.append(ValidationFailure(
            check="non_empty_decisions",
            game_idx=rec.game_idx,
            detail="record has zero decision snapshots",
            pkl_path=pkl_path,
        ))

    if rec.terminal_state.phase != Phase.BEFORE_SCORING:
        failures.append(ValidationFailure(
            check="terminal_phase",
            game_idx=rec.game_idx,
            detail=f"terminal_state.phase={rec.terminal_state.phase}, "
                    f"expected BEFORE_SCORING",
            pkl_path=pkl_path,
        ))
    else:
        # Only run scoring drift check if terminal phase is correct.
        try:
            p0_actual, _ = score(rec.terminal_state, 0)
            p1_actual, _ = score(rec.terminal_state, 1)
            if p0_actual != rec.p0_final_score:
                failures.append(ValidationFailure(
                    check="scoring_drift_p0",
                    game_idx=rec.game_idx,
                    detail=f"stored p0_final_score={rec.p0_final_score}, "
                            f"score(terminal_state, 0)={p0_actual}",
                    pkl_path=pkl_path,
                ))
            if p1_actual != rec.p1_final_score:
                failures.append(ValidationFailure(
                    check="scoring_drift_p1",
                    game_idx=rec.game_idx,
                    detail=f"stored p1_final_score={rec.p1_final_score}, "
                            f"score(terminal_state, 1)={p1_actual}",
                    pkl_path=pkl_path,
                ))
        except Exception as exc:
            failures.append(ValidationFailure(
                check="scoring_exception",
                game_idx=rec.game_idx,
                detail=f"score() raised on terminal_state: "
                        f"{type(exc).__name__}: {exc}",
                pkl_path=pkl_path,
            ))

    # Per-snapshot checks
    for i, snap in enumerate(rec.decisions):
        if snap.state.phase == Phase.BEFORE_SCORING:
            failures.append(ValidationFailure(
                check="terminal_in_decisions",
                game_idx=rec.game_idx, snap_idx=i,
                detail="snapshot state has phase=BEFORE_SCORING "
                       "(terminal states should be in terminal_state)",
                pkl_path=pkl_path,
            ))
            # Skip further checks on this snapshot.
            continue

        # Check decider consistency.
        expected_decider = decider_of(snap.state)
        if snap.decider_idx != expected_decider:
            failures.append(ValidationFailure(
                check="decider_idx_mismatch",
                game_idx=rec.game_idx, snap_idx=i,
                detail=f"stored decider_idx={snap.decider_idx}, "
                        f"decider_of(state)={expected_decider}",
                pkl_path=pkl_path,
            ))

        # Check action legality + non-singleton.
        try:
            actions = filter_implemented(legal_actions(snap.state))
        except Exception as exc:
            failures.append(ValidationFailure(
                check="legal_actions_exception",
                game_idx=rec.game_idx, snap_idx=i,
                detail=f"legal_actions() raised: {type(exc).__name__}: {exc}",
                pkl_path=pkl_path,
            ))
            continue

        if snap.chosen_action not in actions:
            failures.append(ValidationFailure(
                check="chosen_action_illegal",
                game_idx=rec.game_idx, snap_idx=i,
                detail=f"chosen_action={snap.chosen_action!r} not in "
                        f"legal_actions({len(actions)} options)",
                pkl_path=pkl_path,
            ))

        if len(actions) <= 1:
            failures.append(ValidationFailure(
                check="singleton_snapshot",
                game_idx=rec.game_idx, snap_idx=i,
                detail=f"state has only {len(actions)} legal action(s); "
                       f"singleton states should not be recorded",
                pkl_path=pkl_path,
            ))

    return failures


# ---------------------------------------------------------------------------
# Run-directory loader
# ---------------------------------------------------------------------------

def discover_worker_pickles(run_dir: Path) -> list[Path]:
    """Return sorted list of worker_*.pkl files under run_dir/games/."""
    games_dir = run_dir / "games"
    if not games_dir.is_dir():
        raise FileNotFoundError(
            f"{run_dir} does not contain a 'games/' subdirectory. "
            f"Is this a generation-run directory?"
        )
    pkls = sorted(games_dir.glob("worker_*.pkl"))
    if not pkls:
        raise FileNotFoundError(
            f"No worker_*.pkl files found in {games_dir}"
        )
    return pkls


def load_all_records(pkl_paths: list[Path]) -> list[tuple[GameRecord, Path]]:
    """Load all records, paired with their source path (for failure
    reporting). load_game_records itself enforces DATA_VERSION."""
    out = []
    for pkl in pkl_paths:
        records = load_game_records(pkl)
        for rec in records:
            out.append((rec, pkl))
    return out


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def sample_records(
    all_records: list[tuple[GameRecord, Path]],
    sample_size: int | None,
    seed: int,
) -> list[tuple[GameRecord, Path]]:
    """Return up to `sample_size` random records (with replacement
    semantics: actually deterministic sampling without replacement).
    `None` returns all records."""
    if sample_size is None or sample_size >= len(all_records):
        return all_records
    rng = np.random.default_rng(seed)
    indices = rng.choice(len(all_records), size=sample_size, replace=False)
    return [all_records[i] for i in indices]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_run(
    run_dir: Path,
    *,
    sample_size: int | None = None,
    sample_seed: int = 0,
    verbose: bool = True,
) -> list[ValidationFailure]:
    """Validate a generation run directory. Returns the list of
    failures (empty list = all checks passed). Always continues past
    individual failures to give a complete report."""
    pkls = discover_worker_pickles(run_dir)
    if verbose:
        print(f"Discovered {len(pkls)} worker pickle(s) in {run_dir}")

    all_records = load_all_records(pkls)
    if verbose:
        print(f"Loaded {len(all_records)} game records "
               f"(DATA_VERSION check passed during load)")

    to_check = sample_records(all_records, sample_size, sample_seed)
    if verbose:
        if sample_size is not None and len(to_check) < len(all_records):
            print(f"Sampling {len(to_check)} of {len(all_records)} records "
                   f"(seed={sample_seed})")
        else:
            print(f"Checking all {len(to_check)} records")
        print()

    all_failures: list[ValidationFailure] = []
    for i, (rec, pkl_path) in enumerate(to_check):
        fails = check_record(rec, pkl_path=pkl_path)
        all_failures.extend(fails)
        if verbose and (i + 1) % 100 == 0:
            print(f"  ... checked {i + 1}/{len(to_check)} "
                   f"({len(all_failures)} failures so far)")

    return all_failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-dir", type=Path, required=True,
        help="Generation-run directory containing games/ and metadata.json",
    )
    parser.add_argument(
        "--sample-size", type=int, default=None,
        help="Validate this many random records instead of all. "
             "Useful for huge datasets where full-validation cost is "
             "the bottleneck.",
    )
    parser.add_argument(
        "--sample-seed", type=int, default=0,
        help="Seed for the sample selection (default 0). Same seed → "
             "same subset, useful for reproducible validation.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-progress output. Failures still reported.",
    )
    parser.add_argument(
        "--max-failures-shown", type=int, default=20,
        help="Cap on how many failures to print in the summary "
             "(default 20). All failures are still counted.",
    )
    args = parser.parse_args()

    if not args.run_dir.is_dir():
        print(f"ERROR: {args.run_dir} is not a directory.", file=sys.stderr)
        return 2

    try:
        failures = validate_run(
            args.run_dir,
            sample_size=args.sample_size,
            sample_seed=args.sample_seed,
            verbose=not args.quiet,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print()
    if not failures:
        print("All checks passed.")
        return 0

    # Group failures by check type for a useful summary.
    by_check: dict[str, list[ValidationFailure]] = {}
    for f in failures:
        by_check.setdefault(f.check, []).append(f)

    print(f"FAILED: {len(failures)} failure(s) across "
          f"{len(by_check)} check type(s):")
    print()
    for check, group in sorted(by_check.items()):
        print(f"  {check}: {len(group)} failure(s)")
    print()
    print(f"First {min(args.max_failures_shown, len(failures))} "
          f"failure(s) in detail:")
    for f in failures[:args.max_failures_shown]:
        print(f"  {f}")
    if len(failures) > args.max_failures_shown:
        print(f"  ... ({len(failures) - args.max_failures_shown} more)")

    return 1


if __name__ == "__main__":
    sys.exit(main())
