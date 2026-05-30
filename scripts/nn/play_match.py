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

from agricola.agents import (  # noqa: E402
    DEFAULT_CONFIG_V3,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    make_strict_restricted_legal_actions,
)
from agricola.agents.base import Agent, play_game  # noqa: E402
from agricola.agents.nn.agent import NNAgent, nn_evaluator_differential  # noqa: E402
from agricola.agents.nn.model import NormalizedValueModel  # noqa: E402
from agricola.scoring import score, tiebreaker  # noqa: E402
from agricola.setup import setup  # noqa: E402


SEAT_TYPES = ("mcts", "nn")


# ---------------------------------------------------------------------------
# Worker globals & spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    """Per-match config. Picklable — passed to worker init."""
    p0_model_path: str
    p1_model_path: str
    p0_type: str   # "mcts" or "nn"
    p1_type: str
    sims_per_move: int
    c_uct: float
    n_random_fencing: int
    fpu_offset: float
    temperature: float
    nn_temperature: float


# Worker globals. Two model slots; if the spec's two paths are equal,
# both globals point to the same loaded model (no redundant load).
_WORKER_MODEL_P0: NormalizedValueModel | None = None
_WORKER_MODEL_P1: NormalizedValueModel | None = None
_WORKER_SPEC: _Spec | None = None


def _init_worker(spec: _Spec) -> None:
    """Pool initializer. Load each seat's model once per worker and pin
    BLAS to 1 thread so the N workers don't fight for the shared thread
    pool."""
    global _WORKER_MODEL_P0, _WORKER_MODEL_P1, _WORKER_SPEC
    torch.set_num_threads(1)
    _WORKER_SPEC = spec
    _WORKER_MODEL_P0 = NormalizedValueModel.load(spec.p0_model_path)
    _WORKER_MODEL_P0.eval()
    if spec.p1_model_path == spec.p0_model_path:
        _WORKER_MODEL_P1 = _WORKER_MODEL_P0  # share the loaded model
    else:
        _WORKER_MODEL_P1 = NormalizedValueModel.load(spec.p1_model_path)
        _WORKER_MODEL_P1.eval()


def _model_for_seat(seat: int) -> NormalizedValueModel:
    assert _WORKER_MODEL_P0 is not None and _WORKER_MODEL_P1 is not None
    return _WORKER_MODEL_P0 if seat == 0 else _WORKER_MODEL_P1


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
    rng = np.random.default_rng(s ^ 0xC0FFEE)
    strict_fn = make_strict_restricted_legal_actions(
        config=DEFAULT_CONFIG_V3, rng=rng,
    )
    return NNAgent(
        model,
        differential=True,
        seed=s,
        temperature=_WORKER_SPEC.nn_temperature,
        legal_actions_fn=strict_fn,
    )


def _build_seat(kind: str, seed: int, seat: int) -> Agent:
    if kind == "mcts":
        return _build_mcts_agent(seed, seat)
    if kind == "nn":
        return _build_nn_agent(seed, seat)
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
    initial = setup(seed=seed)
    p0 = _build_seat(_WORKER_SPEC.p0_type, seed, 0)
    p1 = _build_seat(_WORKER_SPEC.p1_type, seed, 1)
    final, _trace = play_game(initial, (p0, p1))
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
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--sims", type=int, default=500,
                   help="MCTS sims/move (only used for mcts seats)")
    p.add_argument("--c-uct", type=float, default=1.4)
    p.add_argument("--n-random-fencing", type=int, default=4)
    p.add_argument("--fpu-offset", type=float, default=0.0)
    p.add_argument("--temperature", type=float, default=0.2,
                   help="MCTS action-selection softmax T")
    p.add_argument("--nn-temperature", type=float, default=0.0,
                   help="NNAgent softmax T (0.0 = argmax greedy)")
    p.add_argument("--jobs", type=int, default=mp.cpu_count())
    p.add_argument("--seed-start", type=int, default=0)
    args = p.parse_args()

    # Resolve per-seat model paths.
    if args.model is not None:
        if args.p0_model is not None or args.p1_model is not None:
            print("ERROR: --model is mutually exclusive with --p0-model / --p1-model",
                  file=sys.stderr)
            return 1
        p0_model_path = p1_model_path = str(Path(args.model).resolve())
    else:
        if args.p0_model is None or args.p1_model is None:
            print("ERROR: must supply either --model OR both --p0-model and --p1-model",
                  file=sys.stderr)
            return 1
        p0_model_path = str(Path(args.p0_model).resolve())
        p1_model_path = str(Path(args.p1_model).resolve())
    for label, path in (("P0", p0_model_path), ("P1", p1_model_path)):
        if not Path(path).is_file():
            print(f"ERROR: {label} model not found at {path}", file=sys.stderr)
            return 1

    spec = _Spec(
        p0_model_path=p0_model_path,
        p1_model_path=p1_model_path,
        p0_type=args.p0,
        p1_type=args.p1,
        sims_per_move=args.sims,
        c_uct=args.c_uct,
        n_random_fencing=args.n_random_fencing,
        fpu_offset=args.fpu_offset,
        temperature=args.temperature,
        nn_temperature=args.nn_temperature,
    )
    seeds = list(range(args.seed_start, args.seed_start + args.n))

    print(f"NN match: P0={args.p0} vs P1={args.p1}")
    if p0_model_path == p1_model_path:
        print(f"  model:    {p0_model_path}")
    else:
        print(f"  P0 model: {p0_model_path}")
        print(f"  P1 model: {p1_model_path}")
    print(f"  sims:     {args.sims} (mcts seats only)")
    print(f"  c_uct:    {args.c_uct}")
    print(f"  n_random_fencing: {args.n_random_fencing}")
    print(f"  fpu_offset: {args.fpu_offset}")
    print(f"  mcts_temperature: {args.temperature}")
    print(f"  nn_temperature: {args.nn_temperature}")
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
