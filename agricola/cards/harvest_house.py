"""Harvest House (minor improvement, B71; Bubulcus Expansion; Crop Provider).

Card text: "When you play this card, if the number of completed harvests is equal
to the number of occupations you played, you immediately get 1 food, 1 grain,
and 1 vegetable."

Cost: 1 wood, 1 clay, 1 reed. VPs: 2. No prerequisite, not passing.

Category 2 (on-play one-shot), conditional. The grant fires only when the
equality holds at play time; otherwise the card is still played (and kept, for
its 2 VPs) with no immediate goods.

Two subtleties drive the implementation:

  - "Number of completed harvests" — the harvest of round R resolves at the
    WORK -> PREPARATION boundary, AFTER round R's worker placements. A card
    played during the WORK phase of round R has therefore NOT yet experienced
    harvest R. So the count is the number of HARVEST_ROUNDS strictly LESS than
    the current `state.round_number` (`< `, not `<=`). This matches
    `dutch_windmill`'s `_POST_HARVEST_ROUNDS = {5, 8, 10, 12, 14}` precedent:
    harvest 4 has completed once round 5 is reached.

  - "Number of occupations you played" — `len(p.occupations)`, the played
    frozenset (exactly what `specs.prereq_met` reads for min/max_occupations).
    This minor is not an occupation, so it never affects the count.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "harvest_house"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    completed_harvests = sum(1 for h in HARVEST_ROUNDS if h < state.round_number)
    n_occupations = len(p.occupations)
    if completed_harvests != n_occupations:
        return state  # condition unmet: card played (kept for VPs) with no goods
    p = fast_replace(p, resources=p.resources + Resources(food=1, grain=1, veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=1, reed=1)),
    vps=2,
    on_play=_on_play,
)
