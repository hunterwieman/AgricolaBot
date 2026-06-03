"""NN-backed match driver supporting MCTS-NN and NNAgent seats.

Each seat is independently configured as either:
  - `mcts`: MCTSAgent with `nn_evaluator_differential` as the leaf
    evaluator (via MCTSSearch's `evaluator_fn` + `evaluator_config`
    plumbing — same hook that lets V3-MCTS use `evaluate_hubris_v3`).
    The NN's differential evaluator is exactly antisymmetric by
    construction (`V_diff(s, 0) == -V_diff(s, 1)`), so we pass
    `leaf_differential=False` to MCTSSearch — otherwise it would
    compute `(+V_diff) - (-V_diff) = 2·V_diff`, double-counting.
  - `nn`: NNAgent with `nn_evaluator_differential` (1-turn greedy
    lookahead, no tree search).

Both seats load the SAME model file — this script's purpose is
isolating the lift (or regression) MCTS provides on top of the NN
when otherwise-identical evaluators are in play.

The V3 strict-restricted legality wrapper and V3 greedy-macro
heuristic are used by MCTS regardless of evaluator — only the
leaf-eval is swapped to NN. Per-game MCTSSearch instances → no
shared transposition tables.

Parallelization: multiprocessing.Pool, one game per task. Each
worker loads the model once at init and reuses it across games.
PyTorch BLAS is pinned to 1 thread per worker so N workers don't
contend for N² total threads.

Usage:
    # MCTS-NN-500 (P0) vs NNAgent-1-turn (P1)
    python scripts/nn/play_match.py \\
        --model nn_models/20260529-162301-04fe/best.pt \\
        --p0 mcts --p1 nn --n 100 --sims 500 --jobs 8

    # MCTS-NN-500 self-play (uninformative by symmetry, useful for timing)
    python scripts/nn/play_match.py --p0 mcts --p1 mcts ...
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from agricola.agents import (  # noqa: E402
    CONFIG_V1_T2,
    DEFAULT_CONFIG_V3,
    HeuristicConfig,
    HeuristicConfigV3,
    HubrisHeuristicV1,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
)
from agricola.agents.base import Agent, play_game  # noqa: E402
from agricola.agents.nn.agent import NNAgent, nn_evaluator_differential  # noqa: E402
from agricola.agents.nn.model import NormalizedValueModel  # noqa: E402
from agricola.scoring import score, tiebreaker  # noqa: E402
from agricola.setup import setup, setup_env  # noqa: E402


# Seat types: model-based (need a checkpoint) vs config-based (need a config).
SEAT_TYPES = ("mcts", "nn", "heuristic")
_MODEL_SEATS = ("mcts", "nn")


def _load_heuristic_config(spec: str, arch: str):
    """Resolve a heuristic config spec → config object. `spec` is either
    the 't2' sentinel (→ V1 CONFIG_V1_T2) or a path to a tuned JSON whose
    `best_config` is loaded as a V3 (or V1) config. Mirrors
    eval_vs_ensemble._load_config."""
    if spec == "t2":
        return CONFIG_V1_T2
    with Path(spec).open("r") as f:
        cfg_dict = json.load(f)["best_config"]
    return HeuristicConfigV3(**cfg_dict) if arch == "v3" else HeuristicConfig(**cfg_dict)


# ---------------------------------------------------------------------------
# Worker globals & spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    """Per-match config. Picklable — passed to worker init."""
    p0_model_path: str | None   # None for heuristic seats
    p1_model_path: str | None
    p0_type: str   # "mcts" | "nn" | "heuristic"
    p1_type: str
    p0_config: str | None       # heuristic config spec ("t2" or json path)
    p1_config: str | None
    p0_arch: str                # "v1" | "v3" (heuristic seats)
    p1_arch: str
    sims_per_move: int
    c_uct: float
    n_random_fencing: int
    fpu_offset: float
    temperature: float
    nn_temperature: float
    nn_legality: str = "strict"   # "strict" | "regular" — NNAgent seat's legality wrapper
    opt_pareto_level: int = 0      # agricola.opt_config.PARETO_OPT_LEVEL (0-3) — MCTS speedup
    opt_fence_cache: bool = False  # agricola.opt_config.FENCE_SCAN_CACHE — MCTS speedup


# Worker globals. Two model slots; if the spec's two paths are equal,
# both globals point to the same loaded model (no redundant load).
_WORKER_MODEL_P0: NormalizedValueModel | None = None
_WORKER_MODEL_P1: NormalizedValueModel | None = None
_WORKER_SPEC: _Spec | None = None


def _init_worker(spec: _Spec) -> None:
    """Pool initializer. Load each model-based seat's checkpoint once per
    worker (heuristic seats need no model) and pin BLAS to 1 thread so the
    N workers don't fight for the shared thread pool."""
    global _WORKER_MODEL_P0, _WORKER_MODEL_P1, _WORKER_SPEC
    torch.set_num_threads(1)
    # Apply the behavior-transparent MCTS legality-enumeration speedups in each
    # worker (spawn re-imports opt_config fresh, so the parent's setting doesn't
    # propagate — must be set here). See CLAUDE.md §2 / FRONTIER_OPT_DESIGN.md.
    from agricola import opt_config
    opt_config.PARETO_OPT_LEVEL = spec.opt_pareto_level
    opt_config.FENCE_SCAN_CACHE = spec.opt_fence_cache
    _WORKER_SPEC = spec
    p0_needs = spec.p0_type in _MODEL_SEATS
    p1_needs = spec.p1_type in _MODEL_SEATS
    _WORKER_MODEL_P0 = None
    _WORKER_MODEL_P1 = None
    if p0_needs:
        _WORKER_MODEL_P0 = NormalizedValueModel.load(spec.p0_model_path)
        _WORKER_MODEL_P0.eval()
    if p1_needs:
        if p0_needs and spec.p1_model_path == spec.p0_model_path:
            _WORKER_MODEL_P1 = _WORKER_MODEL_P0  # share the loaded model
        else:
            _WORKER_MODEL_P1 = NormalizedValueModel.load(spec.p1_model_path)
            _WORKER_MODEL_P1.eval()


def _model_for_seat(seat: int) -> NormalizedValueModel:
    # Only the requested seat needs a loaded model — the other seat may be a
    # heuristic (no model). Asserting both broke nn-vs-heuristic matches.
    m = _WORKER_MODEL_P0 if seat == 0 else _WORKER_MODEL_P1
    assert m is not None
    return m


def _build_mcts_agent(seed: int, seat: int) -> MCTSAgent:
    """MCTSAgent with NN leaf evaluator. `seat` ∈ {0, 1} selects which
    worker-loaded model this seat uses (P0 or P1) and offsets the RNG."""
    assert _WORKER_SPEC is not None
    model = _model_for_seat(seat)
    s = seed * 2 + seat
    rng = np.random.default_rng(s ^ 0xC0FFEE)
    strict_fn = make_strict_restricted_legal_actions(
        config=DEFAULT_CONFIG_V3, rng=rng,
    )
    heuristic = HubrisHeuristicV3(
        config=DEFAULT_CONFIG_V3,
        seed=s,
        lookahead="turn",
        legal_actions_fn=strict_fn,
    )
    search = MCTSSearch(
        evaluator_config=model,
        evaluator_fn=nn_evaluator_differential,
        heuristic=heuristic,
        legal_actions_fn=strict_fn,
        leaf_differential=False,
        # Normalize this model's leaf values to unit-ish scale so one
        # c_uct is comparable across value heads (Experiment P2). 1.0 for
        # models without a measured value_scale (pre-P2).
        leaf_value_scale=getattr(model, "value_scale", 1.0),
        n_random_fencing=_WORKER_SPEC.n_random_fencing,
        rng_seed=s,
    )
    return MCTSAgent(
        search,
        sims_per_move=_WORKER_SPEC.sims_per_move,
        c_uct=_WORKER_SPEC.c_uct,
        fpu_offset=_WORKER_SPEC.fpu_offset,
        action_selection_temperature=_WORKER_SPEC.temperature,
        rng_seed=s,
    )


def _build_nn_agent(seed: int, seat: int) -> NNAgent:
    """NNAgent (1-turn lookahead + softmax) using the seat's NN model."""
    assert _WORKER_SPEC is not None
    model = _model_for_seat(seat)
    s = seed * 2 + seat
    if _WORKER_SPEC.nn_legality == "regular":
        # Matches eval_vs_ensemble / how the ensemble configs are evaluated —
        # use for a fair NN-vs-heuristic comparison (both seats regular).
        legal_fn = restricted_legal_actions
    else:
        rng = np.random.default_rng(s ^ 0xC0FFEE)
        legal_fn = make_strict_restricted_legal_actions(
            config=DEFAULT_CONFIG_V3, rng=rng,
        )
    return NNAgent(
        model,
        differential=True,
        seed=s,
        temperature=_WORKER_SPEC.nn_temperature,
        legal_actions_fn=legal_fn,
    )


def _build_heuristic_agent(seed: int, seat: int) -> Agent:
    """Heuristic opponent seat (V3 or V1 from a tuned config). Uses the
    regular `restricted_legal_actions` — matching how these configs were
    evaluated during tuning and in eval_vs_ensemble."""
    assert _WORKER_SPEC is not None
    spec = _WORKER_SPEC
    cfg_spec = spec.p0_config if seat == 0 else spec.p1_config
    arch = spec.p0_arch if seat == 0 else spec.p1_arch
    cfg = _load_heuristic_config(cfg_spec, arch)
    s = seed * 2 + seat
    cls = HubrisHeuristicV1 if arch == "v1" else HubrisHeuristicV3
    return cls(
        seed=s, temperature=0.0, lookahead="turn",
        config=cfg, legal_actions_fn=restricted_legal_actions,
    )


def _build_seat(kind: str, seed: int, seat: int) -> Agent:
    if kind == "mcts":
        return _build_mcts_agent(seed, seat)
    if kind == "nn":
        return _build_nn_agent(seed, seat)
    if kind == "heuristic":
        return _build_heuristic_agent(seed, seat)
    raise ValueError(f"Unknown seat kind: {kind!r}")


def _winner(s0: int, s1: int, tb0: tuple, tb1: tuple) -> int | None:
    if s0 > s1:
        return 0
    if s1 > s0:
        return 1
    if tb0 > tb1:
        return 0
    if tb1 > tb0:
        return 1
    return None


def _play_one_game(seed: int) -> dict:
    assert _WORKER_SPEC is not None
    t0 = time.time()
    initial, env = setup_env(seed=seed)
    p0 = _build_seat(_WORKER_SPEC.p0_type, seed, 0)
    p1 = _build_seat(_WORKER_SPEC.p1_type, seed, 1)
    final, _trace = play_game(initial, (p0, p1), env.resolve)
    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    tb0 = tiebreaker(final, 0)
    tb1 = tiebreaker(final, 1)
    return {
        "seed": seed,
        "score_p0": s0,
        "score_p1": s1,
        "winner": _winner(s0, s1, tb0, tb1),
        "starting_player": initial.starting_player,
        "elapsed": time.time() - t0,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=str, default=None,
                   help="Path to a NormalizedValueModel checkpoint (.pt). "
                        "If given, both seats use it. Mutually exclusive "
                        "with --p0-model / --p1-model.")
    p.add_argument("--p0-model", type=str, default=None,
                   help="P0's model path. Use together with --p1-model "
                        "for asymmetric head-to-head matchups.")
    p.add_argument("--p1-model", type=str, default=None,
                   help="P1's model path.")
    p.add_argument("--p0", choices=SEAT_TYPES, default="mcts",
                   help="Agent type for P0 (default: mcts)")
    p.add_argument("--p1", choices=SEAT_TYPES, default="nn",
                   help="Agent type for P1 (default: nn)")
    p.add_argument("--p0-config", type=str, default=None,
                   help="Heuristic config for a 'heuristic' P0 seat: 't2' "
                        "or a tuned JSON path.")
    p.add_argument("--p1-config", type=str, default=None,
                   help="Heuristic config for a 'heuristic' P1 seat.")
    p.add_argument("--p0-arch", choices=["v1", "v3"], default="v3",
                   help="Arch for a 'heuristic' P0 seat (default v3).")
    p.add_argument("--p1-arch", choices=["v1", "v3"], default="v3",
                   help="Arch for a 'heuristic' P1 seat (default v3).")
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--sims", type=int, default=500,
                   help="MCTS sims/move (only used for mcts seats)")
    p.add_argument("--c-uct", type=float, default=1.4)
    p.add_argument("--n-random-fencing", type=int, default=4)
    p.add_argument("--fpu-offset", type=float, default=0.0)
    p.add_argument("--temperature", type=float, default=0.2,
                   help="MCTS action-selection softmax T")
    p.add_argument("--opt-level", type=int, default=0, choices=[0, 1, 2, 3],
                   help="agricola.opt_config.PARETO_OPT_LEVEL — behavior-transparent "
                        "MCTS legality-enumeration speedup (default 0=off; 3=all).")
    p.add_argument("--fence-cache", action="store_true", default=False,
                   help="agricola.opt_config.FENCE_SCAN_CACHE — caches the "
                        "fence-universe legality scan (the dominant MCTS speedup).")
    p.add_argument("--nn-temperature", type=float, default=0.0,
                   help="NNAgent softmax T (0.0 = argmax greedy)")
    p.add_argument("--nn-legality", choices=["strict", "regular"], default="strict",
                   help="NNAgent seat's legality wrapper. 'strict' (default) "
                        "matches prior NN-vs-NN/MCTS runs; 'regular' matches "
                        "eval_vs_ensemble — use for fair NN-vs-heuristic.")
    p.add_argument("--jobs", type=int, default=mp.cpu_count())
    p.add_argument("--seed-start", type=int, default=0)
    args = p.parse_args()

    # Resolve per-seat resources: model-based seats (nn/mcts) need a
    # checkpoint; heuristic seats need a config. `--model` is a shorthand
    # that fills any model-based seat that wasn't given an explicit path.
    def _resolve_model(seat_type, explicit):
        if seat_type not in _MODEL_SEATS:
            return None  # heuristic seat — no model
        path = explicit or args.model
        if path is None:
            print(f"ERROR: seat type '{seat_type}' needs a model "
                  f"(--model or the per-seat --pX-model).", file=sys.stderr)
            sys.exit(1)
        path = str(Path(path).resolve())
        if not Path(path).is_file():
            print(f"ERROR: model not found at {path}", file=sys.stderr)
            sys.exit(1)
        return path

    def _resolve_config(seat, seat_type, cfg):
        if seat_type != "heuristic":
            return None
        if cfg is None:
            print(f"ERROR: {seat} is 'heuristic' but no --{seat.lower()}-config given.",
                  file=sys.stderr)
            sys.exit(1)
        if cfg != "t2" and not Path(cfg).is_file():
            print(f"ERROR: {seat} config not found: {cfg}", file=sys.stderr)
            sys.exit(1)
        return cfg

    p0_model_path = _resolve_model(args.p0, args.p0_model)
    p1_model_path = _resolve_model(args.p1, args.p1_model)
    p0_config = _resolve_config("P0", args.p0, args.p0_config)
    p1_config = _resolve_config("P1", args.p1, args.p1_config)

    spec = _Spec(
        p0_model_path=p0_model_path,
        p1_model_path=p1_model_path,
        p0_type=args.p0,
        p1_type=args.p1,
        p0_config=p0_config,
        p1_config=p1_config,
        p0_arch=args.p0_arch,
        p1_arch=args.p1_arch,
        sims_per_move=args.sims,
        c_uct=args.c_uct,
        n_random_fencing=args.n_random_fencing,
        fpu_offset=args.fpu_offset,
        temperature=args.temperature,
        nn_temperature=args.nn_temperature,
        nn_legality=args.nn_legality,
        opt_pareto_level=args.opt_level,
        opt_fence_cache=args.fence_cache,
    )
    seeds = list(range(args.seed_start, args.seed_start + args.n))

    def _seat_desc(t, model, cfg, arch):
        if t == "heuristic":
            return f"heuristic[{arch}] {cfg}"
        return f"{t} {model}"
    print(f"NN match: P0={args.p0} vs P1={args.p1}")
    print(f"  P0: {_seat_desc(args.p0, p0_model_path, p0_config, args.p0_arch)}")
    print(f"  P1: {_seat_desc(args.p1, p1_model_path, p1_config, args.p1_arch)}")
    print(f"  sims:     {args.sims} (mcts seats only)")
    print(f"  c_uct:    {args.c_uct}")
    print(f"  n_random_fencing: {args.n_random_fencing}")
    print(f"  fpu_offset: {args.fpu_offset}")
    print(f"  mcts_temperature: {args.temperature}")
    print(f"  nn_temperature: {args.nn_temperature}")
    print(f"  opt: PARETO_OPT_LEVEL={args.opt_level} FENCE_SCAN_CACHE={args.fence_cache}")
    print(f"  games:    {args.n} (seeds {args.seed_start}..{args.seed_start + args.n - 1})")
    print(f"  jobs:     {args.jobs}")
    print()

    t0 = time.time()
    wins0 = wins1 = draws = 0
    sum_margin = 0
    results: list[dict] = []
    with mp.Pool(args.jobs, initializer=_init_worker, initargs=(spec,)) as pool:
        for i, r in enumerate(pool.imap_unordered(_play_one_game, seeds), start=1):
            results.append(r)
            margin = r["score_p0"] - r["score_p1"]
            sum_margin += margin
            if r["winner"] == 0:
                wins0 += 1
                tag = "P0"
            elif r["winner"] == 1:
                wins1 += 1
                tag = "P1"
            else:
                draws += 1
                tag = "draw"
            elapsed = time.time() - t0
            eta = elapsed / i * (len(seeds) - i)
            print(f"[{i:3d}/{len(seeds)}] seed={r['seed']:3d} SP={r['starting_player']} "
                  f"P0={r['score_p0']:3d} P1={r['score_p1']:3d} ({tag})  "
                  f"P0W={wins0} P1W={wins1} D={draws}  "
                  f"avgM={sum_margin/i:+.2f}  "
                  f"t={r['elapsed']:.1f}s elapsed={elapsed:.0f}s eta={eta:.0f}s",
                  flush=True)

    total = time.time() - t0
    print()
    print(f"Final: P0={wins0}  P1={wins1}  D={draws}  "
          f"avg margin (P0-P1)={sum_margin/len(seeds):+.2f}")
    print(f"Total elapsed: {total:.0f}s ({total/len(seeds):.1f}s/game avg)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
