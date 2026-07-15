"""Cottar (occupation, E122; Ephipparius Expansion; players 1+).

Card text: "Each time you play or build an improvement, you get your choice of
1 wood or 1 clay immediately after paying its cost."

USER RULING (2026-07-15): "immediately after paying its cost" is implemented as
the improvement's ordinary AFTER window — i.e. after the improvement resolves,
its own effect included (the deferred after-flip, ruling 60) — matching the
official online implementation; the user chose consistency with it despite the
printed wording naming the payment instant.

Shape: MANDATORY-with-choice ("you get your choice" — the gain cannot be
declined, only directed) on BOTH improvement events, own actions only:

- ``after_play_minor`` — every minor-play route (the improvement spaces, House
  Redevelopment's step, Basic Wish, Meeting Place, card grants) runs through
  the one sub-action host, and a traveling minor is played like any other.
- ``after_build_major`` — every major build.

An OCCUPATION is not an improvement, so Cottar's own play never fires it.
The host's phase-exit (Stop) is withheld while the trigger is unfired (the
mandatory gate, added to these two hosts' after-phases alongside this card);
firing pushes the wood-or-clay ``PendingCardChoice`` and the registered
resolver grants the pick. Once per improvement via the host frame's
``triggers_resolved``.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_card_choice_resolver
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "cottar"

_GAINS = {"1 wood": Resources(wood=1), "1 clay": Resources(clay=1)}


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return CARD_ID not in triggers_resolved


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id="card:cottar",
        options=tuple(_GAINS)))


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _GAINS[chosen])
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return pop(state)   # resolver owns the PendingCardChoice frame


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("after_play_minor", CARD_ID, _eligible, _apply, mandatory=True)
register("after_build_major", CARD_ID, _eligible, _apply, mandatory=True)
register_card_choice_resolver(CARD_ID, _resolve)
