"""Game-trace serialization + the trace-replay adapter (CPP_ENGINE_PLAN.md §2).

The C++ self-play binary will emit compact **game traces** (an initial state +
the full ordered action list, with the search's π / root_value attached to each
searched decision). This module is the Python side of that contract:

- :func:`game_to_trace` — the *writer* (also the §3.2 differential-test trace
  source): plays a game and records a trace.
- :func:`replay_trace` — the *reader / adapter*: replays a trace through the
  unchanged Python engine and rebuilds a :class:`GameRecord`, which flows
  straight into the existing ``build_datasets`` → train pipeline.

Two things make this work (CPP_ENGINE_PLAN.md §2.1):

1. ``RevealCard`` is a normal ``step`` action carrying its card id, so a trace
   that includes the reveals replays through pure ``step`` with **zero**
   ``Environment`` access. We close the web-UI bug where ``RevealCard``'s card
   id was dropped (the per-type ``params`` here is field-complete).
2. The trace carries the **canonical initial-state dump** (not just a seed), so
   replay is independent of the C++ binary's RNG — the action trace, not the
   seed, is the source of truth.

Action ``params`` mirror the web-UI ``_action_params`` shape (``play_web.py``)
so a web-downloaded trace and a C++-emitted trace share one reader.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from agricola import actions as _actions_mod
from agricola.actions import Action, RevealCard
from agricola.agents.base import LegalActionsFn, decider_of
from agricola.cost import RESOURCE_FIELDS, ReturnImprovement
from agricola.resources import Resources
from agricola.agents.nn.schema import (
    DATA_VERSION,
    DecisionSnapshot,
    GameRecord,
    compute_winner,
)
from agricola.canonical import from_canonical, to_canonical
from agricola.constants import HouseMaterial, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.scoring import score, tiebreaker
from agricola.state import GameState
from tests.test_utils import filter_implemented

TRACE_SCHEMA = "agricola-cpp-trace-v1"

# Action class registry: every concrete dataclass in agricola.actions except the
# ``CommitSubAction`` marker base (which is never instantiated directly).
_ACTION_CLASSES: dict[str, type] = {
    obj.__name__: obj
    for name in dir(_actions_mod)
    if isinstance((obj := getattr(_actions_mod, name)), type)
    and dataclasses.is_dataclass(obj)
    and obj.__module__ == _actions_mod.__name__
    and obj.__name__ != "CommitSubAction"
}


# ---------------------------------------------------------------------------
# Action <-> trace params
# ---------------------------------------------------------------------------


def _payment_to_json(pay: Any) -> dict[str, Any]:
    """Serialize a ``PaymentOption`` (``CommitRenovate.payment`` etc.) — a tagged dict
    so the inverse can tell a resource payment from a non-resource route. Mirrored by
    the C++ trace emitter (CPP_ENGINE_PLAN.md / COST_MODIFIER_DESIGN.md §3.8)."""
    if isinstance(pay, ReturnImprovement):
        return {"route": "return_improvement", "improvement_idx": pay.improvement_idx}
    return {"route": "resources", **{f: getattr(pay, f) for f in RESOURCE_FIELDS}}


def _payment_from_json(d: dict[str, Any]) -> Any:
    if d.get("route") == "return_improvement":
        return ReturnImprovement(int(d["improvement_idx"]))
    return Resources(**{f: int(d[f]) for f in RESOURCE_FIELDS})


def action_to_params(action: Action) -> dict[str, Any]:
    """Serialize an action's fields to a JSON-able ``params`` dict.

    Two non-scalar field shapes occur across the action types:
    ``CommitBuildPasture.cells`` (a ``frozenset[tuple[int, int]]``), emitted as a
    sorted list of ``[row, col]`` pairs; and the ``payment`` of the wide commits
    (a ``PaymentOption`` — ``Resources`` or ``ReturnImprovement``), emitted as a
    tagged dict (:func:`_payment_to_json`).
    """
    params: dict[str, Any] = {}
    for f in dataclasses.fields(action):
        v = getattr(action, f.name)
        # Card-only `variant` fields are DEFAULT-SKIPPED when None (the
        # action-side analog of canonical's default-skip): a Family action
        # never sets one, so omitting it keeps the Family wire encoding — and
        # the C++ legality gates, which compare these params byte-for-byte —
        # unchanged when a variant field is added to an action Family also
        # uses (CommitHarvestConversion, 2026-07-06). `action_from_params`
        # restores the dataclass default for the missing key.
        if f.name == "variant" and v is None:
            continue
        if isinstance(v, frozenset):
            params[f.name] = [list(t) for t in sorted(v)]
        elif isinstance(v, (Resources, ReturnImprovement)):
            params[f.name] = _payment_to_json(v)
        elif f.name == "to_material":
            params[f.name] = v.name          # HouseMaterial enum -> "WOOD"/"CLAY"/"STONE"
        else:
            params[f.name] = v
    return params


def action_from_params(type_name: str, params: dict[str, Any]) -> Action:
    """Inverse of :func:`action_to_params`."""
    cls = _ACTION_CLASSES[type_name]
    kwargs: dict[str, Any] = {}
    for k, v in params.items():
        if k == "cells":
            kwargs[k] = frozenset(tuple(c) for c in v)
        elif isinstance(v, dict) and "route" in v:
            kwargs[k] = _payment_from_json(v)
        elif k == "to_material":
            kwargs[k] = HouseMaterial[v]
        else:
            kwargs[k] = v
    return cls(**kwargs)


def _action_entry(
    state: GameState,
    action: Action,
    *,
    visit_distribution: dict[Action, int] | None = None,
    root_value: float | None = None,
) -> dict[str, Any]:
    """Build one trace action entry (the web-UI shape + optional π/root_value)."""
    decider = decider_of(state)
    entry: dict[str, Any] = {
        "round": state.round_number,
        "phase": state.phase.name,
        "decider": decider,
        "type": type(action).__name__,
        "params": action_to_params(action),
        "display": str(action),
    }
    if visit_distribution is not None:
        entry["visit_distribution"] = [
            [action_to_params(a), int(n)] for a, n in visit_distribution.items()
        ]
        # the action TYPE is needed to reconstruct each π key
        entry["visit_distribution_types"] = [
            type(a).__name__ for a in visit_distribution
        ]
    if root_value is not None:
        entry["root_value"] = float(root_value)
    return entry


def _visit_distribution_from_entry(entry: dict[str, Any]) -> dict[Action, int] | None:
    vd = entry.get("visit_distribution")
    if vd is None:
        return None
    types = entry["visit_distribution_types"]
    return {
        action_from_params(t, params): int(n)
        for t, (params, n) in zip(types, vd)
    }


# ---------------------------------------------------------------------------
# Writer: game -> trace
# ---------------------------------------------------------------------------


def game_to_trace(
    initial_state: GameState,
    p0_agent: Callable[[GameState], Action],
    p1_agent: Callable[[GameState], Action],
    *,
    dealer: Callable[[GameState], Action],
    seed: int,
    legal_actions_fn: LegalActionsFn = legal_actions,
) -> dict[str, Any]:
    """Play one full game and record it as a trace dict.

    The agent is consulted at **every** player decision (singletons included),
    matching ``play_recording_game`` so that an identically-seeded run produces
    an identical game. Reveals are routed to ``dealer`` and recorded as explicit
    ``RevealCard`` entries. (Stage 0: ``visit_distribution`` / ``root_value`` are
    left unset — the C++ MCTS binary fills them at Stage 6.)
    """
    state = initial_state
    actions_log: list[dict[str, Any]] = []
    while state.phase != Phase.BEFORE_SCORING:
        decider = decider_of(state)
        if decider is None:
            action = dealer(state)
        else:
            action = (p0_agent, p1_agent)[decider](state)
        actions_log.append(_action_entry(state, action))
        state = step(state, action)
    return {
        "schema": TRACE_SCHEMA,
        "seed": seed,
        "initial_state": to_canonical(initial_state),
        "actions": actions_log,
    }


# ---------------------------------------------------------------------------
# Reader / adapter: trace -> GameRecord
# ---------------------------------------------------------------------------


def replay_trace(
    trace: dict[str, Any],
    *,
    game_idx: int = 0,
    p0_config_path: str = "cpp_selfplay",
    p1_config_path: str = "cpp_selfplay",
    p0_temperature: float = 1.0,
    p1_temperature: float = 1.0,
    legal_actions_fn: LegalActionsFn = legal_actions,
) -> GameRecord:
    """Replay a trace through the Python engine and rebuild a ``GameRecord``.

    A ``DecisionSnapshot`` is recorded at exactly the states that are
    non-singleton player decisions; the trace is authoritative for the
    ``visit_distribution`` / ``root_value`` attached to each (CPP_ENGINE_PLAN.md
    §2.4). The recorded ``decider`` is cross-checked against the replayed state
    as a cheap drift guard.

    Identifying the non-singleton decisions: replay never uses ``legal_actions``
    to *validate* the trace's actions (``step`` applies them unconditionally),
    only to decide which states are decisions worth snapshotting. MCTS self-play
    traces already carry that signal — the search records a ``visit_distribution``
    *only* on non-singleton decisions — so "entry has a ``visit_distribution``"
    is exactly equivalent to the singleton test
    ``len(filter_implemented(legal_actions_fn(state))) > 1`` (verified
    set-identical). Using it skips ``legal_actions`` entirely, which matters
    because that call re-runs the animal-accommodation frontier (the
    ``PARETO_OPT_LEVEL`` Phi build) — pathologically slow on big late-game farms
    (tens of seconds for a single game) yet pointless here, since replay visits
    each state once and the Phi build has nothing to amortize against. Value-only
    traces (no ``visit_distribution`` recorded anywhere) carry no such signal and
    fall back to ``legal_actions_fn``.
    """
    if trace.get("schema") != TRACE_SCHEMA:
        raise ValueError(
            f"unexpected trace schema {trace.get('schema')!r}, "
            f"expected {TRACE_SCHEMA!r}"
        )
    state: GameState = from_canonical(trace["initial_state"])
    decisions: list[DecisionSnapshot] = []

    # If the trace records pi on any action it is an MCTS self-play trace, where
    # pi-presence marks exactly the non-singleton decisions (see docstring) — so
    # we can avoid the expensive legal_actions call. A value-only trace records
    # no pi anywhere and must re-derive decisions via legal_actions.
    trace_records_pi = any(e.get("visit_distribution") for e in trace["actions"])

    for i, entry in enumerate(trace["actions"]):
        action = action_from_params(entry["type"], entry["params"])
        decider = decider_of(state)
        if entry.get("decider") != decider:
            raise ValueError(
                f"trace drift at action {i}: recorded decider={entry.get('decider')} "
                f"but replayed decider_of(state)={decider} "
                f"(round={state.round_number}, phase={state.phase.name})"
            )
        if decider is not None:
            if trace_records_pi:
                is_decision = bool(entry.get("visit_distribution"))
            else:  # value-only trace — no pi signal, re-derive via legality
                is_decision = len(filter_implemented(legal_actions_fn(state))) > 1
            if is_decision:
                decisions.append(DecisionSnapshot(
                    state=state,
                    chosen_action=action,
                    decider_idx=decider,
                    visit_distribution=_visit_distribution_from_entry(entry),
                    root_value=entry.get("root_value"),
                ))
        state = step(state, action)

    if state.phase != Phase.BEFORE_SCORING:
        raise ValueError(
            "trace did not reach a terminal state "
            f"(ended at round={state.round_number}, phase={state.phase.name})"
        )

    p0_total, _ = score(state, 0)
    p1_total, _ = score(state, 1)
    p0_tb = tiebreaker(state, 0)
    p1_tb = tiebreaker(state, 1)
    winner = compute_winner(p0_total, p1_total, p0_tb, p1_tb)

    return GameRecord(
        data_version=DATA_VERSION,
        game_idx=game_idx,
        seed=trace["seed"],
        p0_config_path=p0_config_path,
        p1_config_path=p1_config_path,
        p0_temperature=p0_temperature,
        p1_temperature=p1_temperature,
        p0_final_score=p0_total,
        p1_final_score=p1_total,
        winner=winner,
        terminal_state=state,
        decisions=tuple(decisions),
    )
