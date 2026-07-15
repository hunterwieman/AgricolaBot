"""Fish Farmer (occupation, Dulcinaria D110; players 1+).

Card text: "Each time there is 1/2/3+ food on the \"Fishing\" accumulation
space, you get an additional 2 food on the \"Reed Bank\"/ \"Clay Pit\"/
\"Forest\" accumulation spaces." (Official errata applied in the data file:
"Grove" should be "Forest".)

USER RULING (2026-07-14): the correct reading is a USE-BONUS — "When the
player goes on the relevant Reed Bank/Clay Pit/Forest space, they get 2
additional food from Fish Farmer." The CARD provides the food (from the
general supply); no food is ever physically placed on those spaces — which is
also why this bonus deliberately does NOT trigger Kindling Gatherer ("each
time you get food from an action space" — the food is from the card, not the
space). No interaction code needed.

Mechanically: a mandatory, choice-free automatic effect on the BEFORE window
of the three spaces (register_auto on `before_action_space`), with a strict
slash-correlation on Fishing's CURRENT accumulated food at the moment of use:

- using Reed Bank while Fishing holds EXACTLY 1 food  → +2 food
- using Clay Pit  while Fishing holds EXACTLY 2 food  → +2 food
- using Forest    while Fishing holds 3 OR MORE food  → +2 food

No payout otherwise (e.g. Reed Bank while Fishing holds 3 pays nothing), and
using Fishing itself never pays. All three spaces are atomic, so they must be
hosted via `register_action_space_hook`. Played via Lessons; on-play is a
no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "fish_farmer"

# space used -> predicate on Fishing's accumulated food at the moment of use.
_FISHING_CONDITIONS = {
    "reed_bank": lambda n: n == 1,
    "clay_pit": lambda n: n == 2,
    "forest": lambda n: n >= 3,
}

SPACES = frozenset(_FISHING_CONDITIONS)


def _eligible(state: GameState, idx: int) -> bool:
    cond = _FISHING_CONDITIONS.get(state.pending_stack[-1].space_id)
    if cond is None:
        return False
    return cond(get_space(state.board, "fishing").accumulated_amount)


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
