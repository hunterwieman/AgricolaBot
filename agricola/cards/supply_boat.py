"""Supply Boat (minor improvement, D73; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "Each time after you use the 'Fishing' accumulation space,
you can choose to buy 1 grain for 1 food, or 1 vegetable for 3 food."

Cost: 1 Wood. Prerequisite: 1 Occupation. Printed 1 VP. Not a passing card.
(No errata or clarifications in the card data.)

An OPTIONAL play-variant trigger on the atomic 'Fishing' accumulation space — the
one card-shape that surfaces a *choice between two routes* (buy grain OR buy
vegetable) rather than a single grant.

TIMING — `after_action_space`. The text's "Each time AFTER you use Fishing" is the
explicit "immediately after" exception to the default "each time you use [space]" =
before ruling (the same exception Carpenter's Axe / Wood Cutter rely on), so it
rides the after-phase frame, firing only once Fishing's own pickup (+1 food) has
already happened. That ordering is correct: the food the player pays with may
include this turn's catch.

OPTIONALITY — `register` (NOT `register_auto`). "You can choose to buy" is a
declinable choice, so it is an optional FireTrigger; the decline path is the
host's after-phase `Stop` (reached by simply NOT firing the trigger). Because
declining must always be possible, the variant enumerator gates each route on
AFFORDABILITY (food >= 1 for grain, food >= 3 for vegetable) so a dead-end fire is
never surfaced — with neither route affordable, no FireTrigger is offered and the
after-phase `Stop` is the only action.

THE OR — the "buy grain OR buy vegetable" choice is collapsed INTO the fire via
`register_play_variant_trigger` (like Cottager's room-vs-renovate, Scholar's
occupation-vs-minor): the after-phase host expands this card's one trigger into a
distinct `FireTrigger("supply_boat", variant="grain")` / `variant="vegetable"` per
currently-affordable route, and `_apply` takes the chosen variant. This is a
play-variant in the trigger EFFECT, not a "/" alternative in the minor's purchase
cost (which is a flat 1 wood), so it is fully supported.

APPLY — a direct resource swap with NO push (buy exactly one good): grain route
-1 food / +1 grain; vegetable route -3 food / +1 vegetable. There is no sub-frame
or resolver, mirroring Potter Ceramics' direct exchange (but variant-threaded).

"Each time" = at most once per Fishing use, enforced by the host frame's
`triggers_resolved` (handled by `_apply_fire_trigger`): each new Fishing use pushes
a fresh PendingActionSpace with an empty `triggers_resolved`, so the card
re-becomes eligible on the next use. Fishing is an ATOMIC accumulation space, so it
must be explicitly hosted (`register_action_space_hook`) to push a frame whose
after-phase surfaces this trigger. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "supply_boat"
SPACES = frozenset({"fishing"})

# Printed prices: 1 grain for 1 food; 1 vegetable for 3 food.
_GRAIN_PRICE = 1
_VEG_PRICE = 3


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The buy routes Supply Boat can currently afford: 'grain' when food >= 1,
    'vegetable' when food >= 3 (the printed prices). Empty list -> nothing to buy
    this use (so no FireTrigger is offered and the host's after-phase Stop is the
    only action — i.e. declining is the sole option)."""
    food = state.players[idx].resources.food
    variants: list[str] = []
    if food >= _GRAIN_PRICE:
        variants.append("grain")
    if food >= _VEG_PRICE:
        variants.append("vegetable")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # after_action_space on the fishing host. Ownership + once-per-use
    # (triggers_resolved) are already gated by _eligible_fire_triggers; here we only
    # check the space and that at least one route is affordable.
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Buy exactly one good — the chosen route's direct resource swap, no push."""
    if variant == "grain":
        swap = Resources(food=-_GRAIN_PRICE, grain=1)
    else:  # "vegetable"
        swap = Resources(food=-_VEG_PRICE, veg=1)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + swap)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               min_occupations=1, vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_space_hook(CARD_ID, SPACES)
