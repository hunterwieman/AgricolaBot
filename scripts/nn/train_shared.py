"""Train the joint shared-trunk value+policy model — thin CLI over
`agricola.agents.nn.shared_training.train_shared()`.

One trunk feeds the value head + every policy head; they train together on the
self-play data (one cached one-pass encode, reused across architecture sweeps).
The architecture is fully parameterized — pass the trunk/embedding/head shapes;
nothing is baked in.

CLI usage:

    # Smoke run
    python scripts/nn/train_shared.py \\
        --run-dir data/nn_training/runs/cpp_selfplay_10k \\
        --trunk-hidden-dims 256,256 --embedding-dim 256 --max-epochs 4

    # Production: all v3 self-play, warm-start trunk from the value-sweep winner
    python scripts/nn/train_shared.py \\
        --run-dir data/nn_training/runs/cpp_selfplay_30k \\
                  data/nn_training/runs/cpp_selfplay_10k \\
                  data/nn_training/runs/cpp_ab_batch \\
        --trunk-hidden-dims 512,512 --embedding-dim 128 \\
        --init-from nn_models/sp_v_512x2/best --save-all-epochs

Outputs under `--out-dir` (defaults to `nn_models/<auto-id>/`):
    best.pt + best.meta.json   # best value-val-MSE checkpoint + metadata
    config.json                # full run configuration
    train_log.jsonl            # per-epoch value MSE/MAE + per-head val CE
    epoch_NNN.pt               # (with --save-all-epochs) for play-based selection
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.shared_training import train_shared  # noqa: E402
from agricola.agents.nn.training import make_run_id  # noqa: E402


def _dims(s: str) -> list[int]:
    s = s.strip()
    return [] if not s else [int(x) for x in s.split(",") if x != ""]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, nargs="+", required=True)
    p.add_argument("--out-dir", type=Path, default=None)
    # architecture (agnostic)
    p.add_argument("--trunk-hidden-dims", type=_dims, default=[256, 256])
    p.add_argument("--embedding-dim", type=int, default=256)
    p.add_argument("--value-head-dims", type=_dims, default=[])
    p.add_argument("--fixed-head-dims", type=_dims, default=[])
    p.add_argument("--pointer-head-dims", type=_dims, default=[64])
    p.add_argument("--activation", type=str, default="gelu",
                   choices=["gelu", "silu", "relu", "tanh"])
    p.add_argument("--norm", type=str, default="layer", choices=["layer", "none"])
    p.add_argument("--dropout", type=float, default=0.0)
    p.add_argument("--no-embed-norm", dest="embed_norm", action="store_false")
    # task balancing
    p.add_argument("--value-weight", type=float, default=None,
                   help="Task-sampling weight for the value task (default: #heads, "
                        "so value gets ~half the steps and heads split the rest).")
    p.add_argument("--head-weight", type=float, default=1.0)
    # optimization
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=2048)
    p.add_argument("--max-epochs", type=int, default=40)
    p.add_argument("--early-stop-patience", type=int, default=8)
    p.add_argument("--steps-per-epoch", type=int, default=None)
    p.add_argument("--no-fast-loader", dest="fast_loader", action="store_false",
                   help="Use the per-row DataLoader instead of the batched-index "
                        "fast path (slower; for debugging / parity checks).")
    # data
    p.add_argument("--hard-targets", dest="soft_targets", action="store_false",
                   help="One-hot BC instead of cross-entropy against π.")
    p.add_argument("--no-cache", dest="use_cache", action="store_false")
    p.add_argument("--split-seed", type=int, default=0)
    p.add_argument("--store-dtype", type=str, default="float16",
                   choices=["float16", "float32"])
    # misc
    p.add_argument("--init-from", type=Path, default=None,
                   help="Value checkpoint to warm-start the trunk from "
                        "(shape-tolerant; only matching trunk layers transplant).")
    p.add_argument("--save-all-epochs", action="store_true")
    p.add_argument("--torch-seed", type=int, default=42)
    p.add_argument("--device", type=str, default="cpu", choices=["cpu", "mps", "cuda"])
    p.set_defaults(embed_norm=True, soft_targets=True, use_cache=True, fast_loader=True)
    args = p.parse_args()

    out_dir = args.out_dir or (ROOT / "nn_models" / make_run_id())
    train_shared(
        run_dirs=args.run_dir, out_dir=out_dir,
        trunk_hidden_dims=args.trunk_hidden_dims, embedding_dim=args.embedding_dim,
        value_head_dims=args.value_head_dims, fixed_head_dims=args.fixed_head_dims,
        pointer_head_dims=args.pointer_head_dims, activation=args.activation,
        norm=args.norm, dropout=args.dropout, embed_norm=args.embed_norm,
        value_weight=args.value_weight, head_weight=args.head_weight,
        lr=args.lr, weight_decay=args.weight_decay, batch_size=args.batch_size,
        max_epochs=args.max_epochs, early_stop_patience=args.early_stop_patience,
        steps_per_epoch=args.steps_per_epoch, fast_loader=args.fast_loader,
        soft_targets=args.soft_targets,
        split_seed=args.split_seed, store_dtype=args.store_dtype,
        use_cache=args.use_cache, init_from=args.init_from,
        save_all_epochs=args.save_all_epochs, torch_seed=args.torch_seed,
        device=args.device,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
