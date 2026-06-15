"""Joint trainer for the shared-trunk value+policy model (Stage B).

Trains one `SharedTrunkModel` on value + every policy head together. The loop
**interleaves per-task batches** through the shared trunk: each step samples a
task (value / a fixed head / a pointer head), draws one batch from that task's
loader, and backprops its loss into the shared trunk + that head. The trunk thus
accumulates gradient from every task.

**Per-head gradient balancing** lives in the task-sampling weights, not a global
loss scalar. With raw dataset sizes the trunk would be shaped almost entirely by
value + placement (placement has ~hundreds× the rows of bake); sampling each head
*equally often* (regardless of its row count) gives the rare heads a real vote in
the trunk — the condition for the multi-task "better trunk" to actually
materialize. Value, the strength driver, gets a configurable larger share.

Reuses the soft-π losses already built: `_soft_ce` (fixed heads), the segment
log-softmax (pointer heads), and `pointer_collate`. Data + the encode cache come
from `build_shared_datasets`. Selection is on **value val MSE** (the most
reliable single signal; MAE≠strength, so `save_all_epochs` lets you pick the
final checkpoint by play); all per-head val CEs are logged.

Imports torch; the CLI wrapper is `scripts/nn/train_shared.py`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODER_V2, ENCODING_VERSION
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.policy_pointer_dataset import pointer_collate
from agricola.agents.nn.policy_pointer_model import segment_log_softmax
from agricola.agents.nn.policy_training import _soft_ce
from agricola.agents.nn.schema import DATA_VERSION
from agricola.agents.nn.shared_dataset import build_shared_datasets
from agricola.agents.nn.shared_model import SharedTrunkModel
from agricola.agents.nn.training import current_git_sha, make_run_id, setup_seeds


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------


def build_shared_trunk_model(sd, *, trunk_hidden_dims=(256, 256), embedding_dim=256,
                             value_head_dims=(), fixed_head_dims=(),
                             pointer_head_dims=(64,), activation="gelu",
                             norm="layer", dropout=0.0, embed_norm=True) -> SharedTrunkModel:
    """Construct a `SharedTrunkModel` from a `SharedDatasets` *or* `SharedStreams`
    bundle: head specs from the registries, the shared input norm + pointer
    candidate norms from the bundle. The full head roster is always built (heads
    with no rows still need their output layer for inference); the bundle only
    supplies the norms."""
    model = SharedTrunkModel(
        fixed_head_specs={n: HEADS[n].num_classes for n in HEADS},
        pointer_head_specs={n: POINTER_HEADS[n].candidate_dim for n in POINTER_HEADS},
        norm_stats=sd.input_stats,
        input_dim=int(sd.input_stats.input_mean.shape[0]),  # follows the dataset's encoder
        trunk_hidden_dims=list(trunk_hidden_dims),
        embedding_dim=embedding_dim, value_head_dims=list(value_head_dims),
        fixed_head_dims=list(fixed_head_dims), pointer_head_dims=list(pointer_head_dims),
        activation=activation, norm=norm, dropout=dropout, embed_norm=embed_norm,
    )
    for name, (mean, std) in sd.pointer_cand_norm.items():
        model.set_pointer_cand_norm(name, mean, std)
    return model


def _masked_logits(logits, mask):
    """illegal classes → −inf (all-illegal row treated as all-legal)."""
    if mask.dtype != torch.bool:
        mask = mask.bool()
    all_illegal = ~mask.any(dim=-1, keepdim=True)
    return logits.masked_fill(~(mask | all_illegal), float("-inf"))


# ---------------------------------------------------------------------------
# Per-task losses
# ---------------------------------------------------------------------------


def _value_loss(model, batch, device):
    x, y = batch
    x, y = x.to(device), y.to(device)
    pred = model.value_from_embedding(model.embed(x))
    return torch.nn.functional.mse_loss(pred, y)


def _fixed_loss(model, name, batch, device):
    x, pi, mask, weight = batch
    x, pi, mask, weight = x.to(device), pi.to(device), mask.to(device), weight.to(device)
    logits = _masked_logits(model.fixed_logits_from_embedding(model.embed(x), name), mask)
    logp = torch.log_softmax(logits, dim=-1)
    ce = _soft_ce(pi, logp)
    return (weight * ce).sum() / weight.sum().clamp_min(1e-8)


def _pointer_loss(model, name, batch, device):
    state, cand, seg, chosen_flat, weight, pi_flat = batch
    state, cand, seg = state.to(device), cand.to(device), seg.to(device)
    weight, pi_flat = weight.to(device), pi_flat.to(device)
    b = state.shape[0]
    emb = model.embed(state)                       # (B, E)
    scores = model.pointer_scores_from_embedding(name, emb[seg], cand)  # (M,)
    lp = segment_log_softmax(scores, seg, b)
    per_snap = -scores.new_zeros(b).index_add_(0, seg, pi_flat * lp)
    return (weight * per_snap).sum() / weight.sum().clamp_min(1e-8)


# ---------------------------------------------------------------------------
# Cyclic loader (infinite stream of batches per task)
# ---------------------------------------------------------------------------


class _Cyclic:
    def __init__(self, loader):
        self.loader = loader
        self._it = iter(loader)

    def next(self):
        try:
            return next(self._it)
        except StopIteration:
            self._it = iter(self.loader)
            return next(self._it)


class _CyclicTensor:
    """Batched-index sampler over aligned in-memory tensors — the fast path that
    skips the per-row `DataLoader` (the dominant overhead at scale; see
    NN_TRAINING_SPEEDUP.md). Cycles with a reshuffle each pass and upcasts
    `tensors[0]` from float16. `.next()` returns a tuple of sliced tensors in the
    same layout the DataLoader would (so the loss functions are unchanged). Used
    for the value + fixed tasks; the ragged pointer tasks keep their collate."""

    def __init__(self, tensors, batch_size, generator):
        self.tensors = tensors
        self.bs = batch_size
        self.gen = generator
        self.n = tensors[0].shape[0]
        self._perm = None
        self._pos = 0

    def next(self):
        if self._perm is None or self._pos >= self.n:
            self._perm = torch.randperm(self.n, generator=self.gen)
            self._pos = 0
        idx = self._perm[self._pos:self._pos + self.bs]
        self._pos += self.bs
        out = []
        for i, t in enumerate(self.tensors):
            b = t[idx]
            if i == 0 and b.dtype != torch.float32:  # X stored float16/int8 → upcast
                b = b.float()
            out.append(b)
        return tuple(out)


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------


@torch.no_grad()
def _eval_value(model, ds, device, bs):
    model.eval()
    n = len(ds)
    if n == 0:
        return {"mse": float("nan"), "mae_pts": float("nan")}
    se = ae = 0.0
    ts = float(model.target_std)
    for s in range(0, n, bs):
        x = ds._X[s:s + bs]
        x = (x.float() if ds._x_is_half else x).to(device)
        y = ds._y[s:s + bs].to(device)
        pred = model.value_from_embedding(model.embed(x))
        se += float(((pred - y) ** 2).sum())
        ae += float((pred - y).abs().sum() * ts)        # MAE in points
    return {"mse": se / n, "mae_pts": ae / n}


@torch.no_grad()
def _eval_fixed(model, name, ds, device, bs):
    model.eval()
    n = len(ds)
    if n == 0:
        return {"ce": float("nan"), "top1": float("nan")}
    ce = top1 = 0.0
    for s in range(0, n, bs):
        x = ds._X[s:s + bs]
        x = (x.float() if ds._x_is_half else x).to(device)
        pi = ds._pi[s:s + bs].to(device)
        mask = ds._mask[s:s + bs].to(device)
        tgt = ds._target[s:s + bs].to(device)
        logits = _masked_logits(model.fixed_logits_from_embedding(model.embed(x), name), mask)
        logp = torch.log_softmax(logits, dim=-1)
        ce += float(_soft_ce(pi, logp).sum())
        top1 += float((logits.argmax(-1) == tgt).sum())
    return {"ce": ce / n, "top1": top1 / n}


@torch.no_grad()
def _eval_pointer(model, name, ds, device, bs):
    model.eval()
    n = len(ds)
    if n == 0:
        return {"ce": float("nan")}
    ce = 0.0
    off = ds._off
    for s in range(0, n, bs):
        e = min(s + bs, n)
        b = e - s
        state = ds._state[s:e].to(device)
        cand = ds._cand[int(off[s]):int(off[e])].to(device)
        pi_flat = ds._pi[int(off[s]):int(off[e])].to(device)
        counts = (off[s + 1:e + 1] - off[s:e]).astype(np.int64)
        seg = torch.from_numpy(np.repeat(np.arange(b), counts)).to(device)
        emb = model.embed(state)
        scores = model.pointer_scores_from_embedding(name, emb[seg], cand)
        lp = segment_log_softmax(scores, seg, b)
        ce += float((-scores.new_zeros(b).index_add_(0, seg, pi_flat * lp)).sum())
    return {"ce": ce / n}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def train_shared(
    run_dirs, out_dir, *,
    # architecture (agnostic — pass the sweep winner's shape)
    trunk_hidden_dims=(256, 256), embedding_dim=256, value_head_dims=(),
    fixed_head_dims=(), pointer_head_dims=(64,), activation="gelu", norm="layer",
    dropout=0.0, embed_norm=True,
    # task balancing
    value_weight=None, head_weight=1.0,
    # optimization
    lr=1e-3, weight_decay=1e-4, batch_size=2048, max_epochs=40,
    early_stop_patience=8, steps_per_epoch=None, fast_loader=True,
    # data
    encoder=None, soft_targets=True, train_frac=0.8, val_frac=0.1, split_seed=0,
    store_dtype="float16", use_cache=True, encode_workers=1,
    stream=False, buffer_chunks=8, snapshot_keep=None,
    # misc
    init_from=None, save_all_epochs=False, torch_seed=42, device="cpu", verbose=True,
):
    """Train the joint shared-trunk model. Returns `(epoch_log, best_path)`.

    `value_weight` defaults to the number of policy heads, so value gets ~half
    the optimizer steps and the heads split the rest equally (the balancing).
    Selection is on value val MSE; `save_all_epochs` writes every epoch for
    play-based selection.

    `stream=True` trains directly off the on-disk per-pickle chunk npzs via
    `build_shared_streams` (bounded RAM ~2-3 GB regardless of corpus size — the
    117k-game OOM fix), with a ~`buffer_chunks`-chunk windowed-shuffle buffer per
    dense task. The default (`stream=False`) materializes the whole dataset in RAM
    (`build_shared_datasets`). The training loop body is identical either way."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_seeds(torch_seed)
    dev = torch.device(device)

    if verbose:
        print(f"Run dir: {out_dir}\nDevice: {device}\n")
    if encoder is None:
        encoder = ENCODER_V2
    if verbose:
        print(f"Encoder: {encoder.tag} (dim={encoder.dim}, "
              f"strip_begging={encoder.strip_begging})\n")
    # Two data backends, same training loop. `stream=True` trains directly off the
    # on-disk chunk npzs (bounded RAM ~2-3 GB regardless of corpus size — the 117k
    # OOM fix); the default in-RAM `build_shared_datasets` materializes everything.
    if stream:
        from agricola.agents.nn.shared_stream import build_shared_streams
        g_data = torch.Generator(); g_data.manual_seed(torch_seed)
        sd = build_shared_streams(
            run_dirs, encoder=encoder, batch_size=batch_size, buffer_chunks=buffer_chunks,
            train_frac=train_frac, val_frac=val_frac, split_seed=split_seed,
            soft_targets=soft_targets, use_cache=True, n_workers=encode_workers,
            generator=g_data, verbose=verbose)
    else:
        sd = build_shared_datasets(
            run_dirs, encoder=encoder, soft_targets=soft_targets, train_frac=train_frac,
            val_frac=val_frac, split_seed=split_seed, store_dtype=store_dtype,
            use_cache=use_cache, n_workers=encode_workers, snapshot_keep=snapshot_keep,
            verbose=verbose)

    model = build_shared_trunk_model(
        sd, trunk_hidden_dims=trunk_hidden_dims, embedding_dim=embedding_dim,
        value_head_dims=value_head_dims, fixed_head_dims=fixed_head_dims,
        pointer_head_dims=pointer_head_dims, activation=activation, norm=norm,
        dropout=dropout, embed_norm=embed_norm).to(dev)
    if verbose:
        print(f"Model: {model.param_count():,} params | trunk={list(trunk_hidden_dims)} "
              f"→ E={embedding_dim}")

    # Optional warm-start / resume from `init_from`. Two cases, dispatched on the
    # checkpoint's model_kind:
    #   * a SharedTrunkModel ("shared_trunk")  -> shape-tolerant transplant of
    #     every matching-shape tensor (trunk + value + all heads) EXCEPT the
    #     data-derived normalization (input mean/std, target_std, pointer cand
    #     norms), which must follow the NEW data. Transplanting target_std (the old
    #     behavior) trained the value head against the new target_std while
    #     predict_margin used the source's — a constant mis-scale (e.g. 7.73 vs
    #     5.57 = 1.39x) that inflated val-MAE and mis-calibrated the value head.
    #     When the source has the SAME dims this is a full resume (every weight
    #     matches; the norm is identical anyway) — the sleep-kill recovery path.
    #     When dims differ (e.g. warm-
    #     starting a 178-feature candidate from the 170-feature best joint model)
    #     only the input projection is a fresh layer; the whole deep trunk + heads
    #     transplant. The optimizer restarts either way (AdamW re-warms quickly).
    #   * anything else (a value net) -> trunk-only transplant (the original
    #     warm-start of a fresh joint model from the value-sweep winner).
    if init_from is not None:
        import json as _json
        from agricola.agents.nn.model import NormalizedValueModel
        meta = _json.loads(Path(init_from).with_suffix(".meta.json").read_text())
        if meta.get("model_kind") == "shared_trunk":
            resumed = SharedTrunkModel.load(Path(init_from))
            src = resumed.state_dict()
            dst = model.state_dict()

            def _is_norm(k):  # data-derived normalization — keep the NEW data's
                return (k in ("input_mean", "input_std", "target_std")
                        or k.startswith("cand_mean__") or k.startswith("cand_std__"))

            matched = [k for k in dst
                       if k in src and src[k].shape == dst[k].shape and not _is_norm(k)]
            fresh = [k for k in dst if k not in matched and not _is_norm(k)]
            dst.update({k: src[k] for k in matched})
            model.load_state_dict(dst)
            # value_scale follows the NEW data (re-measured post-train), not the
            # source's stale one; target_std buffer was kept from the new data.
            model.value_scale = float(model.target_std)
            if verbose:
                kind = "RESUMED full" if not fresh else "warm-started"
                print(f"  {kind} shared model from {init_from}: "
                      f"{len(matched)} tensors transplanted, norm kept from new data"
                      + (f", {len(fresh)} fresh ({fresh})" if fresh else ""))
        else:
            src = NormalizedValueModel.load(Path(init_from)).net.state_dict()
            dst = model.trunk.state_dict()
            loaded = sum(1 for k, v in dst.items()
                         if k in src and src[k].shape == v.shape)
            dst.update({k: src[k] for k, v in dst.items()
                        if k in src and src[k].shape == v.shape})
            model.trunk.load_state_dict(dst)
            if verbose:
                print(f"  warm-start trunk from {init_from}: {loaded} matching tensors")

    # ---- Tasks + cyclic loaders ----
    g = torch.Generator(); g.manual_seed(torch_seed)

    def _loader(ds, collate=None):
        return DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=False,
                          generator=g, collate_fn=collate)

    def _source(kind, ds):
        # Fast batched-index path for the dense value/fixed tasks; the ragged
        # pointer tasks keep their DataLoader + collate.
        if fast_loader and kind == "value":
            return _CyclicTensor((ds._X, ds._y), batch_size, g)
        if fast_loader and kind == "fixed":
            return _CyclicTensor((ds._X, ds._pi, ds._mask, ds._weight), batch_size, g)
        return _Cyclic(_loader(ds, pointer_collate if kind == "pointer" else None))

    tasks = []  # (name, kind, source, weight)
    if stream:
        # Streaming backend: value + fixed sources are `_TaskStream`s already (they
        # expose `.next()` in the exact loss-fn layout); pointer train rides the
        # materialized DataLoader path. Eval reads the materialized `sd.val[...]`.
        tasks.append(("value", "value", sd.value_stream, None))  # weight below
        for name, src in sd.fixed_streams.items():
            tasks.append((name, "fixed", src, head_weight))
        for name, ds in sd.pointer_train.items():
            if len(ds) > 0:
                tasks.append((name, "pointer", _source("pointer", ds), head_weight))
        n_value_train = sd.sizes["value"][0]
    else:
        tasks.append(("value", "value", _source("value", sd.value[0]), None))  # weight below
        for name, triple in sd.fixed.items():
            if len(triple[0]) > 0:
                tasks.append((name, "fixed", _source("fixed", triple[0]), head_weight))
        for name, triple in sd.pointer.items():
            if len(triple[0]) > 0:
                tasks.append((name, "pointer", _source("pointer", triple[0]), head_weight))
        n_value_train = len(sd.value[0])
    n_heads = sum(1 for _, k, _, _ in tasks if k != "value")
    vweight = float(value_weight) if value_weight is not None else float(max(1, n_heads))
    tasks = [(nm, k, ld, vweight if k == "value" else w) for nm, k, ld, w in tasks]
    weights = np.array([w for *_, w in tasks], dtype=np.float64)
    probs = weights / weights.sum()
    if steps_per_epoch is None:
        steps_per_epoch = max(1, n_value_train // batch_size)
    rng = np.random.default_rng(torch_seed)

    config = {
        "model_kind": "shared_trunk", "trunk_hidden_dims": list(trunk_hidden_dims),
        "embedding_dim": embedding_dim, "value_head_dims": list(value_head_dims),
        "fixed_head_dims": list(fixed_head_dims), "pointer_head_dims": list(pointer_head_dims),
        "activation": activation, "norm": norm, "dropout": dropout,
        "value_weight": vweight, "head_weight": head_weight, "lr": lr,
        "weight_decay": weight_decay, "batch_size": batch_size, "max_epochs": max_epochs,
        "steps_per_epoch": steps_per_epoch, "fast_loader": fast_loader,
        "soft_targets": soft_targets, "stream": stream,
        "buffer_chunks": buffer_chunks if stream else None,
        "split_seed": split_seed, "init_from": str(init_from) if init_from else None,
        "encoding_version": ENCODING_VERSION, "encoding_tag": encoder.tag,
        "strip_begging": encoder.strip_begging, "data_version": DATA_VERSION,
        "code_sha": current_git_sha(), "sizes": sd.sizes, "param_count": model.param_count(),
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2))

    # Val-dataset accessors — uniform across the in-RAM bundle (`sd.value[1]`,
    # `sd.fixed[n][1]`, `sd.pointer[n][1]`) and the streaming bundle (the
    # materialized `sd.val[...]` dict). Heads/pointers iterate the full roster.
    if stream:
        _val_value = sd.val["value"]
        def _val_fixed(n): return sd.val[f"fixed:{n}"]
        def _val_pointer(n): return sd.val[f"ptr:{n}"]
        _fixed_names = list(HEADS)
        _pointer_names = list(POINTER_HEADS)
    else:
        _val_value = sd.value[1]
        def _val_fixed(n): return sd.fixed[n][1]
        def _val_pointer(n): return sd.pointer[n][1]
        _fixed_names = list(sd.fixed)
        _pointer_names = list(sd.pointer)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    log, best_val, patience = [], float("inf"), 0
    best_path = out_dir / "best"
    log_path = out_dir / "train_log.jsonl"; log_path.write_text("")
    _header_printed = False  # per-epoch table: one header row, then numeric rows

    for epoch in range(1, max_epochs + 1):
        t0 = time.perf_counter()
        model.train()
        task_idx = rng.choice(len(tasks), size=steps_per_epoch, p=probs)
        for ti in task_idx:
            name, kind, loader, _ = tasks[ti]
            batch = loader.next()
            optimizer.zero_grad()
            if kind == "value":
                loss = _value_loss(model, batch, dev)
            elif kind == "fixed":
                loss = _fixed_loss(model, name, batch, dev)
            else:
                loss = _pointer_loss(model, name, batch, dev)
            loss.backward()
            optimizer.step()

        val_v = _eval_value(model, _val_value, dev, batch_size)
        fixed_ce = {n: _eval_fixed(model, n, _val_fixed(n), dev, batch_size)
                    for n in _fixed_names}
        ptr_ce = {n: _eval_pointer(model, n, _val_pointer(n), dev, batch_size)
                  for n in _pointer_names}
        dt = time.perf_counter() - t0

        is_best = val_v["mse"] < best_val
        if is_best:
            best_val = val_v["mse"]
            model.save(best_path, extras={"epoch": epoch, "val_mse": val_v["mse"], **config})
            patience = 0
        else:
            patience += 1
        if save_all_epochs:
            model.save(out_dir / f"epoch_{epoch:03d}",
                       extras={"epoch": epoch, "val_mse": val_v["mse"]})

        entry = {"epoch": epoch, "val_mse": val_v["mse"], "val_mae_pts": val_v["mae_pts"],
                 "fixed_val_ce": {n: fixed_ce[n]["ce"] for n in fixed_ce},
                 "fixed_val_top1": {n: fixed_ce[n]["top1"] for n in fixed_ce},
                 "pointer_val_ce": {n: ptr_ce[n]["ce"] for n in ptr_ce},
                 "is_best": is_best, "patience": patience, "time_s": dt}
        log.append(entry)
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        if verbose:
            _short = {"build_stop": "bstop", "choose_subaction": "chsub",
                      "commit_bake": "bake", "commit_build_major": "major",
                      "commit_sow": "sow", "fencing": "fence", "placement": "place",
                      "animal_frontier": "animal", "harvest_feed": "feed"}
            # One aligned table: a single header row, then numeric rows. Head
            # columns are the per-head val CEs, in fixed-then-pointer order.
            head_labels = ([_short.get(n, n[:6]) for n in fixed_ce]
                           + [_short.get(n, n[:6]) for n in ptr_ce])
            head_vals = ([fixed_ce[n]["ce"] for n in fixed_ce]
                         + [ptr_ce[n]["ce"] for n in ptr_ce])
            if not _header_printed:
                hdr = (f"{'ep':>3} {'val_mae':>8} {'val_mse':>8} {'b':>1} "
                       + " ".join(f"{lab:>6}" for lab in head_labels)
                       + f" {'sec':>5}")
                print(hdr, flush=True)
                print("-" * len(hdr), flush=True)
                _header_printed = True
            row = (f"{epoch:>3} {val_v['mae_pts']:>8.2f} {val_v['mse']:>8.4f} "
                   f"{'*' if is_best else ' ':>1} "
                   + " ".join(f"{v:>6.2f}" for v in head_vals)
                   + f" {dt:>5.0f}")
            print(row, flush=True)
        if patience >= early_stop_patience:
            if verbose:
                print(f"Early stop at epoch {epoch}.")
            break

    # value_scale for MCTS, measured on paired val rows (consecutive perspectives).
    if best_path.with_suffix(".pt").exists():
        from agricola.agents.nn.shared_model import SharedTrunkModel as _S
        best = _S.load(best_path).to(dev)
        vds = _val_value
        # Batched forward — a single `predict_margin` over the whole val set
        # (2.5M rows at 117k games) allocates a float32 copy of `_X` + the trunk
        # activations all at once (~4+ GB), overflowing the 8 GB box. Stream it.
        n = vds._X.shape[0]
        with torch.no_grad():
            parts = []
            for s in range(0, n, batch_size):
                xb = vds._X[s:s + batch_size]
                xb = (xb.float() if vds._x_is_half else xb).to(dev)
                parts.append(best.predict_margin(xb))
            m = torch.cat(parts) if parts else torch.zeros(0)
        diff = (m[0::2] - m[1::2]) / 2.0
        scale = float(diff.std()) if diff.shape[0] >= 2 else 1.0
        best.value_scale = scale if scale > 1e-9 else 1.0
        best.save(best_path, extras={"value_scale": best.value_scale, **config})
        if verbose:
            print(f"value_scale={best.value_scale:.3f}")
    return log, best_path
