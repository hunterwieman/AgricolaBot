"""Ropemaker (occupation, A145; Artifex Expansion; players 3+; Building Resource
Provider).

Card text (verbatim): "At the end of each harvest, you get 1 reed from the general
supply."
No clarifications / errata printed.

A harvest-window automatic income. "At the end of each harvest" is the harvest
ladder's window #16 `end_of_harvest` — the last moment INSIDE the harvest, after
the breeding phase, before the outside-the-harvest `after_harvest` window (the
post-breeding-timeline ruling of 2026-07-03; Winter Caretaker maps the same
phrase to `end_of_harvest`). The reward is MANDATORY and choice-free — +1 reed
from the general supply, no threshold, no accommodation (reed is a supply good) —
so it is an automatic effect (`register_auto` on the `end_of_harvest` window
event), fired by the harvest walk per owner (starting player first). The
`register_harvest_window_hook` call indexes the card so the walk knows to fire it
at that window for the owner.

Played via Lessons; no on-play effect. The registries default empty in the Family
game, so it stays byte-identical and the C++ gates are untouched. See
social_benefits.py / bale_of_straw.py (the harvest-window auto idiom) and
winter_caretaker.py (the `end_of_harvest` window).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "ropemaker"
WINDOW_ID = "end_of_harvest"


def _eligible(state: GameState, idx: int) -> bool:
    """Unconditional — the reward is a flat +1 reed at the end of every harvest."""
    return True


def _apply(state: GameState, idx: int) -> GameState:
    """+1 reed from the general supply at the end of the harvest."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(reed=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
register_auto(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
