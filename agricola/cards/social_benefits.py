"""Social Benefits (minor improvement, D76; Dulcinaria Expansion; Building
Resource Provider).

Card text (verbatim): "Immediately after the feeding phase of each harvest, if
you have no food left, you get 1 wood and 1 clay."
No clarifications printed.

Deck D, number 76. Cost "1 Reed" = `Cost(reed=1)`. Prerequisite: "At Most 1
Occupation" → `max_occupations=1` (the occupation-count prereq shape). Printed
VPs: none (0). Not passing.

TIMING — harvest window #10 `immediately_after_feeding`: the printed "immediately
after the feeding phase of each harvest" is that window's defining phrase
(HARVEST_WINDOWS_DESIGN.md §1/§5, the anti-food-laundering window sitting between
the FEED payment and after_feeding). A MANDATORY, choiceless income (a wood + clay
gain always fits — no accommodation, no threshold) → an automatic effect
(`register_auto` on the `immediately_after_feeding` window event), fired by the
harvest walk (`_process_simple_window`, window-major, starting player first) per
owner — no frame.

WHAT IT READS — window #10 resolves AFTER the FEED payment has fully committed
(the walk re-enters `_advance_harvest` past the "feeding" sentinel once every
PendingHarvestFeed frame has resolved), so "if you have no food left" reads the
POST-PAYMENT food: the engine pays `min(need, available)` at feeding and cannot
withhold tokens ("Cannot withhold food tokens"), so a player who could not fully
cover feeding ends with exactly 0 food (begging markers already taken for any
shortfall). Eligibility is therefore `resources.food == 0` at this instant — the
literal "no food left". Breeding (window #13) has NOT happened yet, so this reads
the state after feeding but before breeding, exactly as printed. This is BEFORE
window #11 `after_feeding`, matching the ladder order.

Played via a play-minor flow; no on-play effect (the effect is purely the
recurring window income). Card-only registries default empty, so the Family game
is byte-identical and the C++ differential gates are untouched. See bale_of_straw.py
(the harvest-window auto idiom) and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "social_benefits"
WINDOW_ID = "immediately_after_feeding"

_GRANT = Resources(wood=1, clay=1)


def _eligible(state: GameState, idx: int) -> bool:
    """Fire only when the owner has no food left after this harvest's feeding."""
    return state.players[idx].resources.food == 0


def _apply(state: GameState, idx: int) -> GameState:
    """+1 wood +1 clay, granted immediately after the feeding payment resolves."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _GRANT)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(Resources(reed=1)), max_occupations=1, vps=0)
register_auto(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
