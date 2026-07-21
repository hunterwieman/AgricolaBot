"""Cooking-rate modifiers — the card seam on `helpers.cooking_rates`.

`helpers.cooking_rates(state, idx)` computes the player's at-any-time
goods->food conversion rates `(sheep, boar, cattle, veg)` from the best cooking
improvement they own (Cooking Hearth > Fireplace > none). Cards that modify how
cooking itself works (the ruling-42 cooking-modifier class) register here; the
fold is applied by `apply_cooking_rate_bonuses`, called at the end of
`cooking_rates` — the single chokepoint every consumer (the feed/liquidation/
overflow/breeding frontiers, the work-phase cook sites) reads rates through, so
a registered bonus flows into all of them with no per-consumer wiring.

Cache safety (CARD_ENGINE_IMPLEMENTATION.md §5.4): every memoized frontier
takes the rates as explicit ARGUMENTS (part of its projection key), so a
card-modified rate produces a different key by construction — no staleness.

The first (and so far only) member is **Fatstock Stretcher** (D56): +1 food per
sheep/boar cooked via a cooking improvement, i.e. +1 to the sheep and boar
rates — but ONLY where that conversion already exists (user ruling 2026-07-21:
(2,2,3) -> (3,3,3), (0,0,0) stays (0,0,0), (3,0,5) -> (4,0,5)). That
only-where-available guard lives in the CARD's bonus_fn (it reads the base
rates), not in this fold: a future member might legitimately *create* a rate
(Oriental Fireplace / Earth Oven are themselves cooking improvements — still
parked on the ruling-42 design pass; when built, they should inject through
this same chokepoint so additive bonuses compose automatically).

Family game: the registry is empty, `apply_cooking_rate_bonuses` returns the
base tuple unchanged (one truthiness check), and `cooking_rates` behaves
byte-identically — no C++ change.
"""
from __future__ import annotations

from typing import Callable

# card_id -> bonus_fn(state, owner_idx, base_rates) -> (d_sheep, d_boar, d_cattle, d_veg)
# The bonus_fn receives the BASE rates (post best-improvement selection, pre-fold)
# so a card can gate its delta on a conversion existing (Fatstock Stretcher's
# only-where-available guard). Deltas from all owned cards are summed.
COOKING_RATE_BONUSES: dict[str, Callable] = {}


def register_cooking_rate_bonus(card_id: str, bonus_fn: Callable) -> None:
    """Register `bonus_fn(state, owner_idx, base_rates) -> 4-tuple of deltas` for
    `card_id`. Applied (summed) whenever the card's owner's cooking rates are
    computed — the card must be PLAYED (in the tableau), not merely in hand."""
    COOKING_RATE_BONUSES[card_id] = bonus_fn


def apply_cooking_rate_bonuses(
    state, player_idx: int, base: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Fold every owned registered bonus over the base rates. Empty registry
    (the Family game) → `base` unchanged."""
    if not COOKING_RATE_BONUSES:
        return base
    p = state.players[player_idx]
    owned = p.occupations | p.minor_improvements
    s, b, c, v = base
    for card_id, bonus_fn in COOKING_RATE_BONUSES.items():
        if card_id not in owned:
            continue
        ds, db, dc, dv = bonus_fn(state, player_idx, base)
        s, b, c, v = s + ds, b + db, c + dc, v + dv
    return (s, b, c, v)
