#!/usr/bin/env python
"""Post-hoc retention eval: measure each checkpoint's raw-margin MAE on a
FIXED held-out slice of the BROAD (heuristic) data distribution.

Motivation (FIRST_NN.md, the Option-B fine-tune): when a model is fine-tuned
on a narrow self-play dataset, its own val split only measures fit-to-the-new
distribution — it cannot reveal whether the fine-tune is *degrading* the broad
distribution the base model (M82k) was strong on. This script supplies that
missing instrument: encode a broad-distribution probe set ONCE, then sweep a
set of checkpoints (e.g. every saved epoch of each L2-SP arm) computing
raw-margin MAE in points, with the base model as the baseline line.

The probe set uses the SAME (state, perspective) → margin target convention as
`dataset.py:_encode_one` (margin mode), and `predict_margin` denormalizes each
model with its own target_std, so MAE-in-points is comparable across models
regardless of their internal NormStats.

NOTE: MAE is a diagnostic, not strength (the project's recurring MAE≠strength
theme). Use this to understand forgetting / pick lambda; the head-to-head vs
the base model stays the acceptance gate.

Usage:
    python scripts/nn/retention_eval.py \
        --probe-dir data/nn_training/runs/standard_bimodal_5k \
        --probe-games 400 \
        --baseline nn_models/M_82k_warmM62k/best.pt \
        --sweep "nn_models/ftA_plain_M82k_nn70t2/epoch_*.pt" \
                "nn_models/ftB1_l2sp1e3_M82k_nn70t2/epoch_*.pt" \
                "nn_models/ftB2_l2sp1e2_M82k_nn70t2/epoch_*.pt"
"""
import argparse
import glob
import re
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.schema import load_game_records  # noqa: E402
from agricola.agents.nn.encoder import encode_state, ENCODED_DIM  # noqa: E402
from agricola.agents.nn.model import NormalizedValueModel  # noqa: E402


def build_probe_set(probe_dir: Path, n_games: int):
    """Load up to the LAST `n_games` GameRecords from a run dir and expand to
    (X, y) over both perspectives of every non-singleton snapshot + the
    terminal state — mirroring dataset.py margin-mode targets exactly.

    Using the *last* games keeps the probe disjoint from any prefix-based
    sampling and is deterministic given the run dir."""
    pkls = sorted(probe_dir.glob("games/worker_*.pkl"))
    games = []
    for p in pkls:
        games.extend(load_game_records(p))
    games.sort(key=lambda g: g.game_idx)
    if n_games and n_games < len(games):
        games = games[-n_games:]

    feats, targs = [], []
    for g in games:
        states = [(d.state, False) for d in g.decisions]
        states.append((g.terminal_state, True))
        for state, _is_term in states:
            m0 = float(g.p0_final_score - g.p1_final_score)
            for persp, m in ((0, m0), (1, -m0)):
                feats.append(encode_state(state, persp))
                targs.append(m)
    X = np.asarray(feats, dtype=np.float32).reshape(-1, ENCODED_DIM)
    y = np.asarray(targs, dtype=np.float32)
    return X, y, len(games)


@torch.no_grad()
def model_mae(model: NormalizedValueModel, X: torch.Tensor, y: torch.Tensor,
              batch_size: int = 8192) -> float:
    model.eval()
    sum_abs = 0.0
    n = X.shape[0]
    for s in range(0, n, batch_size):
        pred = model.predict_margin(X[s:s + batch_size])
        sum_abs += (pred.squeeze(-1) - y[s:s + batch_size]).abs().sum().item()
    return sum_abs / n


def _epoch_of(path: str) -> int:
    m = re.search(r"epoch_(\d+)", path)
    return int(m.group(1)) if m else -1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--probe-dir", type=Path, required=True,
                   help="Run dir of BROAD-distribution data to validate on.")
    p.add_argument("--probe-games", type=int, default=400,
                   help="Use the last N games of the probe dir (default 400).")
    p.add_argument("--baseline", type=Path, default=None,
                   help="Base checkpoint (e.g. M82k best.pt) for the reference line.")
    p.add_argument("--sweep", type=str, nargs="+", default=[],
                   help="Glob(s) of checkpoints to sweep (e.g. arm epoch_*.pt).")
    args = p.parse_args()

    print(f"Building probe set from {args.probe_dir} (last {args.probe_games} games)...")
    X, y, n_games = build_probe_set(args.probe_dir, args.probe_games)
    Xt = torch.from_numpy(X)
    yt = torch.from_numpy(y)
    print(f"  probe: {n_games} games -> {X.shape[0]} descriptors "
          f"(both perspectives + terminal)\n")

    if args.baseline:
        base = NormalizedValueModel.load(args.baseline)
        base_mae = model_mae(base, Xt, yt)
        print(f"BASELINE  {args.baseline.parent.name:32s}  MAE = {base_mae:.4f} pts\n")
    else:
        base_mae = None

    # group sweep paths by their parent dir (= arm)
    groups: dict[str, list[str]] = {}
    for pattern in args.sweep:
        for path in glob.glob(pattern):
            groups.setdefault(str(Path(path).parent.name), []).append(path)

    for arm, paths in groups.items():
        paths = sorted(paths, key=_epoch_of)
        print(f"=== {arm} ===")
        print(f"{'epoch':>6} | {'retention MAE (pts)':>20} | "
              f"{'vs baseline':>12}")
        print("-" * 46)
        for path in paths:
            mdl = NormalizedValueModel.load(path)
            mae = model_mae(mdl, Xt, yt)
            delta = f"{mae - base_mae:+.4f}" if base_mae is not None else "n/a"
            print(f"{_epoch_of(path):>6} | {mae:>20.4f} | {delta:>12}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
