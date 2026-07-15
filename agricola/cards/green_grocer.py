"""Green Grocer (occupation, Corbarius C103; players 1+).

Card text: "At the start of each round, you can make exactly one of the following
exchanges: 1 Cattle → 1 Vegetable; 1 Vegetable → 1 Cattle; 2 Sheep → 1 Vegetable;
1 Vegetable → 2 Sheep; 2 Food → 1 Grain; 1 Grain → 2 Food"

User decision (2026-07-14): the six exchanges are surfaced WIDE — one
FireTrigger(card_id, variant=...) per currently-affordable exchange (the standard
start-of-round play-variant expansion, Scholar's shape), not a nested choice frame.

A start-of-round OPTIONAL play-variant trigger on the preparation ladder's
`start_of_round` window (ruling 54, 2026-07-14): the window's choice host surfaces
one FireTrigger per affordable exchange; "do none" = the host's Proceed. "Exactly
one" exchange per round = the host frame's `triggers_resolved` (one fire per host
visit — automatic) + the `used_this_round` latch (cleared at each round entry, so
next round offers again) — Scholar's once-per-round shape, mirrored.

Spends are direct edits (animals straight off `p.animals` — discarding animals is
free at any time; goods off `p.resources`). Animal GAINS route through
`helpers.grant_animals` (veg_to_cattle: +1 cattle; veg_to_sheep2: +2 sheep) so the
accommodation barrier surfaces the keep-which choice when the farm can't house
them. On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "green_grocer"

# The six printed exchanges, in card-text order. Each variant maps to
# (affordability predicate over the player, direct player edit, animal grant).
_VARIANTS = (
    "cattle_to_veg",   # 1 Cattle  → 1 Vegetable
    "veg_to_cattle",   # 1 Vegetable → 1 Cattle
    "sheep2_to_veg",   # 2 Sheep   → 1 Vegetable
    "veg_to_sheep2",   # 1 Vegetable → 2 Sheep
    "food2_to_grain",  # 2 Food    → 1 Grain
    "grain_to_food2",  # 1 Grain   → 2 Food
)


def _affordable(p, variant: str) -> bool:
    """Can player-state `p` pay the variant's input right now?"""
    if variant == "cattle_to_veg":
        return p.animals.cattle >= 1
    if variant == "veg_to_cattle":
        return p.resources.veg >= 1
    if variant == "sheep2_to_veg":
        return p.animals.sheep >= 2
    if variant == "veg_to_sheep2":
        return p.resources.veg >= 1
    if variant == "food2_to_grain":
        return p.resources.food >= 2
    if variant == "grain_to_food2":
        return p.resources.grain >= 1
    raise ValueError(f"unknown Green Grocer variant {variant!r}")


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The exchanges affordable right now, in card-text order. Empty → nothing
    to exchange this round (the trigger is withheld)."""
    p = state.players[idx]
    return [v for v in _VARIANTS if _affordable(p, v)]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Latch once-per-round, pay the exchange's input directly, then grant the
    output — goods directly, animals via `grant_animals` (the accommodation
    barrier reconciles overflow at the next decision boundary)."""
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    if variant == "cattle_to_veg":
        p = fast_replace(p, animals=p.animals - Animals(cattle=1),
                         resources=p.resources + Resources(veg=1))
    elif variant == "sheep2_to_veg":
        p = fast_replace(p, animals=p.animals - Animals(sheep=2),
                         resources=p.resources + Resources(veg=1))
    elif variant == "food2_to_grain":
        p = fast_replace(p, resources=p.resources
                         - Resources(food=2) + Resources(grain=1))
    elif variant == "grain_to_food2":
        p = fast_replace(p, resources=p.resources
                         - Resources(grain=1) + Resources(food=2))
    elif variant in ("veg_to_cattle", "veg_to_sheep2"):
        p = fast_replace(p, resources=p.resources - Resources(veg=1))
    else:
        raise ValueError(f"unknown Green Grocer variant {variant!r}")
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    if variant == "veg_to_cattle":
        state = grant_animals(state, idx, Animals(cattle=1))
    elif variant == "veg_to_sheep2":
        state = grant_animals(state, idx, Animals(sheep=2))
    return state


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
