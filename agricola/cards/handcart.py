"""Handcart (minor improvement, B81; Bubulcus Expansion; players -).

Card text (verbatim): "Before each work phase, you can take 1 building resource
from at most one wood/clay/reed/stone accumulation space containing at least
6/5/4/4 building resources of the same type."
Cost: 1 Wood. No prerequisite. VPs: none. Not passing.

USER RULINGS (2026-07-20):

1. The mechanism is APPROVED — a no-worker-placed take off an accumulation
   space, surfaced as a trigger that edits the space's stock (the deferred-plans
   cluster C3, resolved 2026-07-20).
2. Threshold and take semantics (verbatim): "the X resources of the same type
   do not need to be the native type of the action space. Additionally, the
   player can take any resource from the space, not just the resource that has
   a count of X+. (Building resource accumulation spaces can sometimes hold
   multiple different types of building resources due to card effects)".

   So: the 6/5/4/4 slash-correlation keys the NUMBER to the space's family (a
   wood accumulation space needs 6, a clay space 5, a reed space 4, a stone
   space 4), and the space QUALIFIES iff ANY single building-resource type on
   it reaches that number — 6 stone sitting on the Forest qualifies it, while
   3 wood + 3 stone on the Forest does not (six goods, but no single type
   reaches 6). From a qualifying space the player may take 1 of ANY
   building-resource type present on it (count >= 1), not only the
   threshold-meeting type.

TIMING. "Before each work phase" is the preparation ladder's `before_work`
window (ruling 54, 2026-07-14, as classified in CARD_ENGINE_IMPLEMENTATION.md
§5d — Handcart is the named member-in-waiting; Pavior is the existing member):
post-replenishment, the preparation phase's last instant. Consequence, tested
rather than assumed: the round's accumulation REFILL (`__replenish__`) has
already happened when this window fires, so the just-refilled goods count
toward the thresholds.

MACHINERY. Preparation windows are eligibility-driven — no hook registration;
the walk (`engine._advance_preparation` → `_process_simple_window`) pushes a
`PendingHarvestWindow(window_id="before_work")` choice host for the owner
exactly when this trigger is eligible (some space qualifies), and no frame at
all otherwise. "You can" → an OPTIONAL play-variant trigger (`register` +
`register_play_variant_trigger`, the Scholar shape): the window host's
enumerator expands the one trigger into one
`FireTrigger(card_id="handcart", variant="<space_id>:<type>")` per
(qualifying space, building-resource type present on it) pair; the host's
`Proceed` is the decline. "At most one" space is STRUCTURAL — and caps the
whole window at ONE take, one (space, type) pick: firing stamps the card into
the host frame's `triggers_resolved`, so no second fire is surfaced in the
same window however many spaces qualify. Firing debits 1 of the chosen type
from that space's `accumulated` (the board-edit idiom of Nail Basket / Pet
Lover) and credits the owner 1 of it.

The four space families are the derived frozensets in `agricola/constants.py`
(WOOD/CLAY/REED/STONE_ACCUMULATION_SPACES) — computed from
BUILDING_ACCUMULATION_RATES, so they extend automatically once the 3-4-player
spaces (Copse/Grove wood, Hollow clay) enter the rate table; a family member
not on the current board is simply skipped. At 2 players: wood = Forest
(needs 6), clay = Clay Pit (5), reed = Reed Bank (4), stone = Western +
Eastern Quarry (each judged independently, 4).

Card-game only (ownership-gated registries; no new engine state), so the Family
trace and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import (
    CLAY_ACCUMULATION_SPACES,
    REED_ACCUMULATION_SPACES,
    SPACE_INDEX,
    STONE_ACCUMULATION_SPACES,
    WOOD_ACCUMULATION_SPACES,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "handcart"

# The printed slash-correlation: the space's FAMILY sets the number (wood 6 /
# clay 5 / reed 4 / stone 4); which building-resource type reaches it does not
# matter (user ruling 2026-07-20 above). The family sets are derived from the
# rate table (4-player forward-compatible — Copse/Grove/Hollow join
# automatically when added there).
_FAMILIES: tuple[tuple[frozenset, int], ...] = (
    (WOOD_ACCUMULATION_SPACES,  6),
    (CLAY_ACCUMULATION_SPACES,  5),
    (REED_ACCUMULATION_SPACES,  4),
    (STONE_ACCUMULATION_SPACES, 4),
)

# The building-resource types — the only goods the threshold counts and the
# only goods takeable ("take 1 building resource"), in canonical offer order.
_BUILDING_GOODS: tuple[str, ...] = ("wood", "clay", "reed", "stone")


def _qualifying_spaces(state: GameState) -> list[str]:
    """The accumulation spaces on which SOME single building-resource type
    reaches the space's family threshold (any type, not just the native one —
    the 2026-07-20 ruling), in canonical board order. A family member not on
    this board (a future 3-4-player space) is skipped."""
    out: list[str] = []
    for family, threshold in _FAMILIES:
        for space_id in family:
            if space_id not in SPACE_INDEX:
                continue  # not on this board (4-player forward-compat guard)
            acc = get_space(state.board, space_id).accumulated
            if any(getattr(acc, g) >= threshold for g in _BUILDING_GOODS):
                out.append(space_id)
    out.sort(key=SPACE_INDEX.__getitem__)
    return out


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """One "<space_id>:<type>" variant per building-resource type PRESENT
    (count >= 1) on each qualifying space — any present type is takeable, not
    only the threshold-meeting one (the 2026-07-20 ruling). Empty = nothing to
    take this window (then no window frame is pushed at all —
    eligibility-driven hosting)."""
    variants: list[str] = []
    for space_id in _qualifying_spaces(state):
        acc = get_space(state.board, space_id).accumulated
        for good in _BUILDING_GOODS:
            if getattr(acc, good) >= 1:
                variants.append(f"{space_id}:{good}")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return bool(_qualifying_spaces(state))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire for the chosen (space, type): move 1 of that building resource from
    the space's accumulated stock to the owner's supply. "At most one" needs no
    bookkeeping here — the fire already stamped `triggers_resolved` on the
    window host, so the enumerator surfaces no second Handcart fire this window
    (one take total, one (space, type) pick)."""
    space_id, good = variant.split(":", 1)
    assert good in _BUILDING_GOODS, f"Handcart fired for non-building good {good!r}"
    one = Resources(**{good: 1})
    # Debit the space's stock (the Nail Basket / Pet Lover board-edit idiom).
    sp = get_space(state.board, space_id)
    state = fast_replace(
        state, board=with_space(
            state.board, space_id,
            fast_replace(sp, accumulated=sp.accumulated - one)))
    # Credit the owner 1 of the chosen good.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + one)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
# "Before each work phase" → the preparation ladder's before_work window
# (ruling 54, 2026-07-14; §5d classification). Optional take → a play-variant
# trigger, one FireTrigger per (qualifying space, present type); Proceed
# declines.
register("before_work", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
