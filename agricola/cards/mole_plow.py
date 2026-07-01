"""Mole Plow (minor improvement, C20; Corbarius Expansion; cost 3 wood + 1 food;
prereq "Play in Round 9 or Later").

Card text: "Each time you use the 'Farmland' or 'Cultivation' action space, you can plow
1 additional field."

NOT a pay-food card: the granted plow is FREE — the only food is in the PLAY cost (3
wood + 1 food), which the central minor-play path already handles (liquidation-payable).
So this is the Assistant Tiller template (an optional trigger that pushes a free
PendingPlow), filtered to Farmland or Cultivation, with no food in the grant.

"Each time you use [space]" fires in the BEFORE phase (the Trigger-Timing ruling,
CARD_AUTHORING_GUIDE.md §2). A grant is the player's choice → an OPTIONAL trigger
(register, not register_auto). Eligibility gates on `_can_plow_twice` and the granted plow
sets `must_preserve_base=True` (cells restricted to the non-stranding `safe_plow_cells`) so
firing it never strands the base plow — on BOTH Farmland and Cultivation (loss-less; see
_eligible). Once-per-use via the host's `triggers_resolved`. Both Farmland and Cultivation
are non-atomic (always hosted), so no `register_action_space_hook` is needed.

The "Play in Round 9 or Later" prerequisite is a custom `prereq` predicate on
`state.round_number >= 9` (a HAVE/when-check on the round, not a cost). See
PAY_FOOD_PLOW_CARDS.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow_twice
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "mole_plow"
SPACES = frozenset({"farmland", "cultivation"})


def _prereq(state: GameState, idx: int) -> bool:
    """"Play in Round 9 or Later" — a when-check on the current round number."""
    return state.round_number >= 9


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    sid = state.pending_stack[-1].space_id
    if CARD_ID in triggers_resolved or sid not in SPACES:
        return False
    # The grant must leave the base plow legal so it never strands it — `_can_plow_twice`
    # and `must_preserve_base=True` on BOTH spaces. On Farmland the base plow is mandatory;
    # on Cultivation it is declinable (you may sow), but spending a LIMITED granted plow on a
    # cell the FREE base plow could take is strictly dominated, and no card rewards declining
    # the base PLOW (Lazy Sowman A94 rewards declining the SOW, which this never constrains),
    # so the same restriction is loss-less on Cultivation too. See CARD_AUTHORING_GUIDE.md.
    return _can_plow_twice(state.players[idx])


def _apply(state: GameState, idx: int) -> GameState:
    # Restrict the granted plow's cells (safe_plow_cells) so the base plow stays legal — on
    # both Farmland and Cultivation (loss-less; see _eligible).
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
                                   must_preserve_base=True))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=3, food=1)),
    prereq=_prereq,
)
register("before_action_space", CARD_ID, _eligible, _apply)
