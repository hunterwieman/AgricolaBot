"""Wood Collector (occupation, C118; Consul Dirigens Expansion; players 1+).

Card text: "Place 1 wood on each of the next 5 round spaces. At the start of these
rounds, you get the wood."

Category 8 (deferred goods on round spaces). The on-play effect schedules 1 wood
onto each of the next 5 round spaces — rounds R+1..R+5 (1-indexed, R = the round in
which the card is played) — of `future_resources`, collected automatically at the
START of each of those rounds (in `engine._complete_preparation`). Unlike Estate
Worker (one different good per round) this is the SAME good (1 wood) on all five.

`schedule_resources` uses 1-indexed rounds and silently drops any round > 14, so a
late play places only on the next round spaces that still exist ("each of the next 5
round spaces"). Goods (unlike effect cards) need no start_of_round trigger — they are
collected directly from `future_resources`, so there is nothing to register beyond
the occupation's on-play schedule.

Played via Lessons; the on-play schedule IS the effect. No cost / prereq / vps /
passing — all defaults. (Distinct from "Firewood Collector" [A119] and "Brushwood
Collector" [B145]; do not conflate.)
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "wood_collector"


def _on_play(state: GameState, idx: int) -> GameState:
    # "Each of the next 5 round spaces" = rounds R+1..R+5 (1-indexed);
    # schedule_resources clamps any round > 14 away (only the remaining ones).
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 6), Resources(wood=1))


register_occupation(CARD_ID, _on_play)
