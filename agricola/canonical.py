"""Canonical, deterministic (de)serialization of ``GameState``.

This is the **shared contract** the C++ engine must reproduce byte-for-byte in
the differential-test harness (CPP_ENGINE_PLAN.md §3.1). It is *test / interop
scaffolding only* — nothing on a production path imports it, and the existing
engine is never modified; this module only reads it.

Design: a fully self-describing, tag-driven JSON form. Each value carries
enough information to reconstruct itself with no type hints, so the format is
trivial to mirror in C++ (each side already knows its own struct/dataclass
field types) and the Python deserializer needs no ``typing`` introspection.

Encoding:

=====================  ============================================================
Python value           Canonical JSON
=====================  ============================================================
frozen dataclass       ``{"__type__": "<ClassName>", "<field>": <v>, ...}``  (declaration order)
``enum.Enum`` member    ``{"__enum__": "<EnumClassName>", "name": "<MEMBER>"}``
``frozenset``           ``{"__set__": [<element>, ...]}``  (deterministically sorted)
``tuple``               ``[<element>, ...]``  (JSON array)
int / bool / str / float / None   the JSON primitive
=====================  ============================================================

The ``_hash_cache`` slot (``object.__setattr__`` on the frozen state objects) is
not a dataclass field, so the generic walker excludes it automatically.

Guarantees:
- ``dumps(loads(dumps(s))) == dumps(s)`` (byte-identical round-trip), and
- ``loads(dumps(s)) == s`` and ``hash(loads(dumps(s))) == hash(s)``.

The real cross-language gate (Stage 1+) is that the C++ serializer emits the
*same* string for the equivalent state.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from typing import Any

from agricola import actions as _actions_mod
from agricola import constants as _constants_mod
from agricola import pasture as _pasture_mod
from agricola import pending as _pending_mod
from agricola import resources as _resources_mod
from agricola import state as _state_mod
from agricola.state import GameState

# Modules scanned to build the name -> type registry the deserializer dispatches
# on. Order is irrelevant; a class is registered under its own ``__name__``.
_REGISTRY_MODULES = (
    _state_mod,
    _resources_mod,
    _pasture_mod,
    _pending_mod,
    _actions_mod,
    _constants_mod,
)

_DATACLASSES: dict[str, type] = {}
_ENUMS: dict[str, type] = {}


def _build_registry() -> None:
    for mod in _REGISTRY_MODULES:
        for name in dir(mod):
            obj = getattr(mod, name)
            if not isinstance(obj, type):
                continue
            # Only types DEFINED in this module (skip re-exports / imports).
            if getattr(obj, "__module__", None) != mod.__name__:
                continue
            if dataclasses.is_dataclass(obj):
                _DATACLASSES[obj.__name__] = obj
            elif issubclass(obj, enum.Enum):
                _ENUMS[obj.__name__] = obj


_build_registry()


# ---------------------------------------------------------------------------
# Serialize
# ---------------------------------------------------------------------------


# Card-game fields OMITTED from the JSON when they hold their default. A Family
# state always holds the default for each (mode=FAMILY, empty hands), so its JSON
# is byte-identical to the pre-card format and the C++ Family differential gates
# stay green with no C++ change; a CARDS state carries non-default values, so they
# ARE emitted (and the C++ card port will then read them). Round-trip is preserved
# because an omitted field falls back to its dataclass default in `from_canonical`.
#
# This is a NAMED allow-list, NOT a blanket "skip any field == its default": many
# existing fields routinely equal their defaults in a Family game (pending_stack=(),
# newborns=0, harvest_conversions_used=frozenset(), …) and skipping THOSE would
# change the Family JSON and break the very gates this protects. The names below
# occur on GameState / PlayerState, plus the three `build_*_action` flags on the
# build-pending frames (PendingBuildFences / Stables / Rooms): those are
# Family-constant True (every Family build IS a literal action), so omitting them
# keeps the Family JSON byte-identical and needs no C++ change; a CARDS card-effect
# build sets one False, which is then emitted (and read by the card port).
# See CARD_IMPLEMENTATION_PLAN.md I.1 and COST_MODIFIER_DESIGN.md §9.6.
#
# `accrued_cost` / `free_fence_budget` on PendingBuildFences are the Cards-only
# deferred-tally fields (COST_MODIFIER_DESIGN.md §9.2): a Family build debits
# per-commit and never accrues, so both hold their defaults (Resources(), 0) in
# every Family state — omitting them keeps the Family JSON byte-identical and
# needs no C++ change; a CARDS fence build sets them, which is then emitted.
_DEFAULT_SKIP_FIELDS = frozenset({
    "mode", "hand_occupations", "hand_minors",
    "used_this_turn", "used_this_round", "fired_once",
    "card_state", "future_rewards", "draft_pools",
    "build_fences_action", "build_stables_action", "build_rooms_action",
    "accrued_cost", "free_fence_budget", "restrictions",
    "must_preserve_base",
    # Card-only animal-overflow reconciliation flag (engine._reconcile_accommodation):
    # Family-constant False (Family never grants animals decision-free), so omitting it
    # keeps the Family JSON byte-identical and needs no C++ change.
    "animals_need_accommodation",
    # PendingPlow multi-shot grant fields (Swing/Turnwrest/Wheel Plow): Family-constant
    # defaults (every Family plow is single-shot), so omitting them keeps the Family JSON
    # byte-identical and needs no C++ change.
    "max_plows", "num_plowed",
    # PendingSow cap for card-granted partial sows (Fodder Planter's per-newborn
    # one-field sows): Family-constant 0 (= uncapped, every Family sow), so omitting
    # it keeps the Family JSON byte-identical and needs no C++ change.
    "max_fields",
    # PendingSow crops-only flag for crops-explicit sow grants (user ruling 48,
    # 2026-07-12 — "sow crops" cannot target wood/stone card-fields): Family-constant
    # False (no card-fields exist there), so omitting it keeps the Family JSON
    # byte-identical and needs no C++ change.
    "crops_only",
    # The harvest-window walk cursor (engine._advance_harvest): skipped when None
    # (any non-harvest state, and every pre-ruling-40 Family state). Since the
    # FEED/BREED banding (ruling 40, 2026-07-12) the FAMILY game carries it while a
    # payment/breeding frame is up (values 14/17/20/23), so mid-feed/mid-breed
    # Family JSON now EMITS it — mirrored by the C++ engine (the banding re-port).
    "harvest_cursor",
    # Card-only round-end walk cursor (engine._advance_round_end, rulings 49/50):
    # set only while a round-end window's choice frame pauses the walk —
    # Family-constant None (no round-end cards → no frames), so omitting it keeps
    # the Family JSON byte-identical and needs no C++ change.
    "round_end_cursor",
    # Card-only preparation walk cursor (engine._advance_preparation, ruling 54,
    # 2026-07-14): set only while a prep window's choice frame pauses the walk —
    # never across the reveal (the post-reveal resume is derived from public
    # state), so Family-constant None and omitted; the C++ engine needs no field.
    "prep_cursor",
    # The reveal-round stamp on ActionSpaceState (user decision 2026-07-15, the
    # reveal-order card family): skipped only when None (an unrevealed stage
    # card — matching the pre-change JSON for those); every REVEALED space
    # emits it (permanents 0, stage cards their round), so this is
    # Family-REACHABLE and the C++ twin mirrors the field, the stamp at the
    # reveal, and the setup 0s.
    "revealed_round",
    # The deferred after-flip signal on every commit-terminated host (user ruling
    # 2026-07-14: "after you [do X]" fires after X's FULL effect): set by the
    # commit executor, cleared when _advance_until_decision flips the host, so it
    # is True only in states where the effect's own pushed frames are still up.
    # Family-REACHABLE there — the ovens' free-bake wrapper over PendingBuildMajor
    # — so mid-free-bake Family JSON EMITS it, mirrored by the C++ engine (the
    # deferred-flip re-port). Every other state omits it at the default False.
    "effect_initiated",
    # QUALIFIED entries ("<Type>.<field>") skip a field on ONE dataclass only —
    # for a field whose NAME is emitted on other (Family) frames but whose value
    # is Family-constant-default on this one. PendingHarvestBreed exists in every
    # Family harvest, but only cards ever stamp its triggers_resolved (the
    # in-breeding-phase card triggers, Stone Importer et al.), so omitting it at
    # default keeps the Family JSON byte-identical with no C++ change — while the
    # sow/bake/plow frames keep emitting theirs as before.
    "PendingHarvestBreed.triggers_resolved",
})


def _is_field_default(f: "dataclasses.Field", value: Any) -> bool:
    """True if `value` equals dataclass field `f`'s default (plain default or factory)."""
    if f.default is not dataclasses.MISSING:
        return value == f.default
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
        return value == f.default_factory()
    return False


def _sorted_set(fs: frozenset) -> list:
    """Deterministically order a frozenset for serialization.

    All frozensets in the state model hold ``str`` (card ids) or
    ``tuple[int, int]`` (cells) — both natively sortable. The JSON-key fallback
    keeps the function total in case a future field holds something else.
    """
    try:
        return sorted(fs)
    except TypeError:
        return sorted(fs, key=lambda e: json.dumps(to_canonical(e), sort_keys=True))


def to_canonical(obj: Any) -> Any:
    """Convert a state object (or any of its parts) to canonical JSON-able form."""
    if obj is None:
        return None
    # Enum before int: an IntEnum is also an int, and must serialize as an enum.
    if isinstance(obj, enum.Enum):
        return {"__enum__": type(obj).__name__, "name": obj.name}
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float, str)):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {"__type__": type(obj).__name__}
        for f in dataclasses.fields(obj):
            if not f.init:
                continue
            value = getattr(obj, f.name)
            if ((f.name in _DEFAULT_SKIP_FIELDS
                 or f"{type(obj).__name__}.{f.name}" in _DEFAULT_SKIP_FIELDS)
                    and _is_field_default(f, value)):
                continue  # default card field → omit (keeps Family JSON byte-identical)
            out[f.name] = to_canonical(value)
        return out
    if isinstance(obj, frozenset):
        return {"__set__": [to_canonical(e) for e in _sorted_set(obj)]}
    if isinstance(obj, (tuple, list)):
        return [to_canonical(e) for e in obj]
    raise TypeError(f"canonical: unsupported type {type(obj)!r}: {obj!r}")


# ---------------------------------------------------------------------------
# Deserialize
# ---------------------------------------------------------------------------


def from_canonical(node: Any) -> Any:
    """Reconstruct a state object from its canonical JSON-able form."""
    if node is None or isinstance(node, (bool, int, float, str)):
        return node
    if isinstance(node, list):
        # Every bare JSON array in the format is a tuple (sets are tagged).
        return tuple(from_canonical(e) for e in node)
    if isinstance(node, dict):
        if "__enum__" in node:
            return _ENUMS[node["__enum__"]][node["name"]]
        if "__set__" in node:
            return frozenset(from_canonical(e) for e in node["__set__"])
        if "__type__" in node:
            cls = _DATACLASSES[node["__type__"]]
            kwargs = {k: from_canonical(v) for k, v in node.items() if k != "__type__"}
            return cls(**kwargs)
        raise ValueError(f"canonical: unrecognized object node {node!r}")
    raise TypeError(f"canonical: unsupported node {type(node)!r}: {node!r}")


# ---------------------------------------------------------------------------
# String helpers (the actual contract the C++ side matches)
# ---------------------------------------------------------------------------


def dumps(state: GameState) -> str:
    """Serialize a ``GameState`` to a deterministic canonical JSON string."""
    return json.dumps(to_canonical(state), separators=(",", ":"), ensure_ascii=False)


def loads(text: str) -> GameState:
    """Inverse of :func:`dumps`."""
    return from_canonical(json.loads(text))
