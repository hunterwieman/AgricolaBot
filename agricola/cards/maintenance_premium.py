"""Maintenance Premium (minor improvement, B55; Bubulcus Expansion; players -).

Card text: "Place 3 food on this card. Each time you use a wood accumulation space,
you get 1 food from this card. Each time you renovate restock this card to 3 food."
Prerequisite: 2 Occupations. No printed cost. No VPs. Not passing.

A FOOD-bearing card: it holds a small reservoir of food (a `CardStore` scalar,
keyed "maintenance_premium") that pays the owner 1 food each time they use a wood
accumulation space, and is topped back up to 3 each time they renovate. Two
mandatory, choice-free clauses → automatic effects (`register_auto`), one per hook;
neither is ever surfaced to the agent.

- **place 3 food on this card** (on play) → seed the CardStore reservoir at 3.
- **use a wood accumulation space → +1 food from the card** → `before_action_space`
  on the Forest (the only wood accumulation space on the 2-player board; Copse /
  Grove are 3–4-player board-extension spaces). Mandatory and choice-free, and the
  +1 food is independent of the space's own wood pickup, so it rides the
  `before_action_space` event (the Wood Cutter pattern). Pays out only while the
  reservoir holds food — `card_state > 0` — so once drained it is inert until a
  renovate restocks it (the "from this card" wording: the food comes off the card,
  not the general supply). The Forest must be HOSTED for the auto to fire, which
  `register_action_space_hook({"forest"})` arranges (the atomic fast path is bypassed
  once the owner holds this card).
- **renovate → restock to 3** → `after_renovate`, unconditional (the owner gate is
  applied by `apply_auto_effects`; every renovate — wood→clay AND clay→stone —
  restocks, matching "each time you renovate"). Sets the reservoir back to exactly 3,
  NOT +3 (a restock-to, not a top-up).

Played as a minor (prereq 2 occupations). Card-only state (the reservoir lives in
CardStore, default empty → the Family game is byte-identical and the C++ gates are
untouched). Template: wood_cutter.py + roughcaster.py + ash_trees.py. See
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "maintenance_premium"

STARTING_FOOD = 3   # food placed on the card at play and restocked to on renovate


def _on_play(state: GameState, idx: int) -> GameState:
    """Place 3 food on the card (seed the CardStore reservoir)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, STARTING_FOOD))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- wood-space payout: +1 food from the card, while the reservoir holds food ---

def _eligible_wood_space(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space uniformly via
    # the host frame's `space_id`. Pay out only while food remains on the card.
    return (state.pending_stack[-1].space_id in WOOD_ACCUMULATION_SPACES
            and state.players[idx].card_state.get(CARD_ID, 0) > 0)


def _apply_wood_space(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    remaining = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=1),
        card_state=p.card_state.set(CARD_ID, remaining - 1),
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- renovate: restock the card to 3 food ---

def _eligible_renovate(state: GameState, idx: int) -> bool:
    # Every renovate restocks (owner gate applied by apply_auto_effects).
    return True


def _apply_renovate(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, STARTING_FOOD))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, min_occupations=2, on_play=_on_play)
register_auto("before_action_space", CARD_ID, _eligible_wood_space, _apply_wood_space)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
register_auto("after_renovate", CARD_ID, _eligible_renovate, _apply_renovate)
