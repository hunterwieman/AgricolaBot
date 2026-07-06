"""Beer Stall (minor improvement, C49; Corbarius Expansion; Food Provider).

Card text (verbatim): "In the feeding phase of each harvest, for each empty
unfenced stable you have, you can exchange 1 grain for 5 food."
Cost: 1 Wood. No prerequisite, no printed VPs.

**The count is a chosen outcome — user ruling 30 (2026-07-06, superseding the
same-day defer).** Animals are not location-tracked, so "each empty unfenced
stable" is read after the player freely rearranges AND may cook/release
animals to empty stables. The user's design: **a Pareto frontier over animal
counts PER grain-conversions-TAKEN k** (taken, not offered — options with
different k never dominate each other: more conversions is more food and less
grain, and neither is a frontier dimension), with the k exchanges BUNDLED
INTO each option alongside the cooking — which is what dissolves the original
defer's cook-first sequencing problem: nothing is sequenced through the
feeding flow, one commit does it all.

An option = (kept animals, k) where:
- 1 <= k <= min(unfenced stables, grain supply), and
- the kept animals fit the farm with k unfenced stables left EMPTY — tested
  by blanking k standalone-stable cells (the k-stable generalization of
  Shepherd's Whistle's doctored-farm technique; standalone stables are
  interchangeable for capacity, so WHICH k doesn't matter) through the
  ownership-aware `accommodates` (a Dolly's Mother sheep-slot composes).

Firing an option cooks the released animals at the player's rates, pays k
grain, and grants 5k food. Declining is the seam's implicit decline —
`CommitConvert` without firing — the user's "(current animals, 0
conversions)" point. Within one k, animals-only dominance is exact (same
rates: food differences equal the deferred cook-value of the animal
difference); across k, options are never compared.

TIMING (the user's 2026-07-06 clarification): the exchange fires in the feed
frame's craft window, BEFORE the final `CommitConvert` payment — so the 5k
food (and the cook proceeds) pay this same feeding. Realized on the
conversion-variants seam (`HarvestConversionSpec.variants_fn`, the Craft
Brewery machinery): `input_cost` is zero (the k grain is variant-dependent,
debited by the side effect), `food_out` 0 (the 5k likewise); once per
feeding phase via `harvest_conversions_used`, the k choice carrying the
multiplicity.

Card-only registries; the Family game is byte-identical.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.constants import CellType
from agricola.helpers import accommodates, cooking_rates
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "beer_stall"


def _without_k_standalone_stables(state: GameState, idx: int, k: int):
    """A doctored PlayerState with k standalone (unfenced) STABLE cells
    blanked — the farm on which "k unfenced stables stay empty" becomes an
    ordinary fit test. None when the player has fewer than k of them.
    Standalone stables are interchangeable for capacity (the Shepherd's
    Whistle argument), so the first k in scan order stand for any k."""
    p = state.players[idx]
    enclosed = {cell for past in p.farmyard.pastures for cell in past.cells}
    blanked = 0
    grid = [list(row) for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if (blanked < k
                    and grid[r][c].cell_type == CellType.STABLE
                    and (r, c) not in enclosed):
                grid[r][c] = fast_replace(grid[r][c], cell_type=CellType.EMPTY)
                blanked += 1
    if blanked < k:
        return None
    return fast_replace(p, farmyard=fast_replace(
        p.farmyard, grid=tuple(tuple(row) for row in grid)))


def _options(state: GameState, idx: int) -> list:
    """The surviving (kept_animals, k, cook_food) options: for each k in
    1..min(unfenced stables, grain), the animals-Pareto keep-sets that fit
    with k stables blanked. Small cold-path enumeration (the card-local
    constrained-frontier idiom — Mineral Feeder / Shepherd's Whistle)."""
    p = state.players[idx]
    cur = p.animals
    k_max = min(count_unfenced_stables(p.farmyard), p.resources.grain)
    if k_max < 1:
        return []
    sR, bR, cR = cooking_rates(state, idx)[:3]
    out = []
    for k in range(1, k_max + 1):
        reduced = _without_k_standalone_stables(state, idx, k)
        if reduced is None:
            continue
        fitting = [
            Animals(sheep=s, boar=b, cattle=c)
            for s in range(cur.sheep + 1)
            for b in range(cur.boar + 1)
            for c in range(cur.cattle + 1)
            if accommodates(reduced, s, b, c)
        ]

        def dominates(x: Animals, y: Animals) -> bool:
            return (x.sheep >= y.sheep and x.boar >= y.boar
                    and x.cattle >= y.cattle and x != y)

        for kept in fitting:
            if any(dominates(o, kept) for o in fitting):
                continue
            food = ((cur.sheep - kept.sheep) * sR
                    + (cur.boar - kept.boar) * bR
                    + (cur.cattle - kept.cattle) * cR)
            out.append((kept, k, food))
    return out


def _variants(state: GameState, idx: int) -> list[str]:
    """One variant per surviving option: "k<k>s<n>b<n>c<n>" (the kept-animal
    vector plus the conversions taken)."""
    return [f"k{k}s{a.sheep}b{a.boar}c{a.cattle}"
            for a, k, _food in _options(state, idx)]


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Resolve the chosen option in one step: keep the encoded animals (cook
    the released at the player's rates), pay k grain, gain 5k food."""
    for a, k, food in _options(state, idx):
        if f"k{k}s{a.sheep}b{a.boar}c{a.cattle}" == variant:
            p = state.players[idx]
            p = fast_replace(
                p, animals=a,
                resources=p.resources + Resources(grain=-k, food=food + 5 * k))
            return fast_replace(
                state,
                players=tuple(p if i == idx else state.players[i]
                              for i in range(2)))
    raise AssertionError(f"beer_stall variant {variant!r} not offered")


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(),          # the k grain rides the variant's apply
    food_out=0,                      # the 5k food likewise
    is_owned_fn=lambda state, idx: CARD_ID in state.players[idx].minor_improvements,
    side_effect_fn=_apply,
    variants_fn=_variants,
))
