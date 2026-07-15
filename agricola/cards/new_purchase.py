"""New Purchase (minor improvement, B70; Bubulcus Expansion; free).

Card text (verbatim): "Before the start of each round that ends with a harvest,
you can buy one of each of the following crops: 2 Food → 1 Grain; 4 Food → 1
Vegetable"

No cost, no prerequisite, not passing, no printed VPs.

Category: a preparation-ladder window trigger — an OPTIONAL `before_round`
play-variant trigger (the Forest Trader per-route shape, hosted on the
`before_round` window like Civic Facade's income).

- **Timing.** "Before the start of each round" → the preparation ladder's FIRST
  rung, `before_round` (user ruling 2026-07-14; Civic Facade). At that window
  `round_number` still names the just-completed round, so the round being entered
  is `round_number + 1`; "each round that ends with a harvest" gates eligibility on
  `round_number + 1 ∈ HARVEST_ROUNDS` (rounds 4/7/9/11/13/14).

- **Optional + a choice.** "you can buy one of each of the following crops" — up to
  one grain AND up to one vegetable, in a single decision. Modeled as a
  play-variant trigger (declined by the window host's Proceed), with the routes:
    - `grain` — 2 food → 1 grain (needs ≥ 2 food),
    - `veg`   — 4 food → 1 vegetable (needs ≥ 4 food),
    - `both`  — 6 food → 1 grain + 1 vegetable (needs ≥ 6 food).
  The `both` route is what makes "one of EACH" reachable: the window frame's
  `triggers_resolved` allows only one fire per round, so buying both crops must be
  a single combined route. Goods-only (food → crops); nothing to accommodate.

`PendingCardChoice` is deliberately NOT used — it has no decline, and this whole
option is declinable; the play-variant path carries the decline at the window's
Proceed. Card-only registries; the Family game is byte-identical.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "new_purchase"

# route -> (food spent, resources gained)
_ROUTES = {
    "grain": Resources(food=-2, grain=1),
    "veg":   Resources(food=-4, veg=1),
    "both":  Resources(food=-6, grain=1, veg=1),
}


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The affordable crop-buy routes. Empty -> the trigger is not offered."""
    food = state.players[idx].resources.food
    variants: list[str] = []
    if food >= 2:
        variants.append("grain")
    if food >= 4:
        variants.append("veg")
    if food >= 6:
        variants.append("both")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "each round that ends with a harvest": the round being ENTERED (round_number
    # + 1, since before_round precedes the round-number increment) is a harvest round.
    return ((state.round_number + 1) in HARVEST_ROUNDS
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _ROUTES[variant])
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _action_label(variant: str):
    return {
        "grain": "buy 1 grain (2 food)",
        "veg":   "buy 1 vegetable (4 food)",
        "both":  "buy 1 grain + 1 vegetable (6 food)",
    }.get(variant)


register_minor(CARD_ID)
register("before_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_labeler(CARD_ID, _action_label)
