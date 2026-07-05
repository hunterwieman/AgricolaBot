"""Winnowing Fan (minor improvement, A61; Artifex Expansion; Food Provider).

Card text (verbatim): "After the field phase of each harvest, you can use a
baking improvement but only to turn exactly 1 grain into food. (This is not
considered a "Bake Bread" action.)"

Cost: 1 Reed. Prerequisite: "Baking Improvement" (owning one — a HAVE-check at
play time, never spent).

An `after_field_phase` (harvest window #7) optional trigger implemented as a
DIRECT best-rate conversion — **user ruling 2026-07-05**: rather than granting
a hook-suppressed 1-grain bake through the Bake Bread primitive, find the
owned baking improvement with the best conversion rate and offer 1 grain →
that many food. The two are outcome-identical: the bake executor allocates
grain greedily by rate, so a real 1-grain bake would use the best rate anyway,
and per-improvement variants would only surface strictly-dominated options
(the action-shaping principle). The printed parenthetical — this is NOT a
"Bake Bread" action — is satisfied structurally: the Bake Bread primitive is
never constructed, so no before/after-bake card hook (Dutch Windmill, Hand
Truck, Potter Ceramics, …) can fire.

The rate is read live from `baking_specs_for_player`, which includes the major
improvements (Fireplace 2, Cooking Hearth 3, Stone Oven 4, Clay Oven 5) and
any card-registered baking source — "use a baking improvement" is a live read
of the best owned source at fire time. Per-source bake CAPS are irrelevant at
1 grain (every source's cap is >= 1). Once per harvest via the window frame's
`triggers_resolved`; declining is `Proceed`.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "winnowing_fan"
WINDOW_ID = "after_field_phase"


def _best_rate(state: GameState, idx: int) -> int:
    """The best food-per-grain rate among the player's owned baking sources
    (0 when none owned)."""
    from agricola.legality import baking_specs_for_player
    specs = baking_specs_for_player(state, idx)
    return max((rate for _cap, rate in specs), default=0)


def _prereq(state: GameState, idx: int) -> bool:
    """"Baking Improvement" — the player owns at least one baking source."""
    return _best_rate(state, idx) > 0


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    # A grain to convert and a baking improvement to convert it with.
    return (state.players[idx].resources.grain >= 1
            and _best_rate(state, idx) > 0)


def _apply(state: GameState, idx: int) -> GameState:
    """Turn exactly 1 grain into food at the best owned baking rate."""
    rate = _best_rate(state, idx)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=-1, food=rate))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), prereq=_prereq)
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
