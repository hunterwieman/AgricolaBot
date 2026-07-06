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
k in 1..(N2+N3) with cost(k) = 2*min(k, N2) + 3*max(0, k − N2), offered only
while affordable (cost(k) <= food). Choosing k in ONE fire is exact, not an
approximation: nothing changes between successive buys within one occasion (a buy
neither harvests nor empties anything), so the one-shot k loses no information
against buying one vegetable at a time.

ONCE PER OCCASION comes from the host frame's `triggers_resolved`: the k is
chosen at the fire and the card is marked resolved for that occasion. A later
occasion — a card-granted additional harvest, the next harvest's take — hosts
afresh, as "for each grain you harvest" requires.

COST — the occasion-trigger machinery carries no cost layer (the Farm Store /
Winter Caretaker precedent), so `_apply` debits the food and grants the
vegetables in one step; `_variants` / `_eligible` enforce affordability so no
unaffordable k is ever offered.

Card-game only (occupation + occasion-trigger registries, both ownership-gated;
no CardStore use): the Family game is byte-identical and the C++ gates are
untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_trigger
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
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
    """One variant per affordable vegetable count k in 1..(n2+n3)."""
    n2, n3 = _buy_counts(occasion)
    food = state.players[idx].resources.food
    return [str(k) for k in range(1, n2 + n3 + 1) if _cost(k, n2) <= food]


def _eligible(state: GameState, idx: int, occasion) -> bool:
    """Grain was harvested this occasion AND at least one buy is affordable —
    exactly 'some variant exists' (no grain harvested => the k-range is empty)."""
    return bool(_variants(state, idx, occasion))


def _apply(state: GameState, idx: int, occasion, variant: str) -> GameState:
    """Buy k vegetables: debit cost(k) food, gain k vegetables from the general
    supply (no cost layer on occasion triggers — the food is debited here)."""
    k = int(variant)
    n2, _n3 = _buy_counts(occasion)
    p = state.players[idx]
    p = fast_replace(
        p, resources=p.resources - Resources(food=_cost(k, n2)) + Resources(veg=k))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_harvest_occasion_trigger(CARD_ID, _eligible, _apply, variants_fn=_variants)
