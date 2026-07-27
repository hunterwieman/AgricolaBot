"""Fir Cutter (occupation, E116; Ephipparius Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 food. Each time
after you use an animal accumulation space with your 1st/2nd/3rd/4th/5th
person, you get 1/1/2/2/3 wood."

Two effects:

  - On play: a one-time +1 food (choice-free goods grant, the
    `register_occupation` on-play hook).
  - Each time AFTER the owner uses an animal accumulation space — Sheep Market,
    Pig Market, or Cattle Market — a mandatory choiceless wood grant whose size
    is keyed to WHICH of the owner's people this placement was, this round:
    the Nth person placed pays [1, 1, 2, 2, 3][N-1] wood.

TIMING: the text says "each time AFTER you use" (an explicit "after" exception
to the default "each time you use" = before ruling), so the hook is on
`after_action_space`, NOT `before_action_space`. Under the deferred after-flip
(user ruling 60, 2026-07-14: "after you [do X]" fires after X's FULL effect,
pushed frames included) the wood arrives only once the market's whole effect —
including the animal accommodation frontier the market pushes — has resolved.

The three animal accumulation spaces are NON-ATOMIC and self-hosting:
`_initiate_sheep_market` / `_initiate_pig_market` / `_initiate_cattle_market`
(resolution.py) always push their PendingSheepMarket / PendingPigMarket /
PendingCattleMarket host frame, so there is NO `register_action_space_hook` —
eligibility just filters the host frame's `space_id`.

"With your Nth person" is the ACTING person's ordinal, read via
helpers.acting_placement_number exactly as Catcher does it (the standing-worker
ledger's number at the market — ruling 79): the just-minted number at an
ordinary placement, the moved worker's PRESERVED number at a relocated use
(Straw Hat's end-of-work move onto a market — ruling 79 item 4: a relocation
counts as using the space with that person). The old derived expression
`(people_total − newborns) − people_home` is retired with the rest of its
family.

The grant is choiceless income with no downside, so it is a mandatory
automatic effect (`register_auto`), not a declinable trigger. It fires only on
the OWNER's own use ("you use" — no `any_player`).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import acting_placement_number
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "fir_cutter"

# The three animal accumulation spaces. All non-atomic and self-hosting, so no
# register_action_space_hook (see module docstring).
ANIMAL_MARKETS = frozenset({"sheep_market", "pig_market", "cattle_market"})

# Nth person placed this round -> wood granted after the market use.
WOOD_BY_PERSON = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}


def _grant_on_play(state: GameState, idx: int) -> GameState:
    """One-time +1 food when the card is played."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _wood_amount(state: GameState, idx: int) -> int:
    """Wood owed for this use: keyed to the ACTING person's 1-based ordinal
    ("with your Nth person" — helpers.acting_placement_number, the standing-
    worker ledger's number at the market). The just-minted number at an ordinary
    placement; the moved worker's PRESERVED number at a relocated use (Straw
    Hat's end-of-work move onto a market — ruling 79 item 4)."""
    n_placed = acting_placement_number(state, idx)
    return WOOD_BY_PERSON.get(n_placed, 0)


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at an after_action_space host frame; read the space uniformly
    # via the host frame's `space_id`.
    if state.pending_stack[-1].space_id not in ANIMAL_MARKETS:
        return False
    return _wood_amount(state, idx) > 0


def _grant_wood(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=_wood_amount(state, idx)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _grant_on_play)                  # +1 food on play
register_auto("after_action_space", CARD_ID, _eligible, _grant_wood)
# NO register_action_space_hook: the three markets are non-atomic + self-hosting.
