"""Random-pairing tournament over search-agent configurations.

Each game samples two agent configs and plays them head-to-head (cap ON, NN
leaf). Configs are sampled by archetype — 1-turn NN anchor (1/7), UCT (2/7),
PUCT (4/7) — and within UCT/PUCT the c and sims params are sampled uniformly
from their grids. Results stream to a JSONL file (one row per game) plus a
human-readable progress log on stdout, so the run is resumable: re-invoking
with the same --out-dir skips game indices already recorded.

Analysis is a separate step (scripts/analyze_tournament.py) that reads the
JSONL — run it any time, including on a partial/killed run.

All randomness (which configs each game uses, the per-game engine seed) is
derived deterministically from --plan-seed, so the plan is reproducible and a
killed run resumes onto the exact same games.

Why cap ON: --cap-total-sims makes `sims` a clean effective-budget axis and
removes the tree-reuse inheritance confound (peaked PUCT trees inherit more
effective sims than flatter UCT trees), so UCT-vs-PUCT at matched sims is
apples-to-apples. See CLAUDE.md / mcts.py cap_total_sims.

Example:
    python scripts/run_search_tournament.py --n 2000 --jobs 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for play_mcts_match / play_match

import play_mcts_match as pmm  # noqa: E402  (reuse _value_model / _resolve_policy + their lru_caches)
from play_match import _winner  # noqa: E402

from agricola.agents import (  # noqa: E402
    FenceMode,
    MCTSAgent,
    MCTSSearch,
    restricted_legal_actions,
)
from agricola.agents.base import play_game  # noqa: E402
from agricola.legality import legal_actions as full_legal_actions  # noqa: E402
from agricola.scoring import score, tiebreaker  # noqa: E402
from agricola.setup import setup_env  # noqa: E402

# --- Config grids -----------------------------------------------------------
UCT_C = [0.1, 0.2, 0.3]
PUCT_C = [0.25, 0.5, 1.0]
SIMS = [200, 400, 800, 1200]
LEAF_CKPT = "nn_models/best"
P1_SEED_OFFSET = 1_000_000  # keep P1 agent RNG disjoint from any P0 across games


@dataclass(frozen=True)
class Cfg:
    kind: str            # "anchor" | "uct" | "puct"
    c: float | None
    sims: int | None

    @property
    def name(self) -> str:
        if self.kind == "anchor":
            return "anchor"
        return f"{self.kind}-c{self.c:g}-s{self.sims}"


ANCHOR = Cfg("anchor", None, None)


def sample_cfg(rng: np.random.Generator) -> Cfg:
    """Sample one config: anchor 1/7, UCT 2/7, PUCT 4/7; params uniform."""
    r = rng.random()
    if r < 1.0 / 7.0:
        return ANCHOR
    if r < 3.0 / 7.0:  # 2/7
        return Cfg("uct", float(rng.choice(UCT_C)), int(rng.choice(SIMS)))
    return Cfg("puct", float(rng.choice(PUCT_C)), int(rng.choice(SIMS)))  # 4/7


def build_plan(n: int, plan_seed: int, base_seed: int) -> list[tuple]:
    """Deterministic list of (idx, engine_seed, p0_cfg, p1_cfg).

    p1 is resampled until its config NAME differs from p0's, so identical-config
    mirror matches (which carry no ranking signal) are skipped. Distinct
    c/sims/kind count as different configs and are kept.
    """
    rng = np.random.default_rng(plan_seed)
    plan = []
    for idx in range(n):
        p0 = sample_cfg(rng)
        p1 = sample_cfg(rng)
        while p1.name == p0.name:
            p1 = sample_cfg(rng)
        plan.append((idx, base_seed + idx, p0, p1))
    return plan


# --- Agent construction (mirrors play_mcts_match._build_agent, cap ON) -------
def build_agent(cfg: Cfg, seed: int):
    from agricola.agents.nn.agent import NNAgent, nn_evaluator

    model = pmm._value_model(LEAF_CKPT)  # lru_cached per worker

    if cfg.kind == "anchor":
        # 1-turn greedy NN lookahead, plain e(s,0) (differential=False to match
        # the swept baseline), regular restricted legality, T=0.
        return NNAgent(
            model, differential=False, seed=seed, temperature=0.0,
            legal_actions_fn=restricted_legal_actions,
        )

    lvs = float(getattr(model, "value_scale", 1.0))
    if cfg.kind == "uct":
        policy_fn = None
        legal_fn = restricted_legal_actions
        fence_mode = FenceMode.MACRO
        macro_policy_fn = pmm._resolve_policy("combined:awr")
    elif cfg.kind == "puct":
        policy_fn = pmm._resolve_policy("combined:awr")
        legal_fn = full_legal_actions
        fence_mode = FenceMode.FLATTEN
        macro_policy_fn = None
    else:
        raise ValueError(f"unknown kind {cfg.kind!r}")

    search = MCTSSearch(
        n_random_fencing=4,
        rng_seed=seed,
        legal_actions_fn=legal_fn,
        fence_mode=fence_mode,
        policy_fn=policy_fn,
        macro_policy_fn=macro_policy_fn,
        leaf_value_scale=lvs,
        evaluator_config=model,
        evaluator_fn=nn_evaluator,
    )
    return MCTSAgent(
        search,
        sims_per_move=cfg.sims,
        c_uct=cfg.c,
        fpu_offset=0.0,
        action_selection_temperature=0.0,
        rng_seed=seed,
        cap_total_sims=True,
    )


# --- Worker ----------------------------------------------------------------
def _init_worker():
    # Caches are ON by module default; set explicitly so a spawned worker is
    # unambiguous regardless of future default changes.
    from agricola import opt_config
    opt_config.PARETO_OPT_LEVEL = 3
    opt_config.FENCE_SCAN_CACHE = True


def play_one(task: tuple) -> dict:
    idx, seed, p0_cfg, p1_cfg = task
    initial, env = setup_env(seed=seed)
    p0 = build_agent(p0_cfg, seed)
    p1 = build_agent(p1_cfg, seed + P1_SEED_OFFSET)
    final, _trace = play_game(initial, (p0, p1), env.resolve)
    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    tb0 = tiebreaker(final, 0)
    tb1 = tiebreaker(final, 1)
    winner = _winner(s0, s1, tb0, tb1)
    return {
        "idx": idx,
        "seed": seed,
        "p0": p0_cfg.name, "p0_kind": p0_cfg.kind, "p0_c": p0_cfg.c, "p0_sims": p0_cfg.sims,
        "p1": p1_cfg.name, "p1_kind": p1_cfg.kind, "p1_c": p1_cfg.c, "p1_sims": p1_cfg.sims,
        "score0": s0, "score1": s1, "tb0": tb0, "tb1": tb1,
        "winner": winner,  # 0, 1, or None (draw)
        "sp": initial.starting_player,
    }


# --- Driver ----------------------------------------------------------------
def main() -> None:
    import multiprocessing as mp

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=2000, help="Total games to play.")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    p.add_argument("--plan-seed", type=int, default=20260605,
                   help="Seeds the config-sampling RNG (reproducible plan).")
    p.add_argument("--base-seed", type=int, default=50000,
                   help="Engine seed of game 0; game i uses base_seed+i. "
                        "Default disjoint from sweep (1000-1031) / matrix (0-99).")
    p.add_argument("--out-dir", type=str,
                   default="data/tournaments/search_tourney",
                   help="Results dir (games.jsonl + metadata.json). Resumes if it exists.")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "games.jsonl"
    meta_path = out_dir / "metadata.json"

    plan = build_plan(args.n, args.plan_seed, args.base_seed)

    # Resume: skip idxs already recorded.
    done: set[int] = set()
    if results_path.exists():
        with results_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        done.add(json.loads(line)["idx"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    todo = [t for t in plan if t[0] not in done]

    meta_path.write_text(json.dumps({
        "n": args.n, "plan_seed": args.plan_seed, "base_seed": args.base_seed,
        "sampling": {"anchor": "1/7", "uct": "2/7", "puct": "4/7"},
        "uct_c": UCT_C, "puct_c": PUCT_C, "sims": SIMS,
        "leaf_ckpt": LEAF_CKPT, "cap_total_sims": True, "jobs": args.jobs,
    }, indent=2))

    n_total, n_done = len(plan), len(done)
    print(f"Tournament: {n_total} games planned, {n_done} already done, "
          f"{len(todo)} to play. jobs={args.jobs}", flush=True)
    print(f"  out: {results_path}", flush=True)
    print(f"  sampling: anchor 1/7, uct 2/7, puct 4/7 | cap ON | leaf={LEAF_CKPT}",
          flush=True)
    if not todo:
        print("Nothing to do.", flush=True)
        return

    t0 = time.time()
    completed = 0
    win_by_kind = {"anchor": [0, 0], "uct": [0, 0], "puct": [0, 0]}  # [wins, games]

    with results_path.open("a") as out_f:
        ctx = mp.get_context("spawn")
        with ctx.Pool(args.jobs, initializer=_init_worker) as pool:
            for res in pool.imap_unordered(play_one, todo, chunksize=1):
                out_f.write(json.dumps(res) + "\n")
                out_f.flush()
                completed += 1
                # Running per-archetype win tally (each seat counts once).
                for seat, kind_key in (("0", "p0_kind"), ("1", "p1_kind")):
                    k = res[kind_key]
                    win_by_kind[k][1] += 1
                    if res["winner"] == int(seat):
                        win_by_kind[k][0] += 1
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed else 0.0
                eta = (len(todo) - completed) / rate if rate else 0.0
                w = res["winner"]
                wstr = "draw" if w is None else f"P{w}"
                print(
                    f"  [{n_done + completed}/{n_total}] seed={res['seed']} "
                    f"{res['p0']} vs {res['p1']} -> {wstr} "
                    f"({res['score0']}-{res['score1']}) | "
                    f"{rate*3600:.0f}/hr ETA {eta/60:.1f}m",
                    flush=True,
                )

    elapsed = time.time() - t0
    print(f"\nDone: {completed} games in {elapsed/60:.1f}m "
          f"({completed/elapsed*3600:.0f}/hr)", flush=True)
    print("Per-archetype raw win% (confounded by opponents — use BT analysis):",
          flush=True)
    for k, (w, g) in win_by_kind.items():
        if g:
            print(f"  {k:6s}: {w}/{g} = {100*w/g:.1f}%", flush=True)


if __name__ == "__main__":
    main()
