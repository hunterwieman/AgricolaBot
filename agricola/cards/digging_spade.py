"""Digging Spade (minor improvement, B51; Bubulcus Expansion; cost 1 wood,
prereq play in round 7 or later).

Card text: "Each time you use a clay accumulation space, you also get a number
of food equal to the number of wild boar in your farmyard." No printed VP.

Category 3 (action-space hook, automatic income) on the atomic Clay Pit space.
"a clay accumulation space" resolves to clay_pit ONLY — it is the sole clay entry
in BUILDING_ACCUMULATION_RATES (day_laborer is a food space, not a clay space).
The granted food equals the OWNER's own wild-boar count (animals.boar); this is a
pure goods grant, never an animal grant, so there is no accommodation concern (and
no effect when the player has 0 boar — a harmless +0).

The "each time you use" wording carries no "immediately after" qualifier, so per
the trigger-timing ruling it fires in the before_action_space phase. (The boar
count is unaffected by taking the clay, so the amount is identical either way; the
before phase is used to honor the ruling, not for convenience.) It is a
downside-free pure-goods grant, so it is a register_auto (mandatory, choice-free),
never surfaced as an optional FireTrigger. clay_pit is an atomic accumulation
space, so register_action_space_hook is required to host a frame for the
before-phase to fire on. The round-7-or-later prerequisite is a play-time
HAVE-check on state.round_number (prereq, not a cost).
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "digging_spade"
SPACES = frozenset({"clay_pit"})


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite: play in round 7 or later (a play-time HAVE-check on the
    current round, not a cost)."""
    return state.round_number >= 7


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    boar = state.players[idx].animals.boar
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=boar))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
