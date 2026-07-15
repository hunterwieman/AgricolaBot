"""Informant (occupation, deck B #117; Bubulcus Expansion; 1+ players).

Card text: "When you play this card, you immediately get 1 wood. After each
work phase, if you have more stone than clay in your supply, you get 1 wood."
Category: Building Resource Provider.

Two pieces:

- **the on-play grant** — "you immediately get 1 wood" is a mandatory
  pure-goods gain at play time: `on_play` credits +1 wood, no choice, no frame.

- **the recurring grant** — "after each work phase" is the round-end ladder's
  `after_work` rung. User ruling (2026-07-14): "after each work phase" = the
  round-end ladder's `after_work` rung (ruling 50's separate rung, glossed
  "immediately before the returning home phase" — the user confirmed these
  merge for this card). The grant is mandatory and choice-free — a pure-goods
  gain with no downside — so it is an automatic effect (`register_auto`),
  never a forced FireTrigger button (ruling 21, 2026-07-05: a mandatory
  choice-free tier is an AUTO). The ladder walk fires the `after_work` window
  per player, starting player first; each owner's copy fires on their own
  supply.

- **the condition** — "if you have more stone than clay in your supply" is the
  bearer's own eligibility clause, checked at the instant the window fires:
  `p.resources.stone > p.resources.clay` (strictly more; equal counts do not
  qualify). "In your supply" is a HAVE-check, never a cost — nothing is spent.
  The ladder itself runs unconditioned every round, harvest rounds included
  (the round end precedes the harvest), so the grant fires on any round whose
  end finds more stone than clay.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "informant"


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card, you immediately get 1 wood." """
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    """"...if you have more stone than clay in your supply" — strictly more,
    read from the owner's supply at the after_work instant."""
    p = state.players[idx]
    return p.resources.stone > p.resources.clay


def _apply(state: GameState, idx: int) -> GameState:
    """"...you get 1 wood." Mandatory and choice-free: +1 wood to the owner."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_auto("after_work", CARD_ID, _eligible, _apply)
