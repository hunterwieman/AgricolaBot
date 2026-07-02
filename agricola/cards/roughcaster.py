"""Roughcaster (occupation, A110; Base Revised; players 1+).

Card text: "Each time you build at least 1 clay room or renovate your house from
clay to stone, you also get 3 food."

Category 5 (build / renovate hook, automatic income). Two mandatory, choice-free
clauses → automatic effects (register_auto), one per hook:

- **build at least 1 clay room** → `after_build_rooms`. A clay room is a room
  built while the house is clay (rooms always match the current house material),
  so eligibility checks `house_material == CLAY`. The event fires ONCE per
  build-rooms session (at the session-ending Stop in `_apply_stop`), so "at least
  1 room" is satisfied exactly when the session built any room — i.e. whenever the
  hook fires at all. +3 food, not +3-per-room.
- **renovate from clay to stone** → `after_renovate`. At the after-phase the
  renovation has already applied, so `house_material` is the NEW (post-renovate)
  material — which cannot distinguish a clay->stone renovate from a wood->stone one
  (Conservator, occupation A87, makes wood->stone legal, and both cards can be
  owned). The card grants only "from clay to stone", so the FROM material must be
  captured *before* the renovate applies: a `before_renovate` automatic snapshots
  the owner's current (pre-renovate) `house_material` into this card's CardStore,
  and the `after_renovate` clause grants iff that snapshot was CLAY. This is the
  shepherds_crook before/after CardStore snapshot idiom.

Played via Lessons; its on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md
Category 5.
"""
from __future__ import annotations

from agricola.constants import HouseMaterial
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "roughcaster"

# CardStore key holding the pre-renovate ("from") house material, snapshotted in
# before_renovate and read in after_renovate to gate the clay->stone clause.
_FROM_KEY = "roughcaster_renovate_from"


def _eligible_room(state: GameState, idx: int) -> bool:
    # Fired at the build-rooms session end: a room was built (the hook only fires
    # when one was) and the house is clay → it was a clay room.
    return state.players[idx].house_material == HouseMaterial.CLAY


def _snapshot_from(state: GameState, idx: int) -> GameState:
    # before_renovate (fires at the PendingRenovate push, before it applies): record
    # the owner's current (pre-renovate) house material so after_renovate can tell a
    # clay->stone renovate from a wood->stone one (Conservator). register_auto fires
    # only for the owner, so no ownership guard is needed.
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(_FROM_KEY, p.house_material))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible_renovate(state: GameState, idx: int) -> bool:
    # after_renovate fires post-application, so the house is already the NEW material
    # (STONE for both clay->stone and Conservator's wood->stone). Gate on the FROM
    # material snapshotted in before_renovate: grant iff it was a clay->stone renovate.
    return state.players[idx].card_state.get(_FROM_KEY, None) == HouseMaterial.CLAY


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_build_rooms", CARD_ID, _eligible_room, _apply)
register_auto("before_renovate", CARD_ID, lambda state, idx: True, _snapshot_from)
register_auto("after_renovate", CARD_ID, _eligible_renovate, _apply)
