"""Young Animal Market (minor improvement, A9; Base Revised; cost 1 sheep, traveling).

Card text: "You immediately get 1 cattle. (Effectively, you are exchanging 1 sheep
for 1 cattle.)" No prerequisite, no printed VPs; a TRAVELING (passing) card.

Category 2 (on-play one-shot) + passing — the first card with an ANIMAL cost
(1 sheep, debited by _execute_play_minor via Cost.animals), gaining 1 cattle. The
cattle is granted via `helpers.grant_animals` (add + flag): net animal count is
unchanged (pay 1 sheep, gain 1 cattle), so it usually fits and the accommodation
barrier just clears the flag — but the barrier still guards the case where the
sheep→cattle type swap doesn't (a full sheep pasture, no cattle home), surfacing the
keep-which choice. See CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.helpers import grant_animals
from agricola.resources import Animals, Cost
from agricola.state import GameState

CARD_ID = "young_animal_market"


def _on_play(state: GameState, idx: int) -> GameState:
    return grant_animals(state, idx, Animals(cattle=1))


register_minor(CARD_ID, cost=Cost(animals=Animals(sheep=1)),
               passing_left=True, on_play=_on_play)
