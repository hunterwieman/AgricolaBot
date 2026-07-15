"""Merchant (occupation, C96; Corbarius Expansion; players 1+).

Card text: "Immediately after each time you take a 'Major or Minor Improvement'
or 'Minor Improvement' action, you can pay 1 food to take the action a second
time."

Clarification: "Does not combo with Field Merchant B103." (Field Merchant is not
implemented; nothing to encode — its own clarification already says Merchant
does not double a decline.)

User rulings (2026-07-14):
  1. House Redevelopment's optional major-or-minor second step COUNTS — "the
     Major or Minor Improvement action is distinct from the Major or Minor
     Improvement action space." Mechanically both routes run through the shared
     composite host (`PendingMajorMinorImprovement`), so hooking the composite's
     own event covers both entry points.
  2. "Immediately after" falls in the SAME trigger seam as ordinary after-window
     triggers (on the ACTION's host, not the action space).
  3. "A second time" — Merchant may NOT fire again off its own granted action
     (no chaining).

(The "Minor Improvement" action named on the card is the 3+-player 6p-space's
action — absent at 2 players; the composite covers everything reachable here.)

Category 4 (granted action). "You can pay 1 food" is the player's choice → an
OPTIONAL trigger (`register`, not `register_auto`) on
`after_major_minor_improvement` — the composite host's own after-event (it is
deliberately excluded from the coarse `action_space` bucket; see
`trigger_event` in agricola/legality.py). Not firing IS the decline.

Eligibility (never grant a dead end):
  - the player holds >= 1 food (the payment), AND
  - the host was not itself granted by Merchant (ruling 3): the composite's
    `initiated_by_id != "card:merchant"`, AND
  - AFTER paying the 1 food, the granted composite would still have a legal
    child — an affordable unowned major (`_can_afford_any_major_improvement`)
    or a playable hand minor (`playable_minors`), the exact predicates the
    composite's own choose-enumerator uses. The post-payment check matters:
    with exactly 1 food and a sole playable minor costing 1 food, paying
    Merchant's fee would strand a dead host.

Firing: debit 1 food and push a fresh `PendingMajorMinorImprovement` with
provenance `"card:merchant"` — the player then chooses build-major or
play-minor as usual. The composite is itself a host, so its
`before_major_minor_improvement` autos fire at the push (mirroring the two
engine push sites; `_fire_subaction_before_auto` deliberately skips composite
hosts). The granted host's own after-window will not re-offer Merchant (the
provenance guard), and the original host's `triggers_resolved` latch makes the
offer once per action-take.

Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import apply_auto_effects, register
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "merchant"


def _sub_one_food(state: GameState, idx: int) -> GameState:
    """`state` with 1 food debited from player `idx`."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    # Ruling 3: never chain off Merchant's own granted action.
    if getattr(top, "initiated_by_id", "") == "card:merchant":
        return False
    if state.players[idx].resources.food < 1:
        return False
    # The granted composite must have a legal child AFTER the 1-food payment.
    paid = _sub_one_food(state, idx)
    return (_can_afford_any_major_improvement(paid, paid.players[idx])
            or bool(playable_minors(paid, idx)))


def _apply(state: GameState, idx: int) -> GameState:
    state = _sub_one_food(state, idx)
    state = push(state, PendingMajorMinorImprovement(
        player_idx=idx, initiated_by_id="card:merchant",
    ))
    # The composite is itself a host: fire its before-autos at the push
    # (mirrors the space / House-Redevelopment push sites).
    return apply_auto_effects(state, "before_major_minor_improvement", idx)


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register("after_major_minor_improvement", CARD_ID, _eligible, _apply)
