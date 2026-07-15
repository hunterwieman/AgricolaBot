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

"Which person am I placing this round?" is derived without new state, exactly
as Catcher does it: a round starts with every worker home
(`people_home == people_total`), each placement decrements `people_home` by
one, and by the after window `people_home` has already been decremented for the
placement now resolving — so `(people_total − newborns) − people_home` is the
1-based ordinal of THIS placement among the owner's workers this round. The
`− newborns` term is load-bearing: a same-round Wish-for-Children birth bumps
`people_total` (and `newborns`) without consuming a `people_home` worker (the
newborn is parked on the wish space until next round's preparation), so
`people_total − people_home` alone would over-count by 1 per same-round birth;
subtracting `newborns` cancels exactly those slots. (`newborns` is cleared at
each round start, so it only ever reflects THIS round's births.)

The grant is choiceless income with no downside, so it is a mandatory
automatic effect (`register_auto`), not a declinable trigger. It fires only on
the OWNER's own use ("you use" — no `any_player`).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
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
    """Wood owed for this placement: keyed to the 1-based ordinal of the worker
    the owner placed this round (already-decremented `people_home`; same-round
    newborns subtracted — see the module docstring)."""
    p = state.players[idx]
    n_placed = (p.people_total - p.newborns) - p.people_home
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
