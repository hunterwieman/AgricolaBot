"""Fodder Planter (occupation, D115; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "In the breeding phase of each harvest, for each newborn
animal you get, you can sow crops in exactly 1 field."
Clarifications (verbatim): "You must be able to accommodate each newborn in
order to get it.  You may not plant onto Wood Field D075 this way."
Occupation — no cost / prerequisite / VPs.

WHAT THE CARD DOES — at each harvest's breeding, every newborn the player
actually gets earns them one optional sow of exactly one field (a normal sow:
1 grain from supply -> 3 on the field, 1 veg -> 2), still inside the breeding
phase. Two seams carry it:

- **The outcome latch (an AUTO).** ``register_breeding_outcome_auto`` fires at
  ``CommitBreed`` with the ``BreedingOutcome`` payload — which newborns were
  actually PLACED. The auto latches ``(round_number, outcome.total)`` in this
  card's own ``card_state`` entry. The latch is ROUND-KEYED: harvest rounds are
  unique, so a latch left over from a previous harvest never matches the
  current round and is inert with no clearing step. The printed accommodation
  clarification is inherent in the payload — an unaccommodated newborn is
  never placed, so it never appears in the outcome (``BreedingOutcome``
  docstring, ``agricola/pending.py``).

- **The sow grant (an optional TRIGGER).** Registered on the breed frame's
  post-commit ``"breeding_outcome"`` event. **User ruling 20 (2026-07-05)**:
  outcome-reactive breeding grants surface AFTER CommitBreed, before Stop,
  still inside the breeding phase — the breed frame's "breeding_outcome"
  trigger event. Eligibility reads THIS round's latch (> 0 newborns) and
  requires a sow to be actually committable — at least one empty FIELD cell
  AND grain or veg in supply — so a fired trigger is never a dead frame.
  Firing pushes ``PendingSow(max_fields=<latched newborn total>)``: k newborns
  cap the one commit at k fields, the enumerator offers grain+veg in 1..k, so
  each granted field is individually optional (partial use is legal).

DECLINE PATH — **granted sub-actions are optional** even when worded like a
command: declining ALL k sows is simply not firing the trigger (the breed
frame's Stop is always available alongside it), and sowing fewer than k fields
is the partial-use middle. Once fired, the sow frame requires at least one
field — the optionality lives at the FireTrigger, the standard granted-
sub-action shape (CARD_AUTHORING_GUIDE.md "A granted sub-action is optional").
Once per breeding phase comes free from the breed frame's
``triggers_resolved``.

THE WOOD FIELD D075 EXCLUSION — "You may not plant onto Wood Field D075 this
way" is currently vacuously satisfied as a fact about the engine: card-created
fields do not exist yet (Wood Field D075 is unimplemented), so every FIELD
cell this card's granted sow can reach is an ordinary field. When card-fields
land, their implementation must respect this exclusion (the granted
``PendingSow`` carries ``initiated_by_id="card:fodder_planter"`` as the hook
for that gate).

Played via Lessons; on-play is a no-op (the effect is purely recurring).
Card-only registries are empty in the Family game, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_breeding_outcome_auto
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.constants import CellType
from agricola.pending import PendingSow, push
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "fodder_planter"


def _latch(state: GameState, idx: int):
    """This player's (harvest_round, newborn_total) latch, or None."""
    return state.players[idx].card_state.get(CARD_ID)


def _latch_outcome(state: GameState, idx: int, outcome) -> GameState:
    """AUTO at CommitBreed: latch this round's placed-newborn total,
    round-keyed (a stale latch from a past harvest round is inert)."""
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, (state.round_number, outcome.total)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _sow_committable(state: GameState, idx: int) -> bool:
    """Is a sow actually committable — >= 1 empty FIELD cell AND grain or veg
    in supply, or an empty CROP card-field with matching supply (this grant is
    crops-explicit, so wood/stone card-fields never qualify — ruling 48,
    2026-07-12)? Never push a frame with no legal commit."""
    from agricola.cards.card_fields import can_sow_card_fields

    p = state.players[idx]
    board_ok = (
        (p.resources.grain > 0 or p.resources.veg > 0)
        and any(
            cell.cell_type == CellType.FIELD
            and cell.grain == 0 and cell.veg == 0
            for row in p.farmyard.grid for cell in row))
    return board_ok or can_sow_card_fields(p, crops_only=True)


def _trig_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the sow grant iff THIS round's latch records >= 1 placed newborn
    and a sow is committable. Ownership is the trigger enumerator's gate;
    once-per-breeding-phase is the breed frame's ``triggers_resolved``."""
    latch = _latch(state, idx)
    if latch is None or latch[0] != state.round_number or latch[1] <= 0:
        return False
    return _sow_committable(state, idx)


def _trig_apply(state: GameState, idx: int) -> GameState:
    """Push the granted sow, capped at this round's newborn total: k newborns
    -> up to k fields in one commit (the enumerator offers 1..k; declining all
    = not firing this trigger). `crops_only`: the card prints "sow CROPS" —
    a crops-explicit grant that may not plant wood/stone card-fields (user
    ruling 48, 2026-07-12; the card's own clarification: "You may not plant
    onto Wood Field D075 this way")."""
    latch = _latch(state, idx)
    return push(state, PendingSow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
        max_fields=latch[1], crops_only=True))


# Pure recurring-harvest occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# AUTO at CommitBreed: latch (round, placed-newborn total) in card_state.
register_breeding_outcome_auto(
    CARD_ID, lambda state, idx, outcome: outcome.total > 0, _latch_outcome)

# Optional post-commit trigger on the breed frame (user ruling 20, 2026-07-05):
# fire to sow up to <newborn total> fields, still inside the breeding phase.
register("breeding_outcome", CARD_ID, _trig_eligible, _trig_apply)
