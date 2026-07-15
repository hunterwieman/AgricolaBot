"""Granary (minor improvement, C65; Consul Dirigens Expansion; Crop Provider).

Card text (verbatim): "Place 1 grain each on the remaining spaces for rounds 8,
10, and 12. At the start of these rounds, you get the grain."
Cost: 3 Wood / 3 Clay (an ALTERNATIVE cost — pay ONE). Prerequisite: none.
VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape but onto ABSOLUTE round spaces:
on play, schedule 1 grain onto rounds 8, 10, and 12 of `future_resources`
(slots 7, 9, 11), collected at the start of each of those rounds by
`engine._complete_preparation`. Unlike Pond Hut / Barn Cats (which place onto the
NEXT N rounds, R+1..R+N), Granary names fixed board rounds.

"the REMAINING spaces for rounds 8, 10, and 12" is handled for free by the
schedule model: `future_resources` slots are collected exactly once, when their
round is entered, and rounds advance monotonically — so if Granary is played after
round 8 has already begun, writing slot 7 is a harmless dead write (round 8 is
never re-entered, so that grain is never collected), leaving only the still-future
rounds among {8, 10, 12}. `schedule_resources` also clamps to the 1..14 range.

Cost "3 Wood / 3 Clay" is an ALTERNATIVE ("/") cost: pay EITHER 3 wood OR 3 clay,
never both (the slash-cost rule — CARD_AUTHORING_GUIDE.md §2). The printed 3-wood
cost is `cost`; the 3-clay alternative rides on `alt_costs`. The reward does NOT
depend on which alternative is paid (both simply grant the grain schedule), so no
`cost_labels` are needed — contrast Grain Depot B65, whose reward IS coupled to the
paid resource.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "granary"

# The board rounds named on the card (absolute, not relative to the play round).
_ROUNDS = (8, 10, 12)


def _on_play(state: GameState, idx: int) -> GameState:
    return schedule_resources(state, idx, _ROUNDS, Resources(grain=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=3)),
    alt_costs=(Cost(resources=Resources(clay=3)),),
    vps=1,
    on_play=_on_play,
)
