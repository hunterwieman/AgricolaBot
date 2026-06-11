"""Training library for the pointer (score-the-legal-set) policy heads (POLICY_HEAD.md §11).

`train_pointer(run_dirs, out_dir, ...)` mirrors `train_policy` but over the ragged
frontier examples: build datasets → fit input-norm → (optional warm-start) → AdamW
+ early-stop on **val segment cross-entropy** → best checkpoint + per-epoch log +
curves + metadata.

Differs from the fixed-head `train_policy`:
- Loss is **weighted segment-CE**: the per-candidate scorer runs over the flat
  `(ΣK, ·)` batch, `segment_log_softmax` normalizes per snapshot, and the loss is
  `−Σ wᵢ·log p(chosenᵢ) / Σ wᵢ`.
- Metrics are **top-1 / top-3 within each frontier** (the chosen commit's rank
  among its own candidates), overall + winners-subset.
- The model is `NormalizedPointerModel` (input `[state ; candidate_delta]`).

Reuses `training.setup_seeds / current_git_sha`. Imports torch; the CLI wrapper is
`scripts/nn/train_policy_pointer.py`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import ConfigurableMLP, NormalizedValueModel
from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD, PointerHead
from agricola.agents.nn.policy_pointer_dataset import (
    DEFAULT_VALUE_CKPT,
    build_pointer_datasets,
    pointer_collate,
)
from agricola.agents.nn.policy_pointer_model import (
    NormalizedPointerModel,
    segment_log_softmax,
)
from agricola.agents.nn.schema import DATA_VERSION
from agricola.agents.nn.training import current_git_sha, setup_seeds


# ---------------------------------------------------------------------------
# Train / eval primitives
# ---------------------------------------------------------------------------


def _load_init_net_state(path: Path) -> dict:
    """Inner-net state_dict from a warm-start checkpoint (value / policy /
    pointer), for the shape-tolerant trunk transplant. Note the pointer net's
    first Linear (input `ENCODED_DIM + candidate_dim`) won't shape-match a value
    net's (`ENCODED_DIM`), so only the deeper trunk layers transplant."""
    meta = json.loads(path.with_suffix(".meta.json").read_text())
    kind = str(meta.get("model_kind", ""))
    if kind == "policy_pointer":
        return NormalizedPointerModel.load(path).net.state_dict()
    if kind.startswith("policy"):
        from agricola.agents.nn.policy_model import NormalizedPolicyModel
        return NormalizedPolicyModel.load(path).net.state_dict()
    return NormalizedValueModel.load(path).net.state_dict()


def _segment_ce_soft(model, state, cand, seg, pi_flat, b):
    """Per-snapshot CE-against-π `(B,)` and the raw `scores (M,)` (reused for
    top-k). `pi_flat (M,)` is the per-candidate target prob (segment-normalized);
    the per-snapshot loss is `−Σ_c π_c·log p_c`. Reduces to ordinary one-hot
    segment CE when `pi_flat` is one-hot per segment."""
    scores = model.score_flat(state, cand, seg)
    lp = segment_log_softmax(scores, seg, b)         # (M,)
    per_cand = pi_flat * lp                          # all candidates legal → lp finite
    ce = -scores.new_zeros(b).index_add_(0, seg, per_cand)
    return ce, scores


def train_one_epoch_pointer(model, loader, optimizer, device) -> float:
    """One weighted segment-CE-against-π pass. Returns the weight-normalized train CE."""
    model.train()
    ce_sum = w_sum = 0.0
    for state, cand, seg, chosen_flat, weight, pi_flat in loader:
        state, cand, seg = state.to(device), cand.to(device), seg.to(device)
        weight, pi_flat = weight.to(device), pi_flat.to(device)
        optimizer.zero_grad()
        ce, _ = _segment_ce_soft(model, state, cand, seg, pi_flat, state.shape[0])
        loss = (weight * ce).sum() / weight.sum().clamp_min(1e-8)
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            ce_sum += (weight * ce).sum().item()
            w_sum += weight.sum().item()
    return ce_sum / max(w_sum, 1e-8)


@torch.no_grad()
def evaluate_pointer(model, ds, device, batch_size: int) -> dict:
    """Unweighted segment-CE-against-π (the selection metric) + within-frontier
    top-1/top-3 agreement with the played candidate over `ds`, overall and on the
    winners' subset (`won == 1`). A candidate is top-k iff fewer than k of its
    frontier-mates score strictly higher (lenient on ties)."""
    model.eval()
    n = len(ds)
    off, pos, won = ds._off, ds._pos, ds._won
    ce_sum = 0.0
    top1 = top3 = 0
    top1_w = top3_w = n_w = 0
    for s in range(0, n, batch_size):
        e = min(s + batch_size, n)
        b = e - s
        state = ds._state[s:e].to(device)
        cand = ds._cand[int(off[s]):int(off[e])].to(device)
        pi_flat = ds._pi[int(off[s]):int(off[e])].to(device)
        counts = (off[s + 1:e + 1] - off[s:e]).astype(np.int64)
        seg = torch.from_numpy(np.repeat(np.arange(b), counts)).to(device)
        local_off = np.concatenate([[0], np.cumsum(counts)])
        chosen_flat = torch.from_numpy(
            (local_off[:b] + pos[s:e]).astype(np.int64)).to(device)

        ce, scores = _segment_ce_soft(model, state, cand, seg, pi_flat, b)
        ce_sum += ce.sum().item()
        # within-frontier rank of the chosen candidate
        gt = (scores > scores[chosen_flat][seg]).float()
        rank = torch.zeros(b, device=device).index_add_(0, seg, gt)
        t1, t3 = (rank == 0), (rank < 3)
        top1 += int(t1.sum().item())
        top3 += int(t3.sum().item())
        wb = (won[s:e] == 1.0).to(device)
        if wb.any():
            n_w += int(wb.sum().item())
            top1_w += int((t1 & wb).sum().item())
            top3_w += int((t3 & wb).sum().item())
    return {
        "ce": ce_sum / max(n, 1),
        "top1": top1 / max(n, 1), "top3": top3 / max(n, 1),
        "top1_win": top1_w / max(n_w, 1), "top3_win": top3_w / max(n_w, 1),
        "n": n, "n_win": n_w,
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
    axes[0].set_xlabel("epoch"); axes[0].set_ylabel("segment cross-entropy")
    axes[0].set_title("Loss curves"); axes[0].legend(); axes[0].grid(alpha=0.3)
    axes[1].plot(epochs, [e["val_top1"] for e in log], label="val top-1")
    axes[1].plot(epochs, [e["val_top3"] for e in log], label="val top-3")
    axes[1].set_xlabel("epoch"); axes[1].set_ylabel("accuracy")
    axes[1].set_title("Frontier agreement"); axes[1].legend(); axes[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=100); plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def train_pointer(
    run_dirs,
    out_dir,
    *,
    head: PointerHead = ANIMAL_FRONTIER_HEAD,
    loss_weight: str = "unweighted",
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
    soft_targets: bool = True,
    verbose: bool = True,
) -> tuple[list[dict], Path]:
    """Train a pointer-head NN. Returns `(epoch_log, best_checkpoint_path)`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_seeds(torch_seed)
    device_obj = torch.device(device)

    if verbose:
        print(f"Run dir: {out_dir}\nDevice: {device}\nHead: {head.name}\n"
              f"Loss weight: {loss_weight}\n")

    # ----- Datasets -----
    train_ds, val_ds, test_ds, stats, info = build_pointer_datasets(
        run_dirs, head=head, loss_weight=loss_weight, value_ckpt=value_ckpt,
        awr_clip=awr_clip, train_frac=train_frac, val_frac=val_frac,
        split_seed=split_seed, soft_targets=soft_targets, verbose=verbose,
    )
    stats.save(out_dir / "pointer_norm_stats.json")

    # ----- Model -----
    input_dim = ENCODED_DIM + head.candidate_dim
    mlp = ConfigurableMLP(
        input_dim=input_dim, hidden_dims=list(hidden_dims), output_dim=1,
        activation=activation, norm=norm, dropout=dropout, head="linear",
    )
    model = NormalizedPointerModel(mlp, stats).to(device_obj)
    model.head_name = head.name
    if verbose:
        print(f"\nModel: {mlp.param_count():,} parameters | head={head.name} "
              f"(scorer over {input_dim}-d [state;cand])")

    # ----- Optional warm-start (deeper trunk layers only; layer-0 width differs) -----
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
                  f"tensors, kept {skipped} fresh")

    # ----- Run config -----
    run_dirs_list = ([str(run_dirs)] if isinstance(run_dirs, (str, Path))
                     else [str(r) for r in run_dirs])
    config = {
        "model_kind": "policy_pointer",
        "head": head.name,
        "candidate_dim": head.candidate_dim,
        "soft_targets": soft_targets,
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
        "input_dim": input_dim, "encoding_version": ENCODING_VERSION,
        "data_version": DATA_VERSION, "code_sha": current_git_sha(),
        "run_dirs": run_dirs_list, "train_size": info["n_train"],
        "val_size": info["n_val"], "test_size": info["n_test"],
        "train_candidates": info.get("candidates_train"),
        "param_count": mlp.param_count(),
    }
    with (out_dir / "config.json").open("w") as f:
        json.dump(config, f, indent=2)

    # ----- Loaders / optimizer -----
    g = torch.Generator(); g.manual_seed(torch_seed)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              drop_last=False, generator=g, collate_fn=pointer_collate)
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
        train_ce = train_one_epoch_pointer(model, train_loader, optimizer, device_obj)
        val = evaluate_pointer(model, val_ds, device_obj, batch_size)
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
                print(f"\nEarly stop at epoch {epoch}.")
            break

    # ----- Final test eval on the best checkpoint -----
    if best_path.with_suffix(".pt").exists():
        best_model = NormalizedPointerModel.load(best_path).to(device_obj)
        test = evaluate_pointer(best_model, test_ds, device_obj, batch_size)
        best_epoch = max((e["epoch"] for e in log if e["is_best"]), default=None)
        if verbose:
            print(f"\nbest epoch: {best_epoch}")
            print(f"  test CE:    {test['ce']:.4f}")
            print(f"  test top-1: {test['top1']:.3f}  (winners {test['top1_win']:.3f})")
            print(f"  test top-3: {test['top3']:.3f}  (winners {test['top3_win']:.3f})")
        with (out_dir / "test_metrics.json").open("w") as f:
            json.dump({"best_epoch": best_epoch, "best_val_ce": best_val_ce,
                       "test": test, "loss_weight": loss_weight,
                       "awr_beta": info.get("awr_beta")}, f, indent=2)
        if _save_curves(log, out_dir / "train_curves.png") and verbose:
            print(f"  saved: {out_dir / 'train_curves.png'}")

    return log, best_path
