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

GENERATION MODES (both produce byte-for-byte the same run-dir output):
  * BATCH (default): each pool worker launches ONE C++ subprocess that loads
    the NN weights once and plays its whole slice of games (`--game-idxs ...
    --base-seed B --out-dir <worker-tmp>`), writing `trace_<i>.json` per game;
    the worker then replays each trace → GameRecord and chunk-writes. This
    removes the per-game ~0.15s weight-reload startup.
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
import os
import platform
import subprocess
import sys
import tempfile
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


def _run_one_game(spec: _Spec, *, game_idx: int, seed: int, tmp_dir: Path):
    """Run the C++ binary for one game → load its trace → replay → GameRecord.

    The PER-GAME path (one subprocess per game). Writes the trace to a unique
    temp file under `tmp_dir`, deletes it after loading. Raises on subprocess
    failure (non-zero exit) or replay error — the caller logs it into
    `errored_games` and continues.
    """
    bin_path = _bin_path(spec)
    model_dir = spec.model_dir  # passed through verbatim to the binary

    # A unique trace file per game so concurrent workers never collide.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"cpp_trace_g{game_idx:08d}_", suffix=".json", dir=str(tmp_dir)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        cmd = [
            str(bin_path),
            "--mcts",
            "--seed", str(seed),
            "--sims", str(spec.sims),
            "--c-uct", str(spec.c_uct),
            "--temperature", str(spec.temperature),
            "--model-dir", model_dir,
            "--out", str(tmp_path),
        ]
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"selfplay binary exited {proc.returncode} for game_idx={game_idx} "
                f"seed={seed}. stderr:\n{proc.stderr.strip()}"
            )
        # The trace carries its own seed (the binary's), but the plan seed is
        # the authoritative one and they match (we pass --seed=seed). Trust the
        # record's seed from the trace; nothing to reconcile.
        return _replay_trace_file(spec, game_idx=game_idx, trace_path=tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _run_batch_games(spec: _Spec, *, game_idxs: list[int], tmp_dir: Path):
    """Run ONE C++ subprocess that plays all `game_idxs` (one weight load).

    Returns (batch_dir, written_idxs, proc):
      * batch_dir    — a unique dir under `tmp_dir` holding `trace_<i>.json` for
        each game the binary wrote (caller replays + deletes them).
      * written_idxs — the set of game_idxs whose trace file actually exists,
        regardless of the process exit code. On a nonzero exit we still return
        whatever traces DID get written so the caller can salvage them and only
        mark the missing idxs errored.
      * proc         — the CompletedProcess, so the caller can log returncode /
        stderr for the missing idxs.

    Raises RuntimeError (carrying stderr) ONLY on total failure — a nonzero exit
    that produced ZERO traces. A partial exit (some traces written) returns
    normally so the salvaged games still count.
    """
    bin_path = _bin_path(spec)
    batch_dir = Path(tempfile.mkdtemp(prefix="cpp_batch_", dir=str(tmp_dir)))

    idxs_arg = ",".join(str(i) for i in game_idxs)
    cmd = [
        str(bin_path),
        "--mcts",
        "--game-idxs", idxs_arg,
        "--base-seed", str(spec.base_seed),
        "--sims", str(spec.sims),
        "--c-uct", str(spec.c_uct),
        "--temperature", str(spec.temperature),
        "--model-dir", spec.model_dir,
        "--out-dir", str(batch_dir),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)

    written = {
        i for i in game_idxs if (batch_dir / f"trace_{i}.json").exists()
    }
    if proc.returncode != 0 and not written:
        # Total failure — nothing salvageable. Clean up and raise.
        try:
            for f in batch_dir.glob("*"):
                f.unlink(missing_ok=True)
            batch_dir.rmdir()
        except OSError:
            pass
        raise RuntimeError(
            f"selfplay batch exited {proc.returncode} with no traces "
            f"(idxs[0:5]={game_idxs[:5]}..., base_seed={spec.base_seed}). "
            f"stderr:\n{proc.stderr.strip()}"
        )
    return batch_dir, written, proc


def _worker(args: dict) -> dict:
    worker_id: int = args["worker_id"]
    games_dir = Path(args["games_dir"])
    tmp_dir = Path(args["tmp_dir"])
    plan_slice: list[dict] = args["plan_slice"]   # _GamePlan items as dicts
    spec: _Spec = args["spec"]

    completed, next_chunk = _completed_idxs_and_next_chunk(games_dir, worker_id)

    buffer: list = []
    per_game_times: list[float] = []
    errored: list[tuple[int, str]] = []
    n_completed = 0

    # The chunk-file name is keyed only on worker_id, so the chunk layout (and
    # therefore the on-disk run dir) is identical across modes. nonlocal state
    # below is shared between the two mode branches.
    next_chunk_box = [next_chunk]

    def _flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        path = games_dir / f"worker_{worker_id:02d}_c{next_chunk_box[0]:03d}.pkl"
        _write_pickle_atomic(path, buffer)
        next_chunk_box[0] += 1
        buffer = []          # drop the in-memory chunk → bounded RAM

    def _record(rec) -> None:
        nonlocal n_completed, buffer
        buffer.append(rec)
        n_completed += 1
        if _PROGRESS_COUNTER is not None:
            with _PROGRESS_COUNTER.get_lock():
                _PROGRESS_COUNTER.value += 1
        if len(buffer) >= spec.chunk_size:
            _flush()

    # Remaining (post-resume) work items, in plan order. Skipping here keeps the
    # game order — and thus the chunk packing — identical to the per-game path.
    remaining = [it for it in plan_slice if it["game_idx"] not in completed]
    n_skipped = len(plan_slice) - len(remaining)

    if spec.generation_mode == "per_game":
        for item in remaining:
            game_idx = item["game_idx"]
            seed = item["seed"]
            t0 = time.perf_counter()
            try:
                rec = _run_one_game(
                    spec, game_idx=game_idx, seed=seed, tmp_dir=tmp_dir
                )
            except Exception as exc:
                tb = traceback.format_exc()
                errored.append((game_idx, f"{type(exc).__name__}: {exc}\n{tb}"))
                continue  # don't crash the run; move to the next game
            per_game_times.append(time.perf_counter() - t0)
            _record(rec)
        _flush()
    else:  # "batch": ONE subprocess for the whole remaining slice (one NN load)
        if remaining:
            idxs = [it["game_idx"] for it in remaining]
            batch_t0 = time.perf_counter()
            try:
                batch_dir, written, proc = _run_batch_games(
                    spec, game_idxs=idxs, tmp_dir=tmp_dir
                )
            except Exception as exc:
                # Total batch failure (no traces produced) → mark every
                # remaining idx errored; the run continues with other workers.
                tb = traceback.format_exc()
                msg = f"{type(exc).__name__}: {exc}\n{tb}"
                errored = [(i, msg) for i in idxs]
                return {
                    "worker_id": worker_id,
                    "n_completed": 0,
                    "n_skipped": n_skipped,
                    "errored": errored,
                    "per_game_times": per_game_times,
                }
            # Amortize the single batch wall-time over the games it produced
            # (the per-game generation cost isn't separable in batch mode).
            n_written = max(1, len(written))
            amortized = (time.perf_counter() - batch_t0) / n_written
            try:
                # Replay in plan order so chunk packing matches the per-game path.
                for item in remaining:
                    game_idx = item["game_idx"]
                    if game_idx not in written:
                        # The batch process skipped/failed this one (partial exit).
                        errored.append((
                            game_idx,
                            f"batch process did not write trace_{game_idx}.json "
                            f"(exit={proc.returncode}); "
                            f"stderr:\n{proc.stderr.strip()}",
                        ))
                        continue
                    trace_path = batch_dir / f"trace_{game_idx}.json"
                    try:
                        rec = _replay_trace_file(
                            spec, game_idx=game_idx, trace_path=trace_path
                        )
                    except Exception as exc:
                        tb = traceback.format_exc()
                        errored.append(
                            (game_idx, f"{type(exc).__name__}: {exc}\n{tb}")
                        )
                        continue
                    per_game_times.append(amortized)
                    _record(rec)
                _flush()
            finally:
                # Always delete the per-game traces + the batch dir.
                try:
                    for f in batch_dir.glob("*"):
                        f.unlink(missing_ok=True)
                    batch_dir.rmdir()
                except OSError:
                    pass

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
    base_seed: int,
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

    games_dir = run_dir / "games"
    tmp_dir = run_dir / ".tmp"
    games_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

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
              f"mode={spec.generation_mode}, data_version={DATA_VERSION}\n",
              flush=True)

    worker_args = [
        {"worker_id": w, "games_dir": str(games_dir), "tmp_dir": str(tmp_dir),
         "plan_slice": [asdict(p) for p in slices[w]], "spec": spec}
        for w in range(n_workers)
    ]

    # Games already on disk (full chunks only — the partial final chunk exists
    # only at completion), so progress can report the resumed baseline.
    baseline = len(list(games_dir.glob("worker_*_c*.pkl"))) * spec.chunk_size
    if baseline and verbose:
        print(f"  resuming: ~{baseline} games already on disk\n", flush=True)

    t0 = time.perf_counter()
    if n_workers == 1:
        global _PROGRESS_COUNTER
        _PROGRESS_COUNTER = None
        results = [_worker(worker_args[0])]
    else:
        counter = mp.Value("i", 0)
        stop = threading.Event()

        def _monitor() -> None:
            while not stop.wait(60.0):
                el = time.perf_counter() - t0
                rate = counter.value / el if el > 0 else 0.0   # games/sec this run
                done = baseline + counter.value
                remaining = max(0, n_games - done)
                eta_h = remaining / rate / 3600 if rate > 0 else float("inf")
                print(f"  [progress] {done}/{n_games} games (~{100*done/n_games:.0f}%), "
                      f"{rate*60:.1f}/min this run, ETA {eta_h:.1f} h", flush=True)

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

    meta = {
        "run_id": run_id,
        "code_sha": _current_git_sha(),
        "host": platform.node(),
        "kind": "mcts_selfplay",
        "generator": "cpp",
        "data_version": DATA_VERSION,
        "n_workers": n_workers,
        "base_seed": base_seed,
        "planned_games": n_games,
        "completed_games": n_done + n_skip,
        "errored_games": all_errored,
        "selfplay_bin": spec.selfplay_bin,
        "model_dir": spec.model_dir,
        "sims": spec.sims,
        "c_uct": spec.c_uct,
        "temperature": spec.temperature,
        "chunk_size": spec.chunk_size,
        "generation_mode": spec.generation_mode,
        "legality": "full", "fence_mode": "flatten", "cap_total_sims": True,
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    # Best-effort cleanup of the temp dir (only if empty; resumes may share it).
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

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
    p.add_argument("--base-seed", type=int, default=0,
                   help="Per-game seed = base_seed + game_idx (mirrors the "
                        "Python generator's scheme). Default 0.")
    p.add_argument("--sims", type=int, default=400)
    p.add_argument("--c-uct", type=float, default=1.4)
    p.add_argument("--temperature", type=float, default=1.0,
                   help="Played-move visit softmax temperature (passed to the "
                        "binary; π is stored raw regardless).")
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
        generation_mode="per_game" if args.per_game_process else "batch",
    )
    generate(
        n_games=args.n_games, out_dir=args.out_dir, n_workers=args.n_workers,
        base_seed=args.base_seed, spec=spec, resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
