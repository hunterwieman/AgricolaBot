"""Blackberry Farmer (occupation, E108; Ephipparius Expansion; Food Provider;
players 1+).

Card text: "Each time you build fences, place 1 food on each remaining round
space, up to the number of fences just built. At the start of these rounds, you
get the food."

Printed VPs: none. Cost: none. Prerequisite: none. Played via Lessons
(occupation), so on-play is a no-op.

Classification (settled in the batch spec, 2026-07-14): the payout depends on HOW
MANY fences the action built ("just built" is outcome-dependent — it reads what
the action produced), so it is computed ONCE at the AFTER boundary of the
build-fences ACTION. Build Fences is one action; its internal per-pasture commits
are not event opportunities (CARD_AUTHORING_GUIDE — sequential commits are
search-layer decomposition, never card-visible events).

Mechanism — the Shepherd's Crook / Trimmer before/after CardStore-snapshot pair on
the build_fences sub-action host:

  - `before_build_fences` (fires when PendingBuildFences is pushed, before any
    pasture commit): snapshot the count of fence pieces ON THE BOARD
    (`helpers.fences_built`, the ground-truth fence arrays) into the per-card
    CardStore. Counting board pieces — not `fences_in_supply` deltas — means
    free-pool fences (Ash Trees pieces held on a card, not in the supply) still
    count as fences built, which they are.
  - `after_build_fences` (fires at the Proceed work-complete flip, after all
    commits): `built` = board count now − snapshot. If built > 0, place 1 food on
    each of the next `built` round spaces — rounds R+1 .. R+built
    (`schedule_resources`, which silently drops rounds > 14, giving the printed
    "each remaining round space, up to the number of fences just built": near game
    end fewer than `built` spaces remain and the excess food is simply not
    placed). "At the start of these rounds, you get the food" is the standard
    future_resources collection at round entry. Then always reset the snapshot to
    the canonical value 0, so two commit orders reaching the same farmyard
    converge to the same state.

Two fencings in one action (two pastures committed before Proceed) are ONE build
— one snapshot diff, one payout covering the combined fence count (shared edges
between the pastures are naturally counted once, since the diff reads the board).
Fires identically whether fencing is reached via the Fencing action space or Farm
Redevelopment ("Overhaul"), since both push PendingBuildFences; declining Farm
Redevelopment's optional fences never pushes the frame, so nothing fires.
Card-only state (the CardStore snapshot) defaults canonically, so the Family game
is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import fences_built
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "blackberry_farmer"


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_build_fences: record the pre-action board fence count so the
    after-hook can tell how many pieces this action built."""
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, fences_built(p.farmyard))
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _schedule_after(state: GameState, idx: int) -> GameState:
    """after_build_fences: place 1 food on each of the next `built` round spaces
    (built = board fence count now − the before-snapshot; rounds past 14 are
    dropped by `schedule_resources`). Always reset the snapshot to canonical 0."""
    p = state.players[idx]
    before = p.card_state.get(CARD_ID, None)
    if before is None:
        # Defensive: no snapshot was taken (cannot happen — before_build_fences
        # always fires at the push). Schedule nothing rather than over-granting.
        return state
    built = fences_built(p.farmyard) - before
    # Reset the snapshot to canonical 0 (so two commit orders converge).
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, 0))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    if built > 0:
        R = state.round_number
        state = schedule_resources(
            state, idx, range(R + 1, R + 1 + built), Resources(food=1)
        )
    return state


# Occupation: no on-play effect (played via Lessons).
register_occupation(CARD_ID, lambda state, idx: state)
register_auto("before_build_fences", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_build_fences", CARD_ID, lambda state, idx: True, _schedule_after)
