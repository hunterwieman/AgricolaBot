"""Forest School (minor improvement, A28; Artifex Expansion; players -).

Card text: "You can consider the \"Lessons\" action spaces not occupied. You can replace
each food that an occupation costs with wood."
Cost: 1 Wood + 1 Clay. Kept (not traveling). 1 printed VP.

Two independent clauses:

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

CLAUSE 2 — replace the occupation's food cost with wood, PER FOOD (user ruling 2026-07-17,
ruling 65): "each food" is a per-unit license, so the player may replace ANY SUBSET of the
food cost — k wood -> k food, k in 1..min(food cost, wood held) — and MIXED payments are
legal (1 wood + 1 food on Writing Desk's 2-food granted play). Implemented as a play-variant
trigger on `before_play_occupation`: one FireTrigger(variant=str(k)) per legal k (expanded by
the play-occupation enumerator); firing swaps k wood for k food, and the commit then debits
the full cost from the raised supply.

THE PRICE IS THE FRAME'S. The cost of the play in progress lives on
`PendingPlayOccupation.cost` (the Lessons ramp, Scholar's flat 1 food, Writing Desk's granted
2 food, Seed Researcher's granted 0) and that is what every function here reads. The original
implementation re-derived it from `occupation_cost(len(occupations))` — the Lessons ramp —
which was correct on Lessons (identical by construction) and on Scholar (owning Scholar forces
the ramp to 1, its flat price) but wrong on every differently-priced granted route: it offered
a phantom 1-wood swap on Seed Researcher's FREE play (a wood->food converter the card never
grants) and mis-sized the swap on Writing Desk's 2-food play. Fixed 2026-07-17.

Each variant k carries the standing before-trigger STRANDING GUARD: the play-occupation host
has no decline (commits are withheld while the cost is short), so a swap after which the cost
were no longer payable would soft-lock the turn; `_variants` offers only k where `_payable`
still holds on the post-swap supply. This also filters a k below the shortfall (the raised
food still couldn't pay, and the play host offers no other way out).

Because firing produces food usable for the play cost, the card ALSO registers an
OCCUPATION_FOOD_SOURCE so the affordability gate (`_payable_occupation`) knows the food is
reachable and offers a play payable only via Forest School. The seam's signature carries the
route's actual cost — `source_fn(state, idx, cost)`, extended 2026-07-17 for exactly this
card — and the source reports the max-k swap with the cost's own wood component reserved.
The commit gate (`_payable(top.cost)`) then withholds the commit until the swap is fired, so
there is no empty-frontier dead state. Once per play via the host's `triggers_resolved`.

Card-only state (all registries are empty in the Family game), so the Family game is
byte-identical and the C++ differential gates are untouched. See CARD_AUTHORING_GUIDE.md,
sleeping_corner.py (clause 1) and paper_maker.py (the food-source pattern).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_occupation_food_source
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.legality import _payable, register_occupancy_override
from agricola.pending import PendingPlayOccupation
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
# Clause 2 — replace the occupation's food cost with wood (per food; mixed OK)
# ---------------------------------------------------------------------------

def _play_cost(state: GameState) -> Resources | None:
    """The cost of the occupation play IN PROGRESS — the top frame's route-supplied
    `cost` (the Lessons ramp / Scholar's flat 1 / a grant's own price). None when the
    top frame is not a play-occupation host (defensive; the trigger only surfaces there)."""
    top = state.pending_stack[-1] if state.pending_stack else None
    if not isinstance(top, PendingPlayOccupation):
        return None
    return top.cost


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional; once per play (host `triggers_resolved`). Offered only when the play in
    # progress actually costs food (nothing to replace on a free play — the first Lessons
    # occupation, Seed Researcher's grant) and the owner holds wood to swap. The per-k
    # legality lives in `_variants`.
    if CARD_ID in triggers_resolved:
        return False
    cost = _play_cost(state)
    if cost is None or cost.food < 1:
        return False
    return state.players[idx].resources.wood >= 1


def _variants(state: GameState, idx: int) -> list[str]:
    """One variant per legal replacement count k ("1", "2", ...): swap k wood -> k food,
    k up to min(food cost, wood held). Each k is offered only if the play stays payable
    AFTER the swap — the play host has no decline, so a swap that stranded the mandatory
    play would soft-lock the turn (the standing before-trigger stranding guard)."""
    cost = _play_cost(state)
    if cost is None:
        return []
    p = state.players[idx]
    out: list[str] = []
    for k in range(1, min(cost.food, p.resources.wood) + 1):
        p_after = fast_replace(
            p, resources=p.resources - Resources(wood=k) + Resources(food=k))
        if _payable(state, idx, p_after, cost):
            out.append(str(k))
    return out


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Spend k wood, gain k food — the per-food substitution at the chosen count. The
    food then pays (part of) the occupation's food cost at the commit."""
    k = int(variant)
    p = state.players[idx]
    p = fast_replace(p, resources=(p.resources - Resources(wood=k)
                                   + Resources(food=k)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _food_source(state: GameState, idx: int, cost: Resources):
    """For the occupation-affordability gate: the MAX swap against the route's actual
    cost — (k food produced, k wood consumed) for k = min(cost.food, wood beyond the
    cost's own wood component), or None when no swap is possible. `_payable_occupation`
    simulates this single best firing; a smaller k never succeeds where max-k fails
    (the swap is 1:1 and the cost's own wood is reserved)."""
    p = state.players[idx]
    k = min(cost.food, p.resources.wood - cost.wood)
    if k < 1:
        return None
    return (k, Resources(wood=k))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=1)),
    vps=1,
)
register_occupancy_override(_occupancy_override)
register("before_play_occupation", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_occupation_food_source(CARD_ID, _food_source)
