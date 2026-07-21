"""Cottager (occupation, B87; Base Revised; players 1+).

Card text: "Each time you use the 'Day Laborer' action space, you can also either build
exactly 1 room or renovate your house. Either way, you have to pay the cost."

Category 4 (granted sub-action) — but the one Category-4 card that grants a *choice*
between two different primitives (build 1 room OR renovate) rather than a single one.
Modeled as the COLLAPSED PLAY-VARIANT trigger (like Scholar), now generalized to the
action-space host: "each time you use Day Laborer" → an OPTIONAL `before_action_space`
trigger on the `day_laborer` host (the Trigger-Timing ruling: "each time you use
[space]" fires before the space's own effect — observationally neutral here since Day
Laborer yields only food, never a building material, but fixed by the ruling). The
host enumerator (`_enumerate_pending_action_space`, via `_expand_variant_triggers`)
surfaces a distinct `FireTrigger("cottager", variant="room")` (when a room is
affordable + placeable) and `FireTrigger("cottager", variant="renovate")` (when the
house can be upgraded + afforded); "do neither" is the host's Proceed (the trigger is
optional). Firing pushes the standard `PendingBuildRooms(max_builds=1)` or
`PendingRenovate` with the normal cost (mirroring Farm Expansion / House
Redevelopment), so no new sub-decision machinery. The host's `triggers_resolved` makes
it fire at most once per Day Laborer use ("each time you use"). On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.legality import _can_build_room, _can_renovate
from agricola.pending import PendingBuildRooms, PendingRenovate, push
from agricola.state import GameState

CARD_ID = "cottager"
SPACES = frozenset({"day_laborer"})


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The grants currently legal for Cottager: 'room' when a room is affordable and
    placeable; 'renovate' when the house can still be upgraded and the cost is
    affordable. Empty list → nothing to do this use."""
    p = state.players[idx]
    variants: list[str] = []
    if _can_build_room(state, p):
        variants.append("room")
    if _can_renovate(state, p):
        variants.append("renovate")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "each time you use Day Laborer" → before_action_space on the day_laborer host.
    # The host's triggers_resolved (handled by _apply_fire_trigger) prevents re-firing
    # within one use, giving the once-per-use semantics.
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    # Push the chosen primitive; the pushed frame's own enumerator then offers the
    # build/renovate commits + exit, and resolves cost through the cost-modifier
    # chokepoint. The host's Proceed (decline) is the "do neither" path — reached
    # only by NOT firing this trigger.
    if variant == "room":
        return push(state, PendingBuildRooms(
            player_idx=idx,
            initiated_by_id="card:cottager",
            max_builds=1,                       # "exactly 1 room"
            # A card effect that builds a room, NOT the named "Build Rooms"
            # action (the §9.6 flag contract / the RULES.md named-action
            # doctrine) — so named-action readers (Family Friendly Home's
            # "each time you take a 'Build Rooms' action") do not fire on it.
            build_rooms_action=False,
        ))
    # renovate: cost is resolved through the cost-modifier chokepoint at the pushed
    # frame's enumerator (COST_MODIFIER_DESIGN.md §3.3), exactly like House
    # Redevelopment — nothing to compute or store here.
    return push(state, PendingRenovate(
        player_idx=idx, initiated_by_id="card:cottager"))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_space_hook(CARD_ID, SPACES)   # host Day Laborer when Cottager is owned
