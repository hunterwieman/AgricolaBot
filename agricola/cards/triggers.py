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
