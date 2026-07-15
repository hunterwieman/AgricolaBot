"""Twibil (minor improvement, E49; Ephipparius Expansion; players -).

Card text: "Each time after any player (including you) builds at least 1 wood
room, you get 1 food."
Cost: 1 Stone. VPs: 1.

Category: Food Provider, opponent-action hook. "any player (including you)" ->
an automatic effect registered with `any_player=True`, so it fires for its OWNER
even on the opponent's room build (owner routing lives in `apply_auto_effects`).
"you get 1 food" is mandatory and choice-free -> `register_auto`, never a
FireTrigger (ruling 21, 2026-07-05: a mandatory choice-free effect is an AUTO).

Timing / event: "after ... builds at least 1 wood room" -> `after_build_rooms`,
the build-rooms host's after-window. That event fires exactly ONCE per
build-rooms session, and only when >= 1 room was actually built (the Proceed flip
requires ``num_built >= 1``) -- so "at least 1 room" is satisfied precisely when
the hook fires at all, and no before/after snapshot is needed. The grant is a
FLAT +1 food regardless of how many rooms were built.

"WOOD room": all of a player's rooms share one material (`PlayerState`.
``house_material``; rooms always match the current house), so a room built while
the builder's house is WOOD is a wood room. `after_build_rooms` fires with the
BUILDER as the frame's ``player_idx``, which during a worker placement is the
active player -- so ``state.current_player`` is the builder. Under
``any_player=True`` the ``idx`` handed to these fns is the OWNER; the builder is
read separately as ``state.current_player``. Building rooms never changes
``house_material`` (only renovation does), so the builder's house material at the
after-hook is exactly the material the just-built rooms were made of.

Played via an improvement space; on_play is a no-op (the hook is the whole card).
Mirrors the Milk Jug ``any_player=True`` owner-routing pattern and the Roughcaster
``after_build_rooms`` / ``house_material`` build hook.
"""
from __future__ import annotations

from agricola.constants import HouseMaterial
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "twibil"


def _eligible(state: GameState, idx: int) -> bool:
    """`idx` is the OWNER (any_player). Fire whenever the just-built rooms were
    WOOD rooms -- i.e. the BUILDER's house is wood. The builder is the active
    player (``current_player``); all their rooms share ``house_material``, so a
    wood house at this after-hook means wood rooms were built."""
    return state.players[state.current_player].house_material == HouseMaterial.WOOD


def _apply(state: GameState, idx: int) -> GameState:
    """Grant a flat 1 food to the owner (`idx`), regardless of how many rooms
    were built."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(stone=1)), vps=1)
register_auto("after_build_rooms", CARD_ID, _eligible, _apply, any_player=True)
