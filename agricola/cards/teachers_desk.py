"""Teacher's Desk (minor improvement, C28; Corbarius Expansion).

Card text: "Each time you use the 'Major Improvement' or 'House Redevelopment'
action space, you can also play 1 occupation at an occupation cost of 1 food."
Cost: 1 Wood. Prerequisite: 1 Occupation. No VPs. Not passing.

An OPTIONAL `before_action_space` trigger on the two improvement-building action
spaces. The text reads "each time you use the ... action space" with NO "after" /
"immediately after" wording, so it rides `before_action_space` per the default
"each time you use [space]" = before ruling (the opposite of Forestry Studies,
whose "after you use" forces it onto `after_action_space`). Firing it before the
space's own work is done is harmless here — the occupation play is an independent
side benefit ("you can also play 1 occupation"), not a modification of the major /
renovate the space does.

WHICH SPACES: both the Major Improvement space and the House Redevelopment space.
- "major_improvement" is hosted by a PendingSubActionSpace (a Delegating host); its
  before-phase enumerator (`_enumerate_pending_subactionspace`) surfaces
  before_action_space triggers.
- "house_redevelopment" is hosted by a PendingHouseRedevelopment (a Proceed-host);
  its before-phase enumerator surfaces before_action_space triggers too.
Both spaces are NON-ATOMIC and already hosted, so NO `register_action_space_hook` is
needed — a single `register("before_action_space", ...)` covers both, gated on the
host frame's `space_id`.

OPTIONALITY: "you can also play" → an OPTIONAL trigger (`register`, not
`register_auto`). The decline path is simply NOT firing — the player picks the host's
mandatory ChooseSubAction / Proceed instead (no SkipTrigger; optionality lives at the
parent host). Because firing pushes a PendingPlayOccupation whose own enumerator offers
a CommitPlayOccupation per playable hand occupation (no decline once pushed — the
Scholar / Forestry Studies precedent), eligibility gates on a playable hand occupation
actually existing AND the 1-food being affordable, so a fire is never a dead end.

EFFECT (`_apply`): push PendingPlayOccupation with `cost=Resources(food=1)` — the flat
1-food occupation cost (NOT the Lessons occupation-count ramp). `_execute_play_occupation`
reads that cost off the frame and debits 1 food (raising any shortfall via the
liquidation guard). No on-play effect, no VPs, not passing.

"Each time" = once per use of the space, enforced by `CARD_ID not in triggers_resolved`
(NOT used_this_round — it may fire on every use of either space). The food affordability
is checked liquidation-aware via `_payable_occupation`, exactly as Scholar's flat-1-food
occupation route.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _payable_occupation, playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "teachers_desk"

# The two action-space hosts this card fires on (by the host frame's `space_id`).
_SPACES = frozenset({"major_improvement", "house_redevelopment"})

_OCC_COST = Resources(food=1)   # flat 1-food occupation cost (not the Lessons ramp)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # `triggers_resolved` is the host frame's already-fired set; once-per-use.
    if CARD_ID in triggers_resolved:
        return False
    if state.pending_stack[-1].space_id not in _SPACES:
        return False
    p = state.players[idx]
    # Never a dead-end fire: must have a playable hand occupation AND be able to pay the
    # flat 1-food cost (liquidation-aware — the food may be raised from crops/animals,
    # mirroring `_execute_play_occupation`'s food-shortfall guard).
    return bool(playable_occupations(state, idx)) and _payable_occupation(
        state, idx, p, _OCC_COST
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Push a 1-food occupation play; its enumerator offers the playable occupations."""
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", cost=_OCC_COST))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), min_occupations=1)
register("before_action_space", CARD_ID, _eligible, _apply)
