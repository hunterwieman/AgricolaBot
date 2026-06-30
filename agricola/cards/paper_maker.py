"""Paper Maker (occupation, B109; Base Revised; players 1+).

Card text: "Immediately before playing each occupation after this one, you can pay 1 wood
total to get 1 food for each occupation you have in front of you."

An optional `before_play_occupation` trigger: each time you play an occupation (via Lessons,
Scholar, or any future route), BEFORE paying its cost, you MAY pay 1 wood to get 1 food per
occupation you have in front of you. The play-occupation host's before-phase already surfaces
`before_play_occupation` triggers, so no new firing machinery is needed.

"after this one" is AUTOMATIC: triggers only fire for OWNED cards (`_eligible_fire_triggers`
checks `_owns`), and Paper Maker is not yet in the tableau during its OWN play (it is added at
`CommitPlayOccupation`, after the before-phase), so it never fires on itself. (Contrast Seed
Almanac on `after_play_minor`, where the card IS in the tableau by the after-phase.) Once per
play ("1 wood total") via the host's `triggers_resolved`. "occupations you have in front of
you" = `len(p.occupations)` (the occupation being played is not yet added) — always >= 1
since you own Paper Maker.

Because firing it produces food usable for the occupation's food cost, it ALSO registers an
OCCUPATION_FOOD_SOURCE: the affordability gate (`_legal_lessons_cards` / Scholar) consults it
via `_payable_occupation` so an occupation payable only by firing Paper Maker first is still
offered (else you'd never reach the frame to fire it). The play-occupation enumerator's commit
gate (`_payable(top.cost)`) then withholds the commit until Paper Maker has been fired, so
there is no empty-frontier `PendingFoodPayment` dead state. The source declares its inputs
(1 wood) so the gate's simulated liquidation reserves them (forward-compatible with a future
wood->food liquidation). It is NOT folded into the food-payment frame: as a pure 1-wood->N-food
value trade it must be offered even when you already have the food. See PAY_FOOD_PLOW_CARDS.md /
FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation, register_occupation_food_source
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "paper_maker"


def _food_for(state: GameState, idx: int) -> int:
    """Food produced = occupations in front of you (the one being played isn't added yet)."""
    return len(state.players[idx].occupations)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional, always offered when owned + can pay the 1 wood (you always have >= 1 occupation
    # in front of you — Paper Maker itself — so there is always food to gain).
    return CARD_ID not in triggers_resolved and state.players[idx].resources.wood >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=(p.resources - Resources(wood=1)
                                   + Resources(food=_food_for(state, idx))))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _food_source(state: GameState, idx: int):
    """For the occupation-affordability gate: (food produced, inputs consumed) when firing is
    possible, else None. Used by `_payable_occupation` to simulate firing Paper Maker."""
    if state.players[idx].resources.wood < 1:
        return None
    return (_food_for(state, idx), Resources(wood=1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_play_occupation", CARD_ID, _eligible, _apply)
register_occupation_food_source(CARD_ID, _food_source)
