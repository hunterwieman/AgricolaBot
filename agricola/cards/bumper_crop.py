"""Bumper Crop (minor improvement, E25; Ephipparius Expansion; players -).

Card text (verbatim): "When you play this card, immediately play the field phase
of the harvest on your farmyard only."

Cost: none (free). Printed VPs: 1. Prerequisite: "2 Grain Fields". Kept (not
passing). Category: Actions Booster.

ON-PLAY field-phase effect (user rulings 4 and 12, quoted in
``CARD_DEFERRED_PLANS.md`` → "Harvest-window redesign — user rulings"):

- **Ruling 4** — Bumper Crop "triggers the field-phase EFFECT, not the phase and
  not a harvest." So the on-play does NOT run a harvest detour and does NOT walk
  the field-phase window ladder; it applies the bare take (harvest 1 crop from
  each of the owner's planted fields) directly, via
  ``resolution.field_take(state, idx, source="card:bumper_crop")``, then emits its
  ``HarvestOccasion`` with ``resolution.emit_harvest_occasion`` so non-phase-keyed
  occasion consumers still attach to it.

- **"on your farmyard only"** — ``field_take`` operates on exactly one player's
  grid (the owner's ``idx``), which is what this clause requires; the opponent's
  fields are untouched.

- **NO take-modifier fold-ins.** ``field_take`` is called with no ``extra_takes``.
  Both implemented take-modifiers (Scythe Worker, Stable Manure) are printed "in
  the field phase of EACH HARVEST" — harvest-event-scoped (ruling 12) — so they do
  not fold into a card-played field-phase effect that is not a harvest.

- **No phase-keyed cards fire.** The take runs during ``Phase.WORK`` (the card is
  played mid-round), and its occasion carries ``source="card:bumper_crop"``. So:
  - Phase-scoped occasion consumers (Crack Weeder, Potato Harvester — "in the field
    phase of a harvest", gated on ``state.phase == Phase.HARVEST_FIELD``) stay
    silent, because the phase is WORK, not HARVEST_FIELD.
  - Take-once occasion consumers (Grain Sieve, Barley Mill — ruling 9, gated on
    ``occasion.source == "take"``) stay silent, because the source is
    ``"card:bumper_crop"``, not ``"take"``.
  The crops still arrive on the owner's supply regardless — only the field-phase
  bonus cards are (correctly) inert.

Prerequisite "2 Grain Fields" is a HAVE-check at PLAY time: at least two of the
player's own FIELD cells currently hold grain (``cell.grain > 0``, ``>= 2``) — the
same definition Raised Bed / Bale of Straw / Gardener's Knife use for a "grain
field". A prerequisite is checked, never spent (distinct from the cost).

Card-only state is empty (no CardStore use), so the Family game is byte-identical
and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_card_choice_resolver
from agricola.constants import CellType
from agricola.state import GameState

CARD_ID = "bumper_crop"


def _prereq(state: GameState, idx: int) -> bool:
    """2 Grain Fields — at least two FIELD cells that currently hold grain."""
    grid = state.players[idx].farmyard.grid
    grain_fields = sum(
        1
        for row in grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    )
    return grain_fields >= 2


def _take(state: GameState, idx: int, modifiers=()) -> GameState:
    """The bare take with the chosen UNSCOPED-modifier uses folded in, then
    emit its occasion. Harvest-scoped modifiers (Stable Manure, Scythe
    Worker, Scythe) never fold here (ruling 12 — this is not a harvest);
    unscoped ones (Grain Thief's per-field replacement) do, because "each
    time you would harvest a grain field" reads on the field-phase effect
    wherever it runs.

    Imported here (not at module top) to avoid an import cycle — the cards
    package is imported by the engine, so a top-level ``import resolution``
    would cycle. The load-order-safe pattern the rest of the cards package
    uses.
    """
    from agricola import resolution
    from agricola.cards.harvest_windows import fold_chosen_modifiers

    plan = fold_chosen_modifiers(state, idx, modifiers, harvest=False)
    assert plan is not None, "infeasible modifier combo offered at Bumper Crop"
    state, occasion = resolution.field_take(
        state, idx, source="card:bumper_crop",
        extra_takes=plan.extras or None,
        skip_cells=plan.skipped, bonus=plan.bonus)
    return resolution.emit_harvest_occasion(state, idx, occasion)


def _on_play(state: GameState, idx: int) -> GameState:
    """Immediately play the field phase EFFECT on the owner's farmyard only
    (ruling 4). When the owner also owns a usable UNSCOPED choice-bearing
    take-modifier (Grain Thief), the use is the player's choice — surface it
    as a PendingCardChoice over the feasible modifier combinations (the bare
    `()` = use none) and resolve the take on the pick; otherwise take
    directly."""
    from agricola.cards.harvest_windows import take_modifier_combos
    from agricola.pending import PendingCardChoice, push

    combos = take_modifier_combos(state, idx, harvest=False)
    if len(combos) > 1:
        return push(state, PendingCardChoice(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
            options=tuple(combos)))
    return _take(state, idx)


def _resolve_choice(state: GameState, idx: int, chosen) -> GameState:
    """Apply the picked modifier combination (the PendingCardChoice contract:
    pop the frame, then run the take with the chosen uses folded in)."""
    from agricola.pending import pop
    return _take(pop(state), idx, modifiers=chosen)


register_minor(CARD_ID, prereq=_prereq, vps=1, on_play=_on_play)
register_card_choice_resolver(CARD_ID, _resolve_choice)
