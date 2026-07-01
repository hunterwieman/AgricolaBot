"""Education Bonus (minor improvement, D42; Consul Dirigens Expansion; cost 1 food).

Card text: "After you play your 1st/2nd/3rd/4th/5th/6th occupation this game, you
immediately get 1 grain/clay/reed/stone/vegetable/field (not retroactively)."
Prerequisite: "2 Improvements". Printed VP: none (0).

Category 5 (play-occupation hook). The rewards are keyed to the GAME-TOTAL
occupation count, one reward per occupation play (while this card is owned):

  1st occupation -> 1 grain      2nd -> 1 clay       3rd -> 1 reed
  4th occupation -> 1 stone      5th -> 1 veg        6th -> 1 field (a free plow)

- **Occupations 1-5** grant a pure good. A pure-goods gain with no downside is a
  MANDATORY, choice-free effect -> `register_auto("after_play_occupation", ...)`.
  The single auto dispatches on the lifetime occupation count `len(p.occupations)`
  (the occupation is already in `p.occupations` when the after-phase autos fire —
  resolution.py `_execute_play_occupation` adds it before `_enter_after_phase`, so
  `len` is the 1-based index directly, no +1).
- **Occupation 6** grants "1 field" = a free field tile = a plow. A granted
  sub-action is the player's CHOICE (declinable) -> an OPTIONAL trigger
  (`register`, not `register_auto`) whose apply_fn pushes the existing PendingPlow
  primitive. Eligibility gates on a plow actually being possible (`_can_plow`), so
  it never grants a dead-end. Mirrors Assistant Tiller (an after-phase grant that
  pushes PendingPlow); the FireTrigger surfaces in the play-occupation host's
  after-phase, and the engine records `education_bonus` in `triggers_resolved` when
  it fires (so it offers at most once per occupation play).

"Not retroactively": the hooks fire only on the ACT of playing an occupation while
this card is owned, so occupations played before the card was acquired never grant
anything (they do not re-fire). The reward is still keyed to the lifetime total —
playing this card after two occupations, then playing the third, grants the THIRD
reward (reed), not the first.

See CARD_IMPLEMENTATION_PLAN.md Category 5 / CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_auto
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "education_bonus"

# Reward good per 1-based occupation index (1..5). The 6th grant is a field (plow),
# handled by the optional trigger below, not this table.
_GOOD_BY_INDEX: dict[int, Resources] = {
    1: Resources(grain=1),
    2: Resources(clay=1),
    3: Resources(reed=1),
    4: Resources(stone=1),
    5: Resources(veg=1),
}


def _prereq(state: GameState, idx: int) -> bool:
    """At least 2 improvements: minor improvements PLUS owned majors.

    Majors live on ``state.board.major_improvement_owners`` (a per-slot owner idx),
    not on ``PlayerState`` — mirrors Food Basket's improvements count.
    """
    p = state.players[idx]
    n_minor = len(p.minor_improvements)
    n_major = sum(1 for o in state.board.major_improvement_owners if o == idx)
    return (n_minor + n_major) >= 2


# --- Occupations 1-5: mandatory good grant (automatic effect) ---------------

def _auto_eligible(state: GameState, idx: int) -> bool:
    """Fires for occupation plays 1..5 (a tabled good reward exists)."""
    return len(state.players[idx].occupations) in _GOOD_BY_INDEX


def _auto_apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    gain = _GOOD_BY_INDEX[len(p.occupations)]
    p = fast_replace(p, resources=p.resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Occupation 6: optional field grant (declinable plow trigger) -----------

def _plow_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and len(state.players[idx].occupations) == 6
            and _can_plow(state.players[idx]))


def _plow_apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:education_bonus"))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    prereq=_prereq,
)
register_auto("after_play_occupation", CARD_ID, _auto_eligible, _auto_apply)
register("after_play_occupation", CARD_ID, _plow_eligible, _plow_apply)
