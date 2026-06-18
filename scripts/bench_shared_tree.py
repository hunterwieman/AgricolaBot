"""Benchmark: MCTS-vs-MCTS game wall time, shared tree vs separate trees.

Plays N games of MCTS-vs-MCTS at a fixed sim budget in two configurations and
compares the average per-game wall time:

  * shared    — ONE MCTSSearch / MCTSAgent passed to BOTH seats (the
                "shared tree via shared agent" mode, MCTS_IMPLEMENTATION.md
                §11.2 mode 2). Both seats accumulate into one transposition
                table, so re-rooted nodes inherit visits from the opponent's
                prior search (with cap_total_sims=True, fewer fresh sims run).
  * separate  — each seat gets its OWN MCTSSearch / MCTSAgent (the default,
                §11.2 mode 1). A seat only inherits visits from its own turns.

The leaf evaluator is the production NN value net (`nn_models/best`) + the
combined behavioral-cloning policy (PUCT, FenceMode.FLATTEN, full legality) —
the data-generation workload (MCTS_IMPLEMENTATION.md §12 "Recommended PUCT").

Only the `play_game` call is timed. The value model + policy heads are loaded
ONCE per worker (lru_cache) in the pool initializer, and a short warmup search
is run there so no timed game pays torch / engine-cache cold-start.

Usage:
    ~/miniconda3/bin/python scripts/bench_shared_tree.py --n 8 --sims 500 --jobs 4
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import os
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import FenceMode, MCTSAgent, MCTSSearch
from agricola.agents.base import play_game
from agricola.legality import legal_actions as full_legal_actions
from agricola.scoring import score
from agricola.setup import setup_env


# ---------------------------------------------------------------------------
# Per-worker cached resources (loaded once, reused across games)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _value_model(path: str):
    from agricola.agents.nn.model import NormalizedValueModel
    model = NormalizedValueModel.load(path)
    model.eval()  # load() leaves TRAIN mode → dropout would fire on every leaf
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
    cap_total_sims: bool


_WORKER_SPEC: _Spec | None = None


def _is_shared_trunk(path: str) -> bool:
    """True if `path`'s meta `model_kind` is a joint `SharedTrunkModel`."""
    from agricola.agents.nn.model import read_model_kind
    try:
        return read_model_kind(path) == "shared_trunk"
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _joint_fns(path: str):
    """Load a joint `SharedTrunkModel` → `(value_fn, policy_fn, value_scale)`."""
    from agricola.agents.nn.model import load_value_evaluator
    from agricola.agents.nn.shared_policy import make_joint_fns
    model = load_value_evaluator(path)              # eval()'d SharedTrunkModel
    value_fn, policy_fn = make_joint_fns(model)
    return value_fn, policy_fn, float(getattr(model, "value_scale", 1.0))


def _make_search(spec: _Spec, *, rng_seed: int) -> MCTSSearch:
    """One production NN-leaf PUCT search (FLATTEN, full legality). The leaf can
    be a separate-net value model (+ a separate `--policy`) OR a joint
    `SharedTrunkModel` (value + policy off one trunk, overriding `--policy`)."""
    if _is_shared_trunk(spec.leaf_ckpt):
        value_fn, policy_fn, vscale = _joint_fns(spec.leaf_ckpt)
        return MCTSSearch(
            rng_seed=rng_seed,
            legal_actions_fn=full_legal_actions,    # policy is the sole prune
            evaluator_fn=value_fn,                  # single-pass P0-frame margin
            leaf_value_scale=vscale,
            policy_fn=policy_fn,                    # joint trunk's own heads
            fence_mode=FenceMode.FLATTEN,           # required for PUCT
        )
    from agricola.agents.nn.agent import nn_evaluator
    model = _value_model(spec.leaf_ckpt)
    return MCTSSearch(
        rng_seed=rng_seed,
        legal_actions_fn=full_legal_actions,        # policy is the sole prune
        evaluator_config=model,                     # NN model rides in config slot
        evaluator_fn=nn_evaluator,                  # single-pass P0-frame margin
        leaf_value_scale=float(getattr(model, "value_scale", 1.0)),
        policy_fn=_combined_policy(spec.policy_variant),
        fence_mode=FenceMode.FLATTEN,               # required for PUCT
    )


def _make_agent(spec: _Spec, search: MCTSSearch, *, rng_seed: int) -> MCTSAgent:
    return MCTSAgent(
        search,
        sims_per_move=spec.sims,
        c_uct=spec.c_uct,
        rng_seed=rng_seed,
        cap_total_sims=spec.cap_total_sims,
    )


def _init_worker(spec: _Spec) -> None:
    import torch
    torch.set_num_threads(1)  # one BLAS thread/worker → no oversubscription
    global _WORKER_SPEC
    _WORKER_SPEC = spec
    # Warm everything OUT of the timed region: model load, policy load (9
    # checkpoints for a separate-net leaf; the joint trunk owns its policy),
    # torch thread spin-up, engine frontier/fence lru-caches.
    if _is_shared_trunk(spec.leaf_ckpt):
        _joint_fns(spec.leaf_ckpt)
    else:
        _value_model(spec.leaf_ckpt)
        _combined_policy(spec.policy_variant)
    initial, env = setup_env(seed=999_999)
    warm = MCTSAgent(_make_search(spec, rng_seed=0), sims_per_move=40,
                     rng_seed=0, c_uct=spec.c_uct,
                     cap_total_sims=spec.cap_total_sims)
    # A few real moves so the engine + NN paths are all exercised.
    state = initial
    from agricola.agents.base import decider_of
    for _ in range(6):
        if state.phase.name == "BEFORE_SCORING":
            break
        d = decider_of(state)
        from agricola.engine import step
        action = env.resolve(state) if d is None else warm(state)
        state = step(state, action)


def _play(task: tuple[str, int]) -> tuple[str, int, float, int, int]:
    """Play one game; time ONLY the play_game call. task = (mode, seed)."""
    mode, seed = task
    spec = _WORKER_SPEC
    assert spec is not None
    initial, env = setup_env(seed=seed)
    if mode == "shared":
        # One search + one agent, used for BOTH seats (§11.2 mode 2).
        agent = _make_agent(spec, _make_search(spec, rng_seed=seed), rng_seed=seed)
        agents = (agent, agent)
    else:
        # Separate tree per seat (§11.2 mode 1); models/policy shared by ref.
        p0 = _make_agent(spec, _make_search(spec, rng_seed=seed), rng_seed=seed)
        p1 = _make_agent(spec, _make_search(spec, rng_seed=seed + 1_000_000),
                         rng_seed=seed + 1_000_000)
        agents = (p0, p1)
    t0 = time.perf_counter()
    final, _ = play_game(initial, agents, env.resolve)
    elapsed = time.perf_counter() - t0
    return mode, seed, elapsed, score(final, 0)[0], score(final, 1)[0]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=8, help="Games per configuration.")
    p.add_argument("--sims", type=int, default=500, help="MCTS sims/move.")
    p.add_argument("--jobs", type=int, default=4, help="Parallel worker processes.")
    p.add_argument("--c-uct", type=float, default=1.0)
    p.add_argument("--leaf-ckpt", type=str, default="nn_models/best")
    p.add_argument("--policy", type=str, default="unweighted",
                   choices=("unweighted", "awr"))
    p.add_argument("--no-cap-total-sims", action="store_true",
                   help="Run --sims FRESH sims/move instead of capping total "
                        "root visits at --sims (the default cap_total_sims=True).")
    args = p.parse_args()

    spec = _Spec(
        leaf_ckpt=args.leaf_ckpt,
        policy_variant=args.policy,
        sims=args.sims,
        c_uct=args.c_uct,
        cap_total_sims=not args.no_cap_total_sims,
    )

    seeds = list(range(args.n))
    # Interleave modes so neither is systematically scheduled first/last.
    tasks = [m for s in seeds for m in (("shared", s), ("separate", s))]
    jobs = max(1, args.jobs)

    print(f"Benchmark: MCTS-vs-MCTS, {args.n} games/config, sims={args.sims}, "
          f"cap_total_sims={spec.cap_total_sims}, jobs={jobs}")
    print(f"  leaf=nn ({args.leaf_ckpt}), policy=combined:{args.policy}, "
          f"PUCT/FLATTEN/full-legality, c_uct={args.c_uct}")
    print(f"  (loading models + warmup per worker — untimed — then {len(tasks)} games)\n")

    results: list[tuple[str, int, float, int, int]] = []
    with Pool(processes=jobs, initializer=_init_worker, initargs=(spec,)) as pool:
        for mode, seed, elapsed, s0, s1 in pool.imap_unordered(_play, tasks):
            results.append((mode, seed, elapsed, s0, s1))
            print(f"  [{len(results):>2}/{len(tasks)}] {mode:>8} seed={seed:>2} "
                  f"{elapsed:6.1f}s  (P0 {s0} - {s1} P1)", flush=True)

    print()
    for mode in ("shared", "separate"):
        times = sorted(e for m, _, e, _, _ in results if m == mode)
        n = len(times)
        avg = sum(times) / n
        med = times[n // 2] if n % 2 else (times[n // 2 - 1] + times[n // 2]) / 2
        print(f"  {mode:>8}: avg {avg:6.1f}s/game | median {med:6.1f}s | "
              f"min {times[0]:.1f}s | max {times[-1]:.1f}s  (n={n})")

    sh = [e for m, _, e, _, _ in results if m == "shared"]
    se = [e for m, _, e, _, _ in results if m == "separate"]
    avg_sh, avg_se = sum(sh) / len(sh), sum(se) / len(se)
    faster = "shared" if avg_sh < avg_se else "separate"
    ratio = max(avg_sh, avg_se) / min(avg_sh, avg_se)
    print(f"\n  → {faster} is faster: {avg_se:.1f}s (separate) vs "
          f"{avg_sh:.1f}s (shared), {ratio:.2f}× ratio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
