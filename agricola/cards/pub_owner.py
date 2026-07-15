"""Pub Owner (occupation, B160; Bubulcus Expansion; players 4+; Crop Provider).

Card text (verbatim): "Immediately, when you play this card, and at the end of each
work phase, in which the "Forest", "Clay Pit", and "Reed Bank" accumulation spaces
are all occupied, you get 1 grain."
No clarifications / errata printed.

READING (grammatical, not a chosen convenience). The sentence has ONE reward
clause ("you get 1 grain") governed by two timing conditions joined by "and":

  (1) "Immediately, when you play this card"  — the on-play instant, and
  (2) "at the end of each work phase, in which the ... spaces are all occupied".

The restrictive relative clause "in which [the three spaces] are all occupied"
can only take a noun antecedent, and the only noun it can bind to is "each work
phase" — "when you play this card" offers no antecedent for "in which". So the
occupancy condition modifies ONLY the end-of-work timing; the on-play grant is
unconditional (the ordinary on-play "immediately", as in Credit / Winter
Caretaker). Two effects:

- **On play** — a mandatory, choice-free +1 grain (`on_play`), unconditional.

- **End of each work phase** — the round-end ladder's `end_of_work` rung
  (position 0 — still DURING the work phase, run once every worker is placed;
  the same rung Master Renovator uses, user ruling 2026-07-14). At `end_of_work`
  the board is still fully placed (the return-home `__reset__` is a later ladder
  step), so the occupancy of Forest / Clay Pit / Reed Bank is read directly off
  their worker tuples. A space is occupied when it holds >= 1 worker of any
  player (`sum(get_space(board, id).workers) > 0`). MANDATORY and choice-free
  (+1 grain when all three are occupied, nothing otherwise) → an automatic effect
  (`register_auto`). Unconditioned on round number: it fires at the end of every
  work phase, harvest rounds included (the round end precedes the harvest).

Grain is a supply good with no capacity, so both grants are plain resource adds.
Played via Lessons; the recurring registry is empty in the Family game, so it
stays byte-identical and the C++ gates are untouched. See credit.py (on-play +
round-end auto) and master_renovator.py (the `end_of_work` rung).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "pub_owner"

# The three accumulation spaces whose joint occupancy gates the end-of-work grain.
_SPACES = ("forest", "clay_pit", "reed_bank")


def _grant_grain(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _on_play(state: GameState, idx: int) -> GameState:
    """"Immediately, when you play this card, ... you get 1 grain." Unconditional
    (the occupancy condition binds only to the end-of-work timing — see docstring)."""
    return _grant_grain(state, idx)


def _eligible(state: GameState, idx: int) -> bool:
    """"...each work phase in which the Forest, Clay Pit, and Reed Bank accumulation
    spaces are all occupied": every one of the three holds >= 1 worker. Read at
    `end_of_work`, where the board is still fully placed."""
    return all(sum(get_space(state.board, s).workers) > 0 for s in _SPACES)


def _apply(state: GameState, idx: int) -> GameState:
    """+1 grain at the end of a work phase in which all three spaces are occupied."""
    return _grant_grain(state, idx)


register_occupation(CARD_ID, _on_play)
register_auto("end_of_work", CARD_ID, _eligible, _apply)
