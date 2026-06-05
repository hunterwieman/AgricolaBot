"""Browser UI for AgricolaBot. Companion to the terminal play.py driver.

Run:
    python play_web.py [--seed N] [--seats AGENT AGENT] [--mcts-sims N]
        [--nn-model PATH] [--host 127.0.0.1] [--port 8000] [--no-browser]

`AGENT` is one of: human, random, simple, hubris, hubris_v3, mcts, nn.
Defaults: ["human", "random"].

The `nn` seat plays a trained value network directly (1-turn lookahead).
The `mcts` seat is configured per-game from the New-game dialog: pick its
leaf evaluator (any compatible value-NN checkpoint under nn_models/), its
search mode (UCT or PUCT), and — for PUCT — the combined-policy variant
(unweighted / awr). UCT uses strict-restricted legality + macro fencing;
PUCT uses full legality + flattened fencing with the multi-head policy as
the sole prune. The `nn` seat's network is fixed at startup via --nn-model
(default: nn_models/best); --mcts-sims sets the default sims/move.

Examples:
    python play_web.py --seats human hubris        # play vs the Hubris heuristic
    python play_web.py --seats human mcts          # play vs MCTS (default 500 sims)
    python play_web.py --seats human mcts --mcts-sims 1000
    python play_web.py --seats human nn            # play vs the default NN
    python play_web.py --seats human nn --nn-model nn_models/M_10k_all_lowT
    python play_web.py --seats hubris hubris       # watch self-play
    python play_web.py --seats simple random       # watch Simple vs Random

When both seats are AI, the game does NOT auto-advance — click the
"Advance" button in the UI (or press Enter) to step one move at a time.
When at least one seat is human, AI seats fast-forward until the human is
on the clock (matching the old behavior).

The New-game dialog in the browser also exposes seat selection AND, when
'mcts' is picked, prompts for sims/move (override of --mcts-sims).

Stdlib-only: ThreadingHTTPServer for HTTP, Server-Sent Events for push.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    FOOD_ANIMAL_ACCUMULATION_RATES,
    HARVEST_ROUNDS,
    NUM_ROUNDS,
    PERMANENT_ACTION_SPACES_SET,
    SPACE_IDS,
    STAGE_CARDS,
    STAGE_ROUNDS,
    CellType,
    HouseMaterial,
    Phase,
)
from agricola.agents import (
    CONFIG_V1_T2,
    CONFIG_V3_T1,
    DEFAULT_CONFIG_V3,
    HeuristicConfigV3,
    HubrisHeuristic,
    HubrisHeuristicV1,
    HubrisHeuristicV2,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    RandomAgent,
    SimpleHeuristic,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
)


# Tuned V3 config loaded at startup via --v3-config PATH (or None if the
# flag wasn't passed). When None, `hubris_v3` falls back to DEFAULT_CONFIG_V3.
_TUNED_V3_CONFIG: HeuristicConfigV3 | None = None
_TUNED_V3_SOURCE_PATH: str | None = None

# Whether AI seats use agricola.agents.restricted_legal_actions. Set from the
# --restricted / --no-restricted CLI flag at startup; default ON to match the
# training pipeline (scripts/tune_heuristic.py + scripts/run_iterative_v3.py
# default --restricted ON as of CHANGES.md Change 11). Read by _build_agent.
_RESTRICTED: bool = True

# Default MCTS sims/move for the `mcts` seat type. Settable at startup via
# --mcts-sims; overridable per-session via the `mcts_sims` field on the
# /api/reset payload (and from the frontend's New-game dialog).
_MCTS_SIMS_DEFAULT: int = 500


def _load_v3_config_from_json(path: str) -> HeuristicConfigV3:
    """Load a HeuristicConfigV3 from a tune_heuristic.py JSON output file's
    `best_config` field. Raises if the file isn't a V3 tuning artifact."""
    import json as _json
    with open(path) as f:
        data = _json.load(f)
    if data.get("candidate_arch") != "v3":
        raise ValueError(
            f"{path}: candidate_arch is {data.get('candidate_arch')!r}, "
            f"expected 'v3'. This JSON is not a V3 tuning result."
        )
    if "best_config" not in data:
        raise ValueError(f"{path}: missing 'best_config' field.")
    return HeuristicConfigV3(**data["best_config"])
from agricola.engine import step
from agricola.helpers import fences_in_supply, stables_in_supply
from agricola.legality import legal_actions
from agricola.scoring import score, tiebreaker
from agricola.setup import setup, setup_env
from agricola.state import GameState


# Allowed seat types. "human" leaves the seat to be controlled by the
# browser; the others are agent classes from agricola.agents.
#
# "hubris" is the currently-strongest configured Hubris (V1 architecture with
# CONFIG_V1_T2 — tuned via scripts/tune_heuristic.py round 2; +8.85 holdout
# margin vs default V1). "hubris_v1" still points at the original V1 with
# DEFAULT_CONFIG, useful for direct comparisons against the pre-tuning
# baseline. "hubris_v2" is the V2 architecture (joint frontier) on default
# config.
AGENT_TYPES: tuple[str, ...] = (
    "human", "random", "simple", "hubris", "hubris_v1", "hubris_v2",
    "hubris_v3", "mcts", "nn",
)

# Default checkpoint backing the NN-based seats (`nn` and the `mcts` leaf
# evaluator) when --nn-model is not passed. A stem
# (NormalizedValueModel.load appends .pt/.meta.json), resolved relative to
# this file so it works regardless of CWD. `nn_models/best` is the canonical
# "best NN" pointer (a copy of the current champion's best.pt/.meta.json — see
# nn_models/REGISTRY.md); promoting a new champion = overwrite that pair, no
# code change here. Currently → M_82k_warmM62k (linear/margin head).
_DEFAULT_NN_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "nn_models", "best",
)

# Checkpoint the NN-based seats load. Set once at startup from --nn-model
# (see main); fixed for the process lifetime, so every new game uses the
# same model — to use a different NN, restart the UI. Stem or directory: a
# directory is resolved to "<dir>/best" by _resolve_nn_model_path.
_NN_MODEL_PATH: str = _DEFAULT_NN_MODEL_PATH

# Lazily-loaded, process-wide cache of loaded NN value models, keyed by
# checkpoint stem. Loading pulls in torch (heavy) and reads the checkpoint,
# so we do it once per stem and share each (eval-mode, read-only) model
# across all seats/resets that select it. The `mcts` seat can pick any
# discovered value checkpoint as its leaf evaluator (see _discover_value_models),
# so the cache is path-keyed rather than a single slot.
_NN_MODEL_CACHE: dict = {}

# Lazily-loaded, process-wide cache of the combined multi-head policy_fn for
# PUCT, keyed by variant ("unweighted" / "awr"). Building one loads 9 head
# checkpoints (POLICY_HEAD.md), so we do it once per variant.
_POLICY_FN_CACHE: dict = {}


def _resolve_nn_model_path(path: str) -> str:
    """Map a --nn-model argument to the stem NormalizedValueModel.load wants.

    Accepts either a checkpoint directory (e.g. nn_models/M_10k_all_lowT) —
    resolved to "<dir>/best" — or an explicit stem (e.g.
    nn_models/M_10k_all_lowT/best), used as-is."""
    return os.path.join(path, "best") if os.path.isdir(path) else path


def _load_nn_model(path: str | None = None):
    """Load (and cache) an NN value model by checkpoint stem.

    `path` defaults to the startup `_NN_MODEL_PATH` (the `nn` seat + the
    default MCTS leaf evaluator). Imports torch lazily so sessions that
    never use an NN seat don't pay the import cost. Each distinct stem is
    loaded once and shared read-only (eval mode, @torch.no_grad())."""
    stem = path if path is not None else _NN_MODEL_PATH
    if stem not in _NN_MODEL_CACHE:
        from agricola.agents.nn.model import NormalizedValueModel
        _NN_MODEL_CACHE[stem] = NormalizedValueModel.load(stem)
    return _NN_MODEL_CACHE[stem]


# ---------------------------------------------------------------------------
# MCTS leaf-evaluator (value NN) discovery + PUCT policy loading
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_NN_MODELS_ROOT = os.path.join(_PROJECT_ROOT, "nn_models")


def _discover_value_models() -> list[dict]:
    """Scan nn_models/ for compatible value checkpoints usable as an MCTS
    leaf evaluator, returning [{id, label, stem}] ordered with the champion
    `best` pointer first.

    A directory qualifies when it holds `best.pt` + `best.meta.json`, the
    meta's `model_kind` is "value" (policy / pointer heads are excluded),
    and its `encoding_version` matches the engine's current ENCODING_VERSION
    (incompatible-encoding checkpoints would crash on load). `id` is the
    directory name (the top-level pointer is id "best"); `stem` is the path
    NormalizedValueModel.load wants.
    """
    from agricola.agents.nn.encoder import ENCODING_VERSION

    def _is_value(meta_path: str) -> bool:
        try:
            with open(meta_path) as f:
                m = json.load(f)
        except (OSError, ValueError):
            return False
        return (m.get("model_kind", "value") == "value"
                and m.get("encoding_version") == ENCODING_VERSION)

    out: list[dict] = []
    # The top-level champion pointer (nn_models/best.{pt,meta.json}).
    best_meta = os.path.join(_NN_MODELS_ROOT, "best.meta.json")
    if os.path.exists(best_meta) and _is_value(best_meta):
        out.append({"id": "best", "label": "best (champion)",
                    "stem": os.path.join(_NN_MODELS_ROOT, "best")})
    try:
        names = sorted(n for n in os.listdir(_NN_MODELS_ROOT)
                       if os.path.isdir(os.path.join(_NN_MODELS_ROOT, n)))
    except OSError:
        names = []
    for name in names:
        meta = os.path.join(_NN_MODELS_ROOT, name, "best.meta.json")
        if os.path.exists(meta) and _is_value(meta):
            out.append({"id": name, "label": name,
                        "stem": os.path.join(_NN_MODELS_ROOT, name, "best")})
    return out


def _value_model_stem(model_id: str | None) -> str:
    """Resolve an MCTS evaluator id (from the New-game dialog) to a checkpoint
    stem. None / unknown id falls back to the startup `_NN_MODEL_PATH`."""
    if model_id is None:
        return _NN_MODEL_PATH
    for entry in _discover_value_models():
        if entry["id"] == model_id:
            return entry["stem"]
    return _NN_MODEL_PATH


def _load_combined_policy_fn(variant: str):
    """Load (and cache) the combined multi-head PUCT policy_fn for `variant`.

    Delegates to scripts/nn/build_combined_policy.build(variant) so the
    9-head manifest has a single source of truth. Loaded via importlib from
    the script path (scripts/ is not an importable package)."""
    if variant not in _POLICY_FN_CACHE:
        import importlib.util
        path = os.path.join(_PROJECT_ROOT, "scripts", "nn", "build_combined_policy.py")
        spec = importlib.util.spec_from_file_location("build_combined_policy", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _POLICY_FN_CACHE[variant] = mod.build(variant)
    return _POLICY_FN_CACHE[variant]


def _build_agent(
    seat_type: str,
    seed: int,
    *,
    mcts_sims: int | None = None,
    mcts_evaluator: str | None = None,
    mcts_search: str = "uct",
    mcts_policy: str = "unweighted",
):
    """Construct an agent for an AI seat (or return None for human seats).

    Each agent gets its own seeded RNG; we XOR the session seed with a
    per-seat constant so the two seats don't end up with identical
    tiebreaks in self-play scenarios.

    When the module-level `_RESTRICTED` flag is True (default — controlled
    by the --restricted/--no-restricted CLI), every AI agent is built with
    `legal_actions_fn=restricted_legal_actions` so it consults the
    action-pruned set defined in agricola.agents.restricted. This matches
    the training pipeline's default, so AI seats in the UI behave the same
    way they do during fitness evaluation.

    The `mcts_*` kwargs are consulted only when `seat_type == "mcts"`:

    - `mcts_sims`: simulations/move. None → module-level `_MCTS_SIMS_DEFAULT`.
    - `mcts_evaluator`: id of the value-NN leaf evaluator (one of
      `_discover_value_models`). None / unknown → the startup `_NN_MODEL_PATH`.
    - `mcts_search`: "uct" or "puct". UCT uses strict-restricted legality +
      `FenceMode.MACRO` and no policy prior; PUCT uses full legality +
      `FenceMode.FLATTEN` with the combined multi-head policy as the sole
      prune (POLICY_PUCT_DESIGN.md).
    - `mcts_policy`: which combined-policy variant PUCT uses, "unweighted"
      or "awr" (ignored for UCT).

    The MCTS seat is V3-free: the value NN is the leaf evaluator, the strict
    wrapper's harvest-feed cap ranks with that same NN (not V3), and the
    leaf is calibrated via the model's `value_scale` so `c_uct=1.4` is
    comparable across value heads. Mirrors scripts/play_mcts_match.py.
    """
    if seat_type == "human":
        return None
    extra = {"legal_actions_fn": restricted_legal_actions} if _RESTRICTED else {}
    if seat_type == "random":
        return RandomAgent(seed=seed, **extra)
    if seat_type == "simple":
        return SimpleHeuristic(seed=seed, **extra)
    if seat_type == "hubris":
        # Current strongest: V1 architecture + tuned CONFIG_V1_T2.
        return HubrisHeuristicV1(seed=seed, config=CONFIG_V1_T2, **extra)
    if seat_type == "hubris_v1":
        # Original V1 with hand-picked DEFAULT_CONFIG (kept for comparison).
        return HubrisHeuristicV1(seed=seed, **extra)
    if seat_type == "hubris_v2":
        return HubrisHeuristicV2(seed=seed, **extra)
    if seat_type == "hubris_v3":
        # V3 architecture. Priority: --v3-config PATH (if set at startup) >
        # CONFIG_V3_T1 (the promoted tuned constant — current strongest V3).
        # Falls back further to DEFAULT_CONFIG_V3 only if CONFIG_V3_T1 is
        # somehow None (shouldn't happen — it's a module-level constant).
        cfg = _TUNED_V3_CONFIG if _TUNED_V3_CONFIG is not None else CONFIG_V3_T1
        return HubrisHeuristicV3(seed=seed, config=cfg, **extra)
    if seat_type == "mcts":
        # MCTS with a trained value NN as its leaf evaluator. The leaf returns
        # an already-P0-frame margin (nn_evaluator, 1 forward pass) and is
        # normalized by the model's `value_scale` so a single c_uct stays
        # calibrated across value heads (matches scripts/play_mcts_match.py).
        # The whole agent is V3-free: the strict wrapper's harvest-feed cap
        # ranks with the SAME NN (feed_evaluator), and the greedy macro-fence
        # agent is MCTSSearch's NN-backed default (heuristic left unset).
        import numpy as _np

        from agricola.agents import FenceMode
        from agricola.agents.nn.agent import nn_evaluator
        from agricola.legality import legal_actions as _full_legal

        stem = _value_model_stem(mcts_evaluator)
        model = _load_nn_model(stem)
        cfg = _TUNED_V3_CONFIG if _TUNED_V3_CONFIG is not None else CONFIG_V3_T1
        sims = int(mcts_sims) if mcts_sims is not None else _MCTS_SIMS_DEFAULT
        lvs = float(getattr(model, "value_scale", 1.0))
        use_puct = (mcts_search == "puct")

        if use_puct:
            # PUCT: full legality (the policy is the sole prune) + FLATTEN
            # fencing + the combined multi-head policy prior.
            policy_fn = _load_combined_policy_fn(mcts_policy)
            search = MCTSSearch(
                evaluator_fn=nn_evaluator,
                evaluator_config=model,
                legal_actions_fn=_full_legal,
                policy_fn=policy_fn,
                fence_mode=FenceMode.FLATTEN,
                leaf_value_scale=lvs,
                n_random_fencing=4,
                rng_seed=seed,
            )
        else:
            # UCT: strict-restricted legality (feed-cap ranked by the NN, so
            # V3-free) + MACRO fencing, no policy prior.
            rng = _np.random.default_rng(seed)
            feed_eval = (lambda s, p, _m=model: nn_evaluator(s, p, _m))
            strict_legal = make_strict_restricted_legal_actions(
                config=cfg, rng=rng, evaluator=feed_eval,
            )
            search = MCTSSearch(
                evaluator_fn=nn_evaluator,
                evaluator_config=model,
                legal_actions_fn=strict_legal,
                leaf_value_scale=lvs,
                n_random_fencing=4,
                rng_seed=seed,
            )
        return MCTSAgent(
            search,
            sims_per_move=sims,
            c_uct=1.4,
            fpu_offset=0.0,
            action_selection_temperature=0.2,
            rng_seed=seed,
        )
    if seat_type == "nn":
        # Trained value NN (M_10k_standard_bimodal). NNAgent is an
        # EvaluatorAgent subclass (not a HeuristicAgent — its evaluator is
        # learned, not hand-crafted), so it threads `legal_actions_fn` the
        # same way and supports the per-action preview overlay. The model
        # is loaded once (cached) and shared read-only across seats.
        from agricola.agents.nn.agent import NNAgent
        return NNAgent(_load_nn_model(), seed=seed, **extra)
    raise ValueError(f"unknown seat type {seat_type!r}; choose from {AGENT_TYPES}")

# Reuse formatting helpers from play.py.
from play import (
    HOUSE_MATERIAL_NAME,
    MAJOR_NAMES,
    SPACE_DISPLAY_NAMES,
    _fmt_action_inline,
    _fmt_accumulation,
    _pending_detail,
)


HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
TEMPLATES_DIR = os.path.join(HERE, "templates")


# ---------------------------------------------------------------------------
# UI hints per action type
# ---------------------------------------------------------------------------

def _ui_hint_for(action: Action) -> str:
    if isinstance(action, PlaceWorker):
        return "space"
    if isinstance(action, Stop):
        return "stop"
    if isinstance(action, (ChooseSubAction, FireTrigger, CommitRenovate)):
        return "button"
    if isinstance(action, CommitBuildMajor):
        return "major"
    if isinstance(action, (CommitPlow, CommitBuildStable, CommitBuildRoom)):
        return "cell"
    if isinstance(action, CommitBuildPasture):
        return "cell_set"
    # CommitSow, CommitBake, CommitAccommodate, CommitBreed, CommitConvert,
    # CommitHarvestConversion -> numeric / button-list.
    return "numeric"


def _action_params(action: Action) -> dict:
    if isinstance(action, PlaceWorker):
        return {"space": action.space}
    if isinstance(action, ChooseSubAction):
        return {"name": action.name}
    if isinstance(action, FireTrigger):
        return {"card_id": action.card_id}
    if isinstance(action, Stop):
        return {}
    if isinstance(action, CommitSow):
        return {"grain": action.grain, "veg": action.veg}
    if isinstance(action, CommitBake):
        return {"grain": action.grain}
    if isinstance(action, CommitPlow):
        return {"row": action.row, "col": action.col}
    if isinstance(action, CommitBuildStable):
        return {"row": action.row, "col": action.col}
    if isinstance(action, CommitBuildRoom):
        return {"row": action.row, "col": action.col}
    if isinstance(action, CommitBuildMajor):
        return {
            "major_idx": action.major_idx,
            "return_fireplace_idx": action.return_fireplace_idx,
        }
    if isinstance(action, CommitRenovate):
        return {}
    if isinstance(action, CommitAccommodate):
        return {"sheep": action.sheep, "boar": action.boar, "cattle": action.cattle}
    if isinstance(action, CommitBuildPasture):
        return {"cells": sorted([list(c) for c in action.cells])}
    if isinstance(action, CommitHarvestConversion):
        return {"conversion_id": action.conversion_id}
    if isinstance(action, CommitConvert):
        return {
            "grain": action.grain, "veg": action.veg,
            "sheep": action.sheep, "boar": action.boar, "cattle": action.cattle,
        }
    if isinstance(action, CommitBreed):
        return {"sheep": action.sheep, "boar": action.boar, "cattle": action.cattle}
    return {}


# ---------------------------------------------------------------------------
# State -> JSON
# ---------------------------------------------------------------------------

def _resources_to_dict(r) -> dict:
    return {
        "wood": r.wood, "clay": r.clay, "reed": r.reed, "stone": r.stone,
        "food": r.food, "grain": r.grain, "veg": r.veg,
    }


def _animals_to_dict(a) -> dict:
    return {"sheep": a.sheep, "boar": a.boar, "cattle": a.cattle}


def _cell_to_dict(cell) -> dict:
    return {
        "type": cell.cell_type.name,
        "grain": cell.grain,
        "veg": cell.veg,
    }


def _farmyard_to_dict(fy) -> dict:
    grid = [[_cell_to_dict(fy.grid[r][c]) for c in range(5)] for r in range(3)]
    h = [[bool(fy.horizontal_fences[r][c]) for c in range(5)] for r in range(4)]
    v = [[bool(fy.vertical_fences[r][c]) for c in range(6)] for r in range(3)]
    pastures = []
    for past in fy.pastures:
        cells = sorted(past.cells)
        fenced_stables = sum(
            1 for (r, c) in past.cells
            if fy.grid[r][c].cell_type == CellType.STABLE
        )
        pastures.append({
            "cells": [list(c) for c in cells],
            "capacity": past.capacity,
            "fenced_stables": fenced_stables,
        })
    return {
        "cells": grid,
        "h_fences": h,
        "v_fences": v,
        "pastures": pastures,
    }


def _decider_of(state: GameState) -> "int | None":
    # None at a round-card reveal (a PendingReveal — nature decides).
    if state.pending_stack:
        return state.pending_stack[-1].player_idx
    return state.current_player


def _player_to_dict(state: GameState, idx: int, decider: int) -> dict:
    p = state.players[idx]
    majors = [
        {"idx": i, "name": MAJOR_NAMES[i]}
        for i, owner in enumerate(state.board.major_improvement_owners)
        if owner == idx
    ]
    # Interim score (works mid-game too — scoring is pure over the state).
    total, _bd = score(state, idx)
    # Per-player supply totals are fixed by the rules (15 fences, 4 stables).
    # "Built" = total - in_supply.
    fences_left  = fences_in_supply(p.farmyard)
    stables_left = stables_in_supply(p.farmyard)
    return {
        "idx": idx,
        "is_sp": state.starting_player == idx,
        "is_decider": decider == idx,
        "is_current": state.current_player == idx,
        "house_material": HOUSE_MATERIAL_NAME[p.house_material],
        "people_total": p.people_total,
        "people_home": p.people_home,
        "newborns": p.newborns,
        "begging_markers": p.begging_markers,
        "interim_score": total,
        "resources": _resources_to_dict(p.resources),
        "animals": _animals_to_dict(p.animals),
        "fences_built":   15 - fences_left,
        "fences_total":   15,
        "stables_built":  4  - stables_left,
        "stables_total":  4,
        "majors": majors,
        "minors": sorted(p.minor_improvements),
        "farmyard": _farmyard_to_dict(p.farmyard),
    }


# Short effect blurbs shown under the name for the non-atomic spaces whose
# bundled sub-actions aren't obvious from the title. Only these four are
# annotated (per request); every other space renders name + accumulation
# only. Keyed by space id; absent ids get no effect line.
SPACE_EFFECT_TEXT: dict[str, str] = {
    "farm_expansion": "build rooms and/or build stables",
    "grain_utilization": "sow and/or bake bread",
    "house_redevelopment": "renovate, then build an improvement",
    "farm_redevelopment": "renovate, then build fences",
}


def _space_category(space_id: str) -> str:
    return "permanent" if space_id in PERMANENT_ACTION_SPACES_SET else "stage"


def _space_stage(space_id: str) -> int | None:
    """Stage (1–6) the space's card belongs to, or None for a permanent space."""
    for stage, cards in STAGE_CARDS.items():
        if space_id in cards:
            return stage
    return None


def _board_to_dict(state: GameState) -> dict:
    spaces = []
    for sid, ss in zip(SPACE_IDS, state.board.action_spaces):
        spaces.append({
            "id": sid,
            "name": SPACE_DISPLAY_NAMES.get(sid, sid),
            "category": _space_category(sid),
            "stage": _space_stage(sid),
            "is_revealed": ss.revealed,
            "workers": list(ss.workers),
            "accumulation_text": _fmt_accumulation(sid, ss),
            "effect_text": SPACE_EFFECT_TEXT.get(sid),
        })
    return {
        "spaces": spaces,
        "major_owners": list(state.board.major_improvement_owners),
    }


def _pending_to_dict(state: GameState) -> list:
    out = []
    for frame in state.pending_stack:
        out.append({
            "type": type(frame).__name__,
            "player_idx": frame.player_idx,
            "details_text": _pending_detail(frame, state),
        })
    return out


def _legal_actions_to_dicts(state: GameState, actions: list[Action]) -> list[dict]:
    out = []
    for i, a in enumerate(actions):
        out.append({
            "index": i,
            "type": type(a).__name__,
            "display": _fmt_action_inline(a),
            "params": _action_params(a),
            "ui_hint": _ui_hint_for(a),
        })
    return out


def _harvest_note(state: GameState) -> str:
    if state.phase == Phase.WORK and state.round_number in HARVEST_ROUNDS:
        return "harvest after this round"
    if state.phase == Phase.WORK and (state.round_number + 1) in HARVEST_ROUNDS:
        return "harvest next round"
    if state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        return state.phase.name.replace("HARVEST_", "harvest: ").lower()
    return ""


SCORE_ROWS = [
    ("Fields",          "field_tiles"),
    ("Pastures",        "pastures"),
    ("Grain",           "grain"),
    ("Vegetables",      "vegetables"),
    ("Sheep",           "sheep"),
    ("Boar",            "boar"),
    ("Cattle",          "cattle"),
    ("Unused",          "unused_spaces"),
    ("Fenced stables",  "fenced_stables"),
    ("Clay rooms",      "clay_rooms"),
    ("Stone rooms",     "stone_rooms"),
    ("People",          "people"),
    ("Begging",         "begging_markers"),
    ("Major imp.",      "major_improvement_points"),
    ("Craft bonus",     "bonus_points"),
]


def _score_block(state: GameState) -> dict:
    t0, b0 = score(state, 0)
    t1, b1 = score(state, 1)
    rows = []
    for label, attr in SCORE_ROWS:
        rows.append({
            "label": label,
            "p0": getattr(b0, attr),
            "p1": getattr(b1, attr),
        })
    if t0 == t1:
        tb0 = tiebreaker(state, 0)
        tb1 = tiebreaker(state, 1)
        if tb0 == tb1:
            winner = -1  # true tie
            note = f"Tie on tiebreaker ({tb0}-{tb1})"
        else:
            winner = 0 if tb0 > tb1 else 1
            note = f"Tiebreak P{winner} wins ({tb0}-{tb1})"
    else:
        winner = 0 if t0 > t1 else 1
        note = f"P{winner} wins"
    return {
        "rows": rows,
        "p0_total": t0,
        "p1_total": t1,
        "winner": winner,
        "note": note,
    }


def state_to_json(state: GameState, log_entries: list[dict], game_over: bool,
                  actions: list[Action] | None = None,
                  seats: tuple[str, str] | None = None,
                  interactive_ai_paused: bool = False) -> dict:
    decider = _decider_of(state)
    if actions is None:
        actions = legal_actions(state) if not game_over else []

    payload = {
        "round_number": state.round_number,
        "phase": state.phase.name,
        "starting_player": state.starting_player,
        "current_player": state.current_player,
        "decider": decider,
        "harvest_note": _harvest_note(state),
        "game_over": game_over,
        "seats": list(seats) if seats is not None else ["human", "human"],
        "players": [_player_to_dict(state, i, decider) for i in (0, 1)],
        "board": _board_to_dict(state),
        "pending_stack": _pending_to_dict(state),
        "legal_actions": _legal_actions_to_dicts(state, actions),
        "round_log": log_entries,
        "scoring": _score_block(state) if game_over else None,
        # True when interactive_ai is on AND the auto-driver paused before
        # an AI's top-level worker placement. Frontend uses this to know
        # when to fetch /api/ai_preview and overlay scores.
        "interactive_ai_paused": interactive_ai_paused,
    }
    return payload


# ---------------------------------------------------------------------------
# Round log (lifted from play.py's RoundLog, but yields dicts for the wire)
# ---------------------------------------------------------------------------

class RoundLog:
    def __init__(self, humans: set[int]) -> None:
        self.humans = humans
        self.entries: list[tuple[int, int, str]] = []
        self._buf_round: int | None = None
        self._buf_decider: int | None = None
        self._buf_parts: list[str] = []

    def add(self, decider: int, action: Action, round_num: int) -> None:
        is_new_turn = isinstance(action, PlaceWorker) or self._buf_decider != decider
        if is_new_turn and self._buf_parts:
            self._flush()
        if decider in self.humans:
            self.entries = [e for e in self.entries if e[0] == round_num]
        if not self._buf_parts:
            self._buf_decider = decider
            self._buf_round = round_num
        self._buf_parts.append(_fmt_action_inline(action))

    def _flush(self) -> None:
        if self._buf_parts:
            self.entries.append(
                (self._buf_round, self._buf_decider, " -> ".join(self._buf_parts))
            )
            self._buf_parts = []
            self._buf_decider = None
            self._buf_round = None

    def round_transition(self) -> None:
        self._flush()
        last_human = -1
        for i, (_r, decider, _p) in enumerate(self.entries):
            if decider in self.humans:
                last_human = i
        self.entries = self.entries[last_human + 1:]

    def to_wire(self, current_round: int) -> list[dict]:
        out: list[dict] = []
        for r, decider, parts in self.entries:
            out.append({
                "round": r,
                "decider": decider,
                "is_carryover": r != current_round,
                "text": parts,
            })
        if self._buf_parts:
            out.append({
                "round": self._buf_round,
                "decider": self._buf_decider,
                "is_carryover": False,
                "text": " -> ".join(self._buf_parts),
                "in_progress": True,
            })
        return out


# ---------------------------------------------------------------------------
# Game session — singleton wrapped in a lock
# ---------------------------------------------------------------------------

class Session:
    def __init__(
        self,
        seed: int,
        seats: tuple[str, str],
        *,
        mcts_sims: int | None = None,
        mcts_evaluator: str | None = None,
        mcts_search: str = "uct",
        mcts_policy: str = "unweighted",
        fast_mode: bool = False,
    ) -> None:
        for s in seats:
            if s not in AGENT_TYPES:
                raise ValueError(f"unknown seat type {s!r}; choose from {AGENT_TYPES}")
        self.seed = seed
        self.seats = seats
        self.mcts_sims = mcts_sims  # None means use _MCTS_SIMS_DEFAULT
        # MCTS seat configuration (only consulted for 'mcts' seats):
        # leaf-evaluator id, search mode ("uct"/"puct"), and PUCT policy
        # variant ("unweighted"/"awr"). See _build_agent.
        self.mcts_evaluator = mcts_evaluator
        self.mcts_search = mcts_search
        self.mcts_policy = mcts_policy
        # When True, the auto-advance driver also auto-applies human
        # singletons (a state where the human has exactly one legal
        # action). Settable via /api/fast_mode at runtime — survives
        # across resets. Server-side resolution avoids the SSE-arrival
        # races the previous client-side fast-mode had.
        self.fast_mode: bool = fast_mode
        # Interactive-AI mode: when ON, the auto-driver stops BEFORE each
        # AI top-level worker placement (pending_stack empty) and waits
        # for an explicit /api/step_ai call. Pending-stack AI decisions
        # still auto-execute silently. Lets the user inspect per-action
        # evaluator scores via /api/ai_preview before each AI placement.
        self.interactive_ai: bool = False
        self.humans: set[int] = {i for i, s in enumerate(seats) if s == "human"}
        # Per-seat agent objects; None for human seats.
        self.agents = self._make_agents()
        self.state, self.env = setup_env(seed)
        self.log = RoundLog(self.humans)
        self.current_round = self.state.round_number
        self.lock = threading.Lock()
        self.game_over = (self.state.phase == Phase.BEFORE_SCORING)
        # Full ordered action trace: every action ever applied to this
        # session's state, in apply order, captured before `step` is
        # invoked. Combined with `self.seed` and `self.seats` this is
        # sufficient to replay the entire session deterministically.
        # Exposed via /api/trace and the UI's "Download trace" button.
        self.action_trace: list[dict] = []
        # SSE subscribers
        self.subs: list[queue.Queue] = []
        self.subs_lock = threading.Lock()
        # If at least one seat is human, fast-forward any opening AI moves
        # until a human decision is reached. With no humans (AI-vs-AI), we
        # leave the state as-is and require explicit /api/step_ai calls.
        with self.lock:
            if self.humans:
                self._drive_until_decision_locked()

    def _make_agents(self) -> tuple:
        """Build both seats' agent objects from the current seat/mcts config.

        Each seat gets its own seeded RNG (session seed XOR a per-seat
        constant) so the two seats don't share tiebreaks in self-play. The
        mcts_* settings are threaded through to `_build_agent` (consulted
        only for 'mcts' seats)."""
        mcts_kw = dict(
            mcts_sims=self.mcts_sims,
            mcts_evaluator=self.mcts_evaluator,
            mcts_search=self.mcts_search,
            mcts_policy=self.mcts_policy,
        )
        return (
            _build_agent(self.seats[0], self.seed ^ 0x10000, **mcts_kw),
            _build_agent(self.seats[1], self.seed ^ 0x20000, **mcts_kw),
        )

    # ---------- subscriber management ----------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self.subs_lock:
            self.subs.append(q)
        # Immediately push the current state so the new client gets in sync.
        q.put(self.snapshot())
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.subs_lock:
            try:
                self.subs.remove(q)
            except ValueError:
                pass

    def _broadcast(self, payload: dict) -> None:
        dead = []
        with self.subs_lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    # ---------- state queries ----------

    def snapshot(self) -> dict:
        with self.lock:
            actions = [] if self.game_over else legal_actions(self.state)
            return state_to_json(
                self.state,
                self.log.to_wire(self.current_round),
                self.game_over,
                actions,
                seats=self.seats,
                interactive_ai_paused=self._interactive_ai_paused_here_locked(),
            )

    def trace_snapshot(self) -> dict:
        """Return the full session trace (seed + seats + ordered actions).

        Self-contained replay payload: feeding `setup(seed)` and stepping
        each entry's (type, params) reconstructs the exact game state. The
        `display` field is for human eyeballing; consumers that replay
        should use `type` + `params`.
        """
        with self.lock:
            return {
                "seed": self.seed,
                "seats": list(self.seats),
                "current_round": self.current_round,
                "phase": self.state.phase.name,
                "game_over": self.game_over,
                "actions": list(self.action_trace),
            }

    # ---------- step driving ----------

    def _maybe_round_transition_locked(self) -> None:
        if self.state.round_number != self.current_round:
            self.log.round_transition()
            self.current_round = self.state.round_number

    def _apply_action_locked(self, action: Action) -> None:
        dec = _decider_of(self.state)
        # Capture into the persistent trace before stepping. We record the
        # decider, round, type name, params, and human-readable display
        # so the trace is both replayable (type+params is enough to
        # reconstruct the Action) and debuggable by eye.
        self.action_trace.append({
            "round": self.current_round,
            "phase": self.state.phase.name,
            "decider": dec,
            "type": type(action).__name__,
            "params": _action_params(action),
            "display": _fmt_action_inline(action),
        })
        self.log.add(dec, action, self.current_round)
        self.state = step(self.state, action)
        self._maybe_round_transition_locked()
        if self.state.phase == Phase.BEFORE_SCORING:
            self.game_over = True

    def _interactive_ai_paused_here_locked(self) -> bool:
        """Are we currently paused waiting for the user to release the
        next AI placement?

        True iff: interactive_ai is on AND game not over AND the decider
        is an AI seat AND the pending_stack is empty (i.e. a top-level
        PlaceWorker is up). Pending-stack AI decisions don't pause.
        """
        if not self.interactive_ai or self.game_over:
            return False
        dec = _decider_of(self.state)
        if dec in self.humans:
            return False
        if self.state.pending_stack:
            return False
        return True

    def _drive_until_decision_locked(self) -> None:
        """Apply moves until a meaningful human decision OR game over.

        Two auto-application rules combined:

        - **AI moves**: always auto-applied (so the human isn't waiting
          through opponent turns). Used only when at least one seat is
          human — with zero humans the session never calls this and each
          AI step requires an explicit /api/step_ai call.

        - **Human singletons** (when `self.fast_mode` is on): if it's a
          human's turn and the engine reports exactly one legal action,
          apply that action automatically and loop. Lets the user skip
          forced decisions without an extra click. Resolving server-side
          avoids the SSE-arrival races the client-side fast-mode had.

        Without fast_mode, this exits as soon as a human is the decider,
        regardless of how many legal actions they have — matching the
        original `_drive_until_human` semantic.
        """
        while not self.game_over:
            self._maybe_round_transition_locked()
            dec = _decider_of(self.state)
            if dec is None:
                # Nature's round-card reveal — resolved by the env dealer.
                self._apply_action_locked(self.env.resolve(self.state))
                continue
            if dec in self.humans:
                # Human's turn. Auto-resolve singletons iff fast_mode on.
                if not self.fast_mode:
                    return
                actions = legal_actions(self.state)
                if len(actions) != 1:
                    return
                self._apply_action_locked(actions[0])
                continue
            # AI's turn — always auto-apply, EXCEPT when interactive_ai
            # mode is on and we're at a top-level placement (pending_stack
            # empty). In that case the user wants to inspect scores first.
            if self.interactive_ai and not self.state.pending_stack:
                return
            agent = self.agents[dec]
            if agent is None:
                # Defensive: shouldn't happen — humans set is consistent with agents.
                return
            action = agent(self.state)
            self._apply_action_locked(action)

    def submit_human_action(self, action_index: int) -> tuple[bool, str]:
        with self.lock:
            if self.game_over:
                return False, "game over"
            actions = legal_actions(self.state)
            if not (0 <= action_index < len(actions)):
                return False, f"action_index {action_index} out of range (0..{len(actions)-1})"
            dec = _decider_of(self.state)
            if dec not in self.humans:
                return False, "not a human's turn"
            self._apply_action_locked(actions[action_index])
            if self.humans:
                self._drive_until_decision_locked()
            payload = state_to_json(
                self.state,
                self.log.to_wire(self.current_round),
                self.game_over,
                [] if self.game_over else legal_actions(self.state),
                seats=self.seats,
                interactive_ai_paused=self._interactive_ai_paused_here_locked(),
            )
        self._broadcast(payload)
        return True, "ok"

    def set_fast_mode(self, fast_mode: bool) -> None:
        """Toggle server-side fast mode and (if turning ON) immediately
        auto-advance through any pending human singletons.

        Broadcasts the post-advance state if anything changed. Called by
        the frontend's fast-mode toggle via /api/fast_mode.
        """
        with self.lock:
            prev = self.fast_mode
            self.fast_mode = bool(fast_mode)
            advanced = False
            if self.fast_mode and not prev and self.humans and not self.game_over:
                # Capture pre-state so we can tell if the auto-advance moved.
                pre_state_id = id(self.state)
                self._drive_until_decision_locked()
                advanced = id(self.state) != pre_state_id
            payload = state_to_json(
                self.state,
                self.log.to_wire(self.current_round),
                self.game_over,
                [] if self.game_over else legal_actions(self.state),
                seats=self.seats,
                interactive_ai_paused=self._interactive_ai_paused_here_locked(),
            )
        if advanced:
            self._broadcast(payload)

    def set_interactive_ai(self, interactive_ai: bool) -> None:
        """Toggle interactive-AI mode. When turning OFF, immediately
        resume the auto-driver from wherever we paused (broadcasts the
        post-advance state if anything changed). When turning ON, no
        immediate action — the toggle takes effect the next time the
        auto-driver would auto-apply an AI top-level placement."""
        with self.lock:
            prev = self.interactive_ai
            self.interactive_ai = bool(interactive_ai)
            advanced = False
            # Turning OFF: resume the driver so we don't get stuck paused.
            # Turning ON while already at an AI placement: surfacing the
            # pause requires a broadcast so the frontend can switch UI.
            if prev and not self.interactive_ai and not self.game_over:
                pre_state_id = id(self.state)
                self._drive_until_decision_locked()
                advanced = id(self.state) != pre_state_id
            payload = state_to_json(
                self.state,
                self.log.to_wire(self.current_round),
                self.game_over,
                [] if self.game_over else legal_actions(self.state),
                seats=self.seats,
                interactive_ai_paused=self._interactive_ai_paused_here_locked(),
            )
        # Broadcast on any toggle so the UI flag flips even without an advance.
        self._broadcast(payload)

    def ai_preview(self) -> tuple[bool, str, list[dict]]:
        """Return per-top-level-action preview scores for the current AI
        decider. Only valid when we're at the interactive-AI pause point
        (decider is AI, pending_stack empty, game not over).

        Returns (ok, message, rows) where rows is a list of
        {action_type, params, space, score, is_top, is_close_call}
        sorted by descending score. `is_close_call` is True for any
        action whose score is within 0.5 of the top score (including
        the top itself) — used by the frontend to render a gold ring
        on multiple tiles when the AI is near-indifferent.

        Only EvaluatorAgent (and its subclasses — the heuristic family
        plus NNAgent) is supported, since `preview_top_actions` lives on
        that base. Other agent types (RandomAgent, MCTSAgent) return
        ok=False.
        """
        from agricola.agents.base import EvaluatorAgent
        with self.lock:
            if self.game_over:
                return False, "game over", []
            dec = _decider_of(self.state)
            if dec in self.humans:
                return False, "human's turn — no preview", []
            if self.state.pending_stack:
                return False, "mid-resolution decision; preview only for top-level placement", []
            agent = self.agents[dec]
            if not isinstance(agent, EvaluatorAgent):
                return False, f"agent type {type(agent).__name__!r} does not support preview", []
            scored = agent.preview_top_actions(self.state)
        if not scored:
            return False, "no multi-option preview at current state", []

        top_score = scored[0][1]
        rows = []
        for action, score in scored:
            row = {
                "type": type(action).__name__,
                "params": _action_params(action),
                "display": _fmt_action_inline(action),
                "score": float(score),
                "is_top": (score == top_score),
                "is_close_call": (top_score - score) <= 0.5,
            }
            # Surface the space id for PlaceWorker so the frontend can
            # map score → board tile without parsing the display string.
            if isinstance(action, PlaceWorker):
                row["space"] = action.space
            rows.append(row)
        return True, "ok", rows

    def step_ai(self) -> tuple[bool, str]:
        """Apply one AI action and broadcast the new state.

        In interactive-AI mode this is the "release the next AI move"
        action: apply the one top-level placement the user just inspected,
        then auto-drive through any resulting AI mid-resolution chain
        until either control hands off to a human or the next AI top-level
        placement pauses again. Outside interactive mode this is "step
        one AI action" — used in AI-vs-AI watching mode.

        Returns (False, msg) if the game is over or it's a human's turn.
        """
        with self.lock:
            if self.game_over:
                return False, "game over"
            dec = _decider_of(self.state)
            if dec is None:
                # Nature reveal — resolve it, then re-evaluate the decider.
                self._apply_action_locked(self.env.resolve(self.state))
                dec = _decider_of(self.state)
            if dec in self.humans:
                return False, "human's turn"
            agent = self.agents[dec]
            if agent is None:
                return False, "no agent for current decider"
            self._maybe_round_transition_locked()
            action = agent(self.state)
            self._apply_action_locked(action)
            # In interactive mode, the user wants Enter → ONE full AI
            # placement + all its resolution sub-actions, NOT Enter →
            # PlaceWorker, then Enter → ChooseSubAction, etc. Re-drive
            # the auto-loop; it'll auto-apply the AI's chain and stop at
            # either a human, game-over, or the next AI top-level pause.
            if self.interactive_ai:
                self._drive_until_decision_locked()
            payload = state_to_json(
                self.state,
                self.log.to_wire(self.current_round),
                self.game_over,
                [] if self.game_over else legal_actions(self.state),
                seats=self.seats,
                interactive_ai_paused=self._interactive_ai_paused_here_locked(),
            )
        self._broadcast(payload)
        return True, "ok"

    def reset(
        self,
        seed: int,
        seats: tuple[str, str],
        *,
        mcts_sims: int | None = None,
        mcts_evaluator: str | None = None,
        mcts_search: str = "uct",
        mcts_policy: str = "unweighted",
    ) -> None:
        for s in seats:
            if s not in AGENT_TYPES:
                raise ValueError(f"unknown seat type {s!r}")
        with self.lock:
            self.seed = seed
            self.seats = seats
            self.mcts_sims = mcts_sims
            self.mcts_evaluator = mcts_evaluator
            self.mcts_search = mcts_search
            self.mcts_policy = mcts_policy
            self.humans = {i for i, s in enumerate(seats) if s == "human"}
            self.agents = self._make_agents()
            self.state, self.env = setup_env(seed)
            self.log = RoundLog(self.humans)
            self.current_round = self.state.round_number
            self.game_over = (self.state.phase == Phase.BEFORE_SCORING)
            # Drop any prior session's trace; this is a fresh game.
            self.action_trace = []
            if self.humans:
                self._drive_until_decision_locked()
            payload = state_to_json(
                self.state,
                self.log.to_wire(self.current_round),
                self.game_over,
                [] if self.game_over else legal_actions(self.state),
                seats=self.seats,
            )
        self._broadcast(payload)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

# Allowed extensions for /static/* (defense-in-depth on top of path
# normalization).
_STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
    ".json": "application/json",
}


def _make_handler(session: Session):
    class Handler(BaseHTTPRequestHandler):
        # Silence default per-request logging.
        def log_message(self, format, *args):
            return

        # ---------- helpers ----------
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, status: int, text: str, ctype: str = "text/plain; charset=utf-8") -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, abs_path: str, ctype: str) -> None:
            try:
                with open(abs_path, "rb") as f:
                    body = f.read()
            except OSError:
                self._send_text(HTTPStatus.NOT_FOUND, "not found")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}

        # ---------- routes ----------
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                self._send_file(os.path.join(TEMPLATES_DIR, "index.html"),
                                "text/html; charset=utf-8")
                return
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                # Reject any '..' segments via normalization.
                norm = os.path.normpath(rel)
                if norm.startswith("..") or os.path.isabs(norm):
                    self._send_text(HTTPStatus.FORBIDDEN, "forbidden")
                    return
                abs_path = os.path.join(STATIC_DIR, norm)
                ext = os.path.splitext(abs_path)[1].lower()
                ctype = _STATIC_MIME.get(ext, "application/octet-stream")
                self._send_file(abs_path, ctype)
                return
            if path == "/api/state":
                self._send_json(HTTPStatus.OK, session.snapshot())
                return
            if path == "/api/config":
                # Static UI config used by the New-game dialog: the available
                # MCTS leaf evaluators (value NN checkpoints), the search
                # modes, and the PUCT policy variants. Discovered fresh so a
                # newly-trained checkpoint shows up without a server restart.
                self._send_json(HTTPStatus.OK, {
                    "mcts_evaluators": [
                        {"id": e["id"], "label": e["label"]}
                        for e in _discover_value_models()
                    ],
                    "mcts_search_modes": ["uct", "puct"],
                    "mcts_policies": ["unweighted", "awr"],
                    "mcts_sims_default": _MCTS_SIMS_DEFAULT,
                    "default_evaluator": "best",
                })
                return
            if path == "/api/trace":
                # Self-contained replay payload — seed, seats, and the
                # ordered action trace. Served as an attachment so the
                # browser saves it directly rather than navigating to it.
                payload = session.trace_snapshot()
                body = json.dumps(payload, indent=2).encode("utf-8")
                fname = f"agricola-trace-seed{payload['seed']}.json"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{fname}"',
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/events":
                self._serve_sse()
                return
            if path == "/api/ai_preview":
                ok, msg, rows = session.ai_preview()
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {
                    "ok": ok, "error": None if ok else msg, "rows": rows,
                })
                return
            self._send_text(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/api/step":
                body = self._read_body()
                idx = body.get("action_index")
                if not isinstance(idx, int):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "action_index must be int"})
                    return
                ok, msg = session.submit_human_action(idx)
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {"ok": ok, "error": None if ok else msg})
                return
            if path == "/api/step_ai":
                # No body required — just advance one AI move.
                ok, msg = session.step_ai()
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {"ok": ok, "error": None if ok else msg})
                return
            if path == "/api/fast_mode":
                body = self._read_body()
                value = body.get("enabled")
                if not isinstance(value, bool):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "enabled must be a boolean",
                    })
                    return
                session.set_fast_mode(value)
                self._send_json(HTTPStatus.OK, {"ok": True, "fast_mode": value})
                return
            if path == "/api/interactive_ai":
                body = self._read_body()
                value = body.get("enabled")
                if not isinstance(value, bool):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "enabled must be a boolean",
                    })
                    return
                session.set_interactive_ai(value)
                self._send_json(HTTPStatus.OK, {
                    "ok": True, "interactive_ai": value,
                })
                return
            if path == "/api/reset":
                body = self._read_body()
                seed = body.get("seed")
                if not isinstance(seed, int):
                    seed = int(time.time())
                raw_seats = body.get("seats", ["human", "random"])
                if (
                    not isinstance(raw_seats, list)
                    or len(raw_seats) != 2
                    or any(s not in AGENT_TYPES for s in raw_seats)
                ):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": f"seats must be a 2-element list of {AGENT_TYPES}",
                    })
                    return
                seats = (raw_seats[0], raw_seats[1])
                # Optional MCTS sims override (only relevant if a seat is
                # 'mcts'). Reject non-positive / non-integer values.
                mcts_sims = body.get("mcts_sims")
                if mcts_sims is not None:
                    if not (isinstance(mcts_sims, int) and mcts_sims >= 1):
                        self._send_json(HTTPStatus.BAD_REQUEST, {
                            "ok": False,
                            "error": "mcts_sims must be a positive integer",
                        })
                        return
                # Optional MCTS evaluator / search-mode / policy (only
                # relevant if a seat is 'mcts'). Validate against the
                # discovered value models and the fixed enums.
                mcts_evaluator = body.get("mcts_evaluator")
                if mcts_evaluator is not None:
                    valid_ids = {e["id"] for e in _discover_value_models()}
                    if mcts_evaluator not in valid_ids:
                        self._send_json(HTTPStatus.BAD_REQUEST, {
                            "ok": False,
                            "error": f"mcts_evaluator must be one of {sorted(valid_ids)}",
                        })
                        return
                mcts_search = body.get("mcts_search", "uct")
                if mcts_search not in ("uct", "puct"):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "mcts_search must be 'uct' or 'puct'",
                    })
                    return
                mcts_policy = body.get("mcts_policy", "unweighted")
                if mcts_policy not in ("unweighted", "awr"):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "mcts_policy must be 'unweighted' or 'awr'",
                    })
                    return
                session.reset(
                    seed, seats,
                    mcts_sims=mcts_sims,
                    mcts_evaluator=mcts_evaluator,
                    mcts_search=mcts_search,
                    mcts_policy=mcts_policy,
                )
                self._send_json(HTTPStatus.OK, {
                    "ok": True,
                    "seed": seed,
                    "seats": list(seats),
                    "mcts_sims": mcts_sims if mcts_sims is not None else _MCTS_SIMS_DEFAULT,
                    "mcts_evaluator": mcts_evaluator if mcts_evaluator is not None else "best",
                    "mcts_search": mcts_search,
                    "mcts_policy": mcts_policy,
                })
                return
            self._send_text(HTTPStatus.NOT_FOUND, "not found")

        # ---------- SSE ----------
        def _serve_sse(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q = session.subscribe()
            try:
                # SSE prelude — comment line just to flush headers.
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        payload = q.get(timeout=15.0)
                    except queue.Empty:
                        # heartbeat
                        try:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        continue
                    try:
                        data = json.dumps(payload).encode("utf-8")
                        self.wfile.write(b"event: state\n")
                        self.wfile.write(b"data: " + data + b"\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
            finally:
                session.unsubscribe(q)

    return Handler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Browser UI for AgricolaBot.")
    ap.add_argument("--seed", type=int, default=None,
                    help="Engine RNG seed (default: time-based).")
    ap.add_argument(
        "--seats", nargs=2, choices=AGENT_TYPES, default=["human", "random"],
        metavar="AGENT",
        help=(
            "Seat assignments for P0 and P1. Choices: human, random, simple, "
            "hubris. Default: human random. The browser UI can reassign seats "
            "via the New-game dialog."
        ),
    )
    ap.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    ap.add_argument("--port", type=int, default=8000, help="Bind port (default 8000).")
    ap.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser.")
    ap.add_argument(
        "--v3-config", default=None,
        help="Path to a JSON file (from scripts/tune_heuristic.py) whose "
             "'best_config' is loaded as the HubrisHeuristicV3 config when "
             "'hubris_v3' is selected as a seat. If omitted, hubris_v3 uses "
             "DEFAULT_CONFIG_V3 (untuned).",
    )
    ap.add_argument(
        "--restricted", action=argparse.BooleanOptionalAction, default=True,
        help="If set (default), AI seats use agricola.agents.restricted_legal_actions "
             "— the action-pruned set (rooms-before-stables ordering, cell priorities, "
             "room cap, first-pasture cells, min-begging at harvest feed). Matches the "
             "training pipeline's default. Use --no-restricted to play against agents "
             "that see the full unrestricted legal-action set.",
    )
    ap.add_argument(
        "--mcts-sims", type=int, default=500,
        help="Default MCTS simulations per move when an MCTS seat is selected. "
             "Per-session override available via the New-game dialog in the "
             "browser UI. Defaults to 500. Approximate per-move wall on an "
             "M-series Mac core: 500 sims ≈ 50-100ms, 1000 sims ≈ 100-200ms.",
    )
    ap.add_argument(
        "--nn-model", default=None, metavar="PATH",
        help="Checkpoint the NN-based seats use — the 'nn' seat (played "
             "directly) and the 'mcts' seat's leaf evaluator. Either a "
             "checkpoint directory (e.g. nn_models/M_10k_all_lowT, resolved "
             "to '<dir>/best') or an explicit stem (e.g. "
             "nn_models/M_55k_all/epoch_47). Fixed for the process: every new "
             "game uses the same model; restart the UI to switch. Defaults to "
             "nn_models/M_55k_all/epoch_47.",
    )
    ap.add_argument(
        "--opt-level", type=int, default=0, choices=[0, 1, 2, 3],
        help="agricola.opt_config.PARETO_OPT_LEVEL (0-3, cumulative): "
             "behavior-transparent legal-action enumeration speedups for "
             "MCTS. Default 0 (off). Use 3 to speed up MCTS seats.",
    )
    ap.add_argument(
        "--fence-cache", action="store_true", default=False,
        help="agricola.opt_config.FENCE_SCAN_CACHE: cache the fence-universe "
             "legality scan (the dominant MCTS speedup). Default off.",
    )
    return ap.parse_args()


def main() -> None:
    global _TUNED_V3_CONFIG, _TUNED_V3_SOURCE_PATH, _RESTRICTED
    global _MCTS_SIMS_DEFAULT, _NN_MODEL_PATH
    args = parse_args()
    if args.v3_config is not None:
        _TUNED_V3_CONFIG = _load_v3_config_from_json(args.v3_config)
        _TUNED_V3_SOURCE_PATH = args.v3_config
    _RESTRICTED = bool(args.restricted)
    _MCTS_SIMS_DEFAULT = int(args.mcts_sims)
    # Behavior-transparent MCTS enumeration speedups (read at call time by
    # helpers.py / legality.py, so setting them here before any game starts is
    # sufficient). Default off → byte-identical to baseline.
    from agricola import opt_config as _opt_config
    _opt_config.PARETO_OPT_LEVEL = int(args.opt_level)
    _opt_config.FENCE_SCAN_CACHE = bool(args.fence_cache)
    if args.nn_model is not None:
        _NN_MODEL_PATH = _resolve_nn_model_path(args.nn_model)
    # Fail fast on a bad checkpoint path rather than at first `nn`-seat use.
    if not (os.path.exists(_NN_MODEL_PATH + ".pt")
            and os.path.exists(_NN_MODEL_PATH + ".meta.json")):
        print(f"error: NN checkpoint not found at {_NN_MODEL_PATH!r} "
              f"(expected {_NN_MODEL_PATH}.pt + .meta.json). "
              f"Pass a checkpoint dir or '<dir>/best' stem via --nn-model.",
              file=sys.stderr)
        sys.exit(2)
    seed = args.seed if args.seed is not None else int(time.time())
    seats = (args.seats[0], args.seats[1])
    session = Session(seed=seed, seats=seats)
    handler = _make_handler(session)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"AgricolaBot WebUI - seed={seed} | seats={list(seats)}")
    if _TUNED_V3_SOURCE_PATH is not None:
        print(f"  hubris_v3 / mcts will use tuned V3 config from: {_TUNED_V3_SOURCE_PATH}")
    print(f"  AI seats use restricted_legal_actions: {'ON' if _RESTRICTED else 'OFF'}")
    print(f"  MCTS default sims/move: {_MCTS_SIMS_DEFAULT}  (override per session via New-game dialog)")
    print(f"  nn seat + mcts leaf evaluator use NN checkpoint: {_NN_MODEL_PATH}")
    print(f"  MCTS speedups: PARETO_OPT_LEVEL={args.opt_level}  "
          f"FENCE_SCAN_CACHE={'ON' if args.fence_cache else 'OFF'}")
    print(f"Serving at {url}")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer interrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
