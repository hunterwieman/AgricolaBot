"""Bunny Breeder (occupation, deck E #139; Ephipparius Expansion; players 3+).

Card text (verbatim): "Select a future round space, subtract the number of the
current round from it, and place this many food on that space. At the start of
that round, you get the food."
Category: Food Provider. No printed VPs.

Category 8 (deferred goods onto a future round space) with a play-time CHOICE of
WHICH round. Modeled as a play-variant occupation
(`register_play_occupation_variant`): one route per selectable future round R
(the rounds after the current one, R in `round_number + 1 .. 14`), each
surcharge-free. The variant-aware `on_play` schedules `R - round_number` food
onto round R via `schedules.schedule_resources` — the standard deferred-goods
helper that lands the food in `future_resources`, collected automatically at that
round's start ("At the start of that round, you get the food").

The amount is literally "the future round number minus the current round number":
selecting round 10 in round 3 places 3->10 = 7 food, arriving at round 10's start.
Played in the last round (14) there is no future round space, so the variants_fn
returns a single zero-surcharge no-op ("none") and the card is still playable.

Played via Lessons; card-only (the schedule rides `future_resources`, whose
default is the empty tuple the Family game holds) — the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.constants import NUM_ROUNDS
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "bunny_breeder"


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """One surcharge-free route per future round space (round_number+1 .. 14);
    a single no-op when none remain (played in round 14)."""
    future = list(range(state.round_number + 1, NUM_ROUNDS + 1))
    if not future:
        return [("none", Resources())]
    return [(str(r), Resources()) for r in future]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Place (selected round - current round) food on the selected round space."""
    if variant is None or variant == "none":
        return state
    target = int(variant)
    amount = target - state.round_number
    return schedule_resources(state, idx, [target], Resources(food=amount))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
