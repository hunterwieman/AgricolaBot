"""Train the placement-policy network — thin CLI over
`agricola.agents.nn.policy_training.train_policy()`.

All logic (extraction, AWR weighting, model, train/val loop, early stop,
checkpointing, plots) lives in the library; this is argparse + one call.

CLI usage:

    # Smoke run — one dir, few epochs, unweighted
    python scripts/nn/train_policy.py \\
        --run-dir data/nn_training/runs/standard_bimodal_5k \\
        --hidden-dims 16,16 --max-epochs 3 --out-dir nn_models/policy_smoke

    # Production — all populated dirs, AWR weighting, warm-started trunk
    python scripts/nn/train_policy.py \\
        --run-dir data/nn_training/runs/standard_bimodal_5k \\
                  data/nn_training/runs/S1_standard_bimodal_10k ... \\
        --loss-weight awr --init-from nn_models/best

Outputs under `--out-dir` (default `nn_models/<auto-id>/`):
    best.pt + best.meta.json   # best-val-CE checkpoint + metadata sidecar
    config.json                # training-run configuration
    policy_norm_stats.json     # PolicyNormStats used
    train_log.jsonl            # one JSON object per epoch
    test_metrics.json          # final test CE + top-1/top-3 (overall + winners)
    train_curves.png           # CE + top-1/top-3 over epochs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.policy_heads import HEADS  # noqa: E402
from agricola.agents.nn.policy_training import train_policy  # noqa: E402
from agricola.agents.nn.training import make_run_id  # noqa: E402


def _parse_hidden_dims(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--run-dir", type=Path, nargs="+", required=True,
                   help="One or more data-generation run directories.")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Output directory. Default: nn_models/<auto-id>/")
    p.add_argument("--head", type=str, default="placement", choices=sorted(HEADS),
                   help="Which decision-type head to train (policy_heads.HEADS).")
    # Loss / weighting
    p.add_argument("--loss-weight", type=str, default="unweighted",
                   choices=["unweighted", "awr"],
                   help="Per-example loss weighting: unweighted (plain BC) or awr "
                        "(advantage-weighted, value-net baseline).")
    p.add_argument("--value-ckpt", type=str, default="nn_models/best",
                   help="(awr) Value checkpoint for the advantage baseline.")
    p.add_argument("--awr-clip", type=float, default=6.0,
                   help="(awr) Max weight w_max in clip(exp(A/β), 0, w_max).")
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
                   help="Warm-start: transplant the matching trunk tensors from "
                        "this value checkpoint (requires --hidden-dims 256,256).")
    # Dataset / seeds / device
    p.add_argument("--store-dtype", type=str, default="float16",
                   choices=["float16", "float32"])
    p.add_argument("--train-frac", type=float, default=0.8)
    p.add_argument("--val-frac", type=float, default=0.1)
    p.add_argument("--split-seed", type=int, default=0)
    p.add_argument("--torch-seed", type=int, default=42)
    p.add_argument("--device", type=str, default="cpu", choices=["cpu", "mps", "cuda"])
    p.add_argument("--legality", type=str, default="restricted",
                   choices=["restricted", "full"],
                   help="Legality for the legal mask: 'restricted' (default; "
                        "restricted_legal_actions) or 'full' (unrestricted "
                        "legal_actions). Use 'full' for the fencing head.")
    args = p.parse_args()

    legal_actions_fn = None
    if args.legality == "full":
        from agricola.legality import legal_actions as legal_actions_fn

    out_dir = args.out_dir or (ROOT / "nn_models" / make_run_id())
    train_policy(
        run_dirs=args.run_dir,
        out_dir=out_dir,
        head=HEADS[args.head],
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
        store_dtype=args.store_dtype,
        train_frac=args.train_frac,
        val_frac=args.val_frac,
        split_seed=args.split_seed,
        torch_seed=args.torch_seed,
        device=args.device,
        legal_actions_fn=legal_actions_fn,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
