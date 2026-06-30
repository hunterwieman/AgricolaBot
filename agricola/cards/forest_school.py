"""Forest School (minor improvement, A28; Artifex Expansion; players -).

Card text: "You can consider the \"Lessons\" action spaces not occupied. You can replace
each food that an occupation costs with wood."
Cost: 1 Wood + 1 Clay. Kept (not traveling). 1 printed VP.

Two independent clauses, each a small, already-existing mechanism:

CLAUSE 1 — a LEGALITY RELAXATION on worker placement at Lessons. Normally Lessons (like every
action space) may hold only one worker; this card lets its owner place there even when one
opponent already occupies it. Identical shape to Sleeping Corner's Wish-for-Children relaxation:
registered via `register_occupancy_override`, which `_is_available` consults ONLY on the
occupied branch (so the Family game, which never registers, pays nothing). The owner must hold
no worker on Lessons themselves and exactly one OTHER player must hold it — written as a player
count (not a worker count) so it stays correct under a future 4-player variant (in the current
2-player game the single occupant is always the lone opponent, so `== 1` is automatically true
on the occupied branch). Unlike a Wish space, Lessons never generates a newborn second worker,
so there is no parent+newborn pair to tolerate — but the player-count form handles that uniformly.

CLAUSE 2 — replace the food an occupation costs with wood. In the 2-player game the first
occupation is free and every later one costs 1 food (`occupation_cost`). This clause swaps that
1 food for 1 wood — a 1-for-1 substitution ("EACH food ... with wood"). It is implemented exactly
like Paper Maker's food source: an OPTIONAL `before_play_occupation` trigger that, when fired,
spends the occupation's food-cost in WOOD and produces that much FOOD, which then pays the
occupation's printed food cost. Net effect: the occupation is paid for in wood instead of food.

Because firing produces food usable for the play cost, the clause-2 trigger ALSO registers an
OCCUPATION_FOOD_SOURCE so the Lessons/Scholar affordability gate (`_payable_occupation`) knows
the food is reachable and offers an occupation whose only payment route is firing Forest School
first. The play-occupation enumerator's commit gate (`_payable(top.cost)`) then withholds the
commit until Forest School has been fired, so there is no empty-frontier dead state. The source
declares its inputs (the wood) so the gate's simulated liquidation reserves them. It is NOT
folded into the food-payment frame: as an optional substitution it is offered as a real
FireTrigger step (the player may decline and pay food normally). Once per play via the host's
`triggers_resolved`. Offered only when the occupation actually costs food (the free first
occupation has nothing to replace).

Card-only state (both registries are empty in the Family game), so the Family game is
byte-identical and the C++ differential gates are untouched. See CARD_AUTHORING_GUIDE.md,
sleeping_corner.py (clause 1) and paper_maker.py (clause 2).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_occupation_food_source
from agricola.cards.triggers import register
from agricola.legality import occupation_cost, register_occupancy_override
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "forest_school"


# ---------------------------------------------------------------------------
# Clause 1 — Lessons usable even when one opponent occupies it
# ---------------------------------------------------------------------------

def _occupancy_override(state: GameState, space_id: str) -> bool:
    """The current player may place on an occupied "Lessons" space iff they own Forest
    School, hold no worker there themselves, and exactly one OTHER player does (count
    players, not workers — the 4-player-safe form)."""
    if space_id != "lessons":
        return False
    ap = state.current_player
    if CARD_ID not in state.players[ap].minor_improvements:
        return False
    workers = get_space(state.board, space_id).workers
    if workers[ap] != 0:
        return False
    others_with_workers = sum(1 for i, w in enumerate(workers) if i != ap and w > 0)
    return others_with_workers == 1


# ---------------------------------------------------------------------------
# Clause 2 — replace the occupation's food cost with wood
# ---------------------------------------------------------------------------

def _food_cost(state: GameState, idx: int) -> int:
    """Food the NEXT occupation play costs (0 for the free first, 1 for each later one)."""
    return occupation_cost(len(state.players[idx].occupations)).food


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional. Offered once per play, only when the occupation actually costs food (nothing
    # to replace on the free first occupation) and the owner can pay that food cost in wood.
    if CARD_ID in triggers_resolved:
        return False
    need = _food_cost(state, idx)
    return need >= 1 and state.players[idx].resources.wood >= need


def _apply(state: GameState, idx: int) -> GameState:
    """Spend `need` wood, gain `need` food — the 1-for-1 food->wood substitution. The food
    then pays the occupation's printed food cost at the commit."""
    need = _food_cost(state, idx)
    p = state.players[idx]
    p = fast_replace(p, resources=(p.resources - Resources(wood=need)
                                   + Resources(food=need)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _food_source(state: GameState, idx: int):
    """For the occupation-affordability gate: (food produced, inputs consumed) when firing is
    possible, else None. Used by `_payable_occupation` to simulate firing Forest School."""
    need = _food_cost(state, idx)
    if need < 1 or state.players[idx].resources.wood < need:
        return None
    return (need, Resources(wood=need))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=1)),
    vps=1,
)
register_occupancy_override(_occupancy_override)
register("before_play_occupation", CARD_ID, _eligible, _apply)
register_occupation_food_source(CARD_ID, _food_source)
