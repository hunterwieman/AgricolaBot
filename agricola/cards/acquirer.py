"""Acquirer (occupation, E102; Ephipparius Expansion; players 1+).

Card text (verbatim): "At the start of each round, you may pay food equal to the
number of people you have to buy 1 good of your choice from the general supply."

Category: a start-of-round play-variant trigger — the Scholar / Mineral Feeder
shape (an optional `start_of_round` trigger surfaced WIDE as one FireTrigger per
route, via `register_play_variant_trigger`), with the routes being the goods you
may buy (like Forest Trader's per-resource purchase variants).

- **Timing.** "At the start of each round" → the preparation ladder's
  `start_of_round` window. At that window last round's newborns have already become
  adults (`engine._enter_new_round` sets `newborns=0` at the earlier `__collect__`
  step), so `people_total` is exactly "the number of people you have".

- **Optional.** "you may" → declined by the window host's Proceed (no route fired).

- **Cost.** "pay food equal to the number of people you have" = `people_total` food.
  Every good is the same price, so the trigger is offered (all goods) exactly when
  the player can afford one (`food >= people_total`), and nothing otherwise.

- **"1 good of your choice from the general supply."** A *good* is any resource
  token (food included by definition — Emissary D124) or an **animal** (sheep /
  wild boar / cattle). One variant per good, **except food**: the price is
  `people_total` food (>= 1), so buying 1 food for >= 1 food is strictly
  dominated and never offered (user ruling 2026-07-15). One variant per remaining
  good. Resource goods are a direct debit-and-grant; an animal good routes through
  `helpers.grant_animals` so the accommodation barrier surfaces the keep-which
  choice on overflow (never a raw `p.animals + …`). Once per round comes from the
  window frame's `triggers_resolved` ("buy 1 good").

Played via Lessons; on-play is a no-op. Card-only registries — the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "acquirer"

# A "good" = any resource token or any animal. Food is a good (Emissary D124) but
# is NOT offered: the price is people_total food, so buying 1 food for >= 1 food is
# strictly dominated (user ruling 2026-07-15).
_RESOURCE_GOODS = ("wood", "clay", "reed", "stone", "grain", "veg")
_ANIMAL_GOODS = ("sheep", "boar", "cattle")
_GOODS = _RESOURCE_GOODS + _ANIMAL_GOODS


def _cost(state: GameState, idx: int) -> int:
    # "food equal to the number of people you have." At start_of_round the
    # newborns have already become adults, so people_total is the family count.
    return state.players[idx].people_total


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """Every good, when the player can afford the (uniform) food price; else none."""
    if state.players[idx].resources.food >= _cost(state, idx):
        return list(_GOODS)
    return []


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return bool(_legal_variants(state, idx))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Pay `people_total` food, gain 1 of the chosen good."""
    p = state.players[idx]
    paid = p.resources + Resources(food=-_cost(state, idx))
    if variant in _ANIMAL_GOODS:
        p = fast_replace(p, resources=paid)
        state = fast_replace(
            state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
        return grant_animals(state, idx, Animals(**{variant: 1}))
    p = fast_replace(p, resources=paid + Resources(**{variant: 1}))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _action_label(variant: str):
    return f"buy 1 {variant}" if variant in _GOODS else None


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_labeler(CARD_ID, _action_label)
