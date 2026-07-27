"""Catcher (occupation, A107; Artifex Expansion; players 1+).

Card text: "Each time you place your 1st/2nd/3rd person in a round on a building
resource accumulation space with exactly 5/4/3 building resources, you get 1 food."

Category 3 (action-space hook, automatic income). The +1 food is a mandatory,
choiceless effect → an automatic effect (register_auto) on the `before_action_space`
event, NOT a FireTrigger. "Each time you place ... on a [space]" fires in the BEFORE
phase per the Trigger-Timing ruling, so the goods pile is read at FULL — before the
space's own pickup empties it (matching Wood Cutter / Throwing Axe / Milk Jug / Plow
Hero). Played via Lessons; its on-play is a no-op.

The trap is the *paired* threshold: the required goods count is a FUNCTION of which
person you are placing this round — your 1st person needs exactly 5, your 2nd exactly
4, your 3rd exactly 3, and your 4th/5th person never fire. It is EXACTLY-equal (==),
not at-least.

"Which person am I placing?" is the ACTING person's ordinal, read via
helpers.acting_placement_number (the standing-worker ledger's number at the acting
space — ruling 79): the just-minted number at an ordinary placement, the moved
worker's PRESERVED number at a relocated use (Straw Hat's end-of-work move onto
one of these spaces — ruling 79 item 4: a relocation counts as placing that
person). The old derived expression `(people_total − newborns) − people_home`
is retired with the rest of its family.

The five building resource accumulation spaces (BUILDING_RESOURCE_ACCUMULATION_SPACES)
hold only building resources on `accumulated` (a Resources), never `accumulated_amount` (0 here),
so the count is `acc.wood + acc.clay + acc.reed + acc.stone`. These spaces are ATOMIC,
so the card must host them (register_action_space_hook) for a before-phase frame to
exist. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.constants import BUILDING_RESOURCE_ACCUMULATION_SPACES
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.helpers import acting_placement_number
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "catcher"

# Nth person placed this round -> the exact building-resource count that fires.
# 1st->5, 2nd->4, 3rd->3. The 4th/5th person never trigger (no entry).
REQUIRED_BY_PERSON = {1: 5, 2: 4, 3: 3}


def _eligible(state: GameState, idx: int) -> bool:
    sid = state.pending_stack[-1].space_id
    if sid not in BUILDING_RESOURCE_ACCUMULATION_SPACES:
        return False
    # The ACTING person's ordinal (helpers.acting_placement_number — the standing-
    # worker ledger's number at this space): the just-minted number at an ordinary
    # placement, the moved worker's PRESERVED number at a relocated use (Straw
    # Hat's end-of-work move onto an accumulation space — ruling 79 item 4:
    # a relocation counts as placing that person).
    n_placed = acting_placement_number(state, idx)
    required = REQUIRED_BY_PERSON.get(n_placed)
    if required is None:                       # 4th / 5th person never fires
        return False
    acc = get_space(state.board, sid).accumulated
    count = acc.wood + acc.clay + acc.reed + acc.stone
    return count == required                    # EXACTLY-equal, not at-least


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES)
