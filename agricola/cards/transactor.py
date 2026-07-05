"""Transactor (occupation, D98; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "Immediately before the final harvest at the end of round
14, you can take all the building resources that are left on the entire game
board."

Category: Points Provider. Occupation. No cost / prerequisite / VPs (the JSON
carries only name / category / text — no cost, prereq, or VP fields).

TIMING — window #1 ``immediately_before_harvest``. The printed "Immediately
before the final harvest" maps directly to the harvest ladder's first window,
``immediately_before_harvest`` (``agricola/cards/harvest_windows.py``), the
instant before window #2 (start_of_harvest) and the whole field phase.

ROUND-14 GATE — "the final harvest at the end of round 14". The harvest walk runs
on rounds {4, 7, 9, 11, 13, 14} (``constants.HARVEST_ROUNDS``); each round's
harvest resolves while ``state.round_number`` still equals that round (round_number
is only incremented in the NEXT round's PREPARATION, ``engine._complete_preparation``).
Round 14 is the last round (``NUM_ROUNDS == 14``), so its harvest is the final one.
The eligibility function therefore gates on ``state.round_number == 14`` — the
verbatim "at the end of round 14" — and fires at no earlier harvest.

(Note: the census annotates BOTH Haydryer and Transactor as "round-14-gated". The
printed text supports this for Transactor only; Haydryer fires "immediately before
EACH harvest" and is un-gated. This module implements the text: round-14-only.)

OPTIONAL TRIGGER — "you can take …" is a declinable, once-per-harvest offer, so it
is registered as an optional trigger (``register`` on the ``immediately_before_harvest``
event). It surfaces as a ``FireTrigger`` on the per-player ``PendingHarvestWindow``
frame; ``Proceed`` declines. Once-per-window is automatic (firing marks the card
resolved in the frame's ``triggers_resolved``) — the sweep is a one-shot anyway,
since it empties the board.

WHAT IS SWEPT — "all the building resources that are left on the entire game
board." Building resources are wood / clay / reed / stone. In this engine they
accumulate as the ``ActionSpaceState.accumulated`` ``Resources`` object on the
building-accumulation spaces (forest, clay_pit, reed_bank, western_quarry,
eastern_quarry — ``constants.BUILDING_ACCUMULATION_RATES``); food / animals live in
a SEPARATE scalar ``accumulated_amount`` and are NOT building resources, so they are
untouched. ``_apply`` sums every space's ``accumulated`` into the owner's resources
and resets each to ``Resources()`` — "take all … on the entire game board" — reading
the whole board so a card that ever puts building resources on another space is
covered too.

Card-only state is empty (no CardStore use), so the Family game is byte-identical
and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "transactor"
WINDOW_ID = "immediately_before_harvest"
_FINAL_ROUND = 14


def _board_building_resources(state: GameState) -> Resources:
    """Sum the building resources (the ``accumulated`` Resources) sitting on every
    action space on the board — "all the building resources left on the entire game
    board." Food/animal accumulation (the scalar ``accumulated_amount``) is not a
    building resource and is not included."""
    total = Resources()
    for space in state.board.action_spaces:
        total = total + space.accumulated
    return total


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the sweep iff it is the final harvest (round 14) AND there is at least
    one building resource on the board to take. Ownership and the once-per-window
    guard are enforced by the host enumerator (``_owns`` / the frame's
    ``triggers_resolved``); the round gate and the "something to take" affordability
    check live here."""
    if state.round_number != _FINAL_ROUND:
        return False
    return bool(_board_building_resources(state))


def _apply(state: GameState, idx: int) -> GameState:
    """Take every building resource off the board into the owner's resources and
    clear the board's accumulated building resources."""
    swept = _board_building_resources(state)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + swept)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    new_spaces = tuple(
        fast_replace(space, accumulated=Resources()) if space.accumulated else space
        for space in state.board.action_spaces
    )
    return fast_replace(
        state, board=fast_replace(state.board, action_spaces=new_spaces)
    )


# Pure recurring-window occupation: no on-play effect (the effect is the round-14
# board sweep only), so the on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Optional trigger on window #1 (immediately_before_harvest), round-14-gated.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
