"""Heirloom (minor improvement, E29; Ephipparius Expansion; printed 2 VP).

Card text: "(This card has no additional effect.)"
Cost: none. Prerequisite: "Your Person on Day Laborer".

Category 1 (pure points) — the simplest shape: a printed 2 VP with a placement
prerequisite and NO ongoing effect. The prerequisite is a HAVE-check at play time
(§1 step 2): one of your people must currently occupy the Day Laborer action space.
Space occupancy is read off the space's `workers` tuple (per-player counts), so the
prereq is `get_space(board, "day_laborer").workers[idx] > 0` (the idiom in
CARD_ENGINE_IMPLEMENTATION.md §6). Your people leave every space in the returning-home
phase, so this is satisfiable only during the work phase while your worker still sits
on Day Laborer (placed on an earlier turn this round).

No cost, no on-play effect; the 2 VP ride `MinorSpec.vps` and are summed directly at
scoring (no scoring term needed).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.state import GameState, get_space

CARD_ID = "heirloom"


def _prereq(state: GameState, idx: int) -> bool:
    """At least one of player `idx`'s people currently occupies Day Laborer."""
    return get_space(state.board, "day_laborer").workers[idx] > 0


register_minor(CARD_ID, prereq=_prereq, vps=2)
