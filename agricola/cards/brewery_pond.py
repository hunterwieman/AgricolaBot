"""Brewery Pond (minor improvement, B40; Bubulcus Expansion; players -).

Card text: "Each time you use the 'Fishing' or 'Reed Bank' accumulation space,
you also get 1 grain and 1 wood."
Cost: none. Prerequisite: 2 Occupations. VPs: -1. Not passing.

Category 3 (action-space hook, automatic income) on TWO atomic accumulation
spaces. "Each time you use [space]" → the `before_action_space` event on both the
`fishing` and `reed_bank` spaces, per the Trigger-Timing ruling (a bare "each time
you use [space]" fires BEFORE the space's own effect — the same phase as
Wood Cutter / Geologist / Herring Pot). The +1 grain +1 wood is independent of
fishing's catch / reed_bank's reed pickup, so the end state would coincide either
way — but the phase is fixed by the ruling, not by convenience.

A mandatory, choice-free pure-goods grant → an automatic effect
(`register_auto`), never a FireTrigger. Eligibility reads the host frame's
`space_id` so one effect serves both spaces. The host frame is pushed on the
placement (`register_action_space_hook` over both spaces). Played via an
improvement space; the play itself is a no-op (the per-use hook is the effect), so
on_play is the default. The "2 Occupations" prerequisite is a `min_occupations=2`
have-check (NOT a cost); the -1 VP flows through `MINORS[cid].vps` in scoring, so
no `register_scoring` is needed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "brewery_pond"
SPACES = frozenset({"fishing", "reed_bank"})


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space uniformly via
    # the host frame's `space_id` so one effect serves both Fishing and Reed Bank.
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1, wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, min_occupations=2, vps=-1)   # cost=Cost() default (no cost)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
