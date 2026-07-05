"""Bed in the Grain Field (minor improvement, C24; Corbarius Expansion).

Card text (verbatim): "At the start of the next harvest, you get a "Family
Growth" action if you have room for the newborn."
Clarification (verbatim): "Only works in the next harvest after it is played.
The newborn must be fed."
Cost: none (free). Printed VPs: none (0). Prerequisite: 1 Grain Field. Kept.

TIMING — window #2 ``start_of_harvest``: the printed "at the start of the next
harvest" is that window's phrase (the harvest-ladder census,
HARVEST_WINDOWS_DESIGN.md §1, lists Bed in the Grain Field there). "The NEXT
harvest" (clarification: "Only works in the next harvest after it is played")
is expressed by round arithmetic, not a spend-latch: on play, ``_on_play``
records ``state.round_number`` in CardStore; ``_eligible`` fires only when the
current round IS the first harvest round at-or-after the play round
(``min(r in HARVEST_ROUNDS if r >= play_round)``). At-or-after, not strictly
after: a minor is played during a WORK turn, which always precedes that same
round's harvest (the harvest detours the end of the round), so a card played on
a harvest round R works in round R's own harvest — the next one to start. The
round key can match only ONE harvest, so the card is one-shot by construction:
a decline (or a failed room check) in that harvest consumes the opportunity —
"the next harvest" has passed — with no latch to spend.

THE GROWTH — the card-granted family-growth primitive (Group A1, built
2026-07-03 with the user's ruling recorded in CARD_DEFERRED_PLANS.md §A1 / the
``PendingFamilyGrowth`` docstring): firing pushes
``PendingFamilyGrowth(place_on_space=False)``, so the newborn occupies NO
action space. "You get a 'Family Growth' action" grants a sub-action, and a
granted sub-action is optional even when worded as a command (only "you must"
is mandatory — CARD_AUTHORING_GUIDE.md "A granted sub-action is optional"), so
it is an OPTIONAL trigger: a ``FireTrigger`` on the ``PendingHarvestWindow``
frame, declinable via ``Proceed``.

"IF YOU HAVE ROOM FOR THE NEWBORN" — the printed condition, checked in
``_eligible`` (the primitive does not self-check; CARD_DEFERRED_PLANS.md §A1
names the predicate): ``people_total < 5`` (the family cap — a game rule the
card does not waive) AND ``people_total < _num_rooms(p)`` (a free room for the
newborn) — the Basic Wish for Children gate.

"THE NEWBORN MUST BE FED" (clarification) — the growth happens at window #2,
before FEED, so the newborn is counted in THIS harvest's feeding bill as a
newborn (1 food, the engine's uniform newborn rule); it grows up at
RETURN_HOME like any other.

Prerequisite "1 Grain Field": at least one FIELD cell that currently holds
grain (``cell.cell_type is FIELD and cell.grain > 0``) — the project's settled
reading of a "grain field" (Straw-Thatched Roof, Sleeping Corner, Gardener's
Knife). A prerequisite is a HAVE-check at play time, never spent.

Card-only registries and CardStore are empty in the Family game, so the Family
game is byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.constants import CellType, HARVEST_ROUNDS
from agricola.legality import _num_rooms
from agricola.pending import PendingFamilyGrowth, push
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "bed_in_the_grain_field"
WINDOW_ID = "start_of_harvest"


def _one_grain_field(state: GameState, idx: int) -> bool:
    """Prerequisite: 1 Grain Field — at least one FIELD cell that currently
    holds grain."""
    return any(
        cell.cell_type is CellType.FIELD and cell.grain > 0
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _on_play(state: GameState, idx: int) -> GameState:
    """Record the round the card is played. "Only works in the next harvest
    after it is played" — ``_eligible`` keys on this round to identify that
    one harvest."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, state.round_number))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _next_harvest_round(play_round: int) -> int | None:
    """The round of the first harvest to START after a play in `play_round`'s
    WORK phase: the smallest harvest round >= play_round (a WORK-phase play
    always precedes its own round's harvest). None if no harvest remains."""
    later = [r for r in HARVEST_ROUNDS if r >= play_round]
    return min(later) if later else None


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the growth iff (a) this harvest IS the next harvest after the play
    (the recorded play round's round arithmetic — one specific harvest round,
    so the card can never fire twice) and (b) the printed room condition holds.
    Ownership is the window enumerator's ``_owns`` gate."""
    p = state.players[idx]
    play_round = p.card_state.get(CARD_ID)
    if play_round is None or state.round_number != _next_harvest_round(play_round):
        return False
    return p.people_total < 5 and p.people_total < _num_rooms(p)


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the growth: push the card-grant family-growth primitive (no board
    placement; the commit increments the owner's people_total/newborns)."""
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


# Free, 0 VPs, prerequisite 1 Grain Field; on-play records the play round.
register_minor(CARD_ID, prereq=_one_grain_field, on_play=_on_play)

# The one-shot growth grant at the start of the next harvest: an optional
# trigger on window #2 (start_of_harvest).
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
