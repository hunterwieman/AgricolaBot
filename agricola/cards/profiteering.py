"""Profiteering (minor improvement, E82; Ephipparius Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 food. Each time after
you use the "Day Laborer" action space, you can exchange 1 building resource for
another building resource."

Cost: none. Prerequisite: none. VPs: none. Not passing.

Two effects:

1. **On play** — a plain +1 food goods gain (the consultant.py / clay_embankment.py
   shape). User ruling 2026-07-17 (ruling 66): the on-play "immediately" adds or
   changes nothing — it is the ordinary on-play instant, no separate/earlier moment.

2. **The exchange** — "Each time AFTER you use the 'Day Laborer' action space, you can
   exchange 1 building resource for another." The text says "after you use" explicitly,
   so this is an **optional** `after_action_space` trigger filtered to the
   `day_laborer` host (own use only — ownership is checked on `pending.player_idx`, so
   the opponent's Day Laborer use never offers it). Day Laborer is a TRUE-ATOMIC space
   (no host frame by default), so `register_action_space_hook("profiteering",
   {"day_laborer"})` is REQUIRED to give it a `PendingActionSpace` host to fire from.

   The exchange is a CHOICE of a (give, get) pair, so it is modeled as a
   **play-variant trigger** (`register_play_variant_trigger`, the Cottager / Cookery
   Lesson mechanism): `_legal_variants(state, idx)` returns one variant per legal pair
   — give in {wood, clay, reed, stone} the owner holds >= 1 of, get in the OTHER three
   building-resource types (never give == get) — each surfaced as a distinct
   `FireTrigger("profiteering", variant="wood->clay")`. The apply fn is 3-arg
   `(state, idx, variant)`: -1 give, +1 get. The host's `triggers_resolved` makes it
   fire at most once per Day Laborer use ("each time you use"); declining is the host's
   Stop (the after-phase exit). When the owner holds no building resource, the variant
   list is empty so no FireTrigger is offered and the host is a bare Stop.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "profiteering"
SPACES = frozenset({"day_laborer"})
BUILDING_RESOURCES = ("wood", "clay", "reed", "stone")


def _on_play(state: GameState, idx: int) -> GameState:
    # Ruling 66 (2026-07-17): the on-play "immediately" is the ordinary on-play
    # instant — a plain +1 food gain, nothing earlier or separate.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The exchanges currently legal for Profiteering: one "give->get" per pair where
    the owner holds >= 1 of the give type and get is a DIFFERENT building resource.
    Empty list → the owner has no building resource to trade, so nothing to offer."""
    r = state.players[idx].resources
    variants: list[str] = []
    for give in BUILDING_RESOURCES:
        if getattr(r, give) < 1:
            continue
        for get in BUILDING_RESOURCES:
            if get == give:
                continue
            variants.append(f"{give}->{get}")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "after you use the Day Laborer action space" → after_action_space on the
    # day_laborer host. The host's triggers_resolved (handled by _apply_fire_trigger)
    # prevents re-firing within one use, giving the once-per-use semantics.
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    give, get = variant.split("->")
    p = state.players[idx]
    # give != get is guaranteed by _legal_variants, so the two kwargs are distinct.
    delta = Resources(**{give: -1, get: 1})
    p = fast_replace(p, resources=p.resources + delta)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, on_play=_on_play)               # no cost, no prereq, no VPs
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_space_hook(CARD_ID, SPACES)             # host Day Laborer when owned
