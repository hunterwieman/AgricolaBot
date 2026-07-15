"""Farmyard Manure (minor improvement, A43; Artifex Expansion; Food Provider).

Card text (verbatim): "Each time you build 1 or more stables in one turn, you place
1 food on each of the next 3 round spaces. At the start of these rounds, you get the
food."
Clarification: "Stables built off-turn, e.g. with Stable Planner A089 or Groom
B089, do not trigger this card."
Cost: none (free). Prerequisite: 1 Animal. VPs: none. Not passing.

The Food-Provider twin of Stable Tree A74: identical mechanism, scheduling 1 FOOD
(not wood) onto each of the next 3 round spaces (R+1..R+3 of `future_resources`)
each time the owner builds >= 1 stable on their own turn.

- Stable BUILD trigger — "each time you build 1 or more stables in one turn" is a
  per-ACTION, mandatory, choice-free effect (Build Stables is one action;
  CARD_AUTHORING_GUIDE.md §2), so it is an `after_build_stables` AUTOMATIC effect
  fired once at the action's after-flip (num_built >= 1 is guaranteed by Proceed).
- THE OFF-TURN GATE (load-bearing — stable_planner.py's "OFF-TURN NOTE"): the
  clarification excludes off-turn Stable Planner / Groom builds, which run in the
  PREPARATION phase (the round_space_collection window). Eligibility gates on
  `state.phase == Phase.WORK`, so only the owner's own work-phase stable builds
  qualify.
- Prerequisite "1 Animal" is a HAVE-check (never spent): the player must hold at
  least one animal (sheep + boar + cattle >= 1) at play time — a custom `prereq`
  predicate, since it is not an occupation-count bound.

Cost is None (free) -> `cost=Cost()` (the register_minor default).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import Phase
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "farmyard_manure"


def _prereq(state: GameState, idx: int) -> bool:
    """"1 Animal": hold at least one animal (any kind) — a have-check, not a cost."""
    a = state.players[idx].animals
    return a.sheep + a.boar + a.cattle >= 1


def _eligible(state: GameState, idx: int) -> bool:
    # On-turn only (see Stable Tree): off-turn preparation builds run in the
    # PREPARATION phase and must not trigger this card.
    return state.phase == Phase.WORK


def _apply(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(food=1))


register_minor(CARD_ID, prereq=_prereq)
register_auto("after_build_stables", CARD_ID, _eligible, _apply)
