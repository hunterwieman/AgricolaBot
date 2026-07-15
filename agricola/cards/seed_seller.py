"""Seed Seller (occupation, D141; Consul Dirigens Expansion; players 3+).

Card text: "When you play this card, you immediately get 1 grain. Each time you use the
'Grain Seeds' action space, you get 1 additional grain."

Two effects, both on existing seams:
- on-play: +1 grain (the "immediately get [goods] on play" instant — the Consultant /
  Millwright pattern; the effect fires when the card enters the tableau).
- Category 3 (action-space hook, automatic income) — the Corn Scoop shape: a mandatory,
  choice-free +1 grain each time the owner uses Grain Seeds. "Each time you use" → the
  BEFORE window; a flat +1 grain does not read the space's own effect, so before is
  correct. Grain Seeds is atomic, so `register_action_space_hook` hosts it when owned.

This is a [3+] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "seed_seller"
SPACES = frozenset({"grain_seeds"})


def _on_play(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int) -> bool:
    return getattr(state.pending_stack[-1], "space_id", None) in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _on_play)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
