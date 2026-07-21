"""Family Friendly Home (minor improvement, deck A #21; Base Revised; players 1+).

Card text (verbatim): "Each time you take a "Build Rooms" action while having
more rooms than people already, you also get a "Family Growth" action and 1
food." Clarification (verbatim): "This card allows exactly 1 growth action
regardless of how many rooms are built." Prerequisite: 1 Occupation; no cost;
no printed VPs; not a traveling card.

USER RULINGS (2026-07-20):

1. "The rooms>people measure occurs before the build rooms action (so before
   the first room is built)."
2. "If rooms>people, the food is given whether or not the family growth is
   accepted."
3. (USER-CONFIRMED 2026-07-20 — originally the driver's application of the
   §9.6 flag contract + RULES.md's named-action doctrine: "'take a 'Build
   Rooms' action' gated to the named action only - this is correct".)
   "take a 'Build Rooms' action" means the NAMED
   action only — gate on ``PendingBuildRooms.build_rooms_action == True``.
   Farm Expansion's rooms category is the named action; a card effect that
   builds a room (Cottager's "build exactly 1 room", which sets
   ``build_rooms_action=False``) is not.

MECHANISM — two registrations, both on the ``before_build_rooms`` event (the
build-rooms host's before-window):

- The FOOD is an AUTOMATIC effect (``register_auto``): mandatory and
  choice-free per ruling 2 (granted "whether or not the family growth is
  accepted"). Before-autos fire at the instant the ``PendingBuildRooms`` host
  is pushed (``engine._fire_subaction_before_auto``, i.e. at
  ``ChooseSubAction("build_rooms")``) — before any room is built, which is
  exactly ruling 1's measurement point. Eligibility reads the top frame:
  named-action flag (ruling 3), owner's frame, ``num_built == 0`` (defensive —
  the push guarantees it), and rooms > people.

- The GROWTH is an OPTIONAL trigger (``register``): a granted sub-action is
  optional even when worded like a grant-with-no-choice ("you also get") —
  declining is implicit (build a room / Proceed instead of firing). The
  build-rooms enumerator offers before-triggers only while ``num_built == 0``
  (the before-window closes at the first room commit), so the rooms > people
  read in eligibility IS the pre-action measure of ruling 1 — the room count
  cannot have changed while the trigger is still on offer. The host frame's
  ``triggers_resolved`` latches the fire, giving the clarification's "exactly
  1 growth action regardless of how many rooms are built".

THE GROWTH ITSELF — the card-granted family-growth primitive (Group A1 user
ruling, recorded in CARD_DEFERRED_PLANS.md §A1 / the ``PendingFamilyGrowth``
docstring): firing pushes ``PendingFamilyGrowth(place_on_space=False)``, so
the newborn occupies NO action space — the commit increments the owner's
people_total/newborns only (people_home untouched; the newborn is never
placeable this round). It is a normal newborn otherwise (feeds at 1 food if a
harvest ends its birth round; grows up at RETURN_HOME).

GROWTH GATES (the caller's eligibility, per the primitive's convention):

- The family cap is ``workers_in_supply > 0`` — the engine's canonical growth
  gate (state.py: a growth is legal only while a meeple remains in the supply
  pile). This equals ``people_total < 5`` absent meeple-removing cards and
  stays correct with them; the cap is a game rule this card does not waive.
- The named "Family Growth" action's own room requirement (more rooms than
  people) is SUBSUMED by the card's rooms > people condition — one check
  serves both, at the same pre-action instant.

Played normally (the play-minor paths); on-play is a no-op — the effect is
purely recurring. Card-only registries are empty in the Family game, so the
Family game is byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_auto
from agricola.legality import _num_rooms
from agricola.pending import PendingBuildRooms, PendingFamilyGrowth, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "family_friendly_home"


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _named_build_rooms_entry(state: GameState, idx: int) -> bool:
    """The shared frame gate: the top frame is the NAMED Build Rooms action's
    host (ruling 3), it is `idx`'s frame, no room has been built yet (ruling
    1's window — the push point for the auto, the enumerator's before-window
    for the trigger), and the owner has more rooms than people (the pre-action
    measure: while num_built == 0 the room count is the pre-action count)."""
    if not state.pending_stack:
        return False
    top = state.pending_stack[-1]
    if not isinstance(top, PendingBuildRooms):
        return False
    if top.player_idx != idx or not top.build_rooms_action or top.num_built != 0:
        return False
    p = state.players[idx]
    return _num_rooms(p) > p.people_total


def _food_eligible(state: GameState, idx: int) -> bool:
    return _named_build_rooms_entry(state, idx)


def _apply_food(state: GameState, idx: int) -> GameState:
    """The 1 food — automatic at category entry, unconditional on whether the
    growth is accepted (ruling 2)."""
    p = state.players[idx]
    return _update_player(
        state, idx, fast_replace(p, resources=p.resources + Resources(food=1)))


def _growth_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the growth in the same before-window, with the family cap (a
    meeple left in supply — the game rule the card does not waive). Once per
    action is the host's triggers_resolved (self-checked here too, mirroring
    the exemplars). The named action's room requirement is the same rooms >
    people check the frame gate already makes."""
    if CARD_ID in triggers_resolved:
        return False
    if not _named_build_rooms_entry(state, idx):
        return False
    return state.players[idx].workers_in_supply > 0


def _apply_growth(state: GameState, idx: int) -> GameState:
    """Grant the growth: push the card-granted family-growth primitive (no
    board placement — the commit increments people_total/newborns only)."""
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


# Minor improvement: prereq 1 Occupation, no cost, no VPs; on-play is a no-op
# (the effect is purely recurring).
register_minor(CARD_ID, min_occupations=1)

# The 1 food: automatic, at the named Build Rooms host's push (ruling 2).
register_auto("before_build_rooms", CARD_ID, _food_eligible, _apply_food)

# The growth: an optional trigger in the same before-window (granted
# sub-actions are optional; declining is implicit).
register("before_build_rooms", CARD_ID, _growth_eligible, _apply_growth)
