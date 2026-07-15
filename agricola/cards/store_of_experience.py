"""Store of Experience (minor improvement, B5; Bubulcus Expansion; traveling).

Card text: "If you have 0-4/5/6/7 occupations left in hand, you immediately get 1
stone/reed/clay/wood."

No cost, no prerequisite, no printed VPs; a TRAVELING (passing) card — after the
immediate effect it passes to the opponent rather than being kept.

Category 2 (on-play one-shot) + passing. The positional slash-list is keyed on
how many occupation cards remain in the DECIDER's OWN hand (`hand_occupations`),
at the moment of play (Store of Experience is a MINOR, so it never sits in
`hand_occupations` and never counts itself):

    0-4 occupations left -> 1 stone
    5   occupations left -> 1 reed
    6   occupations left -> 1 clay
    7   occupations left -> 1 wood

(A hand can hold at most 7 occupations — the dealt hand — so the bands are
exhaustive; the 0-4 band is the catch-all low end.) No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "store_of_experience"


def _reward(n_occ_in_hand: int) -> Resources:
    """The single-resource reward for `n_occ_in_hand` occupations left in hand."""
    if n_occ_in_hand >= 7:
        return Resources(wood=1)
    if n_occ_in_hand == 6:
        return Resources(clay=1)
    if n_occ_in_hand == 5:
        return Resources(reed=1)
    return Resources(stone=1)   # 0-4 (the low band)


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _reward(len(p.hand_occupations)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    passing_left=True,
    on_play=_on_play,
)
