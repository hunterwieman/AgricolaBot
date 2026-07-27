"""Steam Machine (minor improvement, C25; Consul Dirigens Expansion).

Card text: "Each work phase, if the last action space you use is an accumulation
space, you can immediately afterward take a 'Bake Bread' action."
Cost: 2 Wood. No prerequisite. VPs: 1. Not passing.

An OPTIONAL `after_action_space` trigger that grants a Bake Bread action, but only
when the placement it fires on is BOTH (a) the player's LAST worker placement of the
work phase and (b) on an accumulation space.

TIMING — `after_action_space`. "Immediately afterward" is the explicit "after you
use" wording (the same exception Carpenter's Axe / Wood Cutter ride), so the grant
fires once the space's own pickup has already resolved — Bake Bread is offered in the
space host's after-phase.

"THE LAST ACTION SPACE YOU USE" — `people_home == 0` + the last-use latch.
`people_home` is decremented at placement (`_apply_worker_placement`) BEFORE the
after-phase fires, so at the after_action_space moment `people_home == 0` means "no
worker at home can place after this one." That is exact for every mechanism routed
through people_home — returned workers (Tea Time), delayed placements, and an
ACCEPTED loaner (helpers.activate_temp_worker puts the meeple in people_home, so the
gate simply waits for the true last placement, which may be the loaner's — and the
bake is then correctly offered there). What people_home cannot see is an optional
future use living OUTSIDE it: an unanswered supply-loaner OFFER (Telegram / Work
Permit, and Delayed Wayfarer's offer, which only arises at the all-players-placed
boundary — later than this fire). Ruled resolution (the Telegram-arc principle):
firing this card COMMITS "this was my last use of the work phase" and implicitly
DECLINES every such offer for the round — `_apply` sets
`PlayerState.last_use_committed`, which `turn_offers.pending_turn_start_offer`
consults at its single chokepoint. Eligibility reads the same latch: once a use has
been committed as last, any later use's "last" claim is false — which is also what
keeps this once-per-phase when a relocation effect creates a second
people_home == 0 use. The consulting parties (each blocks its own contradiction):
Straw Hat's relocation variants (its "get 1 food" branch is unaffected) and Sheep
Inspector's return — the return shares this trigger's after-window, and a returned
home worker MUST be re-placed, which would falsify the commitment; the reverse
order needs nothing (a return first raises people_home, blocking this gate). A
MANDATORY future placement needs no handling: every catalog mechanism of that kind
lives in people_home, which already blocks the fire. ON MARKET MASTER'S BUILD (the
other own-last-placement instant): both cards can fire in the SAME window
(Traveling Players is an accumulation space), so this eligibility's blind latch
read must then be scoped to other-window commitments — the executable flag is
tests/test_last_use_commitment_tripwire.py.

"ACCUMULATION SPACE" — the 9 goods-accumulating spaces, read at eligibility
through the category accessor `helpers.accumulation_spaces(state)` (the one
definition every "accumulation space" wording quantifies over): the 6 ATOMIC
building/food spaces (forest / clay_pit / reed_bank / western_quarry /
eastern_quarry / fishing) + the 3 NON-ATOMIC animal markets (sheep / pig / cattle).
`meeting_place` is excluded: in the card game Meeting Place gives no food and
accumulates nothing (it is become-start-player + an optional minor), so it is not
functioning as an accumulation space and must not satisfy "the last action space you
use is an accumulation space" — the accessor's CARDS-mode set already excludes it.

HOSTING — `register_action_space_hook` is needed ONLY for the 6 ATOMIC accumulation
spaces, so that placing on them pushes a `PendingActionSpace` host whose after-phase can
surface this trigger. The 3 markets are non-atomic and self-host their before/after
lifecycle (the `PendingSheepMarket` / `PendingPigMarket` / `PendingCattleMarket` frames
already surface `after_action_space`, verified against Claw Knife / Milk Jug), so they
must NOT be added to the hook — but they ARE matched by the accumulation-space
membership test, so they still grant the Bake Bread.

OPTIONALITY — "you can" → an OPTIONAL `register` (declinable) trigger, not
`register_auto`. The decline path is simply not firing it (the host's Stop pops out
without baking). Eligibility additionally gates on `_can_bake_bread` (a baking
improvement + grain, or a card extension) so the fire is never a dead-end. "Each work
phase" once-per-use is enforced by `CARD_ID not in triggers_resolved` — but the
people_home == 0 gate already restricts firing to the single last placement of the
phase, so it never fires twice in a phase regardless.

VPs: 1 (printed). No on-play effect.
"""
from __future__ import annotations

from agricola.constants import ACCUMULATION_SPACES
from agricola.legality import _can_bake_bread
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.pending import PendingBakeBread, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.resolution import ATOMIC_HANDLERS
from agricola.state import GameState

CARD_ID = "steam_machine"

# Hook registration is import-time and therefore static: of the card-game
# accumulation set (constants.ACCUMULATION_SPACES — the CARDS-mode value of the
# helpers.accumulation_spaces accessor eligibility reads), only the ATOMIC spaces
# need an explicit host hook; the 3 markets self-host. (A 4-player board's extra
# accumulation spaces would register here when its board lands.)
_ACC_ATOMIC = frozenset(s for s in ACCUMULATION_SPACES if s in ATOMIC_HANDLERS)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    from agricola.helpers import accumulation_spaces
    if state.pending_stack[-1].space_id not in accumulation_spaces(state):
        return False
    p = state.players[idx]
    # "the LAST action space you use": this placement emptied the player's hand of
    # workers (people_home decremented at placement, before this after-phase fires).
    if p.people_home != 0:
        return False
    # An earlier use was already committed as the phase's last — this one's "last"
    # claim is false (and this is what keeps the fire once-per-phase when a
    # relocation creates a second people_home == 0 use).
    if p.last_use_committed:
        return False
    # Never grant a dead-end Bake Bread.
    return _can_bake_bread(state, p)


def _apply(state: GameState, idx: int) -> GameState:
    """Commit this use as the phase's last (implicitly declining any outstanding or
    later-arising loaner offer for the round — see the module docstring), then grant
    the optional Bake Bread sub-action (the existing primitive)."""
    p = state.players[idx]
    state = fast_replace(state, players=tuple(
        fast_replace(p, last_use_committed=True) if i == idx else state.players[i]
        for i in range(len(state.players))))
    return push(state, PendingBakeBread(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _ACC_ATOMIC)
