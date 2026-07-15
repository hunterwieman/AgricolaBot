"""Renovation Preparer (occupation, D123; Dulcinaria Expansion; players 1+).

Card text (verbatim): "For each new wood/clay room you build, you get 2 clay/2
stone." No clarifications printed.

Slash-correlation reading (settled classification, 2026-07-14 wave spec): the
reward slash pairs with the room-material slash —

- each new WOOD room you build → you get 2 clay;
- each new CLAY room you build → you get 2 stone;
- stone rooms → nothing.

Mechanics:

- **"New … room you build"** = a room built during the game (rooms are only ever
  built through the build_rooms sub-action — Farm Expansion, or any card grant
  that pushes `PendingBuildRooms`). The two starting rooms are never inside a
  build session, and a renovation converts rooms without *building* any, so
  neither ever pays.

- **The rooms' material is the builder's CURRENT house material** — rooms always
  match the house at build time, and a renovate can never happen inside a
  build-rooms action, so `house_material` read at the after-hook IS the material
  of every room this action built (the Rustic / Roughcaster reading).

- **Per room, per action — outcome-dependent → `after_build_rooms`.** The payout
  scales with how many rooms the action built, so it must read what the action
  produced (the guide's flat-before / outcome-dependent-after rule). Build Rooms
  is ONE action: the event fires once, at the host's Proceed work-complete flip
  (the deferred after-flip, user ruling 60, 2026-07-14), with the whole action's
  rooms paid in one payout. The `PendingBuildRooms` host frame is still on top
  when the after-autos fire, so the count is read directly from its `num_built`
  field (rooms committed this action) — no snapshot needed.

Mandatory, choice-free income → `register_auto` (fires for the owner only, so an
opponent's build pays nothing). Played via Lessons; its on-play is a no-op.
Card-only registries are untouched in the Family game, so it stays byte-identical
and the C++ differential gates are unaffected. See CARD_AUTHORING_GUIDE.md §2
("Build Rooms … is ONE action") and rustic.py / cubbyhole.py (the per-room
after_build_rooms payout family).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import HouseMaterial
from agricola.pending import PendingBuildRooms
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "renovation_preparer"

# Slash-correlation: house material at build time -> (reward field, per room).
_REWARD = {
    HouseMaterial.WOOD: ("clay", 2),
    HouseMaterial.CLAY: ("stone", 2),
    # HouseMaterial.STONE: nothing — stone rooms are outside the printed pairs.
}


def _rooms_built(state: GameState) -> int:
    """Rooms built by the current build-rooms action, read off the host frame.

    `after_build_rooms` fires from `_enter_after_phase` with the (just-flipped)
    `PendingBuildRooms` host still on top of the stack, so its `num_built` is the
    whole action's room count. The isinstance check is defensive only.
    """
    top = state.pending_stack[-1] if state.pending_stack else None
    return top.num_built if isinstance(top, PendingBuildRooms) else 0


def _eligible(state: GameState, idx: int) -> bool:
    # A wood or clay house (the rooms built this action were wood/clay rooms)
    # and at least one room actually built.
    return (state.players[idx].house_material in _REWARD
            and _rooms_built(state) >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    """after_build_rooms: grant the material's reward once per room built this
    action (2 clay per wood room / 2 stone per clay room)."""
    p = state.players[idx]
    field, per_room = _REWARD[p.house_material]
    reward = Resources(**{field: per_room * _rooms_built(state)})
    p = fast_replace(p, resources=p.resources + reward)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_build_rooms", CARD_ID, _eligible, _apply)
