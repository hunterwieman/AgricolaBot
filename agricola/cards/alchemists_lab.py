"""Alchemists Lab (minor improvement, E81; Ephipparius Expansion; no cost,
prereq 3 occupations, 1 printed VP).

Card text: "This card is an action space for all. A player who uses it gets
1 building resource of each type they already have. If another player uses it,
they must first pay you 1 food."

A FOOD-tolled for-all card space (ruling 86; the Forest Inn shape): the toll
gates a non-owner's arrival liquidation-aware and is paid to the OWNER before
the host's before-window. The action's yield is DYNAMIC — +1 wood/clay/reed/
stone for each type the USER already holds ≥1 of — so carryability is "at
least one building resource in hand" (`placeable_fn` empty otherwise). The
yield lands in the host's `taken` delta, which is exactly why Mattock E77 and
Beaver Colony E33 were rebuilt content-based (a Lab take of reed/stone fires
them; a named-space read never would).
"""
from __future__ import annotations

from agricola.cards.card_spaces import register_card_action_space
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "alchemists_lab"
_TYPES = ("wood", "clay", "reed", "stone")


def _placeable(state: GameState, placer_idx: int, owner_idx: int) -> list:
    r = state.players[placer_idx].resources
    return [None] if any(getattr(r, t) >= 1 for t in _TYPES) else []


def _use(state: GameState, placer_idx: int, owner_idx: int, picks) -> GameState:
    p = state.players[placer_idx]
    gained = Resources(**{t: 1 for t in _TYPES if getattr(p.resources, t) >= 1})
    p = fast_replace(p, resources=p.resources + gained)
    return fast_replace(state, players=tuple(
        p if i == placer_idx else state.players[i]
        for i in range(len(state.players))))


register_minor(CARD_ID, min_occupations=3, vps=1)
register_card_action_space(
    CARD_ID, _use, placeable_fn=_placeable, for_all=True,
    toll=Cost(resources=Resources(food=1)))
