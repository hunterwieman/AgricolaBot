#!/usr/bin/env python
"""Standalone joint-dataset encoder — materialize the shared chunk cache WITHOUT
training.

Why this exists: the joint shared-trunk chunk cache
(`<run_dir>/shared_<encoder_tag>_chunks/`) is keyed only on the encoder tag + head
roster, NOT on model architecture or activation, and `snapshot_keep` is applied at
load time (seeded, deterministic) — NOT baked into the cache. So one full encode is
shared by every subsequent `train_shared.py` run over the same run-dirs/encoder, and
each run thins to the identical seeded subsample at load.

The catch: if several trainings start cold in parallel they would RACE writing the
same chunk files. So the cache must be built ONCE up front, then the parallel
trainings read it read-only. This script is that one-time build step.

It calls `_load_or_encode_run_dir` directly (the function that writes the per-pickle
chunk npzs) rather than `build_shared_datasets`, so it only materializes the cache —
it does not finalize/hold the full in-memory datasets.

    python scripts/nn/encode_shared.py \
        --run-dir data/nn_training/runs/run_a data/nn_training/runs/run_b \
        --encoder v2 --encode-workers 16
"""
import argparse
from pathlib import Path

from agricola.agents.nn.encoder import ENCODERS
from agricola.agents.nn.shared_dataset import (
    _load_or_encode_run_dir,
    full_legal_actions,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, nargs="+", required=True,
                   help="One or more self-play run dirs to encode.")
    p.add_argument("--encoder", type=str, default="v2", choices=sorted(ENCODERS),
                   help="Feature schema (must match what training will use).")
    p.add_argument("--encode-workers", type=int, default=1,
                   help="Process-pool size for the per-pickle encode.")
    args = p.parse_args()

    spec = ENCODERS[args.encoder]
    for rd in args.run_dir:
        print(f"=== encoding {rd}  [encoder={spec.tag}, workers={args.encode_workers}] ===",
              flush=True)
        chunks = _load_or_encode_run_dir(
            Path(rd), full_legal_actions, soft_targets=True, use_cache=True,
            verbose=True, encoder=spec, n_workers=args.encode_workers, max_games=None)
        print(f"    -> {len(chunks)} chunks in "
              f"{Path(rd) / f'shared_{spec.tag}_chunks'}", flush=True)
    print("encode_shared: done", flush=True)


if __name__ == "__main__":
    main()
