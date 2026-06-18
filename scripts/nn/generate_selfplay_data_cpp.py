"""C++ MCTS self-play training-data generator (DATA_VERSION 3).

The C++ sibling of `generate_selfplay_data.py`. Instead of driving a
shared-tree Python `MCTSAgent` per game, this runs the compiled C++
self-play binary (`cpp/build/selfplay --mcts ...`) once per game — each
process plays ONE shared-tree MCTS-vs-MCTS game (NN value leaf + combined
behavioral-cloning policy, PUCT / FLATTEN / full legality) and writes an
`agricola-cpp-trace-v1` JSON trace. We then replay that trace through the
*unchanged Python engine* via `agricola.agents.nn.trace_replay.replay_trace`,
which rebuilds a `GameRecord` with π (`visit_distribution`) + `root_value`
populated on each non-singleton decision.

The on-disk OUTPUT is BYTE-FOR-BYTE the same format as the Python generator:
a run dir `<out-dir>/` with `games/worker_NN_cNNN.pkl` (each a chunked
`list[GameRecord]`) + `metadata.json`. So `build_datasets` / the training
pipeline consume it unchanged — the only difference from the Python generator
is `metadata.json["generator"] == "cpp"`.

Reuses the proven scaffold from `generate_training_data.py`
(`partition_plan`, `_write_pickle_atomic`, `_current_git_sha`, `_new_run_id`)
and the chunked-streaming worker shape from `generate_selfplay_data.py`.

Traces are written to a persistent `<out-dir>/traces/` dir, and each game's
trace is deleted only once its GameRecord is durably chunk-written. Two
consequences: (1) a run KILLED mid-generation (before any chunk is flushed)
RESUMES from the traces already on disk instead of regenerating them — every
game is always recoverable from either its chunk or its trace; (2) the
progress monitor reports real generation progress (chunks + trace files on
disk), so the log advances during phase-1 C++ generation rather than sitting
at 0 until the phase-2 replay.

GENERATION MODES (both produce byte-for-byte the same run-dir output):
  * BATCH (default): each pool worker launches ONE C++ subprocess that loads
    the NN weights once and plays its whole slice of games (`--game-idxs ...
    --base-seed B --out-dir <out-dir>/traces`), writing `trace_<i>.json` per
    game; the worker then replays each trace → GameRecord and chunk-writes.
    This removes the per-game ~0.15s weight-reload startup.
  * PER-GAME (`--per-game-process`): the OLD path — one C++ subprocess per
    game (reloads weights every game). Kept as the A/B baseline.

Usage:
    # Small smoke run
    ~/miniconda3/bin/python scripts/nn/generate_selfplay_data_cpp.py \\
        --n-games 8 --n-workers 4 --sims 64 \\
        --out-dir data/nn_training/runs/cpp_pipeline_smoke

    # Full run (resumes if --out-dir exists)
    ~/miniconda3/bin/python scripts/nn/generate_selfplay_data_cpp.py \\
        --n-games 5000 --n-workers 8 --sims 400 --chunk-size 100 \\
        --out-dir data/nn_training/runs/cpp_selfplay_5k
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass, replace as dc_replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.nn import DATA_VERSION  # noqa: E402
from agricola.agents.nn.trace_replay import replay_trace  # noqa: E402

# Reuse the heuristic generator's tested scaffolding.
sys.path.insert(0, str(ROOT / "scripts" / "nn"))
from generate_training_data import (  # noqa: E402
    _current_git_sha,
    _new_run_id,
    _write_pickle_atomic,
    partition_plan,
)

# Sentinel config paths recorded on each GameRecord (mirrors the Python
# self-play generator's "cpp_selfplay" convention via replay_trace defaults).
_CPP_CONFIG = "cpp_selfplay"


# ---------------------------------------------------------------------------
# Per-game work item + run spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GamePlan:
    """A single game's work item — game_idx + the seed handed to the binary."""

    game_idx: int
    seed: int


@dataclass(frozen=True)
class _Spec:
    selfplay_bin: str
    model_dir: str
    sims: int
    c_uct: float
    temperature: float
    chunk_size: int
    base_seed: int = 0
    prior_mix: float = 0.0
    select_by: str = "visits"  # "visits" (default) or "q"
    keep_traces: bool = False  # if True, never delete traces (keep as the root archive)
    # "batch" (one subprocess per worker-slice, one weight load) or
    # "per_game" (one subprocess per game — the A/B baseline). Default batch.
    generation_mode: str = "batch"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

# Shared per-game progress counter, bound in each pool worker via the Pool
# initializer; a parent monitor thread reads it to log live progress.
_PROGRESS_COUNTER = None


def _pool_init(counter) -> None:
    global _PROGRESS_COUNTER
    _PROGRESS_COUNTER = counter


def _completed_idxs_and_next_chunk(games_dir: Path, worker_id: int) -> tuple[set, int]:
    """Scan a worker's existing chunk files → (completed game_idxs, next chunk #)."""
    import pickle
    completed: set = set()
    chunks = sorted(games_dir.glob(f"worker_{worker_id:02d}_c*.pkl"))
    for f in chunks:
        with f.open("rb") as fh:
            for rec in pickle.load(fh):
                completed.add(rec.game_idx)
    return completed, len(chunks)


def _bin_path(spec: _Spec) -> Path:
    bin_path = Path(spec.selfplay_bin)
    if not bin_path.is_absolute():
        bin_path = ROOT / bin_path
    return bin_path


def _replay_trace_file(spec: _Spec, *, game_idx: int, trace_path: Path):
    """Load one C++ trace file → replay → GameRecord (the shared replay step).

    Identical in both modes so the on-disk GameRecord is byte-for-byte the same
    regardless of how the trace was generated. Raises on read / replay error.
    """
    trace = json.loads(trace_path.read_text())
    return replay_trace(
        trace,
        game_idx=game_idx,
        p0_config_path=_CPP_CONFIG,
        p1_config_path=_CPP_CONFIG,
        p0_temperature=spec.temperature,
        p1_temperature=spec.temperature,
    )


def _trace_path(traces_dir: Path, game_idx: int) -> Path:
    return traces_dir / f"trace_{game_idx}.json"


def _trace_complete(path: Path) -> bool:
    """True iff `path` holds a fully-parseable trace.

    The resume predicate: a trace that exists AND parses can be replayed
    without regenerating it. A partially-written file left behind by a killed
    binary fails to parse → treated as missing → regenerated. So resume never
    trusts a truncated trace.
    """
    if not path.exists():
        return False
    try:
        with path.open() as fh:
            json.load(fh)
        return True
    except (OSError, ValueError):
        return False


def _run_batch_games(spec: _Spec, *, game_idxs: list[int], out_dir: Path):
    """Run ONE C++ subprocess that plays `game_idxs` into `out_dir`.

    Writes `trace_<i>.json` per game into the SHARED, PERSISTENT `out_dir`
    (game idxs are globally unique across workers, so files never collide).
    Deletes nothing — traces persist until the owning game's GameRecord is
    durably chunked (worker `_flush`) or the whole run completes cleanly
    (`generate`). That persistence is exactly what makes a killed run resumable.

    Returns (written_idxs, proc) — `written_idxs` are the idxs whose trace file
    now exists, regardless of exit code (a partial exit still salvages what it
    wrote). Raises only on TOTAL failure: a nonzero exit that produced ZERO of
    this call's traces.
    """
    bin_path = _bin_path(spec)
    idxs_arg = ",".join(str(i) for i in game_idxs)
    cmd = [
        str(bin_path),
        "--mcts",
        "--game-idxs", idxs_arg,
        "--base-seed", str(spec.base_seed),
        "--sims", str(spec.sims),
        "--c-uct", str(spec.c_uct),
        "--temperature", str(spec.temperature),
        "--prior-mix", str(spec.prior_mix),
        "--select-by", spec.select_by,
        "--model-dir", spec.model_dir,
        "--out-dir", str(out_dir),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    written = {i for i in game_idxs if _trace_path(out_dir, i).exists()}
    if proc.returncode != 0 and not written:
        raise RuntimeError(
            f"selfplay batch exited {proc.returncode} with no traces "
            f"(idxs[0:5]={game_idxs[:5]}..., base_seed={spec.base_seed}). "
            f"stderr:\n{proc.stderr.strip()}"
        )
    return written, proc


def _generate_traces(spec: _Spec, items: list[dict], traces_dir: Path):
    """Ensure every item in `items` has a complete trace in `traces_dir`.

    Items whose trace already exists and parses are SKIPPED (the resume path);
    the rest are generated by the C++ binary — one subprocess for the whole
    missing set in "batch" mode, one per game in "per_game" mode.

    Returns (gen_failed, errored, gen_time, n_generated):
      * gen_failed  — set of game_idxs whose trace is still missing afterward.
      * errored     — list of (game_idx, message) for generation failures.
      * gen_time    — total wall spent generating (for the timing report).
      * n_generated — count of newly written traces (to amortize `gen_time`).
    """
    need = [it for it in items
            if not _trace_complete(_trace_path(traces_dir, it["game_idx"]))]
    gen_failed: set = set()
    errored: list[tuple[int, str]] = []
    gen_time = 0.0
    if not need:
        return gen_failed, errored, gen_time, 0

    if spec.generation_mode == "per_game":
        for it in need:
            gi = it["game_idx"]
            t0 = time.perf_counter()
            try:
                written, _ = _run_batch_games(spec, game_idxs=[gi], out_dir=traces_dir)
            except Exception as exc:
                errored.append((gi, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
                gen_failed.add(gi)
                continue
            gen_time += time.perf_counter() - t0
            if gi not in written:
                gen_failed.add(gi)
                errored.append((gi, f"per-game process did not write trace_{gi}.json"))
    else:  # "batch": ONE subprocess for the whole missing slice (one NN load)
        idxs = [it["game_idx"] for it in need]
        t0 = time.perf_counter()
        try:
            written, proc = _run_batch_games(spec, game_idxs=idxs, out_dir=traces_dir)
        except Exception as exc:
            # Total batch failure (no traces produced) → mark every idx errored.
            msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            for gi in idxs:
                gen_failed.add(gi)
                errored.append((gi, msg))
            return gen_failed, errored, gen_time, 0
        gen_time += time.perf_counter() - t0
        for gi in idxs:
            if gi not in written:  # partial exit skipped this one
                gen_failed.add(gi)
                errored.append((
                    gi,
                    f"batch process did not write trace_{gi}.json "
                    f"(exit={proc.returncode}); stderr:\n{proc.stderr.strip()}",
                ))

    return gen_failed, errored, gen_time, len(need) - len(gen_failed)


def _worker(args: dict) -> dict:
    worker_id: int = args["worker_id"]
    games_dir = Path(args["games_dir"])
    traces_dir = Path(args["traces_dir"])
    plan_slice: list[dict] = args["plan_slice"]   # _GamePlan items as dicts
    spec: _Spec = args["spec"]

    completed, next_chunk = _completed_idxs_and_next_chunk(games_dir, worker_id)

    buffer: list = []
    chunk_idxs: list[int] = []    # game_idxs in `buffer` (for trace cleanup on flush)
    per_game_times: list[float] = []
    errored: list[tuple[int, str]] = []
    n_completed = 0
    next_chunk_box = [next_chunk]

    def _flush() -> None:
        nonlocal buffer, chunk_idxs
        if not buffer:
            return
        path = games_dir / f"worker_{worker_id:02d}_c{next_chunk_box[0]:03d}.pkl"
        _write_pickle_atomic(path, buffer)
        next_chunk_box[0] += 1
        # The GameRecords are now durably on disk, so their traces are
        # redundant — drop them to keep the traces dir bounded. Until this
        # flush each game was recoverable from its trace; after it, from the
        # chunk. So a kill at ANY moment leaves every game recoverable.
        # With --keep-traces we instead KEEP them as the permanent root archive
        # (games replay from traces ~instantly; traces alone cost hours to regen).
        if not spec.keep_traces:
            for gi in chunk_idxs:
                _trace_path(traces_dir, gi).unlink(missing_ok=True)
        buffer = []
        chunk_idxs = []

    def _record(rec, game_idx: int) -> None:
        nonlocal n_completed
        buffer.append(rec)
        chunk_idxs.append(game_idx)
        n_completed += 1
        if _PROGRESS_COUNTER is not None:
            with _PROGRESS_COUNTER.get_lock():
                _PROGRESS_COUNTER.value += 1
        if len(buffer) >= spec.chunk_size:
            _flush()

    # Remaining (post-resume) work, in plan order. Skipping completed idxs here
    # keeps the game order — and thus the chunk packing — identical regardless
    # of resume.
    remaining = [it for it in plan_slice if it["game_idx"] not in completed]
    n_skipped = len(plan_slice) - len(remaining)

    # Phase 1: ensure every remaining game has a complete trace on disk —
    # generating the ones that don't, reusing any left by a killed prior run.
    gen_failed, gen_errored, gen_time, n_generated = _generate_traces(
        spec, remaining, traces_dir
    )
    errored.extend(gen_errored)
    # Replay is ~free; report generation cost as the per-game wall (amortized
    # over the batch in batch mode, exact in per-game mode).
    amortized = gen_time / max(1, n_generated)

    # Phase 2: replay each trace → GameRecord → chunk, in plan order.
    for item in remaining:
        gi = item["game_idx"]
        if gi in gen_failed:
            continue
        try:
            rec = _replay_trace_file(
                spec, game_idx=gi, trace_path=_trace_path(traces_dir, gi)
            )
        except Exception as exc:
            errored.append((gi, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
            continue
        per_game_times.append(amortized)
        _record(rec, gi)
    _flush()

    return {
        "worker_id": worker_id,
        "n_completed": n_completed,
        "n_skipped": n_skipped,
        "errored": errored,
        "per_game_times": per_game_times,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def generate(
    *,
    n_games: int,
    out_dir: Path | None,
    n_workers: int,
    base_seed: int | None = None,
    spec: _Spec,
    resume: bool = False,
    verbose: bool = True,
) -> dict:
    """Generate (or resume) a C++ self-play dataset. Returns final metadata.

    Resume semantics mirror the Python generators: a run dir that already
    contains a `metadata.json` is resumed (workers scan existing chunks and
    skip completed game_idxs). To guard against accidentally writing into a
    non-empty, non-resumable directory, we refuse unless it is a metadata.json
    run of THIS generator, or `--resume` is passed.
    """
    # ----- resolve run dir + resume status -----
    existing = None
    if out_dir is not None:
        run_dir = Path(out_dir)
        meta_path = run_dir / "metadata.json"
        is_resume = meta_path.exists()
        if is_resume:
            existing = json.loads(meta_path.read_text())
            run_id = existing.get("run_id", run_dir.name)
            if existing.get("generator") != "cpp" and not resume:
                raise SystemExit(
                    f"{run_dir} has a metadata.json from a DIFFERENT generator "
                    f"(generator={existing.get('generator')!r}). Refusing to mix "
                    f"outputs. Pass --resume to override (only if you know the "
                    f"chunk layout is compatible)."
                )
        else:
            # No metadata.json. Refuse to write into a non-empty dir unless
            # told to (never clobber unrelated data).
            if run_dir.exists() and any(run_dir.iterdir()) and not resume:
                raise SystemExit(
                    f"{run_dir} exists and is non-empty but has no metadata.json "
                    f"(not a resumable run of this generator). Pass --resume to "
                    f"write into it anyway, or choose a fresh --out-dir."
                )
            run_id = run_dir.name
    else:
        run_id = _new_run_id()
        run_dir = ROOT / "data" / "nn_training" / "runs" / run_id
        is_resume = False

    # ----- resolve base_seed (guard the base_seed=0 cross-run-collision footgun) -----
    if is_resume:
        stored = existing.get("base_seed") if existing else None
        if base_seed is None:
            base_seed = stored if stored is not None else 0  # legacy dirs: assume 0
        elif stored is not None and base_seed != stored:
            raise SystemExit(
                f"resume base_seed mismatch: {run_dir} was generated with "
                f"base_seed={stored}, but --base-seed={base_seed} was passed. "
                f"Omit --base-seed on resume (it is read from metadata) or pass "
                f"{stored} to match — a wrong base_seed misaligns game_idx→seed.")
    else:
        if base_seed is None:
            raise SystemExit(
                "Fresh run requires an explicit --base-seed. Pass a DISJOINT value "
                "per run so seed ranges never overlap (seed = base_seed + game_idx); "
                "overlap with a same-model+config run produces DUPLICATE games. "
                "E.g. --base-seed 1000000 (then 2000000, ...). Pass --base-seed 0 "
                "explicitly only if you truly want the 0-based range.")
        if base_seed == 0 and verbose:
            print("WARNING: --base-seed 0 — seeds 0..N-1 overlap any other "
                  "base_seed=0 run (duplicate games if model+config also match). "
                  "Prefer a disjoint base seed.", flush=True)

    games_dir = run_dir / "games"
    traces_dir = run_dir / "traces"
    games_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)

    # The batch C++ path computes seed = spec.base_seed + game_idx, so it MUST
    # equal the plan's base_seed. Pin it here so the two can never diverge
    # regardless of how the caller built `spec`.
    spec = dc_replace(spec, base_seed=base_seed)

    # ----- build the plan (mirror the Python seed scheme: seed = base+idx) -----
    plan = [_GamePlan(game_idx=i, seed=base_seed + i) for i in range(n_games)]
    slices = partition_plan(plan, n_workers)

    if verbose:
        print(f"Run dir: {run_dir}")
        print(f"  {n_games} games, {n_workers} workers, chunk_size={spec.chunk_size}, "
              f"resume={is_resume}")
        print(f"  C++ MCTS: bin={spec.selfplay_bin}, model_dir={spec.model_dir}, "
              f"sims={spec.sims}, c_uct={spec.c_uct}, T={spec.temperature}, "
              f"prior_mix={spec.prior_mix}, select_by={spec.select_by}, "
              f"keep_traces={spec.keep_traces}, mode={spec.generation_mode}, "
              f"data_version={DATA_VERSION}\n",
              flush=True)

    worker_args = [
        {"worker_id": w, "games_dir": str(games_dir), "traces_dir": str(traces_dir),
         "plan_slice": [asdict(p) for p in slices[w]], "spec": spec}
        for w in range(n_workers)
    ]

    # Games already chunked (full chunks only — the partial final chunk exists
    # only at completion), so progress can report the resumed baseline.
    baseline = len(list(games_dir.glob("worker_*_c*.pkl"))) * spec.chunk_size
    if baseline and verbose:
        print(f"  resuming: ~{baseline} games already on disk\n", flush=True)

    def _meta(status: str, completed_games: int, errored_games: list) -> dict:
        return {
            "run_id": run_id,
            "code_sha": _current_git_sha(),
            "host": platform.node(),
            "kind": "mcts_selfplay",
            "generator": "cpp",
            "status": status,
            "data_version": DATA_VERSION,
            "n_workers": n_workers,
            "base_seed": base_seed,
            "planned_games": n_games,
            "completed_games": completed_games,
            "errored_games": errored_games,
            "selfplay_bin": spec.selfplay_bin,
            "model_dir": spec.model_dir,
            "sims": spec.sims,
            "c_uct": spec.c_uct,
            "temperature": spec.temperature,
            "prior_mix": spec.prior_mix,
            "select_by": spec.select_by,
            "keep_traces": spec.keep_traces,
            "chunk_size": spec.chunk_size,
            "generation_mode": spec.generation_mode,
            "legality": "full", "fence_mode": "flatten", "cap_total_sims": True,
        }

    # Write metadata BEFORE launching workers so a run killed mid-generation
    # leaves a `metadata.json` marked generator="cpp" — the next invocation then
    # auto-resumes (reusing on-disk traces) without needing --resume. Rewritten
    # with final counts + status="complete" at the end.
    (run_dir / "metadata.json").write_text(
        json.dumps(_meta("in_progress", baseline, []), indent=2))

    t0 = time.perf_counter()
    if n_workers == 1:
        global _PROGRESS_COUNTER
        _PROGRESS_COUNTER = None
        results = [_worker(worker_args[0])]
    else:
        counter = mp.Value("i", 0)
        stop = threading.Event()

        def _monitor() -> None:
            # Progress is filesystem-derived so it tracks PHASE-1 C++ generation
            # in real time (the long pole), not just phase-2 replay: a game is
            # "done" once its trace exists OR it has been chunked. A flushed
            # chunk adds chunk_size to the chunk count and removes the same
            # number of traces, so `done` stays monotonic across the handoff.
            def _done() -> int:
                n_chunks = len(list(games_dir.glob("worker_*_c*.pkl")))
                n_traces = len(list(traces_dir.glob("trace_*.json")))
                return min(n_games, n_chunks * spec.chunk_size + n_traces)

            done0 = _done()   # this-run baseline (incl. any resumed traces)
            while not stop.wait(60.0):
                el = time.perf_counter() - t0
                done = _done()
                n_traces = len(list(traces_dir.glob("trace_*.json")))
                rate = (done - done0) / el if el > 0 else 0.0   # games/sec this run
                remaining = max(0, n_games - done)
                eta_h = remaining / rate / 3600 if rate > 0 else float("inf")
                print(f"  [progress] {done}/{n_games} games (~{100*done/n_games:.0f}%), "
                      f"{rate*60:.1f}/min this run, ETA {eta_h:.1f} h "
                      f"(traces on disk: {n_traces}, replayed this run: {counter.value})",
                      flush=True)

        mon = threading.Thread(target=_monitor, daemon=True)
        mon.start()
        try:
            with mp.Pool(processes=n_workers, initializer=_pool_init,
                         initargs=(counter,)) as pool:
                results = pool.map(_worker, worker_args)
        finally:
            stop.set()
            mon.join(timeout=1.0)
    elapsed = time.perf_counter() - t0

    all_times = [t for r in results for t in r["per_game_times"]]
    n_done = sum(r["n_completed"] for r in results)
    n_skip = sum(r["n_skipped"] for r in results)
    all_errored = []
    for r in results:
        for game_idx, msg in r["errored"]:
            all_errored.append({"game_idx": game_idx, "error": msg})

    meta = _meta("complete", n_done + n_skip, all_errored)
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    # On clean completion every GameRecord is durably chunked, so the persisted
    # traces are no longer needed — UNLESS --keep-traces asked to retain them as
    # the permanent root archive. (A killed run never reaches here, leaving the
    # traces on disk so the next invocation resumes from them instead of
    # regenerating.)
    if not spec.keep_traces:
        shutil.rmtree(traces_dir, ignore_errors=True)

    if verbose:
        print(f"\nDone in {elapsed:.1f}s — completed {n_done}, skipped {n_skip}, "
              f"errored {len(all_errored)}")
        if all_errored:
            print("  First few errors:")
            for e in all_errored[:3]:
                print(f"    game_idx {e['game_idx']}: {e['error'].splitlines()[0]}")
        if all_times:
            ts = sorted(all_times)
            avg = sum(ts) / len(ts)
            med = ts[len(ts) // 2]
            gps = n_done / elapsed if elapsed > 0 else 0.0
            print(f"  per-game wall: avg {avg:.2f}s | median {med:.2f}s | "
                  f"min {ts[0]:.2f}s | max {ts[-1]:.2f}s  (n={len(ts)})")
            print(f"  throughput: {gps:.2f} games/sec "
                  f"(~{gps * 3600:.0f} games/hr at {n_workers} workers)")
        print(f"  out-dir: {run_dir}")
    return meta


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-games", type=int, required=True)
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Run dir (resumes if it has metadata.json). Default: auto-id.")
    p.add_argument("--n-workers", type=int, default=4)
    p.add_argument("--base-seed", type=int, default=None,
                   help="Per-game seed = base_seed + game_idx. REQUIRED for a "
                        "fresh run — pass a DISJOINT value per run (e.g. 1000000, "
                        "2000000, ...) so seed ranges never overlap another run "
                        "(overlap = duplicate games when model+config also match). "
                        "On resume it is read from metadata. Pass 0 explicitly "
                        "only if you really want the 0-based range (warns).")
    p.add_argument("--sims", type=int, default=400)
    p.add_argument("--c-uct", type=float, default=1.0)
    p.add_argument("--temperature", type=float, default=1.0,
                   help="Played-move visit softmax temperature (passed to the "
                        "binary; π is stored raw regardless).")
    p.add_argument("--prior-mix", type=float, default=0.0,
                   help="Uniform-mix weight for the policy prior: "
                        "prior' = (1-w)*policy + w*(1/k). Default 0 (pure policy).")
    p.add_argument("--select-by", choices=["visits", "q"], default="visits",
                   help="Played-move selection: visits (default) or q "
                        "(rank root children by sign-corrected mean-Q).")
    p.add_argument("--keep-traces", action="store_true",
                   help="Keep the C++ action traces as the permanent root archive "
                        "instead of deleting them after chunk-writing. Traces are "
                        "~game-size but replay to GameRecords ~instantly, so they "
                        "let you delete games/chunks later and recover fast.")
    p.add_argument("--chunk-size", type=int, default=100,
                   help="Games per pickle file. Smaller → lower per-worker RAM "
                        "and O(n) writes. Default 100.")
    p.add_argument("--model-dir", type=str, default="nn_models/cpp_export",
                   help="Exported-weights dir handed to the C++ binary.")
    p.add_argument("--selfplay-bin", type=str, default="cpp/build/selfplay",
                   help="Path to the compiled C++ self-play binary.")
    p.add_argument("--resume", action="store_true",
                   help="Allow writing into an existing non-empty / "
                        "foreign-metadata dir (otherwise the driver refuses).")
    p.add_argument("--per-game-process", action="store_true",
                   help="Use the OLD one-subprocess-per-game path (reloads NN "
                        "weights every game). Default is BATCH: one subprocess "
                        "per worker-slice with a single weight load. Kept for "
                        "the A/B comparison.")
    args = p.parse_args()

    spec = _Spec(
        selfplay_bin=args.selfplay_bin, model_dir=args.model_dir,
        sims=args.sims, c_uct=args.c_uct, temperature=args.temperature,
        chunk_size=args.chunk_size, base_seed=args.base_seed,
        prior_mix=args.prior_mix, select_by=args.select_by,
        keep_traces=args.keep_traces,
        generation_mode="per_game" if args.per_game_process else "batch",
    )
    generate(
        n_games=args.n_games, out_dir=args.out_dir, n_workers=args.n_workers,
        base_seed=args.base_seed, spec=spec, resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
