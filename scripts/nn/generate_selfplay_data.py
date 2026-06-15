"""MCTS self-play training-data generator (DATA_VERSION 3).

Plays N games of MCTS-vs-MCTS with a SHARED tree (one agent drives both
seats per game) and records each non-singleton decision with the search's
root visit distribution π and root value — the AlphaZero policy/value
targets. The production leaf is the NN value net (`nn_models/best`) + the
combined behavioral-cloning policy (PUCT / FLATTEN / full legality).

Differs from `generate_training_data.py` (the heuristic-ensemble generator)
in three ways, all deliberate:

  * Shared-tree MCTS self-play seats, not a sampled heuristic ensemble.
  * Records π + root_value (schema v3), not just `chosen_action`.
  * CHUNKED STREAMING writes: each worker flushes a fresh pickle every
    `--chunk-size` games and drops the buffer, so per-worker RAM stays
    bounded and write cost is O(n) instead of the O(n²) full-list rewrite
    the heuristic generator does after every game.

A fresh tree is built per game (shared only between the two seats); trees
are never carried across games, so RAM doesn't accumulate.

Reuses the proven scaffold from `generate_training_data.py`
(`partition_plan`, `_write_pickle_atomic`, `_current_git_sha`,
`_new_run_id`).

Usage:
    # Timing pass (a handful of games), prints per-game wall + extrapolation
    ~/miniconda3/bin/python scripts/nn/generate_selfplay_data.py \\
        --n-games 12 --n-workers 4 --sims 400

    # Full run (resumes if --out-dir exists with metadata.json)
    ~/miniconda3/bin/python scripts/nn/generate_selfplay_data.py \\
        --n-games 2000 --n-workers 4 --sims 400 --chunk-size 100
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import multiprocessing as mp
import platform
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import FenceMode, MCTSSearch  # noqa: E402
from agricola.agents.nn import DATA_VERSION  # noqa: E402
from agricola.agents.nn.selfplay_recording import (  # noqa: E402
    RootCapturingMCTSAgent,
    play_selfplay_recording_game,
)
from agricola.legality import legal_actions as full_legal_actions  # noqa: E402
from agricola.setup import setup_env  # noqa: E402

# Reuse the heuristic generator's tested scaffolding.
sys.path.insert(0, str(ROOT / "scripts" / "nn"))
from generate_training_data import (  # noqa: E402
    _current_git_sha,
    _new_run_id,
    _write_pickle_atomic,
    partition_plan,
)


# ---------------------------------------------------------------------------
# Per-worker cached resources (loaded ONCE per process)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _value_model(path: str):
    import torch
    torch.set_num_threads(1)
    from agricola.agents.nn.model import NormalizedValueModel
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    model = NormalizedValueModel.load(p)
    model.eval()  # load() leaves TRAIN mode → dropout would noise the leaf
    return model


@functools.lru_cache(maxsize=1)
def _combined_policy(variant: str):
    path = ROOT / "scripts" / "nn" / "build_combined_policy.py"
    spec = importlib.util.spec_from_file_location("build_combined_policy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build(variant)


@dataclass(frozen=True)
class _Spec:
    leaf_ckpt: str
    policy_variant: str
    sims: int
    c_uct: float
    temperature: float
    chunk_size: int


def _is_shared_trunk(path: str) -> bool:
    """True if `path`'s meta `model_kind` is a joint `SharedTrunkModel`."""
    from agricola.agents.nn.model import read_model_kind
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    try:
        return read_model_kind(p) == "shared_trunk"
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _joint_fns(path: str):
    """Load a joint `SharedTrunkModel` and return `(value_fn, policy_fn, value_scale)`
    off the one shared trunk — value AND policy from a single forward per node
    (the joint model's own heads ARE the policy, overriding `--policy`)."""
    import torch
    torch.set_num_threads(1)
    from agricola.agents.nn.model import load_value_evaluator
    from agricola.agents.nn.shared_policy import make_joint_fns
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    model = load_value_evaluator(p)             # eval()'d SharedTrunkModel
    value_fn, policy_fn = make_joint_fns(model)
    return value_fn, policy_fn, float(getattr(model, "value_scale", 1.0))


def _build_agent(spec: _Spec, *, seed: int) -> RootCapturingMCTSAgent:
    """A fresh shared-tree self-play agent for ONE game (NN leaf + policy).

    The leaf checkpoint can be a separate-net value model (+ a separate combined
    `--policy`) OR a joint `SharedTrunkModel` (value + policy off one trunk via
    `make_joint_fns`, which then overrides `--policy`)."""
    if _is_shared_trunk(spec.leaf_ckpt):
        value_fn, policy_fn, vscale = _joint_fns(spec.leaf_ckpt)
        search = MCTSSearch(
            rng_seed=seed,
            legal_actions_fn=full_legal_actions,   # policy is the sole prune
            evaluator_fn=value_fn,                  # single-pass P0-frame margin
            leaf_value_scale=vscale,
            policy_fn=policy_fn,                    # joint trunk's own heads
            fence_mode=FenceMode.FLATTEN,           # required for PUCT
        )
        return RootCapturingMCTSAgent(
            search,
            sims_per_move=spec.sims,
            c_uct=spec.c_uct,
            action_selection_temperature=spec.temperature,
            rng_seed=seed,
            cap_total_sims=True,
        )
    from agricola.agents.nn.agent import nn_evaluator
    model = _value_model(spec.leaf_ckpt)
    search = MCTSSearch(
        rng_seed=seed,
        legal_actions_fn=full_legal_actions,       # policy is the sole prune
        evaluator_config=model,
        evaluator_fn=nn_evaluator,                  # single-pass P0-frame margin
        leaf_value_scale=float(getattr(model, "value_scale", 1.0)),
        policy_fn=_combined_policy(spec.policy_variant),
        fence_mode=FenceMode.FLATTEN,               # required for PUCT
    )
    return RootCapturingMCTSAgent(
        search,
        sims_per_move=spec.sims,
        c_uct=spec.c_uct,
        action_selection_temperature=spec.temperature,
        rng_seed=seed,
        cap_total_sims=True,
    )


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


def _worker(args: dict) -> dict:
    worker_id: int = args["worker_id"]
    games_dir = Path(args["games_dir"])
    plan_slice: list[tuple[int, int]] = args["plan_slice"]   # (game_idx, seed)
    spec: _Spec = args["spec"]

    completed, next_chunk = _completed_idxs_and_next_chunk(games_dir, worker_id)

    buffer: list = []
    per_game_times: list[float] = []
    n_completed = 0
    n_skipped = 0

    def _flush() -> None:
        nonlocal buffer, next_chunk
        if not buffer:
            return
        path = games_dir / f"worker_{worker_id:02d}_c{next_chunk:03d}.pkl"
        _write_pickle_atomic(path, buffer)
        next_chunk += 1
        buffer = []          # drop the in-memory chunk → bounded RAM

    for game_idx, seed in plan_slice:
        if game_idx in completed:
            n_skipped += 1
            continue
        initial, env = setup_env(seed=seed)
        agent = _build_agent(spec, seed=seed)
        t0 = time.perf_counter()
        rec = play_selfplay_recording_game(
            initial, agent, dealer=env.resolve,
            game_idx=game_idx, seed=seed, temperature=spec.temperature,
        )
        per_game_times.append(time.perf_counter() - t0)
        buffer.append(rec)
        n_completed += 1
        if _PROGRESS_COUNTER is not None:
            with _PROGRESS_COUNTER.get_lock():
                _PROGRESS_COUNTER.value += 1
        if len(buffer) >= spec.chunk_size:
            _flush()
    _flush()

    return {
        "worker_id": worker_id,
        "n_completed": n_completed,
        "n_skipped": n_skipped,
        "per_game_times": per_game_times,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def generate(
    *, n_games: int, out_dir: Path | None, n_workers: int, base_seed: int, spec: _Spec,
) -> dict:
    if out_dir is not None and (Path(out_dir) / "metadata.json").exists():
        run_dir = Path(out_dir)
        run_id = json.loads((run_dir / "metadata.json").read_text())["run_id"]
    elif out_dir is not None:
        run_dir, run_id = Path(out_dir), Path(out_dir).name
    else:
        run_id = _new_run_id()
        run_dir = ROOT / "data" / "nn_training" / "runs" / run_id
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True, exist_ok=True)

    plan = [(i, base_seed + i) for i in range(n_games)]
    slices = partition_plan(plan, n_workers)

    print(f"Run dir: {run_dir}")
    print(f"  {n_games} games, {n_workers} workers, chunk_size={spec.chunk_size}")
    print(f"  MCTS: sims={spec.sims}, c_uct={spec.c_uct}, T={spec.temperature}, "
          f"shared tree, NN leaf ({spec.leaf_ckpt}) + policy={spec.policy_variant}, "
          f"PUCT/FLATTEN/full-legality, data_version={DATA_VERSION}\n", flush=True)

    worker_args = [
        {"worker_id": w, "games_dir": str(games_dir),
         "plan_slice": slices[w], "spec": spec}
        for w in range(n_workers)
    ]

    # Games already on disk (full chunks only — the partial final chunk exists
    # only at completion), so progress can report the resumed baseline.
    baseline = len(list(games_dir.glob("worker_*_c*.pkl"))) * spec.chunk_size
    if baseline:
        print(f"  resuming: ~{baseline} games already on disk\n", flush=True)

    t0 = time.perf_counter()
    if n_workers == 1:
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

    meta = {
        "run_id": run_id, "code_sha": _current_git_sha(), "host": platform.node(),
        "kind": "mcts_selfplay", "data_version": DATA_VERSION,
        "n_workers": n_workers, "base_seed": base_seed, "planned_games": n_games,
        "completed_games": n_done + n_skip,
        "sims_per_move": spec.sims, "c_uct": spec.c_uct,
        "action_selection_temperature": spec.temperature,
        "leaf_ckpt": spec.leaf_ckpt, "policy_variant": spec.policy_variant,
        "chunk_size": spec.chunk_size,
        "legality": "full", "fence_mode": "flatten", "cap_total_sims": True,
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    # Timing report + extrapolation.
    print(f"\nDone in {elapsed:.1f}s — completed {n_done}, skipped {n_skip}")
    if all_times:
        ts = sorted(all_times)
        avg = sum(ts) / len(ts)
        med = ts[len(ts) // 2]
        print(f"  per-game wall: avg {avg:.1f}s | median {med:.1f}s | "
              f"min {ts[0]:.1f}s | max {ts[-1]:.1f}s  (n={len(ts)})")
        print(f"  throughput: ~{n_workers / avg * 3600:.0f} games/hr at {n_workers} workers")
        print(f"  extrapolated wall (this worker count):")
        for total in (1000, 2000, 5000, 10000):
            hrs = total * avg / n_workers / 3600
            print(f"    {total:>6} games ≈ {hrs:5.1f} h")
    return meta


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-games", type=int, required=True)
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Run dir (resumes if it has metadata.json). Default: auto-id.")
    p.add_argument("--n-workers", type=int, default=4)
    p.add_argument("--base-seed", type=int, default=2_000_000)
    p.add_argument("--sims", type=int, default=400)
    p.add_argument("--c-uct", type=float, default=0.5)
    p.add_argument("--temperature", type=float, default=1.0,
                   help="action_selection_temperature (played-move visit softmax). "
                        "Equal throughout; π is stored raw (τ=1) regardless.")
    p.add_argument("--chunk-size", type=int, default=100,
                   help="Games per pickle file. Smaller → lower per-worker RAM "
                        "and O(n) writes. Default 100.")
    p.add_argument("--leaf-ckpt", type=str, default="nn_models/best")
    p.add_argument("--policy", type=str, default="unweighted",
                   choices=("unweighted", "awr"))
    args = p.parse_args()

    spec = _Spec(
        leaf_ckpt=args.leaf_ckpt, policy_variant=args.policy,
        sims=args.sims, c_uct=args.c_uct, temperature=args.temperature,
        chunk_size=args.chunk_size,
    )
    generate(n_games=args.n_games, out_dir=args.out_dir, n_workers=args.n_workers,
             base_seed=args.base_seed, spec=spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
