"""Stable Tree (minor improvement, A74; Artifex Expansion; Building Resource
Provider).

Card text (verbatim): "Each time you build 1 or more stables on your turn, place 1
wood on each of the next 3 round spaces. At the start of these rounds, you get the
wood."
Clarification: "Stables built off-turn, e.g. with Stable Planner A089 or Groom
B089, do not trigger this card."
Cost: 1 Wood. Prerequisite: none. VPs: none. Not passing.

Two mechanisms compose:
- A stable BUILD trigger — "each time you build 1 or more stables" is a per-ACTION
  effect (Build Stables is one action; CARD_AUTHORING_GUIDE.md §2 — no per-piece
  event exists). It is mandatory and choice-free (schedule wood, no decision), so
  it is an `after_build_stables` AUTOMATIC effect (register_auto), fired once at the
  action's after-flip (the `PendingBuildStables` host is guaranteed `num_built >= 1`
  there, since Proceed only flips after at least one stable is committed — so "1 or
  more stables" is satisfied structurally). It reads nothing the build produced, so
  before/after is a pure round-space schedule either way; after is chosen only for
  the OFF-TURN gate below (a before-phase auto would fire at the push, but the phase
  check is identical). Own-action only (`any_player=False`, the register_auto
  default): the auto fires for the acting/building player, who is also the owner.
- Category 8 (deferred goods): the effect schedules 1 wood onto each of the next 3
  round spaces (R+1..R+3 of `future_resources`), collected at each round's start.

THE OFF-TURN GATE (load-bearing — see stable_planner.py's "OFF-TURN NOTE"): the
clarification says stables built off-turn (Stable Planner A089 / Groom B089) must
NOT trigger this card. Those cards build a free stable during the preparation
ladder's `round_space_collection` window — a `PendingBuildStables` pushed while
`state.phase == PREPARATION`, at the stack base. So the eligibility gates on
`state.phase == Phase.WORK`: an on-turn build (Farm Expansion, or a work-phase card
grant during the owner's placement) fires while phase is WORK; an off-turn
preparation build fires while phase is PREPARATION and is correctly skipped. This
is exactly the "gate on the owner's own WORK-phase build" the sibling clarification
demands.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import Phase
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stable_tree"


def _eligible(state: GameState, idx: int) -> bool:
    # On-turn only: a real worker-placement build happens in the WORK phase; the
    # off-turn Stable Planner / Groom builds happen in the PREPARATION phase (the
    # round_space_collection window) and must NOT trigger this card.
    return state.phase == Phase.WORK


def _apply(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(wood=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("after_build_stables", CARD_ID, _eligible, _apply)
