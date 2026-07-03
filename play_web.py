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
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitCardChoice,
    CommitChooseCost,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitDraftPick,
    CommitFoodPayment,
    CommitHarvestConversion,
    CommitPlayMinor,
    CommitPlayOccupation,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    RevealCard,
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
    GameMode,
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
_MCTS_SIMS_DEFAULT: int = 800

# ---- Multi-tenancy / resource control (online deployment) ----
# Cap on concurrently-running AI searches across ALL games. The AI move is
# CPU-bound (an MCTS subprocess), so without a cap a public link is a trivial
# way to overload the box. Each AI move acquires this semaphore; excess moves
# queue. Default sized to the host's cores (override with the env var); on a
# small VM set AGRICOLA_MAX_CONCURRENT_AI=1 or 2.
_MAX_CONCURRENT_AI: int = (
    int(os.environ.get("AGRICOLA_MAX_CONCURRENT_AI", "0"))
    or max(1, min(4, (os.cpu_count() or 2)))
)
_AI_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT_AI)

# Max number of live game sessions held in memory at once. Beyond this the
# registry evicts the least-recently-used game (its in-memory state is lost —
# acceptable for a hobby deployment). Override with AGRICOLA_MAX_GAMES.
_MAX_GAMES: int = int(os.environ.get("AGRICOLA_MAX_GAMES", "200"))

# Idle games older than this (seconds since last request) are swept on the
# next game creation. Override with AGRICOLA_GAME_IDLE_TTL.
_GAME_IDLE_TTL: float = float(os.environ.get("AGRICOLA_GAME_IDLE_TTL", str(2 * 3600)))

# Name of the cookie that keys a browser to its game session.
_GID_COOKIE = "agricola_gid"

# Seats for every game created by the registry (online setup: human vs the
# joint-model MCTS bot). Set from --seats at startup.
_DEFAULT_SEATS: tuple[str, str] = ("human", "mcts")


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
from agricola.canonical import dumps
from agricola.cards import display as card_display
from agricola.engine import step
from agricola.helpers import buildable_fences, stables_in_supply
from agricola.legality import legal_actions
from agricola.pending import PendingDraftPick, PendingHarvestBreed, PendingHarvestFeed
from agricola.scoring import score, tiebreaker
from agricola.setup import CardPool, HAND_SIZE, setup, setup_env
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

# C++ selfplay binary + model export dir. When both exist the `mcts` seat
# delegates to the C++ binary (much faster than Python MCTS); otherwise it
# falls back to the Python MCTSAgent automatically.
_CPP_BINARY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "cpp", "build", "selfplay",
)
_CPP_EXPORT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "nn_models", "cpp_export_best",
)

# The deployed champion is a MIX-leaf model: the bot searches (and the analysis
# overlay searches) with a leaf value blending the margin and outcome heads at
# this α (0.9 = 90% margin / 10% outcome). The C++ binary defaults to "margin"
# (backward-compatible), so these are passed explicitly on every --move /
# --analyze call.
_CPP_LEAF_MODE = "mix"
_CPP_MIX_ALPHA = 0.9


class _CppMctsAgent:
    """Thin wrapper that shells out to the C++ selfplay --move binary.

    The C++ binary loads the NN once per process (process-level cache), so
    subsequent calls in the same server process are fast. Each AI move is one
    subprocess call; the state is serialized to canonical JSON on stdin and the
    chosen action + root value are returned as JSON on stdout.
    """

    def __init__(self, model_dir: str, sims: int, c_uct: float, temperature: float,
                 prior_mix: float = 0.0, leaf_mode: str = "margin",
                 mix_alpha: float = 0.5):
        self._model_dir = model_dir
        self._sims = sims
        self._c_uct = c_uct
        self._temperature = temperature
        self._prior_mix = prior_mix  # 0 = pure policy (standard opponent)
        self._leaf_mode = leaf_mode  # margin (default) / outcome / mix
        self._mix_alpha = mix_alpha  # blend weight for --leaf-mode mix

    def __call__(self, state) -> "Action":
        from agricola.canonical import dumps as _cdumps
        from agricola.agents.nn.trace_replay import action_from_params

        state_json = _cdumps(state)
        cmd = [
            _CPP_BINARY, "--move",
            "--model-dir", self._model_dir,
            "--sims", str(self._sims),
            "--c-uct", str(self._c_uct),
            "--temperature", str(self._temperature),
        ]
        if self._prior_mix > 0.0:
            cmd += ["--prior-mix", str(self._prior_mix)]
        if self._leaf_mode != "margin":
            cmd += ["--leaf-mode", self._leaf_mode, "--mix-alpha", str(self._mix_alpha)]
        result = subprocess.run(
            cmd,
            input=state_json.encode(),
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"C++ selfplay --move failed (rc={result.returncode}): "
                f"{result.stderr.decode()[:500]}"
            )
        out = json.loads(result.stdout.decode())
        act = out["action"]
        return action_from_params(act["type"], act["params"])


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
        # model_kind-aware: a separate-net NormalizedValueModel ("value") OR a
        # joint SharedTrunkModel ("shared_trunk"). Both expose predict_margin /
        # value_scale, so either is a drop-in value evaluator for the `nn` seat
        # (1-turn) and the `mcts` leaf — the joint model's policy heads are
        # simply unused on this value path. Routing through one loader is what
        # lets `nn_models/best` be a joint checkpoint without per-seat branching.
        from agricola.agents.nn.model import load_value_evaluator
        _NN_MODEL_CACHE[stem] = load_value_evaluator(stem)
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
    meta's `model_kind` is "value" OR "shared_trunk" (a joint SharedTrunkModel's
    value head is a valid leaf evaluator — see `_load_nn_model`), and its
    `encoding_version` matches the engine's current ENCODING_VERSION
    (incompatible-encoding checkpoints would crash on load). `id` is the
    directory name (the top-level pointer is id "best"); `stem` is the path
    the value loader wants.
    """
    from agricola.agents.nn.encoder import ENCODING_VERSION

    def _is_value(meta_path: str) -> bool:
        try:
            with open(meta_path) as f:
                m = json.load(f)
        except (OSError, ValueError):
            return False
        return (m.get("model_kind", "value") in ("value", "shared_trunk")
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
    opponent_mix: float = 0.0,
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
    leaf is calibrated via the model's `value_scale` so `c_uct=1.0` is
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
        sims = int(mcts_sims) if mcts_sims is not None else _MCTS_SIMS_DEFAULT

        # Fast path: delegate to the C++ binary when it and the exported
        # weights are both present.  The C++ binary runs PUCT with the joint
        # shared-trunk model (shared_trunk_v1 manifest) and is ~4× faster than
        # the Python MCTSAgent.
        if (
            os.path.isfile(_CPP_BINARY)
            and os.path.isdir(_CPP_EXPORT_DIR)
            and os.path.isfile(os.path.join(_CPP_EXPORT_DIR, "weights_manifest.json"))
        ):
            return _CppMctsAgent(
                model_dir=_CPP_EXPORT_DIR,
                sims=sims,
                c_uct=1.0,
                temperature=0.2,
                prior_mix=opponent_mix,
                leaf_mode=_CPP_LEAF_MODE,
                mix_alpha=_CPP_MIX_ALPHA,
            )

        # Python MCTS fallback (no C++ binary or no exported weights).
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
            c_uct=1.0,
            fpu_offset=0.0,
            action_selection_temperature=0.2,
            rng_seed=seed,
            # Cap TOTAL root visits (tree-reuse-inherited + fresh) at
            # sims_per_move, rather than running that many FRESH sims each
            # move. Equalizes the effective search budget per decision
            # regardless of how much the re-rooted node inherited — so the
            # sims/move you pick is the real per-move budget (and UCT/PUCT
            # are compared on an equal footing, since peaked PUCT trees
            # inherit more). See MCTSAgent.cap_total_sims.
            cap_total_sims=True,
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


# Seat types allowed in the cards game. Cards has no bot yet, so an AI seat is
# limited to "random" (alongside "human"); the heuristic/MCTS/NN agents are
# Family-only.
CARDS_AGENT_TYPES: tuple[str, ...] = ("human", "random")


def _validate_seats(seats: tuple[str, str], game_mode: str) -> None:
    """Raise ValueError if any seat is illegal for the given game mode. Family
    mode allows every AGENT_TYPES seat; cards mode allows only human/random."""
    allowed = CARDS_AGENT_TYPES if game_mode == "cards" else AGENT_TYPES
    for s in seats:
        if s not in allowed:
            raise ValueError(
                f"unknown seat type {s!r} for game_mode {game_mode!r}; "
                f"choose from {allowed}"
            )


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
# Cards mode — card pool + display metadata
# ---------------------------------------------------------------------------
#
# The cards game is set up via setup_env(seed, card_pool=...) with the pool
# of all implemented cards; setup_env deals each player a non-overlapping 7
# occupations + 7 minors. _CARD_META holds display name / effect text / cost
# for every implemented card, joined from the card-data JSON by slugged name.

def _min_players_excluded_slugs() -> set:
    """Slugs of cards printed for 3+/4+ players only — excluded from the 2-player
    deal pool (per the official rules, these leave the deck below their player
    count). The cards stay implemented and registered; only dealing is gated.
    A slug is excluded only if EVERY catalog row bearing it is 3+/4+ (name
    collisions between distinct printings share a slug, so a 2p-legal printing
    keeps the slug dealable)."""
    data_dir = os.path.join(HERE, "agricola", "cards", "data")
    counts: dict[str, list] = {}
    try:
        for fname in ("revised_occupations.json", "revised_minor_improvements.json"):
            with open(os.path.join(data_dir, fname)) as f:
                for row in json.load(f):
                    counts.setdefault(_card_slug(row["name"]), []).append(row.get("players"))
    except Exception as exc:  # pragma: no cover — defensive at import time
        print(f"[play_web] WARNING: players-filter load failed: {exc}", file=sys.stderr)
        return set()
    return {slug for slug, ps in counts.items()
            if ps and all(p in ("3+", "4+", "5+", "6+") for p in ps)}


def _card_pool() -> "CardPool":
    """The card pool for a cards game: every implemented occupation + minor
    printed for 2 players (3+/4+-only cards are registered but never dealt)."""
    import agricola.cards  # noqa: F401  (registers OCCUPATIONS / MINORS)
    from agricola.cards.specs import OCCUPATIONS, MINORS
    excluded = _min_players_excluded_slugs()
    return CardPool(occupations=tuple(c for c in OCCUPATIONS if c not in excluded),
                    minors=tuple(c for c in MINORS if c not in excluded))


def _apply_custom_hand(
    state: "GameState",
    selected_occs: list,
    selected_mins: list,
    card_pool: "CardPool",
    seed: int,
) -> "GameState":
    """Overwrite P0's hand with the player's selections for the hand-picker feature.

    Selected cards are guaranteed to be in P0's hand.  Any slots not filled by
    the player (up to HAND_SIZE each) are drawn randomly from the remaining
    pool.  P1 receives the next HAND_SIZE cards from whatever is left over.
    A separate RNG (derived from the seed) is used so the game's own randomness
    is not perturbed.
    """
    import numpy as np
    from agricola.replace import fast_replace

    rng = np.random.default_rng(int(seed) ^ 0x7A5F3B91)

    pool_occs: set[str] = set(card_pool.occupations)
    pool_mins: set[str] = set(card_pool.minors)

    # Clamp to valid pool members and hand-size limit.
    sel_occs: list[str] = [c for c in selected_occs if c in pool_occs][:HAND_SIZE]
    sel_mins: list[str] = [c for c in selected_mins if c in pool_mins][:HAND_SIZE]

    # Cards not reserved by the player — shuffled for filling + P1.
    other_occs: list[str] = sorted(pool_occs - set(sel_occs))
    other_mins: list[str] = sorted(pool_mins - set(sel_mins))
    rng.shuffle(other_occs)  # type: ignore[arg-type]
    rng.shuffle(other_mins)  # type: ignore[arg-type]

    n_fill_occ = HAND_SIZE - len(sel_occs)
    n_fill_min = HAND_SIZE - len(sel_mins)

    p0_occs = frozenset(sel_occs) | frozenset(other_occs[:n_fill_occ])
    p0_mins = frozenset(sel_mins) | frozenset(other_mins[:n_fill_min])

    p1_occs = frozenset(other_occs[n_fill_occ : n_fill_occ + HAND_SIZE])
    p1_mins = frozenset(other_mins[n_fill_min : n_fill_min + HAND_SIZE])

    new_p0 = fast_replace(state.players[0], hand_occupations=p0_occs, hand_minors=p0_mins)
    new_p1 = fast_replace(state.players[1], hand_occupations=p1_occs, hand_minors=p1_mins)
    return fast_replace(state, players=(new_p0, new_p1))


def _card_slug(name: str) -> str:
    """The card_id bridge: slug(json_name) == card_id for every implemented card.

    Apostrophes are DROPPED (not turned into a separator) so a possessive name
    slugs to the natural id — "Shepherd's Crook" -> "shepherds_crook", not
    "shepherd_s_crook". Every other run of non-alphanumerics collapses to a single
    "_". (Dropping apostrophes introduces no new same-slug collisions across the
    full catalog — 18 names carry one, e.g. Carpenter's Apprentice, Potter's Yard.)
    """
    bare = name.lower().replace("'", "").replace("’", "")   # ASCII + curly apostrophe
    return re.sub(r"[^a-z0-9]+", "_", bare).strip("_")


def _fmt_cost(cost) -> str:
    """Render a Cost (Resources + Animals) as 'N name, ...' or '—' if free."""
    parts: list[str] = []
    r = cost.resources
    for field in ("wood", "clay", "reed", "stone", "food", "grain", "veg"):
        n = getattr(r, field)
        if n:
            parts.append(f"{n} {field}")
    a = cost.animals
    if a is not None:
        for field in ("sheep", "boar", "cattle"):
            n = getattr(a, field)
            if n:
                parts.append(f"{n} {field}")
    return ", ".join(parts) if parts else "—"


def _is_blank_json(value) -> bool:
    """A JSON cost/prerequisite cell that carries no real condition."""
    return value is None or str(value).strip().lower() in ("", "none", "-")


def _card_prereq(row: "dict | None", *, spendable_cost_empty: bool) -> str:
    """Human-readable prerequisite for a card, drawn from the JSON catalog.

    Two sources, joined: (1) the JSON `prerequisites` cell (e.g. Loom's "2
    Occupations"); and (2) a "have N in your supply" CONDITION that the catalog
    files under the `cost` cell for cards with no spendable cost (e.g. Thick
    Forest's "5 Clay in Your Supply" — the engine models it as a prereq, not a
    debit, so it would otherwise be invisible). Empty string if neither."""
    if not row:
        return ""
    parts: list[str] = []
    pre = row.get("prerequisites")
    if not _is_blank_json(pre):
        parts.append(str(pre).strip())
    jc = row.get("cost")
    if spendable_cost_empty and not _is_blank_json(jc):
        parts.append(str(jc).strip())
    return "; ".join(parts)


def _load_card_meta() -> dict[str, dict]:
    """Build {card_id: {name, type, text, cost, prereq}} for every implemented card.

    Joins the implemented OCCUPATIONS / MINORS registries to the card-data
    JSON rows by slugged name. Occupations are free (cost ""); minors format
    their structured Cost. `prereq` surfaces occupation/supply requirements.
    Guarded so a missing/malformed JSON leaves the table possibly partial
    rather than crashing the server at import."""
    meta: dict[str, dict] = {}
    try:
        import agricola.cards  # noqa: F401
        from agricola.cards.specs import OCCUPATIONS, MINORS
        data_dir = os.path.join(HERE, "agricola", "cards", "data")
        # Join key is the slugged name (== card_id). Two DISTINCT cards can share
        # a name — e.g. the Base-Revised "Market Stall" (the one we implement) and
        # the unrelated Corbarius "Market Stall" — so the slug, and thus card_id,
        # collides. Disambiguate by status: a card_id refers to the printing marked
        # "implemented", so prefer that row over any same-named non-implemented one
        # (otherwise a later, unimplemented printing would shadow the real card's
        # name/text/cost in the UI). Self-correcting as more cards are implemented.
        by_slug: dict[str, dict] = {}
        for fname in ("revised_occupations.json", "revised_minor_improvements.json"):
            with open(os.path.join(data_dir, fname)) as f:
                for row in json.load(f):
                    slug = _card_slug(row["name"])
                    prev = by_slug.get(slug)
                    if (prev is not None
                            and prev.get("status") == "implemented"
                            and row.get("status") != "implemented"):
                        continue   # keep the implemented printing; skip the shadow
                    by_slug[slug] = row
        for cid in OCCUPATIONS:
            row = by_slug.get(cid)
            meta[cid] = {
                "name": row["name"] if row else cid.replace("_", " ").title(),
                "type": "occupation",
                "text": row.get("text", "") if row else "",
                "cost": "",
                "prereq": _card_prereq(row, spendable_cost_empty=True),
                "vps": 0,   # occupations carry no printed VP in this game
                "deck": row.get("deck", "") if row else "",
            }
        for cid in MINORS:
            row = by_slug.get(cid)
            cost_str = _fmt_cost(MINORS[cid].cost)
            meta[cid] = {
                "name": row["name"] if row else cid.replace("_", " ").title(),
                "type": "minor",
                "text": row.get("text", "") if row else "",
                "cost": cost_str,
                "prereq": _card_prereq(row, spendable_cost_empty=(cost_str == "—")),
                "vps": int(MINORS[cid].vps),   # printed victory points (yellow circle)
                "deck": row.get("deck", "") if row else "",
            }
    except Exception as exc:  # pragma: no cover — defensive at import time
        print(f"[play_web] WARNING: card metadata load failed: {exc}", file=sys.stderr)
    return meta


_CARD_META: dict[str, dict] = _load_card_meta()


def _card_info(card_id: str) -> dict:
    """Display info for one card: {id, name, type, text, cost, prereq}. Falls
    back to a title-cased id with empty fields for an unknown id."""
    fallback = {
        "name": card_id.replace("_", " ").title(),
        "type": "",
        "text": "",
        "cost": "",
        "prereq": "",
        "vps": 0,
    }
    return {"id": card_id, **_CARD_META.get(card_id, fallback)}


def _played_card_info(state: GameState, idx: int, card_id: str,
                      reveal: bool = False) -> dict:
    """`_card_info` plus this card's live per-player state for player `idx`:
    a `bonus_vps` (history-derived "+X vp" emblem) and/or a `state_text` (a
    resource/counter badge) — both PUBLIC, attached for either seat. When `reveal`
    (this is the owner's own view, same rule as a hand), also attach an owner-only
    `state_text` for cards whose live value would leak a hidden fact to the opponent
    (Butler's play-round). See `agricola.cards.display`."""
    info = _card_info(card_id)
    bv = card_display.bonus_vps(card_id, state, idx)
    if bv is not None:
        info["bonus_vps"] = bv
    st = card_display.state_text(card_id, state.players[idx])
    if reveal and st is None:
        st = card_display.private_state_text(card_id, state.players[idx])
    if st:
        info["state_text"] = st
    return info


# ---------------------------------------------------------------------------
# UI hints per action type
# ---------------------------------------------------------------------------

def _ui_hint_for(action: Action) -> str:
    if isinstance(action, PlaceWorker):
        return "space"
    if isinstance(action, Stop):
        return "stop"
    if isinstance(action, (ChooseSubAction, FireTrigger, CommitRenovate, Proceed,
                           CommitCardChoice)):
        return "button"
    if isinstance(action, CommitBuildMajor):
        return "major"
    if isinstance(action, (CommitPlow, CommitBuildStable, CommitBuildRoom)):
        return "cell"
    if isinstance(action, CommitBuildPasture):
        return "cell_set"
    if isinstance(action, (CommitPlayOccupation, CommitPlayMinor)):
        return "card"
    if isinstance(action, CommitDraftPick):
        return "draft_card"
    # CommitSow, CommitBake, CommitAccommodate, CommitBreed, CommitConvert,
    # CommitHarvestConversion -> numeric / button-list.
    return "numeric"


def _payment_str(payment) -> str:
    """Render a PaymentOption (CommitRenovate / CommitChooseCost) for the web UI: a
    resource vector as 'N good, ...', a non-resource route by what it returns."""
    from agricola.cost import ReturnImprovement
    if isinstance(payment, ReturnImprovement):
        return f"return improvement #{payment.improvement_idx}"
    parts = [f"{getattr(payment, f)} {f}"
             for f in ("wood", "clay", "reed", "stone", "food", "grain", "veg")
             if getattr(payment, f)]
    return ", ".join(parts) if parts else "nothing"


def _payment_params(payment) -> dict:
    """JSON-able form of a PaymentOption for the action's `params`."""
    from agricola.cost import ReturnImprovement
    if isinstance(payment, ReturnImprovement):
        return {"route": "return_improvement", "improvement_idx": payment.improvement_idx}
    return {"route": "resources", **_resources_to_dict(payment)}


def _action_params(action: Action) -> dict:
    if isinstance(action, PlaceWorker):
        return {"space": action.space}
    if isinstance(action, ChooseSubAction):
        return {"name": action.name}
    if isinstance(action, FireTrigger):
        return {"card_id": action.card_id, "variant": getattr(action, "variant", None)}
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
        # CommitBuildMajor is now wide (payment: PaymentOption). Keep the derived
        # `return_fireplace_idx` in the wire format (None for a resource payment, the
        # fireplace idx for a ReturnImprovement route) so the existing frontend
        # (static/app.js) renders the Cooking-Hearth return variants unchanged.
        from agricola.cost import ReturnImprovement
        rf = (action.payment.improvement_idx
              if isinstance(action.payment, ReturnImprovement) else None)
        return {
            "major_idx": action.major_idx,
            "return_fireplace_idx": rf,
            "payment": _payment_params(action.payment),
        }
    if isinstance(action, CommitRenovate):
        return {"payment": _payment_params(action.payment)}
    if isinstance(action, CommitChooseCost):
        return {"payment": _payment_params(action.payment)}
    if isinstance(action, CommitAccommodate):
        return {"sheep": action.sheep, "boar": action.boar, "cattle": action.cattle}
    if isinstance(action, CommitBuildPasture):
        return {"cells": sorted([list(c) for c in action.cells])}
    if isinstance(action, CommitHarvestConversion):
        return {"conversion_id": action.conversion_id}
    if isinstance(action, (CommitConvert, CommitFoodPayment)):
        return {
            "grain": action.grain, "veg": action.veg,
            "sheep": action.sheep, "boar": action.boar, "cattle": action.cattle,
        }
    if isinstance(action, CommitBreed):
        return {"sheep": action.sheep, "boar": action.boar, "cattle": action.cattle}
    if isinstance(action, CommitPlayOccupation):
        return {"card_id": action.card_id, "variant": getattr(action, "variant", None)}
    if isinstance(action, CommitPlayMinor):
        return {"card_id": action.card_id, "variant": getattr(action, "variant", None)}
    if isinstance(action, CommitCardChoice):
        return {"index": action.index}
    if isinstance(action, CommitDraftPick):
        return {"card_id": action.card_id}
    return {}


# Friendly labels for play-variant trigger routes (Cottager, Scholar), so the two
# buttons of a single trigger read distinctly instead of both as the card name.
_TRIGGER_VARIANT_LABELS = {
    "room": "build a room",
    "renovate": "renovate",
    "occupation": "play an occupation",
    "minor": "play a minor",
}

_FIELD_GROUP_RE = re.compile(r"^(grain|veg)(\d+):(\d+)$")


def _trigger_variant_label(variant: str) -> str:
    """Human label for a FireTrigger variant: the static route labels, plus the
    field-count-vector encoding of the harvest-field triggers (Stable Manure) —
    "grain3:1|veg2:2" -> "+1 grain (from a 3-grain field), +2 veg (from 2-veg fields)"."""
    if variant in _TRIGGER_VARIANT_LABELS:
        return _TRIGGER_VARIANT_LABELS[variant]
    parts = []
    for part in variant.split("|"):
        m = _FIELD_GROUP_RE.match(part)
        if not m:
            return variant                       # not a count vector — raw fallback
        crop, remaining, count = m.group(1), m.group(2), int(m.group(3))
        fields = f"a {remaining}-{crop} field" if count == 1 else f"{count} {remaining}-{crop} fields"
        parts.append(f"+{count} {crop} (from {fields})")
    return ", ".join(parts)


def _web_action_display(action: Action) -> str:
    """Human-readable label for an action in the web UI.

    Same as play.py's `_fmt_action_inline` for most action types, EXCEPT:
    - the two card-play commits render as the card's real display name (e.g.
      "Clay Hut Builder") instead of the raw dataclass repr; and
    - a FireTrigger renders as its card's name, with its play-variant route
      appended when present — so a variant trigger like Cottager shows two
      distinct buttons ("Cottager: build a room" / "Cottager: renovate") rather
      than two identical `FireTrigger('cottager')`s.
    """
    if isinstance(action, CommitDraftPick):
        return _card_info(action.card_id)["name"]
    if isinstance(action, (CommitPlayOccupation, CommitPlayMinor)):
        name = _card_info(action.card_id)["name"]
        variant = getattr(action, "variant", None)
        return f"{name} [{variant}]" if variant else name
    if isinstance(action, FireTrigger):
        name = _card_info(action.card_id)["name"]
        variant = getattr(action, "variant", None)
        if variant:
            return f"{name}: {_trigger_variant_label(variant)}"
        return name
    # Payment-bearing commits (cost-modifier cards): show the chosen payment so the
    # multiple options of a renovate / two-step build read distinctly.
    if isinstance(action, CommitRenovate):
        return f"Renovate (pay {_payment_str(action.payment)})"
    if isinstance(action, CommitChooseCost):
        return f"Pay {_payment_str(action.payment)}"
    if isinstance(action, CommitFoodPayment):
        # Raise food to pay a card cost: show the goods cooked/eaten (animals at their
        # cooking_rates, grain/veg at 1:1). Always non-empty — the frame only appears when
        # food on hand is short, so every frontier point consumes something.
        spent = [f"{getattr(action, f)} {f}"
                 for f in ("grain", "veg", "sheep", "boar", "cattle") if getattr(action, f)]
        return "Pay with " + (", ".join(spent) if spent else "food on hand")
    return _fmt_action_inline(action)


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


# Order goods are listed in an "owed" slot — food first, since the Well (the
# only Family-game source) promises food.
_OWED_RESOURCE_ORDER = ("food", "grain", "veg", "wood", "clay", "reed", "stone")


def _owed_future(p, round_number: int) -> list[dict]:
    """Goods/benefits a player is promised at the START of future rounds — the
    Well grants +1 food at the start of each of its next 5 rounds (and, with
    cards, scheduled goods/animals). This is PUBLIC information (a built Well is
    visible to both players), so it is surfaced for both seats; the UI must not
    hide non-hidden information.

    `future_resources[idx]` / `future_rewards[idx]` are delivered at the start of
    round `idx + 1`, so only slots for rounds strictly after the current one are
    still owed. Returns one entry per such round that carries anything, in round
    order: `{"round": int, "text": str}` (display string built server-side, per
    the wire-format convention)."""
    out = []
    for idx in range(len(p.future_resources)):
        rnd = idx + 1
        if rnd <= round_number:
            continue  # already delivered (the slot was cleared at that round's start)
        parts = []
        res = p.future_resources[idx]
        for fld in _OWED_RESOURCE_ORDER:
            v = getattr(res, fld)
            if v:
                parts.append(f"{v} {fld}")
        # future_rewards is card-only (empty in the Family game) — forward-compat:
        # surface any scheduled animals too.
        animals = p.future_rewards[idx].animals
        for fld in ("sheep", "boar", "cattle"):
            v = getattr(animals, fld)
            if v:
                parts.append(f"{v} {fld}")
        if parts:
            out.append({"round": rnd, "text": ", ".join(parts)})
    return out


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


def _player_to_dict(state: GameState, idx: int, decider: int,
                    reveal_hand: bool = False) -> dict:
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
    fences_left  = buildable_fences(p)
    stables_left = stables_in_supply(p.farmyard)
    out = {
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
        # Goods/benefits owed at the start of future rounds (Well food, etc.) —
        # public info, shown for both seats. Empty unless a Well/scheduling card
        # has been built.
        "owed_future": _owed_future(p, state.round_number),
        "fences_built":   15 - fences_left,
        "fences_total":   15,
        "stables_built":  4  - stables_left,
        "stables_total":  4,
        "majors": majors,
        # Played occupations and minor improvements are PUBLIC tableau — visible
        # to both players (unlike the private hand) with full name + effect text,
        # so each is sent as a card-info dict regardless of `reveal_hand`. Empty in
        # the Family game. `played_occupations` is new (occupations were previously
        # not surfaced at all, so they vanished once played).
        "played_occupations": [_played_card_info(state, idx, cid, reveal_hand) for cid in sorted(p.occupations)],
        "played_minors": [_played_card_info(state, idx, cid, reveal_hand) for cid in sorted(p.minor_improvements)],
        "farmyard": _farmyard_to_dict(p.farmyard),
        # Hand sizes are common knowledge (empty in Family mode); the hand
        # CONTENTS are private and only revealed for a human seat.
        "hand_counts": {
            "occupations": len(p.hand_occupations),
            "minors": len(p.hand_minors),
        },
    }
    if reveal_hand:
        out["hand"] = (
            [{**_card_info(cid), "type": "occupation"} for cid in sorted(p.hand_occupations)]
            + [_card_info(cid) for cid in sorted(p.hand_minors)]
        )
    return out


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


# The fixed 25-space board carries BOTH "side_job" and "lessons", but each game
# mode uses only one of that pair: the Family game uses Side Job (Lessons is a
# permanently-inert dead tile), and the card game replaces Side Job with Lessons.
# Hide the mode-inert tile so the action board shows only the usable one in that
# slot, rather than a confusing tile you can never place on.
_MODE_INERT_SPACE = {GameMode.FAMILY: "lessons", GameMode.CARDS: "side_job"}


def _board_to_dict(state: GameState) -> dict:
    spaces = []
    inert = _MODE_INERT_SPACE.get(state.mode)
    for sid, ss in zip(SPACE_IDS, state.board.action_spaces):
        if sid == inert:
            continue
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


def _card_choice_display(state: GameState, action: CommitCardChoice) -> str:
    """Label a CommitCardChoice by the option it picks (e.g. "Choose: grain"),
    read off the top PendingCardChoice frame's `options`, instead of the raw repr."""
    top = state.pending_stack[-1] if state.pending_stack else None
    opts = getattr(top, "options", ())
    if 0 <= action.index < len(opts):
        return f"Choose: {opts[action.index]}"
    return _web_action_display(action)


def _legal_actions_to_dicts(state: GameState, actions: list[Action]) -> list[dict]:
    out = []
    for i, a in enumerate(actions):
        display = (_card_choice_display(state, a)
                   if isinstance(a, CommitCardChoice) else _web_action_display(a))
        out.append({
            "index": i,
            "type": type(a).__name__,
            "display": display,
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
    # Occupation + minor card scoring: printed VPs (the yellow circle) plus
    # per-card scoring terms (e.g. Loom's 1 VP per 3 sheep). 0 in the Family
    # game. Without this row the line items don't sum to the total and card
    # points (Loom, etc.) appear nowhere.
    ("Cards",           "card_points"),
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

    # A player's private hand is only ever revealed for a HUMAN seat (an AI/
    # opponent seat's hand always stays hidden). Among human seats the rule
    # depends on how many there are:
    #   - One human (vs an AI): that human always sees their own hand, even
    #     while the AI is on the clock.
    #   - Two humans (pass-and-play): only the ACTIVE player's hand is shown,
    #     so handing the device over doesn't leak the other player's cards.
    # The active player is the current decider (whose decision is awaited); at
    # a nature step (decider is None) we fall back to current_player. Family
    # hands are empty, so this is harmless there.
    seat_list = list(seats) if seats is not None else ["human", "human"]
    human_seats = [i for i in (0, 1) if seat_list[i] == "human"]
    active_player = decider if decider is not None else state.current_player

    def _reveal_hand(i: int) -> bool:
        if seat_list[i] != "human":
            return False
        if len(human_seats) <= 1:
            return True
        return i == active_player

    payload = {
        "round_number": state.round_number,
        "phase": state.phase.name,
        "starting_player": state.starting_player,
        "current_player": state.current_player,
        "decider": decider,
        "harvest_note": _harvest_note(state),
        "game_over": game_over,
        "seats": seat_list,
        "players": [
            _player_to_dict(state, i, decider, reveal_hand=_reveal_hand(i))
            for i in (0, 1)
        ],
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

    def capture(self) -> tuple:
        """Snapshot the mutable log state so undo_turn can restore it.

        Returns an opaque tuple (entries + the in-progress buffer) that
        `restore` consumes. Part of the turn-snapshot mechanism."""
        return (
            list(self.entries),
            self._buf_round,
            self._buf_decider,
            list(self._buf_parts),
        )

    def restore(self, snap: tuple) -> None:
        """Restore a `capture()` snapshot (undo to the start of a turn)."""
        entries, buf_round, buf_decider, buf_parts = snap
        self.entries = list(entries)
        self._buf_round = buf_round
        self._buf_decider = buf_decider
        self._buf_parts = list(buf_parts)

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
        confirm_mode: bool = False,
        game_mode: str = "family",
        hand_mode: str = "draft",
    ) -> None:
        _validate_seats(seats, game_mode)
        # A random per-Session identity, sent to the client in every snapshot. The
        # client remembers it; when it changes underneath them (the server
        # restarted/redeployed and this in-memory registry was rebuilt, or their
        # session was evicted), the client knows the game it was playing is gone.
        # A user-initiated "New game" reuses THIS Session object (reset()), so the
        # id is stable across resets and never false-triggers the notice.
        self.instance_id = secrets.token_hex(8)
        self.game_mode = game_mode
        # How card hands are set up: "draft" (competitive pick-one-at-a-time),
        # "random" (fully random deal), or "choose" (player-selected hand via the
        # hand picker UI, vs non-human opponents only). Only meaningful for
        # game_mode == "cards". For human-vs-human, "draft" is the only
        # interactive option (pass-and-play handoff).
        self.hand_mode: str = hand_mode if game_mode == "cards" else "random"
        # Pass-and-play draft handoff: set True when the decider changes during
        # Phase.DRAFT; requires /api/draft_handoff_ack before human actions proceed.
        self._draft_handoff_pending: bool = False
        self._prev_draft_decider: int = -1  # -1 sentinel: no previous pick yet
        self.seed = seed
        self.seats = seats
        self.mcts_sims = mcts_sims  # None means use _MCTS_SIMS_DEFAULT
        # MCTS seat configuration (only consulted for 'mcts' seats):
        # leaf-evaluator id, search mode ("uct"/"puct"), and PUCT policy
        # variant ("unweighted"/"awr"). See _build_agent.
        self.mcts_evaluator = mcts_evaluator
        self.mcts_search = mcts_search
        self.mcts_policy = mcts_policy
        # Opponent's policy-prior uniform mix (0 = pure policy / standard bot).
        # Set >0 (e.g. 0.05) via /api/opponent_mix to make the bot explore more.
        # Persists across resets (the client re-asserts via the payload).
        self.opponent_mix: float = 0.0
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
        # ---- Turn snapshot / undo / confirm ----
        # confirm_mode: when ON, a completed human turn (one that involved a
        # real choice) pauses for an explicit Confirm before the AI replies,
        # giving an undo window on every turn. Singleton/forced turns never
        # pause (see submit_human_action).
        self.confirm_mode: bool = confirm_mode
        # awaiting_confirm: a non-trivial human turn is finished and waiting
        # for /api/confirm_turn (only set while confirm_mode is on).
        self.awaiting_confirm: bool = False
        # turn_snapshot: the (immutable) GameState + trace/log bookmark at the
        # START of the human's current turn, so undo_turn can restore it for
        # free (states are immutable — holding an old one is cheap). None when
        # we're not inside a human turn. See _post_advance_locked.
        self.turn_snapshot: dict | None = None
        # turn_had_choice: did the in-progress human turn involve a decision
        # among >1 legal actions? Gates the confirm pause so forced turns
        # don't prompt.
        self.turn_had_choice: bool = False
        self.humans: set[int] = {i for i, s in enumerate(seats) if s == "human"}
        # Live "Show analysis" subprocess (a C++ `selfplay --analyze` run for
        # the human's current state). Read-only background search whose output
        # the frontend overlays. Cancelled when the human moves / resets so it
        # never competes with the bot's reply. Guarded by `_analysis_lock`
        # (NOT self.lock) so the analyze thread can terminate it without
        # contending for the main game lock.
        self._analysis_proc: "subprocess.Popen | None" = None
        self._analysis_lock = threading.Lock()
        # Per-seat agent objects; None for human seats.
        self.agents = self._make_agents()
        self.state, self.env = self._setup_for_mode(seed)
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
        # Order in which the stage action-spaces have been revealed, by space
        # id. The round-1 card is revealed at setup; the rest accrue as the
        # game advances. Drives the action board's reveal-ordered layout
        # (round_revealed = index + 1). Seeded from the initial state.
        self.reveal_order: list[str] = []
        self._seed_reveal_order_locked()
        # If at least one seat is human, fast-forward any opening AI moves
        # until a human decision is reached. With no humans (AI-vs-AI), we
        # leave the state as-is and require explicit /api/step_ai calls.
        with self.lock:
            if self.humans:
                self._drive_until_decision_locked()
                self._post_advance_locked()

    def _seed_reveal_order_locked(self) -> None:
        """Seed reveal_order from the current state's already-revealed stage
        spaces (the round-1 card at game start)."""
        self.reveal_order = [
            sid for sid, ss in zip(SPACE_IDS, self.state.board.action_spaces)
            if ss.revealed and sid not in PERMANENT_ACTION_SPACES_SET
        ]

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
            opponent_mix=self.opponent_mix,
        )
        return (
            _build_agent(self.seats[0], self.seed ^ 0x10000, **mcts_kw),
            _build_agent(self.seats[1], self.seed ^ 0x20000, **mcts_kw),
        )

    def _setup_for_mode(self, seed: int):
        """Build the initial (state, env) for this session's game mode."""
        if self.game_mode == "cards":
            if self.hand_mode == "draft":
                return setup_env(seed, card_pool=_card_pool(), draft=True)
            return setup_env(seed, card_pool=_card_pool())
        return setup_env(seed)

    # ---------- state queries ----------

    def snapshot(self) -> dict:
        with self.lock:
            return self._build_payload_locked()

    def trace_snapshot(self) -> dict:
        """Return the full session trace (seed + seats + ordered actions).

        Self-contained replay payload: feeding `setup(seed)` and stepping
        each entry's (type, params) reconstructs the exact game state. The
        `display` field is for human eyeballing; consumers that replay
        should use `type` + `params`.

        `params` records the game-start configuration the bot ran under —
        the effective sims/move budget, the opponent prior-mix, the fixed
        c_uct, and the NN checkpoint + MCTS seat settings — so a downloaded
        trace is self-describing (e.g. "this game was played at 1600 sims")
        rather than leaving the reader to guess the search budget.
        """
        with self.lock:
            return {
                "seed": self.seed,
                "seats": list(self.seats),
                "current_round": self.current_round,
                "phase": self.state.phase.name,
                "game_over": self.game_over,
                "params": {
                    "sims": (self.mcts_sims if self.mcts_sims is not None
                             else _MCTS_SIMS_DEFAULT),
                    "opponent_mix": self.opponent_mix,
                    "c_uct": 1.0,
                    "nn_model": _NN_MODEL_PATH,
                    "mcts_evaluator": self.mcts_evaluator,
                    "mcts_search": self.mcts_search,
                    "mcts_policy": self.mcts_policy,
                },
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
            "display": _web_action_display(action),
        })
        self.log.add(dec, action, self.current_round)
        # Record stage-card reveals in order (drives the action-board layout).
        if isinstance(action, RevealCard) and action.card not in self.reveal_order:
            self.reveal_order.append(action.card)
        self.state = step(self.state, action)
        self._maybe_round_transition_locked()
        if self.state.phase == Phase.BEFORE_SCORING:
            self.game_over = True
        # Any AI/nature move ends (or precedes) a human turn, so it
        # invalidates the current turn snapshot — the next time control
        # settles on the human, _post_advance_locked takes a fresh one.
        # (decider None = nature; that's not a human either.)
        if dec not in self.humans:
            self.turn_snapshot = None

    # ---------- turn snapshot / undo / confirm ----------

    def _turn_signature_locked(self) -> str:
        """A signature for the human's current decision ROOT.

        A worker-placement turn (and all the sub-decisions it spawns) is one
        turn, signature 'turn'. Each harvest feed / breed decision is its own
        turn (the user's model), so it gets a distinct signature — these are
        the only human turns that can follow one another with NO intervening
        AI move to invalidate the snapshot (FEED -> BREED is a system phase
        transition). The signature lets _post_advance_locked tell that
        feed->breed boundary apart from a worker turn's own sub-frames (which
        must NOT start a new turn)."""
        top = self.state.pending_stack[-1] if self.state.pending_stack else None
        if isinstance(top, (PendingHarvestFeed, PendingHarvestBreed)):
            return type(top).__name__
        return "turn"

    def _capture_turn_snapshot_locked(self, sig: str) -> None:
        self.turn_snapshot = {
            "state": self.state,            # immutable — cheap to hold
            "trace_len": len(self.action_trace),
            "log": self.log.capture(),
            "current_round": self.current_round,
            "sig": sig,
        }
        self.turn_had_choice = False

    def _post_advance_locked(self) -> None:
        """Run after every drive: (re)capture the turn snapshot when control
        has settled on a human at the start of a NEW turn.

        A turn ends when an AI/nature move is applied (which clears the
        snapshot in _apply_action_locked), so normally we capture exactly when
        `turn_snapshot is None`. The one exception is harvest feed -> breed:
        two consecutive human turns with no AI move between them, so the
        snapshot wasn't cleared — we detect the harvest-signature change and
        re-capture. Crucially we do NOT re-capture on a worker turn's own
        sub-frames (signature stays 'turn'), so undo rewinds the whole
        placement, not just the last sub-decision."""
        if self.game_over:
            self.turn_snapshot = None
            self.awaiting_confirm = False
            return
        dec = _decider_of(self.state)
        if dec not in self.humans:
            return

        # Draft handoff detection (pass-and-play only: both seats human).
        if (len(self.humans) == 2
                and self.state.phase == Phase.DRAFT
                and self.state.pending_stack):
            top = self.state.pending_stack[-1]
            if isinstance(top, PendingDraftPick):
                if (self._prev_draft_decider != -1
                        and top.player_idx != self._prev_draft_decider):
                    self._draft_handoff_pending = True
                self._prev_draft_decider = top.player_idx

        sig = self._turn_signature_locked()
        if self.turn_snapshot is None:
            self._capture_turn_snapshot_locked(sig)
        elif sig.startswith("PendingHarvest") and sig != self.turn_snapshot["sig"]:
            # feed -> breed: a new harvest turn with no AI move to clear it.
            self._capture_turn_snapshot_locked(sig)

    def _build_payload_locked(self) -> dict:
        """The full wire payload for the current state: the game state plus the
        undo/confirm fields and the toggle states. The server is authoritative
        for everything the UI shows, including the toggle checkboxes."""
        payload = state_to_json(
            self.state,
            self.log.to_wire(self.current_round),
            self.game_over,
            [] if self.game_over else legal_actions(self.state),
            seats=self.seats,
            interactive_ai_paused=self._interactive_ai_paused_here_locked(),
        )
        payload["game_mode"] = self.game_mode
        payload["hand_mode"] = self.hand_mode
        payload["draft_handoff"] = self._draft_handoff_pending
        # Draft info: which round of the draft, who is picking, and what type.
        if self.state.phase == Phase.DRAFT and self.state.pending_stack:
            from agricola.setup import HAND_SIZE as _HAND_SIZE
            top = self.state.pending_stack[-1]
            if isinstance(top, PendingDraftPick):
                p0_occ, p0_min, p1_occ, p1_min = self.state.draft_pools
                max_size = max(len(p0_occ), len(p0_min), len(p1_occ), len(p1_min))
                # Include full card metadata for both the picking player's pools
                # so the draft modal can render card details without an extra fetch.
                player_occ = p0_occ if top.player_idx == 0 else p1_occ
                player_min = p0_min if top.player_idx == 0 else p1_min
                def _pool_meta(ids):
                    return [{"card_id": cid, **_CARD_META.get(cid, {"name": cid})}
                            for cid in ids]
                player = self.state.players[top.player_idx]
                payload["draft_info"] = {
                    "round": _HAND_SIZE - max_size + 1,
                    "total_rounds": _HAND_SIZE,
                    "picking_player": top.player_idx,
                    "card_type": top.card_type,
                    "occ_pool": _pool_meta(player_occ),
                    "min_pool": _pool_meta(player_min),
                    "picked_occs": _pool_meta(sorted(player.hand_occupations)),
                    "picked_mins": _pool_meta(sorted(player.hand_minors)),
                }
        payload["session_id"] = self.instance_id
        payload["awaiting_confirm"] = self.awaiting_confirm
        payload["confirm_mode"] = self.confirm_mode
        payload["fast_mode"] = self.fast_mode
        payload["interactive_ai"] = self.interactive_ai
        payload["opponent_mix"] = self.opponent_mix
        # Per-space reveal round (1-based; None for permanents / unrevealed) so
        # the action board can lay stage spaces out in reveal order.
        reveal_idx = {sid: i + 1 for i, sid in enumerate(self.reveal_order)}
        for sp in payload["board"]["spaces"]:
            sp["round_revealed"] = reveal_idx.get(sp["id"])
        # Undo is part of the confirm-turns feature: only offered when
        # confirm_mode is ON. (With confirm off you play committed/fast — no
        # undo.) And only once the human has actually changed something this
        # turn — i.e. the live state has diverged from the turn snapshot (at
        # turn start, state IS the snapshot, so there's nothing to undo).
        payload["can_undo"] = (
            self.confirm_mode
            and self.turn_snapshot is not None
            and not self.game_over
            and self.state is not self.turn_snapshot["state"]
        )
        payload["mcts_sims"] = self.mcts_sims if self.mcts_sims is not None else _MCTS_SIMS_DEFAULT
        return payload

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
            # Bound concurrent AI searches across all games (CPU control).
            with _AI_SEMAPHORE:
                action = agent(self.state)
            self._apply_action_locked(action)

    def submit_human_action(self, action_index: int) -> tuple[bool, str]:
        # Cancel any in-flight "Show analysis" search before resolving the
        # move, so it doesn't compete with the bot's reply for CPU. Done
        # outside self.lock (it only touches _analysis_lock).
        self._cancel_analysis()
        with self.lock:
            if self.game_over:
                return False, "game over"
            if self.awaiting_confirm:
                return False, "awaiting turn confirmation"
            if self._draft_handoff_pending:
                return False, "awaiting draft handoff acknowledgment"
            actions = legal_actions(self.state)
            if not (0 <= action_index < len(actions)):
                # The board the client clicked is stale (already changed). The
                # response still carries the current state, so the client just
                # re-renders — no double-apply, no freeze.
                return False, f"action_index {action_index} out of range (0..{len(actions)-1})"
            dec = _decider_of(self.state)
            if dec not in self.humans:
                return False, "not a human's turn"
            # Safety net: ensure a turn snapshot exists (normally set by
            # _post_advance_locked when control arrived here).
            if self.turn_snapshot is None:
                self._capture_turn_snapshot_locked(self._turn_signature_locked())
            # A choice among >1 options makes this a "real" turn — only those
            # trigger the confirm pause (forced/singleton turns never do).
            if len(actions) > 1:
                self.turn_had_choice = True
            self._apply_action_locked(actions[action_index])
            # Did the human's turn just end (control would pass to AI/nature)?
            turn_complete = self.game_over or (_decider_of(self.state) not in self.humans)
            if (self.confirm_mode and not self.game_over and turn_complete
                    and self.turn_had_choice):
                # Hold before driving the AI; the user can Confirm or Undo.
                self.awaiting_confirm = True
            elif self.humans:
                self._drive_until_decision_locked()
                self._post_advance_locked()
        return True, "ok"

    def confirm_turn(self) -> tuple[bool, str]:
        """Commit a turn that's paused awaiting confirmation: drive the AI's
        reply. No-op error if nothing is awaiting confirmation."""
        with self.lock:
            if not self.awaiting_confirm:
                return False, "no turn awaiting confirmation"
            self.awaiting_confirm = False
            if self.humans:
                self._drive_until_decision_locked()
                self._post_advance_locked()
        return True, "ok"

    def undo_turn(self) -> tuple[bool, str]:
        """Rewind to the start of the human's in-progress (or just-completed-
        but-unconfirmed) turn. Restores the immutable snapshot state plus the
        trace/log bookmark. Repeatable (the snapshot is kept)."""
        with self.lock:
            # Undo is a confirm-turns feature only.
            if not self.confirm_mode:
                return False, "undo is only available with confirm-turns on"
            if self.turn_snapshot is None or self.game_over:
                return False, "nothing to undo"
            snap = self.turn_snapshot
            self.state = snap["state"]
            self.action_trace = self.action_trace[:snap["trace_len"]]
            self.log.restore(snap["log"])
            self.current_round = snap["current_round"]
            self.awaiting_confirm = False
            self.turn_had_choice = False
        return True, "ok"

    def set_confirm_mode(self, confirm_mode: bool) -> None:
        """Toggle confirm-turn mode. Never rewinds game state: turning ON just
        arms the pause for future completed turns; turning OFF while a turn is
        paused commits it (drives the AI). The caller reads the resulting state
        via snapshot()."""
        with self.lock:
            self.confirm_mode = bool(confirm_mode)
            if not self.confirm_mode and self.awaiting_confirm:
                self.awaiting_confirm = False
                if self.humans:
                    self._drive_until_decision_locked()
                    self._post_advance_locked()

    def set_fast_mode(self, fast_mode: bool) -> None:
        """Toggle server-side fast mode and (if turning ON) immediately
        auto-advance through any pending human singletons."""
        with self.lock:
            prev = self.fast_mode
            self.fast_mode = bool(fast_mode)
            if self.fast_mode and not prev and self.humans and not self.game_over:
                self._drive_until_decision_locked()
                self._post_advance_locked()

    def set_interactive_ai(self, interactive_ai: bool) -> None:
        """Toggle interactive-AI mode. When turning OFF, resume the auto-driver
        from wherever we paused. When turning ON, the toggle takes effect the
        next time the auto-driver would auto-apply an AI top-level placement."""
        with self.lock:
            prev = self.interactive_ai
            self.interactive_ai = bool(interactive_ai)
            if prev and not self.interactive_ai and not self.game_over:
                self._drive_until_decision_locked()
                self._post_advance_locked()

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
                "display": _web_action_display(action),
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

    # ---------- "Show analysis" (read-only MCTS overlay) ----------

    def _cancel_analysis(self) -> None:
        """Terminate any in-flight analysis subprocess so it stops competing
        with the bot's reply. Thread-safe and idempotent; called when the human
        moves (submit_human_action) and on reset. The analyze thread holds a
        reference to the Popen it launched, so terminating here just makes its
        `communicate()` return early — it discards the (now-stale) output."""
        with self._analysis_lock:
            proc = self._analysis_proc
            self._analysis_proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def analyze(self, sims: int, c_uct: float = 1.0,
                prior_mix: float = 0.05, leaf_mode: str | None = None,
                mix_alpha: float | None = None) -> tuple[bool, list[dict], str]:
        """Run a read-only MCTS analysis rooted at the human's current state.

        `c_uct` controls exploration; analysis coverage (a Q for several of the
        human's options, not just the single best line) comes from the uniform
        `prior_mix`, which spreads visits across more moves.

        Analysis is decoupled from how the bot plays: `leaf_mode`
        ("margin" / "outcome" / "mix") selects which value head supplies the
        backed-up leaf Q, and `mix_alpha` is the blend weight for the "mix"
        leaf (`α·margin + (1−α)·outcome`). Both default to the deployed bot's
        leaf (`_CPP_LEAF_MODE` / `_CPP_MIX_ALPHA`) when not given, so the
        overlay matches the bot's evaluation unless the caller overrides it.

        Returns (ok, children, value_target) where children mirror the C++
        `--analyze` contract: [{type, params, visits, q}, ...] with q already in
        the human's frame (higher = better for the human) and denormalized into
        the value head's natural units (the C++ side multiplies the raw Q by the
        model's value_scale). `value_target` ("margin" / "outcome" / "mix")
        labels what those units mean: "margin" => points of expected score
        diff, "outcome" => expected win/draw/loss value in [-1,1], "mix" => the
        RAW unitless margin/outcome blend. ok=False (empty children, "margin")
        when it's not a human's turn, the game is over, the C++ binary/export
        are missing, or the search fails.

        Does NOT mutate game state and does NOT go through self.lock for the
        search itself — only a brief lock to read the state JSON. The search
        runs under `_AI_SEMAPHORE` (bounded concurrency, shared with the bot)
        and via Popen so submit_human_action can cancel it mid-flight."""
        # Read-only snapshot of the state to analyze (brief lock).
        with self.lock:
            if self.game_over:
                return False, [], "margin"
            if _decider_of(self.state) not in self.humans:
                return False, [], "margin"
            state_json = dumps(self.state)
        # Graceful no-op when the C++ fast path isn't available.
        if not (os.path.isfile(_CPP_BINARY) and os.path.isdir(_CPP_EXPORT_DIR)
                and os.path.isfile(os.path.join(_CPP_EXPORT_DIR, "weights_manifest.json"))):
            return False, [], "margin"
        mode = leaf_mode if leaf_mode is not None else _CPP_LEAF_MODE
        alpha = mix_alpha if mix_alpha is not None else _CPP_MIX_ALPHA
        cmd = [
            _CPP_BINARY, "--analyze",
            "--model-dir", _CPP_EXPORT_DIR,
            "--sims", str(sims),
            "--c-uct", str(c_uct),
            "--temperature", "0.2",
            # Leaf head the analysis evaluates with (margin / outcome / mix) —
            # chosen by the caller, independent of how the bot plays. For the
            # mix leaf the C++ side emits the RAW Q (unitless blend) with
            # value_target "mix", forwarded unchanged below.
            "--leaf-mode", mode, "--mix-alpha", str(alpha),
        ]
        if prior_mix > 0.0:
            cmd += ["--prior-mix", str(prior_mix)]
        with _AI_SEMAPHORE:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except OSError:
                return False, [], "margin"
            # Register so a concurrent human move can cancel it.
            with self._analysis_lock:
                # Cancel any prior in-flight analysis we may be replacing.
                prev = self._analysis_proc
                self._analysis_proc = proc
            if prev is not None and prev.poll() is None:
                try:
                    prev.terminate()
                except OSError:
                    pass
            try:
                out, _err = proc.communicate(input=state_json.encode(), timeout=60)
            except Exception:
                try:
                    proc.kill()
                except OSError:
                    pass
                return False, [], "margin"
            finally:
                with self._analysis_lock:
                    if self._analysis_proc is proc:
                        self._analysis_proc = None
        # A non-zero return code means it was cancelled (terminate) or failed.
        if proc.returncode != 0:
            return False, [], "margin"
        try:
            data = json.loads(out.decode())
            children = data.get("children", [])
            # The q-unit descriptor ("margin" / "outcome"); default "margin" for
            # an older binary that doesn't emit it.
            value_target = str(data.get("value_target", "margin"))
        except (ValueError, UnicodeDecodeError):
            return False, [], "margin"
        if not isinstance(children, list):
            return False, [], "margin"
        return True, children, value_target

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
            self._post_advance_locked()
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
        opponent_mix: float = 0.0,
        game_mode: str = "family",
        hand_mode: str = "draft",
        custom_hand: dict | None = None,
    ) -> None:
        _validate_seats(seats, game_mode)
        # Cancel any in-flight analysis from the previous game.
        self._cancel_analysis()
        with self.lock:
            self.game_mode = game_mode
            self.hand_mode = hand_mode if game_mode == "cards" else "random"
            self._draft_handoff_pending = False
            self._prev_draft_decider = -1
            self.seed = seed
            self.seats = seats
            self.mcts_sims = mcts_sims
            self.mcts_evaluator = mcts_evaluator
            self.mcts_search = mcts_search
            self.mcts_policy = mcts_policy
            # Opponent prior-mix is chosen per game (New-game dialog).
            self.opponent_mix = max(0.0, float(opponent_mix))
            self.humans = {i for i, s in enumerate(seats) if s == "human"}
            self.agents = self._make_agents()
            self.state, self.env = self._setup_for_mode(seed)
            # Hand-picker: overwrite P0's dealt hand with the player's selection.
            if custom_hand and self.game_mode == "cards":
                self.state = _apply_custom_hand(
                    self.state,
                    custom_hand.get("occupations", []),
                    custom_hand.get("minors", []),
                    _card_pool(),
                    seed,
                )
            self.log = RoundLog(self.humans)
            self.current_round = self.state.round_number
            self.game_over = (self.state.phase == Phase.BEFORE_SCORING)
            # Drop any prior session's trace; this is a fresh game.
            self.action_trace = []
            self._seed_reveal_order_locked()
            # Fresh game: clear the turn-snapshot / confirm state. confirm_mode
            # and fast_mode persist across resets (server-authoritative; the
            # client reflects whatever the reset response reports).
            self.awaiting_confirm = False
            self.turn_snapshot = None
            self.turn_had_choice = False
            if self.humans:
                self._drive_until_decision_locked()
                self._post_advance_locked()


# ---------------------------------------------------------------------------
# Session registry — multi-tenant: one Session per browser (cookie-keyed)
# ---------------------------------------------------------------------------

class SessionRegistry:
    """Holds the live game sessions, one per browser, keyed by an opaque
    cookie id. Online deployment needs this (the old singleton meant every
    visitor shared one board). Game state lives in memory only — an evicted
    or expired game is gone, which is acceptable for a hobby deployment.

    `make_session(seed)` is a factory capturing the startup config (seats =
    human vs mcts, the mcts knobs, fast/confirm defaults). Capacity is bounded
    by `_MAX_GAMES` with LRU eviction; idle games past `_GAME_IDLE_TTL` are
    swept lazily on creation."""

    def __init__(self, make_session) -> None:
        self._make_session = make_session
        self._sessions: dict[str, Session] = {}
        self._access: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, gid: str | None) -> Session | None:
        if not gid:
            return None
        with self._lock:
            sess = self._sessions.get(gid)
            if sess is not None:
                self._access[gid] = time.time()
            return sess

    def create(self) -> tuple[str, Session]:
        """Create a fresh game, returning (gid, session). Sweeps idle games
        and enforces the capacity cap first."""
        # Build the session OUTSIDE the registry lock (it runs the opening
        # drive, which can call the AI). Insert under the lock.
        sess = self._make_session(secrets.randbits(31))
        with self._lock:
            self._sweep_idle_locked()
            while len(self._sessions) >= _MAX_GAMES and self._sessions:
                self._evict_lru_locked()
            gid = secrets.token_urlsafe(16)
            self._sessions[gid] = sess
            self._access[gid] = time.time()
            return gid, sess

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _evict_lru_locked(self) -> None:
        oldest = min(self._access, key=self._access.get)
        self._sessions.pop(oldest, None)
        self._access.pop(oldest, None)

    def _sweep_idle_locked(self) -> None:
        cutoff = time.time() - _GAME_IDLE_TTL
        stale = [g for g, t in self._access.items() if t < cutoff]
        for g in stale:
            self._sessions.pop(g, None)
            self._access.pop(g, None)


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


def _make_handler(registry: SessionRegistry):
    class Handler(BaseHTTPRequestHandler):
        # Set to a game id when this request created a new session; the
        # senders emit it as a Set-Cookie so the browser is bound to its game.
        _set_cookie_gid: str | None = None

        # Silence default per-request logging.
        def log_message(self, format, *args):
            return

        # ---------- session resolution (multi-tenant) ----------
        def _read_gid(self) -> str | None:
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            try:
                jar = SimpleCookie(raw)
            except Exception:
                return None
            morsel = jar.get(_GID_COOKIE)
            return morsel.value if morsel else None

        def _session(self) -> Session:
            """Resolve this browser's game session, creating one (and stamping
            a Set-Cookie) if it has none yet."""
            sess = registry.get(self._read_gid())
            if sess is None:
                gid, sess = registry.create()
                self._set_cookie_gid = gid
            return sess

        def _emit_set_cookie(self) -> None:
            if self._set_cookie_gid:
                self.send_header(
                    "Set-Cookie",
                    f"{_GID_COOKIE}={self._set_cookie_gid}; Path=/; "
                    f"HttpOnly; SameSite=Lax; Max-Age=86400",
                )

        # ---------- helpers ----------
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._emit_set_cookie()
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, status: int, text: str, ctype: str = "text/plain; charset=utf-8") -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._emit_set_cookie()
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
            self._emit_set_cookie()
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
                # Ensure this browser has a game session (sets the cookie on
                # first visit) before serving the page.
                self._session()
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
                self._send_json(HTTPStatus.OK, self._session().snapshot())
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
                payload = self._session().trace_snapshot()
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
                self._emit_set_cookie()
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/cards_list":
                # All cards available in the pool, with display metadata.
                # Used by the hand-picker overlay in the Cards new-game flow.
                pool = _card_pool()
                occs = sorted(
                    [_card_info(cid) for cid in pool.occupations],
                    key=lambda c: c["name"],
                )
                mins = sorted(
                    [_card_info(cid) for cid in pool.minors],
                    key=lambda c: c["name"],
                )
                self._send_json(HTTPStatus.OK, {"occupations": occs, "minors": mins})
                return
            if path == "/api/ai_preview":
                ok, msg, rows = self._session().ai_preview()
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {
                    "ok": ok, "error": None if ok else msg, "rows": rows,
                })
                return
            self._send_text(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            # Every POST acts on the caller's game session.
            session = self._session()
            if path == "/api/step":
                body = self._read_body()
                idx = body.get("action_index")
                if not isinstance(idx, int):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "action_index must be int"})
                    return
                ok, msg = session.submit_human_action(idx)
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                # Always return the current authoritative state so the client
                # renders it whether the action applied or was rejected (e.g. a
                # click on a board that already changed) — the single source of
                # truth, and self-healing by construction.
                self._send_json(status, {
                    "ok": ok, "error": None if ok else msg,
                    "state": session.snapshot(),
                })
                return
            if path == "/api/draft_handoff_ack":
                # Acknowledge the pass-and-play draft handoff (human clicked "Ready").
                # Clears the pending flag so the new picker's actions are accepted.
                with session.lock:
                    session._draft_handoff_pending = False
                self._send_json(HTTPStatus.OK, {"ok": True, "state": session.snapshot()})
                return
            if path == "/api/confirm_turn":
                # Commit a turn paused awaiting confirmation (drive the AI).
                ok, msg = session.confirm_turn()
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {
                    "ok": ok, "error": None if ok else msg,
                    "state": session.snapshot(),
                })
                return
            if path == "/api/undo_turn":
                # Rewind to the start of the in-progress / unconfirmed turn.
                ok, msg = session.undo_turn()
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {
                    "ok": ok, "error": None if ok else msg,
                    "state": session.snapshot(),
                })
                return
            if path == "/api/confirm_mode":
                body = self._read_body()
                value = body.get("enabled")
                if not isinstance(value, bool):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "enabled must be a boolean",
                    })
                    return
                session.set_confirm_mode(value)
                self._send_json(HTTPStatus.OK, {
                    "ok": True, "confirm_mode": value,
                    "state": session.snapshot(),
                })
                return
            if path == "/api/step_ai":
                # No body required — just advance one AI move.
                ok, msg = session.step_ai()
                status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
                self._send_json(status, {
                    "ok": ok, "error": None if ok else msg,
                    "state": session.snapshot(),
                })
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
                self._send_json(HTTPStatus.OK, {
                    "ok": True, "fast_mode": value,
                    "state": session.snapshot(),
                })
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
                    "state": session.snapshot(),
                })
                return
            if path == "/api/analyze":
                # Read-only: run MCTS on the human's current state and return
                # each candidate move's visit count + value. Does not mutate
                # game state. All search params come from the client and are
                # independent of how the bot plays: c_uct (exploration), sims
                # (search budget), leaf_mode (margin/outcome/mix value head),
                # and mix_alpha (blend weight for the mix leaf). Cancelled when
                # the human moves.
                body = self._read_body()
                c_uct = body.get("c_uct", 1.0)
                if not (isinstance(c_uct, (int, float)) and c_uct > 0):
                    c_uct = 1.0
                sims = body.get("sims")
                if not (isinstance(sims, int) and sims >= 1):
                    sims = (session.mcts_sims if session.mcts_sims is not None
                            else _MCTS_SIMS_DEFAULT)
                leaf_mode = body.get("leaf_mode")
                if leaf_mode not in ("margin", "outcome", "mix"):
                    leaf_mode = None  # fall back to the bot's deployed leaf
                mix_alpha = body.get("mix_alpha")
                if not (isinstance(mix_alpha, (int, float)) and 0.0 <= mix_alpha <= 1.0):
                    mix_alpha = None
                ok, children, value_target = session.analyze(
                    sims, float(c_uct), leaf_mode=leaf_mode,
                    mix_alpha=(float(mix_alpha) if mix_alpha is not None else None))
                self._send_json(HTTPStatus.OK, {
                    "ok": ok, "children": children, "value_target": value_target})
                return
            if path == "/api/reset":
                # New game in the SAME session (same cookie). The seed is taken
                # from the client (optional). game_mode picks Family (human vs
                # the joint-model MCTS bot) or cards (human vs random — cards
                # has no bot yet, so the MCTS knobs are ignored there).
                body = self._read_body()
                seed = body.get("seed")
                if not isinstance(seed, int):
                    seed = secrets.randbits(31)
                game_mode = body.get("game_mode", "family")
                if game_mode not in ("family", "cards"):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "game_mode must be 'family' or 'cards'",
                    })
                    return
                if game_mode == "cards":
                    # Cards: human vs random by default; no bot, so no MCTS
                    # knobs. Seats are taken from the body (each human/random).
                    seats = body.get("seats", ["human", "random"])
                    if (not isinstance(seats, list) or len(seats) != 2
                            or any(s not in CARDS_AGENT_TYPES for s in seats)):
                        self._send_json(HTTPStatus.BAD_REQUEST, {
                            "ok": False,
                            "error": f"cards seats must each be one of {CARDS_AGENT_TYPES}",
                        })
                        return
                    seats = tuple(seats)
                    # hand_mode: "draft" (pick one card at a time), "random" (fully
                    # random deal), or "choose" (player-selected hand, non-human opp only).
                    hand_mode = body.get("hand_mode", "draft")
                    if hand_mode not in ("draft", "random", "choose"):
                        self._send_json(HTTPStatus.BAD_REQUEST, {
                            "ok": False,
                            "error": "hand_mode must be 'draft', 'random', or 'choose'",
                        })
                        return
                    if hand_mode == "choose" and all(s == "human" for s in seats):
                        self._send_json(HTTPStatus.BAD_REQUEST, {
                            "ok": False,
                            "error": "hand_mode 'choose' is only available vs a non-human opponent",
                        })
                        return
                    # Optional hand selection from the hand-picker UI (choose mode only).
                    # {occupations: [...ids], minors: [...ids]} — any subset of
                    # the pool; missing slots are randomised.  None = fully random.
                    custom_hand = body.get("custom_hand") if hand_mode == "choose" else None
                    if custom_hand is not None and not isinstance(custom_hand, dict):
                        self._send_json(HTTPStatus.BAD_REQUEST, {
                            "ok": False,
                            "error": "custom_hand must be an object or null",
                        })
                        return
                    session.reset(seed, seats, game_mode="cards", hand_mode=hand_mode,
                                  custom_hand=custom_hand or None)
                    self._send_json(HTTPStatus.OK, {
                        "ok": True,
                        "seed": seed,
                        "seats": list(seats),
                        "game_mode": "cards",
                        "hand_mode": hand_mode,
                        "state": session.snapshot(),
                    })
                    return
                seats = _DEFAULT_SEATS
                # Optional sims/move override for the MCTS bot.
                mcts_sims = body.get("mcts_sims")
                if mcts_sims is not None and not (isinstance(mcts_sims, int) and mcts_sims >= 1):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "mcts_sims must be a positive integer",
                    })
                    return
                # Optional opponent prior-uniform-mix for this game (0 = standard).
                opponent_mix = body.get("opponent_mix", 0.0)
                if not (isinstance(opponent_mix, (int, float)) and opponent_mix >= 0):
                    self._send_json(HTTPStatus.BAD_REQUEST, {
                        "ok": False,
                        "error": "opponent_mix must be a number >= 0",
                    })
                    return
                session.reset(seed, seats, game_mode="family", mcts_sims=mcts_sims,
                              opponent_mix=float(opponent_mix))
                self._send_json(HTTPStatus.OK, {
                    "ok": True,
                    "seed": seed,
                    "seats": list(seats),
                    "game_mode": "family",
                    "mcts_sims": mcts_sims if mcts_sims is not None else _MCTS_SIMS_DEFAULT,
                    "opponent_mix": float(opponent_mix),
                    "state": session.snapshot(),
                })
                return
            self._send_text(HTTPStatus.NOT_FOUND, "not found")

    return Handler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Browser UI for AgricolaBot.")
    ap.add_argument("--seed", type=int, default=None,
                    help="Engine RNG seed (default: time-based).")
    ap.add_argument(
        "--seats", nargs=2, choices=AGENT_TYPES, default=["human", "mcts"],
        metavar="AGENT",
        help=(
            "Seat assignments for P0 and P1, used for every game created in "
            "the session registry. Default: human mcts (play the joint-model "
            "MCTS bot)."
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
        "--mcts-sims", type=int, default=800,
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
    global _MCTS_SIMS_DEFAULT, _NN_MODEL_PATH, _DEFAULT_SEATS
    args = parse_args()
    if args.v3_config is not None:
        _TUNED_V3_CONFIG = _load_v3_config_from_json(args.v3_config)
        _TUNED_V3_SOURCE_PATH = args.v3_config
    _RESTRICTED = bool(args.restricted)
    _MCTS_SIMS_DEFAULT = int(args.mcts_sims)
    _DEFAULT_SEATS = (args.seats[0], args.seats[1])
    # Behavior-transparent MCTS enumeration speedups (read at call time by
    # helpers.py / legality.py, so setting them here before any game starts is
    # sufficient). Default off → byte-identical to baseline.
    from agricola import opt_config as _opt_config
    _opt_config.PARETO_OPT_LEVEL = int(args.opt_level)
    _opt_config.FENCE_SCAN_CACHE = bool(args.fence_cache)
    if args.nn_model is not None:
        _NN_MODEL_PATH = _resolve_nn_model_path(args.nn_model)
    # The 'mcts' seat prefers the torch-free C++ binary; when it's present the
    # Python NN checkpoint (best.pt) is never loaded, so it need not be on disk
    # (the Docker image ships only the C++ export). Only require the checkpoint
    # when a seat genuinely needs the Python NN: an 'nn' seat, or an 'mcts'
    # seat with no C++ fast path available.
    cpp_available = (
        os.path.isfile(_CPP_BINARY)
        and os.path.isdir(_CPP_EXPORT_DIR)
        and os.path.isfile(os.path.join(_CPP_EXPORT_DIR, "weights_manifest.json"))
    )
    needs_py_nn = ("nn" in _DEFAULT_SEATS) or ("mcts" in _DEFAULT_SEATS and not cpp_available)
    if needs_py_nn and not (os.path.exists(_NN_MODEL_PATH + ".pt")
                            and os.path.exists(_NN_MODEL_PATH + ".meta.json")):
        print(f"error: NN checkpoint not found at {_NN_MODEL_PATH!r} "
              f"(expected {_NN_MODEL_PATH}.pt + .meta.json). "
              f"Pass a checkpoint dir or '<dir>/best' stem via --nn-model.",
              file=sys.stderr)
        sys.exit(2)

    def make_session(seed: int) -> Session:
        return Session(seed=seed, seats=_DEFAULT_SEATS)

    registry = SessionRegistry(make_session)
    handler = _make_handler(registry)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"AgricolaBot WebUI - seats={list(_DEFAULT_SEATS)} (per-browser games)")
    print(f"  AI opponent: {'C++ joint-model MCTS' if cpp_available else 'Python MCTS (no C++ binary)'}")
    print(f"  AI seats use restricted_legal_actions: {'ON' if _RESTRICTED else 'OFF'}")
    print(f"  MCTS default sims/move: {_MCTS_SIMS_DEFAULT}")
    print(f"  Max concurrent AI searches: {_MAX_CONCURRENT_AI}  |  max live games: {_MAX_GAMES}")
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
