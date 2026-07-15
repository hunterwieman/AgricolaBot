"""Angler (occupation, A95; Artifex Expansion; players 1+).

Card text: "Each time after you use the \"Fishing\" Accumulation space while
there are at most 2 food on that space, you get a \"Major or Minor Improvement\"
action."

Timing: the grant is explicitly AFTER ("Each time after you use ...") — an
`after_action_space` trigger on the `fishing` host. The CONDITION, though, reads
Fishing AS YOU USE IT: "while there are at most 2 food on that space" is the
pre-take count (0/1/2 food qualifies; 3+ does not). By the after window the take
has already emptied the space (the accumulation handler zeroes
`accumulated_amount` at Proceed), so the pre-take amount is captured by a
`before_action_space` AUTOMATIC snapshot into the card's own CardStore — the
Shepherd's Crook before/after snapshot idiom. The snapshot is overwritten at
every hosted Fishing use (the before-auto fires unconditionally at the push), so
a stale value from an earlier use is inert.

Firing kind: a granted ACTION is optional (only "you must" is mandatory) → an
OPTIONAL trigger (`register`, not `register_auto`); not firing IS the decline
(the host's Stop). Firing pushes a fresh `PendingMajorMinorImprovement` with
provenance `"card:angler"` and fires the composite's before-autos at the push —
the Merchant idiom (Merchant is the precedent for a card-granted "Major or Minor
Improvement action"). The player then chooses build-major or play-minor as
usual.

Eligibility (never push a dead host): the snapshot must be <= 2 AND the granted
composite must have a legal child right now — an affordable unowned major
(`_can_afford_any_major_improvement`) or a playable hand minor
(`playable_minors`), the exact predicates the composite's own choose-enumerator
uses. The host's `triggers_resolved` latch makes the grant once per Fishing use.

Fishing is an atomic accumulation space, so `register_action_space_hook` is
required to host it. (In real play Fishing holds >= 1 food — it refills every
round — so the 0 band is unreachable, but "at most 2" covers it harmlessly.)

Card-only state (the CardStore snapshot) never exists in the Family game →
byte-identical, C++ gates untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    apply_auto_effects,
    register,
    register_action_space_hook,
    register_auto,
)
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, push
from agricola.replace import fast_replace
from agricola.state import GameState, get_space

CARD_ID = "angler"
SPACES = frozenset({"fishing"})
MAX_FOOD = 2   # "at most 2 food on that space" — the pre-take count


def _snapshot_eligible(state: GameState, idx: int) -> bool:
    # Fire the snapshot only on the fishing host (before_action_space is a
    # coarse event — another owned card could host a different space).
    return getattr(state.pending_stack[-1], "space_id", None) in SPACES


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_action_space AUTO on fishing: record the pre-take food count so the
    after-window trigger can read the "at most 2" condition (the take has emptied
    the space by then). Overwritten each use — stale values are inert."""
    amount = get_space(state.board, "fishing").accumulated_amount
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, amount))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per Fishing use
        return False
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) not in SPACES:
        return False
    snap = state.players[idx].card_state.get(CARD_ID, None)
    if snap is None or snap > MAX_FOOD:                    # pre-take count 0/1/2
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
register_auto("before_action_space", CARD_ID, _snapshot_eligible, _snapshot_before)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
