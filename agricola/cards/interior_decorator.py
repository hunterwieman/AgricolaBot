"""Interior Decorator (occupation, D111; Consul Dirigens Expansion; players 1+).

Card text: "Each time you renovate, place 1 food on each of the next 6 round
spaces. At the start of these rounds, you get the food."

Category 8 (deferred goods on round spaces) hung off the renovate sub-action.
"Each time you [renovate]" is the before-window idiom and the reward is flat
(it reads nothing the renovate produced), so this is a mandatory, choice-free
automatic effect on `before_renovate` — the sub-action event is uniform across
every renovate source (House Redevelopment, Farm Redevelopment, card-granted
renovates), so one registration covers them all. The effect fires at the
`PendingRenovate` push; the push is gated on the renovate being legal and
affordable, so a fire always corresponds to a renovate that happens.

The "next 6 round spaces" from current round R are rounds R+1..R+6 (the same
"next N" reading as Lumberjack: the current round's space is behind us, the
next one is R+1). `schedule_resources` writes 1 food into each of those slots
(1-indexed round N -> slot N-1) and silently drops rounds past 14, so a
late-game renovate places food on only the remaining round spaces. Repeated
renovates stack additively on overlapping slots. The scheduled food is
collected automatically at the start of each scheduled round (the preparation
ladder's collection step pays out `future_resources` when the round is
entered).

Played via Lessons; its on-play is a no-op (the card only watches renovates).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "interior_decorator"


def _schedule_food(state: GameState, idx: int) -> GameState:
    """before_renovate: 1 food on each of the next 6 round spaces (R+1..R+6,
    rounds past 14 dropped by schedule_resources). Additive with any earlier
    schedule. register_auto fires only for the owner, so no ownership guard."""
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 7), Resources(food=1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_renovate", CARD_ID, lambda state, idx: True, _schedule_food)
