"""Angler (occupation, A95; Artifex Expansion; players 1+).

Card text: "Each time after you use the \"Fishing\" Accumulation space while
there are at most 2 food on that space, you get a \"Major or Minor Improvement\"
action."

Timing: the grant is explicitly AFTER ("Each time after you use ...") — an
`after_action_space` trigger on the `fishing` host. The CONDITION, "while there
are at most 2 food on that space", is the PRE-take count (0/1/2 food qualifies;
3+ does not). Fishing sweeps its whole pile into the player at the take, so the
food that WAS on the space equals the host frame's `taken.food` — the Resources
delta stamped across the take (Refactor A). The after-window trigger reads that
directly; no before-window snapshot is needed (this replaces the old
CardStore-snapshot idiom, which existed only because the pre-take scalar was
gone by the after window).

Firing kind: a granted ACTION is optional (only "you must" is mandatory) → an
OPTIONAL trigger (`register`, not `register_auto`); not firing IS the decline
(the host's Stop). Firing pushes a fresh `PendingMajorMinorImprovement` with
provenance `"card:angler"` and fires the composite's before-autos at the push —
the Merchant idiom (Merchant is the precedent for a card-granted "Major or Minor
Improvement action"). The player then chooses build-major or play-minor as
usual.

Eligibility (never push a dead host): `taken.food <= 2` AND the granted composite
must have a legal child right now — an affordable unowned major
(`_can_afford_any_major_improvement`) or a playable hand minor
(`playable_minors`), the exact predicates the composite's own choose-enumerator
uses. The host's `triggers_resolved` latch makes the grant once per Fishing use.

Fishing is an atomic accumulation space, so `register_action_space_hook` is
required to host it. (In real play Fishing holds >= 1 food — it refills every
round — so the 0 band is unreachable, but "at most 2" covers it harmlessly.)

Fishing is never hosted in the Family game (no hooking card), so this frame's
after-window is card-only → byte-identical, C++ gates untouched. Played via
Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    apply_auto_effects,
    register,
    register_action_space_hook,
)
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, push
from agricola.state import GameState

CARD_ID = "angler"
SPACES = frozenset({"fishing"})
MAX_FOOD = 2   # "at most 2 food on that space" — the pre-take count


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per Fishing use
        return False
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) not in SPACES:
        return False
    # "at most 2 food on that space" is the PRE-take count. Fishing sweeps its whole
    # pile into the player, so the food that WAS on the space == `taken.food` (the
    # Resources delta stamped across the take). The space_id pin guarantees `top` is
    # the atomic fishing host, which always carries `taken`.
    if top.taken.food > MAX_FOOD:                          # pre-take count 0/1/2
        return False
    # Never push a dead host: the granted composite must have a legal child now.
    return (_can_afford_any_major_improvement(state, state.players[idx])
            or bool(playable_minors(state, idx)))


def _apply(state: GameState, idx: int) -> GameState:
    state = push(state, PendingMajorMinorImprovement(
        player_idx=idx, initiated_by_id="card:angler",
    ))
    # The composite is itself a host: fire its before-autos at the push
    # (mirrors the engine push sites and Merchant's granted-composite idiom).
    return apply_auto_effects(state, "before_major_minor_improvement", idx)


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play; effect is the hook
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
