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
    # Ownership predicate override (ruling 74, 2026-07-21 — the craft majors'
    # harvest-span triggers): `(state, player_idx) -> bool`. None (every card
    # module's default) = tableau ownership via `_owns`. A non-tableau source —
    # Joinery/Pottery/Basketmaker's, owned via the board's major-owner array —
    # supplies its own predicate; BOTH surfacing gates (the trigger enumerator
    # in legality.py and engine._has_window_trigger) consult it.
    is_owned_fn: Callable | None = None


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
    is_owned_fn: Callable | None = None,
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
        is_owned_fn=is_owned_fn,
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
    order: firing priority WITHIN one event (lower first; ties keep registration
        order — the sort is stable). The default 0 leaves ordinary autos in
        registration order; a card whose effect must READ the combined result of
        its same-instant peers registers late (Museum Caretaker's six-goods check
        at `start_of_work` must see Freemason's clay/stone land first — import
        order is an accident, this is the explicit mechanism).
    """
    card_id: str
    event: str
    eligibility_fn: Callable
    apply_fn: Callable
    any_player: bool = False
    order: int = 0


# Event-keyed registry — mirrors TRIGGERS for the automatic-effect path. Each
# event's list is kept sorted by `order` (stable — equal orders keep
# registration order); registration is import-time only, so the sort is free.
AUTO_EFFECTS: dict[str, list[AutoEntry]] = {}


def register_auto(
    event: str,
    card_id: str,
    eligibility_fn: Callable,
    apply_fn: Callable,
    *,
    any_player: bool = False,
    order: int = 0,
) -> None:
    """Register an automatic effect (called at import time by each card module)."""
    entries = AUTO_EFFECTS.setdefault(event, [])
    entries.append(
        AutoEntry(card_id, event, eligibility_fn, apply_fn, any_player, order)
    )
    entries.sort(key=lambda e: e.order)


def apply_auto_effects(state, event: str, acting_player: int):
    """Fire every owned, eligible automatic effect for `event`, in `order` then
    registration order (the registry list is kept order-sorted, stably).

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


# Cards whose after-build hook needs the IDENTITY of the major just built (Brick
# Hammer's "improvement costing at least 2 clay" printed-cost check — user ruling
# 2026-07-20). When any player OWNS a member, `_execute_build_major` stamps
# `PendingBuildMajor.built_major_idx` at the commit so the after-flip's autos can
# read which major the frame built. Empty set → the Family game never stamps and
# the field stays at its canonical-skipped default (the should_host_space
# pattern: an ownership-gated control-flow index, O(1) on the Family fast path).
BUILD_MAJOR_IDENTITY_CARDS: set[str] = set()


def register_build_major_identity(card_id: str) -> None:
    """Index `card_id` as needing `PendingBuildMajor.built_major_idx` stamped."""
    BUILD_MAJOR_IDENTITY_CARDS.add(card_id)


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
# Start-of-round hosting — RETIRED (the preparation ladder, ruling 54, 2026-07-14)
# ---------------------------------------------------------------------------
# The pre-ladder engine hosted the whole preparation phase behind an ownership
# index (`START_OF_ROUND_CARDS` / `register_start_of_round_hook` /
# `owns_start_of_round_card` / `should_host_preparation`) and pushed one
# PendingPreparation frame per owning player. The preparation ladder
# (`agricola/cards/preparation.py`; walk: `engine._advance_preparation`) replaced
# all of it with the harvest/round-end model: each window's autos fire
# mechanically, and a per-player choice frame is pushed only for a player with an
# ELIGIBLE trigger on that window (`_window_trigger_players`) — eligibility-driven
# hosting, no ownership index. A schedule-driven grant (Handplow) hosts on its due
# round because its own eligibility fn reads its `future_rewards` slot.


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


# A one-shot fired at every AGENT-DECISION BOUNDARY (rather than only at the renovate /
# card-play seams `CONDITIONAL_ONE_SHOTS` uses). This is the home for a one-shot keyed to a
# condition that can become true at points those two seams miss — most importantly a
# RESOURCE / ANIMAL COUNT (Hook Knife's "when you have 8 sheep on your farm, get 2 bonus
# points"): sheep counts change at the animal market, at breeding, and via cards, none of
# which the renovate/card-play sweep covers. `engine._fire_boundary_one_shots` runs these
# right AFTER the accommodation barrier settles at each boundary, so an animal-count
# condition sees the ACCOMMODATED animals (never a transient over-capacity grant). Each
# fires once per game (`fired_once`). Empty registry -> Family no-op / byte-identical.
BOUNDARY_ONE_SHOTS: dict[str, tuple[Callable, Callable]] = {}


def register_boundary_one_shot(card_id: str, condition_fn: Callable,
                               apply_fn: Callable) -> None:
    """Register `card_id` as a decision-boundary one-shot (§3/§6). Fires once, via
    `engine._fire_boundary_one_shots`, the first boundary at which
    `condition_fn(state, owner_idx)` is true for the OWNER — checked after the
    accommodation barrier settles, so an animal-count condition reads housed animals."""
    BOUNDARY_ONE_SHOTS[card_id] = (condition_fn, apply_fn)


# A card that offers a DECISION just before end-game scoring — the minimal
# `PendingBeforeScoring` window (Ox Skull's "discard your one cattle to reach 0 for +3").
# `engine._push_before_scoring_choice` runs at the BEFORE_SCORING boundary: for each owning
# player (once — latched in `fired_once` at push) whose `options_fn(state, idx)` returns a
# non-empty option tuple, it pushes a `PendingCardChoice(initiated_by_id="card:<id>",
# options=...)`, reusing the existing choice frame + resolver machinery
# (`register_card_choice_resolver`). The choice is surfaced only where a card makes an
# end-game animal-discard relevant, keeping the action set small (the optionality-preservation
# principle). Empty registry -> Family no-op / byte-identical.
BEFORE_SCORING_CARDS: dict[str, Callable] = {}


def register_before_scoring(card_id: str, options_fn: Callable) -> None:
    """Register `card_id`'s before-scoring decision. `options_fn(state, owner_idx) -> tuple`
    returns the choice options (empty = no decision now); pair with a
    `register_card_choice_resolver` that applies the pick and pops the frame."""
    BEFORE_SCORING_CARDS[card_id] = options_fn


# A card that REACTS to an animal being cooked (converted to food via a cooking improvement —
# a Fireplace/Cooking Hearth). `resolution.note_animal_cook` fires each owned card's reaction
# at the two work-phase cook sites (`_execute_food_payment`, `_execute_accommodate`) right
# after the animal→food conversion — so "used a cooking improvement" is detected as the ACTUAL
# cook, not an animal-count change (an animal spent as a card COST, or discarded, never fires
# it). Cookery Lesson uses this to award its point for cooking on a Lessons turn, wherever the
# cook happens (paying the occupation cost, an on-play-grant overflow, or its own explicit
# cook). `react_fn(state, owner_idx) -> state`. Empty registry / no owner -> Family no-op.
ANIMAL_COOK_REACTIONS: dict[str, Callable] = {}


def register_animal_cook_reaction(card_id: str, react_fn: Callable) -> None:
    """Register `card_id`'s reaction to an animal being cooked (import time)."""
    ANIMAL_COOK_REACTIONS[card_id] = react_fn


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


# ---------------------------------------------------------------------------
# Improvement-decline income (user ruling 74, 2026-07-21 — Field Merchant B103)
# ---------------------------------------------------------------------------
# A card paying its owner when the owner DECLINES one of the two named
# improvement actions (Field Merchant: "Each time you decline a 'Minor/Major
# Improvement' action, you get 1 food/vegetable instead" — the slash correlates:
# declining a "Minor Improvement" action pays the "minor" kind, declining a
# "Major or Minor Improvement" action pays the "major_or_minor" kind).
#
# The DETECTION lives at the engine's decline seams, not here: each seam is a
# moment the engine already knows a named improvement action was
# offered-and-not-taken (the Meeting Place / Basic Wish Proceed with the minor
# branch unchosen; House Redevelopment's Proceed with the composite step not
# entered; a named-minor `PendingGrantedSubAction` popped via Stop untaken; the
# composite host's ownership-gated decline route). Each seam calls
# `note_improvement_action_declined(state, decliner_idx, kind)` exactly once per
# decline event. Per the ruling, exiting an improvement action you COULD NOT USE
# also counts as declining (Meeting Place with no playable minor still pays).
#
# "You decline" — only the DECLINING player's own registered cards pay, which is
# also what keeps the Family game inert: the registry is populated at import in
# every mode, but Family players never own cards, so `note_...` returns the same
# state object untouched (and the card-only frames most seams key on never exist
# there).
#
# payout_fn signature: (state, owner_idx, kind) -> GameState,
#   kind in {"minor", "major_or_minor"}.
IMPROVEMENT_DECLINE_INCOME: dict[str, Callable] = {}


def register_improvement_decline_income(card_id: str, payout_fn: Callable) -> None:
    """Register `card_id` as paying its owner on an improvement-action decline
    (called at card-module import). `payout_fn(state, owner_idx, kind)` with
    `kind` in {"minor", "major_or_minor"}."""
    IMPROVEMENT_DECLINE_INCOME[card_id] = payout_fn


def owns_improvement_decline_income(state, idx: int) -> bool:
    """Does player `idx` OWN (have played) a registered decline-income card?

    The gate for the decline affordances that exist only because the income
    does: the Major Improvement space's place-just-to-decline placement and the
    composite host's decline route (Field Merchant's printed clarification:
    "You can place onto the 'Major Improvement' ... action space just to
    decline it"). Empty registry / hand-only copies -> False (a hand card
    cannot fire)."""
    if not IMPROVEMENT_DECLINE_INCOME:
        return False
    p = state.players[idx]
    return any(_owns(p, cid) for cid in IMPROVEMENT_DECLINE_INCOME)


# --- Named-action GRANTS and the unfired-trigger decline (user ruling 76,
# 2026-07-21, CARD_DEFERRED_PLANS.md item 2) -----------------------------------
#
# Ruling (quoted): "Unfired granting triggers ARE declines (user: 'yes it
# does'): declining-to-fire a trigger that would grant a named improvement
# action counts as declining the action for decline income — including when the
# trigger was withheld as unaffordable (the can't-use-counts-as-declining ruling
# extends to grants). Requires the grant-condition-held-but-unfired seam at host
# exits; fired-then-declined stays on the existing frame seams (no double pay)."
#
# Each card whose TRIGGER grants a named improvement action registers its grant
# CONDITION here — the part of its eligibility that says "this card's grant is
# live at this host", independent of whether the granted action is currently
# doable/affordable (Angler: the space is Fishing and its pre-take food was
# <= 2; NOT "a composite child is affordable"). At the host's terminal exit
# (`engine._sweep_unfired_named_action_grants` — the Stop pop for frame-hosted
# grants, the window frame's Proceed for window-hosted ones), every owned entry
# whose condition held and whose trigger was NOT fired (the host's
# `triggers_resolved`) pays the owner's decline income once. A FIRED grant is
# skipped here — its pushed frame's own decline seams govern it (the composite
# decline route, the wrapper Stop), so nothing pays twice.
#
# `window` names the ladder window id for a window-hosted grant (Sample Stable
# Maker / Task Artisan's reveal half / Tree Farm Joiner): those windows host a
# choice frame only for players with an ELIGIBLE trigger, so a withheld
# (unaffordable) grant would never see a host exit — `engine.
# _window_trigger_players` therefore also hosts the frame for a player whose
# registered grant CONDITION holds when they own a decline-income card (gated
# exactly so: without decline income the extra frame would have no observable
# effect, and hosting is unchanged). None = a frame-hosted grant (the host frame
# exists independently of the trigger's eligibility).
#
# Deliberate exclusions: **Stone Company** (ruling 76) — its granted composite
# is NOT declinable ("Improvement action is not declinable in order to use
# Field Merchant B103"), so it registers nothing; **Harvest Festival Planning**
# (ruling 76) — its composite is pushed by its own on-play resolution, not by a
# trigger, so there is no declining-to-fire moment for this seam to read (its
# pushed composite, when declinable, is governed by the frame's own decline
# route); **Merchant** (ruling 77 item 3, 2026-07-21 — the user, verbatim:
# "Merchant requires the player to pay 1 food and then take the relevant
# action. I don't think declining this bundle counts as declining the action")
# — its pay-and-repeat bundle is not a bare grant of the named action, so
# leaving it unfired pays nothing.
#
# condition_fn signature: (state, owner_idx, host_frame) -> bool.
@dataclass(frozen=True)
class NamedActionGrantEntry:
    card_id: str
    kind: str                    # "minor" | "major_or_minor"
    condition_fn: Callable       # (state, owner_idx, host_frame) -> bool
    window: str | None = None    # ladder window id for window-hosted grants


# A list, not a dict: one card may grant BOTH kinds (Merchant's two repeats).
NAMED_ACTION_GRANTS: list[NamedActionGrantEntry] = []


def register_named_action_grant(card_id: str, kind: str, condition_fn: Callable,
                                *, window: str | None = None) -> None:
    """Register a trigger-granted named improvement action's grant CONDITION
    (user ruling 76, 2026-07-21 — called at card-module import). `kind` in
    {"minor", "major_or_minor"}; `condition_fn(state, owner_idx, host_frame)`
    tests the grant's own condition at the host, independent of the granted
    action's doability; `window` = the ladder window id when the granting
    trigger is window-hosted."""
    assert kind in ("minor", "major_or_minor"), kind
    NAMED_ACTION_GRANTS.append(
        NamedActionGrantEntry(card_id, kind, condition_fn, window))


def note_improvement_action_declined(state, idx: int, kind: str):
    """Player `idx` just DECLINED a named improvement action of `kind`
    ("minor" = the "Minor Improvement" action; "major_or_minor" = the "Major or
    Minor Improvement" action). Pay each registered decline-income card the
    declining player owns — their own cards only ("you decline"). Called once
    per decline event, so each decline pays each owned card exactly once
    (Field Merchant's printed clarification "Merchant C096 does not double a
    decline" is satisfied structurally: a Merchant-repeated action declined is
    ONE decline event and pays once). Empty registry / no owned card -> the
    same state object, unchanged."""
    assert kind in ("minor", "major_or_minor"), kind
    if not IMPROVEMENT_DECLINE_INCOME:
        return state
    p = state.players[idx]
    for cid in sorted(IMPROVEMENT_DECLINE_INCOME):
        if _owns(p, cid):
            state = IMPROVEMENT_DECLINE_INCOME[cid](state, idx, kind)
    return state


def grant_named_minor_or_pay_decline(state, idx: int, initiated_by_id: str):
    """A card's PUSH SITE for an OPTIONAL granted NAMED "Minor Improvement"
    action (`minor_is_action=True`): push the standard choose-or-decline
    wrapper when the owner has a playable hand minor, ELSE pay the "minor"-kind
    decline income for the unusable named action (user ruling 78 item 3,
    2026-07-21 — "I lean towards granting Field Merchant income even when the
    player has no minors in hand": the ruling-74 "could not use counts as
    declining" rule, already live at Meeting Place / Basic Wish, extends to a
    GRANTED named minor the owner cannot use).

    - **Playable minor exists** → push `PendingGrantedSubAction(subactions=
      ("play_minor",), minor_is_action=True)` carrying `initiated_by_id`. The
      wrapper's own Stop is then the decline seam (`engine._apply_stop` pays the
      "minor" income when the wrapper is Stopped untaken), so this path must NOT
      pay too — no double.
    - **No playable minor** → the wrapper would offer only Stop (a dead grant),
      so it is not pushed; instead pay the decline income directly. Registry-
      gated / owner-only via `note_improvement_action_declined` — a no-op for a
      non-owner and for the Family game (no card push happens either way).

    Callers: Sample Stable Maker's fire, Task Artisan's on-play grant. (Task
    Artisan's REVEAL grant's unusable case is already covered by the ruling-76
    unfired-trigger WINDOW seam — its trigger is withheld when no minor is
    playable, and the window frame pays via
    `engine._sweep_unfired_named_action_grants`; that path never reaches a push
    site, so it does not use this helper.)"""
    from agricola.legality import playable_minors
    from agricola.pending import PendingGrantedSubAction, push
    if playable_minors(state, idx):
        return push(state, PendingGrantedSubAction(
            player_idx=idx, initiated_by_id=initiated_by_id,
            subactions=("play_minor",), minor_is_action=True))
    return note_improvement_action_declined(state, idx, "minor")
