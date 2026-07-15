"""Vegetable Vendor (occupation, deck E #141; Ephipparius Expansion; players 3+).

Card text (verbatim): "Each time you use the "Major Improvement" or "Vegetable
Seeds" action space, you also get 1 vegetable or a "Major or Minor Improvement"
action, respectively."
Category: Crop Provider. No printed VPs.

"respectively" pairs each space with its reward, and "Each time you use" is the
Trigger-Timing ruling's BEFORE window (fires before the space's own effect — flat
rewards, observationally neutral, but fixed to before by the ruling). Two clauses:

- **Major Improvement -> +1 vegetable.** A mandatory, flat, parameter-free gain
  -> an AUTOMATIC effect on `before_action_space`, filtered to the Major
  Improvement action space's own `action_space` surface (space_id
  "major_improvement" — the PendingSubActionSpace wrapper, distinct from House
  Redevelopment and from card grants of the composite). The +1 veg does not touch
  the composite's building-resource cost, so a before auto never strands the
  improvement.

- **Vegetable Seeds -> a "Major or Minor Improvement" action.** A granted ACTION
  is optional (only "you must" is mandatory) -> an OPTIONAL trigger
  (`register`, declined by the host's Proceed). Firing pushes a fresh
  `PendingMajorMinorImprovement` (the composite: build a major OR play a minor)
  with this card's provenance and fires its before-autos at the push — the
  Angler / Merchant granted-composite idiom. Vegetable Seeds is an atomic
  accumulation-free space, so `register_action_space_hook` hosts it when the card
  is owned (the Cottager before-window-grant-on-an-atomic-space precedent). The
  before-window grant does not consume the space's own vegetable, so it never
  strands it. Eligibility never pushes a dead composite: it requires an affordable
  unowned major OR a playable hand minor (the composite's own child predicates);
  once per use via the host's `triggers_resolved`.

Played via Lessons; card-only registries — the Family game is byte-identical and
the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    apply_auto_effects, register, register_action_space_hook, register_auto,
)
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "vegetable_vendor"
_MAJOR = "major_improvement"
_VEG_SEEDS = "vegetable_seeds"


# --- Clause 1: the Major Improvement space grants +1 vegetable (auto) ---------

def _on_major(state: GameState, idx: int) -> bool:
    return getattr(state.pending_stack[-1], "space_id", None) == _MAJOR


def _grant_veg(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# --- Clause 2: the Vegetable Seeds space grants a composite action (trigger) ---

def _on_veg_seeds(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if getattr(state.pending_stack[-1], "space_id", None) != _VEG_SEEDS:
        return False
    # Never push a dead composite: a legal child must exist right now.
    return (_can_afford_any_major_improvement(state, state.players[idx])
            or bool(playable_minors(state, idx)))


def _grant_improvement(state: GameState, idx: int) -> GameState:
    state = push(state, PendingMajorMinorImprovement(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))
    # The composite is itself a host: fire its before-autos at the push (the
    # Merchant / Angler granted-composite idiom).
    return apply_auto_effects(state, "before_major_minor_improvement", idx)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _on_major, _grant_veg)
register("before_action_space", CARD_ID, _on_veg_seeds, _grant_improvement)
register_action_space_hook(CARD_ID, frozenset({_VEG_SEEDS}))
