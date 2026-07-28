"""Forest Inn (minor improvement, B42; Bubulcus Expansion; cost 1 clay +
1 reed, prereq "Play in Round 6 or Before").

Card text: "This is an action space for all. A player who uses it can exchange
5/7/9 wood for 8 wood and 2/4/7 food. When another player uses it, they must
first pay you 1 food."

The first FOOD-tolled for-all card space (ruling 86): the 1-food toll gates a
non-owner's arrival liquidation-aware (`toll_payable` — cooking mid-payment is
legal, so a 0-food player with a cookable animal still arrives via the
raise frame, whose resume pays the OWNER before the host fires any
before-window effect). The action IS the exchange (ruling 86 item 4 —
carryability): each affordable tier surfaces as one WIDE placement variant
(`picks = (tier,)`, the Collector idiom — 5, 7, or 9 wood in → 8 wood plus
2, 4, or 7 food out), so a placer below 5 wood cannot arrive at all. The
exchange's food-and-wood yield lands in the host's `taken` delta, so
"got food/wood from a space" reactors (Kindling Gatherer) fire on it.
"""
from __future__ import annotations

from agricola.cards.card_spaces import register_card_action_space
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "forest_inn"
_TIERS = {5: (8, 2), 7: (8, 4), 9: (8, 7)}   # wood in -> (wood out, food out)


def _prereq(state: GameState, idx: int) -> bool:
    return state.round_number <= 6            # "Play in Round 6 or Before"


def _placeable(state: GameState, placer_idx: int, owner_idx: int) -> list:
    """One variant per affordable exchange tier — the action IS the exchange,
    so no tier affordable means no arrival (carryability, ruling 86 item 4)."""
    wood = state.players[placer_idx].resources.wood
    return [(t,) for t in sorted(_TIERS) if wood >= t]


def _use(state: GameState, placer_idx: int, owner_idx: int, picks) -> GameState:
    tier = picks[0]
    wood_out, food_out = _TIERS[tier]
    p = state.players[placer_idx]
    p = fast_replace(p, resources=p.resources
                     + Resources(wood=wood_out - tier, food=food_out))
    return fast_replace(state, players=tuple(
        p if i == placer_idx else state.players[i]
        for i in range(len(state.players))))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1, reed=1)),
               prereq=_prereq)
register_card_action_space(
    CARD_ID, _use, placeable_fn=_placeable, for_all=True,
    toll=Cost(resources=Resources(food=1)))
