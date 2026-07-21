"""Dung Collector (occupation, E90; Ephipparius Expansion; players 1+).

Card text (verbatim): "Each time you get 2 or more newborn animals, you can pay
1 food to plow 1 field."
Clarification (verbatim): "You must be able to accommodate each newborn in
order to get it."
Occupation — no cost / prerequisite / VPs.

WHAT "GET 2 OR MORE NEWBORN ANIMALS" MEANS HERE — **user ruling 74 (2026-07-21,
CARD_DEFERRED_PLANS.md)**: the card fires **only on harvest breeding outcomes**
— the ``BreedingOutcome`` payload with >= 2 newborns placed. Breeding places at
most 1 newborn per type, so >= 2 placed means >= 2 types bred. This is the same
payload read Champion Breeder already uses for its "place 2 or 3+ newborn
animals" wording.

**User ruling 2026-07-21**: the Pig Breeder (A165) and Pure Breeder (D167)
end-of-round-12 card breeds are **sequential and distinct** events (1 newborn
each) — they never reach 2 newborns in one event and never trigger this card.

REQUIRED CAVEAT — any future card that can breed 2+ newborns outside
``_execute_breed`` must emit the ``BreedingOutcome`` payload, or this card and
Champion Breeder will under-fire. (A forum query on the round-12 simultaneity
question is outstanding; revisit if it rules simultaneous.)

THE ACCOMMODATION CLARIFICATION NEEDS NO CODE — "You must be able to
accommodate each newborn in order to get it" is inherent in the payload: an
unaccommodated newborn is never placed, so it never appears in the outcome
(``BreedingOutcome`` docstring, ``agricola/pending.py``; the Fodder Planter /
Champion Breeder precedent).

HOW IT FIRES — the outcome-reactive TRIGGER pattern (CARD_ENGINE_IMPLEMENTATION
.md §5b; the ``fodder_planter.py`` exemplar):

- **The outcome latch (an AUTO).** ``register_breeding_outcome_auto`` fires at
  ``CommitBreed`` with the ``BreedingOutcome`` payload. When >= 2 newborns were
  placed, the auto latches ``(round_number, outcome.total)`` in this card's own
  ``card_state`` entry. The latch is ROUND-KEYED: harvest rounds are unique, so
  a latch left over from a previous harvest never matches the current round and
  is inert with no clearing step.

- **The paid plow (an optional TRIGGER).** Registered on the breed frame's
  post-commit ``"breeding_outcome"`` event — reactions to WHICH newborns were
  just placed surface AFTER ``CommitBreed``, before ``Stop``, still inside the
  breeding phase (ruling 20's post-commit stretch). Eligibility reads THIS
  round's latch (>= 2 placed) and requires the pay-and-plow to be actually
  doable — food >= 1 AND a plowable cell (``legality._can_plow``) — so a fired
  trigger is never a dead end. Firing debits the 1 food directly (frame
  triggers carry no cost layer — the Stone Importer idiom) and pushes
  ``PendingPlow(initiated_by_id="card:dung_collector")``; the pushed primitive
  composes mid-harvest (the Autumn Mother precedent — the walk hosts it
  unchanged).

DECLINE PATH — "you can": declining is simply not firing the trigger (the breed
frame's ``Stop`` is always available alongside it); once fired, the pay-and-
plow is mandatory (optionality lives at the FireTrigger, the standard granted-
sub-action shape). Once per breeding event: the frame's ``triggers_resolved``
records the fire, and the latch is per-round (harvest rounds are unique).

Played via Lessons; on-play is a no-op (the effect is purely recurring).
Card-only registries and the CardStore entry are empty in the Family game, so
the Family game is byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_breeding_outcome_auto
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "dung_collector"
_FOOD_COST = 1


def _latch(state: GameState, idx: int):
    """This player's (harvest_round, newborns_placed) latch, or None."""
    return state.players[idx].card_state.get(CARD_ID)


def _latch_outcome(state: GameState, idx: int, outcome) -> GameState:
    """AUTO at CommitBreed (>= 2 newborns placed): latch this round's
    placed-newborn total, round-keyed (a stale latch from a past harvest
    round is inert)."""
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, (state.round_number, outcome.total)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _trig_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the paid plow iff THIS round's latch records >= 2 placed newborns
    AND the pay-and-plow is doable now (food >= 1, a plowable cell) — never a
    dead end. Ownership is the trigger enumerator's gate (and the latch is only
    ever written for an owner); once-per-breeding-event is the breed frame's
    ``triggers_resolved`` plus the round-keyed latch."""
    latch = _latch(state, idx)
    if latch is None or latch[0] != state.round_number or latch[1] < 2:
        return False
    p = state.players[idx]
    return p.resources.food >= _FOOD_COST and _can_plow(p)


def _trig_apply(state: GameState, idx: int) -> GameState:
    """Pay the 1 food (frame triggers carry no cost layer — debited directly,
    the Stone Importer idiom), then grant the plow."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


# Pure recurring occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# AUTO at CommitBreed: latch (round, placed-newborn total) when >= 2 newborns
# were placed (user ruling 74, 2026-07-21: harvest breeding outcomes only).
register_breeding_outcome_auto(
    CARD_ID, lambda state, idx, outcome: outcome.total >= 2, _latch_outcome)

# Optional post-commit trigger on the breed frame (the "breeding_outcome"
# stretch): pay 1 food, plow 1 field, still inside the breeding phase.
register("breeding_outcome", CARD_ID, _trig_eligible, _trig_apply)
