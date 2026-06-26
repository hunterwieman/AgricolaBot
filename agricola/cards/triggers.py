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
        (or (state, player_idx, variant) for a play-variant trigger such as
        Scholar — see _apply_fire_trigger's variant threading).
    mandatory: the third firing kind (CARD_IMPLEMENTATION_PLAN.md II.1). A
        mandatory trigger is still surfaced as a FireTrigger, but its host frame's
        phase-exit (Proceed/Stop) is GATED OFF while it is eligible and unfired —
        the player cannot decline, only choose how to resolve it (its apply_fn
        pushes a PendingCardChoice). Seasonal Worker (r6+) and Childless use it.
        Default False (the ordinary optional trigger).
    """
    card_id: str
    event: str
    eligibility_fn: Callable
    apply_fn: Callable
    mandatory: bool = False


# Event-keyed registry — for "what eligible cards fire on event X?" queries.
TRIGGERS: dict[str, list[TriggerEntry]] = {}

# Card-id-keyed registry — for "given a card_id, get its TriggerEntry."
CARDS: dict[str, TriggerEntry] = {}


def register(
    event: str,
    card_id: str,
    eligibility_fn: Callable,
    apply_fn: Callable,
    *,
    mandatory: bool = False,
) -> None:
    """Called at import time by each card module.

    Adds the trigger to both TRIGGERS (under the given event) and CARDS
    (under card_id). Both registries reference the same TriggerEntry.

    `mandatory=True` registers the third firing kind (II.1): a trigger that gates
    its host frame's phase-exit until it fires (Seasonal Worker, Childless).
    """
    entry = TriggerEntry(
        card_id=card_id,
        event=event,
        eligibility_fn=eligibility_fn,
        apply_fn=apply_fn,
        mandatory=mandatory,
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


# ---------------------------------------------------------------------------
# Start-of-round phase-hook index (CARD_IMPLEMENTATION_PLAN.md II.6)
# ---------------------------------------------------------------------------
# The start-of-round (preparation) phase stays purely mechanical (today's fast
# path — increment round, refill, distribute future_resources, → WORK) UNTIL a
# card could fire on it. `should_host_preparation` answers "should
# _complete_preparation push a PendingPreparation host frame before the → WORK
# transition?" by consulting this registration-time set of start-of-round card ids
# — the preparation-phase analog of `should_host_space` / `should_host_harvest_field`.
#
# Family game → no card registered → the set is empty → should_host_preparation is
# always False → preparation runs unhosted → byte-identical, no host frame ever
# pushed (and the C++ Family-only engine never sees it). Per-player ownership is
# what is indexed; the engine pushes a PendingPreparation per OWNING player.
START_OF_ROUND_CARDS: set[str] = set()


def register_start_of_round_hook(card_id: str) -> None:
    """Index `card_id` as firing on the start-of-round phase hook.

    Called at card-module import alongside the card's `register("start_of_round", …)`
    or `register_auto("start_of_round", …)`.
    """
    START_OF_ROUND_CARDS.add(card_id)


def owns_start_of_round_card(player_state) -> bool:
    """Does this player own any start-of-round card? O(1) on the Family fast path
    (the index is empty)."""
    if not START_OF_ROUND_CARDS:
        return False
    return bool(
        START_OF_ROUND_CARDS & (player_state.occupations | player_state.minor_improvements)
    )


def has_scheduled_round_start_effect(player_state, round_number: int) -> bool:
    """Does this player have a scheduled round-start effect grant for `round_number`?

    A `FutureReward` slot can carry effect-card ids (Handplow's deferred plow) that
    name a card with a scheduled start-of-round effect for that round. Such a grant
    is surfaced as an ordinary `start_of_round` trigger/auto whose eligibility checks
    this schedule (CARD_IMPLEMENTATION_PLAN.md II.5) — so a deferred grant drives
    preparation hosting on its own, independently of owning a start-of-round card
    (the card may have been played rounds earlier, or be a minor that wouldn't
    otherwise host every round). False for the Family game (future_rewards is all
    the default `FutureReward()`)."""
    slot = round_number - 1
    fr = player_state.future_rewards
    return 0 <= slot < len(fr) and bool(fr[slot].effect_card_ids)


def should_host_preparation(state) -> bool:
    """Should the preparation phase push PendingPreparation host frames (vs. run
    straight to WORK)? True iff SOME player either owns a start-of-round card OR has
    a deferred round-start effect scheduled for the round being entered. Reads PLAYED
    cards + the per-player schedule only. A no-op in the Family game (no owned
    start-of-round cards, every future_rewards slot default) → preparation stays
    byte-identical."""
    rn = state.round_number
    return any(
        owns_start_of_round_card(p) or has_scheduled_round_start_effect(p, rn)
        for p in state.players
    )


# ---------------------------------------------------------------------------
# One-shot conditional latch (CARD_IMPLEMENTATION_PLAN.md II.3 / §6)
# ---------------------------------------------------------------------------
# Some cards fire ONCE, the first moment a standing condition becomes true —
# "Once you live in a stone house, …" (Manservant), "Once you no longer live in a
# wooden house, …" (Clay Hut Builder). These are level-triggered, not edge-
# triggered on a specific action: the condition can become true via a renovate, or
# already be true the instant the card is played (you renovated to stone, THEN
# played Manservant). So they are checked by a small sweep, `_fire_ready_one_shots`
# (engine.py), run at exactly the two points the condition can change for the
# OWNER: right after a renovate applies, and right after a card is played. Each
# fires at most once per game, recorded in the per-game `fired_once` latch (never
# cleared). Family game → no conditional registered → the sweep is a no-op.
#
# condition_fn (state, owner_idx) -> bool: is the standing condition met now?
# apply_fn     (state, owner_idx) -> GameState: the one-time effect.
CONDITIONAL_ONE_SHOTS: dict[str, tuple[Callable, Callable]] = {}


def register_conditional(card_id: str, condition_fn: Callable, apply_fn: Callable) -> None:
    """Register `card_id` as a one-shot conditional (II.3 / §6).

    Called at card-module import. Fires once, via `_fire_ready_one_shots`, the first
    time `condition_fn(state, owner_idx)` is true for the OWNER.
    """
    CONDITIONAL_ONE_SHOTS[card_id] = (condition_fn, apply_fn)


# ---------------------------------------------------------------------------
# Mandatory-with-choice gate (CARD_IMPLEMENTATION_PLAN.md II.1)
# ---------------------------------------------------------------------------
# A host frame's phase-exit (Proceed/Stop) is withheld while an eligible, unfired
# `mandatory`-tagged trigger exists for the frame's current event. The player must
# fire it (its apply_fn pushes a PendingCardChoice) before exiting the host.
#
# Family game → no mandatory trigger registered → TRIGGERS is empty for any event
# → this is always False → no gate → byte-identical.

def has_unfired_mandatory_trigger(state, pending, event: str) -> bool:
    """True iff some owned, eligible, unfired `mandatory` trigger is registered on
    `event` for `pending`'s player. The signal an enumerator uses to withhold the
    frame's phase-exit (Proceed/Stop). Mirrors `_eligible_fire_triggers`' filters."""
    p = state.players[pending.player_idx]
    for entry in TRIGGERS.get(event, ()):
        if not entry.mandatory:
            continue
        if not _owns(p, entry.card_id):
            continue
        if entry.card_id in pending.triggers_resolved:
            continue
        if not entry.eligibility_fn(state, pending.player_idx, pending.triggers_resolved):
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# PendingCardChoice resolvers (CARD_IMPLEMENTATION_PLAN.md II.6)
# ---------------------------------------------------------------------------
# A mandatory-with-choice trigger's apply_fn pushes a PendingCardChoice(options).
# When the agent picks CommitCardChoice(index), the engine looks up the pushing
# card's resolver here (keyed on the card id parsed off the frame's
# initiated_by_id "card:<id>") and calls it with the chosen option.
#
# resolver signature: (state, player_idx, chosen_option) -> GameState  (must pop
# the PendingCardChoice frame itself, mirroring how trigger apply_fns own their
# stack).
CARD_CHOICE_RESOLVERS: dict[str, Callable] = {}


def register_card_choice_resolver(card_id: str, resolver: Callable) -> None:
    """Register the resolver a card uses to apply a chosen PendingCardChoice option
    (called at card-module import)."""
    CARD_CHOICE_RESOLVERS[card_id] = resolver


# ---------------------------------------------------------------------------
# Play-variant triggers (CARD_IMPLEMENTATION_PLAN.md Category 7 — Scholar)
# ---------------------------------------------------------------------------
# A few "you can do A OR B" cards (Scholar: play an occupation OR a minor) collapse
# the route choice INTO the fire: the enumerator surfaces a distinct
# FireTrigger(card_id, variant=...) per currently-legal route, and the trigger's
# apply_fn takes the variant. This registry maps such a card_id to a function that
# returns its currently-legal variant strings, so the host enumerator can expand the
# card's one trigger into per-variant FireTriggers.
#
# variants_fn signature: (state, player_idx) -> list[str]  (empty = none legal now).
PLAY_VARIANT_TRIGGERS: dict[str, Callable] = {}


def register_play_variant_trigger(card_id: str, variants_fn: Callable) -> None:
    """Register a card's legal-variant enumerator (called at card-module import)."""
    PLAY_VARIANT_TRIGGERS[card_id] = variants_fn
