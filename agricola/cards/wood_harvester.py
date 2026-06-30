"""Wood Harvester (occupation, A104; Artifex Expansion; players 1+).

Card text: "In the field phase of each harvest, you get 1 wood/1 food for each wood
accumulation space with exactly 2 wood/at least 3 wood."

Category 6 (harvest-field hook). The text is the Agricola slash-template — TWO
parallel clauses, NOT one combined gain:
  - 1 WOOD for each wood accumulation space with EXACTLY 2 wood, and
  - 1 FOOD for each wood accumulation space with AT LEAST 3 wood.
"exactly 2" and "at least 3" are mutually exclusive, so a single space yields at
most one of {1 wood, 1 food}.

On the 2-player board (reused in cards mode) the only wood accumulation space is
the Forest, so the whole effect collapses to a single read of
`forest.accumulated.wood`: ==2 grants +1 wood, >=3 grants +1 food, <2 grants
nothing. The income is read from the Forest's `accumulated` Resources field (the
wood pile sitting on the space) — NOT `accumulated_amount` (the scalar used by
food/animal spaces, which is 0 here).

Implemented as an automatic effect (`register_auto` on `harvest_field`), fired by
`_resolve_harvest_field` in the field phase before the mechanical crop take. The
effect is a pure goods grant with no downside, so it is mandatory/choice-free (no
optional FireTrigger). Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "wood_harvester"

# 2-player: Forest is the only wood accumulation space.
WOOD_SPACES = frozenset({"forest"})


def _wood_income(state: GameState) -> Resources:
    """The card's total income: across every wood accumulation space, +1 wood for
    each space holding exactly 2 wood and +1 food for each holding at least 3."""
    wood = 0
    food = 0
    for sid in WOOD_SPACES:
        w = get_space(state.board, sid).accumulated.wood
        if w == 2:
            wood += 1
        elif w >= 3:
            food += 1
    return Resources(wood=wood, food=food)


def _eligible(state: GameState, idx: int) -> bool:
    return bool(_wood_income(state))


def _apply(state: GameState, idx: int) -> GameState:
    income = _wood_income(state)
    if not income:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + income)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
