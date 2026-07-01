"""Petrified Wood (minor improvement, D6; Dulcinaria Expansion; players -).

Card text: "Immediately exchange up to 3 wood for 1 stone each."

Prerequisite: "2 Occupations". Cost: none. Not passing.

Category 2 (on-play one-shot) with an OPTIONAL amount choice. "up to 3 ... for 1
stone each" is a strict 1:1 trade of wood for stone (1 wood -> 1 stone), where the
player chooses how many to convert — between 0 and min(3, wood-on-hand). Because
"up to 3" lets the player decline entirely, **0 is a valid choice**, and since the
forced-choice frame (`PendingCardChoice`) has no Stop/decline action, 0 is offered as
an explicit option in the options tuple — the player picks an amount, never a "stop".

The on-play pushes a `PendingCardChoice` whose options are the integers
`0..min(3, wood)`. Options are capped at the wood actually on hand so no illegal
over-spend is ever offered: with 0 wood the sole option is `(0,)` (a no-op the agent
auto-resolves via singleton-skip). The resolver applies `wood -= n; stone += n` for
the chosen `n` and pops the frame. No event hooks, no scoring, not passing.

A minor on_play that PUSHes a frame is supported: resolution.py runs `on_play` AFTER
the PendingPlayMinor after-phase pivot, and `_fire_subaction_before_auto` is a no-op
on a `card_choice` frame (it is not a sub-action pending). See seasonal_worker.py /
childless.py for the same PendingCardChoice resolver shape and
CARD_IMPLEMENTATION_PLAN.md Category 2 / II.6.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_card_choice_resolver
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "petrified_wood"
MAX_EXCHANGE = 3


def _on_play(state: GameState, idx: int) -> GameState:
    """Push the amount choice: how many wood (0..min(3, wood)) to turn into stone."""
    wood = state.players[idx].resources.wood
    n_max = min(MAX_EXCHANGE, wood)
    options = tuple(range(0, n_max + 1))   # always includes 0 (decline) — no Stop path
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", options=options))


def _resolve(state: GameState, idx: int, n: int) -> GameState:
    """Apply the chosen 1:1 trade (n wood -> n stone) and pop the choice frame."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=-n, stone=n))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return pop(state)   # resolver owns the PendingCardChoice frame


register_minor(CARD_ID, min_occupations=2, on_play=_on_play)
register_card_choice_resolver(CARD_ID, _resolve)
