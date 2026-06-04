"""Training library for the placement-policy network (POLICY_HEAD.md §8).

`train_policy(run_dirs, out_dir, ...)` runs the full cycle: build datasets →
fit input-norm → (optional warm-start trunk transplant) → AdamW + early-stop
on **val cross-entropy** → best checkpoint + per-epoch log + curves + metadata.

Differs from the value `training.train` in three ways:
- Loss is **weighted, legal-masked cross-entropy** (the `awr` weights come
  from the dataset; `none` weights are all 1).
- Metrics are **top-1 / top-3** placement agreement (overall + winners-subset),
  not MSE/MAE; selection is on val CE.
- The model is `NormalizedPolicyModel` (25-way head, no target normalization).

Reuses `training.setup_seeds / make_run_id / current_git_sha`. Imports torch;
the CLI wrapper is `scripts/nn/train_policy.py`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import ConfigurableMLP, NormalizedValueModel
from agricola.agents.nn.policy_dataset import (
    DEFAULT_VALUE_CKPT,
    AgricolaPolicyDataset,
    build_policy_datasets,
)
from agricola.agents.nn.policy_heads import PLACEMENT_HEAD, DecisionHead
from agricola.agents.nn.policy_model import NormalizedPolicyModel
from agricola.agents.nn.schema import DATA_VERSION
from agricola.agents.nn.training import current_git_sha, make_run_id, setup_seeds


# ---------------------------------------------------------------------------
# Train / eval primitives
# ---------------------------------------------------------------------------


def _load_init_net_state(path: Path) -> dict:
    """Inner-net state_dict from a warm-start checkpoint — accepts either a
    value (`NormalizedValueModel`) or policy (`NormalizedPolicyModel`)
    checkpoint, dispatched on the meta sidecar's `model_kind`. Only the trunk
    tensors are reused downstream (the final head layer won't shape-match)."""
    meta = json.loads(path.with_suffix(".meta.json").read_text())
    if str(meta.get("model_kind", "")).startswith("policy"):
        from agricola.agents.nn.policy_model import NormalizedPolicyModel
        return NormalizedPolicyModel.load(path).net.state_dict()
    return NormalizedValueModel.load(path).net.state_dict()


def train_one_epoch_policy(model, loader, optimizer, device) -> float:
    """One weighted-masked-CE pass. Returns the (weight-normalized) train CE."""
    model.train()
    ce_sum = 0.0
    w_sum = 0.0
    for x, target, mask, weight in loader:
        x = x.to(device)
        target = target.to(device)
        mask = mask.to(device)
        weight = weight.to(device)
        optimizer.zero_grad()
        logits = model.predict_logits(x, mask)          # illegal → −inf
        ce = F.cross_entropy(logits, target, reduction="none")
        loss = (weight * ce).sum() / weight.sum().clamp_min(1e-8)
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            ce_sum += (weight * ce).sum().item()
            w_sum += weight.sum().item()
    return ce_sum / max(w_sum, 1e-8)


@torch.no_grad()
def evaluate_policy(model, ds: AgricolaPolicyDataset, device, batch_size: int) -> dict:
    """Unweighted CE + top-1/top-3 over `ds`, overall and on the winners'
    subset (`won == 1`). Operates on the dataset tensors directly."""
    model.eval()
    n = len(ds)
    X, target, mask, won = ds._X, ds._target, ds._mask, ds._won
    is_half = ds._x_is_half
    ce_sum = 0.0
    top1 = top3 = 0
    top1_w = top3_w = n_w = 0
    for s in range(0, n, batch_size):
        e = s + batch_size
        xb = X[s:e]
        if is_half:
            xb = xb.float()
        xb = xb.to(device)
        tb = target[s:e].to(device)
        mb = mask[s:e].to(device)
        wonb = won[s:e]
        logits = model.predict_logits(xb, mb)
        ce_sum += F.cross_entropy(logits, tb, reduction="sum").item()
        top1_b = logits.argmax(dim=-1) == tb
        k = min(3, logits.shape[-1])
        top3_idx = logits.topk(k, dim=-1).indices
        top3_b = (top3_idx == tb.unsqueeze(-1)).any(dim=-1)
        top1 += int(top1_b.sum().item())
        top3 += int(top3_b.sum().item())
        win_mask = (wonb == 1.0)
        if win_mask.any():
            wm = win_mask.to(device)
            n_w += int(win_mask.sum().item())
            top1_w += int((top1_b & wm).sum().item())
            top3_w += int((top3_b & wm).sum().item())
    return {
        "ce": ce_sum / max(n, 1),
        "top1": top1 / max(n, 1),
        "top3": top3 / max(n, 1),
        "top1_win": top1_w / max(n_w, 1),
        "top3_win": top3_w / max(n_w, 1),
        "n": n,
        "n_win": n_w,
    }


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _print_header() -> None:
    print(f"{'epoch':>5} | {'train_ce':>9} | {'val_ce':>9} | {'val_top1':>9} | "
          f"{'val_top3':>9} | best | pat | {'time(s)':>7}")
    print("-" * 78)


def _print_epoch(e: dict) -> None:
    best = " * " if e["is_best"] else "   "
    print(f"{e['epoch']:>5} | {e['train_ce']:>9.4f} | {e['val_ce']:>9.4f} | "
          f"{e['val_top1']:>9.3f} | {e['val_top3']:>9.3f} | {best:^4} | "
          f"{e['patience']:>3} | {e['time_s']:>7.1f}", flush=True)


def _save_curves(log: list[dict], path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    epochs = [e["epoch"] for e in log]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(epochs, [e["train_ce"] for e in log], label="train")
    axes[0].plot(epochs, [e["val_ce"] for e in log], label="val")
    axes[0].set_xlabel("epoch"); axes[0].set_ylabel("cross-entropy")
    axes[0].set_title("Loss curves"); axes[0].legend(); axes[0].grid(alpha=0.3)
    axes[1].plot(epochs, [e["val_top1"] for e in log], label="val top-1")
    axes[1].plot(epochs, [e["val_top3"] for e in log], label="val top-3")
    axes[1].set_xlabel("epoch"); axes[1].set_ylabel("accuracy")
    axes[1].set_title("Placement agreement"); axes[1].legend(); axes[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=100); plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def train_policy(
    run_dirs,
    out_dir,
    *,
    head: DecisionHead = PLACEMENT_HEAD,
    loss_weight: str = "none",
    value_ckpt: str | Path = DEFAULT_VALUE_CKPT,
    awr_clip: float = 6.0,
    hidden_dims=(256, 256),
    activation: str = "gelu",
    norm: str = "layer",
    dropout: float = 0.2,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    batch_size: int = 256,
    max_epochs: int = 50,
    early_stop_patience: int = 10,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    torch_seed: int = 42,
    device: str = "cpu",
    init_from: str | Path | None = None,
    store_dtype: str = "float16",
    verbose: bool = True,
) -> tuple[list[dict], Path]:
    """Train a placement-policy NN. Returns `(epoch_log, best_checkpoint_path)`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_seeds(torch_seed)
    device_obj = torch.device(device)

    if verbose:
        print(f"Run dir: {out_dir}\nDevice: {device}\nLoss weight: {loss_weight}\n")

    # ----- Datasets -----
    train_ds, val_ds, test_ds, stats, info = build_policy_datasets(
        run_dirs, head=head, loss_weight=loss_weight, value_ckpt=value_ckpt,
        awr_clip=awr_clip, train_frac=train_frac, val_frac=val_frac,
        split_seed=split_seed, store_dtype=store_dtype, verbose=verbose,
    )
    stats.save(out_dir / "policy_norm_stats.json")

    # ----- Model -----
    mlp = ConfigurableMLP(
        input_dim=ENCODED_DIM, hidden_dims=list(hidden_dims),
        output_dim=head.num_classes,
        activation=activation, norm=norm, dropout=dropout, head="linear",
    )
    model = NormalizedPolicyModel(mlp, stats).to(device_obj)
    model.head_name = head.name
    if verbose:
        print(f"\nModel: {mlp.param_count():,} parameters | "
              f"head={head.name} ({head.num_classes}-way)")

    # ----- Optional warm-start: transplant matching net tensors from a value
    #       checkpoint (the [256,256] trunk matches; the 256→25 head doesn't,
    #       so it stays fresh). Mirrors training.train's shape-tolerant copy. -----
    if init_from is not None:
        src = _load_init_net_state(Path(init_from))
        dst = model.net.state_dict()
        loaded = skipped = 0
        for k, v in dst.items():
            if k in src and src[k].shape == v.shape:
                dst[k] = src[k]; loaded += 1
            else:
                skipped += 1
        model.net.load_state_dict(dst)
        if verbose:
            print(f"  warm-start from {init_from}: loaded {loaded} matching "
                  f"tensors, kept {skipped} fresh (head/shape mismatch)")

    # ----- Run config -----
    run_dirs_list = ([str(run_dirs)] if isinstance(run_dirs, (str, Path))
                     else [str(r) for r in run_dirs])
    config = {
        "model_kind": "policy",
        "head": head.name,
        "num_classes": head.num_classes,
        "loss_weight": loss_weight,
        "awr_beta": info.get("awr_beta"),
        "awr_clip": awr_clip if loss_weight == "awr" else None,
        "value_ckpt": str(value_ckpt) if loss_weight == "awr" else None,
        "hidden_dims": list(hidden_dims), "activation": activation, "norm": norm,
        "dropout": dropout, "lr": lr, "weight_decay": weight_decay,
        "batch_size": batch_size, "max_epochs": max_epochs,
        "early_stop_patience": early_stop_patience, "train_frac": train_frac,
        "val_frac": val_frac, "split_seed": split_seed, "torch_seed": torch_seed,
        "device": device, "init_from": str(init_from) if init_from else None,
        "store_dtype": store_dtype, "input_dim": ENCODED_DIM,
        "encoding_version": ENCODING_VERSION, "data_version": DATA_VERSION,
        "code_sha": current_git_sha(), "run_dirs": run_dirs_list,
        "train_size": info["n_train"], "val_size": info["n_val"],
        "test_size": info["n_test"], "param_count": mlp.param_count(),
    }
    with (out_dir / "config.json").open("w") as f:
        json.dump(config, f, indent=2)

    # ----- Loaders / optimizer -----
    g = torch.Generator(); g.manual_seed(torch_seed)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              drop_last=False, generator=g)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    # ----- Training loop -----
    if verbose:
        print(); _print_header()
    log: list[dict] = []
    best_val_ce = float("inf")
    patience = 0
    best_path = out_dir / "best"
    log_path = out_dir / "train_log.jsonl"
    log_path.write_text("")

    for epoch in range(1, max_epochs + 1):
        t0 = time.perf_counter()
        train_ce = train_one_epoch_policy(model, train_loader, optimizer, device_obj)
        val = evaluate_policy(model, val_ds, device_obj, batch_size)
        dt = time.perf_counter() - t0

        is_best = val["ce"] < best_val_ce
        if is_best:
            best_val_ce = val["ce"]
            model.save(best_path, extras={"epoch": epoch, "val_ce": val["ce"], **config})
            patience = 0
        else:
            patience += 1

        entry = {
            "epoch": epoch, "train_ce": train_ce, "val_ce": val["ce"],
            "val_top1": val["top1"], "val_top3": val["top3"],
            "val_top1_win": val["top1_win"], "val_top3_win": val["top3_win"],
            "is_best": is_best, "patience": patience, "time_s": dt,
        }
        log.append(entry)
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        if verbose:
            _print_epoch(entry)
        if patience >= early_stop_patience:
            if verbose:
                print(f"\nEarly stop at epoch {epoch}: no val-CE improvement "
                      f"for {early_stop_patience} epochs.")
            break

    # ----- Final test eval on the best checkpoint -----
    if best_path.with_suffix(".pt").exists():
        best_model = NormalizedPolicyModel.load(best_path).to(device_obj)
        test = evaluate_policy(best_model, test_ds, device_obj, batch_size)
        best_epoch = max((e["epoch"] for e in log if e["is_best"]), default=None)
        if verbose:
            print(f"\nbest epoch: {best_epoch}")
            print(f"  test CE:        {test['ce']:.4f}")
            print(f"  test top-1:     {test['top1']:.3f}  (winners {test['top1_win']:.3f})")
            print(f"  test top-3:     {test['top3']:.3f}  (winners {test['top3_win']:.3f})")
        with (out_dir / "test_metrics.json").open("w") as f:
            json.dump({"best_epoch": best_epoch, "best_val_ce": best_val_ce,
                       "test": test, "loss_weight": loss_weight,
                       "awr_beta": info.get("awr_beta")}, f, indent=2)
        if _save_curves(log, out_dir / "train_curves.png") and verbose:
            print(f"  saved: {out_dir / 'train_curves.png'}")

    return log, best_path
