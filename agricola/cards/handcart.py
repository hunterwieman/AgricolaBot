"""Handcart (minor improvement, B81; Bubulcus Expansion; players -).

Card text (verbatim): "Before each work phase, you can take 1 building resource
from at most one wood/clay/reed/stone accumulation space containing at least
6/5/4/4 building resources of the same type."
Cost: 1 Wood. No prerequisite. VPs: none. Not passing.

USER RULINGS (2026-07-20):

1. The mechanism is APPROVED — a no-worker-placed take off an accumulation
   space, surfaced as a trigger that edits the space's stock (the deferred-plans
   cluster C3, resolved 2026-07-20).
2. NATIVE-TYPE semantics — the adopted analog of the same day's Material Hub
   ruling ("the native-type filter is therefore the complete, final semantics —
   no deposit provenance is ever needed"), FLAGGED FOR USER CONFIRMATION on this
   card: the slash-correlation reads per the space's NATIVE family — a wood
   accumulation space qualifies iff it holds >= 6 units OF WOOD, a clay space
   >= 5 clay, a reed space >= 4 reed, a stone space >= 4 stone. A FOREIGN-type
   good a card deposited on a space (e.g. Nail Basket's stone on Forest) never
   counts toward that space's threshold, while a NATIVE-type good a card
   returned onto the space counts like any other (origin irrelevant). The
   resource taken is 1 of the space's NATIVE type.

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
enumerator expands the one trigger into one `FireTrigger(card_id="handcart",
variant=<space_id>)` per currently-qualifying space; the host's `Proceed` is
the decline. "At most one" space is STRUCTURAL: firing stamps the card into the
host frame's `triggers_resolved`, so no second fire is surfaced in the same
window even with several qualifying spaces. Firing debits 1 native unit from
that space's `accumulated` (the board-edit idiom of Nail Basket / Pet Lover)
and credits the owner 1 of it.

The four space families are the derived frozensets in `agricola/constants.py`
(WOOD/CLAY/REED/STONE_ACCUMULATION_SPACES) — computed from
BUILDING_ACCUMULATION_RATES, so they extend automatically once the 3-4-player
spaces (Copse/Grove wood, Hollow clay) enter the rate table; a family member
not on the current board is simply skipped. At 2 players: wood = Forest (>= 6),
clay = Clay Pit (>= 5), reed = Reed Bank (>= 4), stone = Western + Eastern
Quarry (each judged independently, >= 4).

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

# The printed slash-correlation, per NATIVE family (ruling 2 above): a space
# qualifies iff it holds at least the threshold in its OWN native good. The
# family sets are derived from the rate table (4-player forward-compatible —
# Copse/Grove/Hollow join automatically when added there).
_FAMILIES: tuple[tuple[frozenset, str, int], ...] = (
    (WOOD_ACCUMULATION_SPACES,  "wood",  6),
    (CLAY_ACCUMULATION_SPACES,  "clay",  5),
    (REED_ACCUMULATION_SPACES,  "reed",  4),
    (STONE_ACCUMULATION_SPACES, "stone", 4),
)


def _native_of(space_id: str):
    """(native_good, threshold) for a building accumulation space, or None for
    any other space id."""
    for family, good, threshold in _FAMILIES:
        if space_id in family:
            return good, threshold
    return None


def _qualifying_spaces(state: GameState) -> list[str]:
    """The accumulation spaces currently holding at least their family threshold
    in their NATIVE good (foreign-type deposits never count — ruling 2), in
    canonical board order. A family member not on this board (a future
    3-4-player space) is skipped."""
    out: list[str] = []
    for family, good, threshold in _FAMILIES:
        for space_id in family:
            if space_id not in SPACE_INDEX:
                continue  # not on this board (4-player forward-compat guard)
            sp = get_space(state.board, space_id)
            if getattr(sp.accumulated, good) >= threshold:
                out.append(space_id)
    out.sort(key=SPACE_INDEX.__getitem__)
    return out


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """One variant per qualifying space; empty = nothing to take this window
    (then no window frame is pushed at all — eligibility-driven hosting)."""
    return _qualifying_spaces(state)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return bool(_qualifying_spaces(state))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire for the chosen space: move 1 of its NATIVE good from the space's
    accumulated stock to the owner's supply. "At most one" needs no bookkeeping
    here — the fire already stamped `triggers_resolved` on the window host, so
    the enumerator surfaces no second Handcart fire this window."""
    native = _native_of(variant)
    assert native is not None, f"Handcart fired for non-accumulation space {variant!r}"
    good, _threshold = native
    one = Resources(**{good: 1})
    # Debit the space's stock (the Nail Basket / Pet Lover board-edit idiom).
    sp = get_space(state.board, variant)
    state = fast_replace(
        state, board=with_space(
            state.board, variant,
            fast_replace(sp, accumulated=sp.accumulated - one)))
    # Credit the owner 1 of the native good.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + one)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
# "Before each work phase" → the preparation ladder's before_work window
# (ruling 54, 2026-07-14; §5d classification). Optional take → a play-variant
# trigger, one FireTrigger per qualifying space; Proceed declines.
register("before_work", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
