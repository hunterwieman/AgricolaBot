"""One-pass, cached dataset builder for the shared-trunk model (Stage B).

The shared model trains value + every policy head on one trunk, so it needs all
their examples from the *same* games with a *consistent* train/val/test split.
This module reads each run dir's pickles **once** and emits, per game:

- **value rows** — both perspectives of every decision state *and* the terminal
  state, target = the game's terminal score margin from that perspective (the
  same target the standalone value net uses);
- **fixed-head rows** — the decider-perspective encoding of each decision state a
  fixed `DecisionHead` owns, with its legal mask + soft-π target;
- **pointer-head rows** — likewise for the `PointerHead` frontier decisions, with
  per-candidate features + soft-π over the candidates.

The decider-perspective encoding is computed once and shared between a state's
value row and its policy row, so the one pass is cheaper than running the value
builder and nine policy builders separately (which would each re-read every
pickle and re-encode).

**Caching.** The expensive work — `encode_state` over ~41k games — is written to
`<run_dir>/shared_v{ENCODING_VERSION}.npz` (one per run dir, like the value
builder's `encoded_v2.npz`, but carrying the policy targets too). A cache hit is
a pure `np.load` with zero engine calls, so every architecture you sweep on the
joint model reuses the one encode. Invalidated only by an encoder change
(`ENCODING_VERSION`) or a change in the head roster.

The returned `SharedDatasets` bundle reuses the existing, tested dataset classes
(`AgricolaValueDataset` / `AgricolaPolicyDataset` / `AgricolaPointerDataset`) so
the per-task loaders are unchanged; the trainer just interleaves them through the
shared model. A single input normalization (fit on the value train split — the
broadest population) is shared by all tasks, since the shared trunk has one input
norm; per-pointer-head candidate normalization is fit alongside.

Imports torch (via the dataset classes); not re-exported from
`agricola.agents.nn.__init__`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from agricola.agents.nn.dataset import (
    NormStats,
    _iter_worker_pickles,
    _seed_split,
)
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION, encode_state
from agricola.agents.nn.policy_dataset import (
    AgricolaPolicyDataset,
    _pi_vector,
)
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.policy_pointer_dataset import (
    AgricolaPointerDataset,
    _pi_pointer,
)
from agricola.agents.nn.schema import load_game_records
from agricola.legality import legal_actions as full_legal_actions


# Head roster baked into the cache key — re-encode if it changes.
_FIXED_NAMES = tuple(sorted(HEADS))
_POINTER_NAMES = tuple(sorted(POINTER_HEADS))
_ROSTER_TAG = "+".join(_FIXED_NAMES) + "|" + "+".join(_POINTER_NAMES)


def _margin_from(g, perspective: int) -> float:
    """Terminal score margin from `perspective`'s view (the value target)."""
    m = float(g.p0_final_score - g.p1_final_score)
    return m if perspective == 0 else -m


def _won_from(g, perspective: int) -> float:
    if g.winner is None:
        return -1.0
    return 1.0 if g.winner == perspective else 0.0


# ---------------------------------------------------------------------------
# One-pass extraction (per run dir) + cache
# ---------------------------------------------------------------------------


class _Accum:
    """Flat per-run-dir accumulators for value + each head's rows."""

    def __init__(self):
        self.v_X, self.v_y, self.v_seed = [], [], []
        # fixed[name] = dict of lists
        self.fixed = {n: {"X": [], "t": [], "m": [], "pi": [], "R": [],
                          "won": [], "seed": []} for n in _FIXED_NAMES}
        # pointer[name]
        self.ptr = {n: {"state": [], "cand": [], "pos": [], "pi": [], "R": [],
                        "won": [], "seed": []} for n in _POINTER_NAMES}

    def add_value(self, x, y, seed):
        self.v_X.append(x); self.v_y.append(y); self.v_seed.append(seed)


def _encode_games(games, legal_actions_fn, soft_targets: bool) -> _Accum:
    """One pass: emit value + fixed + pointer rows for a list of games."""
    acc = _Accum()
    fixed_heads = [HEADS[n] for n in _FIXED_NAMES]
    pointer_heads = [POINTER_HEADS[n] for n in _POINTER_NAMES]
    for g in games:
        for snap in g.decisions:
            s = snap.state
            d = snap.decider_idx
            x_d = encode_state(s, d).astype(np.float32)        # decider view
            x_o = encode_state(s, 1 - d).astype(np.float32)    # other view
            # value rows: both perspectives
            acc.add_value(x_d, _margin_from(g, d), g.seed)
            acc.add_value(x_o, _margin_from(g, 1 - d), g.seed)
            R, won = _margin_from(g, d), _won_from(g, d)
            # fixed-head row (decider view, reuse x_d)
            for h in fixed_heads:
                if not h.owns(s):
                    continue
                target = h.target_index(snap.chosen_action)
                if target is None:
                    break
                mask = h.legal_mask(s, legal_actions_fn)
                if not mask[target]:
                    raise ValueError(
                        f"chosen class {target} ({h.name}) not in its legal mask "
                        f"(seed={g.seed}) — encoder/legality drift.")
                pi = _pi_vector(h, snap, target, mask, soft_targets=soft_targets)
                fx = acc.fixed[h.name]
                fx["X"].append(x_d); fx["t"].append(target); fx["m"].append(mask)
                fx["pi"].append(pi); fx["R"].append(R); fx["won"].append(won)
                fx["seed"].append(g.seed)
                break
            # pointer-head row
            for h in pointer_heads:
                if not h.owns(s):
                    continue
                pairs = h.enumerate_candidates(s)
                if len(pairs) < 2:
                    break
                pos = h.target_position(s, snap.chosen_action)
                if pos is None:
                    raise ValueError(
                        f"chosen action not among '{h.name}' candidates "
                        f"(seed={g.seed}) — frontier drift.")
                pi = _pi_pointer(h, snap, pairs, pos, soft_targets=soft_targets)
                cand = np.stack([f for _, f in pairs]).astype(np.float32)
                pt = acc.ptr[h.name]
                pt["state"].append(x_d); pt["cand"].append(cand); pt["pos"].append(pos)
                pt["pi"].append(pi); pt["R"].append(R); pt["won"].append(won)
                pt["seed"].append(g.seed)
                break
        # terminal value rows
        ts = g.terminal_state
        acc.add_value(encode_state(ts, 0).astype(np.float32), _margin_from(g, 0), g.seed)
        acc.add_value(encode_state(ts, 1).astype(np.float32), _margin_from(g, 1), g.seed)
    return acc


def _accum_to_npz(acc: _Accum) -> dict:
    """Flatten an `_Accum` into a single dict of arrays for `np.savez`."""
    out: dict[str, np.ndarray] = {
        "roster": np.array(_ROSTER_TAG),
        "soft": np.array(True),
        "value__X": np.asarray(acc.v_X, np.float16),
        "value__y": np.asarray(acc.v_y, np.float32),
        "value__seed": np.asarray(acc.v_seed, np.int64),
    }
    for n in _FIXED_NAMES:
        fx = acc.fixed[n]
        K = HEADS[n].num_classes
        nrows = len(fx["t"])
        out[f"fixed__{n}__X"] = (np.asarray(fx["X"], np.float16) if nrows
                                 else np.zeros((0, ENCODED_DIM), np.float16))
        out[f"fixed__{n}__t"] = np.asarray(fx["t"], np.int64)
        out[f"fixed__{n}__m"] = (np.asarray(fx["m"], bool) if nrows
                                 else np.zeros((0, K), bool))
        out[f"fixed__{n}__pi"] = (np.asarray(fx["pi"], np.float32) if nrows
                                  else np.zeros((0, K), np.float32))
        out[f"fixed__{n}__R"] = np.asarray(fx["R"], np.float32)
        out[f"fixed__{n}__won"] = np.asarray(fx["won"], np.float32)
        out[f"fixed__{n}__seed"] = np.asarray(fx["seed"], np.int64)
    for n in _POINTER_NAMES:
        pt = acc.ptr[n]
        dim = POINTER_HEADS[n].candidate_dim
        nrows = len(pt["pos"])
        out[f"ptr__{n}__state"] = (np.asarray(pt["state"], np.float16) if nrows
                                   else np.zeros((0, ENCODED_DIM), np.float16))
        counts = np.array([c.shape[0] for c in pt["cand"]], np.int64)
        out[f"ptr__{n}__offsets"] = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        out[f"ptr__{n}__cand"] = (np.concatenate(pt["cand"], 0).astype(np.float32)
                                  if nrows else np.zeros((0, dim), np.float32))
        out[f"ptr__{n}__pi"] = (np.concatenate(pt["pi"], 0).astype(np.float32)
                                if nrows else np.zeros(0, np.float32))
        out[f"ptr__{n}__pos"] = np.asarray(pt["pos"], np.int64)
        out[f"ptr__{n}__R"] = np.asarray(pt["R"], np.float32)
        out[f"ptr__{n}__won"] = np.asarray(pt["won"], np.float32)
        out[f"ptr__{n}__seed"] = np.asarray(pt["seed"], np.int64)
    return out


def _chunk_dir(run_dir: Path) -> Path:
    """Per-pickle chunk cache dir. One npz per source pickle (NOT one giant npz
    per run dir) so peak encode memory is bounded to a single pickle — the OOM
    fix (a whole run dir is ~6M value rows ≈ 4+ GB held at once)."""
    return Path(run_dir) / f"shared_v{ENCODING_VERSION}_chunks"


def _roster_sentinel(run_dir: Path) -> Path:
    return _chunk_dir(run_dir) / "roster.txt"


def _cache_complete(run_dir: Path) -> bool:
    s = _roster_sentinel(run_dir)
    try:
        return s.exists() and s.read_text() == _ROSTER_TAG
    except Exception:
        return False


def _load_or_encode_run_dir(run_dir: Path, legal_actions_fn, soft_targets, use_cache,
                            verbose) -> list[dict]:
    """Return a LIST of per-pickle payload dicts for one run dir (each carries
    float16 X). Streams one pickle at a time, caching each as its own chunk npz —
    so encode peak memory is one pickle, and a kill mid-dir leaves the finished
    chunks on disk (resumable). `_finalize_payloads` consumes the flat chunk list
    directly (it already concatenates across an arbitrary payload list)."""
    cd = _chunk_dir(run_dir)
    if use_cache and _cache_complete(run_dir):
        if verbose:
            print(f"  shared cache HIT: {run_dir.name}", flush=True)
        return [dict(np.load(cp, allow_pickle=False))
                for cp in sorted(cd.glob("chunk_*.npz"))]
    if verbose:
        print(f"  shared cache MISS: encoding {run_dir.name} (per-pickle chunks)",
              flush=True)
    if use_cache:
        cd.mkdir(parents=True, exist_ok=True)
        for old in cd.glob("chunk_*.npz"):  # clear a stale/partial roster
            old.unlink()
        _roster_sentinel(run_dir).unlink(missing_ok=True)
    payloads: list[dict] = []
    for i, pkl in enumerate(_iter_worker_pickles([run_dir])):
        games = load_game_records(pkl)
        payload = _accum_to_npz(_encode_games(games, legal_actions_fn, soft_targets))
        del games
        if use_cache:
            cp = cd / f"chunk_{i:05d}.npz"
            tmp = cd / (cp.name + ".tmp.npz")
            np.savez(tmp, **payload)
            tmp.replace(cp)
            payload = dict(np.load(cp, allow_pickle=False))  # compact reload, drop lists
        payloads.append(payload)
        if verbose and i % 25 == 0:
            print(f"    encoded chunk {i} ({pkl.name})", flush=True)
    if use_cache:
        _roster_sentinel(run_dir).write_text(_ROSTER_TAG)
        if verbose:
            print(f"  wrote {len(payloads)} chunks to {cd.name}/", flush=True)
    return payloads


# ---------------------------------------------------------------------------
# Bundle + build
# ---------------------------------------------------------------------------


@dataclass
class SharedDatasets:
    """Per-task train/val/test datasets + the shared input norm + pointer cand
    norms. The trainer interleaves the per-task loaders through one model."""

    value: tuple                              # (train, val, test) AgricolaValueDataset
    fixed: dict                               # name -> (train, val, test)
    pointer: dict                             # name -> (train, val, test)
    input_stats: NormStats                    # the single shared input norm
    pointer_cand_norm: dict                   # name -> (mean[dim], std[dim])
    sizes: dict                               # task -> (n_train, n_val, n_test)


def _split_mask(seeds: np.ndarray, split_seed, train_frac, val_frac, which: int):
    if seeds.shape[0] == 0:
        return np.zeros(0, bool)
    sp = np.array([_seed_split(int(s), split_seed, train_frac, val_frac) for s in seeds])
    return sp == which


def build_shared_datasets(
    run_dirs: Sequence[Path] | Path | str,
    *,
    legal_actions_fn=full_legal_actions,
    soft_targets: bool = True,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    store_dtype: str = "float16",
    use_cache: bool = True,
    verbose: bool = True,
) -> SharedDatasets:
    """One-pass (cached) build of the joint value+policy datasets. Defaults to
    **full** legality (the self-play data was generated under it, so π's support
    stays inside every head's mask)."""
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]

    # Gather (cached) per-pickle chunk payloads, flattened across dirs. Each dir
    # yields a LIST of per-pickle chunks (bounded encode memory); _finalize
    # concatenates the flat list (handles per-chunk offsets uniformly).
    payloads: list[dict] = []
    for rd in run_dirs:
        payloads.extend(_load_or_encode_run_dir(rd, legal_actions_fn, soft_targets,
                                                use_cache, verbose))
    return _finalize_payloads(payloads, train_frac=train_frac, val_frac=val_frac,
                              split_seed=split_seed, store_dtype=store_dtype,
                              verbose=verbose)


def build_shared_datasets_from_games(
    games, *, legal_actions_fn=full_legal_actions, soft_targets: bool = True,
    train_frac: float = 0.8, val_frac: float = 0.1, split_seed: int = 0,
    store_dtype: str = "float32", verbose: bool = False,
) -> SharedDatasets:
    """In-memory build from a game list (tests / small experiments; no cache)."""
    payload = _accum_to_npz(_encode_games(games, legal_actions_fn, soft_targets))
    return _finalize_payloads([payload], train_frac=train_frac, val_frac=val_frac,
                              split_seed=split_seed, store_dtype=store_dtype,
                              verbose=verbose)


def _finalize_payloads(payloads, *, train_frac, val_frac, split_seed, store_dtype,
                       verbose) -> SharedDatasets:
    def cat(key):
        arrs = [p[key] for p in payloads]
        return np.concatenate(arrs, 0) if arrs else np.zeros(0)

    dt = np.float16 if store_dtype == "float16" else np.float32

    # ---- Value datasets ----
    from agricola.agents.nn.dataset import AgricolaValueDataset
    vX, vy, vseed = cat("value__X"), cat("value__y"), cat("value__seed")
    tr = _split_mask(vseed, split_seed, train_frac, val_frac, 0)
    va = _split_mask(vseed, split_seed, train_frac, val_frac, 1)
    te = _split_mask(vseed, split_seed, train_frac, val_frac, 2)
    # Shared input norm + value target std fit on the value TRAIN split only.
    Xtr = vX[tr].astype(np.float32)
    eps = np.float32(1e-6)
    mean = Xtr.mean(0, dtype=np.float64).astype(np.float32)
    std = Xtr.std(0, dtype=np.float64).astype(np.float32)
    std = np.where(std < eps, np.float32(1.0), std)
    tgt_std = float(vy[tr].std()) if vy[tr].size else 1.0
    if not np.isfinite(tgt_std) or tgt_std < 1e-9:
        tgt_std = 1.0
    input_stats = NormStats(input_mean=mean, input_std=std, target_std=tgt_std,
                            encoding_version=ENCODING_VERSION, target_mode="margin")
    value = tuple(
        AgricolaValueDataset(vX[m].astype(dt), (vy[m] / tgt_std).astype(np.float32))
        for m in (tr, va, te)
    )

    # ---- Fixed-head datasets ----
    fixed, sizes = {}, {"value": tuple(len(d) for d in value)}
    for n in _FIXED_NAMES:
        X, t = cat(f"fixed__{n}__X"), cat(f"fixed__{n}__t")
        m_, pi = cat(f"fixed__{n}__m"), cat(f"fixed__{n}__pi")
        won, seed = cat(f"fixed__{n}__won"), cat(f"fixed__{n}__seed")
        masks = tuple(_split_mask(seed, split_seed, train_frac, val_frac, w) for w in (0, 1, 2))
        fixed[n] = tuple(
            AgricolaPolicyDataset(X[mm].astype(dt), t[mm], m_[mm],
                                  np.ones(int(mm.sum()), np.float32), won[mm], pi[mm])
            for mm in masks
        )
        sizes[f"fixed:{n}"] = tuple(len(d) for d in fixed[n])

    # ---- Pointer-head datasets ----
    pointer, pointer_cand_norm = {}, {}
    for n in _POINTER_NAMES:
        state = cat(f"ptr__{n}__state")
        offsets_parts = [p[f"ptr__{n}__offsets"] for p in payloads]
        cand = cat(f"ptr__{n}__cand")
        pi = cat(f"ptr__{n}__pi")
        pos, won, seed = cat(f"ptr__{n}__pos"), cat(f"ptr__{n}__won"), cat(f"ptr__{n}__seed")
        # Rebuild global offsets by concatenating per-dir candidate blocks.
        per_dir_counts = [np.diff(o) for o in offsets_parts]
        counts = np.concatenate(per_dir_counts) if per_dir_counts else np.zeros(0, np.int64)
        offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        # Fit candidate norm on TRAIN rows' candidates.
        trm = _split_mask(seed, split_seed, train_frac, val_frac, 0)
        if trm.any():
            tr_rows = np.where(trm)[0]
            tr_cand = np.concatenate([cand[offsets[i]:offsets[i + 1]] for i in tr_rows], 0) \
                if tr_rows.size else np.zeros((0, POINTER_HEADS[n].candidate_dim), np.float32)
            cmean = tr_cand.mean(0).astype(np.float32) if tr_cand.size else \
                np.zeros(POINTER_HEADS[n].candidate_dim, np.float32)
            cstd = tr_cand.std(0).astype(np.float32) if tr_cand.size else \
                np.ones(POINTER_HEADS[n].candidate_dim, np.float32)
        else:
            cmean = np.zeros(POINTER_HEADS[n].candidate_dim, np.float32)
            cstd = np.ones(POINTER_HEADS[n].candidate_dim, np.float32)
        pointer_cand_norm[n] = (cmean, cstd)
        # Per-split pointer datasets (slice rows, rebuild local offsets/cand).
        split_ds = []
        for w in (0, 1, 2):
            rm = _split_mask(seed, split_seed, train_frac, val_frac, w)
            rows = np.where(rm)[0]
            if rows.size == 0:
                split_ds.append(AgricolaPointerDataset(
                    np.zeros((0, ENCODED_DIM), np.float32),
                    np.zeros((0, POINTER_HEADS[n].candidate_dim), np.float32),
                    np.zeros(1, np.int64), np.zeros(0, np.int64),
                    np.zeros(0, np.float32), np.zeros(0, np.float32),
                    np.zeros(0, np.float32)))
                continue
            blocks = [cand[offsets[i]:offsets[i + 1]] for i in rows]
            pi_blocks = [pi[offsets[i]:offsets[i + 1]] for i in rows]
            local_counts = np.array([b.shape[0] for b in blocks], np.int64)
            local_off = np.concatenate([[0], np.cumsum(local_counts)]).astype(np.int64)
            split_ds.append(AgricolaPointerDataset(
                state[rows].astype(np.float32),
                np.concatenate(blocks, 0).astype(np.float32),
                local_off, pos[rows].astype(np.int64),
                np.ones(rows.size, np.float32), won[rows].astype(np.float32),
                np.concatenate(pi_blocks, 0).astype(np.float32)))
        pointer[n] = tuple(split_ds)
        sizes[f"ptr:{n}"] = tuple(len(d) for d in pointer[n])

    if verbose:
        print(f"Shared datasets built. value={sizes['value']}")
        for k in sizes:
            if k != "value":
                print(f"  {k}: {sizes[k]}")
    return SharedDatasets(value=value, fixed=fixed, pointer=pointer,
                          input_stats=input_stats, pointer_cand_norm=pointer_cand_norm,
                          sizes=sizes)
