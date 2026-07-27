"""Telegram (minor improvement, A22; Artifex).

Card text (verbatim): "Add 1 to the current round for each fence in your supply and mark
the corresponding round space. In that round only, you can place a person from your
supply."
Clarification: "The person is returned to your supply in the 'returning home' phase."
Cost: 2 Food. Prerequisite: At Least 1 Fence in Supply. 1 VP.

A **supply-loaner** card (the mechanism: `TEMP_WORKER_DESIGN.md`,
CARD_ENGINE_IMPLEMENTATION.md §1's 2026-07-24 entry): a meeple from SUPPLY works one round
without joining the family, then returns to supply — never fed, never scored — and while
it is out it occupies a physical meeple, so Family Growth to a 5th person is blocked.

Two clauses:

1. **The scheduling clause.** `target round = current round + fences in supply`. "Mark the
   corresponding round space" is a physical REMINDER of which round the loaner is
   available in — no meeple and no game state sit on that space (contrast Work Permit,
   which really does park a person there) — so the target round is recorded in this card's
   CardStore. With the prerequisite guaranteeing at least one fence in supply, the target
   is always a LATER round, never the current one. A target past round 14 simply never
   arrives; the card is then only its 1 VP. Note the incentive runs the "wrong" way at
   first glance: FEWER fences left in supply (i.e. more fences already built) means a
   SOONER loaner.
2. **The loaner clause.** "In that round only" — one round, and within it the offer is
   surfaced at the **last usable moment**: once the player has placed every household
   worker (`people_home == 0`). That is a deliberate, loss-less narrowing rather than
   offering at every turn — taking a loaner never yields a placement any sooner (the
   player still places one meeple per turn), so accepting early gains nothing and only
   forecloses the family-growth option earlier. Deferring therefore weakly dominates, and
   every earlier offer would be a dominated choice inflating the action set.

The engine grants the turn: `engine._can_act` counts an outstanding offer as "this player
may yet place", so a player out of household workers is neither skipped by the alternation
nor cut off by the work phase ending.

Because the loaner is drawn from supply at the moment it is taken, a player who has grown
to 5 people by that round simply cannot use the effect — `workers_in_supply` is 0 and the
offer is not made. That falls out of the shared mechanism, not from anything here.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_card_choice_resolver
from agricola.cards.turn_offers import register_turn_start_offer
from agricola.helpers import activate_temp_worker
from agricola.pending import pop
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "telegram"

TAKE = "take"
DECLINE = "decline"
_OPTIONS = (TAKE, DECLINE)

_LAST_ROUND = 14


def _prereq(state: GameState, idx: int) -> bool:
    """"At Least 1 Fence in Supply" — a have-check on the supply pile, not a cost."""
    return state.players[idx].fences_in_supply >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Record the round the loaner becomes available: current + fences in supply."""
    p = state.players[idx]
    target = state.round_number + p.fences_in_supply
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, target))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _offer_eligible(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    if CARD_ID not in p.minor_improvements:
        return False
    if CARD_ID in p.used_this_round:        # answered already (liveness — see below)
        return False
    if p.card_state.get(CARD_ID) != state.round_number:   # "in that round only"
        return False
    if p.people_home != 0:                  # the last usable moment (see the docstring)
        return False
    return p.workers_in_supply > 0          # a meeple to loan


def _resolve(state: GameState, idx: int, chosen) -> GameState:
    """Apply the choice and latch the offer closed.

    The latch is set on BOTH options. That is a LIVENESS requirement, not a "once per
    round" nicety: an outstanding offer keeps the work phase open (`engine._can_act`), and
    eligibility is re-tested at every decision boundary — so an offer that survived being
    declined would be re-pushed forever and the round could never end.
    """
    p = state.players[idx]
    state = fast_replace(state, players=tuple(
        fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
        if i == idx else state.players[i]
        for i in range(len(state.players))))
    if chosen == TAKE:
        state = activate_temp_worker(state, idx)
    return pop(state)   # resolver owns the PendingCardChoice frame


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    prereq=_prereq,
    vps=1,
    on_play=_on_play,
)
register_turn_start_offer(CARD_ID, _offer_eligible, _OPTIONS)
register_card_choice_resolver(CARD_ID, _resolve)
