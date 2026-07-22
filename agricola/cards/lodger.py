"""Lodger (occupation, A127; Artifex; players 3+).

Card text (verbatim): "This card provides room for one person, but only until the
returning home phase of round 9. If, by then, there is no room elsewhere for that
person, remove it from play."
Clarifications: "If you remove it from play, it can never grow back.  This card does
not count as a room."

Two coupled effects:

1. A PEOPLE-capacity bonus of +1 (housing-capacity registry) that is active ONLY
   through the returning-home phase of round 9 (`round_number <= 9`). After round 9 it
   provides nothing — but a person already grown into that slot is NOT evicted by the
   capacity dropping (the memoryless rule: a capacity decrease never removes a person);
   the removal is the explicit, one-time event below.

2. The eviction: an automatic effect on the round-end `returning_home` window, firing
   in round 9 only. "If there is no room elsewhere for that person" means the family
   would be over capacity WITHOUT Lodger's slot — i.e. `people_total > capacity sans
   Lodger`. When so, one person is removed from play: `people_total -= 1`, and the
   meeple is removed from the GAME (workers_in_supply is NOT replenished), so the
   reachable family size drops permanently — "can never grow back". Fires before the
   round-end reset (`returning_home` precedes `__reset__`), so the reset then returns
   the reduced family home. Latched in `fired_once` so it can never double-evict.

Players 3+, so it is registered but never dealt in the 2-player game (tests inject it).
No on-play effect.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_housing_capacity
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "lodger"


def _capacity_bonus(state: GameState, idx: int) -> int:
    """+1 room for one person, active only through the returning-home phase of round 9."""
    return 1 if state.round_number <= 9 else 0


def _relies_on_lodger(state: GameState, idx: int) -> bool:
    """True when the Lodger-housed person has no room elsewhere: the family exceeds the
    housing capacity computed WITHOUT Lodger's own +1 (rooms + any other capacity card)."""
    from agricola.legality import _housing_capacity
    p = state.players[idx]
    cap_sans_lodger = _housing_capacity(state, idx) - _capacity_bonus(state, idx)
    return p.people_total > cap_sans_lodger


def _evict_eligible(state: GameState, idx: int) -> bool:
    return (state.round_number == 9
            and CARD_ID not in state.players[idx].fired_once
            and _relies_on_lodger(state, idx))


def _evict(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    # The over-capacity person Lodger houses is removed. If the family currently
    # includes a newborn, that newborn is the removed one: a newborn present at round
    # 9's returning-home was necessarily grown THIS round, and a growth that put the
    # family over its room count is exactly the overflow Lodger was housing. Removing it
    # (newborns -= 1) means it is not fed at round 9's harvest, which follows. (Assumption
    # flagged to the user: an adult-overflow-with-a-roomed-newborn only arises from a
    # mid-round capacity *decrease* under a second capacity card — a contrived 3+ case.)
    newborns = p.newborns - 1 if p.newborns > 0 else p.newborns
    p = fast_replace(
        p,
        people_total=p.people_total - 1,     # remove the Lodger person from play
        newborns=newborns,
        fired_once=p.fired_once | {CARD_ID},  # one-shot: never double-evict
        # workers_in_supply is deliberately NOT incremented: the meeple leaves the GAME,
        # not the supply, so total meeples drops and it "can never grow back".
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _on_play(state: GameState, idx: int) -> GameState:
    """No on-play effect — the effects are the passive capacity bonus + the round-9 auto."""
    return state


register_occupation(CARD_ID, _on_play)
register_housing_capacity(CARD_ID, _capacity_bonus)
register_auto("returning_home", CARD_ID, _evict_eligible, _evict)
