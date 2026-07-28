"""Merchant (occupation, C96; Corbarius Expansion; players 1+).

Card text: "Immediately after each time you take a 'Major or Minor Improvement'
or 'Minor Improvement' action, you can pay 1 food to take the action a second
time."

Clarification: "Does not combo with Field Merchant B103." Encoded (now that
Field Merchant exists) per Field Merchant's own clarification "Merchant C096
does not double a decline" and USER RULING 77 item 3 (2026-07-21,
CARD_DEFERRED_PLANS.md — verbatim): "Merchant requires the player to pay 1
food and then take the relevant action. I don't think declining this bundle
counts as declining the action." So Merchant registers NOTHING on the
named-action-grant decline-income seam: leaving its pay-1-food-and-repeat
bundle unfired (declined-to-fire or unaffordable) pays no decline income —
the bundle is not a bare grant of the named action. And a decline is never
doubled: Merchant's repeat is only offered off a TAKEN action (a declined
composite pops without opening its after-window, so no repeat trigger ever
surfaces there), and each decline event pays decline income exactly once at
its own seam. (An interim build had registered Merchant's repeat as a
declinable grant on a consequence the driver flagged during ruling 76; the
user had not accepted it and ruling 77 ruled the opposite — corrected.)

User rulings (2026-07-14, refined 2026-07-15 — the "action, not action space"
distinction; RULES.md Primitive Sub-Actions ⚠️ callout, CARD_ENGINE_IMPLEMENTATION.md §6):
  1. Merchant fires on the ACTION, not the action space. It has TWO clauses,
     one per named action, and each offers a TYPE-MATCHED repeat:
       - the **"Major or Minor Improvement" action** (the composite —
         `PendingMajorMinorImprovement`: the Major Improvement space, House
         Redevelopment, and card grants like Angler) → offer a second "Major or
         Minor Improvement" action;
       - the **"Minor Improvement" action** (a *bare* `PendingPlayMinor` whose
         `minor_improvement_action` flag is set: Meeting Place, Basic Wish for
         Children, and card grants of the action — Task Artisan, Tree Farm Joiner,
         Sample Stable Maker) → offer a second "Minor Improvement" action.
     (2026-07-15: the "Minor Improvement" action IS reachable at 2 players — an
     earlier note wrongly called it 6p-only; and card grants of either action
     chain Merchant, by symmetry with Angler firing it on the composite side.)
  1b. A card that merely lets you "play a minor improvement" as its own effect
     (Scholar, Beneficiary, Equipper) is NOT the named "Minor Improvement" action
     and does NOT chain Merchant — user ruling 2026-07-15. The distinction is
     carried structurally by `PendingPlayMinor.minor_improvement_action` (set at
     the push site by the code that knows which kind it is), NOT by matching the
     frame's provenance against a blocklist — a blocklist silently leaks every
     future "play a minor" card.
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
    identified by the frame's `minor_improvement_action` flag. That flag is False
    for the composite's own child minor (handled by the composite clause above)
    and for "play a minor" effects (Scholar / Beneficiary), so both are skipped
    with no provenance blocklist. The one remaining guard is the self-chain
    exclusion `initiated_by_id == "card:merchant"` (ruling 3): Merchant's own
    repeat IS a "Minor Improvement" action (flag True), so the flag alone would
    re-fire it. Firing pushes a fresh bare `PendingPlayMinor` (a second "Minor
    Improvement" action, flag set); `play_minor` IS a sub-action leaf, so the
    engine's `_fire_subaction_before_auto` seam fires its before-autos
    automatically — no manual fire (mirrors Task Artisan's push).

Eligibility (never grant a dead end), for each clause after the 1-food payment:
  - the 1-food fee is payable by ANY legal route — on hand OR raised by the
    at-any-time conversions (ruling 82, corrected 2026-07-27: "An
    implementation must never make a rules-legal move unplayable. The
    canonical violation: a 'pay N food' cost gated on food-on-hand — in
    Agricola the at-any-time conversions are legal payment routes, so the
    plain gate deletes options"); the host is not a Merchant self-chain; AND
  - the second action would have a legal child — the composite needs an
    affordable unowned major OR a playable hand minor; the bare "Minor
    Improvement" action needs a playable hand minor. The post-payment check
    matters: with exactly 1 food and a sole playable 1-food minor, paying the
    fee would strand a dead host.

THE PAYMENT SHAPE (ruling 82 + the preserve seam). With the food on hand the
fire debits and pushes directly, and the child probe runs on the exact
post-debit state (`_sub_one_food`). When short, the fire pushes a raise-only
`PendingFoodPayment` (resume kinds `merchant:composite` / `merchant:bare_minor`,
each resume = debit 1 food + the grant push) — and because the raise consumes
goods the second action might itself need (cooking the last grain that was the
sole minor's cost), both the gate and the frame go through the FOOD-PAYMENT
PRESERVE seam (the registry docstring names this very case): eligibility probes
`raisable_food_preserving` (some bundle's post-state, fee debited, still has a
legal child) and the frame's enumerator offers exactly the preserving bundles
(`register_food_payment_preserve`) — the full_peasant destination-probe shape.
So a rules-legal repeat is never gated off, and a fire can never strand a
childless host.

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

from agricola.cards.specs import (
    register_food_payment_preserve,
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import apply_auto_effects, register
from agricola.legality import (
    _can_afford_any_major_improvement,
    playable_minors,
    raisable_food_preserving,
)
from agricola.pending import (
    PendingFoodPayment,
    PendingMajorMinorImprovement,
    PendingPlayMinor,
    push,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "merchant"

def _sub_one_food(state: GameState, idx: int) -> GameState:
    """`state` with 1 food debited from player `idx`."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fee_ok_with_child(state: GameState, idx: int, child_remains) -> bool:
    """The 1-food fee is payable by SOME legal route whose post-payment world
    still has a legal child for the repeat (ruling 82 + the preserve seam).

    - Food on hand: the fee debits from supply, goods untouched — probe the
      child on the exact post-debit state (`_sub_one_food`), as always.
    - Food short: the fee must be RAISED, and the raise consumes goods the
      child might itself need — so probe `raisable_food_preserving`: does SOME
      liquidation bundle's post-state (fee then debited — post-bundle food is
      >= 1 by construction, the bundle covers the fee) keep a child legal?
      The frame's registered preserve check (below) filters to exactly those
      bundles, so the gate and the frame agree by construction (the
      full_peasant destination-probe shape)."""
    if state.players[idx].resources.food >= 1:
        return child_remains(_sub_one_food(state, idx), idx)
    return raisable_food_preserving(
        state, idx, 1, Cost(),
        lambda post, i: child_remains(_sub_one_food(post, i), i))


# --- Clause 1: the "Major or Minor Improvement" action (the composite) --------

def _child_remains_composite(paid: GameState, idx: int) -> bool:
    """A legal child remains for a second composite on the post-payment state:
    an affordable unowned major OR a playable hand minor (both gates are
    themselves liquidation-aware over the remaining goods)."""
    return (_can_afford_any_major_improvement(paid, paid.players[idx])
            or bool(playable_minors(paid, idx)))


def _eligible_composite(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    if getattr(top, "initiated_by_id", "") == "card:merchant":   # ruling 3
        return False
    return _fee_ok_with_child(state, idx, _child_remains_composite)


def _grant_composite(state: GameState, idx: int) -> GameState:
    """Debit the 1 food and push the second composite. Reached directly (food
    on hand) and as the `merchant:composite` post-food-payment resume (the
    raise-only frame leaves the raised food in supply for this to debit)."""
    state = _sub_one_food(state, idx)
    state = push(state, PendingMajorMinorImprovement(
        player_idx=idx, initiated_by_id="card:merchant"))
    # A composite host is not a sub-action leaf — fire its before-autos manually.
    return apply_auto_effects(state, "before_major_minor_improvement", idx)


# --- Clause 2: the "Minor Improvement" action (a bare minor play) -------------

def _child_remains_bare(paid: GameState, idx: int) -> bool:
    """A second minor remains playable on the post-payment state."""
    return bool(playable_minors(paid, idx))


def _eligible_bare_minor(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    if not getattr(top, "minor_improvement_action", False):
        return False   # not the named action (Scholar/Beneficiary/composite child)
    if getattr(top, "initiated_by_id", "") == "card:merchant":
        return False   # ruling 3: no self-chain (the repeat's flag is True too)
    return _fee_ok_with_child(state, idx, _child_remains_bare)


def _grant_bare_minor(state: GameState, idx: int) -> GameState:
    """Debit the 1 food and push the second bare minor. Reached directly (food
    on hand) and as the `merchant:bare_minor` post-food-payment resume."""
    state = _sub_one_food(state, idx)
    # A bare "Minor Improvement" action (flag set — the repeat IS the named
    # action). `play_minor` is a sub-action leaf, so the engine's
    # _fire_subaction_before_auto seam fires its before-autos — no manual fire
    # (mirrors Task Artisan / other PendingPlayMinor grants; on the resume path
    # `_resume`'s own wrapper provides the same seam).
    return push(state, PendingPlayMinor(
        player_idx=idx, initiated_by_id="card:merchant",
        minor_improvement_action=True))


# --- The single, frame-dispatched apply (see the MACHINERY NOTE) --------------

def _apply(state: GameState, idx: int) -> GameState:
    """Dispatch on the firing host: the composite pushes a second composite, a
    bare minor pushes a second bare minor (the type-matched repeat). With the
    fee on hand, debit-and-push directly; when short, push the raise-only
    PendingFoodPayment whose resume kind carries the clause (ruling 82's
    corrected payment shape; the fee is the only cost, so nothing is
    reserved — the child's own needs are protected by the preserve check)."""
    composite = isinstance(state.pending_stack[-1], PendingMajorMinorImprovement)
    if state.players[idx].resources.food >= 1:
        return _grant_composite(state, idx) if composite \
            else _grant_bare_minor(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=1,
        resume_kind=f"{CARD_ID}:composite" if composite
        else f"{CARD_ID}:bare_minor",
        reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register("after_major_minor_improvement", CARD_ID, _eligible_composite, _apply)
register("after_play_minor", CARD_ID, _eligible_bare_minor, _apply)
# The raise-only food frame's continuations, one per clause (ruling 82), each
# preserve-checked: the frame offers exactly the bundles whose post-state (fee
# debited) still has a legal child for the repeat — mirroring the eligibility
# probe above, so the gate and the frame can never disagree.
register_food_payment_resume(f"{CARD_ID}:composite", _grant_composite)
register_food_payment_resume(f"{CARD_ID}:bare_minor", _grant_bare_minor)
register_food_payment_preserve(
    f"{CARD_ID}:composite",
    lambda post, idx: _child_remains_composite(_sub_one_food(post, idx), idx))
register_food_payment_preserve(
    f"{CARD_ID}:bare_minor",
    lambda post, idx: _child_remains_bare(_sub_one_food(post, idx), idx))
# Deliberately NOT registered on the named-action-grant decline-income seam
# (user ruling 77 item 3, 2026-07-21 — see the module docstring): declining
# the pay-1-food-and-repeat bundle is not declining the named action.
