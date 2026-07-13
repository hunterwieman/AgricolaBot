"""Pigswill (minor improvement, D83; Dulcinaria Expansion; players -).

Card text: "Each time you use the "Fencing" action space, you also get 1 wild
boar." Cost: 2 Food / 1 Grain (an ALTERNATIVE "/" cost — pay 2 food OR 1 grain,
never both). No prerequisite, no printed VPs. Not passing.

Category 3 (action-space hook, automatic income) on the Fencing space. "Each
time you use [space]" with no "after" qualifier fires in the BEFORE phase per
the Trigger-Timing ruling — and here the phase is observable, not neutral: the
boar lands BEFORE any fence is built, so a player already at animal capacity
must resolve the accommodation barrier's keep-which choice (possibly cooking or
releasing an animal) before the new pasture exists to house the boar. The user
ruled this explicitly (2026-07-13): "effect is before. Too bad for players who
were hoping to store the boar in the newly built fences."

"You also get" is mandatory and choice-free, so it is a ``register_auto`` —
never surfaced as an optional FireTrigger. The boar goes through
``helpers.grant_animals`` (the decision-free-grant choke point), so the
accommodation barrier surfaces the keep-which choice on overflow rather than
silently inflating the count. Fencing is a Delegating host
(``PendingSubActionSpace``, always pushed — ``_initiate_fencing``), so no
``register_action_space_hook`` entry is needed; eligibility just filters on the
host frame's ``space_id``. Only the OWNER's own use fires (default
``any_player=False`` routes the auto to the acting player). A Build Fences
action reached from any other space (Farm Redevelopment's optional step, a
card-granted build) is NOT "using the 'Fencing' action space" and never fires.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "pigswill"


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id == "fencing"


def _apply(state: GameState, idx: int) -> GameState:
    """Gain 1 wild boar (via grant_animals — barrier handles overflow)."""
    return grant_animals(state, idx, Animals(boar=1))


# Cost "2 Food / 1 Grain" — an ALTERNATIVE ("/") cost: the printed 2-food cost is
# `cost`; the 1-grain alternative rides `alt_costs`. The play path enumerates one
# CommitPlayMinor per affordable alternative (the Chophouse pattern).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    alt_costs=(Cost(resources=Resources(grain=1)),),
)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
