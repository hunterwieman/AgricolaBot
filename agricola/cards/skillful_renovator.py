"""Skillful Renovator (occupation, C119; Consul Dirigens Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 wood and 1 clay. Each
time after you renovate, you get a number of wood equal to the number of people
you placed that round."
Clarifications: "If you renovate with your 3rd placed person of a round, this card
triggers a payout of 3 wood. Newborns are not placed."

Category: Building Resource Provider. Two mandatory, choice-free clauses → one
on-play effect and one automatic effect (`register_auto`); neither is surfaced to
the agent.

- **on play → +1 wood, +1 clay** (Consultant pattern, one-shot).
- **after you renovate → +wood equal to people placed this round** → `after_renovate`,
  unconditional (the owner gate is applied by `apply_auto_effects`). The renovate
  hook fires once, post-application, matching the Mining Hammer / Roughcaster /
  Maintenance Premium renovate convention.

**Computing "the number of people you placed that round."** A renovate is reached
via a worker placement (House / Farm Redevelopment), and placing a worker
decrements the active player's `people_home` BEFORE the redevelopment frame is
pushed (`resolution.py` `_place_worker`). So at `after_renovate` time the worker
that triggered this renovate is already counted. The per-round placed count is:

    placed = people_total - newborns - people_home

- `people_home` is the workers still at home (not yet placed this round); it is
  reset to `people_total` at end-of-round return-home, so during a round
  `people_total - people_home` is exactly the number placed so far.
- `newborns` must be subtracted: a newborn is in `people_total` (and not cleared
  until the next round's preparation) but is "not placed" (clarification), so it
  would otherwise inflate the count.

Worked check (clarification): renovating with your 3rd placed person of a round
pays 3 wood. With 3 people placed (including this one) and no newborns,
`people_total - newborns - people_home = 3 - 0 - 0 = 3` → +3 wood. ✓

Played via Lessons (occupation). Card-only behavior (no CardStore; the Family game
is byte-identical and the C++ gates are untouched). Template: consultant.py
(on-play goods) + maintenance_premium.py / roughcaster.py (after_renovate auto).
See CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "skillful_renovator"


def _on_play(state: GameState, idx: int) -> GameState:
    """Immediately get 1 wood and 1 clay."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1, clay=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# --- after each renovate: +wood equal to people placed this round ---

def _eligible_renovate(state: GameState, idx: int) -> bool:
    # Every renovate pays out (owner gate applied by apply_auto_effects). The
    # payout can be 0 wood only if zero people are placed, which never happens at a
    # renovate (a renovate is reached by placing a worker), so this is always True.
    return True


def _apply_renovate(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    placed = p.people_total - p.newborns - p.people_home
    p = fast_replace(p, resources=p.resources + Resources(wood=placed))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _on_play)
register_auto("after_renovate", CARD_ID, _eligible_renovate, _apply_renovate)
