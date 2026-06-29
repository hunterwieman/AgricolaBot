"""Rammed Clay (minor improvement, A16; Base Revised; players -).

Card text: "When you play this card, you immediately get 1 clay. You can use clay
instead of wood to build fences."
Clarification: "You can use both wood and clay for the same 'Build Fences' action."

Two effects:
- on-play: +1 clay (immediate; Category 2 one-shot).
- a passive build-fence CONVERSION: clay may substitute for wood, 1:1, with NO per-action
  cap (the clarification — both wood and clay in one action, any split). The fence bill's
  base is geometry-derived wood (`Resources(wood=N)` for N paid edges), so the generator
  returns every wood/clay split `Resources(wood=N-k, clay=k)` for k in 0..N; the
  `effective_payments` Pareto-min keeps them all (wood and clay are incomparable goods), and
  the whole-action settle surfaces them as a `PendingChooseCost` menu (the player picks the
  split). Because the during-building affordability is checked on the WHOLE-ACTION RUNNING
  TOTAL (COST_MODIFIER_DESIGN.md §9.2), this also ENABLES a clay-funded build a wood-tight
  player couldn't otherwise afford — exactly the running-total property Millwright relies on.

Unlimited / per-edge, so it is a PLAIN conversion (no `record`, default `order` — a producer,
applied before a sink like Millwright, which can then turn the resulting clay into grain).
Card-only state (an empty registry in the Family game), so the Family game is byte-identical
and the C++ gates are untouched. See COST_MODIFIER_DESIGN.md §9 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "rammed_clay"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _expand(state, idx, ctx, cost: Resources) -> list[Resources]:
    """Every wood->clay split of the fence bill (1:1, unlimited): the unchanged cost
    (k=0) plus replacing k of the wood with k clay, for k in 1..cost.wood."""
    return [cost - Resources(wood=k) + Resources(clay=k) for k in range(cost.wood + 1)]


register_minor(CARD_ID, on_play=_on_play)
register_conversion("build_fence", CARD_ID, _expand)
