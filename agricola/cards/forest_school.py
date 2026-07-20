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

CLAUSE 2 — replace the occupation's food cost with wood, PER FOOD, as a COST CONVERSION
(rulings 65 + 67). Ruling 65 (2026-07-17) fixed the semantics: "each food" is a per-unit
license priced by the ROUTE'S actual cost (`PendingPlayOccupation.cost` — the Lessons ramp,
Scholar's flat 1, Writing Desk's granted 2, Seed Researcher's granted 0), so the player may
replace any subset k — MIXED payments are legal. Ruling 67 (2026-07-20) fixed the HOME: the
substitution is a `register_conversion` under `action_kind="play_occupation"`, resolved by the
`effective_payments` chokepoint like every other cost conversion, NOT a trigger. The play
enumerator surfaces one `CommitPlayOccupation(payment=...)` per Pareto-minimal way to pay —
(k wood, need−k food) for each k — which:
  - preserves ruling 65's mixed payments as ordinary frontier points;
  - Pareto-prunes a dominated substitution automatically (with Working Gloves co-owned, this
    card's 2-wood payment loses to Working Gloves' 1-wood and is never offered — the user's
    no-dominated-offers requirement, structural);
  - makes double-replacement inexpressible (a payment vector replaces each food unit at most
    once — the trigger model's over-production loophole cannot arise);
  - costs no extra ply (the old fire-then-commit two-step is gone).
The conversion emits variants unfiltered (the pipeline's affordability filter and the
gate<->frontier agreement handle wood the player doesn't hold), and it NEVER touches a
play-variant surcharge or an individual printed cost — those are outside the pipeline by
construction (user ruling 2026-07-20: separate from the occupation cost, never modifiable).

The old trigger implementation (a play-variant trigger + an OCCUPATION_FOOD_SOURCES entry) is
fully superseded: the affordability gate (`_payable_occupation` → `can_pay`) sees the
substitution through the conversion fold, so no food-source registration is needed. "Food paid
as occupation cost" readers (Furniture Maker, ruling 63) now read the host's `paid_cost` stamp
— the actual payment vector — so a partial substitution counts exactly.

Card-only state (both registries are empty in the Family game), so the Family game is
byte-identical and the C++ differential gates are untouched. See CARD_AUTHORING_GUIDE.md,
sleeping_corner.py (clause 1) and frame_builder.py (the conversion pattern).
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import register_minor
from agricola.legality import register_occupancy_override
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
# Clause 2 — the per-food wood substitution (a play_occupation cost conversion)
# ---------------------------------------------------------------------------

def _expand(state: GameState, idx: int, ctx, cost: Resources) -> list[Resources]:
    """Unchanged cost + one variant per replacement count k (1..cost.food): k food
    replaced by k wood ("each food" is a per-unit license — ruling 65). Variants are
    emitted unfiltered; the chokepoint's affordability filter + Pareto prune decide
    what surfaces (the expand1 contract — frame_builder.py)."""
    out = [cost]
    for k in range(1, cost.food + 1):
        out.append(cost - Resources(food=k) + Resources(wood=k))
    return out


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=1)),
    vps=1,
)
register_occupancy_override(_occupancy_override)
register_conversion("play_occupation", CARD_ID, _expand)
