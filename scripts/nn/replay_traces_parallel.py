#!/usr/bin/env python
"""Parallel replay of a run dir's C++ self-play traces into GameRecord chunks.

The serial `replay_traces.py` re-steps every game's recorded actions through the
Python engine one game at a time — fine for a few thousand games, but ~40 min for
240k. This driver shards the `traces/trace_*.json` files across a process pool;
each worker replays its shard and writes its own `games/worker_<wid>_c<NNN>.pkl`
chunks (the same run-dir format `build_shared_datasets` consumes via the
`games/worker_*.pkl` glob). Replay is engine-only (no MCTS, no NN), so it is CPU
cheap and scales near-linearly with cores.

Resumable: trace indices already present in `games/` are skipped before sharding.

    python scripts/nn/replay_traces_parallel.py \
        --run-dir data/nn_training/runs/run_a --n-workers 32 --chunk-size 200
"""
import argparse
import json
import os
import pickle
import sys
from multiprocessing import Pool
from pathlib import Path

from agricola.agents.nn.trace_replay import replay_trace

_CPP_CONFIG = "cpp_selfplay"  # matches generate_selfplay_data_cpp / replay_traces


def _trace_idx(path: Path) -> int:
    return int(path.stem.split("_")[1])


def _write_chunk_atomic(path: Path, records: list) -> None:
    tmp = path.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(records, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def _completed_idxs(games_dir: Path) -> set:
    done = set()
    for pkl in games_dir.glob("worker_*.pkl"):
        try:
            with open(pkl, "rb") as f:
                for rec in pickle.load(f):
                    done.add(int(rec.game_idx))
        except Exception:  # noqa: BLE001 — a partial/corrupt chunk: ignore
            pass
    return done


def _replay_shard(task: tuple) -> tuple:
    """Replay one worker's shard of trace paths into chunk pkls. Returns (ok, err)."""
    wid, trace_paths, games_dir_s, temp, chunk_size = task
    games_dir = Path(games_dir_s)
    buf: list = []
    chunk_no = 0
    n_ok = n_err = 0

    def flush():
        nonlocal chunk_no, buf
        if not buf:
            return
        _write_chunk_atomic(games_dir / f"worker_{wid:03d}_c{chunk_no:03d}.pkl", buf)
        chunk_no += 1
        buf = []

    for tp in trace_paths:
        idx = _trace_idx(Path(tp))
        try:
            trace = json.loads(Path(tp).read_text())
            rec = replay_trace(
                trace, game_idx=idx,
                p0_config_path=_CPP_CONFIG, p1_config_path=_CPP_CONFIG,
                p0_temperature=temp, p1_temperature=temp,
            )
            buf.append(rec)
            n_ok += 1
        except Exception as e:  # noqa: BLE001 — skip a bad trace, keep going
            n_err += 1
            if n_err <= 3:
                print(f"  [w{wid}] replay error trace_{idx}: {e}", file=sys.stderr,
                      flush=True)
        if len(buf) >= chunk_size:
            flush()
    flush()
    return n_ok, n_err


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--n-workers", type=int, default=os.cpu_count())
    p.add_argument("--chunk-size", type=int, default=200)
    p.add_argument("--temperature", type=float, default=None,
                   help="recorded on each GameRecord; default = run metadata's "
                        "temperature, else 1.0.")
    args = p.parse_args()

    run_dir = args.run_dir
    traces_dir = run_dir / "traces"
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True, exist_ok=True)

    meta_path = run_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    temp = args.temperature if args.temperature is not None \
        else float(meta.get("temperature", 1.0))

    traces = sorted(traces_dir.glob("trace_*.json"), key=_trace_idx)
    if not traces:
        print(f"No traces in {traces_dir}", file=sys.stderr)
        return 2

    done = _completed_idxs(games_dir)
    todo = [t for t in traces if _trace_idx(t) not in done]
    nw = max(1, min(args.n_workers, len(todo))) if todo else 1
    print(f"{len(traces)} traces | {len(done)} already replayed | replaying "
          f"{len(todo)} on {nw} workers (temperature={temp})", flush=True)
    if not todo:
        return 0

    # Round-robin shard so each worker gets a roughly equal mix. Worker ids start
    # at 100 to stay clear of generation workers (00..NN) and the serial
    # replay default (90) — only the `worker_*.pkl` glob matters downstream.
    shards: list = [[] for _ in range(nw)]
    for i, t in enumerate(todo):
        shards[i % nw].append(str(t))
    tasks = [(100 + k, shards[k], str(games_dir), temp, args.chunk_size)
             for k in range(nw) if shards[k]]

    n_ok = n_err = 0
    with Pool(nw) as pool:
        for ok, err in pool.imap_unordered(_replay_shard, tasks):
            n_ok += ok
            n_err += err
            print(f"  progress: {n_ok} replayed, {n_err} errored", flush=True)

    total = len(_completed_idxs(games_dir))
    meta["completed_games"] = total
    meta["temperature"] = temp
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"done: {n_ok} replayed, {n_err} errored | games/ now holds {total} "
          f"GameRecords", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
