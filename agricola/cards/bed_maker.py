"""Bed Maker (occupation, deck A #93; Artifex Expansion; players 1+).

Card text (verbatim): "Each time you add rooms to your house, you can also pay
1 wood and 1 grain to immediately get a "Family Growth with Room Only" action."
Clarification (verbatim): "This card allows exactly 1 growth action regardless
of how many rooms are built."

TIMING — USER RULING 2026-07-21 (ruling 74, CARD_DEFERRED_PLANS.md): the
trigger fires in the ``after_build_rooms`` window — a DELIBERATE override of
the bare-"each time"-fires-BEFORE default (the Trigger-Timing ruling), because
the growth is intended to use the just-built rooms: "Family Growth with Room
Only" requires more rooms than people, and the room gate reads POST-build
state. Build Rooms is ONE action, so the after-window opens exactly once, at
the host's ``Proceed`` work-complete flip — never between room commits — and
is only reachable when >= 1 room was actually built (``Proceed`` requires
``num_built >= 1``), which is what "you add rooms to your house" demands.
Under ruling 74 the growth resolves at the fire, within that after-window —
the text's "immediately get" names that instant, no separate earlier moment.

SCOPE — DRIVER READING, FLAGGED AS SUCH (not a dated user ruling): the trigger
fires on ANY rooms addition — ``after_build_rooms`` regardless of the frame's
``build_rooms_action`` flag — by analogy to Furnisher's explicit
every-room-build user ruling. "Each time you add rooms to your house" is not
the named-action wording ("take a 'Build Rooms' action", the Family Friendly
Home gate), so a card-granted room build (Cottager's "build exactly 1 room",
which sets ``build_rooms_action=False``) also qualifies.

ONCE PER ACTION (the printed clarification): the host frame's
``triggers_resolved`` latches the fire for the rest of the host visit —
exactly 1 growth action per rooms-adding action, however many rooms it built.

FIRING KIND — an OPTIONAL trigger ("you can"): surfaced as a ``FireTrigger``
in the build host's after-phase, alongside ``Stop`` (declining is implicit —
no SkipTrigger; ``Stop`` exits without firing). Firing debits the 1 wood +
1 grain directly — a card effect price in raw goods, not a build/renovate/play
cost, so the cost-modifier chokepoint does not apply, and no liquidation layer
exists for wood/grain (contrast the food-payment path) — then pushes the
growth.

THE GROWTH — standing ruling (Group A1, CARD_DEFERRED_PLANS.md §A1 / the
``PendingFamilyGrowth`` docstring): card-granted family growth occupies NO
action space — ``PendingFamilyGrowth(player_idx=idx,
initiated_by_id="card:bed_maker", place_on_space=False)``; the commit
increments the owner's people_total/newborns (spending a meeple from supply)
without touching the board. The room gate is the CALLER's check, not the
primitive's.

ELIGIBILITY (never a dead end): wood >= 1 AND grain >= 1 AND the growth is
legal RIGHT NOW — the family cap ``workers_in_supply > 0`` (the engine's
canonical growth gate: a meeple left in the supply pile — the robust form of
"people_total < 5", staying correct under meeple-removing cards; see the
``workers_in_supply`` comment in state.py) AND ``rooms > people_total`` (the
"Family Growth with Room Only" room requirement, read on the post-build state
per ruling 74). Exactly the Family Friendly Home growth gates, at the
after-instant instead of the before-instant.

Played via Lessons; on-play is a no-op (the effect is purely recurring).
Card-only registries are empty in the Family game, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _num_rooms
from agricola.pending import PendingFamilyGrowth, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "bed_maker"

_PRICE = Resources(wood=1, grain=1)


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the growth in the build host's after-window iff the 1 wood +
    1 grain are on hand AND the growth is legal right now: the family cap (a
    meeple left in supply) and more rooms than people — the post-build read
    ruling 74 fixes (the after-window opens only once every room of the action
    is built). Once per action is the host's ``triggers_resolved`` (checked by
    the firing machinery; self-checked here too, mirroring the exemplars).
    Ownership is the enumerator's gate."""
    if CARD_ID in triggers_resolved:
        return False
    p = state.players[idx]
    if p.resources.wood < 1 or p.resources.grain < 1:
        return False
    return p.workers_in_supply > 0 and _num_rooms(p) > p.people_total


def _apply(state: GameState, idx: int) -> GameState:
    """Pay the 1 wood + 1 grain, then grant the growth: push the card-granted
    family-growth primitive (no board placement — the commit increments
    people_total/newborns only). Eligibility verified goods + gates, so the
    primitive never dead-ends."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - _PRICE)
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


# Occupation; on-play is a no-op (the effect is purely recurring).
register_occupation(CARD_ID, lambda state, idx: state)

# "Each time you add rooms to your house, you can also pay 1 wood and 1 grain
# to immediately get a 'Family Growth with Room Only' action" — an OPTIONAL
# trigger on the rooms build's after-window (user ruling 74, 2026-07-21: the
# room gate reads post-build state), on ANY rooms addition (flagged driver
# reading — see the docstring).
register("after_build_rooms", CARD_ID, _eligible, _apply)
