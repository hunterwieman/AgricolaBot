"""Social Benefits (minor improvement, D76; Dulcinaria Expansion; Building
Resource Provider).

Card text (verbatim): "Immediately after the feeding phase of each harvest, if
you have no food left, you get 1 wood and 1 clay."
No clarifications printed.

Deck D, number 76. Cost "1 Reed" = `Cost(reed=1)`. Prerequisite: "At Most 1
Occupation" → `max_occupations=1` (the occupation-count prereq shape). Printed
VPs: none (0). Not passing.

TIMING — the `after_feeding` window. Per the user ruling of 2026-07-05,
"IMMEDIATELY after the feeding phase" and "after the feeding phase" name the SAME
instant — the ladder carries one window for it. The ruled ordering against Farm
Store ("after the feeding phase…", an optional exchange that SPENDS food) is
Social Benefits FIRST, carried by the standing autos-before-triggers convention:
the automatic grant below is evaluated (against the food the player still holds)
before Farm Store's optional exchange can spend the last food.

WHAT IT READS — the window resolves AFTER the FEED payment has fully committed
(the walk re-enters `_advance_harvest` past the "feeding" sentinel once every
PendingHarvestFeed frame has resolved), so "if you have no food left" reads the
POST-PAYMENT food: the engine pays `min(need, available)` at feeding and cannot
withhold tokens ("Cannot withhold food tokens"), so a player who could not fully
cover feeding ends with exactly 0 food (begging markers already taken for any
shortfall). Breeding has NOT happened yet, so this reads the state after feeding
but before breeding, exactly as printed.

TWO PATHS to "no food left", one shared reward (a flat +1 wood +1 clay):

- The AUTOMATIC grant (`register_auto` on the `after_feeding` event). When the
  player already has 0 food at this instant — they ran out covering feeding —
  the "no food left" condition holds with no decision to make, so a wood + clay
  gain (always fits: no accommodation, no threshold) fires mechanically.
  Eligibility is `resources.food == 0`.

- The DISCARD trigger (`register` on the same event — an OPTIONAL trigger).
  A player who kept SURPLUS food after feeding can still satisfy "no food left":
  the general rule "You may discard goods to the general supply at any time"
  applies to food (food is one of the goods), so discarding all remaining food
  to reach 0 meets the card's condition and collects the same wood + clay. This
  is a genuine choice — discarding forfeits the food — so it is surfaced as an
  optional trigger on the per-player `PendingHarvestWindow` host; the window's
  `Proceed` is the decline (keep the food, no wood/clay). The reward is a flat
  +1 wood +1 clay regardless of how much food is discarded, and the condition
  needs exactly 0 food, so the only reward-granting play is "discard all" — one
  FireTrigger with no variant. Eligibility is `resources.food > 0`.

MUTUALLY EXCLUSIVE — the auto fires iff food == 0 and the trigger is offered iff
food > 0 at the same instant. The auto only adds wood/clay (it never changes the
food count), so the trigger-eligibility check that runs right after the auto sees
the same food value: never can both apply, so there is never a double grant.
Firing the discard trigger zeros the food and marks the card resolved for this
window, so it cannot re-fire (and food is now 0, failing its own eligibility).

Played via a play-minor flow; no on-play effect (the effect is purely the
recurring window income). Card-only registries default empty, so the Family game
is byte-identical and the C++ differential gates are untouched. See
shepherds_whistle.py (the auto + optional-trigger on one harvest window idiom),
bale_of_straw.py (the harvest-window auto idiom), and CARD_AUTHORING_GUIDE.md.

Ruling 84 (2026-07-27) classification: the `food == 0` comparison READS the
player's own post-feeding supply as the printed condition ("no food left") —
nothing is charged for the grant; not a cost gate.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "social_benefits"
WINDOW_ID = "after_feeding"

_GRANT = Resources(wood=1, clay=1)


def _eligible(state: GameState, idx: int) -> bool:
    """Fire the AUTOMATIC grant only when the owner has no food left after this
    harvest's feeding (the "no food left" instant, reached by running out)."""
    return state.players[idx].resources.food == 0


def _apply(state: GameState, idx: int) -> GameState:
    """+1 wood +1 clay, granted immediately after the feeding payment resolves."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _GRANT)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _discard_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the OPTIONAL discard trigger only when the owner still holds food
    (food > 0) — exactly the case the automatic grant's `food == 0` condition
    failed, so the two never both apply. Ownership and the once-per-window guard
    are enforced by the host enumerator (`_owns` + the frame's
    `triggers_resolved`)."""
    return state.players[idx].resources.food > 0


def _discard_apply(state: GameState, idx: int) -> GameState:
    """Discard ALL remaining food (to 0, no proceeds) to satisfy "no food left",
    then take the same +1 wood +1 clay reward."""
    p = state.players[idx]
    p = fast_replace(p, resources=fast_replace(p.resources, food=0) + _GRANT)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(Resources(reed=1)), max_occupations=1, vps=0)
register_auto(WINDOW_ID, CARD_ID, _eligible, _apply)
register(WINDOW_ID, CARD_ID, _discard_eligible, _discard_apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
