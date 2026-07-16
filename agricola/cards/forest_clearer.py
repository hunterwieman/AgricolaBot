"""Forest Clearer (occupation, B162; Bubulcus Expansion; players 4+).

Card text: "Each time you obtain exactly 2/3/4 wood from a wood accumulation space, you
get 1 additional wood and 1/0/1 food."
Clarification: "This card's effect triggers before deciding to leave wood on the action
space (e.g. with Basket A056)."

Category 3 (action-space hook, automatic income). A mandatory, choice-free bonus → an
automatic effect (`register_auto`) on the AFTER window: the wood the acting player actually
obtained from the space (the host frame's `taken` — the Resources delta stamped across the
take at Proceed) is the amount you obtain. Firing in the after-window still lands ahead of
Basket-style goods-return after-triggers, honoring the clarification ("before deciding to
leave wood on the action space"). Banded by that amount: 2→+1 wood +1 food, 3→+1 wood
(+0 food), 4→+1 wood +1 food; nothing outside {2,3,4}.

The only wood accumulation space in the 2-player game is Forest (Copse / Grove are
3–4-player board-extension spaces, never on the 2-player board — the Wood Cutter note).
Forest is atomic, so `register_action_space_hook` hosts it when this card is owned.

This is a [4] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "forest_clearer"
SPACES = frozenset({"forest"})

# wood obtained -> the bonus ("1 additional wood and 1/0/1 food" for "2/3/4").
_BONUS = {
    2: Resources(wood=1, food=1),
    3: Resources(wood=1, food=0),
    4: Resources(wood=1, food=1),
}


def _wood_obtained(state: GameState) -> int:
    """The wood the acting player obtained from the hosted wood space — the host
    frame's `taken` (the Resources delta stamped across the take at Proceed)."""
    return state.pending_stack[-1].taken.wood


def _eligible(state: GameState, idx: int) -> bool:
    return (getattr(state.pending_stack[-1], "space_id", None) in SPACES
            and _wood_obtained(state) in _BONUS)


def _apply(state: GameState, idx: int) -> GameState:
    bonus = _BONUS[_wood_obtained(state)]
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
