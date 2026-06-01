"""Batch generator for NN training data.

Plays N games between agents drawn from an approved-config ensemble and
writes the resulting GameRecords to disk. Supports parallel generation
via a multiprocessing pool and resume-on-existing for restart safety.

Design: see FIRST_NN.md §6. The default ensemble is the 8 configs in
`tuned_configs/DATA_GEN_ENSEMBLE.md`.

CLI usage:

    # Pipeline-check run (small)
    python scripts/generate_nn_training_data.py --n-games 50

    # Sanity-check run (500-1000)
    python scripts/generate_nn_training_data.py --n-games 1000 --n-workers 8

    # Production run (5000)
    python scripts/generate_nn_training_data.py --n-games 5000 --n-workers 8

    # Resume an interrupted run
    python scripts/generate_nn_training_data.py --n-games 5000 \\
        --out-dir data/nn_training/runs/20260527-abcd1234

If `--out-dir` is given and already contains a `metadata.json`, the
script resumes that run instead of starting fresh. Each worker loads its
existing pickle (if any) and skips game_idxs already complete.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pickle
import platform
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

# Make `agricola` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import (  # noqa: E402
    CONFIG_V1_T2,
    HeuristicConfig,
    HeuristicConfigV3,
    HubrisHeuristicV1,
    HubrisHeuristicV3,
    RandomAgent,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
)
from agricola.agents.base import Agent, LegalActionsFn  # noqa: E402
from agricola.agents.nn import (  # noqa: E402
    DATA_VERSION,
    play_recording_game,
)
from agricola.legality import legal_actions  # noqa: E402
from agricola.setup import setup  # noqa: E402


# ---------------------------------------------------------------------------
# Default ensemble (DATA_GEN_ENSEMBLE.md)
# ---------------------------------------------------------------------------

DEFAULT_APPROVED_CONFIGS: tuple[str, ...] = (
    "t2",  # V1 + CONFIG_V1_T2 sentinel
    "tuned_configs/alphas_gen_7.json",
    "tuned_configs/alphas_gen_1.json",
    "tuned_configs/panel_wood_r1.json",
    "tuned_configs/panel_gen16.json",
    "tuned_configs/panel_gen47_wood020.json",
    "tuned_configs/panel_gen_25.json",
    "tuned_configs/panel_gen47.json",
)


# ---------------------------------------------------------------------------
# Agent factory: config spec -> Agent
# ---------------------------------------------------------------------------

# Per-worker cache so a config JSON isn't reloaded each game.
# Holds (config_obj, arch) tuples keyed by spec string.
_CONFIG_CACHE: dict[str, tuple] = {}

# Per-worker cache of loaded NN models (torch), keyed by checkpoint path.
_MODEL_CACHE: dict[str, object] = {}

# The margin reference scale for NN-seat temperature normalization.
# M_55k's measured leaf value_scale (σ of V(s,0)-V(s,1)) ≈ 22.72 — the scale
# the bimodal T_base distribution was implicitly calibrated for (heuristics and
# the margin NN both output margin-scale values). An NN seat's effective
# temperature is T_base * (its value_scale / this), so a single T_base draw
# means the same softmax selectivity across heads regardless of output units
# (margin σ≈22.7, tanh σ≈1.3, sigmoid σ≈0.66). This is the C15 leaf-value
# normalization lesson applied to the generation softmax instead of UCB —
# without it the tanh/sigmoid seats would play near-randomly at the same
# nominal T and pollute the data.
NN_TEMP_REFERENCE_SCALE = 22.72


def _load_nn_model(path_str: str):
    """Load (and cache per-process) a NormalizedValueModel checkpoint.

    Lazy torch import so non-NN generation runs stay torch-free. Pins BLAS
    to one thread so N pool workers don't spawn N² total threads.
    """
    if path_str in _MODEL_CACHE:
        return _MODEL_CACHE[path_str]
    import torch  # lazy: only NN seats pull torch into the worker
    torch.set_num_threads(1)
    from agricola.agents.nn.model import NormalizedValueModel
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    model = NormalizedValueModel.load(path)
    model.eval()
    _MODEL_CACHE[path_str] = model
    return model


def _resolve_config_cached(spec: str) -> tuple:
    """Resolve a config spec to (config_obj, arch).

    Spec forms:
    - `"random"`: returns (None, "random") — for RandomAgent (no config).
    - `"t2"`: returns (CONFIG_V1_T2, "v1") — the V1 round-2-tuned config.
    - Path string (absolute or relative to repo root): loads the JSON,
      reads `best_config`, returns the appropriate dataclass instance
      based on `candidate_arch`.

    Cached per-process. Heuristic configs are immutable dataclasses, so
    sharing the cached instance across many agents in the same worker
    is safe.
    """
    if spec in _CONFIG_CACHE:
        return _CONFIG_CACHE[spec]

    if spec == "random":
        result = (None, "random")
    elif spec == "t2":
        result = (CONFIG_V1_T2, "v1")
    elif spec.startswith("nn:"):
        # NN seat: spec is "nn:<checkpoint path>". Carry the path through;
        # the model itself is loaded + cached lazily in _build_agent (torch).
        result = (spec[len("nn:"):], "nn")
    else:
        path = Path(spec)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise SystemExit(
                f"Config spec {spec!r} is not 'random'/'t2' and not a "
                f"valid file path (tried {path})."
            )
        with open(path) as f:
            data = json.load(f)
        cfg_dict = data.get("best_config")
        if cfg_dict is None:
            raise SystemExit(f"{path} has no 'best_config' field.")
        arch = data.get("candidate_arch", "v1")
        if arch == "v1":
            result = (HeuristicConfig(**cfg_dict), "v1")
        elif arch == "v3":
            result = (HeuristicConfigV3(**cfg_dict), "v3")
        else:
            raise SystemExit(f"Unknown candidate_arch {arch!r} in {path}.")

    _CONFIG_CACHE[spec] = result
    return result


def _build_agent(
    spec: str,
    seed: int,
    temperature: float,
    legal_actions_fn: LegalActionsFn,
) -> Agent:
    """Construct an Agent for the given spec + per-agent seed."""
    cfg, arch = _resolve_config_cached(spec)

    if arch == "nn":
        # cfg is the checkpoint path string (from the "nn:" spec).
        from agricola.agents.nn.agent import NNAgent
        model = _load_nn_model(cfg)
        # Normalize the softmax temperature by the head's value_scale so a
        # single T_base means the same selectivity across margin/tanh/sigmoid.
        vs = getattr(model, "value_scale", 1.0) or 1.0
        t_eff = temperature * (vs / NN_TEMP_REFERENCE_SCALE)
        return NNAgent(
            model,
            differential=True,
            temperature=t_eff,
            seed=seed,
            lookahead="turn",
            legal_actions_fn=legal_actions_fn,
        )
    if arch == "random":
        return RandomAgent(seed=seed, legal_actions_fn=legal_actions_fn)
    if arch == "v1":
        return HubrisHeuristicV1(
            seed=seed,
            temperature=temperature,
            lookahead="turn",
            config=cfg,
            legal_actions_fn=legal_actions_fn,
        )
    if arch == "v3":
        return HubrisHeuristicV3(
            seed=seed,
            temperature=temperature,
            lookahead="turn",
            config=cfg,
            legal_actions_fn=legal_actions_fn,
        )
    raise RuntimeError(f"Unreachable: arch={arch!r}")


# ---------------------------------------------------------------------------
# Plan computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GamePlan:
    """The per-game work item. Derived deterministically from
    (base_seed, game_idx, approved_configs)."""

    game_idx: int
    seed: int
    p0_config: str
    p1_config: str
    p0_temperature: float
    p1_temperature: float
    restriction: str = "restricted"  # one of: unrestricted / restricted / strict


# Restriction level -> (this is mapped to a legal_actions_fn in the worker).
RESTRICTION_LEVELS = ("unrestricted", "restricted", "strict")


def _draw_temperature(rng: np.random.Generator) -> float:
    """Bimodal draw per FIRST_NN.md §6.1:
    - 95%: uniform from [0.3, 1.0] (skilled play)
    - 5%: fixed at T = 4.0 (exploration mode)
    """
    if rng.random() < 0.05:
        return 4.0
    return float(rng.uniform(0.3, 1.0))


def _draw_restriction(rng: np.random.Generator, mix: tuple[float, float, float]) -> str:
    """Draw a per-game restriction level from `mix`
    (p_unrestricted, p_restricted, p_strict). Varying the legality wrapper
    per game broadens the state distribution: unrestricted games visit states
    the wrappers prune; strict games match the MCTS deployment legality."""
    r = rng.random()
    if r < mix[0]:
        return "unrestricted"
    if r < mix[0] + mix[1]:
        return "restricted"
    return "strict"


def compute_plan(
    n_games: int,
    base_seed: int,
    approved_configs: tuple[str, ...],
    fixed_temperature: float | None = None,
    config_weights: tuple[float, ...] | None = None,
    restricted: bool = True,
    restriction_mix: tuple[float, float, float] | None = None,
) -> list[GamePlan]:
    """Generate the full per-game work list deterministically.

    Same arguments → same plan. This is what makes resume-on-existing
    work: a re-invocation with identical `n_games`/`base_seed`/configs/
    `fixed_temperature` regenerates the same plan, and workers can
    identify which games they've already completed via stored `game_idx`s.

    Each game's RNG is seeded by `base_seed * 100000 + game_idx` to
    keep per-game draws independent of `base_seed` magnitude.

    Temperature handling:
    - `fixed_temperature=None` (default): bimodal draw per `_draw_temperature`
      (95% uniform [0.3, 1.0], 5% T=4.0), independently per agent.
    - `fixed_temperature=T`: both agents use temperature `T` for every
      game. Useful for ablation runs that hold temperature constant
      while varying other axes (heuristic mix, etc).
    """
    # Normalize config weights once (None → uniform).
    if config_weights is None:
        weights = None
    else:
        if len(config_weights) != len(approved_configs):
            raise ValueError(
                f"config_weights length {len(config_weights)} != "
                f"approved_configs length {len(approved_configs)}.")
        w = np.asarray(config_weights, dtype=float)
        if (w < 0).any() or w.sum() <= 0:
            raise ValueError("config_weights must be non-negative and sum > 0.")
        weights = w / w.sum()

    if restriction_mix is not None:
        rm = tuple(float(x) for x in restriction_mix)
        if len(rm) != 3 or any(x < 0 for x in rm) or abs(sum(rm) - 1.0) > 1e-6:
            raise ValueError(
                "restriction_mix must be 3 non-negative floats summing to 1 "
                "(p_unrestricted, p_restricted, p_strict).")
    else:
        rm = None
    default_restriction = "restricted" if restricted else "unrestricted"

    n_cfg = len(approved_configs)
    plan = []
    for game_idx in range(n_games):
        game_rng = np.random.default_rng(base_seed * 100000 + game_idx)

        # Configs with replacement (weighted if config_weights given).
        if weights is None:
            p0_idx = int(game_rng.integers(n_cfg))
            p1_idx = int(game_rng.integers(n_cfg))
        else:
            p0_idx = int(game_rng.choice(n_cfg, p=weights))
            p1_idx = int(game_rng.choice(n_cfg, p=weights))

        # Independent per-agent temperatures (or fixed if requested).
        if fixed_temperature is None:
            p0_temp = _draw_temperature(game_rng)
            p1_temp = _draw_temperature(game_rng)
        else:
            p0_temp = float(fixed_temperature)
            p1_temp = float(fixed_temperature)

        # Per-game restriction level (drawn last so adding it doesn't perturb
        # the config/temperature draws of a restriction_mix=None plan).
        restriction = _draw_restriction(game_rng, rm) if rm is not None \
            else default_restriction

        plan.append(GamePlan(
            game_idx=game_idx,
            seed=base_seed + game_idx,
            p0_config=approved_configs[p0_idx],
            p1_config=approved_configs[p1_idx],
            p0_temperature=p0_temp,
            p1_temperature=p1_temp,
            restriction=restriction,
        ))
    return plan


def partition_plan(plan: list[GamePlan], n_workers: int) -> list[list[GamePlan]]:
    """Split the plan into contiguous, optimally-balanced slices.

    Workers 0..r-1 get ceil(n/w) games each; workers r..w-1 get
    floor(n/w) games each, where r = n % w. Max imbalance is exactly 1
    game (vs `(n_workers - 1)` for the naive ceil-chunking approach).

    Contiguous (not strided) so each worker's pickle file holds a known
    range of game_idxs. Helpful for debugging ("worker 3 covers games
    624-749") and for inspecting partial runs.
    """
    n = len(plan)
    base = n // n_workers
    remainder = n % n_workers
    slices: list[list[GamePlan]] = []
    offset = 0
    for w in range(n_workers):
        size = base + (1 if w < remainder else 0)
        slices.append(plan[offset:offset + size])
        offset += size
    return slices


# ---------------------------------------------------------------------------
# Atomic pickle write (so a killed mid-write doesn't corrupt the file)
# ---------------------------------------------------------------------------


def _write_pickle_atomic(path: Path, obj) -> None:
    """Write `obj` to `path` via a temp file + rename. Survives
    SIGKILL mid-write — the previous version of `path` stays valid."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(obj, f)
    tmp.replace(path)  # atomic on POSIX


# ---------------------------------------------------------------------------
# Worker function (runs in a multiprocessing.Pool worker process)
# ---------------------------------------------------------------------------


def _legal_actions_fn_for(restriction: str, seed: int) -> LegalActionsFn:
    """Map a per-game restriction level to a legal_actions_fn.

    `strict` is built per game with a seed-derived RNG so its internal random
    samples (harvest-feed cap, fence-pattern choice) are reproducible.
    """
    if restriction == "unrestricted":
        return legal_actions
    if restriction == "restricted":
        return restricted_legal_actions
    if restriction == "strict":
        return make_strict_restricted_legal_actions(rng=np.random.default_rng(seed))
    raise ValueError(f"Unknown restriction level {restriction!r}.")


def _worker_play_games(args: dict) -> dict:
    """Worker entry point: play the assigned slice of the plan.

    Resume behavior: if the worker's pickle already exists, load it and
    skip game_idxs already present. Re-writes the pickle atomically
    after every completed game so progress isn't lost on interruption.

    Per-game errors (engine bugs, unexpected states) are caught,
    logged, and skipped. The worker continues to the next game.

    Args (dict so it's multiprocessing-safe):
        worker_id: int
        games_dir: str (path)
        plan_slice: list[dict]   # GamePlan items as dicts
        restricted: bool

    Returns a summary dict:
        worker_id, n_completed, n_skipped, errored: list[(game_idx, msg)]
    """
    worker_id: int = args["worker_id"]
    games_dir: Path = Path(args["games_dir"])
    plan_slice: list[dict] = args["plan_slice"]
    restricted: bool = args["restricted"]

    pkl_path = games_dir / f"worker_{worker_id:02d}.pkl"

    # Resume: load existing records and identify completed game_idxs.
    records: list = []
    if pkl_path.exists():
        with pkl_path.open("rb") as f:
            records = pickle.load(f)
    completed_idxs = {rec.game_idx for rec in records}

    errored: list[tuple[int, str]] = []
    n_completed = 0
    n_skipped = 0

    for item in plan_slice:
        game_idx = item["game_idx"]
        if game_idx in completed_idxs:
            n_skipped += 1
            continue

        try:
            initial = setup(seed=item["seed"])

            # Per-game legality wrapper (varies across games when a
            # restriction_mix was used; constant otherwise). Both seats and
            # the recorder share it.
            legal_actions_fn = _legal_actions_fn_for(
                item.get("restriction", "restricted"), item["seed"])

            # Per-agent seeds: derived from the game seed so that swapping
            # agents (e.g., for a resume of the SAME config draws) is
            # deterministic. Convention: p0 = seed*3, p1 = seed*3+1.
            # *3 leaves room for future per-agent variations (e.g., MCTS
            # internal seeds) without collision.
            p0_agent = _build_agent(
                spec=item["p0_config"],
                seed=item["seed"] * 3 + 0,
                temperature=item["p0_temperature"],
                legal_actions_fn=legal_actions_fn,
            )
            p1_agent = _build_agent(
                spec=item["p1_config"],
                seed=item["seed"] * 3 + 1,
                temperature=item["p1_temperature"],
                legal_actions_fn=legal_actions_fn,
            )

            rec = play_recording_game(
                initial,
                p0_agent,
                p1_agent,
                game_idx=game_idx,
                seed=item["seed"],
                p0_config_path=item["p0_config"],
                p1_config_path=item["p1_config"],
                p0_temperature=item["p0_temperature"],
                p1_temperature=item["p1_temperature"],
                legal_actions_fn=legal_actions_fn,
            )

            records.append(rec)
            n_completed += 1

            # Atomic write after every completed game.
            _write_pickle_atomic(pkl_path, records)

        except Exception as exc:
            tb = traceback.format_exc()
            errored.append((game_idx, f"{type(exc).__name__}: {exc}\n{tb}"))
            # Don't stop the worker; continue with the next game.

    return {
        "worker_id": worker_id,
        "n_completed": n_completed,
        "n_skipped": n_skipped,
        "errored": errored,
    }


# ---------------------------------------------------------------------------
# Metadata management
# ---------------------------------------------------------------------------


def _current_git_sha() -> str:
    """Best-effort current git SHA; 'unknown' if not in a repo."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _new_run_id() -> str:
    """ISO-8601 timestamp + short hash for a fresh run."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = format(int(time.time() * 1000) % 0xFFFF, "04x")
    return f"{ts}-{suffix}"


def _write_metadata(
    metadata_path: Path,
    *,
    run_id: str,
    n_workers: int,
    n_games: int,
    base_seed: int,
    approved_configs: tuple[str, ...],
    restricted: bool,
    fixed_temperature: float | None = None,
    config_weights: tuple[float, ...] | None = None,
    restriction_mix: tuple[float, float, float] | None = None,
    completed: int = 0,
    errored: list[dict] | None = None,
) -> None:
    """Write the run's metadata.json. Called once at startup (with
    `completed=0, errored=None`) and once at end with final counts.

    Overwrites in place, so a resumed run replaces the previous
    metadata with current state. Field semantics:
    - `planned_games`: target count for this run's plan.
    - `completed_games`: total stored across worker pickles (sum of
      this-run-completed + previously-completed-on-disk).
    - `errored_games`: list of {game_idx, error message} from the most
      recent invocation only. (To see historical errors, look at logs.)
    """
    if fixed_temperature is None:
        temp_descriptor = (
            "0.95 * uniform([0.3, 1.0]) + 0.05 * delta(4.0), "
            "drawn independently per agent"
        )
    else:
        temp_descriptor = f"fixed at T = {fixed_temperature} for both agents"
    data = {
        "run_id": run_id,
        "code_sha": _current_git_sha(),
        "host": platform.node(),
        "approved_configs": list(approved_configs),
        "config_weights": list(config_weights) if config_weights is not None else None,
        "temperature_distribution": temp_descriptor,
        "fixed_temperature": fixed_temperature,
        "restricted": restricted,
        "restriction_mix": list(restriction_mix) if restriction_mix is not None else None,
        "n_workers": n_workers,
        "planned_games": n_games,
        "completed_games": completed,
        "errored_games": errored or [],
        "base_seed": base_seed,
        "data_version": DATA_VERSION,
    }
    with metadata_path.open("w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Programmatic entry point (called by CLI; also callable from tests)
# ---------------------------------------------------------------------------


def generate_dataset(
    n_games: int,
    *,
    out_dir: Path | None = None,
    n_workers: int | None = None,
    base_seed: int = 1000000,
    approved_configs: tuple[str, ...] | None = None,
    config_weights: tuple[float, ...] | None = None,
    restricted: bool = True,
    restriction_mix: tuple[float, float, float] | None = None,
    fixed_temperature: float | None = None,
    verbose: bool = True,
) -> dict:
    """Generate (or resume) an NN training dataset.

    Returns the final metadata dict. The dataset itself lives on disk:
    one `worker_NN.pkl` per worker plus `metadata.json` in the run dir.

    If `out_dir` is `None`, a fresh run directory is created under
    `data/nn_training/runs/<auto-id>/`. If `out_dir` is given and
    already contains a `metadata.json`, the run is treated as a resume:
    plan is recomputed, workers skip already-completed games, only
    missing games are played.
    """
    n_workers = n_workers if n_workers is not None else mp.cpu_count()
    if approved_configs is None:
        approved_configs = DEFAULT_APPROVED_CONFIGS
    approved_configs = tuple(approved_configs)

    # Resolve run directory and resume status.
    if out_dir is not None:
        run_dir = Path(out_dir)
        is_resume = run_dir.exists() and (run_dir / "metadata.json").exists()
        if is_resume:
            with (run_dir / "metadata.json").open("r") as f:
                existing_meta = json.load(f)
            run_id = existing_meta["run_id"]
        else:
            run_id = run_dir.name
    else:
        run_id = _new_run_id()
        run_dir = ROOT / "data" / "nn_training" / "runs" / run_id
        is_resume = False

    games_dir = run_dir / "games"
    metadata_path = run_dir / "metadata.json"
    games_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Run dir: {run_dir}")
        print(f"Run id: {run_id}")
        print(f"Resume: {is_resume}")
        print(f"N games planned: {n_games}")
        print(f"N workers: {n_workers}")
        print(f"Approved configs: {list(approved_configs)}")
        if config_weights is not None:
            print(f"Config weights: {list(config_weights)}")
        if restriction_mix is not None:
            print(f"Restriction mix (unrestricted/restricted/strict): "
                  f"{list(restriction_mix)}")
        else:
            print(f"Restricted: {restricted}")
        if fixed_temperature is not None:
            print(f"Fixed temperature: {fixed_temperature}")
        else:
            print("Temperature: bimodal (95% uniform[0.3,1.0] + 5% delta(4))")
        print()

    # Build the plan (deterministic; same inputs always produce same plan).
    plan = compute_plan(
        n_games, base_seed, approved_configs,
        fixed_temperature=fixed_temperature,
        config_weights=config_weights,
        restricted=restricted,
        restriction_mix=restriction_mix,
    )
    slices = partition_plan(plan, n_workers)

    # Write initial metadata. (Final state will overwrite at end.)
    if not is_resume:
        _write_metadata(
            metadata_path,
            run_id=run_id,
            n_workers=n_workers,
            n_games=n_games,
            base_seed=base_seed,
            approved_configs=approved_configs,
            restricted=restricted,
            fixed_temperature=fixed_temperature,
            config_weights=config_weights,
            restriction_mix=restriction_mix,
        )

    # Launch workers.
    t_start = time.perf_counter()
    worker_args = [
        {
            "worker_id": w_idx,
            "games_dir": str(games_dir),
            "plan_slice": [asdict(p) for p in slices[w_idx]],
            "restricted": restricted,
        }
        for w_idx in range(n_workers)
    ]

    if n_workers == 1:
        # Single-process path useful for debugging and tests.
        results = [_worker_play_games(worker_args[0])]
    else:
        with mp.Pool(processes=n_workers) as pool:
            results = pool.map(_worker_play_games, worker_args)

    elapsed = time.perf_counter() - t_start

    # Aggregate.
    total_completed_this_run = sum(r["n_completed"] for r in results)
    total_skipped = sum(r["n_skipped"] for r in results)
    all_errored = []
    for r in results:
        for game_idx, msg in r["errored"]:
            all_errored.append({"game_idx": game_idx, "error": msg})

    # `completed_games` in metadata reflects the on-disk total
    # (this-run-completed + previously-completed-and-skipped).
    on_disk_completed = total_completed_this_run + total_skipped

    _write_metadata(
        metadata_path,
        run_id=run_id,
        n_workers=n_workers,
        n_games=n_games,
        base_seed=base_seed,
        approved_configs=approved_configs,
        restricted=restricted,
        fixed_temperature=fixed_temperature,
        config_weights=config_weights,
        restriction_mix=restriction_mix,
        completed=on_disk_completed,
        errored=all_errored,
    )

    if verbose:
        print()
        print(f"Done in {elapsed:.1f}s")
        print(f"  Completed (this run): {total_completed_this_run}")
        print(f"  Skipped (already done): {total_skipped}")
        print(f"  Errored: {len(all_errored)}")
        if all_errored:
            print(f"  First few errors:")
            for e in all_errored[:3]:
                print(f"    game_idx {e['game_idx']}: "
                      f"{e['error'].splitlines()[0]}")

    # Return the final metadata for programmatic callers.
    with metadata_path.open("r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--n-games", type=int, required=True,
        help="Number of games to generate (per the plan).",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help=(
            "Output run directory. Default: data/nn_training/runs/<auto-id>/. "
            "If the dir exists with a metadata.json, the script resumes."
        ),
    )
    parser.add_argument(
        "--n-workers", type=int, default=None,
        help=f"Parallel workers. Default: cpu_count() (={mp.cpu_count()})",
    )
    parser.add_argument(
        "--base-seed", type=int, default=1000000,
        help="Base seed for the deterministic plan + per-game seeds.",
    )
    parser.add_argument(
        "--approved-configs", type=str, nargs="+", default=None,
        help=(
            f"Override the default ensemble. Default: the 8 configs from "
            f"DATA_GEN_ENSEMBLE.md. Use 'random' for RandomAgent, 't2' for "
            f"V1+CONFIG_V1_T2, or a path to a tuned JSON for V3."
        ),
    )
    parser.add_argument(
        "--config-weights", type=float, nargs="+", default=None,
        help=(
            "Per-config sampling weights (parallel to --approved-configs; "
            "need not sum to 1, normalized internally). Default: uniform."
        ),
    )
    parser.add_argument(
        "--restriction-mix", type=float, nargs=3, default=None,
        metavar=("P_UNRESTRICTED", "P_RESTRICTED", "P_STRICT"),
        help=(
            "Per-game legality-wrapper mix as 3 probabilities summing to 1: "
            "(unrestricted, restricted, strict). If set, each game draws its "
            "restriction level and both seats use it. Default: all games use "
            "the --restricted/--no-restricted setting."
        ),
    )
    parser.add_argument(
        "--restricted", action="store_true", default=True,
        help="Use restricted_legal_actions (default ON). Ignored if "
             "--restriction-mix is given.",
    )
    parser.add_argument(
        "--no-restricted", action="store_false", dest="restricted",
        help="Disable restricted_legal_actions.",
    )
    parser.add_argument(
        "--fixed-temperature", type=float, default=None,
        help=(
            "If set, both agents use this temperature for every game "
            "(overrides the bimodal default). Useful for ablation runs "
            "that hold T constant while varying the heuristic mix."
        ),
    )
    args = parser.parse_args()

    generate_dataset(
        n_games=args.n_games,
        out_dir=args.out_dir,
        n_workers=args.n_workers,
        base_seed=args.base_seed,
        approved_configs=tuple(args.approved_configs) if args.approved_configs else None,
        config_weights=tuple(args.config_weights) if args.config_weights else None,
        restricted=args.restricted,
        restriction_mix=tuple(args.restriction_mix) if args.restriction_mix else None,
        fixed_temperature=args.fixed_temperature,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
