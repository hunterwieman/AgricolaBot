"""Card-trigger registry.

Two parallel dicts, populated at import time by each card module:

- TRIGGERS: event-keyed, used by `legal_actions` enumerators to find
  unfired eligible triggers at the current top pending's TRIGGER_EVENT.
- CARDS: card-id-keyed, used by `_apply_fire_trigger` for direct O(1)
  lookup.

Card modules call `register(event, card_id, eligibility_fn, apply_fn)`
at the bottom of their module body. Importing `agricola.cards` causes
those calls to run.

See ENGINE_IMPLEMENTATION.md §6 (card-trigger machinery & deferred design
questions) for the broader design.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class TriggerEntry:
    """Single registered trigger.

    eligibility_fn signature: (state, player_idx, triggers_resolved) -> bool
    apply_fn signature:        (state, player_idx) -> GameState
    """
    card_id: str
    event: str
    eligibility_fn: Callable
    apply_fn: Callable


# Event-keyed registry — for "what eligible cards fire on event X?" queries.
TRIGGERS: dict[str, list[TriggerEntry]] = {}

# Card-id-keyed registry — for "given a card_id, get its TriggerEntry."
CARDS: dict[str, TriggerEntry] = {}


def register(
    event: str,
    card_id: str,
    eligibility_fn: Callable,
    apply_fn: Callable,
) -> None:
    """Called at import time by each card module.

    Adds the trigger to both TRIGGERS (under the given event) and CARDS
    (under card_id). Both registries reference the same TriggerEntry.
    """
    entry = TriggerEntry(
        card_id=card_id,
        event=event,
        eligibility_fn=eligibility_fn,
        apply_fn=apply_fn,
    )
    TRIGGERS.setdefault(event, []).append(entry)
    CARDS[card_id] = entry


# ---------------------------------------------------------------------------
# Automatic effects (CARD_IMPLEMENTATION_PLAN.md II.1)
# ---------------------------------------------------------------------------
# The second of the firing kinds: MANDATORY, choice-free effects (Wood Cutter's
# +1 wood, Milk Jug's payout). Unlike optional triggers (FireTrigger above),
# automatic effects are applied DIRECTLY at the hook by `apply_auto_effects` and
# are never surfaced to the agent. A hook can host both kinds.
#
# (The third firing kind — mandatory-WITH-choice, a `mandatory`-tagged trigger
# that gates the hook's phase-exit and pushes a PendingCardChoice — lands with
# its consumers, the action-space/phase hooks, in a later build step. It will add
# a flag here; there is nothing to gate yet.)


@dataclass(frozen=True)
class AutoEntry:
    """Single registered automatic effect.

    eligibility_fn signature: (state, owner_idx) -> bool
    apply_fn signature:        (state, owner_idx) -> GameState
    any_player: False = fires for the ACTING player only; True = fires for EVERY
        owner regardless of whose turn it is (Milk Jug on the opponent's Cattle
        Market use). Owner routing lives in `apply_auto_effects`, not on frames.
    """
    card_id: str
    event: str
    eligibility_fn: Callable
    apply_fn: Callable
    any_player: bool = False


# Event-keyed registry — mirrors TRIGGERS for the automatic-effect path.
AUTO_EFFECTS: dict[str, list[AutoEntry]] = {}


def register_auto(
    event: str,
    card_id: str,
    eligibility_fn: Callable,
    apply_fn: Callable,
    *,
    any_player: bool = False,
) -> None:
    """Register an automatic effect (called at import time by each card module)."""
    AUTO_EFFECTS.setdefault(event, []).append(
        AutoEntry(card_id, event, eligibility_fn, apply_fn, any_player)
    )


def apply_auto_effects(state, event: str, acting_player: int):
    """Fire every owned, eligible automatic effect for `event`, in registration order.

    A no-op when ``AUTO_EFFECTS.get(event)`` is empty — the Family fast path (no
    card ever registers, so the dict is empty and this returns `state` unchanged).
    Own-action effects fire for `acting_player`; `any_player` effects fire for EACH
    owner (so an opponent-firing card runs for its owner even on the other player's
    turn — its eligibility_fn / apply_fn receive that owner as the index).
    """
    for e in AUTO_EFFECTS.get(event, ()):
        owners = range(len(state.players)) if e.any_player else (acting_player,)
        for owner in owners:
            if _owns(state.players[owner], e.card_id) and e.eligibility_fn(state, owner):
                state = e.apply_fn(state, owner)
    return state


def _owns(player_state, card_id: str) -> bool:
    """Has `player_state` PLAYED this card? (A hand card cannot fire.)

    A sibling of `scoring._owns`; kept local so this low-level registry module
    stays free of an import edge to scoring.
    """
    return card_id in player_state.occupations or card_id in player_state.minor_improvements


# ---------------------------------------------------------------------------
# Action-space hosting indexes (CARD_IMPLEMENTATION_PLAN.md II.2)
# ---------------------------------------------------------------------------
# An atomic action space stays atomic (no frame pushed, today's fast path) UNTIL
# a card could fire on it. `should_host_space` answers "should this placement be
# hosted by a PendingActionSpace frame?" by consulting two registration-time
# indexes, both keyed by space_id → the card ids that hook that space:
#
#   OWN_ACTION_HOOK_CARDS — fire on the ACTING player's use of the space.
#   ANY_PLAYER_HOOK_CARDS — fire on ANY player's use (so the host frame must be
#       pushed on the opponent's turn too — e.g. Milk Jug on Cattle Market). This
#       is empty for almost every space, so the all-players scan is skipped where
#       it's empty, keeping the common path off it.
#
# Family game → no card registered → both empty → should_host_space is always
# False → the atomic fast path runs → byte-identical, no host frame ever pushed.
OWN_ACTION_HOOK_CARDS: dict[str, set[str]] = {}
ANY_PLAYER_HOOK_CARDS: dict[str, set[str]] = {}


def register_action_space_hook(card_id: str, spaces, *, any_player: bool = False) -> None:
    """Index `card_id` as hooking each of `spaces` (space_id strings).

    Called at card-module import alongside the card's register/register_auto. A
    card that fires on several spaces lists them all; `any_player=True` routes it
    to ANY_PLAYER_HOOK_CARDS so the host frame is pushed on either player's turn.
    """
    index = ANY_PLAYER_HOOK_CARDS if any_player else OWN_ACTION_HOOK_CARDS
    for space_id in spaces:
        index.setdefault(space_id, set()).add(card_id)


def should_host_space(state, space_id: str, acting_player: int) -> bool:
    """Should `space_id`'s placement by `acting_player` be hosted (vs. atomic)?

    True iff the acting player owns a card that hooks this space on its OWN use,
    or any player owns a card that hooks it on ANY use. Reads PLAYED cards only
    (a hand card cannot fire). O(1) on the Family fast path (both indexes empty).
    """
    own = OWN_ACTION_HOOK_CARDS.get(space_id)
    if own:
        p = state.players[acting_player]
        if own & (p.occupations | p.minor_improvements):
            return True
    anyp = ANY_PLAYER_HOOK_CARDS.get(space_id)
    if anyp:
        return any(anyp & (p.occupations | p.minor_improvements) for p in state.players)
    return False


# ---------------------------------------------------------------------------
# Harvest-field phase-hook index (CARD_IMPLEMENTATION_PLAN.md II.6)
# ---------------------------------------------------------------------------
# The field phase of each harvest stays purely mechanical (today's fast path)
# UNTIL a card could fire on it. `should_host_harvest_field` answers "should
# _resolve_harvest_field push a PendingHarvestField host frame before the crop
# take?" by consulting this registration-time set of harvest-field card ids — the
# field-phase analog of `should_host_space`.
#
# Family game → no card registered → the set is empty → should_host_harvest_field
# is always False → the mechanical field resolution runs unhosted → byte-identical,
# no host frame ever pushed (and the C++ Family-only engine never sees it).
HARVEST_FIELD_CARDS: set[str] = set()


def register_harvest_field_hook(card_id: str) -> None:
    """Index `card_id` as firing on the harvest-field phase hook.

    Called at card-module import alongside the card's `register_auto("harvest_field", …)`.
    """
    HARVEST_FIELD_CARDS.add(card_id)


def should_host_harvest_field(state) -> bool:
    """Should the field phase be hosted by a PendingHarvestField frame (vs. run
    mechanically)? True iff EITHER player owns a harvest-field card. Reads PLAYED
    cards only. O(1) on the Family fast path (the index is empty)."""
    if not HARVEST_FIELD_CARDS:
        return False
    return any(
        HARVEST_FIELD_CARDS & (p.occupations | p.minor_improvements)
        for p in state.players
    )
