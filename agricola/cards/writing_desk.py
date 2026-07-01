"""Writing Desk (minor improvement, D28; Consul Dirigens Expansion).

Card text: "Each time you use a 'Lessons' action space, you can play 1 additional
occupation for an occupation cost of 2 food."
Cost: 1 Wood. Prerequisite: 2 Occupations. 1 VP. Not passing.

An OPTIONAL `before_action_space` trigger on the Lessons action space. Lessons is a
NON-ATOMIC space already hosted by the Delegating PendingSubActionSpace host (its
single mandatory sub-action is "play one occupation"), so — unlike Forestry Studies on
the atomic Forest space — NO `register_action_space_hook` is needed: the host already
exposes the before/after action_space lifecycle.

TIMING (`before_action_space`): "each time you use [space]" maps to the before-window,
and taking the mandatory Lessons play CLOSES that window (implicitly declining this
grant). So the additional occupation must be played BEFORE the mandatory one — it is the
FIRST occupation played this use, at the flat 2-food cost. This ordering is load-bearing,
not cosmetic: Paper Maker subsidizes "each occupation after this one," so a player who
played Paper Maker as the mandatory occupation could otherwise fire this grant afterward
and have Paper Maker pay its 2 food. Forcing the grant first (Paper Maker not yet in play)
blocks that — the 2 food must come from supply/liquidation. (An earlier `after_action_space`
implementation got this wrong; see CARD_AUTHORING_GUIDE.md.)

COST (flat 2 food): the additional occupation costs a FLAT 2 food, NOT the Lessons
occupation-cost ramp. The 2-food cost rides on the pushed `PendingPlayOccupation.cost`;
`_execute_play_occupation` debits it (its food-shortfall guard liquidates crops/animals
if the player is short).

OPTIONALITY: "you can play" → an OPTIONAL FireTrigger (`register`, not `register_auto`).
Declining = not firing (just take the mandatory play). Because firing pushes a
PendingPlayOccupation whose own enumerator offers a CommitPlayOccupation per playable hand
occupation (no decline once pushed — the Scholar/Forestry precedent), eligibility gates on
a playable hand occupation existing AND the 2-food cost being payable (liquidation-aware),
to never offer a dead-end fire.

STRANDING GUARD: because this is an enforce-first before-trigger, the grant plays one
occupation before the mandatory Lessons play, which cannot be declined. So eligibility
requires at least TWO playable occupations (one for the grant, one left for the mandatory
play) — else firing would strand the mandatory play (CARD_AUTHORING_GUIDE.md).

"Each time" = once per Lessons use, enforced by `CARD_ID not in triggers_resolved` (the
per-host-frame fired-set, which resets with each new Lessons use — NOT `used_this_round`,
since the grant may fire on every Lessons use across the game). No on-play effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _payable_occupation, playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "writing_desk"

# The action space this card fires on.
_LESSONS = "lessons"

# Flat occupation cost for the ADDITIONAL play (not the Lessons ramp).
_OCC_COST = Resources(food=2)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per Lessons use
        return False
    top = state.pending_stack[-1]
    # Only the Lessons action-space host. The host exposes `space_id` via its
    # "space:<id>" provenance; guard on the attribute so non-space frames are skipped.
    if getattr(top, "space_id", None) != _LESSONS:
        return False
    p = state.players[idx]
    # Enforce-first before-trigger: the grant plays one occupation BEFORE the mandatory
    # (non-declinable) Lessons play, so a SECOND playable occupation must remain for that
    # play — require >= 2 playable occupations (else firing strands the mandatory play).
    # Plus the flat 2-food cost must be payable (liquidation-aware) — never a dead-end fire.
    return (len(playable_occupations(state, idx)) >= 2
            and _payable_occupation(state, idx, p, _OCC_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Push an additional occupation play at a flat 2-food cost.

    No goods are debited here — `_execute_play_occupation` reads the frame's `cost` and
    debits the 2 food (raising the shortfall via liquidation if short)."""
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", cost=_OCC_COST))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),   # 1 wood (NOT the "2 Occupations" prereq)
    min_occupations=2,                         # prereq: 2 occupations played
    vps=1,
)
register("before_action_space", CARD_ID, _eligible, _apply)
