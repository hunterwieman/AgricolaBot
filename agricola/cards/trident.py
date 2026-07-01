"""Trident (minor improvement, D7; Consul Dirigens Expansion; cost 1 wood;
prereq "Play in Round 3, 6, 9, or 12").

Card text: "If you play this card in round 3/6/9/12, you immediately get
3/4/5/6 food."
Cost: 1 Wood. VPs: 0. Not passing.

Category 2 (on-play one-shot). The "3/6/9/12 -> 3/4/5/6 food" slash list is NOT
an OR/play-variant — it is a positional schedule keyed to the round in which the
card is played: food = round / 3 + 2 (round 3 -> 3, 6 -> 4, 9 -> 5, 12 -> 6). The
amount is read from `state.round_number` at play time (do NOT hardcode), exactly
as a round-keyed on-play grant.

The round restriction (only rounds 3/6/9/12) is the card's PREREQUISITE — a
HAVE/when-check on `state.round_number` gating legality, NOT a cost. The prereq is
load-bearing: it both enforces the printed restriction and guarantees the food
formula only ever runs on an in-schedule round (off-cycle rounds would yield a
wrong amount). See mole_plow.py / digging_spade.py for the round-gating prereq
shape, and trellises.py for the round-keyed on-play grant shape.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "trident"
PLAYABLE_ROUNDS = frozenset({3, 6, 9, 12})


def _prereq(state: GameState, idx: int) -> bool:
    """"Play in Round 3, 6, 9, or 12" — a when-check on the current round."""
    return state.round_number in PLAYABLE_ROUNDS


def _on_play(state: GameState, idx: int) -> GameState:
    # Positional schedule keyed to the play round: 3->3, 6->4, 9->5, 12->6.
    food = state.round_number // 3 + 2
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    prereq=_prereq,
    on_play=_on_play,
)
