"""Little Stick Knitter (occupation, B92; Bubulcus Expansion; players 1+).

Card text (verbatim): "From Round 5 on, each time you use the "sheep Market"
accumulation space, you can also take a "Family Growth with Room Only" action."
No clarifications printed. Occupation — no cost / prerequisite / VPs.

TIMING — the bare "each time you use [space]" fires in the BEFORE window of the
space (the official Trigger-Timing ruling, CARD_AUTHORING_GUIDE.md §2), so this
registers on ``before_action_space`` with a ``space_id == "sheep_market"``
eligibility filter. Sheep Market is a NON-ATOMIC space (``_initiate_sheep_market``
always pushes a ``PendingSheepMarket`` host frame), so no
``register_action_space_hook`` is needed — that index gates only the conditional
hosting of atomic spaces.

OPTIONALITY — user confirmation (2026-07-14): the family growth is offered as an
OPTION (an optional trigger the player may fire or ignore), never a mandatory
push. "You can also take" is a granted sub-action, and a granted sub-action is
optional (CARD_AUTHORING_GUIDE.md §2 "A granted sub-action is optional"): an
ordinary ``register`` (a ``FireTrigger``), declined by simply proceeding to the
market's own accommodation. Once per use is the host frame's
``triggers_resolved``.

"FROM ROUND 5 ON" — ``state.round_number >= 5``, checked at the moment of use.

"FAMILY GROWTH WITH ROOM ONLY" — the Basic Wish for Children gate, checked in
``_eligible`` per the engine convention (the primitive does not self-check; the
room gate is the CALLER's eligibility check — ``PendingFamilyGrowth`` docstring /
CARD_DEFERRED_PLANS.md §A1): ``workers_in_supply > 0`` (the family cap — a meeple
left in supply, a game rule the card does not waive) AND
``people_total < _num_rooms(p)`` (a free room for the newborn).

THE GROWTH — the card-granted family-growth primitive (Group A1, built
2026-07-03 with the user's ruling recorded in CARD_DEFERRED_PLANS.md §A1 / the
``PendingFamilyGrowth`` docstring): firing pushes
``PendingFamilyGrowth(place_on_space=False)``, so the newborn occupies NO action
space — the commit increments the owner's people_total/newborns only. The
newborn is a normal newborn: it feeds at the next harvest's FEED as a newborn
if born in a harvest round, and grows up at RETURN_HOME like any other.

No stranding concern: the growth consumes nothing the market's mandatory work
(taking the accumulated sheep) needs, so ``_eligible`` gates only on the round
and the room condition.

Played via Lessons; on-play is a no-op (the effect is purely recurring).
Card-only registries are empty in the Family game, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _num_rooms
from agricola.pending import PendingFamilyGrowth, push
from agricola.state import GameState

CARD_ID = "little_stick_knitter"
SPACE_ID = "sheep_market"


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the growth iff this is the owner's use of the Sheep Market, the
    round is 5+ ("From Round 5 on"), and the Room Only gate holds (a free room
    AND under the 5-person cap). Ownership is the enumerator's ``_owns`` gate;
    once-per-use is the host frame's ``triggers_resolved`` (self-checked here
    too, mirroring the market exemplars)."""
    if CARD_ID in triggers_resolved:
        return False
    if state.pending_stack[-1].space_id != SPACE_ID:
        return False
    if state.round_number < 5:
        return False
    p = state.players[idx]
    return p.workers_in_supply > 0 and p.people_total < _num_rooms(p)


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the growth: push the card-grant family-growth primitive (no board
    placement; the commit increments the owner's people_total/newborns)."""
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


# Pure recurring occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Optional trigger on the Sheep Market's before window ("each time you use").
register("before_action_space", CARD_ID, _eligible, _apply)
