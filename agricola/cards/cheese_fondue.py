"""Cheese Fondue (minor improvement, E57; Ephipparius Expansion; Food Provider).

Card text (verbatim): "Each time you bake at least 1 grain into bread, you get 1
additional food if you have at least 1 sheep and (another) 1 additional food if you
have at least 1 cattle."
Cost: 1 Clay. Prerequisite: none. VPs: 1. Not passing.

A bake-bread hook paying flat additional food (the Dutch Windmill A63 shape): a
mandatory, choice-free effect -> an `before_bake_bread` AUTOMATIC effect
(register_auto). Payout: +1 food if the owner holds >= 1 sheep, and a SEPARATE +1
food if the owner holds >= 1 cattle (the "(another)" makes them stack; max +2).

TIMING — `before_bake_bread`, NOT after (this deliberately follows the
Trigger-Timing ruling over the phrase's "at least 1 grain", per
CARD_AUTHORING_GUIDE.md §2):
  - "Each time you [bake ...]" fires in the BEFORE phase of the bake. A reward
    lands in the AFTER phase ONLY when it must read what the bake PRODUCED or its
    chosen target. This reward reads the owner's ANIMAL holdings (sheep / cattle),
    which a bake never changes — so it is a FLAT reward and fires BEFORE. (Sheep and
    cattle counts are identical before and after the bake, so the payout is
    before/after-identical; the ruling fixes the phase regardless of observability.)
  - "bake AT LEAST 1 GRAIN into bread" is a GATE (a real grain-consuming bake must
    happen), not an ordering — the same shape as Beer Stein / Baking Sheet's "you
    must bake normally" clarification, which the guide fixes to `before`. The gate
    is satisfied STRUCTURALLY by before-timing: `PendingBakeBread`'s before-phase
    offers only FireTrigger + CommitBake (no Stop — verified in
    `legality._enumerate_pending_bake_bread`), so once the host exists a real
    grain-baking CommitBake is forced. Every `PendingBakeBread` is reached only via
    `_can_bake_bread` (>= 1 grain + a baking improvement), so the before-auto never
    fires without a genuine >= 1-grain bake following. `after_bake_bread` for this
    FLAT reward would be the exact convenience-bias anti-pattern the guide documents
    (Beer Stein / Baking Sheet shipped on `after` — wrong).

No stranding guard is needed: the effect only ADDS food, consuming nothing the
mandatory bake needs (contrast a grain-converting before-trigger). Own-action only
(register_auto default): the auto pays the acting/baking player, who is the owner.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "cheese_fondue"


def _apply(state: GameState, idx: int) -> GameState:
    a = state.players[idx].animals
    food = (1 if a.sheep >= 1 else 0) + (1 if a.cattle >= 1 else 0)
    if food == 0:
        return state   # no sheep and no cattle -> no additional food (converge)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)), vps=1)
register_auto("before_bake_bread", CARD_ID, lambda state, idx: True, _apply)
