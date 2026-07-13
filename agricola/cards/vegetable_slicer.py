"""Vegetable Slicer (minor improvement, A41; Artifex Expansion; cost 1 wood).

Card text (verbatim): "Each time you upgrade a Fireplace to a Cooking Hearth, you
immediately get 2 wood and 1 vegetable (not retroactively)."
No prerequisite, no printed VPs.

Timing/mechanism — "upgrade a Fireplace to a Cooking Hearth" is, precisely, the
Major/Minor Improvement route that builds a Cooking Hearth by RETURNING a
Fireplace (RULES.md: "A Cooking Hearth is an upgrade of a Fireplace: … return a
Fireplace you built to take a Cooking Hearth"). Building a Cooking Hearth from
CLAY keeps the Fireplace and is NOT an upgrade, so this card must NOT fire there.
The discriminator (a `ReturnImprovement` payment on the build) lives only on the
commit and is gone before `after_build_major`, so the engine exposes a dedicated
`upgrade_to_cooking_hearth` event fired at the return-Fireplace branch of
`_execute_build_major` (resolution.py). This card is a mandatory, choice-free
`register_auto` on that event: +2 wood + 1 vegetable, pure goods (Category 3).

"(not retroactively)": a build-event hook fires only on the ACT of upgrading, so
a Cooking Hearth already owned when Vegetable Slicer is played never triggers —
the clarification is satisfied structurally, no latch needed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "vegetable_slicer"


def _eligible(state: GameState, idx: int) -> bool:
    # Ownership and "an upgrade just happened" are both gated by the event itself
    # (apply_auto_effects checks ownership; the event fires only at the upgrade),
    # so the effect is unconditional once the event fires for this owner.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=2, veg=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("upgrade_to_cooking_hearth", CARD_ID, _eligible, _apply)
