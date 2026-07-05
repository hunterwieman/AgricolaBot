"""Treegardener (occupation, A118; Artifex Expansion; players 1+).

Card text (verbatim): "In the field phase of each harvest, you get 1 wood and
you can buy up to 2 additional wood for 1 food each."

Clarification (verbatim): "《You may use this card to activate the Shaving Horse
A048 twice if and only if you have another decision during the field phase to
separate this card's effect into two distinct parts, e.g. paying wood and food
with Cube Cutter C098.》"

Category: Building Resource Provider. Occupation — no structured cost /
prerequisite / VPs (occupations carry none in the card data). Not passing.

TWO CLAUSES, both in the field phase (harvest window #5, "field_phase"; the
during-window). They are two distinct firing kinds:

1. **"you get 1 wood"** — a MANDATORY, choice-free income → an automatic effect
   (`register_auto("field_phase", …)`). Fired by `engine._field_phase_step` via
   `apply_auto_effects` before the mechanical crop take, once per owner per
   harvest. It only credits wood; it touches no crops, so it does not alter what
   the take then harvests.

2. **"you can buy up to 2 additional wood for 1 food each"** — an OPTIONAL choice
   → a free-ordered `"field_phase"` trigger on the `PendingFieldPhase` host
   (the Cube Cutter class — HARVEST_WINDOWS_DESIGN.md §4a; legal at any point in
   the window, before or after the mandatory `CommitFieldTake`, in any
   player-chosen order). "up to 2" is ONE buying decision (buy 1 wood for 1
   food, OR buy 2 wood for 2 food), NOT two separate uses — so it is modeled as a
   play-variant trigger (`register_play_variant_trigger`, mirroring
   `home_brewer.py`) with variants "1" and "2" (the wood quantity bought / food
   spent). Buying zero is expressed by declining the trigger (`Proceed`). The
   `PendingFieldPhase` frame's `triggers_resolved` gives the once-per-field-phase
   cap the printed "In the field phase of each harvest" describes: firing the
   trigger (at either quantity) marks it resolved, so it cannot fire again this
   window.

   Affordability: buying costs 1 food per wood, so the "1" variant needs >=1
   food and the "2" variant needs >=2 food. The eligibility fn offers the trigger
   iff the owner holds >=1 food (enough for at least the "1" variant); the
   variants fn then filters to the quantities the owner can actually pay for.

The Shaving Horse (A048) clarification is MOOT here: Shaving Horse is BANNED —
never implemented (marked 🚫 BANNED in CARD_IMPLEMENTATION_PROGRESS.md's A48
entry) — so there is no card in the pool whose wood-obtained activation this
could double, and nothing is built for that interaction.

Both effects read/modify only the owner's own resources (no crops, no
HarvestOccasion), so each is a plain state edit. The card is empty in the Family
game (no player owns it), so the engine stays byte-identical and the C++ gates
are untouched. See CARD_AUTHORING_GUIDE.md and harvest_windows.py.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_auto, register_play_variant_trigger
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "treegardener"

WINDOW = "field_phase"

_MAX_BUY = 2   # "up to 2 additional wood"


def _credit_wood(state: GameState, idx: int, wood: int) -> GameState:
    """Grant `wood` wood to player `idx` (touching no other state)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=wood))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Clause 1: the mandatory +1 wood (a field-phase auto) --------------------

def _auto_eligible(state: GameState, idx: int) -> bool:
    """Always fires: the +1 wood is unconditional (no cost, no threshold)."""
    return True


def _auto_apply(state: GameState, idx: int) -> GameState:
    """+1 wood in the field phase, before the crop take (a plain resource credit)."""
    return _credit_wood(state, idx, 1)


# --- Clause 2: the optional "buy up to 2 wood for 1 food each" trigger --------

def _buy_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff the owner can afford at least the smallest quantity — 1
    food for 1 wood. Ownership and the once-per-field-phase cap are enforced by
    the host enumerator / the frame's `triggers_resolved`; this fn only checks
    affordability."""
    return state.players[idx].resources.food >= 1


def _buy_variants(state: GameState, idx: int) -> list[str]:
    """The affordable buy quantities: "1" (1 food -> 1 wood) always when >=1 food,
    "2" (2 food -> 2 wood) additionally when >=2 food. Each quantity costs 1 food
    per wood; the printed cap is 2 additional wood."""
    food = state.players[idx].resources.food
    return [str(q) for q in range(1, _MAX_BUY + 1) if food >= q]


def _buy_apply(state: GameState, idx: int, variant: str) -> GameState:
    """Buy `variant` additional wood, paying 1 food per wood bought."""
    qty = int(variant)
    assert 1 <= qty <= _MAX_BUY, f"unknown treegardener buy quantity {variant!r}"
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=qty, food=-qty))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# Played via Lessons; no on-play effect (both clauses are recurring field-phase
# effects, so on-play is a no-op).
register_occupation(CARD_ID, lambda state, idx: state)

# Clause 1: the mandatory +1 wood, fired pre-take by the field-phase walk.
register_auto(WINDOW, CARD_ID, _auto_eligible, _auto_apply)

# Clause 2: the optional buy — a free-ordered, once-per-field-phase play-variant
# trigger on the "field_phase" during-window (buy 1 or 2 wood, 1 food each).
register(WINDOW, CARD_ID, _buy_eligible, _buy_apply)
register_play_variant_trigger(CARD_ID, _buy_variants)

# One hook registration covers both the auto and the trigger on this window.
register_harvest_window_hook(CARD_ID, WINDOW)
