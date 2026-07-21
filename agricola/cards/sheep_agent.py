"""Sheep Agent (occupation, D86; Dulcinaria Expansion; Farm Planner; players 1+).

Card text (verbatim): "You can keep 1 sheep on each occupation card in front of
you (including this one), unless it is already able to hold animals."

Classification: a pure STANDING capacity card — no on-play effect. It grants one
sheep-only slot per qualifying PLAYED occupation, realized through the per-species
typed-slot registry (`register_typed_slots`, capacity_mods.py) and the greedy
strip at the ownership-aware accommodation entry points (`helpers.accommodates`,
`pareto_frontier`, `breeding_frontier`) — the same machinery Dolly's Mother uses.
A sheep parked on a sheep-only slot never constrains the other animals, so the
owner's accommodation problem equals the standard one with the parked sheep
removed and added back to every answer (exact by dominance, per type).

The qualifying set (user ruling 2026-07-21 — the typed-slot fold + holder-
predicate direction):
- Only OCCUPATION cards count — the text says "each occupation card". Minors are
  irrelevant (`_slots` reads `player_state.occupations` only), and cards still in
  hand do not count ("in front of you" = played).
- An occupation qualifies iff it is NOT "already able to hold animals" — i.e. not
  a registered animal holder (`animal_holder_card_ids()`: any card that registers
  a typed slot, a pasture-like capacity bin, or a flexible slot). Registration-
  time identity is the right predicate here: only implemented cards can ever be in
  play, so `animal_holder_card_ids()` is exactly the "already able to hold animals"
  set among cards that can appear. (A house-capacity card such as Animal Tamer is
  deliberately NOT a holder — it makes the HOUSE hold more, not the card itself, so
  it does not register into any of those three registries and correctly still earns
  a Sheep Agent slot.)
- EXCEPT Sheep Agent itself: it registers as a typed-slot holder, so the predicate
  above would exclude it — but the printed "(including this one)" resolves that
  self-reference, so its own slot always counts. `_slots` only runs when Sheep
  Agent is owned (the registry is ownership-gated), so `CARD_ID in occupations`
  always holds there.

Monotonicity: occupations only accumulate over a game (never removed), so the
slot count is non-decreasing — there is no eviction path to model, and no card can
ever shrink an owner's already-housed sheep.

Family fast path: the typed-slot registry is empty for the Family game, so
`typed_slot_counts` returns `Animals()` and every accommodation formula reduces to
its pre-card text (C++ gates untouched — card-only state).
"""
from __future__ import annotations

from agricola.cards.capacity_mods import (
    animal_holder_card_ids,
    register_typed_slots,
)
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.resources import Animals
from agricola.state import PlayerState

CARD_ID = "sheep_agent"


def _slots(player_state: PlayerState) -> Animals:
    """One sheep slot per qualifying PLAYED occupation (see module docstring):
    every occupation not already able to hold animals, plus Sheep Agent itself
    ("(including this one)")."""
    holders = animal_holder_card_ids()
    n = sum(1 for occ in player_state.occupations
            if occ == CARD_ID or occ not in holders)
    return Animals(sheep=n)


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive capacity)
register_typed_slots(CARD_ID, _slots)
