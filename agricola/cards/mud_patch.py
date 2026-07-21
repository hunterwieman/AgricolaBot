"""Mud Patch (minor improvement, A11; Artifex Expansion; Farm Planner; no cost).

Card text (verbatim): "When you play this card, you immediately get 1 wild boar.
You can hold 1 wild boar on each of your unplanted field tiles."

No cost, no prerequisite, no printed VPs, kept (not passing).

Two effects:

1. On-play grant — `helpers.grant_animals` with 1 wild boar. The accommodation
   barrier handles overflow (a boar that does not fit surfaces the keep-or-cook
   choice); never a raw `p.animals + ...` (CARD_AUTHORING_GUIDE §0.1 / the
   grant_animals contract).

2. A per-species (boar-only) card slot — one boar slot PER UNPLANTED FIELD
   TILE. Registered via `capacity_mods.register_typed_slots` (the per-species
   holder family, generalized 2026-07-21); the accommodation entry points
   realize it via the greedy strip (exact by dominance, per type
   independently). "Field tiles" is grid-only — card-fields never count
   (established ruling 32). UNPLANTED = a FIELD grid cell holding no grain, no
   veg, AND no stone — exactly `Cell.field_empty`, whose stone clause is Stone
   Clearing's errata ("a stone-holding field is considered planted until the
   stone is gone"; user ruling 2026-07-20).

USER RULINGS (both 2026-07-21):
- The capacity is per UNPLANTED field tile (the printed reading confirmed — not
  all tiles).
- The typed-slot fold direction (the per-species independent strip).

EVICTION — the subtle part. The slot count is DYNAMIC, and it can DROP while
boars sit on the card:
  (a) the owner sows a board field (an unplanted tile becomes planted), or
  (b) the owner plays Stone Clearing onto empty board fields (stone makes them
      "planted").
The accommodation barrier only re-checks a player whose
`animals_need_accommodation` flag is set, so a silent drop would leave an
over-capacity state the barrier never revisits. Mud Patch therefore SETS that
flag for its owner at the two count-reducing OWN-action seams — an `after_sow`
auto (own sows) and an `after_play_minor` auto (covers Stone Clearing's
placement). Over-triggering is harmless: the barrier just clears the flag when
everything still fits and surfaces the keep-or-cook choice otherwise. This
mirrors the eviction idiom of the capacity-shrinking cards (milking_place's
on-play flag-set). Eligibility is gated on the owner actually holding a boar
(nothing to evict otherwise); ownership is enforced by the auto registry.

The count RISING (plowing a new field, a harvest emptying a field, a stone
running out) needs no hook — it only grows capacity.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_typed_slots
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.state import GameState, PlayerState

CARD_ID = "mud_patch"


def _unplanted_field_tiles(p: PlayerState) -> int:
    """Board FIELD grid cells holding nothing — `Cell.field_empty` (no grain, no
    veg, no stone). Grid-only (ruling 32: card-fields are never field TILES)."""
    grid = p.farmyard.grid
    return sum(1 for r in range(3) for c in range(5) if grid[r][c].field_empty)


def _slots(state, p: PlayerState) -> Animals:
    """One boar slot per unplanted field tile (recomputed per call — dynamic; the
    greedy strip re-reads it each accommodation question, so no cache staleness)."""
    return Animals(boar=_unplanted_field_tiles(p))


def _on_play(state: GameState, idx: int) -> GameState:
    """Grant 1 wild boar through the accommodation barrier (grant_animals sets the
    flag; a boar that does not fit surfaces the keep-or-cook choice)."""
    return grant_animals(state, idx, Animals(boar=1))


def _has_boar(state: GameState, idx: int) -> bool:
    """Nothing to evict unless the owner holds a boar (a safe, cheap gate;
    ownership is enforced by the auto registry)."""
    return state.players[idx].animals.boar > 0


def _flag_owner(state: GameState, idx: int) -> GameState:
    """Set the accommodation flag so the barrier re-checks the fit — the boar-slot
    count may have just dropped under held boars (a sow planted a tile; Stone
    Clearing stoned empty fields)."""
    p = fast_replace(state.players[idx], animals_need_accommodation=True)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, on_play=_on_play)
register_typed_slots(CARD_ID, _slots)
register_auto("after_sow", CARD_ID, _has_boar, _flag_owner)
register_auto("after_play_minor", CARD_ID, _has_boar, _flag_owner)
