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

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


def _thin_keep(n, frac, salt):
    """Deterministic boolean keep-mask: ~`frac` of `n` rows, seeded reproducibly
    by (`salt`, `n`) — so every key of a given (chunk, task) gets the SAME mask
    (rows stay aligned across X/target/seed) and the build is reproducible across
    processes (crc32, not the salted `hash()`). Returns None for keep-all."""
    if frac is None or frac >= 1.0 or n == 0:
        return None
    seed = zlib.crc32(str(salt).encode()) ^ (int(n) & 0xFFFFFFFF)
    return np.random.default_rng(seed).random(n) < frac

from agricola.agents.nn.dataset import (
    NormStats,
    _iter_worker_pickles,
    _seed_split,
)
from agricola.agents.nn.encoder import (
    ENCODER_V2,
    ENCODING_VERSION,
    EncoderSpec,
    begging_margin,
)
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


def _encode_games(games, legal_actions_fn, soft_targets: bool,
                  encoder: EncoderSpec) -> _Accum:
    """One pass: emit value + fixed + pointer rows for a list of games.

    Value targets are begging-stripped when `encoder.strip_begging` (the
    candidate dropped begging from its features): target = margin − the current
    begging margin at that state, added back deterministically at inference."""
    acc = _Accum()
    fixed_heads = [HEADS[n] for n in _FIXED_NAMES]
    pointer_heads = [POINTER_HEADS[n] for n in _POINTER_NAMES]

    def bstrip(state, persp: int) -> float:
        return begging_margin(state, persp) if encoder.strip_begging else 0.0

    for g in games:
        for snap in g.decisions:
            s = snap.state
            d = snap.decider_idx
            x_d = encoder.encode(s, d).astype(np.float32)        # decider view
            x_o = encoder.encode(s, 1 - d).astype(np.float32)    # other view
            # value rows: both perspectives (begging-stripped target)
            acc.add_value(x_d, _margin_from(g, d) - bstrip(s, d), g.seed)
            acc.add_value(x_o, _margin_from(g, 1 - d) - bstrip(s, 1 - d), g.seed)
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
        # terminal value rows (begging-stripped target)
        ts = g.terminal_state
        acc.add_value(encoder.encode(ts, 0).astype(np.float32),
                      _margin_from(g, 0) - bstrip(ts, 0), g.seed)
        acc.add_value(encoder.encode(ts, 1).astype(np.float32),
                      _margin_from(g, 1) - bstrip(ts, 1), g.seed)
    return acc


def _accum_to_npz(acc: _Accum, dim: int) -> dict:
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
                                 else np.zeros((0, dim), np.float16))
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
                                   else np.zeros((0, dim), np.float16))
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


def _chunk_dir(run_dir: Path, encoder: EncoderSpec) -> Path:
    """Per-pickle chunk cache dir, keyed by the encoder tag so v2 and candidate
    caches never collide. One npz per source pickle (NOT one giant npz per run
    dir) so peak encode memory is bounded to a single pickle — the OOM fix (a
    whole run dir is ~6M value rows ≈ 4+ GB held at once)."""
    return Path(run_dir) / f"shared_{encoder.tag}_chunks"


def _roster_sentinel(run_dir: Path, encoder: EncoderSpec) -> Path:
    """The roster-id marker: identifies WHICH head roster the chunks belong to.
    Written when a (run_dir, encoder) cache is first claimed, so a resume can tell
    same-roster partial chunks (reusable) from stale chunks of an old roster."""
    return _chunk_dir(run_dir, encoder) / "roster.txt"


def _cache_complete(run_dir: Path, encoder: EncoderSpec) -> bool:
    """Complete ⟺ the roster matches AND every expected chunk file is present
    (one per worker pickle, by stable sorted index). Defining completeness as
    "all chunks on disk" — rather than an end-of-run sentinel — is what makes the
    cache truly resumable: a kill mid-encode just leaves fewer chunks, and the
    next run fills only the gaps. Backward-compatible with legacy caches (which
    wrote roster.txt at the end + have all chunks)."""
    cd = _chunk_dir(run_dir, encoder)
    roster = _roster_sentinel(run_dir, encoder)
    try:
        if not (roster.exists() and roster.read_text() == _ROSTER_TAG):
            return False
        n = len(list(_iter_worker_pickles([run_dir])))
        return n > 0 and all((cd / f"chunk_{i:05d}.npz").exists() for i in range(n))
    except Exception:
        return False


def _encode_one_chunk(pkl, chunk_path, legal_actions_fn, soft_targets,
                      encoder: EncoderSpec) -> str:
    """Encode one worker pickle -> one chunk npz (atomic write). Returns the
    chunk path. The unit of work for both the serial loop and the parallel pool;
    self-contained so it is picklable as a `multiprocessing` task (spawn-safe —
    module-level, args are paths + a frozen `EncoderSpec` + module-level fns)."""
    games = load_game_records(Path(pkl))
    payload = _accum_to_npz(
        _encode_games(games, legal_actions_fn, soft_targets, encoder), encoder.dim)
    del games
    cp = Path(chunk_path)
    tmp = cp.with_name(cp.name + ".tmp.npz")
    np.savez(tmp, **payload)
    tmp.replace(cp)
    return str(cp)


def _encode_one_chunk_task(task):
    """`Pool` adapter (single positional arg) for `_encode_one_chunk`."""
    return _encode_one_chunk(*task)


def _load_or_encode_run_dir(run_dir: Path, legal_actions_fn, soft_targets, use_cache,
                            verbose, encoder: EncoderSpec, n_workers: int = 1,
                            max_games=None) -> list:
    """Return the per-pickle chunk SOURCES for one run dir, in stable sorted
    order. With the cache (the production path) each source is a chunk-npz
    **Path** — NOT a loaded dict — so `_finalize_payloads` can stream the chunks
    lazily from disk and never hold the whole run dir's arrays resident (the
    57k-build OOM fix: loading all 579 chunks into RAM up front was ~6-8 GB
    before finalize even ran). Without the cache (tests / no-disk) each source is
    an in-memory payload dict (small). `_finalize_payloads` handles both via
    `_src_load`. Each pickle is encoded to its own chunk npz — so encode peak
    memory is one pickle.

    `n_workers > 1` fans the per-pickle encodes across a process pool (each
    pickle→chunk is independent; chunk indices are fixed by the stable sorted
    pickle order, so the result is identical to the serial path). The parallel
    path requires `use_cache` (chunks land on disk); it falls back to serial
    otherwise.

    **Truly resumable.** A kill mid-encode leaves the finished chunk npzs on
    disk; the next run keeps every same-roster chunk and encodes ONLY the
    missing indices (completeness = all chunks present, see `_cache_complete`).
    Stale chunks from a *different* head roster are cleared before resuming."""
    cd = _chunk_dir(run_dir, encoder)
    pkls = list(_iter_worker_pickles([run_dir]))

    # Optional per-run-dir game cap (ad-hoc, for size-controlled experiments):
    # keep the first ~max_games games by truncating the (stable-sorted) pickle
    # list. Estimate games-per-pickle from the first pickle (one cheap load),
    # since chunks are 1:1 with pickles. A cap bypasses the full-dir cache fast
    # path below (it would return ALL chunks) but still resumes per-chunk.
    if max_games is not None and pkls:
        per = len(load_game_records(pkls[0])) or 1
        keep = min(len(pkls), max(1, -(-max_games // per)))
        if verbose:
            print(f"  max_games={max_games}: using first {keep}/{len(pkls)} "
                  f"pickles (~{keep * per} games) of {run_dir.name}", flush=True)
        pkls = pkls[:keep]

    if max_games is None and use_cache and _cache_complete(run_dir, encoder):
        if verbose:
            print(f"  shared cache HIT: {run_dir.name} [{encoder.tag}]", flush=True)
        return sorted(cd.glob("chunk_*.npz"))  # Paths — streamed lazily by _finalize

    # --- No-cache: simple in-memory serial (no disk, no resume) ---
    if not use_cache:
        if verbose:
            print(f"  shared cache MISS: encoding {run_dir.name} [{encoder.tag}] "
                  f"(no cache)", flush=True)
        payloads: list[dict] = []
        for i, pkl in enumerate(pkls):
            games = load_game_records(pkl)
            payloads.append(_accum_to_npz(
                _encode_games(games, legal_actions_fn, soft_targets, encoder), encoder.dim))
            del games
            if verbose and i % 25 == 0:
                print(f"    encoded chunk {i} ({pkl.name})", flush=True)
        return payloads

    # --- Cached path (resume-aware) ---
    cd.mkdir(parents=True, exist_ok=True)
    roster = _roster_sentinel(run_dir, encoder)
    existing = roster.read_text() if roster.exists() else None
    if existing != _ROSTER_TAG:
        # Absent or stale (different head roster) → drop any old chunks, claim it.
        for old in cd.glob("chunk_*.npz"):
            old.unlink()
        roster.write_text(_ROSTER_TAG)
    # Encode only the chunks not already on disk (the resume).
    todo = [(i, pkl) for i, pkl in enumerate(pkls)
            if not (cd / f"chunk_{i:05d}.npz").exists()]
    cached = len(pkls) - len(todo)
    if verbose:
        verb = "resuming" if (cached and existing == _ROSTER_TAG) else "encoding"
        print(f"  shared cache MISS: {verb} {run_dir.name} [{encoder.tag}] "
              f"({cached}/{len(pkls)} cached, {len(todo)} to do, "
              f"{n_workers} worker(s))", flush=True)

    if n_workers > 1 and len(todo) > 1:
        from multiprocessing import Pool
        tasks = [(str(pkl), str(cd / f"chunk_{i:05d}.npz"),
                  legal_actions_fn, soft_targets, encoder) for i, pkl in todo]
        done = 0
        with Pool(min(n_workers, len(tasks))) as pool:
            for _ in pool.imap_unordered(_encode_one_chunk_task, tasks):
                done += 1
                if verbose and (done % 25 == 0 or done == len(tasks)):
                    print(f"    encoded {done}/{len(tasks)} (this run)", flush=True)
    else:
        for k, (i, pkl) in enumerate(todo):
            _encode_one_chunk(pkl, cd / f"chunk_{i:05d}.npz",
                              legal_actions_fn, soft_targets, encoder)
            if verbose and k % 25 == 0:
                print(f"    encoded {k}/{len(todo)} (this run, {pkl.name})", flush=True)

    # Return exactly the chunks for the (possibly capped) pickle list — chunks are
    # 0..len(pkls)-1 by construction, so this equals sorted(glob) when uncapped but
    # excludes any stale higher-index chunks left by an earlier uncapped run.
    chunk_paths = [cd / f"chunk_{i:05d}.npz" for i in range(len(pkls))]
    if verbose:
        print(f"  {len(chunk_paths)} chunks in {cd.name}/", flush=True)
    return chunk_paths  # Paths — streamed lazily by _finalize


# ---------------------------------------------------------------------------
# Bundle + build
# ---------------------------------------------------------------------------


def _src_load(src, key):
    """Read one array for `key` from a chunk source — an in-memory payload dict
    (returns the stored array) or a chunk-npz Path (lazily loads ONLY that key,
    so a single chunk's worth is resident, not the whole run dir). None if the
    key is absent."""
    if isinstance(src, dict):
        return src.get(key)
    with np.load(src, allow_pickle=False) as z:
        return z[key] if key in z.files else None


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
    encoder: EncoderSpec = ENCODER_V2,
    legal_actions_fn=full_legal_actions,
    soft_targets: bool = True,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    store_dtype: str = "float16",
    use_cache: bool = True,
    n_workers: int = 1,
    snapshot_keep=None,
    max_games=None,
    verbose: bool = True,
) -> SharedDatasets:
    """One-pass (cached) build of the joint value+policy datasets. Defaults to
    **full** legality (the self-play data was generated under it, so π's support
    stays inside every head's mask). `encoder` selects the feature schema (v2 by
    default; a candidate re-encodes the SAME raw games into its own cache).
    `n_workers > 1` fans the one-time per-pickle encode across a process pool.

    `snapshot_keep` thins rows (a seeded keep-fraction per chunk) to cut RAM AND
    within-game autocorrelation (consecutive snapshots are near-duplicate; see the
    `snap6th`/`snap_half` data-efficiency findings). It is None (keep all), a
    single float (uniform), or a per-run-dir list aligned with `run_dirs` — e.g.
    `[1/6, 1/6, 1/6, 1/6, 1/6, 1/2]` keeps 1/6 of the old dirs and 1/2 of the
    newest. Value + fixed-head rows are thinned; the small pointer heads are kept
    whole (ragged, negligible RAM)."""
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]
    if snapshot_keep is None or isinstance(snapshot_keep, (int, float)):
        keeps = [1.0 if snapshot_keep is None else float(snapshot_keep)] * len(run_dirs)
    else:
        keeps = [float(k) for k in snapshot_keep]
        assert len(keeps) == len(run_dirs), "snapshot_keep must align with run_dirs"

    # Gather the per-pickle chunk SOURCES as (src, keep_frac) pairs, flattened
    # across dirs in stable order. With the cache each src is a chunk-npz Path
    # (streamed lazily); without it, an in-memory payload dict. _finalize handles
    # both, and applies each source's keep-fraction when copying its rows.
    sources: list = []
    for rd, keep in zip(run_dirs, keeps):
        for src in _load_or_encode_run_dir(rd, legal_actions_fn, soft_targets,
                                           use_cache, verbose, encoder, n_workers,
                                           max_games=max_games):
            sources.append((src, keep))
    return _finalize_payloads(sources, encoder=encoder, train_frac=train_frac,
                              val_frac=val_frac, split_seed=split_seed,
                              store_dtype=store_dtype, verbose=verbose)


def build_shared_datasets_from_games(
    games, *, encoder: EncoderSpec = ENCODER_V2, legal_actions_fn=full_legal_actions,
    soft_targets: bool = True, train_frac: float = 0.8, val_frac: float = 0.1,
    split_seed: int = 0, store_dtype: str = "float32", verbose: bool = False,
) -> SharedDatasets:
    """In-memory build from a game list (tests / small experiments; no cache)."""
    payload = _accum_to_npz(
        _encode_games(games, legal_actions_fn, soft_targets, encoder), encoder.dim)
    return _finalize_payloads([(payload, 1.0)], encoder=encoder, train_frac=train_frac,
                              val_frac=val_frac, split_seed=split_seed,
                              store_dtype=store_dtype, verbose=verbose)


def _finalize_payloads(sources, *, encoder: EncoderSpec, train_frac, val_frac,
                       split_seed, store_dtype, verbose) -> SharedDatasets:
    """Build the per-task datasets from a list of chunk `sources` (npz Paths or
    in-memory dicts), streaming each chunk lazily so the whole run dir's arrays
    are never resident at once. The big value tensor is built DIRECTLY into its
    three per-split arrays (no combined `vX` that would then double when sliced),
    bounding the value-stage peak to ~1× the value data + one chunk."""

    def _splits_of(seeds):
        """Per-row train/val/test split (0/1/2). Dedups by unique seed (a game's
        rows share one seed) — same assignment as `_split_mask`, just faster."""
        if seeds.shape[0] == 0:
            return np.zeros(0, np.int8)
        uniq, inv = np.unique(seeds, return_inverse=True)
        sp = np.fromiter(
            (_seed_split(int(s), split_seed, train_frac, val_frac) for s in uniq),
            dtype=np.int8, count=uniq.shape[0])
        return sp[inv]

    def cat(key):
        """Concatenate `sources[*][key]` into one array, loading each chunk's
        array lazily and freeing it after the copy. Peak = the result + one
        chunk. Used for the SMALL per-head arrays; the big value tensor is
        streamed straight into its splits instead (see below). Applies each
        source's snapshot keep-fraction — EXCEPT for ragged pointer keys (`ptr__`,
        whose row count is candidate-block offsets, not snapshots), which are kept
        whole. The keep-mask is seeded by (src, n), so every key of a (chunk, head)
        is thinned identically and stays aligned."""
        thin = not key.startswith("ptr__")

        def _load(src, frac):
            a = _src_load(src, key)
            if a is None:
                return None
            if thin:
                mask = _thin_keep(a.shape[0], frac, src)
                if mask is not None:
                    a = a[mask]
            return a

        total, tail, dtype0 = 0, None, None
        for src, frac in sources:
            a = _load(src, frac)
            if a is None:
                continue
            total += a.shape[0]
            if tail is None:
                tail, dtype0 = tuple(a.shape[1:]), a.dtype
            del a
        if dtype0 is None:
            return np.zeros(0)
        out = np.empty((total,) + tail, dtype=dtype0)
        off = 0
        for src, frac in sources:
            a = _load(src, frac)
            if a is None:
                continue
            out[off:off + a.shape[0]] = a
            off += a.shape[0]
            del a
        return out

    dt = {"float16": np.float16, "int8": np.int8}.get(store_dtype, np.float32)
    D = encoder.dim
    _clip8 = dt == np.int8  # int8: features are integer-valued; cap to int8 range

    def _to_store(a):
        """Cast a (float, integer-valued) feature array to the store dtype. For
        int8, clip to [-128,127] first — every encoder feature is an exact
        integer (verified), and only ~0.25% of states have pasture_cap_0 > 127,
        which is harmless to cap. Without the clip, the float→int8 assignment
        would wrap those few values instead of saturating."""
        return np.clip(a, -128, 127).astype(dt) if _clip8 else a.astype(dt)

    # ---- Value datasets (streamed straight into per-split arrays) ----
    # Never materialize a combined `vX`: that 4+ GB array, sliced by boolean mask
    # into train/val/test, would momentarily double (vX + its split copies) and
    # overflow the 8 GB box at 57k. Instead: pre-scan the (tiny) per-row seeds to
    # size each split, pre-allocate the three arrays, then copy each chunk's rows
    # into the right split and free the chunk. Peak = the three split arrays
    # (== the value data, ~4 GB) + one chunk.
    from agricola.agents.nn.dataset import AgricolaValueDataset
    # Thinning: dropped rows get split label -1 (excluded from every split). The
    # keep-mask is seeded by (src, n) — identical in the pre-scan and fill passes,
    # so sizes and copies stay consistent.
    def _value_splits(src, frac, seed):
        sp = _splits_of(seed)
        mask = _thin_keep(seed.shape[0], frac, src)
        return np.where(mask, sp, np.int8(-1)) if mask is not None else sp

    vn = [0, 0, 0]
    for src, frac in sources:
        seed = _src_load(src, "value__seed")
        if seed is None or seed.shape[0] == 0:
            continue
        sp = _value_splits(src, frac, seed)
        for w in (0, 1, 2):
            vn[w] += int((sp == w).sum())
    vX = [np.empty((vn[w], D), dt) for w in (0, 1, 2)]
    vy = [np.empty(vn[w], np.float32) for w in (0, 1, 2)]
    voff = [0, 0, 0]
    for src, frac in sources:
        seed = _src_load(src, "value__seed")
        if seed is None or seed.shape[0] == 0:
            continue
        X, y = _src_load(src, "value__X"), _src_load(src, "value__y")
        sp = _value_splits(src, frac, seed)
        for w in (0, 1, 2):
            m = sp == w
            k = int(m.sum())
            if k:
                # int8: clip before the (saturating-less) assignment; else direct.
                vX[w][voff[w]:voff[w] + k] = np.clip(X[m], -128, 127) if _clip8 else X[m]
                vy[w][voff[w]:voff[w] + k] = y[m]
                voff[w] += k
        del X, y, seed, sp

    # Shared input norm fit on the value TRAIN split only — STREAMED in float64
    # row-blocks so we never materialize a full float32 copy of the train X
    # (~6.6 GB at 57k, which would overflow the box and thrash in `.std()`).
    # Two-pass population mean/std (matches `ndarray.std(ddof=0)`); only one
    # BLOCK×D float64 block is live at a time (~0.27 GB).
    eps = np.float32(1e-6)
    vX_tr, vy_tr = vX[0], vy[0]
    n_tr = vX_tr.shape[0]
    _BLOCK = 200_000
    s1 = np.zeros(D, np.float64)
    for i in range(0, n_tr, _BLOCK):
        s1 += vX_tr[i:i + _BLOCK].astype(np.float64).sum(0)
    mean64 = s1 / max(n_tr, 1)
    s2 = np.zeros(D, np.float64)
    for i in range(0, n_tr, _BLOCK):
        blk = vX_tr[i:i + _BLOCK].astype(np.float64)
        blk -= mean64
        s2 += np.einsum("ij,ij->j", blk, blk)  # fused col sum-of-squares (no blk² temp)
    mean = mean64.astype(np.float32)
    std = np.sqrt(s2 / max(n_tr, 1)).astype(np.float32)
    std = np.where(std < eps, np.float32(1.0), std)
    tgt_std = float(vy_tr.std()) if vy_tr.size else 1.0
    if not np.isfinite(tgt_std) or tgt_std < 1e-9:
        tgt_std = 1.0
    input_stats = NormStats(input_mean=mean, input_std=std, target_std=tgt_std,
                            encoding_version=ENCODING_VERSION, target_mode="margin",
                            encoding_tag=encoder.tag)
    value = tuple(
        AgricolaValueDataset(vX[w], (vy[w] / tgt_std).astype(np.float32))
        for w in (0, 1, 2)
    )
    del vX, vy, vX_tr, vy_tr  # arrays now baked into the datasets (torch holds the buffers)

    # ---- Fixed-head datasets ----
    fixed, sizes = {}, {"value": tuple(len(d) for d in value)}
    for n in _FIXED_NAMES:
        X, t = cat(f"fixed__{n}__X"), cat(f"fixed__{n}__t")
        m_, pi = cat(f"fixed__{n}__m"), cat(f"fixed__{n}__pi")
        won, seed = cat(f"fixed__{n}__won"), cat(f"fixed__{n}__seed")
        masks = tuple(_split_mask(seed, split_seed, train_frac, val_frac, w) for w in (0, 1, 2))
        fixed[n] = tuple(
            AgricolaPolicyDataset(_to_store(X[mm]), t[mm], m_[mm],
                                  np.ones(int(mm.sum()), np.float32), won[mm], pi[mm])
            for mm in masks
        )
        sizes[f"fixed:{n}"] = tuple(len(d) for d in fixed[n])

    # ---- Pointer-head datasets ----
    pointer, pointer_cand_norm = {}, {}
    for n in _POINTER_NAMES:
        state = cat(f"ptr__{n}__state")
        offsets_parts = [o for o in (_src_load(src, f"ptr__{n}__offsets") for src, _ in sources)
                         if o is not None]
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
                    np.zeros((0, encoder.dim), np.float32),
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
