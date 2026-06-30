"""Cowherd (occupation, C147; Consul Dirigens Expansion; printed players 3+).

Card text: "Each time you use the 'Cattle Market' accumulation space (introduced
in round 10 or 11), you get 1 additional cattle."

Category 3 (action-space hook, automatic income) on the non-atomic Cattle Market.
The +1 cattle is a mandatory, choiceless effect -> an automatic effect
(register_auto) on the `before_action_space` event, NOT a FireTrigger. "Each time
YOU use [a space]" fires in the BEFORE phase per the Trigger-Timing ruling and is
owner-gated (`any_player=False`).

The card is printed as a 3+ player card, but `cattle_market` exists as a stage-4
accumulation space (rounds 10-11) in this 2-player engine, so the hook maps
cleanly. Cattle Market is NON-ATOMIC: `_initiate_cattle_market` always pushes a
PendingCattleMarket host frame and fires `before_action_space` from there, so no
`register_action_space_hook` is needed (that index only gates the conditional
hosting of ATOMIC spaces).

The load-bearing detail (matching Feeding Dish A66): `_initiate_cattle_market`
stages the cattle taken from the space on the pending's `gained` field (an int,
NOT on the player) and fires `before_action_space` BEFORE CommitAccommodate moves
them onto the player through the accommodation/overflow Pareto frontier. So Cowherd
must NOT add cattle directly to the player — it bumps `gained` by 1 via
`replace_top`, so the additional cattle flows through the SAME accommodation
frontier (capacity, conversion-on-overflow) as the market's own cattle. Adding to
the player directly would bypass accommodation and is wrong.

Fires unconditionally on every Cattle Market use, even when the space is empty
(`gained == 0`): bumping 0 -> 1 is still correct ("you get 1 additional cattle").
On-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.pending import replace_top
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "cowherd"


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the acting owner ("you"). Fire whenever the active use is Cattle Market.
    return state.pending_stack[-1].space_id == "cattle_market"


def _apply(state: GameState, idx: int) -> GameState:
    # Bump the staged `gained` count by 1 so the extra cattle flows through the
    # market's accommodation/overflow frontier at CommitAccommodate — NOT directly
    # onto the player (which would bypass capacity/conversion).
    top = state.pending_stack[-1]
    return replace_top(state, fast_replace(top, gained=top.gained + 1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
