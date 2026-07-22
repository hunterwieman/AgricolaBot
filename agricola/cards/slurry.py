"""Slurry (minor improvement, C71; Corbarius Expansion; Crop Provider).

Card text (verbatim): "In the breeding phase of each harvest, if you get newborn
animals of at least two types, you also get a "Sow" action."
Clarification (printed): "You must be able to accommodate each newborn in order
to get it."
No cost, no prerequisite, no printed VPs.

card_id `slurry` (== the name slug). NOTE: the unrelated Artifex A106 occupation
is named "Slurry Spreader" (a last-crop-from-a-field income card) and owns the
distinct `slurry_spreader` slug — no collision, so no (slug, deck) alias is needed.

TIMING — the breed frame's post-commit stretch (user ruling 20, 2026-07-05:
an outcome-reactive breeding grant surfaces AFTER CommitBreed, before Stop,
still inside the breeding phase — the ``PendingHarvestBreed`` frame's
"breeding_outcome" trigger event). Two seams carry it:

- ``register_breeding_outcome_auto``: at CommitBreed the engine hands every
  registered consumer the ``BreedingOutcome`` payload — which newborns were
  actually PLACED (0/1 per type). Eligibility is the printed condition,
  ``outcome.types >= 2``; the apply latches the qualification ROUND-KEYED in
  this card's card_state (harvest rounds are unique, so a stale latch from an
  earlier harvest is inert with no clearing step). The printed clarification
  is inherent in the payload: a newborn the player cannot accommodate is
  never placed, so it never appears in the outcome.
- ``register("breeding_outcome", …)``: the optional FireTrigger offered on
  the still-open breed frame after the commit. Eligibility = this round's
  latch AND a sow being committable right now (>= 1 empty field cell AND
  grain or veg in supply) — a pushed ``PendingSow`` with no legal commit
  would be a dead frame, so the trigger is withheld instead
  (CARD_AUTHORING_GUIDE.md §2). Firing pushes an UNCAPPED ``PendingSow`` —
  "a 'Sow' action" is the full standard sow (any number of empty fields,
  grain and/or veg), unlike Fodder Planter's per-newborn ``max_fields`` cap.
  Once per harvest comes from the breed frame's ``triggers_resolved``.

OPTIONALITY — "you also get a 'Sow' action" grants a sub-action, and a granted
sub-action must have a decline path (CARD_AUTHORING_GUIDE.md — granted
sub-actions are optional): declining is Stop on the breed frame without firing
the trigger. Once fired, the sow commits like any standard sow (at least one
field; eligibility guarantees a commit exists).

Card-only registries, all ownership-gated at the enumerator/auto dispatch: no
Family game ever owns the card, so the Family game is byte-identical and the
C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_breeding_outcome_auto
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.constants import CellType
from agricola.pending import PendingSow, push
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "slurry"


def _sow_committable(state: GameState, idx: int) -> bool:
    """Can a pushed PendingSow commit right now? Requires >= 1 empty FIELD
    cell AND a crop (grain or veg) in supply — or a card-field sow (this is
    a GENERIC "Sow" grant, so wood/stone card-fields qualify too; ruling 48,
    2026-07-12). The never-push-a-dead-frame gate (a before-phase PendingSow
    offers no Stop)."""
    from agricola.cards.card_fields import can_sow_card_fields

    p = state.players[idx]
    board_ok = (
        (p.resources.grain >= 1 or p.resources.veg >= 1)
        and any(
            cell.field_empty   # stone-holding fields excluded (Stone Clearing)
            for row in p.farmyard.grid for cell in row))
    return board_ok or can_sow_card_fields(p)


def _outcome_elig(state: GameState, idx: int, outcome) -> bool:
    # The printed condition: newborn animals of at least two types, counting
    # only newborns actually placed (the payload holds PLACED newborns only,
    # so the accommodation clarification is inherent).
    return outcome.types >= 2


def _outcome_apply(state: GameState, idx: int, outcome) -> GameState:
    # Latch "this harvest's breeding qualified", keyed by the harvest round
    # (harvest rounds are unique — a stale latch is inert next harvest).
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, state.round_number))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _trig_elig(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    # This round's latch AND the sow being committable. Ownership is the
    # enumerator's _owns gate; once-per-harvest is the breed frame's
    # triggers_resolved (checked by the enumerator, not here).
    p = state.players[idx]
    return (p.card_state.get(CARD_ID) == state.round_number
            and _sow_committable(state, idx))


def _trig_apply(state: GameState, idx: int) -> GameState:
    # The full standard "Sow" action: an uncapped PendingSow (max_fields=0).
    return push(state, PendingSow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID)                     # no cost, no prerequisite, no VPs
register_breeding_outcome_auto(CARD_ID, _outcome_elig, _outcome_apply)
register("breeding_outcome", CARD_ID, _trig_elig, _trig_apply)
