# NN training speedup — handoff notes

> **Purpose.** This is a handoff doc from a parallel session that investigated why
> NN value-function training feels slow on the M1 (8 GB) and what to change. It exists so
> a session actively running training is **not surprised by code changes mid-stream**.
>
> **The single most important thing to know:** every change proposed here is **opt-in and
> flag-gated**. With no new flags, `train()` and `scripts/nn/train_first.py` behave **exactly as
> they do today** — same loop, same determinism, same numbers. Nothing about your in-flight runs
> changes unless you pass the new flags. So you can land these edits without disrupting a run.
>
> **Hardware context:** Apple M1, 8 GB RAM, fanless (thermal-throttles under sustained load).
> PyTorch `2.1.0.dev` nightly; `torch.backends.mps.is_available() == True`; `cpu_count == 8`;
> `torch.get_num_threads() == 8`.

> **Implementation status (2026-06-02):** Changes **A (batched-index) and B (large batch) are
> implemented** behind `--fast-loader` / `--data-on-device` (with `train_one_epoch_batched` /
> `evaluate_batched` in `training.py`); defaults unchanged, 41 NN tests green. **Validation is
> partial:** on CPU, `--fast-loader` at `bs=512` reproduced the default-path val/test MAE within
> noise (6.402 vs 6.471 — correctness of change **A** confirmed). The **bs=8192 LR sweep (change B)
> was interrupted before completing**, so the quality-preserving LR is *not yet established* — do
> **not** trust a bs=8192 model until that sweep finishes (see §6.1, §7). Change **C (MPS)** is not
> yet implemented/tested. NB: real-machine *timing* comparisons here are unreliable (the validation
> ran under user CPU contention + thermal throttling) — quality (MAE) is load-independent and is the
> validated part.

---

## TL;DR

1. Training is **throughput/overhead-bound, not compute-bound.** The model is tiny (~210K params,
   `[256,256,256,128]`). At `batch_size=256` over ~6M training examples you run **~23,600
   optimizer steps/epoch**, and most of the ~130–225 s/epoch is overhead that scales with the
   *number of steps* — per-step framework cost (`zero_grad` / autograd / `optimizer.step`), plus a
   secondary per-row `DataLoader` `__getitem__`/upcast cost and per-batch `.item()` syncs — **not**
   matrix math. (Breakdown in §1.)
2. Three composable changes, biggest lever last:
   - **(A) Batched indexing** — feed batches by slicing the in-memory tensors directly instead of
     the per-sample `DataLoader`. Removes the ~6M `__getitem__`/upcast calls per epoch — only ~13%
     on its own, but it's the *enabler* for (B) large batches and (C) MPS-resident data.
   - **(B) Bigger batch (≈8192)** + scaled LR — fewer steps, better utilization. **8192 is the
     sweet spot; do not go higher** (see §5).
   - **(C) MPS (`--device mps`) at `bs≈8192`** — the M1 GPU. Only wins once batches are large.
3. **Projected speedup** (synthetic bench matching your model+data shape, scaled to ~6M rows):
   ~155 s/epoch → **~75 s/epoch** (CPU, A+B) → **~40 s/epoch** (MPS, A+B+C), ~**4×**. (Your observed
   epochs are ~130–225 s, so expect that or a touch better.)
4. **Biggest risk is not speed, it's quality.** Larger batches = fewer gradient updates/epoch and
   less gradient noise; LR must be retuned and the resulting **val MAE must be re-validated** before
   the model is trusted/registered. See §6.

---

## 1. Diagnosis — where the time goes

The model is ~210K params; the per-batch FLOPs are trivial. The cost is overhead that scales with
the **number of optimizer steps** (~23,600/epoch at bs=256 on 6M rows; ~1,562 on the 400K bench),
not the math. Three sources, in rough order of impact at the current bs=256:

- **Per-optimizer-step framework overhead (dominant).** `zero_grad` / autograd bookkeeping /
  `optimizer.step` / the Python loop, paid once per step. This is the bulk, and it's what *batch
  size* attacks: in the bench, bs=256→4096 (1,562→98 steps) cut the epoch ~45% (9.0→5.0 s),
  whereas removing the `DataLoader` at fixed bs=256 cut only ~13%.
- **Per-sample `DataLoader` (secondary, ~13%).** `train()` wraps `AgricolaValueDataset` in a
  `DataLoader` that calls `__getitem__(i)` **once per row** (~6M/epoch, independent of batch size)
  + a per-item `.float()` upcast + collate (`AgricolaValueDataset.__getitem__`,
  `agricola/agents/nn/dataset.py:298`). Batched indexing removes this — modest alone, but it's the
  *enabler* for large batches fed cleanly and for MPS-resident data.
- **Per-batch `.item()` syncs (mainly an MPS concern).** `train_one_epoch` calls `.item()` twice
  per batch (`agricola/agents/nn/training.py:122-123`). Cheap on CPU; **on MPS each forces a
  GPU→CPU sync** that would erase the GPU gain if left in the inner loop.

---

## 2. Benchmark evidence

A synthetic benchmark (random data, an `nn.Sequential` equivalent of the real arch:
`Linear→LayerNorm→GELU→Dropout(0.2)` × `[256,256,256,128]` → `Linear(1)`) over 400K rows, scaled
×15.1 to your ~6M-row train split. The current-path scaled number (~155 s) lands inside the
observed log range (~130–225 s; mean ~175 s), which gives some confidence the synthetic is
faithful — **but it is still synthetic; confirm on real data (§7).**

**Path comparison (400K rows; "scaled" = ×15.1 ≈ 6M):**

| Path | per-epoch (400K) | scaled ≈6M | vs current |
|---|---|---|---|
| (A) current: `DataLoader` bs=256, CPU | 10.3 s | **~155 s** | 1× (your log: ~130–225 s ✓) |
| batched-index bs=256, CPU | 9.0 s | ~135 s | 1.1× |
| batched-index bs=4096, CPU | 5.0 s | ~75 s | ~2× |
| batched-index bs=8192, CPU | 5.0 s | ~75 s | ~2× |
| batched-index bs=4096, **MPS** | 7.8 s | ~117 s | *slower than CPU* |
| batched-index bs=8192, **MPS** | 2.5 s | **~40 s** | **~4×** |

**Batch-size sweep (400K rows; `steps` = gradient updates/epoch = N/bs):**

| batch | steps/epoch | CPU | MPS |
|---|---|---|---|
| 4096 | 98 | 9.0 s | 4.7 s |
| **8192** | **49** | 9.0 s | **2.1 s** |
| 16384 | 25 | 8.3 s | 2.3 s |
| 32768 | 13 | 8.7 s | 2.6 s |
| 65536 | 7 | 8.0 s | 2.4 s |

Reading: **CPU is flat past ~4096** (overhead already gone, you're just doing the same total
FLOPs). **MPS is best at ~8192 and gets slightly *worse* beyond.** (CPU absolute numbers drift
run-to-run from fanless thermal throttling; the flat *shape* is the robust part.)

---

## 3. The changes (code)

All three live in `agricola/agents/nn/training.py` + a couple of CLI flags in
`scripts/nn/train_first.py`. **They are additive and gated on a `fast_loader` flag** — when it's
off, the existing `train_one_epoch` / `evaluate` / `DataLoader` path runs untouched.

### 3a. Add two batched-index functions (new, in `training.py`)

```python
def train_one_epoch_batched(
    model, X, y, optimizer, loss_fn, device, batch_size, generator,
):
    """Batched-index training epoch — drop-in replacement for
    `train_one_epoch` that bypasses the per-sample DataLoader.

    X: raw feature tensor (float16 or float32), shape (N, ENCODED_DIM).
    y: normalized target tensor (float32), shape (N,).
    Both may live on CPU or on `device`. One gather per batch (not one
    __getitem__ per row); a single .item() sync at epoch end (not two
    per batch — matters a lot on MPS). Returns (train_mse, train_mae) in
    NORMALIZED space, same as train_one_epoch.
    """
    model.train()
    n = X.shape[0]
    is_half = X.dtype == torch.float16
    # CPU-generated permutation (reproducible via `generator`), moved to
    # the data's device so the gather happens where the data lives.
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
        pred = model(xb)                          # ConfigurableMLP squeezes to (B,)
        loss = loss_fn(pred, yb)
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            err = pred.detach() - yb
            sum_sq += (err * err).sum()           # accumulate as tensors...
            sum_abs += err.abs().sum()
    return (sum_sq / n).item(), (sum_abs / n).item()   # ...sync ONCE per epoch


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
```

These mirror the *exact* per-batch body of the originals (`pred = model(xb)`,
`loss = loss_fn(pred, yb)`, `err = pred - yb`) — so all existing shape handling is preserved
(`ConfigurableMLP` already returns `(B,)`, `y` is `(B,)`, no broadcasting). The only behavioral
deltas are: batches come from index-slicing, and the MSE/MAE accumulators stay on-device and sync
once per epoch.

### 3b. Wire them into `train()` behind a flag

Add two kwargs to the `train(...)` signature:

```python
    fast_loader: bool = False,     # batched-index path instead of DataLoader
    data_on_device: bool = False,  # hold X/y resident on `device` (fastest on MPS; watch RAM)
```

Replace the **DataLoader construction block** (`training.py:443-454`) with a branch:

```python
    g = torch.Generator()
    g.manual_seed(torch_seed)

    if fast_loader:
        # Pull the in-memory tensors straight from the datasets. Optionally
        # hold them resident on the device (fastest on MPS — see §4/§6 RAM note).
        Xtr, ytr = train_ds._X, train_ds._y
        Xva, yva = val_ds._X, val_ds._y
        Xte, yte = test_ds._X, test_ds._y
        if data_on_device:
            Xtr, ytr = Xtr.to(device_obj), ytr.to(device_obj)
            Xva, yva = Xva.to(device_obj), yva.to(device_obj)
            Xte, yte = Xte.to(device_obj), yte.to(device_obj)
    else:
        train_loader = DataLoader(
            train_ds, batch_size=batch_size, shuffle=True,
            drop_last=False, generator=g,
        )
        val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, drop_last=False)
        test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False, drop_last=False)
```

In the **epoch loop** (`training.py:490-493`):

```python
        if fast_loader:
            train_mse, train_mae_norm = train_one_epoch_batched(
                model, Xtr, ytr, optimizer, loss_fn, device_obj, batch_size, g)
            val_mse, val_mae_norm = evaluate_batched(
                model, Xva, yva, device_obj, batch_size)
        else:
            train_mse, train_mae_norm = train_one_epoch(
                model, train_loader, optimizer, loss_fn, device_obj)
            val_mse, val_mae_norm = evaluate(model, val_loader, device_obj)
```

In the **final test eval** (`training.py:537`):

```python
        if fast_loader:
            test_mse, test_mae_norm = evaluate_batched(best_model, Xte, yte, device_obj, batch_size)
        else:
            test_mse, test_mae_norm = evaluate(best_model, test_loader, device_obj)
```

⚠ **One loose end — the calibration plot.** `save_calibration_plot(...)` (`training.py:571`) still
takes a `DataLoader` (`val_loader`). On the `fast_loader` path `val_loader` doesn't exist. Simplest
fix: build a throwaway loader just for the plot, regardless of path:

```python
    cal_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, drop_last=False)
    if save_calibration_plot(best_model, cal_loader, target_std, device_obj, out_dir / "calibration.png"):
        ...
```

(`measure_leaf_value_scale` at `training.py:545` already takes a tensor — `val_ds._X.float().to(...)`
— so it is unaffected.)

### 3c. CLI flags (`scripts/nn/train_first.py`)

```python
    parser.add_argument("--fast-loader", action="store_true", default=False,
                        help="Batched-index training loop (skips the per-sample "
                             "DataLoader). Recommended with large batch / MPS.")
    parser.add_argument("--data-on-device", action="store_true", default=False,
                        help="(fast-loader) Hold train/val/test tensors resident "
                             "on --device. Fastest on MPS; ~2.8 GB f16 total "
                             "(train+val+test) for a 6M-row run — watch RAM on 8 GB.")
```

…and thread them into the `train(...)` call:

```python
        fast_loader=args.fast_loader,
        data_on_device=args.data_on_device,
```

### 3d. (Optional, smaller) Cheap standalone win if you *don't* adopt the fast path yet

Even on the existing `DataLoader` path, move the `.item()` calls out of `train_one_epoch`'s inner
loop — accumulate `sum_sq`/`sum_abs` as device tensors and `.item()` once at the end (same pattern
as 3a). Negligible on CPU, meaningful on MPS. This alone is a low-risk first step.

---

## 4. Recommended invocation

```bash
# Fast CPU run (safe, no GPU, ~2× — good first validation of the fast path)
python scripts/nn/train_first.py --run-dir <run> [usual flags] \
    --fast-loader --batch-size 8192 --lr 3e-3

# Full speed on the M1 GPU (~4×)
python scripts/nn/train_first.py --run-dir <run> [usual flags] \
    --device mps --fast-loader --data-on-device --batch-size 8192 --lr 3e-3
```

- Start with the **CPU** form to confirm the fast path produces sane curves, *then* add `--device mps`.
- `--data-on-device` is what realized the benchmarked MPS speedup (resident gather). Without it,
  per-batch host→device transfer still works but the speedup may be smaller — **measure both** (§6).
- `--lr 3e-3` is a **guess** (≈3× the current `1e-3` default) — see §6 for why and what to watch.

---

## 5. Why not push the batch even higher than ~8192?

- **Speed:** there's a floor and you're already at it. CPU is flat past ~4096; MPS is best at ~8192
  and slightly *worse* beyond (§2 sweep). No speed to be gained.
- **Quality:** gets *worse* with bigger batch (fewer updates/epoch, less gradient noise — §6).
- **Memory is *not* the limiter at the recommended batch:** at bs=8192 the forward/backward
  activations for this tiny model are only ~100–150 MB — negligible beside the fixed ~2 GB
  *resident dataset tensor*. (Activations *do* grow with batch — roughly ~1 GB at bs=65536 — so at
  the extreme they start to matter, one more reason not to go that high. At 8192 they're a non-issue.)

**Conclusion: 8192 is the sweet spot** — essentially all the speed, while keeping ~740 updates/epoch
on the real 6M data (close to the dynamics the pipeline is calibrated around).

---

## 6. Uncertainty / risks — read before trusting a fast-path model

Ordered roughly by how likely they are to bite.

1. **⚠ Optimization quality (the real risk).** Larger batch → fewer gradient updates/epoch
   (bs=8192 ≈ 740 steps on 6M vs ~23,600 at bs=256) and less gradient noise (which acts as a
   regularizer). Consequences: the model may need **more epochs** and/or a **higher LR** to reach
   the same fit, and could land in a sharper minimum that **generalizes slightly worse**
   (large-batch generalization gap). **The `--lr 3e-3` suggestion is unverified** — linear scaling
   (×32 → 3.2e-2) is almost certainly too hot for AdamW; sqrt scaling (≈5.6e-3) or a modest 2–4×
   is a safer starting band. **Action:** sweep LR a bit and **confirm the final val MAE matches a
   current bs=256 baseline** before registering the model. A faster run that's meaningfully worse
   is not a win — the `nn_models/REGISTRY.md` comparisons assume each model trained to its genuine
   best.
2. **⚠ MPS RAM on 8 GB.** `--data-on-device` holds the train tensor (~2 GB f16 for 6M rows) +
   val + test resident in unified memory alongside Python/torch. **This was not tested on the full
   real dataset** — it may OOM. Fallbacks: drop `--data-on-device` (per-batch transfer, slower but
   low memory), or reduce rows via the existing `--train-keep-frac` / `--train-game-frac`.
3. **⚠ MPS numerics ≠ CPU.** MPS is **not bit-deterministic** (the code comment at
   `training.py:57-60` notes the CPU path's determinism guarantee — that does not hold on MPS), and
   LayerNorm/GELU can differ slightly from CPU. Curves won't be identical across devices. **Action:**
   validate the MPS-trained model's val MAE *and* its head-to-head gameplay against a CPU baseline,
   not just the loss number.
4. **⚠ Nightly PyTorch + MPS op gaps.** This is `2.1.0.dev`. MPS coverage in nightlies occasionally
   has unimplemented ops or bugs; an op could error or silently CPU-fallback. **Action:** run 1–2
   epochs on MPS first and watch for warnings/errors before committing to a long run.
5. **Per-batch transfer vs resident speedup is unmeasured.** The ~4× / ~40 s figure came from the
   *resident* (`--data-on-device`) MPS run. The per-batch-transfer MPS speedup is unknown — measure it.
6. **Synthetic benchmark caveat.** All numbers are from a synthetic stand-in arch on random data, not
   your real `ConfigurableMLP`/`NormalizedValueModel` on real features. The current-path number
   matched the observed log (good sign) but **confirm the real before/after** (§7).
7. **Thermal throttling.** Sustained CPU runs throttle on the fanless M1 (visible as the CPU
   numbers creeping up across the sweep). MPS may run cooler for long jobs — a secondary reason it
   can help wall-clock, separate from raw throughput.
8. **`drop_last=False` preserved.** The fast path keeps the final partial batch (matches current
   behavior). Fine; just noting it's intentional.

---

## 7. Validation checklist before adopting

- [ ] `pytest tests/test_train_first_nn.py` (and `tests/test_nn_*`) green after the edits.
- [ ] Run **current path** (no flags) once — confirm identical behavior to before (regression guard).
- [ ] Run **`--fast-loader` on CPU**, same data/seed — confirm val MAE lands at the current baseline
      (the batched path should be numerically ~equivalent on CPU; small float-order differences only).
- [ ] Time a real epoch each way — confirm the ~2× (CPU) / ~4× (MPS) projection holds on real data.
- [ ] Run **`--device mps`** for 1–2 epochs first (op-support / OOM smoke test), then full.
- [ ] LR sweep at bs=8192; pick the LR whose **final val MAE is at least as good as (≤) the bs=256
      baseline**, not just the fastest run.
- [ ] Update `nn_models/REGISTRY.md` per the project convention (note device/batch/LR in the row).

---

## 8. File-change summary

| File | Change | Gated? |
|---|---|---|
| `agricola/agents/nn/training.py` | Add `train_one_epoch_batched` + `evaluate_batched`; add `fast_loader` / `data_on_device` kwargs to `train()`; branch the loader/loop/test-eval; throwaway loader for calibration plot | Yes — `fast_loader=False` default = current behavior |
| `scripts/nn/train_first.py` | Add `--fast-loader` / `--data-on-device` flags; pass through | Yes |
| `agricola/agents/nn/dataset.py` | **No change required** (fast path reads `._X` / `._y`) | — |

Reminder: with the defaults (`fast_loader=False`), **nothing changes** — these are pure additions.
