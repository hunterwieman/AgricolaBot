"""Merchant (occupation, C96; Corbarius Expansion; players 1+).

Card text: "Immediately after each time you take a 'Major or Minor Improvement'
or 'Minor Improvement' action, you can pay 1 food to take the action a second
time."

Clarification: "Does not combo with Field Merchant B103." (Field Merchant is not
implemented; nothing to encode — its own clarification already says Merchant
does not double a decline.)

User rulings (2026-07-14, refined 2026-07-15 — the "action, not action space"
distinction; RULES.md Primitive Sub-Actions ⚠️ callout, CARD_ENGINE_IMPLEMENTATION.md §6):
  1. Merchant fires on the ACTION, not the action space. It has TWO clauses,
     one per named action, and each offers a TYPE-MATCHED repeat:
       - the **"Major or Minor Improvement" action** (the composite —
         `PendingMajorMinorImprovement`: the Major Improvement space, House
         Redevelopment, and card grants like Angler) → offer a second "Major or
         Minor Improvement" action;
       - the **"Minor Improvement" action** (a *bare* `PendingPlayMinor`:
         Meeting Place, Basic Wish for Children, and card grants like
         Beneficiary / Task Artisan / Sample Stable Maker) → offer a second
         "Minor Improvement" action.
     (2026-07-15: the "Minor Improvement" action IS reachable at 2 players — an
     earlier note wrongly called it 6p-only; and card grants of either action
     chain Merchant, by symmetry with Angler firing it on the composite side.)
  2. "Immediately after" falls in the SAME trigger seam as ordinary after-window
     triggers (on the ACTION's host, not the action space).
  3. "A second time" — Merchant may NOT chain off its OWN granted action
     (`initiated_by_id == "card:merchant"` is excluded in both clauses).

Category 4 (granted action). "You can pay 1 food" is the player's choice → an
OPTIONAL trigger (`register`, not `register_auto`), registered on BOTH events:

  - **`after_major_minor_improvement`** — the composite host's own after-event
    (excluded from the coarse `action_space` bucket; see `trigger_event`).
    Firing pushes a fresh `PendingMajorMinorImprovement` (a second composite
    action). The composite is itself a host but is NOT a sub-action leaf, so its
    `before_major_minor_improvement` autos are fired MANUALLY at the push
    (`_fire_subaction_before_auto` skips composite hosts).
  - **`after_play_minor`** — fires only for a BARE "Minor Improvement" action,
    NOT the composite's child minor (which also fires `after_play_minor`): the
    guard excludes `initiated_by_id == "major_minor_improvement"` (a composite
    child — handled by the composite clause above) and `"card:merchant"` (no
    self-chain). Firing pushes a fresh bare `PendingPlayMinor` (a second "Minor
    Improvement" action); `play_minor` IS a sub-action leaf, so the engine's
    `_fire_subaction_before_auto` seam fires its before-autos automatically — no
    manual fire (mirrors Task Artisan's push).

Eligibility (never grant a dead end), for each clause after the 1-food payment:
  - the player holds >= 1 food; the host is not a Merchant self-chain; AND
  - the second action would have a legal child — the composite needs an
    affordable unowned major OR a playable hand minor; the bare "Minor
    Improvement" action needs a playable hand minor. The post-payment check
    matters: with exactly 1 food and a sole playable 1-food minor, paying the
    fee would strand a dead host.

Once per action-take via the firing host's `triggers_resolved`. Played via
Lessons; on-play is a no-op.

MACHINERY NOTE — a card on two trigger events shares ONE frame-dispatched
`apply_fn`. `FireTrigger` dispatch is id-keyed (`_apply_fire_trigger` reads
`CARDS[card_id]`, one entry per card), so two `register` calls for the same card
would make the SECOND clobber the first's apply. Per-event ELIGIBILITY is safe
(the enumerator reads the event-keyed `TRIGGERS`), so each clause keeps its own
eligibility; the single shared `_apply` dispatches on the top frame type
(composite vs bare minor).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import apply_auto_effects, register
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, PendingPlayMinor, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "merchant"

# A bare PendingPlayMinor with one of these provenances is NOT a "Minor
# Improvement" action Merchant chains: the composite's own child minor (handled
# by the composite clause) and Merchant's own grant (ruling 3, no self-chain).
_NOT_A_BARE_MINOR_ACTION = frozenset({"major_minor_improvement", "card:merchant"})


def _sub_one_food(state: GameState, idx: int) -> GameState:
    """`state` with 1 food debited from player `idx`."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- Clause 1: the "Major or Minor Improvement" action (the composite) --------

def _eligible_composite(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    if getattr(top, "initiated_by_id", "") == "card:merchant":   # ruling 3
        return False
    if state.players[idx].resources.food < 1:
        return False
    paid = _sub_one_food(state, idx)   # a legal child must remain after paying
    return (_can_afford_any_major_improvement(paid, paid.players[idx])
            or bool(playable_minors(paid, idx)))


def _apply_composite(state: GameState, idx: int) -> GameState:
    state = _sub_one_food(state, idx)
    state = push(state, PendingMajorMinorImprovement(
        player_idx=idx, initiated_by_id="card:merchant"))
    # A composite host is not a sub-action leaf — fire its before-autos manually.
    return apply_auto_effects(state, "before_major_minor_improvement", idx)


# --- Clause 2: the "Minor Improvement" action (a bare minor play) -------------

def _eligible_bare_minor(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    if getattr(top, "initiated_by_id", "") in _NOT_A_BARE_MINOR_ACTION:
        return False
    if state.players[idx].resources.food < 1:
        return False
    paid = _sub_one_food(state, idx)   # a second minor must remain playable
    return bool(playable_minors(paid, idx))


def _apply_bare_minor(state: GameState, idx: int) -> GameState:
    state = _sub_one_food(state, idx)
    # A bare "Minor Improvement" action. `play_minor` is a sub-action leaf, so
    # the engine's _fire_subaction_before_auto seam fires its before-autos — no
    # manual fire (mirrors Task Artisan / other PendingPlayMinor grants).
    return push(state, PendingPlayMinor(
        player_idx=idx, initiated_by_id="card:merchant"))


# --- The single, frame-dispatched apply (see the MACHINERY NOTE) --------------

def _apply(state: GameState, idx: int) -> GameState:
    """Dispatch on the firing host: the composite pushes a second composite, a
    bare minor pushes a second bare minor (the type-matched repeat)."""
    if isinstance(state.pending_stack[-1], PendingMajorMinorImprovement):
        return _apply_composite(state, idx)
    return _apply_bare_minor(state, idx)


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register("after_major_minor_improvement", CARD_ID, _eligible_composite, _apply)
register("after_play_minor", CARD_ID, _eligible_bare_minor, _apply)
