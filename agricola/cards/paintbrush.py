"""Paintbrush (minor improvement, E39; Ephipparius Expansion; Points Provider).

Card text (verbatim): "Each harvest, you can exchange exactly 1 clay for your
choice of 2 food or 1 bonus point."
Cost: 1 Wood. Prerequisite: 1 Wild Boar (a HAVE-check at play time — the boar
is not spent). No printed VP (the points are earned, not printed). Not passing.

ONE once-per-harvest budget, THREE surfaces. The exchange may be used once per
harvest (id "paintbrush" in `harvest_conversions_used` — reset at each
harvest's fresh FIELD entry), and per the free-span ruling it is reachable
anywhere in the harvest, so the one budget is spendable on any of three
surfaces, each fire carrying the food-vs-point choice as a variant:

1. **The FEED payment frame** — a `HarvestConversionSpec` (this is also what
   puts the card on the feed frame's offer list). `food_out=0` with BOTH
   variants' outputs granted in the side effect keeps ONE spec for both
   branches: the seam's executor debits the 1 clay (input_cost), adds no food,
   marks the budget, then `_side_effect` grants the chosen output — "food" →
   +2 food, "point" → +1 banked point. `variants_fn` returns
   ["food", "point"], so the enumerator offers one
   `CommitHarvestConversion(conversion_id="paintbrush", variant=...)` each.

2. **The generalized in-harvest raise frame** (user rulings 34 + 37,
   2026-07-12: a raise-frame fire IS the food branch — rider outputs like the
   bonus point are NOT frontier-eligible, so only the pure clay→2-food
   converter joins the payment frontier): `frontier_fire=((0, 0, 0, 1, 0, 0),
   2)` (the 6-tuple (grain,veg,wood,clay,reed,stone); 1 clay) on the same spec.
   `_execute_food_payment` debits the clay, adds the 2 food,
   and marks the SAME budget — no side effect runs there (pure fire).

3. **The free span** (user ruling 36, 2026-07-12: the anytime exchanges are
   available throughout the harvest span, field phase through end_of_harvest;
   the point branch rides along per ruling 37's rider treatment on these
   trigger surfaces): `register_free_span_trigger` puts an optional
   variant-expanded FireTrigger on every in-span window/event. Eligibility
   gates on ownership + the unused budget + clay >= 1; the apply debits the
   clay, marks the budget, and grants the chosen output.

Any one surface's fire marks "paintbrush" in `harvest_conversions_used`,
which withholds the other two for the rest of the harvest: the feed enumerator
and `available_span_converters` both check that set, and the span trigger's
eligibility_fn reads it directly.

The bonus point cannot be granted immediately (there is no immediate-VP
mechanism), so each "point" fire increments a per-card CardStore counter
(banked across all six harvests) and the scoring term reads the count back at
end-game — the banked-VP idiom (Furniture Carpenter / Beer Keg). No `vps=` is
set (that would score a printed keep VP; these are earned).

Card-only state (the CardStore int, the registry rows, the span triggers) is
empty/unowned in the Family game, so it stays byte-identical and the C++ gates
are untouched. See CARD_AUTHORING_GUIDE.md, harvest_conversions.py, and
harvest_windows.register_free_span_trigger.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "paintbrush"

# The per-fire choice: "your choice of 2 food or 1 bonus point".
_VARIANTS = ["food", "point"]


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite: 1 Wild Boar — a HAVE-check at play time (the boar is not
    spent to play the card)."""
    return state.players[idx].animals.boar >= 1


def _owns(state: GameState, idx: int) -> bool:
    return CARD_ID in state.players[idx].minor_improvements


def _variants(state: GameState, idx: int) -> list:
    """Both output choices are always legal once the fire itself is (the clay
    affordability is gated by the seam / the span eligibility). Serves both
    the spec's variants_fn and the span triggers' play-variant expansion."""
    return list(_VARIANTS)


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_output(state: GameState, idx: int, variant: str) -> GameState:
    """The chosen output: "food" -> +2 food to supply; "point" -> bank +1 in
    the per-card CardStore counter (read back by the scoring term)."""
    p = state.players[idx]
    if variant == "food":
        p = fast_replace(p, resources=p.resources + Resources(food=2))
    else:
        assert variant == "point", f"paintbrush: unknown variant {variant!r}"
        banked = p.card_state.get(CARD_ID, 0)
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return _update_player(state, idx, p)


def _side_effect(state: GameState, idx: int, variant: str) -> GameState:
    """Feed-seam side effect. The seam's executor has already debited the
    1 clay (input_cost), added food_out=0, and marked the budget — only the
    chosen output remains."""
    return _grant_output(state, idx, variant)


def _span_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Free-span trigger eligibility: owns the card, the once-per-harvest
    budget is unused (SHARED with the feed-seam / raise-frame fires via
    `harvest_conversions_used`), and the clay is on hand."""
    p = state.players[idx]
    return (CARD_ID in p.minor_improvements
            and CARD_ID not in p.harvest_conversions_used
            and p.resources.clay >= 1)


def _span_apply(state: GameState, idx: int, variant: str) -> GameState:
    """Free-span trigger fire: debit the 1 clay, mark the shared budget, then
    grant the chosen output."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(clay=1),
        harvest_conversions_used=p.harvest_conversions_used | {CARD_ID},
    )
    return _grant_output(_update_player(state, idx, p), idx, variant)


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests (1 per "point" fire)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Cost 1 wood; prerequisite 1 wild boar; no printed VP (the points are earned).
register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq, vps=0)

# Surface 1 — the FEED payment frame: one spec for both variants (food_out=0;
# the chosen output is granted in the side effect). Surface 2 — the raise
# frame: frontier_fire is the food branch as a pure clay->2-food converter
# (rulings 34/37, 2026-07-12), sharing the same once-per-harvest budget.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(clay=1),
    food_out=0,
    is_owned_fn=_owns,
    side_effect_fn=_side_effect,
    variants_fn=_variants,
    frontier_fire=((0, 0, 0, 1, 0, 0), 2),   # (grain,veg,wood,clay,reed,stone): clay->2 food
))

# Surface 3 — the free span (ruling 36, 2026-07-12): a variant-expanded
# optional trigger on every in-span window/event.
register_free_span_trigger(CARD_ID, _span_eligible, _span_apply,
                           variants_fn=_variants)

_ACTION_LABELS = {"food": "1 clay → 2 food", "point": "1 clay → 1 point"}


def _action_label(variant: str) -> str | None:
    """Web-UI label for the per-fire choice (mechanical, terse): the full
    exchange each variant performs."""
    return _ACTION_LABELS.get(variant)


register_scoring(CARD_ID, _score)
register_action_labeler(CARD_ID, _action_label)
