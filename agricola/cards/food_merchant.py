"""Food Merchant (occupation, D113; Dulcinaria Expansion; players 1+).

Card text (verbatim): "For each grain you harvest from a field, you can buy 1
vegetable for 3 food. If you harvest the last grain from a field, the vegetable
costs you only 2 food."

Category: Crop Provider. Played via Lessons; the on-play is a no-op — the effect
is a standing reaction to the player's own harvesting.

WHAT THE CARD DOES. Whenever the player harvests grain from their fields, each
grain harvested unlocks the option to buy 1 vegetable (from the general supply)
for 3 food — except that a grain which was a field's LAST grain prices its buy at
2 food instead. Every buy is optional ("you can").

TIMING — an UNSCOPED per-occasion trigger (`register_harvest_occasion_trigger`,
`agricola/cards/harvest_windows.py`; HARVEST_WINDOWS_DESIGN.md §4d). Per user
ruling 12 (2026-07-04): "you harvest from a field" is unscoped harvest-verb
wording — there is no "in the field phase of each harvest" anchor — so the card
reacts to ANY harvesting occasion: a real harvest's field-phase take
(`occasion.source == "take"`) AND a card-played field-phase effect (Bumper Crop's
mid-WORK `source="card:bumper_crop"` occasion) alike. The gate is the occasion
itself, never `state.phase`. Right after an occasion's automatic consequences
fire, the engine pushes the `PendingHarvestOccasion` host whenever this card is
owned and eligible; the buys surface there as `FireTrigger` variants and
`Proceed` declines.

COUNTING (the counting doctrine, `harvest_windows.py` occasion-registry header):

- "For each GRAIN you harvest from a field" counts grain UNITS — the sum of the
  occasion's grain-entry amounts — one buy unlocked per unit.
- "If you harvest the LAST grain from a field" is per EMPTIED grain entry: each
  manifest entry is one FIELD, so exactly ONE of an emptied entry's units is that
  field's last grain. An emptied 2-grain entry (e.g. a take-modifier folding an
  extra unit into the same take) unlocks one 2-food buy plus one 3-food buy.

So per occasion: N2 = the number of emptied grain entries (discounted 2-food
buys) and N3 = total grain units − N2 (full-price 3-food buys).

THE VARIANT SET — one variant per vegetable COUNT k, priced cheapest-first. The
raw choice space is which subset of the N2 + N3 unlocked buys to exercise, but
surfacing every (2-food, 3-food) split would offer strictly-dominated actions:
for a fixed number of vegetables k, filling the discounted buys first is strictly
cheaper, and any other split yields the same k vegetables for more food — Pareto
dominance over the outcome pair (vegetables gained, food spent) prunes those
splits loss-lessly (the legality-shaping principle of CLAUDE.md Foundations; no
strategically meaningful option is discarded). The variants are therefore exactly
k in 1..(N2+N3) with cost(k) = 2*min(k, N2) + 3*max(0, k − N2). Choosing k in ONE
fire is exact, not an approximation: nothing changes between successive buys
within one occasion (a buy neither harvests nor empties anything), so the
one-shot k loses no information against buying one vegetable at a time.

PAYMENT (ruling 82, 2026-07-26; this card shipped with a plain food-on-hand gate
and was corrected 2026-07-27): cost(k) is payable by ANY legal route — food on
hand OR raised by the at-any-time crop/animal conversions — so a count k is
offered iff ITS OWN cost(k) is raise-able (`_liquidatable_to`; the grain the
take just delivered is itself legal fuel). Firing buys directly when the food is
on hand; short of it, the fire STASHES `(occasion, k)` in CardStore (the Sheep
Inspector dynamic-payload idiom — the chosen k and its occasion cannot ride a
static resume kind, and the occasion is not otherwise reconstructible at resume
time) and pushes the raise-only `PendingFoodPayment` for cost(k); the resume
pops the stash, recomputes the same cost off the stashed occasion, debits it,
and grants the k vegetables. The buy reserves nothing — its only cost is the
food being raised.

ONCE PER OCCASION comes from the host frame's `triggers_resolved`: the k is
chosen at the fire and the card is marked resolved for that occasion. A later
occasion — a card-granted additional harvest, the next harvest's take — hosts
afresh, as "for each grain you harvest" requires.

Card-game only (occupation + occasion-trigger registries, ownership-gated; the
CardStore entry exists only between a food-short fire and its resume): the
Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.harvest_windows import register_harvest_occasion_trigger
from agricola.cards.specs import (
    register_food_payment_resume,
    register_occupation,
)
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "food_merchant"


def _buy_counts(occasion) -> tuple[int, int]:
    """(n2, n3) — the discounted 2-food buys and the full-price 3-food buys this
    occasion unlocks. n2 = emptied grain entries (each entry is one FIELD, so
    exactly one of an emptied entry's units is that field's last grain); n3 =
    the remaining grain units (sum of grain-entry amounts, minus n2)."""
    units = sum(e.amount for e in occasion.entries if e.crop == "grain")
    n2 = sum(1 for e in occasion.entries if e.crop == "grain" and e.emptied)
    return n2, units - n2


def _cost(k: int, n2: int) -> int:
    """The food cost of buying k vegetables, discounted buys filled first — the
    Pareto-minimal price for k (see the module docstring)."""
    return 2 * min(k, n2) + 3 * max(0, k - n2)


def _variants(state: GameState, idx: int, occasion) -> list[str]:
    """One variant per vegetable count k in 1..(n2+n3) whose OWN cost(k) is
    raise-able — food on hand or the at-any-time conversions (ruling 82)."""
    n2, n3 = _buy_counts(occasion)
    p = state.players[idx]
    return [str(k) for k in range(1, n2 + n3 + 1)
            if _liquidatable_to(state, idx, p, Resources(food=_cost(k, n2)))]


def _eligible(state: GameState, idx: int, occasion) -> bool:
    """Grain was harvested this occasion AND at least one buy is payable —
    exactly 'some variant exists' (no grain harvested => the k-range is empty)."""
    return bool(_variants(state, idx, occasion))


def _buy(state: GameState, idx: int, k: int, n2: int) -> GameState:
    """Buy k vegetables: debit cost(k) food, gain k vegetables from the general
    supply. Reached directly (food on hand) and via `_resume` after a raise (the
    raise-only frame leaves the raised food in supply to debit)."""
    p = state.players[idx]
    p = fast_replace(
        p, resources=p.resources - Resources(food=_cost(k, n2)) + Resources(veg=k))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _apply(state: GameState, idx: int, occasion, variant: str) -> GameState:
    """Fire one buy of k vegetables. With cost(k) food on hand, buy directly;
    otherwise stash (occasion, k) in CardStore — the count is DYNAMIC and the
    occasion is not reconstructible at resume time, so neither can ride a static
    resume_kind (the Sheep Inspector idiom) — and push the raise-only
    PendingFoodPayment for cost(k); the resume pops the stash and runs the same
    buy. A raise bundle only converts supply goods to food, so the stashed
    occasion's counts (and hence the debited cost) are the ones gated on here."""
    k = int(variant)
    n2, _n3 = _buy_counts(occasion)
    if state.players[idx].resources.food >= _cost(k, n2):
        return _buy(state, idx, k, n2)
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, (occasion, k)))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_cost(k, n2),
        resume_kind=CARD_ID, reserved=Cost(),
    ))


def _resume(state: GameState, idx: int) -> GameState:
    """The post-raise continuation: pop the stashed (occasion, k) and buy."""
    p = state.players[idx]
    stashed = p.card_state.get(CARD_ID)
    assert stashed is not None, "food_merchant resume without a stashed buy"
    occasion, k = stashed
    p = fast_replace(p, card_state=p.card_state.remove(CARD_ID))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    n2, _n3 = _buy_counts(occasion)
    return _buy(state, idx, k, n2)


def _action_label(variant: str) -> str | None:
    """Web-UI label for a buy-count variant (mechanical, terse): "buy 2 veg".
    The food price is NOT in the variant string (cost(k) depends on the
    occasion's discounted-buy count n2), so the label states only the count —
    a price would need state this labeler deliberately has no access to."""
    if not variant.isdigit():
        return None
    return f"buy {int(variant)} veg"


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_harvest_occasion_trigger(CARD_ID, _eligible, _apply, variants_fn=_variants)
register_action_labeler(CARD_ID, _action_label)
register_food_payment_resume(CARD_ID, _resume)
