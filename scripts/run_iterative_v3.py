"""Iterative V3 tuning orchestrator.

Cycles through V3 categories N times. Within a pass, each category:
  - uses `--from <output of previous category in this chain>` as the
    warm-start base (so the cumulative tuned config from this pass's
    earlier categories is layered in)
  - uses `--resume <prior pass's pickle for THIS category>` on passes
    2+, continuing CMA-ES from where this category last left off

Per-pass order: fields_crops → food → resources → pastures_animals.

After each step, scripts/tune_heuristic.py auto-updates
`tuned_configs/v3_best.json` if the new holdout margin beats the
existing one (regardless of whether this run was a forward step in
the chain), so `v3_best.json` always reflects the strongest config
found anywhere in the iteration.

Usage:
    python scripts/run_iterative_v3.py             # defaults: 3 passes, 10 gens, n=100
    python scripts/run_iterative_v3.py --n-passes 1 --max-gens 5   # quick test
    python scripts/run_iterative_v3.py --label run2                # different output prefix
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


# Popsize follows CMA-ES default `4 + floor(3·ln(d))` for each category's
# parameter dimensionality. See run_iterative_v3.py docstring in the
# chat for the derivation.
CATEGORY_POPSIZE: dict[str, int] = {
    "v3_fields_crops":     16,   # d=60
    "v3_food":             13,   # d=18
    "v3_resources":        17,   # d=63
    "v3_pastures_animals": 18,   # d=101
}

# Per-pass order: the user-specified sequence.
CATEGORY_ORDER: list[str] = [
    "v3_fields_crops",
    "v3_food",
    "v3_resources",
    "v3_pastures_animals",
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-passes", type=int, default=3,
                   help="How many times to cycle through all 4 categories. Default 3.")
    p.add_argument("--max-gens", type=int, default=10,
                   help="Generations per category per pass. Default 10.")
    p.add_argument("--n-seeds", type=int, default=100,
                   help="Games per evaluation. Default 100.")
    p.add_argument("--start-from", type=Path,
                   default=ROOT / "tuned_configs" / "v3_best.json",
                   help="JSON file (with 'best_config' field) used as the warm-start "
                        "base for the very first category of pass 1. Default v3_best.json.")
    p.add_argument("--baseline", default="t2",
                   help="Opponent agent for fitness evaluation. Default t2 (V1+T2).")
    p.add_argument("--label", default="iter",
                   help="Prefix for output filenames in tuned_configs/.")
    p.add_argument("--start-step", type=int, default=1,
                   help="Skip the first (start-step - 1) steps. Useful for "
                        "resuming a partially-completed iteration. Step 1 = "
                        "pass 1's first category. Default 1 (no skipping).")
    p.add_argument("--initial-pickles", default="",
                   help="Comma-separated CATEGORY:PATH pairs to pre-populate "
                        "the per-category CMA-ES pickle map. Lets the orchestrator "
                        "--resume an existing run for a category on its FIRST "
                        "scheduled step. Example: "
                        "'v3_food:tuned_configs/iter_p1_v3_food.cma.pkl,"
                        "v3_fields_crops:tuned_configs/iter_p1_v3_fields_crops.cma.pkl'.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the command sequence without executing.")
    args = p.parse_args()

    current_from: Path = args.start_from
    if not current_from.exists() and not args.dry_run:
        raise SystemExit(f"--start-from path {current_from} does not exist.")

    pickles: dict[str, Path] = {}  # category -> previous pass's pickle path
    if args.initial_pickles.strip():
        for spec in args.initial_pickles.split(","):
            spec = spec.strip()
            if not spec:
                continue
            if ":" not in spec:
                raise SystemExit(
                    f"--initial-pickles entry {spec!r} must be CATEGORY:PATH")
            cat, path = spec.split(":", 1)
            cat = cat.strip()
            path = Path(path.strip())
            if cat not in CATEGORY_POPSIZE:
                raise SystemExit(
                    f"--initial-pickles category {cat!r} is not a known "
                    f"category ({list(CATEGORY_POPSIZE)})")
            if not path.exists() and not args.dry_run:
                raise SystemExit(
                    f"--initial-pickles path {path} does not exist")
            pickles[cat] = path
            print(f"  pre-populated pickle for {cat}: {path}")

    out_dir = ROOT / "tuned_configs"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_steps = args.n_passes * len(CATEGORY_ORDER)
    step = 0
    t0 = time.time()

    print(f"Iterative V3 tuning")
    print(f"  passes: {args.n_passes}")
    print(f"  categories per pass: {CATEGORY_ORDER}")
    print(f"  total steps: {total_steps}")
    print(f"  max-gens per step: {args.max_gens}")
    print(f"  n-seeds per evaluation: {args.n_seeds}")
    print(f"  starting from: {current_from}")
    print()

    for pass_idx in range(1, args.n_passes + 1):
        print(f"{'='*72}")
        print(f"  PASS {pass_idx} / {args.n_passes}")
        print(f"{'='*72}")

        for cat in CATEGORY_ORDER:
            step += 1
            output = out_dir / f"{args.label}_p{pass_idx}_{cat}.json"
            resume_pkl = pickles.get(cat)

            # --start-step lets us skip already-completed steps. For skipped
            # steps we don't execute, but we DO advance the chain: set
            # current_from to the step's expected output JSON (must already
            # exist on disk) and update pickles[cat] to the step's pickle.
            if step < args.start_step:
                print(f"\n--- step {step}/{total_steps}: pass {pass_idx}, {cat} (SKIPPED) ---")
                if not args.dry_run and not output.exists():
                    raise SystemExit(
                        f"--start-step {args.start_step} skips step {step} but "
                        f"its expected output {output} doesn't exist. Either "
                        f"reduce --start-step or pre-populate the missing files."
                    )
                current_from = output
                pickles[cat] = output.with_suffix(".cma.pkl")
                continue

            cmd = [
                sys.executable, "-O", str(ROOT / "scripts" / "tune_heuristic.py"),
                "--category",  cat,
                "--from",      str(current_from),
                "--baseline",  args.baseline,
                "--max-gens",  str(args.max_gens),
                "--popsize",   str(CATEGORY_POPSIZE[cat]),
                "--n-seeds",   str(args.n_seeds),
                "--output",    str(output),
            ]
            if resume_pkl is not None and resume_pkl.exists():
                cmd.extend(["--resume", str(resume_pkl)])

            print(f"\n--- step {step}/{total_steps}: pass {pass_idx}, {cat} ---")
            print(f"  --from {current_from}")
            if resume_pkl is not None and resume_pkl.exists():
                print(f"  --resume {resume_pkl}")
            elif resume_pkl is not None:
                print(f"  (no resume; expected pickle {resume_pkl} missing — "
                      f"starting fresh for this category)")
            print(f"  output: {output}")
            print(f"  popsize: {CATEGORY_POPSIZE[cat]}, n-seeds: {args.n_seeds}, "
                  f"max-gens: {args.max_gens}")

            if args.dry_run:
                print(f"  DRY-RUN: would invoke `{' '.join(cmd)}`")
            else:
                t_step = time.time()
                rc = subprocess.call(cmd)
                step_elapsed = time.time() - t_step
                if rc != 0:
                    print(f"\n!!! Step {step} failed (rc={rc}) on category {cat}.")
                    print(f"!!! Stopping the iterative run.")
                    return rc
                print(f"  ✓ step completed in {step_elapsed / 60:.1f} min "
                      f"(cumulative {(time.time() - t0) / 60:.1f} min)")

            current_from = output
            pickles[cat] = output.with_suffix(".cma.pkl")

    print()
    print(f"{'='*72}")
    total_min = (time.time() - t0) / 60
    print(f"  ALL {total_steps} STEPS COMPLETE in {total_min:.1f} min "
          f"({total_min / 60:.1f} hours)")
    print(f"{'='*72}")
    print()
    print(f"Final config chain ended at: {current_from}")
    print(f"v3_best.json was auto-updated whenever a step's holdout improved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
