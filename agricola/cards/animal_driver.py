"""Animal Driver (occupation, E147; Ephipparius Expansion; players 3+; Livestock
Provider).

Card text (verbatim): "At the start of each harvest, if you have 1/2/3+ fenced
stables, you get 1 sheep/wild boar/cattle."
No clarifications / errata printed.

A harvest-window automatic animal grant, TIERED by the number of fenced stables:

  - 1 fenced stable  -> 1 sheep
  - 2 fenced stables -> 1 wild boar
  - 3 or more        -> 1 cattle

The "/"-lists are a single tiered reward keyed to the fenced-stable count, not
cumulative — the highest applicable tier yields exactly ONE animal. "Fenced
stables" are stables that lie inside a pasture (as opposed to standalone
stables); the count is `sum(pasture.num_stables for pasture in
farmyard.pastures)`, the same quantity `extract_slots` reads for capacity.

Timing — "at the start of each harvest" is harvest window #2 `start_of_harvest`
(the window opening the whole harvest, before the field phase; Bale of Straw maps
the same phrase there). The grant is MANDATORY and choice-free (a fixed animal by
tier) → an automatic effect (`register_auto` on the window event), fired by the
harvest walk per owner. The animal is granted through `helpers.grant_animals`
(the choke point for every decision-free animal gain), so an over-capacity farm
is reconciled by the accommodation barrier at the next decision boundary rather
than silently overfilling. `register_harvest_window_hook` indexes the card at the
window.

Played via Lessons; no on-play effect. The registries default empty in the Family
game, so it stays byte-identical and the C++ gates are untouched. See
bale_of_straw.py (the `start_of_harvest` auto idiom) and shepherds_crook.py /
acorns_basket.py (grant_animals).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "animal_driver"
WINDOW_ID = "start_of_harvest"


def _fenced_stables(state: GameState, idx: int) -> int:
    """Stables that lie inside a pasture (fenced stables) — the sum of each
    pasture's `num_stables`. Standalone stables (not in a pasture) do not count."""
    return sum(p.num_stables for p in state.players[idx].farmyard.pastures)


def _tier_animal(n: int) -> Animals:
    """The tier reward for `n` fenced stables: 1 sheep (1), 1 boar (2), 1 cattle
    (>= 3). `n == 0` returns no animals (the auto is gated off in `_eligible`)."""
    if n >= 3:
        return Animals(cattle=1)
    if n == 2:
        return Animals(boar=1)
    if n == 1:
        return Animals(sheep=1)
    return Animals()


def _eligible(state: GameState, idx: int) -> bool:
    """Fire only when the owner has at least 1 fenced stable."""
    return _fenced_stables(state, idx) >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the tier animal (1 sheep / boar / cattle) via grant_animals."""
    return grant_animals(state, idx, _tier_animal(_fenced_stables(state, idx)))


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
register_auto(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
