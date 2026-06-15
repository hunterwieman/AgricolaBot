"""Memory-bounded streaming dataloader for the joint shared-trunk trainer.

The in-RAM builder (`shared_dataset.build_shared_datasets`) materializes the
*entire* dataset as torch tensors. At 117k games that is ~8.5 GB in one process
on the 8 GB M1 → kernel_task memory-compression thrash. This module trains
**directly off the on-disk per-pickle chunk npzs** instead, so the training
process RAM is bounded to ~2-3 GB *regardless of corpus size* (117k, 250k, a
million games all train at the same footprint).

The win comes from NOT holding the full dataset — not from a smaller dtype. So
the streaming buffer holds rows as float32; int8 storage is irrelevant here.

What streams vs what's materialized:
  - **Value + the 7 fixed heads (TRAIN)** — `_TaskStream`s. Each reads ONLY its
    own keys from each chunk, filters to that chunk's train rows (split==0 by
    `_seed_split` on the chunk's seed array), keeps an in-RAM shuffle buffer of
    ~`buffer_chunks` chunks' worth of rows, and `.next()` pops a `batch_size`
    batch with the exact per-task tensor layout `_CyclicTensor.next()` produces.
    The chunk order is reshuffled each epoch and cycled infinitely (the trainer's
    `--steps-per-epoch` defines the epoch length, so the stream never runs dry).
  - **Pointer heads (TRAIN)** — materialized `AgricolaPointerDataset`s. Pointer
    rows are small (a few % of decisions), so a one-time stream-into-RAM is cheap
    and lets the existing ragged `pointer_collate` DataLoader path stay unchanged.
  - **val / test (ALL tasks)** — materialized datasets. These are 10%/10% of the
    corpus (~1.5-2 GB combined at 117k) and the eval loops index them directly
    (`ds._X[...]`), so they must be the real dataset classes held in RAM.

The shared input norm + `target_std` are fit on the value-TRAIN rows by a
streaming two-pass float64-block scan (the same algorithm as
`_finalize_payloads`, adapted to read from chunk paths), so the full train value
tensor is never materialized.

Imports torch (via the dataset classes); not re-exported from
`agricola.agents.nn.__init__`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import torch

from agricola.agents.nn.dataset import (
    AgricolaValueDataset,
    NormStats,
    _seed_split,
)
from agricola.agents.nn.encoder import ENCODER_V2, ENCODING_VERSION, EncoderSpec
from agricola.agents.nn.policy_dataset import AgricolaPolicyDataset
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.policy_pointer_dataset import AgricolaPointerDataset
from agricola.agents.nn.shared_dataset import (
    _FIXED_NAMES,
    _POINTER_NAMES,
    _load_or_encode_run_dir,
    _src_load,
)
from agricola.legality import legal_actions as full_legal_actions


# ---------------------------------------------------------------------------
# Split helper (one place, matches shared_dataset._splits_of)
# ---------------------------------------------------------------------------


def _splits_of(seeds, split_seed, train_frac, val_frac):
    """Per-row train/val/test split (0/1/2). Dedups by unique seed (a game's rows
    share one seed) — same assignment as `_seed_split`, vectorized."""
    if seeds.shape[0] == 0:
        return np.zeros(0, np.int8)
    uniq, inv = np.unique(seeds, return_inverse=True)
    sp = np.fromiter(
        (_seed_split(int(s), split_seed, train_frac, val_frac) for s in uniq),
        dtype=np.int8, count=uniq.shape[0])
    return sp[inv]


# ---------------------------------------------------------------------------
# Per-task shuffle-buffer streamer
# ---------------------------------------------------------------------------


class _TaskStream:
    """Infinite, windowed-shuffle stream of TRAIN batches for one dense task,
    read lazily off the chunk npzs. `.next()` returns the exact tensor tuple the
    trainer's `_CyclicTensor.next()` produces for that task:

      - value : `(X[f32], y[f32])`           y already divided by target_std
      - fixed : `(X[f32], pi[f32], mask[bool], weight[f32])`  weight = ones

    Only this task's keys are loaded from each chunk; rows are filtered to the
    chunk's TRAIN split. A buffer of ~`buffer_chunks` chunks' worth of rows is
    held and globally(-within-buffer) shuffled; when it drops below one batch the
    next chunk's train rows are pulled in and the pool reshuffled. The chunk order
    is reshuffled each time the chunk list is exhausted (one epoch ≈ one pass)."""

    def __init__(self, kind, name, chunk_paths, *, batch_size, buffer_chunks,
                 target_std, split_seed, train_frac, val_frac, generator):
        self.kind = kind                      # "value" | "fixed"
        self.name = name                      # head name (fixed) or "value"
        self.paths = list(chunk_paths)
        self.bs = int(batch_size)
        self.buffer_chunks = int(buffer_chunks)
        self.target_std = float(target_std)
        self.split_seed = split_seed
        self.train_frac = train_frac
        self.val_frac = val_frac
        self.gen = generator
        # The npz key set for this task.
        if kind == "value":
            self._keys = ("value__X", "value__y", "value__seed")
        else:
            p = f"fixed__{name}__"
            self._keys = (p + "X", p + "pi", p + "m", p + "seed")
        # Buffer state: a list of np arrays (one per stream-field) + a cursor.
        self._buf = None                      # tuple of np arrays, train rows only
        self._cursor = 0                      # rows consumed from the front of _buf
        self._order = None                    # shuffled chunk index order
        self._cidx = 0                        # position in self._order

    # -- chunk reading ------------------------------------------------------

    def _reshuffle_chunks(self):
        n = len(self.paths)
        perm = torch.randperm(n, generator=self.gen).numpy()
        self._order = perm
        self._cidx = 0

    def _next_chunk_train_rows(self):
        """Load the next chunk's TRAIN rows for this task as a tuple of np arrays
        in stream-field order. Skips chunks with no train rows for this task."""
        while True:
            if self._order is None or self._cidx >= len(self._order):
                self._reshuffle_chunks()
            path = self.paths[int(self._order[self._cidx])]
            self._cidx += 1
            seed = _src_load(path, self._keys[-1])  # the seed key is last
            if seed is None or seed.shape[0] == 0:
                continue
            tr = _splits_of(seed, self.split_seed, self.train_frac, self.val_frac) == 0
            if not tr.any():
                continue
            arrs = []
            for k in self._keys[:-1]:           # all but seed
                a = _src_load(path, k)
                arrs.append(a[tr])
            return tuple(arrs)

    # -- buffer management --------------------------------------------------

    def _ensure_buffer(self):
        """Compact consumed rows and pull chunks until the buffer holds at least
        one batch (or, if the whole corpus is smaller than a batch, all of it)."""
        # Compact: drop the already-consumed prefix.
        if self._buf is not None and self._cursor > 0:
            self._buf = tuple(a[self._cursor:] for a in self._buf)
            self._cursor = 0
        # How many rows we want resident before serving: roughly buffer_chunks of
        # data, but always ≥ one batch so a single .next() can be served.
        loaded_chunks = 0
        while True:
            have = 0 if self._buf is None else self._buf[0].shape[0]
            if have >= self.bs and loaded_chunks >= 1:
                break
            if have >= self.bs and loaded_chunks == 0 and self._buf is not None:
                # Already have a batch from a prior compaction; still top up to
                # buffer_chunks worth so the shuffle window stays wide.
                pass
            rows = self._next_chunk_train_rows()
            loaded_chunks += 1
            if self._buf is None:
                self._buf = rows
            else:
                self._buf = tuple(np.concatenate([b, r], axis=0)
                                  for b, r in zip(self._buf, rows))
            if loaded_chunks >= self.buffer_chunks and self._buf[0].shape[0] >= self.bs:
                break
        # Shuffle the resident pool, then serve sequentially until depleted.
        n = self._buf[0].shape[0]
        perm = torch.randperm(n, generator=self.gen).numpy()
        self._buf = tuple(a[perm] for a in self._buf)
        self._cursor = 0

    def next(self):
        if (self._buf is None
                or (self._buf[0].shape[0] - self._cursor) < self.bs):
            self._ensure_buffer()
        s = self._cursor
        e = min(s + self.bs, self._buf[0].shape[0])
        self._cursor = e
        sl = tuple(a[s:e] for a in self._buf)
        return self._to_batch(sl)

    def _to_batch(self, sl):
        if self.kind == "value":
            X, y = sl
            xt = torch.from_numpy(np.ascontiguousarray(X)).float()
            yt = torch.from_numpy(np.ascontiguousarray(y).astype(np.float32)
                                  / self.target_std)
            return xt, yt
        # fixed: (X, pi, mask) + weight=ones
        X, pi, mask = sl
        xt = torch.from_numpy(np.ascontiguousarray(X)).float()
        pit = torch.from_numpy(np.ascontiguousarray(pi).astype(np.float32))
        mt = torch.from_numpy(np.ascontiguousarray(mask).astype(bool))
        wt = torch.ones(xt.shape[0], dtype=torch.float32)
        return xt, pit, mt, wt


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass
class SharedStreams:
    """Streaming analog of `SharedDatasets`. The trainer reads `value_stream` +
    `fixed_streams` for dense train batches, the materialized `pointer_train`
    DataLoaders for pointer train, and `val` / `test` (`SharedDatasets`-like
    dicts) for eval."""

    input_stats: NormStats
    value_stream: _TaskStream
    fixed_streams: dict                       # name -> _TaskStream
    pointer_train: dict                       # name -> AgricolaPointerDataset
    val: dict                                 # task -> dataset (value/fixed/ptr keys)
    test: dict
    pointer_cand_norm: dict                   # name -> (mean, std)
    sizes: dict                               # task -> (n_train, n_val, n_test)


# ---------------------------------------------------------------------------
# Streaming norm fit (value-train), two-pass float64 blocks
# ---------------------------------------------------------------------------


def _fit_input_norm_streaming(chunk_paths, *, dim, split_seed, train_frac,
                              val_frac, verbose):
    """Shared input mean/std (population, ddof=0) + target_std, fit on the
    value-TRAIN rows by streaming each chunk's `value__X`/`value__y` and keeping
    only ONE chunk's worth of train rows live at a time (never the whole train
    value tensor). Matches `_finalize_payloads`'s algorithm."""
    eps = np.float32(1e-6)
    # Pass 1: row count + column sums (float64).
    n_tr = 0
    s1 = np.zeros(dim, np.float64)
    y_sum = 0.0
    y_sqsum = 0.0
    for p in chunk_paths:
        seed = _src_load(p, "value__seed")
        if seed is None or seed.shape[0] == 0:
            continue
        tr = _splits_of(seed, split_seed, train_frac, val_frac) == 0
        k = int(tr.sum())
        if not k:
            continue
        X = _src_load(p, "value__X")[tr].astype(np.float64)
        y = _src_load(p, "value__y")[tr].astype(np.float64)
        s1 += X.sum(0)
        y_sum += float(y.sum())
        y_sqsum += float((y * y).sum())
        n_tr += k
        del X, y, seed
    mean64 = s1 / max(n_tr, 1)
    # Pass 2: column sum of squared deviations (float64).
    s2 = np.zeros(dim, np.float64)
    for p in chunk_paths:
        seed = _src_load(p, "value__seed")
        if seed is None or seed.shape[0] == 0:
            continue
        tr = _splits_of(seed, split_seed, train_frac, val_frac) == 0
        if not tr.any():
            continue
        blk = _src_load(p, "value__X")[tr].astype(np.float64)
        blk -= mean64
        s2 += np.einsum("ij,ij->j", blk, blk)
        del blk, seed
    mean = mean64.astype(np.float32)
    std = np.sqrt(s2 / max(n_tr, 1)).astype(np.float32)
    std = np.where(std < eps, np.float32(1.0), std)
    # target_std from streamed y moments (population std).
    if n_tr:
        y_mean = y_sum / n_tr
        tgt_std = float(np.sqrt(max(y_sqsum / n_tr - y_mean * y_mean, 0.0)))
    else:
        tgt_std = 1.0
    if not np.isfinite(tgt_std) or tgt_std < 1e-9:
        tgt_std = 1.0
    if verbose:
        print(f"  input norm fit on {n_tr} value-train rows; target_std={tgt_std:.3f}",
              flush=True)
    return mean, std, tgt_std, n_tr


# ---------------------------------------------------------------------------
# Materialize val/test (+ pointer train) from chunk paths, splits only
# ---------------------------------------------------------------------------


def _cat_split(chunk_paths, key, *, want_split, split_seed, train_frac, val_frac,
               seed_key):
    """Concatenate `key` across chunks, keeping only rows whose seed maps to
    `want_split`. Two-pass (size then fill) so peak = result + one chunk."""
    total, tail, dtype0 = 0, None, None
    for p in chunk_paths:
        seed = _src_load(p, seed_key)
        if seed is None or seed.shape[0] == 0:
            continue
        a = _src_load(p, key)
        if a is None:
            continue
        sp = _splits_of(seed, split_seed, train_frac, val_frac)
        m = sp == want_split
        total += int(m.sum())
        if tail is None:
            tail, dtype0 = tuple(a.shape[1:]), a.dtype
        del a, seed
    if dtype0 is None:
        return np.zeros(0)
    out = np.empty((total,) + tail, dtype=dtype0)
    off = 0
    for p in chunk_paths:
        seed = _src_load(p, seed_key)
        if seed is None or seed.shape[0] == 0:
            continue
        a = _src_load(p, key)
        if a is None:
            continue
        m = _splits_of(seed, split_seed, train_frac, val_frac) == want_split
        k = int(m.sum())
        if k:
            out[off:off + k] = a[m]
            off += k
        del a, seed
    return out


def _materialize_value(chunk_paths, want_split, target_std, *, split_seed,
                       train_frac, val_frac):
    X = _cat_split(chunk_paths, "value__X", want_split=want_split,
                   split_seed=split_seed, train_frac=train_frac, val_frac=val_frac,
                   seed_key="value__seed")
    y = _cat_split(chunk_paths, "value__y", want_split=want_split,
                   split_seed=split_seed, train_frac=train_frac, val_frac=val_frac,
                   seed_key="value__seed")
    if X.shape[0] == 0:
        from agricola.agents.nn.encoder import ENCODED_DIM
        X = np.zeros((0, ENCODED_DIM), np.float16)
        y = np.zeros(0, np.float32)
    return AgricolaValueDataset(X, (y / target_std).astype(np.float32))


def _materialize_fixed(chunk_paths, name, want_split, *, split_seed, train_frac,
                       val_frac):
    p = f"fixed__{name}__"
    sk = p + "seed"
    X = _cat_split(chunk_paths, p + "X", want_split=want_split, split_seed=split_seed,
                   train_frac=train_frac, val_frac=val_frac, seed_key=sk)
    t = _cat_split(chunk_paths, p + "t", want_split=want_split, split_seed=split_seed,
                   train_frac=train_frac, val_frac=val_frac, seed_key=sk)
    m = _cat_split(chunk_paths, p + "m", want_split=want_split, split_seed=split_seed,
                   train_frac=train_frac, val_frac=val_frac, seed_key=sk)
    pi = _cat_split(chunk_paths, p + "pi", want_split=want_split, split_seed=split_seed,
                    train_frac=train_frac, val_frac=val_frac, seed_key=sk)
    won = _cat_split(chunk_paths, p + "won", want_split=want_split, split_seed=split_seed,
                     train_frac=train_frac, val_frac=val_frac, seed_key=sk)
    K = HEADS[name].num_classes
    from agricola.agents.nn.encoder import ENCODED_DIM
    n = X.shape[0] if X.ndim == 2 else 0
    if n == 0:
        X = np.zeros((0, ENCODED_DIM), np.float16)
        t = np.zeros(0, np.int64)
        m = np.zeros((0, K), bool)
        pi = np.zeros((0, K), np.float32)
        won = np.zeros(0, np.float32)
    return AgricolaPolicyDataset(X, t, m, np.ones(n, np.float32), won, pi)


def _materialize_pointer(chunk_paths, name, want_split, *, split_seed, train_frac,
                         val_frac):
    """Materialize one pointer head's rows for a split. Pointer rows are ragged:
    per-snapshot `state` + a flat `cand`/`pi` block sliced by per-row offsets.
    Stream chunks, keep only train/val/test rows, rebuild global offsets."""
    pre = f"ptr__{name}__"
    cdim = POINTER_HEADS[name].candidate_dim
    states, cand_blocks, pi_blocks, pos_list, won_list, counts = [], [], [], [], [], []
    for p in chunk_paths:
        seed = _src_load(p, pre + "seed")
        if seed is None or seed.shape[0] == 0:
            continue
        sp = _splits_of(seed, split_seed, train_frac, val_frac)
        rows = np.where(sp == want_split)[0]
        if rows.size == 0:
            continue
        state = _src_load(p, pre + "state")
        cand = _src_load(p, pre + "cand")
        pi = _src_load(p, pre + "pi")
        pos = _src_load(p, pre + "pos")
        won = _src_load(p, pre + "won")
        offsets = _src_load(p, pre + "offsets")
        for i in rows:
            a, b = int(offsets[i]), int(offsets[i + 1])
            states.append(state[i])
            cand_blocks.append(cand[a:b])
            pi_blocks.append(pi[a:b])
            pos_list.append(int(pos[i]))
            won_list.append(float(won[i]))
            counts.append(b - a)
        del state, cand, pi, pos, won, offsets, seed
    if not states:
        from agricola.agents.nn.encoder import ENCODED_DIM
        return AgricolaPointerDataset(
            np.zeros((0, ENCODED_DIM), np.float32),
            np.zeros((0, cdim), np.float32), np.zeros(1, np.int64),
            np.zeros(0, np.int64), np.zeros(0, np.float32),
            np.zeros(0, np.float32), np.zeros(0, np.float32))
    state_arr = np.stack(states).astype(np.float32)
    cand_flat = np.concatenate(cand_blocks, 0).astype(np.float32)
    pi_flat = np.concatenate(pi_blocks, 0).astype(np.float32)
    local_off = np.concatenate([[0], np.cumsum(np.array(counts, np.int64))]).astype(np.int64)
    return AgricolaPointerDataset(
        state_arr, cand_flat, local_off,
        np.array(pos_list, np.int64), np.ones(len(pos_list), np.float32),
        np.array(won_list, np.float32), pi_flat)


def _fit_pointer_cand_norm(train_ds, candidate_dim):
    """Candidate-feature mean/std over a materialized pointer-train dataset's
    candidate rows (same as `_finalize_payloads`)."""
    if train_ds is None or len(train_ds) == 0 or train_ds._cand.shape[0] == 0:
        return (np.zeros(candidate_dim, np.float32), np.ones(candidate_dim, np.float32))
    c = train_ds._cand.numpy()
    return (c.mean(0).astype(np.float32),
            np.where(c.std(0) < 1e-6, 1.0, c.std(0)).astype(np.float32))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_shared_streams(
    run_dirs: Sequence[Path] | Path | str,
    *,
    encoder: EncoderSpec = ENCODER_V2,
    batch_size: int = 8192,
    buffer_chunks: int = 8,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    legal_actions_fn=full_legal_actions,
    soft_targets: bool = True,
    use_cache: bool = True,
    n_workers: int = 1,
    generator: torch.Generator | None = None,
    verbose: bool = True,
) -> SharedStreams:
    """Build the streaming joint dataloaders. RAM is bounded to ~`buffer_chunks`
    chunks per dense task + the materialized val/test/pointer-train sets,
    regardless of corpus size.

    Ensures the per-pickle chunk caches exist first (via
    `_load_or_encode_run_dir`, which encodes any missing chunks), then:
      - fits the shared input norm + target_std on value-train by streaming,
      - builds `_TaskStream`s for value + each non-empty fixed head (train),
      - materializes pointer-train + all val/test datasets (small splits)."""
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]
    if generator is None:
        generator = torch.Generator()
        generator.manual_seed(0)

    # Ensure chunks on disk; gather their Paths (streamed lazily). The streaming
    # path REQUIRES the on-disk cache — that is the whole point.
    if not use_cache:
        raise ValueError("build_shared_streams requires use_cache=True "
                         "(it streams off the on-disk chunk npzs).")
    chunk_paths: list[Path] = []
    for rd in run_dirs:
        srcs = _load_or_encode_run_dir(rd, legal_actions_fn, soft_targets, True,
                                       verbose, encoder, n_workers)
        # All sources are Paths under use_cache=True.
        chunk_paths.extend(Path(s) for s in srcs)
    if verbose:
        print(f"Streaming over {len(chunk_paths)} chunks "
              f"from {len(run_dirs)} run dir(s) [{encoder.tag}]", flush=True)

    # Shared input norm + target_std (value-train), streamed.
    mean, std, tgt_std, n_value_train = _fit_input_norm_streaming(
        chunk_paths, dim=encoder.dim, split_seed=split_seed, train_frac=train_frac,
        val_frac=val_frac, verbose=verbose)
    input_stats = NormStats(input_mean=mean, input_std=std, target_std=tgt_std,
                            encoding_version=ENCODING_VERSION, target_mode="margin",
                            encoding_tag=encoder.tag)

    # Train streams: value + each fixed head that has any train rows.
    value_stream = _TaskStream(
        "value", "value", chunk_paths, batch_size=batch_size,
        buffer_chunks=buffer_chunks, target_std=tgt_std, split_seed=split_seed,
        train_frac=train_frac, val_frac=val_frac, generator=generator)

    # Per-head train row counts (cheap scan over seed arrays only).
    fixed_train_counts = {n: 0 for n in _FIXED_NAMES}
    ptr_train_counts = {n: 0 for n in _POINTER_NAMES}
    val_counts = {}      # task -> int
    test_counts = {}
    for p in chunk_paths:
        for n in _FIXED_NAMES:
            seed = _src_load(p, f"fixed__{n}__seed")
            if seed is None or seed.shape[0] == 0:
                continue
            sp = _splits_of(seed, split_seed, train_frac, val_frac)
            fixed_train_counts[n] += int((sp == 0).sum())
        for n in _POINTER_NAMES:
            seed = _src_load(p, f"ptr__{n}__seed")
            if seed is None or seed.shape[0] == 0:
                continue
            sp = _splits_of(seed, split_seed, train_frac, val_frac)
            ptr_train_counts[n] += int((sp == 0).sum())

    fixed_streams = {}
    for n in _FIXED_NAMES:
        if fixed_train_counts[n] > 0:
            fixed_streams[n] = _TaskStream(
                "fixed", n, chunk_paths, batch_size=batch_size,
                buffer_chunks=buffer_chunks, target_std=tgt_std, split_seed=split_seed,
                train_frac=train_frac, val_frac=val_frac, generator=generator)

    # Materialize pointer-train (small) + all val/test datasets.
    if verbose:
        print("  materializing val/test + pointer-train ...", flush=True)
    val, test = {}, {}
    val["value"] = _materialize_value(chunk_paths, 1, tgt_std, split_seed=split_seed,
                                      train_frac=train_frac, val_frac=val_frac)
    test["value"] = _materialize_value(chunk_paths, 2, tgt_std, split_seed=split_seed,
                                       train_frac=train_frac, val_frac=val_frac)
    for n in _FIXED_NAMES:
        val[f"fixed:{n}"] = _materialize_fixed(chunk_paths, n, 1, split_seed=split_seed,
                                               train_frac=train_frac, val_frac=val_frac)
        test[f"fixed:{n}"] = _materialize_fixed(chunk_paths, n, 2, split_seed=split_seed,
                                                train_frac=train_frac, val_frac=val_frac)
    pointer_train, pointer_cand_norm = {}, {}
    for n in _POINTER_NAMES:
        pointer_train[n] = _materialize_pointer(chunk_paths, n, 0, split_seed=split_seed,
                                                train_frac=train_frac, val_frac=val_frac)
        val[f"ptr:{n}"] = _materialize_pointer(chunk_paths, n, 1, split_seed=split_seed,
                                               train_frac=train_frac, val_frac=val_frac)
        test[f"ptr:{n}"] = _materialize_pointer(chunk_paths, n, 2, split_seed=split_seed,
                                                train_frac=train_frac, val_frac=val_frac)
        pointer_cand_norm[n] = _fit_pointer_cand_norm(
            pointer_train[n], POINTER_HEADS[n].candidate_dim)

    # Sizes bundle (train/val/test per task), matching SharedDatasets.sizes shape.
    sizes = {"value": (n_value_train, len(val["value"]), len(test["value"]))}
    for n in _FIXED_NAMES:
        sizes[f"fixed:{n}"] = (fixed_train_counts[n], len(val[f"fixed:{n}"]),
                               len(test[f"fixed:{n}"]))
    for n in _POINTER_NAMES:
        sizes[f"ptr:{n}"] = (ptr_train_counts[n], len(val[f"ptr:{n}"]),
                             len(test[f"ptr:{n}"]))

    if verbose:
        print(f"Shared streams built. value train={n_value_train} "
              f"val={len(val['value'])} test={len(test['value'])}", flush=True)
        for n in _FIXED_NAMES:
            print(f"  fixed:{n}: {sizes[f'fixed:{n}']}", flush=True)
        for n in _POINTER_NAMES:
            print(f"  ptr:{n}: {sizes[f'ptr:{n}']}", flush=True)

    return SharedStreams(
        input_stats=input_stats, value_stream=value_stream,
        fixed_streams=fixed_streams, pointer_train=pointer_train, val=val, test=test,
        pointer_cand_norm=pointer_cand_norm, sizes=sizes)
