"""One-off validation of the fast-loader (NN_TRAINING_SPEEDUP.md A+B).

Compares the default DataLoader path vs the batched-index fast path, and
sweeps LR at bs=8192, on a representative blend dir. Reports best val/test
MAE (quality) and avg epoch time (speed) per config so we can pick an LR
whose val MAE matches the bs=512 baseline.
"""
from __future__ import annotations
import json, sys, time, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from agricola.agents.nn.training import train  # noqa: E402

RUN = [ROOT / "data/nn_training/runs/blend_nnforward_10k"]
COMMON = dict(
    run_dirs=RUN, hidden_dims=[256, 256, 256, 128], activation="gelu",
    norm="layer", dropout=0.2, weight_decay=1e-4, max_epochs=50,
    early_stop_patience=15, train_frac=0.8, val_frac=0.1, split_seed=0,
    sample_seed=1, torch_seed=42, device="cpu", target_mode="margin",
    use_cache=True, train_keep_frac=1.0, verbose=False,
)
CONFIGS = [
    ("baseline_bs512_lr1e-3", dict(fast_loader=False, batch_size=512, lr=1e-3)),
    ("fast_bs512_lr1e-3",     dict(fast_loader=True,  batch_size=512, lr=1e-3)),
    ("fast_bs8192_lr1e-3",    dict(fast_loader=True,  batch_size=8192, lr=1e-3)),
    ("fast_bs8192_lr2e-3",    dict(fast_loader=True,  batch_size=8192, lr=2e-3)),
    ("fast_bs8192_lr3e-3",    dict(fast_loader=True,  batch_size=8192, lr=3e-3)),
]

rows = []
for name, cfg in CONFIGS:
    out = Path(tempfile.mkdtemp()) / name
    t0 = time.perf_counter()
    log, _ = train(out_dir=out, **COMMON, **cfg)
    wall = time.perf_counter() - t0
    tm = json.load(open(out / "test_metrics.json"))
    n_ep = len(log)
    # per-epoch time from the log if present, else wall/n_ep
    times = [e.get("time") for e in log if e.get("time") is not None]
    avg_ep = (sum(times) / len(times)) if times else (wall / max(n_ep, 1))
    rows.append((name, tm["test_mae_margin"], tm["best_val_mse"],
                 tm["best_epoch"], n_ep, avg_ep))
    print(f"{name:22s} testMAE={tm['test_mae_margin']:.3f} "
          f"valMSE={tm['best_val_mse']:.4f} bestEp={tm['best_epoch']} "
          f"nEp={n_ep} {avg_ep:.1f}s/ep", flush=True)

print("\n=== SUMMARY (Δ vs baseline) ===")
base_mae = rows[0][1]
base_ep = rows[0][5]
for name, mae, _vm, _be, _ne, aep in rows:
    print(f"{name:22s}  testMAE {mae:.3f} (Δ{mae - base_mae:+.3f})  "
          f"{aep:5.1f}s/ep ({base_ep / aep:.1f}x)")
