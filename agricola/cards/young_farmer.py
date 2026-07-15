"""Young Farmer (occupation, D112; Dulcinaria Expansion; players 1+; Crop Provider).

Card text (verbatim): "Each time you use the "Major Improvement" action space,
you also get 1 grain and, afterward, you can take a "Sow" action."
No cost, no prerequisite, no printed VPs.

TWO HALVES, both riding the Major Improvement space's host frame. That space is
a Delegating host — ``_initiate_major_improvement`` always pushes a
``PendingSubActionSpace`` for ``space:major_improvement`` and fires
``before_action_space`` autos at the push — so the space is NON-atomic and
already hosted: NO ``register_action_space_hook`` (that index only governs
atomic spaces); both halves just filter ``space_id == "major_improvement"``
in eligibility (the Pan Baker / Teacher's Desk idiom).

1. **The +1 grain** — "each time you use [space], you also get 1 grain" is a
   mandatory, choice-free grant with no timing qualifier, so it is an AUTOMATIC
   effect on the ``before_action_space`` window ("each time you use" = before,
   the default ruling). Because the auto fires at the host push — before the
   branch choice even exists — it fires on ANY use of the space: the
   build-a-major branch and the play-a-minor branch alike (the granted grain
   can even pay a 1-grain minor's cost on that same use). Ownership-gated by
   the auto dispatch, so an opponent's use of the space pays nothing and a
   hand-only copy is inert.

2. **The Sow grant** — "afterward, you can take a 'Sow' action": the printed
   "afterward" puts it on ``after_action_space``, and "you can" makes it an
   OPTIONAL trigger (user confirmation 2026-07-14: the sow is optional, like
   Little Stick Knitter's growth). Per the deferred after-flip (ruling 60,
   2026-07-14) the after-phase — and so this trigger — surfaces only once the
   space's WHOLE work (the built major's own pushed effects, e.g. an oven's
   free bake, included) has resolved. Eligibility gates on the engine's own
   sow-possibility predicate ``legality._can_sow`` (>= 1 empty field cell AND
   grain/veg in supply — or a card-field sow: this is a generic "Sow" grant,
   so card fields qualify per rulings 45-48, 2026-07-12) so a fire is never a
   dead end (a pushed ``PendingSow`` offers no Stop). Firing pushes the full,
   UNCAPPED ``PendingSow`` — "a 'Sow' action" is the standard sow (any number
   of empty fields, grain and/or veg), the Slurry Spreader C71 precedent.
   Declining is simply not firing (the host's Stop; optionality lives at the
   parent — no SkipTrigger). "Each time" = once per use of the space, enforced
   by the host frame's ``triggers_resolved``.

Card-only registries, ownership-gated at dispatch: no Family game ever owns
the card, so the Family game is byte-identical and the C++ differential gates
are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_auto
from agricola.legality import _can_sow
from agricola.pending import PendingSow, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "young_farmer"

_SPACE = "major_improvement"


# --- half 1: +1 grain on every use of the space (before-window auto) ---------

def _grain_eligible(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host push; the host frame is on top.
    return state.pending_stack[-1].space_id == _SPACE


def _grain_apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- half 2: the optional "afterward" Sow grant (after-window trigger) -------

def _sow_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Once per use of the space (the host frame's triggers_resolved).
    if CARD_ID in triggers_resolved:
        return False
    if state.pending_stack[-1].space_id != _SPACE:
        return False
    # Never a dead-end fire: the engine's own sow predicate (>= 1 empty field
    # cell AND a crop in supply, or a card-field sow — rulings 45-48).
    return _can_sow(state.players[idx])


def _sow_apply(state: GameState, idx: int) -> GameState:
    # The full standard "Sow" action: an uncapped PendingSow.
    return push(state, PendingSow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _grain_eligible, _grain_apply)
register("after_action_space", CARD_ID, _sow_eligible, _sow_apply)
