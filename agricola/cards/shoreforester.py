"""Shoreforester (occupation, B116; Bubulcus Expansion; players 1+).

Card text: "When you play this card and each time 1 reed is placed on an empty
"Reed Bank" accumulation space in the preparation phase, you get 1 wood."

Two halves (integrator classification, 2026-07-15):

- **On-play** — "When you play this card … you get 1 wood": an unconditional
  one-shot at play time (Category 2; consultant.py is the template).

- **The recurring half** — "each time 1 reed is placed on an empty 'Reed Bank'
  accumulation space in the preparation phase, you get 1 wood": mandatory and
  choice-free, so a `register_auto` on the preparation ladder's `replenishment`
  window (ruling 54, 2026-07-14) — the reaction seam immediately after the
  `__replenish__` sentinel runs the mechanical refill. Nest Site (nest_site.py)
  is the direct precedent: the same "reed placed on the Reed Bank during the
  preparation phase" instant, with the OPPOSITE eligibility (Nest Site pays on a
  non-empty bank, Shoreforester on an empty one).

The window fires right after the refill, so this auto sees the POST-refill
board. The Reed Bank accumulates exactly +1 reed each preparation (its
building-accumulation rate), so post-refill reed == (pre-refill reed) + 1:
  - empty before refill    → post-refill reed == 1 → reed placed on an EMPTY bank → +1 wood.
  - non-empty before refill → post-refill reed >= 2 → placed on a NON-EMPTY bank → nothing.
So `accumulated.reed == 1` at the replenishment window is exactly the "placed
on an empty Reed Bank" condition. CAVEAT on this equivalence: it holds while
nothing else adds reed to the Reed Bank during preparation before the
replenishment window fires; if a future card does, this check must become a
pre-refill snapshot instead of a post-refill count. (The Reed Bank is a
building-resource accumulation space: read `accumulated.reed`, never
`accumulated_amount`.)

The condition is about the SPACE, not about who emptied it — the text has no
"you" in the recurring half — so the owner is paid whichever player (or nobody:
a bank that simply started empty) left the bank empty. Only the card's owner is
paid; a card still in hand registers nothing on the board and is inert.

Round 1 is naturally excluded: setup deals the round-1 board directly and never
runs a preparation phase, so the first possible payout is the round-2
preparation.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "shoreforester"


def _give_wood(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _on_play(state: GameState, idx: int) -> GameState:
    # "When you play this card … you get 1 wood" — unconditional.
    return _give_wood(state, idx)


def _eligible(state: GameState, idx: int) -> bool:
    # Post-refill: reed_bank.accumulated.reed == 1 means the bank was EMPTY
    # before this round's +1 refill — i.e. the reed was placed on an empty bank.
    # (Equivalence caveat: see the module docstring.)
    return get_space(state.board, "reed_bank").accumulated.reed == 1


def _apply(state: GameState, idx: int) -> GameState:
    return _give_wood(state, idx)


register_occupation(CARD_ID, _on_play)
register_auto("replenishment", CARD_ID, _eligible, _apply)
