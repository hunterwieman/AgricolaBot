"""Replay a run dir's existing C++ self-play traces into GameRecord chunks.

The C++ generator (`generate_selfplay_data_cpp.py`) writes per-game traces to
`<run-dir>/traces/trace_<idx>.json`, then replays them into `GameRecord` pickles
under `<run-dir>/games/`. If a run is interrupted after generating traces but
before (or during) the replay, the traces are on disk but `games/` is empty.

This tool does ONLY the replay half: it replays every existing trace into the
same `worker_*.pkl` chunk format the training pipeline consumes — generating
NOTHING and overwriting NO traces. It is resumable (skips game_idxs already
present in `games/`) and safe to re-run.

Usage:
  python scripts/nn/replay_traces.py --run-dir data/nn_training/runs/joint_selfplay_5k

  # temperature is recorded on each GameRecord; default matches the run's
  # generation temperature (read from metadata.json, else 1.0).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.trace_replay import replay_trace  # noqa: E402

_CPP_CONFIG = "cpp_selfplay"  # the sentinel config recorded on cpp self-play records


def _trace_idx(path: Path) -> int:
    return int(path.stem.split("_")[1])  # "trace_<idx>" -> idx


def _completed_idxs(games_dir: Path) -> set[int]:
    """game_idxs already durably written to games/ chunks (resume skip set)."""
    done: set[int] = set()
    for f in sorted(games_dir.glob("worker_*.pkl")):
        with f.open("rb") as fh:
            for rec in pickle.load(fh):
                done.add(rec.game_idx)
    return done


def _write_chunk_atomic(path: Path, records: list) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        pickle.dump(records, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--temperature", type=float, default=None,
                   help="recorded on each GameRecord; default = run's metadata "
                        "generation temperature, else 1.0.")
    p.add_argument("--chunk-size", type=int, default=100)
    p.add_argument("--worker-id", type=int, default=90,
                   help="chunk filename prefix worker_<id> (default 90, kept "
                        "distinct from generation workers 00..NN to avoid collision).")
    args = p.parse_args()

    run_dir = args.run_dir
    traces_dir = run_dir / "traces"
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    temp = args.temperature
    if temp is None:
        temp = float(meta.get("temperature", 1.0))

    traces = sorted(traces_dir.glob("trace_*.json"), key=_trace_idx)
    if not traces:
        print(f"No traces in {traces_dir}", file=sys.stderr)
        return 2

    done = _completed_idxs(games_dir)
    todo = [t for t in traces if _trace_idx(t) not in done]
    print(f"{len(traces)} traces | {len(done)} already in games/ | replaying {len(todo)} "
          f"(temperature={temp}, chunk_size={args.chunk_size})", flush=True)

    # Continue chunk numbering after any existing replay-worker chunks.
    existing = sorted(games_dir.glob(f"worker_{args.worker_id:02d}_c*.pkl"))
    next_chunk = len(existing)

    buf: list = []
    n_ok = n_err = 0

    def flush():
        nonlocal next_chunk, buf
        if not buf:
            return
        path = games_dir / f"worker_{args.worker_id:02d}_c{next_chunk:03d}.pkl"
        _write_chunk_atomic(path, buf)
        next_chunk += 1
        buf = []

    for t in todo:
        idx = _trace_idx(t)
        try:
            trace = json.loads(t.read_text())
            rec = replay_trace(
                trace, game_idx=idx,
                p0_config_path=_CPP_CONFIG, p1_config_path=_CPP_CONFIG,
                p0_temperature=temp, p1_temperature=temp,
            )
            buf.append(rec)
            n_ok += 1
        except Exception as e:  # noqa: BLE001 — skip a bad trace, keep going
            n_err += 1
            if n_err <= 5:
                print(f"  replay error trace_{idx}: {e}", file=sys.stderr)
        if len(buf) >= args.chunk_size:
            flush()
        if n_ok and n_ok % 500 == 0:
            print(f"  replayed {n_ok}/{len(todo)}", flush=True)
    flush()

    total_games = len(_completed_idxs(games_dir))
    meta["completed_games"] = total_games
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"done: {n_ok} replayed, {n_err} errored | games/ now holds {total_games} "
          f"GameRecords", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
