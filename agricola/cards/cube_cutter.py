"""Cube Cutter (occupation, C98; Corbarius Expansion; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 wood. In
the field phase of each harvest, you can use this card to exchange exactly 1
wood and 1 food for 1 bonus point."

Category: Points Provider. Two effects:

1. On play (via Lessons): immediately gain 1 wood.

2. A recurring, optional, once-per-field-phase exchange — spend exactly 1 wood
   and 1 food, produce no food, and bank 1 bonus point.

TIMING — the field phase (harvest window #5). Earlier this card rode the
`HARVEST_CONVERSIONS` seam, which surfaces in the FEEDING phase, not the field
phase. That was a mis-timing (mis-timed card #1 in CARD_DEFERRED_PLANS.md): at
FEED the owner could first cook wood→food via a craft/Joinery conversion and pay
the exchange's food from that, whereas the printed field-phase timing requires
the food already on hand before any feeding conversions run. Per the
harvest-window redesign (HARVEST_WINDOWS_DESIGN.md §4 class (a); user-agreed
design 2026-07-03), Cube Cutter is a **free-ordered independent optional trigger
on the "field_phase" during-window**, legal at any point in the window (before or
after the mandatory crop take, in any player-chosen order). The frame's
`triggers_resolved` gives the once-per-field-phase cap the printed "In the field
phase of each harvest, you can use this card…" describes. The exchange touches no
crops and emits no HarvestOccasion, so it is a plain state edit, not an
additional harvest.

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each fire increments a per-card CardStore counter (banked across all six
harvests), and the scoring term reads the count back at end-game.

Affordability (1 wood + 1 food) is checked in the eligibility fn: the trigger is
only offered when the owner holds at least 1 wood and 1 food. The apply_fn
performs the full exchange (debit the cost, bank the point). Owning the
occupation is sufficient — there is NO Joinery/major gate (unlike Furniture
Carpenter).

Card-only state (the CardStore int) is empty in the Family game, so the engine
stays byte-identical and the C++ gates are untouched. See
CARD_AUTHORING_GUIDE.md and harvest_windows.py.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "cube_cutter"

WINDOW = "field_phase"


def _on_play(state: GameState, idx: int) -> GameState:
    """On play: immediately gain 1 wood."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the exchange iff the owner can afford exactly 1 wood + 1 food.

    Owning the occupation is sufficient (no major/Joinery gate). The
    once-per-field-phase cap is enforced by the PendingFieldPhase frame's
    `triggers_resolved` (this fn is only consulted for unfired triggers), so it
    is not re-checked here. The eligibility is purely affordability: the exchange
    spends 1 wood and 1 food from resources on hand.
    """
    r = state.players[idx].resources
    return r.wood >= 1 and r.food >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Fire the exchange: spend 1 wood + 1 food, produce no food, bank +1 point."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=1, food=1),
        card_state=p.card_state.set(CARD_ID, banked + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Played via Lessons; on-play grants 1 wood.
register_occupation(CARD_ID, _on_play)

# The recurring goods->VP exchange, in the field-phase during-window: an optional,
# free-ordered, once-per-field-phase trigger (spend 1 wood + 1 food, bank +1 point).
register(WINDOW, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW)

register_scoring(CARD_ID, _score)
