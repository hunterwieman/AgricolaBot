"""Train the first NN value function — thin CLI wrapper around
`agricola.agents.nn.training.train()`.

All training logic (data loading, model construction, train/val loop,
early stopping, checkpointing, logging, plots) lives in the library at
`agricola/agents/nn/training.py` so it's reusable from other scripts
(future sweeps, programmatic runs, tests). This script is just argparse
+ a single call into `train()`.

CLI usage:

    # Smoke run — small subset, few epochs
    python scripts/nn/train_first.py \\
        --run-dir data/nn_training/runs/<run-id> \\
        --train-sample-size 10000 --max-epochs 3

    # Production run — all data, default architecture
    python scripts/nn/train_first.py \\
        --run-dir data/nn_training/runs/<run-id>

Outputs under `--out-dir` (defaults to `nn_models/<auto-id>/`):
    best.pt + best.meta.json   # best-val checkpoint + metadata sidecar
    config.json                # training-run configuration
    norm_stats.json            # NormStats used (for reference/debug)
    train_log.jsonl            # one JSON object per epoch
    test_metrics.json          # final test MSE/MAE on the best checkpoint
    train_curves.png           # train/val loss over epochs
    calibration.png            # predicted-vs-actual margin scatter on val set
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.training import make_run_id, train  # noqa: E402


def _parse_hidden_dims(s: str) -> list[int]:
    """Parse '256,256' → [256, 256]."""
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-dir", type=Path, nargs="+", required=True,
        help="One or more data-generation run directories (will be combined).",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help="Output directory. Default: nn_models/<auto-id>/",
    )
    # Architecture
    parser.add_argument("--hidden-dims", type=_parse_hidden_dims, default="256,256",
                        help="Comma-separated hidden layer widths. Default: 256,256")
    parser.add_argument("--activation", type=str, default="gelu",
                        choices=["gelu", "silu", "relu", "tanh"])
    parser.add_argument("--norm", type=str, default="layer", choices=["layer", "none"])
    parser.add_argument("--dropout", type=float, default=0.0)
    # Optimization
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--max-epochs", type=int, default=50)
    parser.add_argument("--early-stop-patience", type=int, default=10)
    parser.add_argument("--loss", type=str, default="mse", choices=["mse", "huber"],
                        help="Regression loss for margin/outcome modes. "
                             "winprob always uses BCE regardless.")
    parser.add_argument("--target-mode", type=str, default="margin",
                        choices=["margin", "outcome", "winprob"],
                        help="Supervision target (Experiment P2): margin "
                             "(score-diff, linear head), outcome (+1/0/-1, "
                             "tanh head), or winprob (1/0.5/0, sigmoid head). "
                             "Head is auto-selected to match unless --head given.")
    parser.add_argument("--head", type=str, default=None,
                        choices=["linear", "tanh", "sigmoid"],
                        help="Override the output-head activation. Default: "
                             "auto from --target-mode.")
    # Dataset
    parser.add_argument("--chunked", action="store_true", default=False,
                        help="Low-memory build: load one worker pickle at a "
                             "time, accumulate float16 arrays. Needed for "
                             "large game collections (~55k+) that don't fit in "
                             "RAM all at once.")
    parser.add_argument("--train-keep-frac", type=float, default=1.0,
                        help="(chunked only) Randomly keep this fraction of "
                             "TRAIN state-keys — shrinks the array / cuts "
                             "within-game redundancy. Default 1.0 = keep all.")
    parser.add_argument("--train-game-frac", type=float, default=1.0,
                        help="(chunked only) Randomly keep this fraction of "
                             "TRAIN *games* whole (every snapshot of surviving "
                             "games). The control arm vs --train-keep-frac for "
                             "the within-game-redundancy experiment (FIRST_NN "
                             "§13.1). Default 1.0 = keep all.")
    parser.add_argument("--store-dtype", type=str, default="float16",
                        choices=["float16", "float32"],
                        help="(chunked only) Encoded-array dtype. float16 "
                             "halves RAM; upcast to f32 per-item at access.")
    parser.add_argument("--use-cache", action="store_true", default=False,
                        help="Per-run-dir encoded-vector cache (FIRST_NN §10.5): "
                             "skip re-encoding when a valid <run>/encoded_vN.npz "
                             "exists; write it on a miss. Implies the chunked path "
                             "+ seed-hash split (NOT MAE-comparable to the "
                             "permutation-split build_datasets).")
    parser.add_argument("--init-from", type=Path, default=None,
                        help="Warm-start: initialize the net weights from this "
                             "checkpoint (.pt) before training (e.g. a killed "
                             "run's best.pt) for faster convergence. Freshly-fit "
                             "NormStats are kept; optimizer state is not restored.")
    parser.add_argument("--train-sample-size", type=int, default=None,
                        help="Cap on train descriptors (paired). Default: use all.")
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--val-frac", type=float, default=0.1)
    # Seeds + device
    parser.add_argument("--split-seed", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=1)
    parser.add_argument("--torch-seed", type=int, default=42)
    parser.add_argument("--device", type=str, default="cpu",
                        choices=["cpu", "mps", "cuda"])
    args = parser.parse_args()

    out_dir = args.out_dir or (ROOT / "nn_models" / make_run_id())

    train(
        run_dirs=args.run_dir,
        out_dir=out_dir,
        hidden_dims=args.hidden_dims,
        activation=args.activation,
        norm=args.norm,
        dropout=args.dropout,
        lr=args.lr,
        weight_decay=args.weight_decay,
        batch_size=args.batch_size,
        max_epochs=args.max_epochs,
        early_stop_patience=args.early_stop_patience,
        train_sample_size=args.train_sample_size,
        train_frac=args.train_frac,
        val_frac=args.val_frac,
        split_seed=args.split_seed,
        sample_seed=args.sample_seed,
        torch_seed=args.torch_seed,
        device=args.device,
        loss_type=args.loss,
        target_mode=args.target_mode,
        head=args.head,
        chunked=args.chunked,
        train_keep_frac=args.train_keep_frac,
        train_game_frac=args.train_game_frac,
        store_dtype=args.store_dtype,
        use_cache=args.use_cache,
        init_from=args.init_from,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
