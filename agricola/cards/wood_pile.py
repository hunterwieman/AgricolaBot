"""Wood Pile (minor improvement, B4; Bubulcus Expansion; traveling).

Card text: "You immediately get a number of wood equal to the number of people
you have on accumulation spaces."

No cost, no prerequisite, no printed VPs. It is a TRAVELING (passing) card —
after the immediate effect it is passed to the opponent rather than kept.

Category 2 (on-play one-shot) + passing. "Accumulation spaces" are exactly the
nine spaces in ``helpers.accumulation_spaces(state)`` (the 5 building-resource spaces
— forest / clay_pit / reed_bank / western_quarry / eastern_quarry — and 4
food/animal spaces — fishing / sheep_market / pig_market / cattle_market). In the
card game meeting_place accumulates nothing, so it is excluded (user ruling
2026-07-02). The count is of the OWNER's own people currently on those
spaces: ``ActionSpaceState.workers[idx]`` summed over those space ids. The
improvement space the playing worker sits on is not an accumulation space, so
the worker that plays Wood Pile is correctly not self-counted.
"""
from __future__ import annotations

from agricola.helpers import accumulation_spaces
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "wood_pile"


def _on_play(state: GameState, idx: int) -> GameState:
    n = sum(get_space(state.board, sid).workers[idx]
            for sid in accumulation_spaces(state))
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(),
    passing_left=True,
    on_play=_on_play,
)
