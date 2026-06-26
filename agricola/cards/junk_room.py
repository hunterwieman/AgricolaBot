"""Junk Room (minor improvement, A55; Base Revised; cost 1 wood + 1 clay).

Card text: "Each time after you build an improvement, including this one, you get
1 food." Printed 0 VP (no `vps`).

Category 5 (improvement-built hook, automatic income). An improvement is a MAJOR
or a MINOR improvement, so this rides the coarse `after_build_improvement` event
— hand-fired (it spans both kinds, so it does not follow the per-PENDING_ID
event-name rule) by BOTH `_execute_build_major` and `_execute_play_minor` right
after the improvement is built. "including this one": the fire in
`_execute_play_minor` happens after Junk Room has already been moved into the
tableau, so it owns the card when its own play fires the event → +1 food on its
own play too. A mandatory, choice-free effect → an automatic effect
(register_auto). See CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "junk_room"


def _always_eligible(state: GameState, idx: int) -> bool:
    return True


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, clay=1)))
register_auto("after_build_improvement", CARD_ID, _always_eligible, _apply)
