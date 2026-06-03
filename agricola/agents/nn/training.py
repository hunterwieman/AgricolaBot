"""Training library for the NN value function.

The reusable functions called by `scripts/nn/train_first.py` (and by
future training scripts / sweeps). The script itself is a thin CLI
wrapper around `train()`.

Public surface (importable as `agricola.agents.nn.training.X`):

- `train(...)` — main programmatic entry. Runs the full training cycle
  for one configuration: builds datasets, model, optimizer; per-epoch
  train+val with early stopping; saves best checkpoint + JSONL log +
  config + final test metrics + plots.
- `train_one_epoch(...)` / `evaluate(...)` — the inner train/eval steps,
  exposed for reuse (e.g., custom training scripts that want to inject
  per-batch behavior).
- `setup_seeds(seed)` — seed Python/NumPy/Torch from a single integer.
- `make_run_id()` — timestamp-based id matching the data-gen convention.
- `current_git_sha()` — best-effort SHA for run metadata.
- `save_curves_plot(...)` / `save_calibration_plot(...)` — matplotlib
  plots (optional dependency; gracefully skips if not installed).
- `print_header()` / `print_epoch_line(...)` — terminal logging helpers.

This module imports torch — it's the torch-dependent library code, in
the same boat as `model.py` and `dataset.py`. Not re-exported from
`__init__.py` to preserve the torch-free data-generation path.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

from agricola.agents.nn.dataset import build_datasets, build_datasets_chunked
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import (
    ConfigurableMLP,
    NormalizedValueModel,
    measure_leaf_value_scale,
)
from agricola.agents.nn.schema import DATA_VERSION


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def setup_seeds(seed: int) -> None:
    """Seed Python/NumPy/Torch from a single integer. CPU training is
    fully deterministic given these seeds plus a seeded DataLoader
    generator (CUDA isn't, even with `manual_seed`)."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def make_run_id() -> str:
    """Timestamp + short hash. Matches `data/nn_training/runs/<id>/`
    convention from the data-gen pipeline."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = format(int(time.time() * 1000) % 0xFFFF, "04x")
    return f"{ts}-{suffix}"


def current_git_sha() -> str:
    """Best-effort current git SHA — recorded in the run config for
    reproducibility. Returns 'unknown' if not in a repo."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# ---------------------------------------------------------------------------
# Training and evaluation primitives
# ---------------------------------------------------------------------------


def _l2sp_penalty(model, l2sp_lambda, l2sp_anchor):
    """L2-SP anchor penalty: λ·Σ‖θ − θ₀‖² over the learnable net weights,
    where θ₀ is the warm-start checkpoint (FIRST_NN.md §13.1 anchored
    fine-tuning). Unlike AdamW weight_decay (which pulls toward 0), this
    pulls toward the warm-start values, making the anchor a trust region.
    Returns a scalar tensor (0.0 when disabled)."""
    if not l2sp_lambda or l2sp_anchor is None:
        return None
    total = None
    for name, p in model.net.named_parameters():
        a = l2sp_anchor.get(name)
        if a is None:
            continue
        term = ((p - a) ** 2).sum()
        total = term if total is None else total + term
    return None if total is None else l2sp_lambda * total


def train_one_epoch(
    model: NormalizedValueModel,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    loss_fn: nn.Module,
    device: torch.device,
    l2sp_lambda: float = 0.0,
    l2sp_anchor: dict | None = None,
) -> tuple[float, float]:
    """One training pass over `loader`. Returns (train_mse, train_mae)
    in NORMALIZED space (multiply mae by `target_std` for margin units).

    Per-batch flow: zero grads, forward, loss, backward, step. The MSE
    and MAE are tracked via running sums of squared/absolute errors, so
    we don't pay an extra pass for diagnostics. When `l2sp_lambda > 0`,
    the L2-SP anchor penalty is added to the data loss before backprop.
    """
    model.train()
    n = 0
    sum_sq = 0.0
    sum_abs = 0.0
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)

        optimizer.zero_grad()
        pred = model(x)                 # normalized scalar output
        loss = loss_fn(pred, y)
        penalty = _l2sp_penalty(model, l2sp_lambda, l2sp_anchor)
        if penalty is not None:
            loss = loss + penalty
        loss.backward()
        optimizer.step()

        with torch.no_grad():
            err = (pred - y).detach()
            sum_sq += (err * err).sum().item()
            sum_abs += err.abs().sum().item()
            n += x.size(0)

    return sum_sq / n, sum_abs / n


@torch.no_grad()
def evaluate(
    model: NormalizedValueModel,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, float]:
    """Run `model` over `loader` in eval mode, no_grad. Returns
    (mse, mae) in NORMALIZED space.

    Validation cadence is per-epoch; reused for the final test eval on
    the best checkpoint.
    """
    model.eval()
    n = 0
    sum_sq = 0.0
    sum_abs = 0.0
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        pred = model(x)
        err = pred - y
        sum_sq += (err * err).sum().item()
        sum_abs += err.abs().sum().item()
        n += x.size(0)
    return sum_sq / n, sum_abs / n


def train_one_epoch_batched(
    model, X, y, optimizer, loss_fn, device, batch_size, generator,
    l2sp_lambda: float = 0.0, l2sp_anchor: dict | None = None,
):
    """Batched-index training epoch — drop-in for `train_one_epoch` that
    bypasses the per-sample DataLoader (NN_TRAINING_SPEEDUP.md §3a).

    X: raw feature tensor (float16 or float32), shape (N, ENCODED_DIM).
    y: normalized target tensor (float32), shape (N,). Both may live on
    CPU or on `device`. One gather per batch (not one __getitem__ per
    row); accumulators stay on-device and sync once per epoch (not twice
    per batch — matters a lot on MPS). Returns (train_mse, train_mae) in
    NORMALIZED space, same as train_one_epoch.
    """
    model.train()
    n = X.shape[0]
    is_half = X.dtype == torch.float16
    perm = torch.randperm(n, generator=generator).to(X.device)
    sum_sq = torch.zeros((), device=device)
    sum_abs = torch.zeros((), device=device)
    for s in range(0, n, batch_size):
        idx = perm[s : s + batch_size]
        xb = X[idx]
        yb = y[idx]
        if is_half:
            xb = xb.float()                       # upcast the BATCH, not per row
        xb = xb.to(device, non_blocking=True)     # no-op if already on device
        yb = yb.to(device, non_blocking=True)
        optimizer.zero_grad()
        pred = model(xb)
        loss = loss_fn(pred, yb)
        penalty = _l2sp_penalty(model, l2sp_lambda, l2sp_anchor)
        if penalty is not None:
            loss = loss + penalty
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            err = pred.detach() - yb
            sum_sq += (err * err).sum()
            sum_abs += err.abs().sum()
    return (sum_sq / n).item(), (sum_abs / n).item()


@torch.no_grad()
def evaluate_batched(model, X, y, device, batch_size):
    """Batched-index eval — drop-in for `evaluate`. No shuffle (sequential
    slices). Returns (mse, mae) in NORMALIZED space."""
    model.eval()
    n = X.shape[0]
    is_half = X.dtype == torch.float16
    sum_sq = torch.zeros((), device=device)
    sum_abs = torch.zeros((), device=device)
    for s in range(0, n, batch_size):
        xb = X[s : s + batch_size]
        yb = y[s : s + batch_size]
        if is_half:
            xb = xb.float()
        xb = xb.to(device, non_blocking=True)
        yb = yb.to(device, non_blocking=True)
        pred = model(xb)
        err = pred - yb
        sum_sq += (err * err).sum()
        sum_abs += err.abs().sum()
    return (sum_sq / n).item(), (sum_abs / n).item()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def print_header() -> None:
    print(
        f"{'epoch':>5} | {'train_mse':>10} | {'train_mae(p)':>12} | "
        f"{'val_mse':>9} | {'val_mae(p)':>10} | best | pat | {'time(s)':>7}"
    )
    print("-" * 95)


def print_epoch_line(entry: dict) -> None:
    best_marker = " * " if entry["is_best"] else "   "
    print(
        f"{entry['epoch']:>5} | "
        f"{entry['train_mse']:>10.4f} | "
        f"{entry['train_mae_margin']:>12.2f} | "
        f"{entry['val_mse']:>9.4f} | "
        f"{entry['val_mae_margin']:>10.2f} | "
        f"{best_marker:^4} | "
        f"{entry['patience']:>3} | "
        f"{entry['time_s']:>7.1f}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Plots — matplotlib is optional; missing it just skips the plots
# ---------------------------------------------------------------------------


def save_curves_plot(log: list[dict], path: Path) -> bool:
    """Train/val loss curves (normalized MSE + MAE in margin units).
    Returns True if a file was written; False if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    epochs = [e["epoch"] for e in log]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(epochs, [e["train_mse"] for e in log], label="train")
    axes[0].plot(epochs, [e["val_mse"] for e in log], label="val")
    axes[0].set_xlabel("epoch")
    axes[0].set_ylabel("MSE (normalized)")
    axes[0].set_title("Loss curves (normalized)")
    axes[0].legend()
    axes[0].grid(alpha=0.3)
    axes[1].plot(epochs, [e["train_mae_margin"] for e in log], label="train")
    axes[1].plot(epochs, [e["val_mae_margin"] for e in log], label="val")
    axes[1].set_xlabel("epoch")
    axes[1].set_ylabel("MAE (margin points)")
    axes[1].set_title("Mean absolute error (margin units)")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return True


def save_calibration_plot(
    model: NormalizedValueModel,
    loader: DataLoader,
    target_std: float,
    device: torch.device,
    path: Path,
) -> bool:
    """Predicted vs. actual margin scatter on the val set. Identity line
    overlaid — a well-calibrated model lies close to the diagonal."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    model.eval()
    preds, targets = [], []
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device, non_blocking=True)
            pred_margin = model.predict_margin(x).cpu().numpy()
            target_margin = (y * target_std).numpy()
            preds.append(pred_margin)
            targets.append(target_margin)
    preds = np.concatenate(preds)
    targets = np.concatenate(targets)
    lim = float(max(abs(targets).max(), abs(preds).max()))
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(targets, preds, alpha=0.1, s=2)
    ax.plot([-lim, lim], [-lim, lim], "r--", label="identity")
    ax.set_xlabel("Actual margin (points)")
    ax.set_ylabel("Predicted margin (points)")
    ax.set_title("Calibration on val set")
    ax.set_aspect("equal")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# Main training entry point
# ---------------------------------------------------------------------------


def train(
    run_dirs,
    out_dir,
    *,
    hidden_dims=(256, 256),
    activation: str = "gelu",
    norm: str = "layer",
    dropout: float = 0.0,
    lr: float = 1e-3,
    weight_decay: float = 0.0,
    batch_size: int = 256,
    max_epochs: int = 50,
    early_stop_patience: int = 10,
    train_sample_size: int | None = None,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    sample_seed: int = 1,
    torch_seed: int = 42,
    device: str = "cpu",
    loss_type: str = "mse",
    target_mode: str = "margin",
    head: str | None = None,
    chunked: bool = False,
    train_keep_frac: float = 1.0,
    train_game_frac: float = 1.0,
    store_dtype: str = "float16",
    use_cache: bool = False,
    init_from: str | Path | None = None,
    l2sp: float = 0.0,
    save_all_epochs: bool = False,
    fast_loader: bool = False,
    data_on_device: bool = False,
    verbose: bool = True,
) -> tuple[list[dict], Path]:
    """Train a value-function NN. Returns `(epoch_log, best_checkpoint_path)`.

    All hyperparameters have safe defaults locked from FIRST_NN.md
    discussions. CLI wrappers (`scripts/nn/train_first.py`) just wire
    `argparse` to these kwargs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    setup_seeds(torch_seed)
    device_obj = torch.device(device)

    # Resolve the head + loss from target_mode (Experiment P2). The head can
    # be overridden explicitly; otherwise it's the natural pairing:
    #   margin  → linear head, MSE (or Huber) loss
    #   outcome → tanh head,   MSE loss
    #   winprob → sigmoid head, BCE loss
    _DEFAULT_HEAD = {"margin": "linear", "outcome": "tanh", "winprob": "sigmoid"}
    if target_mode not in _DEFAULT_HEAD:
        raise ValueError(
            f"Unknown target_mode {target_mode!r}; choose margin / outcome / winprob."
        )
    if head is None:
        head = _DEFAULT_HEAD[target_mode]
    # winprob requires the BCE loss regardless of loss_type; margin/outcome
    # use the requested regression loss.
    effective_loss = "bce" if target_mode == "winprob" else loss_type

    if verbose:
        print(f"Run dir: {out_dir}")
        print(f"Device: {device}")
        print(f"Target mode: {target_mode} | head: {head} | loss: {effective_loss}")
        print()

    # ----- Datasets -----

    if chunked or use_cache:  # the cache lives in the chunked builder
        # Low-memory path for large game collections (loads one pickle at a
        # time, accumulates float16 arrays). See build_datasets_chunked.
        train_ds, val_ds, test_ds, stats = build_datasets_chunked(
            run_dirs,
            train_frac=train_frac,
            val_frac=val_frac,
            split_seed=split_seed,
            sample_seed=sample_seed,
            target_mode=target_mode,
            train_keep_frac=train_keep_frac,
            train_game_frac=train_game_frac,
            store_dtype=store_dtype,
            use_cache=use_cache,
            verbose=verbose,
        )
    else:
        train_ds, val_ds, test_ds, stats = build_datasets(
            run_dirs,
            train_sample_size=train_sample_size,
            train_frac=train_frac,
            val_frac=val_frac,
            split_seed=split_seed,
            sample_seed=sample_seed,
            target_mode=target_mode,
            verbose=verbose,
        )
    stats.save(out_dir / "norm_stats.json")  # reference copy

    # ----- Model -----

    mlp = ConfigurableMLP(
        input_dim=ENCODED_DIM,
        hidden_dims=list(hidden_dims),
        output_dim=1,
        activation=activation,
        norm=norm,
        dropout=dropout,
        head=head,
    )
    model = NormalizedValueModel(mlp, stats).to(device_obj)
    if verbose:
        print(f"\nModel: {mlp.param_count():,} parameters")
        print(f"  arch: {hidden_dims} / {activation} / norm={norm} / dropout={dropout} / head={head}")

    # ----- Optional warm-start: initialize the net weights from a prior
    #       checkpoint (e.g. a killed run's best.pt) for faster convergence.
    #       Only the learnable net weights are copied; the freshly-fit
    #       NormStats buffers (input/target normalization) are kept — they
    #       are identical for identical data/split, and re-using the fresh
    #       fit avoids any drift. The AdamW optimizer state is NOT restored
    #       (re-warms in a few steps); early-stop preserves the best epoch.
    #       Shape-tolerant: only tensors whose name AND shape match are
    #       copied; any that don't (e.g. warm-starting a deeper architecture
    #       from a shallower checkpoint) are left at their fresh random init.
    #       This makes partial transfer across architectures possible, and
    #       degrades to a full warm-start when the architectures match.
    if init_from is not None:
        init_model = NormalizedValueModel.load(Path(init_from)).to(device_obj)
        src = init_model.net.state_dict()
        dst = model.net.state_dict()
        loaded, skipped = [], []
        for k, v in dst.items():
            if k in src and src[k].shape == v.shape:
                dst[k] = src[k]
                loaded.append(k)
            else:
                skipped.append(k)
        model.net.load_state_dict(dst)
        if verbose:
            print(f"  warm-start from {init_from}: loaded {len(loaded)} "
                  f"matching param tensors, kept {len(skipped)} at random init "
                  f"(arch/shape mismatch)")

    # ----- Optional L2-SP anchor: snapshot the (post-warm-start) net
    #       weights as the trust-region center. The penalty λ·‖θ−θ₀‖²
    #       (added in the epoch loop) pulls the fine-tune back toward the
    #       warm-start champion rather than toward 0 (as weight_decay does),
    #       limiting drift onto the narrow fine-tune distribution. Requires
    #       a warm-start to anchor to; harmless no-op otherwise.
    l2sp_anchor = None
    if l2sp and l2sp > 0.0:
        if init_from is None:
            raise ValueError("l2sp > 0 requires --init-from (no anchor to pull toward).")
        l2sp_anchor = {
            name: p.detach().clone()
            for name, p in model.net.named_parameters()
        }
        if verbose:
            print(f"  L2-SP anchor ON: λ={l2sp:g} over {len(l2sp_anchor)} "
                  f"param tensors (anchored to warm-start weights)")

    # ----- Run config (persisted for reproducibility) -----

    if isinstance(run_dirs, (str, Path)):
        run_dirs_list = [str(run_dirs)]
    else:
        run_dirs_list = [str(r) for r in run_dirs]
    config = {
        "hidden_dims": list(hidden_dims),
        "activation": activation,
        "norm": norm,
        "dropout": dropout,
        "lr": lr,
        "weight_decay": weight_decay,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "early_stop_patience": early_stop_patience,
        "train_sample_size": train_sample_size,
        "train_frac": train_frac,
        "val_frac": val_frac,
        "split_seed": split_seed,
        "sample_seed": sample_seed,
        "torch_seed": torch_seed,
        "device": device,
        "loss": effective_loss,
        "target_mode": target_mode,
        "head": head,
        "chunked": chunked or use_cache,
        "use_cache": use_cache,
        "train_keep_frac": train_keep_frac,
        "train_game_frac": train_game_frac,
        "init_from": str(init_from) if init_from is not None else None,
        "l2sp": l2sp,
        "save_all_epochs": save_all_epochs,
        "fast_loader": fast_loader,
        "data_on_device": data_on_device,
        "store_dtype": store_dtype if (chunked or use_cache) else "float32",
        "input_dim": ENCODED_DIM,
        "encoding_version": ENCODING_VERSION,
        "data_version": DATA_VERSION,
        "code_sha": current_git_sha(),
        "run_dirs": run_dirs_list,
        "train_size": len(train_ds),
        "val_size": len(val_ds),
        "test_size": len(test_ds),
        "param_count": mlp.param_count(),
        "target_std": stats.target_std,
    }
    with (out_dir / "config.json").open("w") as f:
        json.dump(config, f, indent=2)

    # ----- DataLoaders -----
    #
    # `generator` makes shuffle order reproducible per `torch_seed`. Each
    # epoch the train DataLoader does a fresh shuffle (good); val/test
    # are not shuffled.

    g = torch.Generator()
    g.manual_seed(torch_seed)
    train_loader = val_loader = test_loader = None
    if fast_loader:
        # Batched-index path (NN_TRAINING_SPEEDUP.md §3b): feed batches by
        # slicing the in-memory tensors directly. Optionally hold them
        # resident on `device` (fastest on MPS; watch RAM on 8 GB).
        Xtr, ytr = train_ds._X, train_ds._y
        Xva, yva = val_ds._X, val_ds._y
        Xte, yte = test_ds._X, test_ds._y
        if data_on_device:
            Xtr, ytr = Xtr.to(device_obj), ytr.to(device_obj)
            Xva, yva = Xva.to(device_obj), yva.to(device_obj)
            Xte, yte = Xte.to(device_obj), yte.to(device_obj)
        if verbose:
            print(f"  fast_loader ON (batched-index, bs={batch_size}, "
                  f"data_on_device={data_on_device})")
    else:
        train_loader = DataLoader(
            train_ds, batch_size=batch_size, shuffle=True,
            drop_last=False, generator=g,
        )
        val_loader = DataLoader(
            val_ds, batch_size=batch_size, shuffle=False, drop_last=False,
        )
        test_loader = DataLoader(
            test_ds, batch_size=batch_size, shuffle=False, drop_last=False,
        )

    # ----- Optimizer + Loss -----

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=lr, weight_decay=weight_decay,
    )
    if effective_loss == "mse":
        loss_fn: nn.Module = nn.MSELoss()
    elif effective_loss == "huber":
        loss_fn = nn.HuberLoss()
    elif effective_loss == "bce":
        # Sigmoid head outputs probabilities in (0,1); BCELoss is the
        # Bernoulli NLL against the {0,0.5,1} win/draw/loss targets.
        loss_fn = nn.BCELoss()
    else:
        raise ValueError(
            f"Unknown loss {effective_loss!r}; choose mse / huber / bce."
        )

    # ----- Training loop -----

    if verbose:
        print()
        print_header()

    target_std = stats.target_std
    log: list[dict] = []
    best_val_mse = float("inf")
    patience_counter = 0
    best_path = out_dir / "best"
    log_path = out_dir / "train_log.jsonl"
    log_path.write_text("")  # truncate any prior contents

    for epoch in range(1, max_epochs + 1):
        epoch_start = time.perf_counter()
        if fast_loader:
            train_mse, train_mae_norm = train_one_epoch_batched(
                model, Xtr, ytr, optimizer, loss_fn, device_obj, batch_size, g,
                l2sp_lambda=l2sp, l2sp_anchor=l2sp_anchor)
            val_mse, val_mae_norm = evaluate_batched(
                model, Xva, yva, device_obj, batch_size)
        else:
            train_mse, train_mae_norm = train_one_epoch(
                model, train_loader, optimizer, loss_fn, device_obj,
                l2sp_lambda=l2sp, l2sp_anchor=l2sp_anchor,
            )
            val_mse, val_mae_norm = evaluate(model, val_loader, device_obj)
        epoch_time = time.perf_counter() - epoch_start

        is_best = val_mse < best_val_mse
        if is_best:
            best_val_mse = val_mse
            model.save(
                best_path,
                extras={"epoch": epoch, "val_mse": val_mse, **config},
            )
            patience_counter = 0
        else:
            patience_counter += 1

        # Per-epoch checkpoints: val MSE is an unreliable strength ranker
        # for warm-start fine-tunes (FIRST_NN.md C16/C19 — MAE≠strength), so
        # we keep every epoch and select the strongest by head-to-head play
        # afterward rather than trusting best.pt.
        if save_all_epochs:
            model.save(
                out_dir / f"epoch_{epoch:03d}",
                extras={"epoch": epoch, "val_mse": val_mse, **config},
            )

        entry = {
            "epoch": epoch,
            "train_mse": train_mse,
            "train_mae_margin": train_mae_norm * target_std,
            "val_mse": val_mse,
            "val_mae_margin": val_mae_norm * target_std,
            "is_best": is_best,
            "patience": patience_counter,
            "time_s": epoch_time,
        }
        log.append(entry)
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        if verbose:
            print_epoch_line(entry)

        if patience_counter >= early_stop_patience:
            if verbose:
                print(
                    f"\nEarly stop at epoch {epoch}: "
                    f"no improvement for {early_stop_patience} epochs."
                )
            break

    # ----- Final eval on best checkpoint -----

    if best_path.with_suffix(".pt").exists():
        if verbose:
            print("\nLoading best checkpoint for test eval...")
        best_model = NormalizedValueModel.load(best_path).to(device_obj)
        if fast_loader:
            test_mse, test_mae_norm = evaluate_batched(
                best_model, Xte, yte, device_obj, batch_size)
        else:
            test_mse, test_mae_norm = evaluate(best_model, test_loader, device_obj)
        test_mae_margin = test_mae_norm * target_std
        best_epoch = max((e["epoch"] for e in log if e["is_best"]), default=None)

        # Measure the MCTS leaf-value scale (std of the leaf differential
        # V(s,0)-V(s,1)) on the val features, and patch it into the meta
        # sidecar so MCTS can normalize this head's leaf to unit scale
        # (FIRST_NN.md Experiment P2). val_ds._X is in paired layout.
        value_scale = measure_leaf_value_scale(
            best_model, val_ds._X.float().to(device_obj))
        best_model.value_scale = value_scale
        meta_path = best_path.with_suffix(".meta.json")
        with meta_path.open("r") as f:
            _meta = json.load(f)
        _meta["value_scale"] = value_scale
        with meta_path.open("w") as f:
            json.dump(_meta, f, indent=2)

        if verbose:
            print(f"  best epoch: {best_epoch}")
            print(f"  test MSE (normalized): {test_mse:.4f}")
            print(f"  test MAE (margin):     {test_mae_margin:.3f} points")
            print(f"  leaf value_scale (σ):  {value_scale:.4f}")
        with (out_dir / "test_metrics.json").open("w") as f:
            json.dump({
                "best_epoch": best_epoch,
                "best_val_mse": best_val_mse,
                "test_mse_normalized": test_mse,
                "test_mae_margin": test_mae_margin,
            }, f, indent=2)

        if save_curves_plot(log, out_dir / "train_curves.png"):
            if verbose:
                print(f"  saved: {out_dir / 'train_curves.png'}")
        # save_calibration_plot needs a DataLoader; on the fast path
        # val_loader is None, so build a throwaway one just for the plot.
        cal_loader = val_loader if val_loader is not None else DataLoader(
            val_ds, batch_size=batch_size, shuffle=False, drop_last=False,
        )
        if save_calibration_plot(
            best_model, cal_loader, target_std, device_obj,
            out_dir / "calibration.png",
        ):
            if verbose:
                print(f"  saved: {out_dir / 'calibration.png'}")

    return log, best_path
