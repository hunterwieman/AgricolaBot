"""Harvest Festival Planning (minor improvement, C72; Corbarius Expansion;
Crop Provider).

Card text (verbatim): "When you play this card, immediately carry out the field
phase of the harvest. Afterwards, you get a "Major or Minor Improvement"
action."
Clarification (verbatim): "This is not a harvest and is for you only."
Cost: 1 Food. Prerequisite: "2 Occupations". No printed VPs. Kept (not passing).

TWO on-play pieces, in order:

1. THE FIELD PHASE (user rulings 4 and 12 — the Bumper Crop precedent). "Carry
   out the field phase of the harvest ... This is not a harvest and is for you
   only":
   - ruling 4 — this triggers the field-phase EFFECT, not the phase and not a
     harvest, so it does NOT run a harvest detour and does NOT walk the field
     window ladder. It applies the bare take (harvest 1 crop from each of the
     owner's planted fields) via ``resolution.field_take(state, idx,
     source="card:harvest_festival_planning")``, then emits its
     ``HarvestOccasion`` with ``resolution.emit_harvest_occasion`` so
     non-phase-keyed occasion consumers still attach.
   - "for you only" — ``field_take`` operates on exactly the owner's grid; the
     opponent's fields are untouched (the Bumper Crop "on your farmyard only").
   - "not a harvest" — the take runs during ``Phase.WORK`` with source
     ``"card:..."``, so phase-keyed occasion consumers (gated on
     ``HARVEST_FIELD``) and take-once consumers (gated on ``source == "take"``)
     stay silent (ruling 4). The crops still arrive on the owner's supply.
   - the unscoped choice-bearing take-modifier fold-in (Grain Thief) is the
     player's choice, surfaced as a ``PendingCardChoice`` over the feasible
     modifier combos exactly as Bumper Crop does; harvest-scoped modifiers
     (Scythe Worker, Stable Manure) never fold into a non-harvest field phase.

2. "AFTERWARDS, you get a 'Major or Minor Improvement' action" — the composite
   improvement action (ruling 64: "Major or Minor Improvement" = the composite,
   ``PendingMajorMinorImprovement`` — the Angler / Merchant precedent), pushed
   AFTER the field phase resolves, with its ``before_major_minor_improvement``
   autos fired manually at the push (the composite is a host, not a sub-action
   leaf). The grant is UNCONDITIONAL in the text, but the composite host has NO
   before-phase decline (its enumerator offers only the legal build_major /
   play_minor choices), so pushing it with no legal child would STALL. Angler's
   gate resolves this: push only when the action has a legal child (an
   affordable unowned major OR a playable hand minor); when it has none, the
   granted action is an unusable no-op and pushing nothing produces the
   identical outcome. The child check runs AFTER the take (the harvested grain/
   veg can make a crop-cost minor newly playable).

RELIANCE ON RULING 4 for the sequencing: ``emit_harvest_occasion`` pushes a
reaction frame only for an eligible occasion TRIGGER, and ruling 4 makes every
occasion trigger silent for a WORK-phase ``card:``-sourced take (they gate on
``HARVEST_FIELD`` / ``source == "take"``). So the stack is clean after the field
phase and the improvement action is correctly pushed on top of nothing — never
above a lingering reaction frame.

Cost "1 Food" → ``Cost(resources=Resources(food=1))``; prerequisite "2
Occupations" → ``min_occupations=2``.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    apply_auto_effects,
    register_card_choice_resolver,
)
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "harvest_festival_planning"


def _take_then_grant(state: GameState, idx: int, modifiers=()) -> GameState:
    """Run the bare field-phase take (with any chosen unscoped-modifier uses
    folded in), emit its occasion, THEN grant the "Major or Minor Improvement"
    action. Imported locally (the cards package is imported by the engine, so a
    top-level ``import resolution`` would cycle — the load-order-safe idiom)."""
    from agricola import resolution
    from agricola.cards.harvest_windows import fold_chosen_modifiers

    plan = fold_chosen_modifiers(state, idx, modifiers, harvest=False)
    assert plan is not None, "infeasible modifier combo at Harvest Festival Planning"
    state, occasion = resolution.field_take(
        state, idx, source=f"card:{CARD_ID}",
        extra_takes=plan.extras or None,
        skip_cells=plan.skipped, bonus=plan.bonus)
    state = resolution.emit_harvest_occasion(state, idx, occasion)

    # "Afterwards, you get a 'Major or Minor Improvement' action" — push the
    # composite only when it has a legal child (Angler's gate; a childless
    # composite host would stall, and an unusable granted action is a no-op
    # anyway). The check is after the take (harvested crops can enable a minor).
    p = state.players[idx]
    if _can_afford_any_major_improvement(state, p) or playable_minors(state, idx):
        state = push(state, PendingMajorMinorImprovement(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))
        state = apply_auto_effects(state, "before_major_minor_improvement", idx)
    return state


def _on_play(state: GameState, idx: int) -> GameState:
    """Immediately carry out the field phase on the owner's farmyard only, then
    grant the improvement action. When the owner also owns a usable unscoped
    choice-bearing take-modifier (Grain Thief), the use is the player's choice —
    surface it as a ``PendingCardChoice`` over the feasible modifier combos (the
    bare ``()`` = use none) and defer the take-and-grant to the pick; otherwise
    take directly (the Bumper Crop shape)."""
    from agricola.cards.harvest_windows import take_modifier_combos
    from agricola.pending import PendingCardChoice

    combos = take_modifier_combos(state, idx, harvest=False)
    if len(combos) > 1:
        return push(state, PendingCardChoice(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
            options=tuple(combos)))
    return _take_then_grant(state, idx)


def _resolve_choice(state: GameState, idx: int, chosen) -> GameState:
    """Apply the picked modifier combination (the PendingCardChoice contract:
    pop the frame, then run the take-and-grant with the chosen uses folded in)."""
    from agricola.pending import pop
    return _take_then_grant(pop(state), idx, modifiers=chosen)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    min_occupations=2,
    on_play=_on_play,
)
register_card_choice_resolver(CARD_ID, _resolve_choice)
