"""Case Builder (occupation, B105; Bubulcus Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 good of each of the
following types, If you have at least 2 of that good in your supply already:
food, grain, vegetable, reed, wood."

So at play time, for each of the five named good types, if the player already
holds at least 2 of that good, they gain 1 more of it. The five checks are all
read against the SAME pre-grant snapshot of the supply (granting one good can
never flip another good's threshold — the goods are disjoint — but the snapshot
is the literal reading and keeps the checks independent).

Category 2 (on-play one-shot, conditional). No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "case_builder"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    base = p.resources  # pre-grant snapshot; every threshold reads this
    gain = Resources(
        food=1 if base.food >= 2 else 0,
        grain=1 if base.grain >= 2 else 0,
        veg=1 if base.veg >= 2 else 0,
        reed=1 if base.reed >= 2 else 0,
        wood=1 if base.wood >= 2 else 0,
    )
    p = fast_replace(p, resources=base + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
