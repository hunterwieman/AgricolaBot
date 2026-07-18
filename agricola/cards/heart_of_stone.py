"""Heart of Stone (minor improvement, C21; Corbarius Expansion; deck C #21).

Card text (verbatim): "Each time a "Quarry" accumulation space is revealed, if
you have room in your house, you can immediately take a "Family Growth" action
without placing a person."
Cost: 4 Food. Prerequisite: none. Printed VPs: none (0). Not passing. Kept.

TIMING — the preparation ladder's ``reveal`` window (ruling 54, 2026-07-14 as
revised; CARD_ENGINE_IMPLEMENTATION.md §5d): the reveal-reaction seam, the
instant immediately after the round-card reveal and the ``__round_setup__``
increment. "Each time a 'Quarry' accumulation space is revealed" places this
card on that rung — Heart of Stone is that window's FIRST member card (the §5d
census names it there). A "Quarry" accumulation space is a stone accumulation
space (``western_quarry`` / ``eastern_quarry`` — the only two, given by
``STONE_ACCUMULATION_SPACES``). "Was revealed by THIS round's preparation" is
read directly off ``ActionSpaceState.revealed_round`` (user decision
2026-07-15: every reveal stamps the round it belongs to; permanents carry 0,
unrevealed None). At the ``reveal`` window the round increment has already run
(``__round_setup__`` precedes it), so a quarry revealed by this round's
preparation satisfies ``revealed_round == state.round_number``; a quarry
revealed in an earlier round has ``revealed_round < round_number`` and never
re-fires. (The same reading Task Artisan uses for the identical event.)

"IMMEDIATELY" (ruling 66, 2026-07-17, quoted verbatim): the word "immediately"
here adds/changes nothing — triggers on the same instant fire in any
player-chosen order. So "immediately take a 'Family Growth' action" is just the
``reveal`` window's own instant, with no separate earlier moment implied. This
is a per-instance ruling (each "immediately" is its own rules question, never
generalized).

FIRING KIND — an OPTIONAL trigger. "you can ... take a 'Family Growth' action"
is a granted sub-action, which is the player's to take or decline (a granted
sub-action is optional even when worded like a command; only "you must" is
mandatory — CARD_AUTHORING_GUIDE.md "A granted sub-action is optional"). So it
is ``register("reveal", …)``, surfaced as a ``FireTrigger`` at the window's
per-player ``PendingHarvestWindow`` choice host; the host's ``Proceed`` IS the
decline. Firing IS the acceptance, so ``_apply`` pushes the growth directly.
Singular "a 'Family Growth' action" = once per reveal, given automatically by
the host's ``triggers_resolved`` (once-per-window).

THE GROWTH — "without placing a person" is the card-granted family-growth
primitive (Group A1, built 2026-07-03; the user's ruling is recorded in the
``PendingFamilyGrowth`` docstring and CARD_DEFERRED_PLANS.md §A1): firing pushes
``PendingFamilyGrowth(player_idx=idx, initiated_by_id="card:heart_of_stone",
place_on_space=False)``, so the newborn occupies NO action space — the commit
increments the owner's people_total/newborns (and spends a meeple from supply)
without touching the board. The card's own "without placing a person" is
exactly this ``place_on_space=False`` behavior.

"IF YOU HAVE ROOM IN YOUR HOUSE" — the printed condition, and the CALLER's
eligibility check (the primitive does not self-check; the ``PendingFamilyGrowth``
docstring names the gate "people_total < 5 and < rooms"): the family cap
``workers_in_supply > 0`` — the codebase's robust form of "people_total < 5", a
meeple left in the supply pile (a game rule the card does not waive; identical
to the sibling grants Autumn Mother / Bed in the Grain Field) — AND
``people_total < _num_rooms(p)`` (a free room for the newborn, the Basic Wish
for Children room gate). The card does NOT waive either clause.

There is no dead-end to gate against beyond the room condition: the growth is
free (the 4 Food is the one-time PLAY cost, handled by the standard minor play
path + food-payment layer — no special code here), so a growth is always doable
once the room gate holds.

Played via the Minor-Improvement / play-a-minor path; on-play is a no-op (the
effect is purely the recurring reveal-window trigger). Hosting on the recurring
half is eligibility-driven (the preparation ladder's model — no hook
registration): a window frame appears only on a round whose reveal was a quarry
and only while the room gate holds.

Card-only registries are empty in the Family game, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.constants import STONE_ACCUMULATION_SPACES
from agricola.legality import _num_rooms
from agricola.pending import PendingFamilyGrowth, push
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "heart_of_stone"


def _quarry_revealed_this_round(state: GameState) -> bool:
    """Did THIS round's preparation reveal a "Quarry" (stone) accumulation
    space? At the ``reveal`` window the round increment has already run, so a
    just-revealed quarry's ``revealed_round`` equals ``state.round_number``
    (permanents carry 0, earlier-round reveals a smaller number, unrevealed
    None)."""
    return any(
        get_space(state.board, q).revealed_round == state.round_number
        for q in STONE_ACCUMULATION_SPACES
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the growth iff (a) a quarry was revealed by this round's
    preparation and (b) the printed "room in your house" condition holds — the
    family cap (a meeple left in supply) AND a free room. Ownership is the
    window enumerator's gate; once-per-window is the host's ``triggers_resolved``
    (checked by the firing machinery, not here)."""
    p = state.players[idx]
    return (
        _quarry_revealed_this_round(state)
        and p.workers_in_supply > 0
        and p.people_total < _num_rooms(p)
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the growth: push the card-granted family-growth primitive with no
    board placement ("without placing a person"). Firing IS the acceptance (the
    host's Proceed was the decline moment); the room gate was verified in
    eligibility, so the primitive never dead-ends."""
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


# Cost 4 Food, no prerequisite, 0 VPs, kept; on-play is a no-op (the effect is
# purely the recurring reveal-window trigger).
register_minor(CARD_ID, cost=Cost(resources=Resources(food=4)))

# "Each time a 'Quarry' accumulation space is revealed, ... you can immediately
# take a 'Family Growth' action" — an OPTIONAL trigger on the preparation
# ladder's `reveal` window (ruling 54, 2026-07-14 as revised), read off
# `revealed_round` (user decision 2026-07-15). "Immediately" adds nothing
# (ruling 66, 2026-07-17).
register("reveal", CARD_ID, _eligible, _apply)
