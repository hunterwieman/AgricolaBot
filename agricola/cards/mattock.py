"""Mattock (minor improvement, Ephipparius E77; cost 1 wood).

Card text (verbatim): "Each time you get reed and/or stone from an action space,
you get 1 additional clay."

The action spaces from which you get reed or stone are exactly the reed / stone
building-resource ACCUMULATION spaces: Reed Bank (reed), Western Quarry and Eastern
Quarry (stone) — the only reed/stone yields in the 2-player action-space set (the
other accumulation spaces give wood/clay, and no non-accumulation space yields reed
or stone). An accumulation space always holds >=1 of its resource when it is usable
(it refills each round and is single-use), so "get reed and/or stone from" one is,
for these three spaces, exactly "use" one — the Geologist idiom ("each time you use
the reed accumulation space, +1 clay"), not an any-source goods-gained trigger. A
single space never yields both reed and stone, so the flat +1 clay fires once per
use, matching "1 additional clay".

Timing / kind: "Each time you [get]…" with a flat, mandatory reward → an automatic
effect (``register_auto``) on the ``before_action_space`` window (the standing
trigger-timing ruling; the clay is independent of the space's own output, so before
vs. after is observationally identical). Western Quarry / Eastern Quarry / Reed Bank
are ATOMIC, so ``register_action_space_hook`` hosts them when the card is owned.
Played via an improvement space; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "mattock"

# The reed / stone accumulation spaces (2-player). Reed Bank yields reed; the two
# quarries yield stone. These are the only reed/stone sources among action spaces.
_SPACES = frozenset({"reed_bank", "western_quarry", "eastern_quarry"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in _SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _SPACES)
