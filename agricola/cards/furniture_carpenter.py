"""Furniture Carpenter (occupation, B101; Bubulcus Expansion; players 1+).

Card text: "Each harvest, if any player (including you) owns the Joinery or an
upgrade thereof, you can buy exactly 1 bonus point for 2 food."

Category: Points Provider. No on-play effect (played via Lessons; its on-play is
a no-op). The recurring "each harvest, you can buy 1 point for 2 food" is an
anytime-in-harvest food-to-point buy with TWO surfaces sharing ONE
once-per-harvest budget — the "furniture_carpenter" entry in
``PlayerState.harvest_conversions_used``, reset at each harvest's FIELD entry:

1. **The FEED payment frame** — a ``HarvestConversionSpec`` entry (the
   ``side_effect_fn`` hook's exact shape; its docstring names "Stone Sculptor
   +1 point per harvest"). Unlike the three built-in crafts (which take a good
   and PRODUCE food), this one spends 2 food and produces no food (food_out=0);
   its only effect is the banked bonus point. This entry is what puts the buy
   on the feed frame's offer list, beside the payment decision — and its
   conversion_id is the shared budget's key.
2. **The free-span window surface** — ``register_free_span_trigger`` puts an
   optional FireTrigger on every free-span event (the in-span simple windows,
   the FIELD during-window, the breed frame's pre-commit stretch), so the point
   can be bought at any moment of the harvest span, not only during feeding.

Either surface's fire marks the shared budget, withholding the other for the
rest of that harvest: one buy per harvest TOTAL.

Timing — user ruling 36 (2026-07-12), verbatim: "The anytime food→resources /
food→points buys are FREE-SPAN: available throughout the harvest span (field
phase through end-of-harvest), NOT anchored to the last in-harvest moment. This
DROPS the previously-approved late-anchor approach... Consequence: Furniture
Carpenter migrates off its FEED-only seam to free-span". The earlier shape —
the buy surfaced ONLY during HARVEST_FEED via the conversion seam — is
superseded by this ruling; the seam entry survives as surface (1) above, the
budget home and the payment-frame offer.

User ruling 37 (2026-07-12): a points-output buy is a standalone free-span
trigger, never folded into the payment frontier — so the spec's
``frontier_fire`` stays None (the buy is never a row of the CommitConvert
Pareto frontier, and never reachable through the generalized raise frame).

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each buy increments a per-card CardStore counter (banked across all six
harvests), and the scoring term reads the count back at end-game.

"the Joinery or an upgrade thereof": in this engine the ten majors are distinct
and there is no upgraded Joinery (Pottery and the Basketmaker's Workshop are
separate crafts, not Joinery upgrades), so the condition is "any player owns the
Joinery" — major improvement index 7. (User ruling 2026-07-02: no upgrade of
Joinery currently exists, so the Joinery-only check is correct as printed.) The conversion enumerator gates only on
is_owned_fn, so the eligibility check MUST also confirm this player actually owns
the occupation (registrations are global) — otherwise the buy would be offered to
the non-owner. The free-span trigger's eligibility reuses the same check.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "furniture_carpenter"

# The Joinery is major improvement index 7 (see harvest_conversions.py).
_JOINERY_MAJOR_IDX = 7


def _eligible(state: GameState, idx: int) -> bool:
    """True iff this player owns Furniture Carpenter AND any player owns the
    Joinery (major idx 7).

    The conversion enumerator (legality.py) gates only on is_owned_fn, and
    registrations are global, so the occupation-ownership check must live here —
    otherwise the buy-a-point would be offered to the non-owner.
    """
    if CARD_ID not in state.players[idx].occupations:
        return False
    return state.board.major_improvement_owners[_JOINERY_MAJOR_IDX] is not None


def _award(state: GameState, idx: int) -> GameState:
    """side_effect_fn: bank one bonus point (incremented per harvest, up to 6)."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


def _window_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Free-span trigger gate: the seam conditions (_eligible — owns the
    occupation + any player owns the Joinery) plus the two checks the FEED
    enumerator performs itself but the window machinery does not: the shared
    once-per-harvest budget is unused, and the 2-food cost is affordable."""
    p = state.players[idx]
    return (
        _eligible(state, idx)
        and CARD_ID not in p.harvest_conversions_used
        and p.resources.food >= 2
    )


def _window_buy(state: GameState, idx: int) -> GameState:
    """Free-span fire: spend 2 food, bank +1 point, and mark the SHARED
    once-per-harvest budget (`harvest_conversions_used`, the same key the
    feed-seam CommitHarvestConversion executor writes) so neither surface
    offers the buy again this harvest — one buy per harvest TOTAL."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=-2),
        harvest_conversions_used=p.harvest_conversions_used | {CARD_ID},
    )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return _award(state, idx)


# Pure-conversion occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Surface 1 — the FEED payment frame: spend 2 food, produce no food, bank +1
# point. The conversion_id is also the shared once-per-harvest budget's key.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(food=2),
    food_out=0,
    is_owned_fn=_eligible,
    side_effect_fn=_award,
))

# Surface 2 — the free-span windows (ruling 36, 2026-07-12): the same buy as an
# optional trigger on every free-span event, sharing surface 1's budget.
register_free_span_trigger(CARD_ID, _window_eligible, _window_buy)

register_scoring(CARD_ID, _score)
