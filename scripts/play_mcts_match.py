"""Run MCTS vs a chosen opponent over a list of seeds and report aggregates.

Built on `scripts/play_match.py`'s pattern: each game's seed maps to per-
agent RNG seeds, then `play_game` drives the engine to completion and
`play_match` aggregates. Adds an MCTS-specific factory and per-MCTS
configuration flags (sims_per_move, c_uct, n_random_fencing, etc.).

Quick examples:

    # 10-game smoke at low sim budget
    python scripts/play_mcts_match.py --opponent hubris_v3 --sims 100 --n 10

    # Production validation against the current strongest V3
    python scripts/play_mcts_match.py --opponent hubris_v3 \\
        --v3-config tuned_configs/v3_best.json \\
        --sims 500 --n 100

    # MCTS-vs-MCTS with different c_uct (separate trees)
    python scripts/play_mcts_match.py --opponent mcts --sims 500 \\
        --c-uct 1.0 --opp-c-uct 2.0 --n 30

    # PUCT (uniform prior, regular legality, flatten fencing) vs UCT+strict
    python scripts/play_mcts_match.py --opponent mcts \\
        --policy uniform --legality regular --fence-mode flatten \\
        --opp-legality strict --sims 500 --n 30

The MCTS seat plays as P0 by default. Use `--mcts-as-p1` to swap seats.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np

# Make `agricola` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import (
    CONFIG_V3_T1,
    DEFAULT_CONFIG_V3,
    FenceMode,
    HeuristicConfigV3,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    RandomAgent,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
    uniform_policy,
)
from agricola.agents.base import Agent, play_game
from agricola.scoring import score, tiebreaker
from agricola.setup import setup, setup_env

# Reuse the play_match library for the aggregation logic.
sys.path.insert(0, str(ROOT / "scripts"))
from play_match import AgentFactory, GameResult, MatchResult, play_match, _winner


# ---------------------------------------------------------------------------
# Agent factories
# ---------------------------------------------------------------------------

def _load_v3_config(path: str | None):
    """Resolve a V3 config: None → DEFAULT_CONFIG_V3, 'v3_t1' → CONFIG_V3_T1,
    'default_v3' → DEFAULT_CONFIG_V3, else JSON path (loads `best_config`).
    """
    if path is None or path == "default_v3":
        return DEFAULT_CONFIG_V3
    if path == "v3_t1":
        return CONFIG_V3_T1
    with open(path) as f:
        payload = json.load(f)
    return HeuristicConfigV3(**payload["best_config"])


_FENCE_MODES = {
    "macro": FenceMode.MACRO,
    "flatten": FenceMode.FLATTEN,
    "sequence_prior": FenceMode.SEQUENCE_PRIOR,
}


@functools.lru_cache(maxsize=2)
def _combined_policy(variant: str):
    """Load + assemble the combined multi-head `policy_fn` for `variant`
    ('unweighted' | 'awr'). lru_cache'd so each worker process loads the 9
    head checkpoints ONCE, not once per game (the build loads ~9 torch
    checkpoints, so the per-game reload was a real cost over a 100+ game run).
    """
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent / "nn" / "build_combined_policy.py"
    spec = importlib.util.spec_from_file_location("build_combined_policy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build(variant)


def _resolve_policy(spec_str: str):
    """Map a `--policy` value to a `policy_fn` for `MCTSSearch`.

    - 'uct'                 → None (vanilla UCT, no prior)
    - 'uniform'             → `uniform_policy` (the c0 PUCT placeholder prior)
    - 'combined:unweighted' → the trained multi-head combiner (unweighted-CE heads)
    - 'combined:awr'        → the trained multi-head combiner (AWR heads)

    The combiner is built in-worker (it loads torch checkpoints), via
    `scripts/nn/build_combined_policy.build(variant)`, memoized by `_combined_policy`.
    """
    if spec_str == "uct":
        return None
    if spec_str == "uniform":
        return uniform_policy
    if spec_str.startswith("combined:"):
        return _combined_policy(spec_str.split(":", 1)[1])
    raise ValueError(
        f"--policy={spec_str!r}: expected 'uct', 'uniform', 'combined:unweighted', "
        "or 'combined:awr'."
    )


@functools.lru_cache(maxsize=4)
def _value_model(path: str):
    """Load a value-net checkpoint for use as the MCTS leaf evaluator. Cached
    per worker process so repeated agent construction reuses one load.

    NB `NormalizedValueModel.load` leaves the model in TRAIN mode, so we must
    `.eval()` it here — otherwise dropout fires on every leaf query and the
    MCTS leaf values are stochastic noise. (mcts-vs-mcts games build no NNAgent
    to incidentally eval the shared cached model, so without this they'd run
    with dropout active.)"""
    from agricola.agents.nn.model import NormalizedValueModel
    model = NormalizedValueModel.load(path)
    model.eval()
    return model


def _is_shared_trunk(path: str) -> bool:
    """True if `path` is a joint `SharedTrunkModel` checkpoint (meta model_kind)
    — i.e. value + policy come off one trunk, consumed via `make_joint_fns`."""
    import json
    from pathlib import Path
    try:
        return json.loads(
            Path(path).with_suffix(".meta.json").read_text()
        ).get("model_kind") == "shared_trunk"
    except Exception:
        return False


def _mcts_factory(
    *,
    seed_offset: int,
    config,
    sims_per_move: int,
    c_uct: float,
    n_random_fencing: int,
    temperature: float,
    fpu_offset: float,
) -> AgentFactory:
    def factory(game_seed: int) -> Agent:
        s = game_seed + seed_offset
        search = MCTSSearch(
            evaluator_config=config,
            n_random_fencing=n_random_fencing,
            rng_seed=s,
        )
        return MCTSAgent(
            search,
            sims_per_move=sims_per_move,
            c_uct=c_uct,
            fpu_offset=fpu_offset,
            action_selection_temperature=temperature,
            rng_seed=s,
        )
    return factory


def _opponent_factory(
    name: str,
    *,
    seed_offset: int,
    config,
    sims_per_move: int,
    c_uct: float,
    n_random_fencing: int,
    temperature: float,
    fpu_offset: float,
) -> AgentFactory:
    """Build the opponent factory. The heuristic opponent uses the SAME
    legal_actions_fn (strict-restricted) as MCTS for a fair comparison —
    matches what MCTS itself consults at every legality check, and aligns
    with the training pipeline's default (CHANGES.md Change 11).
    """
    if name == "mcts":
        return _mcts_factory(
            seed_offset=seed_offset, config=config,
            sims_per_move=sims_per_move, c_uct=c_uct,
            n_random_fencing=n_random_fencing,
            temperature=temperature, fpu_offset=fpu_offset,
        )

    def factory(game_seed: int) -> Agent:
        s = game_seed + seed_offset
        # A per-game RNG for the strict wrapper so cap-random samples are
        # deterministic per (game, seat).
        strict_fn = make_strict_restricted_legal_actions(
            config=config, rng=np.random.default_rng(s ^ 0xC0FFEE),
        )
        if name == "hubris_v3":
            return HubrisHeuristicV3(
                seed=s, temperature=0.0, lookahead="turn",
                config=config, legal_actions_fn=strict_fn,
            )
        if name == "random":
            return RandomAgent(seed=s, legal_actions_fn=strict_fn)
        raise ValueError(
            f"Unknown opponent {name!r}; choose from mcts / hubris_v3 / random"
        )
    return factory


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

OPPONENT_TYPES = ("hubris_v3", "random", "mcts", "nn", "t2")


# ---------------------------------------------------------------------------
# Parallel match runner
# ---------------------------------------------------------------------------
#
# multiprocessing.Pool with a worker initializer that stashes the per-match
# configuration in module-level globals (mirroring tune_heuristic.py's
# pattern). Agents are constructed inside the worker per game — avoids
# pickling MCTSSearch's transposition table, which would be expensive and
# may contain self-referential MCTSNode → MCTSSearch back-refs that don't
# pickle cleanly.


@dataclass(frozen=True)
class _MatchSpec:
    """Everything a worker needs to play one game. All fields are pickle-
    friendly primitives or the HeuristicConfigV3 dataclass."""
    config_v3: HeuristicConfigV3
    p0_name: str            # "mcts" or one of the opponent types
    p1_name: str
    sims_per_move: int
    opp_sims_per_move: int  # only relevant if opponent is also mcts
    c_uct: float
    opp_c_uct: float
    n_random_fencing: int
    fpu_offset: float
    temperature: float
    # PUCT / legality knobs (per-seat; opp_* used when the opponent is also mcts).
    legality: str = "strict"            # "strict" | "regular"
    opp_legality: str = "strict"
    fence_mode: str = "macro"           # "macro" | "flatten" | "sequence_prior"
    opp_fence_mode: str = "macro"
    policy: str = "uct"                 # "uct" | "uniform" | "combined:unweighted" | "combined:awr"
    opp_policy: str = "uct"
    # Fence-macro generator (UCT/MACRO only): sample fence chains from this
    # policy instead of the expensive value-net greedy rollout. "none" = the
    # default greedy+random macros.
    macro_policy: str = "none"          # "none" | "uniform" | "combined:unweighted" | "combined:awr"
    opp_macro_policy: str = "none"
    leaf: str = "v3"                    # "v3" (heuristic) | "nn" (value net)
    opp_leaf: str = "v3"
    leaf_ckpt: str = "nn_models/best"   # (leaf == "nn") value-net checkpoint
    opp_leaf_ckpt: str = "nn_models/best"
    leaf_value_scale: float | None = None   # None → auto (model.value_scale for nn, else 1.0)
    opp_leaf_value_scale: float | None = None
    # NN leaf 2-pass-average toggle (selects the evaluator; NOT an MCTS flag):
    # False (default) = nn_evaluator, 1 forward pass (speed); True =
    # nn_evaluator_differential, the MEAN of both perspectives (e(s,0)-e(s,1))/2
    # — lower variance, SAME scale (so c stays calibrated across it).
    two_pass: bool = False
    opp_two_pass: bool = False
    # MCTS legality-enumeration speedups (FRONTIER_OPT_DESIGN.md). None = inherit
    # the agricola.opt_config module default (now ON); set an int/bool to override.
    # Both seats share these (they're global).
    opt_pareto_level: int | None = None  # agricola.opt_config.PARETO_OPT_LEVEL (0-3)
    opt_fence_cache: bool | None = None  # agricola.opt_config.FENCE_SCAN_CACHE
    # When True, sims_per_move caps the TOTAL root visit count (inherited via
    # tree reuse + fresh) instead of the count of fresh sims. Equalizes the
    # per-decision search budget across moves regardless of inheritance —
    # removes the tree-reuse confound where peaked PUCT trees inherit more
    # effective sims than flatter UCT trees. Applies to BOTH seats and to both
    # UCT and PUCT (the MCTSAgent loop is policy-agnostic).
    cap_total_sims: bool = False


_WORKER_SPEC: _MatchSpec | None = None


def _init_worker(spec: _MatchSpec) -> None:
    """Pool initializer: stash the match config in worker globals so each
    `_play_one_game` call can read it without re-passing on every task.

    Also applies the behavior-transparent MCTS legality-enumeration speedups
    in THIS worker — spawn re-imports `opt_config` fresh, so the parent's
    setting doesn't propagate and must be set here (mirrors nn/play_match.py).
    """
    from agricola import opt_config
    if spec.opt_pareto_level is not None:
        opt_config.PARETO_OPT_LEVEL = spec.opt_pareto_level
    if spec.opt_fence_cache is not None:
        opt_config.FENCE_SCAN_CACHE = spec.opt_fence_cache
    global _WORKER_SPEC
    _WORKER_SPEC = spec


def _build_agent(
    name: str, *, game_seed: int, seed_offset: int, spec: _MatchSpec,
    is_opponent: bool,
) -> Agent:
    """Construct an agent for one seat. Mirrors `_opponent_factory` but
    inline so it can be pickled / called from worker processes.

    `is_opponent` selects between the two MCTS budget knobs
    (sims_per_move vs opp_sims_per_move, c_uct vs opp_c_uct) when both
    seats are MCTS.
    """
    s = game_seed + seed_offset
    if name == "mcts":
        sims = spec.opp_sims_per_move if is_opponent else spec.sims_per_move
        c = spec.opp_c_uct if is_opponent else spec.c_uct
        legality = spec.opp_legality if is_opponent else spec.legality
        fmode = spec.opp_fence_mode if is_opponent else spec.fence_mode
        policy = spec.opp_policy if is_opponent else spec.policy
        macro_policy = spec.opp_macro_policy if is_opponent else spec.macro_policy
        leaf = spec.opp_leaf if is_opponent else spec.leaf
        leaf_ckpt = spec.opp_leaf_ckpt if is_opponent else spec.leaf_ckpt
        lvs = spec.opp_leaf_value_scale if is_opponent else spec.leaf_value_scale
        two_pass = spec.opp_two_pass if is_opponent else spec.two_pass
        # Leaf evaluator FIRST (the strict wrapper below ranks its feed-cap with
        # the SAME value function): V3 heuristic (default) or the value net. The
        # NN leaf uses an already-P0-frame-margin evaluator (2-pass off by
        # default) and calibrates c_uct via the model's value_scale
        # unless overridden. `feed_evaluator` is the (state, player) -> float
        # ranker handed to the strict wrapper — the NN when leaf=nn, else None
        # (the wrapper then builds its V3 default from config).
        joint_policy_fn = None   # set when the leaf is a joint shared-trunk model
        if leaf == "nn":
            from agricola.agents.nn.agent import (
                nn_evaluator, nn_evaluator_differential,
            )
            if _is_shared_trunk(leaf_ckpt):
                # Joint shared-trunk model: value AND policy come off ONE trunk
                # (make_joint_fns — one forward per node). The model's own heads
                # ARE the policy, so it overrides --policy below. value_fn already
                # returns a P0-frame margin (decider-frame, sign-flipped).
                from agricola.agents.nn.shared_model import SharedTrunkModel
                from agricola.agents.nn.shared_policy import make_joint_fns
                model = SharedTrunkModel.load(leaf_ckpt)
                model.eval()
                value_fn, joint_policy_fn = make_joint_fns(model)
                eval_kwargs = dict(evaluator_config=model, evaluator_fn=value_fn)
                lvs_final = lvs if lvs is not None else float(getattr(model, "value_scale", 1.0))
                feed_evaluator = value_fn
            else:
                # NN leaf = a P0-frame margin estimate, ALWAYS on the e(s,0) ~1x
                # margin scale, so one leaf_value_scale serves both modes and a
                # calibrated c is toggle-invariant. The 2-pass-average toggle
                # (two_pass):
                #   off: nn_evaluator — plain e(s,0), 1 forward pass (speed).
                #   on : nn_evaluator_differential — the MEAN (e(s,0)-e(s,1))/2,
                #        lower variance, SAME scale, 1 batched 2-input pass.
                # Both already return a P0-frame margin (the /2 now lives inside
                # nn_evaluator_differential), so the leaf calls them once.
                model = _value_model(leaf_ckpt)
                ev_fn = nn_evaluator_differential if two_pass else nn_evaluator
                eval_kwargs = dict(evaluator_config=model, evaluator_fn=ev_fn)
                # Stored value_scale is the std of the (mean-form) differential leaf,
                # already on the e(s,0) scale — use it directly for both modes.
                lvs_final = lvs if lvs is not None else float(getattr(model, "value_scale", 1.0))
                feed_evaluator = (lambda st, p, _m=model: nn_evaluator(st, p, _m))
        else:
            eval_kwargs = dict(evaluator_config=spec.config_v3)
            lvs_final = lvs if lvs is not None else 1.0
            feed_evaluator = None
        # Legality wrapper. full = no restriction (policy is the sole prune for
        # PUCT); regular = restricted_legal_actions; strict = the MCTS-curated
        # wrapper, whose harvest-feed cap is RNG-bound and ranks with
        # `feed_evaluator` (the NN when leaf=nn — so strict is V3-free for an NN
        # agent — else the wrapper's V3 default).
        if legality == "full":
            from agricola.legality import legal_actions as legal_fn
        elif legality == "regular":
            legal_fn = restricted_legal_actions
        else:
            legal_fn = make_strict_restricted_legal_actions(
                config=spec.config_v3, rng=np.random.default_rng(s ^ 0xC0FFEE),
                evaluator=feed_evaluator,
            )
        # Fence-macro generator (UCT/MACRO only): "none" → default greedy+random
        # macros; otherwise sample fence chains from this policy (cheap).
        macro_policy_fn = (
            None if macro_policy in ("none", "uct")
            else _resolve_policy(macro_policy)
        )
        search = MCTSSearch(
            n_random_fencing=spec.n_random_fencing,
            rng_seed=s,
            legal_actions_fn=legal_fn,
            fence_mode=_FENCE_MODES[fmode],
            policy_fn=joint_policy_fn if joint_policy_fn is not None
            else _resolve_policy(policy),
            macro_policy_fn=macro_policy_fn,
            leaf_value_scale=lvs_final,
            **eval_kwargs,
        )
        return MCTSAgent(
            search,
            sims_per_move=sims,
            c_uct=c,
            fpu_offset=spec.fpu_offset,
            action_selection_temperature=spec.temperature,
            rng_seed=s,
            cap_total_sims=spec.cap_total_sims,
        )
    if name == "nn":
        # 1-turn greedy NN lookahead (the champion NNAgent, M_82k_warmM62k).
        # Uses REGULAR restricted legality — NNAgent's documented/eval config
        # (eval_vs_ensemble) and a deliberate confound vs UCT(strict) / PUCT(full).
        # T=0 (argmax greedy); the value model is the seat's leaf checkpoint.
        from agricola.agents.nn.agent import NNAgent
        ckpt = spec.opp_leaf_ckpt if is_opponent else spec.leaf_ckpt
        model = _value_model(ckpt)
        return NNAgent(
            model, differential=False, seed=s, temperature=0.0,
            legal_actions_fn=restricted_legal_actions,
        )
    # Non-MCTS opponent. Use the same strict-restricted legality as MCTS
    # (matches the training pipeline default).
    strict_fn = make_strict_restricted_legal_actions(
        config=spec.config_v3, rng=np.random.default_rng(s ^ 0xC0FFEE),
    )
    if name == "hubris_v3":
        return HubrisHeuristicV3(
            seed=s, temperature=0.0, lookahead="turn",
            config=spec.config_v3, legal_actions_fn=strict_fn,
        )
    if name == "t2":
        # The ensemble's lone V1-arch member (HubrisHeuristicV1 + CONFIG_V1_T2).
        # Agent uses the V1 config; the strict legality wrapper stays on the V3
        # config (it's an action-pruning prior, arch-independent) for parity
        # with the other ensemble opponents.
        from agricola.agents import CONFIG_V1_T2, HubrisHeuristicV1
        return HubrisHeuristicV1(
            seed=s, temperature=0.0, lookahead="turn",
            config=CONFIG_V1_T2, legal_actions_fn=strict_fn,
        )
    if name == "random":
        return RandomAgent(seed=s, legal_actions_fn=strict_fn)
    raise ValueError(f"Unknown agent name {name!r}")


def _play_one_game(seed: int) -> GameResult:
    """Top-level worker function (pickleable). Plays one game per seed
    and returns a GameResult. Reads config from `_WORKER_SPEC` globals."""
    assert _WORKER_SPEC is not None, "worker globals not initialized"
    spec = _WORKER_SPEC
    initial, env = setup_env(seed=seed)
    p0 = _build_agent(spec.p0_name, game_seed=seed, seed_offset=0,
                       spec=spec, is_opponent=(spec.p0_name != "mcts"))
    # When both seats are MCTS, P0=mcts (not opponent), P1=mcts (opponent).
    # When P0 is mcts and P1 is the opponent, P1 is the opponent.
    # When P0 is the opponent (--mcts-as-p1) and P1 is mcts, P0 IS the
    # opponent.
    p1 = _build_agent(spec.p1_name, game_seed=seed, seed_offset=1,
                       spec=spec, is_opponent=(spec.p1_name != "mcts" or spec.p0_name == "mcts"))
    final, _trace = play_game(initial, (p0, p1), env.resolve)
    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    tb0 = tiebreaker(final, 0)
    tb1 = tiebreaker(final, 1)
    return GameResult(
        seed=seed,
        score_p0=s0, score_p1=s1,
        tiebreaker_p0=tb0, tiebreaker_p1=tb1,
        starting_player=initial.starting_player,
        winner=_winner(s0, s1, tb0, tb1),
    )


def _aggregate(games: list[GameResult], elapsed: float) -> MatchResult:
    """Aggregate per-game results into a MatchResult. Matches
    `play_match.play_match`'s reducer logic."""
    n = len(games)
    p0_wins = sum(1 for g in games if g.winner == 0)
    p1_wins = sum(1 for g in games if g.winner == 1)
    draws   = sum(1 for g in games if g.winner is None)
    avg_p0  = sum(g.score_p0 for g in games) / n if n else 0.0
    avg_p1  = sum(g.score_p1 for g in games) / n if n else 0.0
    return MatchResult(
        n_games=n,
        p0_wins=p0_wins, p1_wins=p1_wins, draws=draws,
        avg_score_p0=avg_p0, avg_score_p1=avg_p1,
        avg_margin=avg_p0 - avg_p1,
        elapsed_seconds=elapsed,
        per_game=tuple(games),
    )


def play_match_parallel(
    spec: _MatchSpec, seeds: list[int], *, jobs: int, progress: bool = True,
) -> MatchResult:
    """Run all games in parallel via multiprocessing.Pool.

    `jobs` workers each process a chunk of seeds. For best throughput,
    pick `len(seeds)` as a multiple of `jobs` so the final batch is full
    (a 10-seed run on 8 cores wastes 6 cores during the trailing batch
    of 2; 16 seeds on 8 cores fills both batches).

    `progress=True` prints one line per completed game (in completion
    order, not seed order) including running win/loss tally and ETA.
    Output is unbuffered (`flush=True`) so it's visible immediately when
    piped through `tee` or redirected to a file.
    """
    t0 = time.perf_counter()
    n_total = len(seeds)
    games: list[GameResult] = []

    def _emit(g: GameResult, completed: int) -> None:
        if not progress:
            return
        wins_so_far = sum(1 for x in games if x.winner == 0)
        losses_so_far = sum(1 for x in games if x.winner == 1)
        draws_so_far = sum(1 for x in games if x.winner is None)
        elapsed = time.perf_counter() - t0
        rate = elapsed / completed
        remaining = rate * (n_total - completed)
        margin_so_far = sum(x.score_p0 - x.score_p1 for x in games) / completed
        winner_str = ("P0" if g.winner == 0 else "P1" if g.winner == 1 else "tie")
        print(
            f"  [{completed:>3}/{n_total}] seed={g.seed:>3} "
            f"P0={g.score_p0:>3} P1={g.score_p1:>3} → {winner_str:>3} | "
            f"tally P0 {wins_so_far}-{draws_so_far}-{losses_so_far} P1, "
            f"avg margin {margin_so_far:+.2f} | "
            f"elapsed {elapsed/60:.1f}m, ETA {remaining/60:.1f}m",
            flush=True,
        )

    if jobs <= 1:
        # Sequential — useful for debugging / tracebacks. Skips the Pool.
        _init_worker(spec)
        for i, s in enumerate(seeds, start=1):
            g = _play_one_game(s)
            games.append(g)
            _emit(g, i)
    else:
        with Pool(processes=jobs, initializer=_init_worker, initargs=(spec,)) as pool:
            for i, g in enumerate(
                pool.imap_unordered(_play_one_game, seeds, chunksize=1),
                start=1,
            ):
                games.append(g)
                _emit(g, i)
        # imap_unordered returns games in completion order; sort by seed for
        # deterministic per-game output (the `--per-game` table later).
        games.sort(key=lambda g: g.seed)
    elapsed = time.perf_counter() - t0
    return _aggregate(games, elapsed)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opponent", choices=OPPONENT_TYPES, default="hubris_v3",
                   help="The non-MCTS seat: hubris_v3 / random / nn (1-turn NNAgent, "
                        "regular legality, uses --opp-leaf-ckpt). (Or 'mcts' for MCTS-vs-MCTS.)")
    p.add_argument("--mcts-as-p1", action="store_true",
                   help="Place MCTS at P1 instead of P0.")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--seeds", type=str, default=None,
                       help="Seed spec ('0-29' or '0,5,10'). Default: '0-{n-1}'.")
    group.add_argument("--n", type=int, default=10,
                       help="Number of games (uses seeds 0..n-1). Default 10.")
    p.add_argument("--v3-config", type=str, default=None,
                   help="Path to JSON config for the V3 evaluator. Defaults "
                        "to DEFAULT_CONFIG_V3. Use 'v3_t1' for CONFIG_V3_T1.")
    p.add_argument("--sims", type=int, default=500,
                   help="MCTS simulations per move. Default 500.")
    p.add_argument("--opp-sims", type=int, default=None,
                   help="MCTS sims/move for the opponent (--opponent mcts only). "
                        "Default = --sims.")
    p.add_argument("--c-uct", type=float, default=1.4)
    p.add_argument("--opp-c-uct", type=float, default=None,
                   help="c_uct for the opponent MCTS. Default = --c-uct.")
    p.add_argument("--n-random-fencing", type=int, default=4)
    p.add_argument("--fpu-offset", type=float, default=0.0)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--legality", choices=("strict", "regular", "full"), default="strict",
                   help="Legality wrapper for the MCTS seat. Use 'full' for the "
                        "combined-policy PUCT eval (the policy is the sole prune); "
                        "'strict' is the existing UCT baseline.")
    p.add_argument("--opp-legality", choices=("strict", "regular", "full"), default=None,
                   help="Legality for the opponent MCTS. Default = --legality.")
    p.add_argument("--fence-mode", choices=("macro", "flatten", "sequence_prior"),
                   default="macro",
                   help="Fencing handling. PUCT requires 'flatten' (auto-coerced "
                        "from 'macro' when --policy is set). Default 'macro' (UCT).")
    p.add_argument("--opp-fence-mode", choices=("macro", "flatten", "sequence_prior"),
                   default=None, help="Fence mode for the opponent MCTS. Default = --fence-mode.")
    p.add_argument("--policy", type=str, default="uct",
                   help="MCTS prior: 'uct' (no prior), 'uniform' (PUCT placeholder "
                        "prior), 'combined:unweighted', or 'combined:awr' (trained "
                        "multi-head policy).")
    p.add_argument("--opp-policy", type=str, default=None,
                   help="Prior for the opponent MCTS. Default = --policy.")
    p.add_argument("--macro-policy", type=str, default="none",
                   help="UCT+MACRO only: generate fence macros by SAMPLING this "
                        "policy ('combined:unweighted'|'combined:awr'|'uniform') "
                        "instead of the expensive value-net greedy rollout. "
                        "'none' (default) = greedy+random macros. Selection stays "
                        "UCB (this is not a PUCT prior).")
    p.add_argument("--opp-macro-policy", type=str, default=None,
                   help="Fence-macro policy for the opponent MCTS. Default = --macro-policy.")
    p.add_argument("--leaf", choices=("v3", "nn"), default="v3",
                   help="MCTS leaf evaluator: 'v3' (heuristic) or 'nn' (value net).")
    p.add_argument("--leaf-ckpt", type=str, default="nn_models/best",
                   help="(--leaf nn) value-net checkpoint for the leaf evaluator.")
    p.add_argument("--opp-leaf", choices=("v3", "nn"), default=None,
                   help="Leaf evaluator for the opponent MCTS. Default = --leaf.")
    p.add_argument("--opp-leaf-ckpt", type=str, default=None,
                   help="(--opp-leaf nn) opponent value-net checkpoint. Default = --leaf-ckpt.")
    p.add_argument("--leaf-value-scale", type=float, default=None,
                   help="Divide leaf values by this (calibrates c_uct / c_puct). "
                        "Default: auto — 1.0 for the V3 leaf, the model's value_scale "
                        "for an NN leaf.")
    p.add_argument("--opp-leaf-value-scale", type=float, default=None,
                   help="leaf_value_scale for the opponent MCTS. Default = --leaf-value-scale.")
    p.add_argument("--two-pass", action=argparse.BooleanOptionalAction, default=False,
                   help="(--leaf nn) 2-pass-average toggle. Off (default): nn_evaluator, "
                        "1 forward pass (speed, for many-game runs). On: "
                        "nn_evaluator_differential, the MEAN of both perspectives "
                        "(lower variance, SAME scale, 1 batched 2-input pass; full "
                        "strength — e.g. vs a human). Same scale → c calibrated across it.")
    p.add_argument("--opp-two-pass", action=argparse.BooleanOptionalAction, default=None,
                   help="--two-pass for the opponent MCTS. Default = --two-pass.")
    p.add_argument("--opt-level", type=int, default=None, choices=[0, 1, 2, 3],
                   help="agricola.opt_config.PARETO_OPT_LEVEL override. Default: "
                        "inherit the module default (ON=3). Pass 0 for byte-identical.")
    p.add_argument("--fence-cache", action=argparse.BooleanOptionalAction, default=None,
                   help="agricola.opt_config.FENCE_SCAN_CACHE override (--fence-cache / "
                        "--no-fence-cache). Default: inherit the module default (ON).")
    p.add_argument("--cap-total-sims", action="store_true",
                   help="Cap TOTAL root visits (inherited via tree reuse + fresh) "
                        "at --sims, instead of running --sims fresh sims per move. "
                        "Equalizes the per-decision search budget across moves, "
                        "removing the tree-reuse confound where peaked PUCT trees "
                        "inherit more effective sims. Applies to both seats.")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                   help="Parallel processes for running games (default: all "
                        "cores). Use 1 for sequential (helpful for debugging). "
                        "Choose a multiple of --jobs as --n for best throughput "
                        "(no half-full final batch).")
    p.add_argument("--per-game", action="store_true",
                   help="Print one line per game in addition to the summary.")
    args = p.parse_args()

    if args.seeds is not None:
        from play_match import _parse_seeds
        seeds = list(_parse_seeds(args.seeds))
    else:
        seeds = list(range(args.n))

    config = _load_v3_config(args.v3_config)

    mcts_factory = _mcts_factory(
        seed_offset=0,
        config=config,
        sims_per_move=args.sims,
        c_uct=args.c_uct,
        n_random_fencing=args.n_random_fencing,
        temperature=args.temperature,
        fpu_offset=args.fpu_offset,
    )
    opp_sims = args.opp_sims if args.opp_sims is not None else args.sims
    opp_c_uct = args.opp_c_uct if args.opp_c_uct is not None else args.c_uct
    opp_factory = _opponent_factory(
        args.opponent,
        seed_offset=1,
        config=config,
        sims_per_move=opp_sims,
        c_uct=opp_c_uct,
        n_random_fencing=args.n_random_fencing,
        temperature=args.temperature,
        fpu_offset=args.fpu_offset,
    )

    if args.mcts_as_p1:
        p0_name, p1_name = args.opponent, "mcts"
    else:
        p0_name, p1_name = "mcts", args.opponent

    # PUCT / legality resolution (opponent knobs fall back to the main seat).
    opp_legality = args.opp_legality or args.legality
    opp_policy = args.opp_policy or args.policy
    opp_macro_policy = args.opp_macro_policy or args.macro_policy
    opp_leaf = args.opp_leaf or args.leaf
    opp_leaf_ckpt = args.opp_leaf_ckpt or args.leaf_ckpt
    opp_leaf_value_scale = (
        args.opp_leaf_value_scale if args.opp_leaf_value_scale is not None
        else args.leaf_value_scale
    )
    opp_two_pass = (
        args.opp_two_pass if args.opp_two_pass is not None
        else args.two_pass
    )
    for pol, lbl in ((args.policy, "--policy"), (opp_policy, "--opp-policy")):
        if pol not in ("uct", "uniform", "combined:unweighted", "combined:awr"):
            p.error(f"{lbl}={pol!r}: expected 'uct', 'uniform', "
                    "'combined:unweighted', or 'combined:awr'.")
    for mp, lbl in ((args.macro_policy, "--macro-policy"),
                    (opp_macro_policy, "--opp-macro-policy")):
        if mp not in ("none", "uct", "uniform", "combined:unweighted", "combined:awr"):
            p.error(f"{lbl}={mp!r}: expected 'none', 'uniform', "
                    "'combined:unweighted', or 'combined:awr'.")

    def _coerce_fence(policy, fence_mode, label):
        # MACRO is UCT-only; coerce to FLATTEN when a prior is set (PUCT).
        if policy != "uct" and fence_mode == "macro":
            print(f"  [note] {label}: --policy set with fence-mode 'macro' "
                  "(MACRO is UCT-only) — using 'flatten'.")
            return "flatten"
        return fence_mode

    fence_mode = _coerce_fence(args.policy, args.fence_mode, "mcts")
    opp_fence_mode = _coerce_fence(
        opp_policy, args.opp_fence_mode or args.fence_mode, "opp-mcts")

    spec = _MatchSpec(
        config_v3=config,
        p0_name=p0_name, p1_name=p1_name,
        sims_per_move=args.sims, opp_sims_per_move=opp_sims,
        c_uct=args.c_uct, opp_c_uct=opp_c_uct,
        n_random_fencing=args.n_random_fencing,
        fpu_offset=args.fpu_offset,
        temperature=args.temperature,
        legality=args.legality, opp_legality=opp_legality,
        fence_mode=fence_mode, opp_fence_mode=opp_fence_mode,
        policy=args.policy, opp_policy=opp_policy,
        macro_policy=args.macro_policy, opp_macro_policy=opp_macro_policy,
        leaf=args.leaf, opp_leaf=opp_leaf,
        leaf_ckpt=args.leaf_ckpt, opp_leaf_ckpt=opp_leaf_ckpt,
        leaf_value_scale=args.leaf_value_scale,
        opp_leaf_value_scale=opp_leaf_value_scale,
        two_pass=args.two_pass,
        opp_two_pass=opp_two_pass,
        opt_pareto_level=args.opt_level,
        opt_fence_cache=args.fence_cache,
        cap_total_sims=args.cap_total_sims,
    )

    cfg_label = args.v3_config or "default_v3"
    jobs = max(1, int(args.jobs))
    print(f"Match: P0={p0_name}  vs  P1={p1_name}  "
          f"({len(seeds)} seeds, jobs={jobs})")
    print(f"  V3 config: {cfg_label}")
    leaf_desc = args.leaf + (f" ({args.leaf_ckpt})" if args.leaf == "nn" else "")
    print(f"  MCTS: sims={args.sims}, c_uct={args.c_uct}, "
          f"legality={args.legality}, fence={fence_mode}, policy={args.policy}, "
          f"leaf={leaf_desc}, leaf_value_scale={args.leaf_value_scale or 'auto'}, "
          f"n_random_fencing={args.n_random_fencing}, "
          f"fpu_offset={args.fpu_offset}, temperature={args.temperature}")
    if args.opponent == "mcts":
        print(f"  Opp MCTS: sims={opp_sims}, c_uct={opp_c_uct}, "
              f"legality={opp_legality}, fence={opp_fence_mode}, policy={opp_policy}")

    result = play_match_parallel(spec, list(seeds), jobs=jobs)
    elapsed = result.elapsed_seconds

    if args.per_game:
        print()
        print(f"{'seed':>6}  {'SP':>3}  {'P0':>4}  {'P1':>4}  "
              f"{'tb0':>4}  {'tb1':>4}  winner")
        for g in result.per_game:
            w = "P0" if g.winner == 0 else ("P1" if g.winner == 1 else "tie")
            print(f"{g.seed:>6}  {g.starting_player:>3}  "
                  f"{g.score_p0:>4}  {g.score_p1:>4}  "
                  f"{g.tiebreaker_p0:>4}  {g.tiebreaker_p1:>4}  {w}")

    print()
    print(result.summary_line())
    print(f"  Wall: {elapsed:.1f}s total, {elapsed / max(1, len(seeds)):.1f}s / game")
    return 0


if __name__ == "__main__":
    sys.exit(main())
