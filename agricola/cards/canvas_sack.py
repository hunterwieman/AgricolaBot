"""Canvas Sack (minor improvement, C40; Corbarius Expansion; Goods Provider).

Card text (verbatim): "When you play this card paying grain/reed for it, you
immediately get 1 vegetable/4 wood."
Cost: 1 Grain / 1 Reed (an ALTERNATIVE cost — pay ONE). Prerequisite: No
Occupations. VPs: 1 (printed keep-card VP).

The reward is COUPLED to which alternative you paid — the slash-correlation rule
(RULES.md "Slashes / respectively"): grain -> 1 vegetable, reed -> 4 wood. This
is a real alternative COST (it must stay cost-modifier-visible), so the card uses
the `alt_costs` path with `cost_labels` (specs.py): the two ways to pay are
`(Cost(grain=1), Cost(reed=1))` labeled `("grain", "reed")`, each surfaced as its
own play through `effective_payments`, and the chosen label is threaded into the
3-arg on_play, which grants the matching benefit. (Contrast a play-variant
surcharge, which would BYPASS cost modifiers — wrong here, where the slash is a
genuine cost, not an effect price.)

"No Occupations" -> max_occupations=0.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "canvas_sack"

_REWARD = {"grain": Resources(veg=1), "reed": Resources(wood=4)}


def _on_play(state: GameState, idx: int, which: str) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _REWARD[which])
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(grain=1)),
    alt_costs=(Cost(resources=Resources(reed=1)),),
    cost_labels=("grain", "reed"),
    max_occupations=0,          # "No Occupations"
    vps=1,
    on_play=_on_play,
)
