"""Train a pointer (score-the-legal-set) policy head — thin CLI over
`agricola.agents.nn.policy_pointer_training.train_pointer()`.

All logic (ragged extraction, segment-CE loss, scorer model, train/val loop,
early stop, checkpointing, plots) lives in the library; this is argparse + one
call. Two pointer heads exist: `animal_frontier` (CommitBreed + CommitAccommodate)
and `harvest_feed` (CommitConvert + CommitHarvestConversion).

Default `--run-dir` is the union of the three hidden-info runs. All DATA_VERSION-2
hidden-info data is valid here (not just hidden_info_v2_10k) because a pointer head
enumerates the **full** engine frontier (`legal_actions`, not the restricted
wrapper), so the recorded chosen commit is always within its candidate set
regardless of which wrapper generated the game — the labels are
forcing-fix-invariant.

CLI usage:

    # Smoke run
    python scripts/nn/train_policy_pointer.py \\
        --run-dir data/nn_training/runs/hidden_info_v2_10k \\
        --hidden-dims 16,16 --max-epochs 3 --out-dir nn_models/pointer_smoke

    # Production — all hidden-info runs, AWR weighting
    python scripts/nn/train_policy_pointer.py --loss-weight awr

Outputs under `--out-dir` (default `nn_models/<auto-id>/`):
    best.pt + best.meta.json    # best-val-CE checkpoint (model_kind=policy_pointer)
    config.json                 # training-run configuration
    pointer_norm_stats.json     # PointerNormStats used
    train_log.jsonl             # one JSON object per epoch
    test_metrics.json           # final test segment-CE + top-1/top-3 (overall + winners)
    train_curves.png            # CE + top-1/top-3 over epochs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.policy_heads import POINTER_HEADS  # noqa: E402
from agricola.agents.nn.policy_pointer_training import train_pointer  # noqa: E402
from agricola.agents.nn.training import make_run_id  # noqa: E402

# All hidden-info runs are valid for pointer heads (see module docstring).
DEFAULT_RUN_DIRS = [
    ROOT / "data/nn_training/runs/hidden_info_v2_10k",
    ROOT / "data/nn_training/runs/hidden_info_bimodal_20k",
    ROOT / "data/nn_training/runs/hidden_info_nnblend_10k",
]


def _parse_hidden_dims(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--run-dir", type=Path, nargs="+", default=None,
                   help="Data-generation run directories. Default: the three "
                        "hidden-info runs (all DATA_VERSION-2 data is valid here).")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Output directory. Default: nn_models/<auto-id>/")
    p.add_argument("--head", type=str, default="animal_frontier",
                   choices=sorted(POINTER_HEADS),
                   help="Which pointer head to train (policy_heads.POINTER_HEADS).")
    # Loss / weighting
    p.add_argument("--loss-weight", type=str, default="unweighted",
                   choices=["unweighted", "awr"])
    p.add_argument("--value-ckpt", type=str, default="nn_models/best",
                   help="(awr) Value checkpoint for the advantage baseline.")
    p.add_argument("--awr-clip", type=float, default=6.0)
    # Architecture
    p.add_argument("--hidden-dims", type=_parse_hidden_dims, default="256,256")
    p.add_argument("--activation", type=str, default="gelu",
                   choices=["gelu", "silu", "relu", "tanh"])
    p.add_argument("--norm", type=str, default="layer", choices=["layer", "none"])
    p.add_argument("--dropout", type=float, default=0.2)
    # Optimization
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--max-epochs", type=int, default=50)
    p.add_argument("--early-stop-patience", type=int, default=10)
    # Warm-start
    p.add_argument("--init-from", type=Path, default=None,
                   help="Warm-start: transplant matching trunk tensors (deeper "
                        "layers only — the input width differs from the value net).")
    # Seeds / device
    p.add_argument("--train-frac", type=float, default=0.8)
    p.add_argument("--val-frac", type=float, default=0.1)
    p.add_argument("--split-seed", type=int, default=0)
    p.add_argument("--torch-seed", type=int, default=42)
    p.add_argument("--device", type=str, default="cpu", choices=["cpu", "mps", "cuda"])
    p.add_argument("--hard-targets", dest="soft_targets", action="store_false",
                   help="Train one-hot behavioral cloning of the played candidate "
                        "instead of the default segment cross-entropy against the "
                        "MCTS visit distribution π (used when present).")
    p.set_defaults(soft_targets=True)
    args = p.parse_args()

    run_dirs = args.run_dir or DEFAULT_RUN_DIRS
    out_dir = args.out_dir or (ROOT / "nn_models" / make_run_id())
    train_pointer(
        run_dirs=run_dirs,
        out_dir=out_dir,
        head=POINTER_HEADS[args.head],
        loss_weight=args.loss_weight,
        value_ckpt=args.value_ckpt,
        awr_clip=args.awr_clip,
        hidden_dims=args.hidden_dims,
        activation=args.activation,
        norm=args.norm,
        dropout=args.dropout,
        lr=args.lr,
        weight_decay=args.weight_decay,
        batch_size=args.batch_size,
        max_epochs=args.max_epochs,
        early_stop_patience=args.early_stop_patience,
        init_from=args.init_from,
        train_frac=args.train_frac,
        val_frac=args.val_frac,
        split_seed=args.split_seed,
        torch_seed=args.torch_seed,
        device=args.device,
        soft_targets=args.soft_targets,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
