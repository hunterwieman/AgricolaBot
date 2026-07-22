"""Collector (occupation, Consul Dirigens Expansion; deck C #104; players 1+).

Card text (verbatim): "This card is an action space for you only. When you use
it for the 1st/2nd/3rd/4th time, you get 1 begging marker and 6/7/8/9
different goods of your choice."
Category: Goods Provider. No printed VPs. On-play is a no-op — the effect is
the standing action space.

GOVERNING RULING (user ruling 74, 2026-07-21, CARD_DEFERRED_PLANS.md, quoted):
"Card-as-action-space approved; card spaces count as action spaces for other
cards' hooks (user: both texts literally say 'action space'). Collector
surfaces wide at PlaceWorker (user) via a picks payload — the goods menu is
the 10 good types (food included), so the maxima are C(10,6)=210 / C(10,7)=120
/ C(10,8)=45 / C(10,9)=10, none Pareto-comparable."

MECHANICS — the played-card-as-action-space machinery
(`agricola/cards/card_spaces.py`; engine seams in its module docstring):

- **Placement, WIDE.** One ``PlaceWorker(space="card:collector", picks=…)``
  per combination of ``6 + uses_so_far`` DISTINCT good names from the 10-good
  menu (wood, clay, reed, stone, grain, veg, food, sheep, boar, cattle —
  Revised "goods" includes food; a begging marker is NOT a good). None of the
  combinations Pareto-dominates another (each is a set of distinct types), so
  there is no pruning — the widths are exactly C(10, 6/7/8/9) = 210/120/45/10.
- **"For you only."** Only the owner is ever offered the placement (the
  machinery's ownership gate); the opponent never sees it.
- **The use.** The placement decrements ``people_home`` like any placement,
  occupies the card for the round (the on-card worker marker), and is hosted
  with the generic action-space lifecycle, so other cards' before/after
  action-space hooks fire on it with ``space_id = "card:collector"`` (the
  ruling's consequence). At the work step the registered ``use_fn`` grants
  1 of each picked good — resources directly, animals via
  ``helpers.grant_animals`` so the accommodation barrier surfaces the
  keep-which choice on overflow — **and 1 begging marker** (part of the
  action, per the ruling), and increments the use counter.
- **Four uses per game.** The counter (this card's own CardStore entry) walks
  1→4; after the 4th use ``placeable_fn`` returns no variants, so the space
  is never placeable again.

Card-game only (ownership-gated registries; the machinery is registry-gated
and Family-inert), so the Family trace and the C++ differential gates are
untouched. See CARD_ENGINE_IMPLEMENTATION.md §2 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from itertools import combinations

from agricola.cards.card_spaces import register_card_action_space
from agricola.cards.specs import register_occupation
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "collector"

# The 10-good menu (user ruling 74): the seven resource goods plus the three
# animal types. Revised "goods" includes food; a begging marker is NOT a good.
# Canonical surfacing order — resources in the Resources field order, then the
# animals in the Animals field order.
GOODS: tuple[str, ...] = (
    "wood", "clay", "reed", "stone", "grain", "veg", "food",
    "sheep", "boar", "cattle",
)
_RESOURCE_GOODS = frozenset({"wood", "clay", "reed", "stone", "grain", "veg", "food"})
_ANIMAL_GOODS = frozenset({"sheep", "boar", "cattle"})

# "When you use it for the 1st/2nd/3rd/4th time": uses 0..3 grant 6..9 goods;
# after the 4th use the space is never placeable again.
_MAX_USES = 4
_BASE_GOODS = 6


def _uses(player_state) -> int:
    """Uses so far (0..4) — this card's own CardStore counter."""
    return player_state.card_state.get(CARD_ID, 0)


def _placeable(state: GameState, owner_idx: int) -> list:
    """The wide placement variants: every combination of ``6 + uses`` distinct
    goods from the 10-good menu, one picks tuple each (C(10, 6/7/8/9) —
    none Pareto-comparable, no pruning). Empty after the 4th use."""
    uses = _uses(state.players[owner_idx])
    if uses >= _MAX_USES:
        return []
    return [tuple(c) for c in combinations(GOODS, _BASE_GOODS + uses)]


def _use(state: GameState, owner_idx: int, picks) -> GameState:
    """The space's action: 1 of each picked good + 1 begging marker (part of
    the action, per the ruling), and the use counter advances. Resources land
    directly; animals go through ``grant_animals`` in the same synchronous
    shot, so the accommodation barrier sees the combined grant and surfaces
    the keep-which choice if the farm overflows."""
    p = state.players[owner_idx]
    gained = Resources(**{g: 1 for g in picks if g in _RESOURCE_GOODS})
    p = fast_replace(
        p,
        resources=p.resources + gained,
        begging_markers=p.begging_markers + 1,
        card_state=p.card_state.set(CARD_ID, _uses(p) + 1),
    )
    state = fast_replace(state, players=tuple(
        p if i == owner_idx else state.players[i]
        for i in range(len(state.players))))
    animals = Animals(**{g: 1 for g in picks if g in _ANIMAL_GOODS})
    if animals.sheep or animals.boar or animals.cattle:
        state = grant_animals(state, owner_idx, animals)
    return state


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_card_action_space(CARD_ID, _use, placeable_fn=_placeable)
