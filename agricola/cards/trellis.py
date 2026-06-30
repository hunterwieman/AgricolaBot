"""Trellis (minor improvement, C15; Corbarius Expansion; players -).

Card text: "Each time before you use the 'Pig Market' accumulation space, you can take a
'Build Fences' action. (You must pay wood for the fences as usual.)"
Prerequisite: 2 Occupations. No cost; no printed VPs; kept (not passing).

NOTE: do NOT confuse with "Trellises" [trellises] (Artifex deck A #47) — a different,
already-implemented card. This is deck C #15 [trellis].

An OPTIONAL, declinable `before_action_space` trigger on the Pig Market space that GRANTS
a literal Build Fences action. It combines two shapes already in the codebase:

- The action-space hook on a market (Assistant Tiller / Milk Jug): "each time before you
  use [the Pig Market]" fires on the space's `before_action_space` event (the card text is
  explicit — "before" — and the bare-"each time you use [space]" ruling agrees: BEFORE the
  space's own effect). Pig Market is a NON-ATOMIC space (`_initiate_pig_market` pushes a
  `PendingPigMarket` host frame), so its host frame is always present — NO
  `register_action_space_hook` is needed (that index only conditionally hosts ATOMIC spaces).

- The OPTIONAL granted Build Fences action (Field Fences): "you CAN take a Build Fences
  action" is the player's choice, so this is a declinable `register` trigger (NOT a
  choiceless `register_auto`). The optionality IS the FireTrigger — declining is simply not
  firing it (the host's Proceed). Once fired, `_apply` pushes the thin
  `PendingGrantedBuildFences` choose-or-decline wrapper (NOT the build host directly), which
  offers ChooseSubAction("build_fences") when a pasture is buildable, else only Stop. The
  wrapper's build_fences choice pushes the real multi-shot `PendingBuildFences` carrying this
  card's provenance ("card:trellis"); the player builds pasture(s) one at a time then Stops.
  The wrapper resolves fully, then the Pig Market before-phase exits via Proceed and the boar
  is granted — a before-phase fire, so the Build Fences happens BEFORE taking the pigs.

"You must pay wood for the fences as usual" → register NO free-fence seed/edge/pool and NO
cost reduction; the granted `PendingBuildFences` pays the normal wood cost.

Eligibility gates on (a) once per use (`triggers_resolved`) and (b) a pasture actually being
buildable under this grant's provenance (`_any_legal_pasture_commit`), so the FireTrigger is
never offered as a dead-end — mirroring Assistant Tiller's "never grant a dead-end
sub-action" gate. Played via Lessons; on-play is a no-op.

Card-only (the grant's restrictions / provenance are unrestricted-default skip-fields);
the Family game is byte-identical and the C++ gates are untouched. See
CARD_IMPLEMENTATION_PLAN.md Category 4 / COST_MODIFIER_DESIGN.md §9.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.pending import PendingGrantedBuildFences, push
from agricola.resources import Cost
from agricola.state import GameState

CARD_ID = "trellis"
FRAME_ID = "card:trellis"   # the granted Build Fences frame's initiated_by_id (provenance)
_SPACE = "pig_market"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                      # once per Pig Market use
        return False
    if state.pending_stack[-1].space_id != _SPACE:
        return False
    # Never a dead-end: a pasture must be buildable under THIS grant's provenance now
    # (Trellis registers no free-fence discount, so the anticipated budget is 0 → normal
    # wood cost). Anticipates exactly what the wrapper's enumerator will offer.
    from agricola.legality import _any_legal_pasture_commit
    return _any_legal_pasture_commit(
        state, state.players[idx], space_id=FRAME_ID, initiated_by_id=FRAME_ID)


def _apply(state: GameState, idx: int) -> GameState:
    # The FireTrigger already supplied the opt-in; push the choose-or-decline wrapper for the
    # natural multi-shot "build a pasture / Stop" loop (matching Field Fences). The wrapper
    # pushes the real PendingBuildFences with this card's provenance — no free-fence budget,
    # so it pays the normal wood cost.
    return push(state, PendingGrantedBuildFences(player_idx=idx, initiated_by_id=FRAME_ID))


register_minor(CARD_ID, cost=Cost(), min_occupations=2)   # no on-play effect (default no-op)
register("before_action_space", CARD_ID, _eligible, _apply)
