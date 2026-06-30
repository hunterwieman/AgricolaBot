"""Hunting Trophy (minor improvement, D82; Dulcinaria; players -).

Card text: "Improvements built on 'House Redevelopment' cost you 1 building resource of your
choice less. Fences built on 'Farm Redevelopment' cost you a total of 3 wood less."
Cost: Return or Cook 1 Wild Boar. 1 VP.
Clarification: "Alone, 'built' can refer to either improvement type. Improvements played by
Merchant C096 do not get discounted."

Three pieces:
- COST + on-play cook: a standard 1-boar animal cost (debited by the play-minor path).
  "Return OR Cook" — with a cooking improvement the boar is COOKED for food (`cooking_rates[1]`
  = 2 with a Fireplace, 3 with a Cooking Hearth); with none it is simply RETURNED (no food).
  Cooking is strictly better whenever possible (food, and it denies the opponent the boar), so
  the on_play just grants the cook value (0 when there is no cooking improvement).
- FENCE clause: "fences built on Farm Redevelopment cost a total of 3 wood less" — a per-action
  free-fence SEED of +3 gated on the Farm Redevelopment entry point (space_id), like Hedge
  Keeper's +3 but space-scoped instead of action-scoped (each fence edge is 1 wood, so 3 wood
  less = 3 free edges).
- HOUSE-REDEV clause: "improvements built on House Redevelopment cost 1 building resource of
  your choice less" — a cost CONVERSION on build_major + play_minor offering the cost minus 1
  of any building resource it contains (the payment menu surfaces the "of your choice"; the
  Pareto-min prunes the undiscounted base, so the discount is effectively mandatory). Gated on
  the improvement being built via House Redevelopment, detected by a `PendingHouseRedevelopment`
  frame on the stack (its Proceed-host stays while the inner build_major/play_minor resolves),
  so no entry-point threading is needed. A Major-Improvement-space build (or a Merchant repeat)
  has no such frame -> no discount, matching the clarification.

1 VP, kept. Card-only state; Family byte-identical, C++ gates untouched. See
COST_MODIFIER_DESIGN.md §9 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion, register_free_fence_seed
from agricola.cards.specs import register_minor
from agricola.helpers import cooking_rates
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "hunting_trophy"
_BUILDING = ("wood", "clay", "reed", "stone")


def _on_play(state: GameState, idx: int) -> GameState:
    cook = cooking_rates(state, idx)[1]   # boar cook value; 0 with no cooking improvement
    if cook == 0:
        return state                      # no cooking improvement -> the boar is returned
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=cook))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _house_redev_discount(state, idx, ctx, cost: Resources) -> list[Resources]:
    """1 building resource of the player's choice off an improvement built via House
    Redevelopment. Gated on a PendingHouseRedevelopment frame on the stack (its host stays
    while the inner build_major / play_minor resolves), so a Major-Improvement-space build (no
    such frame) gets no discount. Returns the base + each single-building-resource removal; the
    Pareto-min over goods prunes the base, so a discount is always taken when one is possible."""
    from agricola.pending import PendingHouseRedevelopment
    if not any(isinstance(f, PendingHouseRedevelopment) for f in state.pending_stack):
        return [cost]
    return [cost] + [cost - Resources(**{f: 1}) for f in _BUILDING if getattr(cost, f) >= 1]


register_minor(CARD_ID, cost=Cost(animals=Animals(boar=1)), vps=1, on_play=_on_play)
register_free_fence_seed(
    CARD_ID,
    lambda state, idx, *, build_fences_action, space_id: (
        3 if space_id == "farm_redevelopment" else 0),
)
for _kind in ("build_major", "play_minor"):
    register_conversion(_kind, CARD_ID, _house_redev_discount)
