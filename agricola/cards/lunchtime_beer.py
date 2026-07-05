"""Lunchtime Beer (minor improvement, E58; Ephipparius Expansion).

Card text (verbatim): "At the start of each harvest, you can choose to skip the
field and breeding phase of that harvest and get exactly 1 food instead."
Free, no prerequisite, no printed VPs.

An optional trigger at the start-of-harvest instant: firing it grants the
1 food and latches the skip for THIS round's harvest (the latch stores the
round number in card_state; harvest rounds are unique, so a past latch is
inert next harvest and the choice re-arms with no clearing step).

**What the skip suppresses** — the FIELD phase and the BREEDING phase, each
WITH its boundaries (user ruling 1, 2026-07-03: a skipped phase has no
boundaries): every field-segment instant (before / start of / during — the
crop take included — / end of / after the field phase) and every
breeding-segment instant (start of breeding, the breeding itself — no
newborns — and after breeding). The player still FEEDS (the feeding phase is
not skipped: its start / income / payment / after instants all run), and the
harvest's own outer instants (immediately-before, start-of-harvest,
end-of-harvest, immediately/after-harvest) are untouched — they belong to the
harvest, not to the skipped phases. The skipper's fields keep their crops.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import (
    register_harvest_skip,
    register_harvest_window_hook,
)
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "lunchtime_beer"
_SKIP_ROUND_KEY = f"{CARD_ID}_skip_round"

# The suppressed instants: the two skipped phases, boundaries included
# (ruling 1). "breeding" / "field_phase" also gate the engine's own frames —
# no take, no breeding frame.
_SKIPPED_WINDOWS = frozenset({
    "before_field_phase", "start_of_field_phase", "field_phase",
    "end_of_field_phase", "after_field_phase",
    "start_of_breeding", "breeding", "after_breeding",
})


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    return True   # always choosable at the window; once per window via the frame


def _apply(state: GameState, idx: int) -> GameState:
    """Take the skip: +1 food and latch this round's harvest."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=1),
        card_state=p.card_state.set(_SKIP_ROUND_KEY, state.round_number),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _skipped(state: GameState, idx: int, window_id: str) -> bool:
    return (window_id in _SKIPPED_WINDOWS
            and state.players[idx].card_state.get(_SKIP_ROUND_KEY)
            == state.round_number)


register_minor(CARD_ID)
register("start_of_harvest", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "start_of_harvest")
register_harvest_skip(CARD_ID, _skipped)
