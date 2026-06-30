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

"THE LAST ACTION SPACE YOU USE" — `people_home == 0`. `people_home` is decremented at
placement (`_apply_worker_placement`) BEFORE the after-phase fires, and the engine's
work-phase-complete signal is exactly `all(p.people_home == 0)`. So at the
after_action_space moment, the placing player's `people_home == 0` is precisely "this
was your last placement this work phase." (In the 2-player Family-derived card game,
family size is fixed and no in-scope card grants extra workers, so the mapping is
exact; a future extra-worker card would need to revisit this.)

"ACCUMULATION SPACE" — the 9 goods-accumulating spaces (`_ACCUMULATION_SPACES`): the 6
ATOMIC building/food spaces (forest / clay_pit / reed_bank / western_quarry /
eastern_quarry / fishing) + the 3 NON-ATOMIC animal markets (sheep / pig / cattle).
`meeting_place` is deliberately EXCLUDED: it is in `constants.ACCUMULATION_SPACES`, but
in the card game Meeting Place gives no food and accumulates nothing (it is
become-start-player + an optional minor), so it is not functioning as an accumulation
space and must not satisfy "the last action space you use is an accumulation space."

HOSTING — `register_action_space_hook` is needed ONLY for the 6 ATOMIC accumulation
spaces, so that placing on them pushes a `PendingActionSpace` host whose after-phase can
surface this trigger. The 3 markets are non-atomic and self-host their before/after
lifecycle (the `PendingSheepMarket` / `PendingPigMarket` / `PendingCattleMarket` frames
already surface `after_action_space`, verified against Claw Knife / Milk Jug), so they
must NOT be added to the hook — but they ARE matched by the `_ACCUMULATION_SPACES`
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
from agricola.resources import Cost, Resources
from agricola.resolution import ATOMIC_HANDLERS
from agricola.state import GameState

CARD_ID = "steam_machine"

# The 9 goods-accumulating spaces (drop meeting_place — no goods in the card game).
_ACCUMULATION_SPACES = frozenset(ACCUMULATION_SPACES) - {"meeting_place"}
# Of those, only the ATOMIC ones need an explicit host hook; the 3 markets self-host.
_ACC_ATOMIC = frozenset(s for s in _ACCUMULATION_SPACES if s in ATOMIC_HANDLERS)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in _ACCUMULATION_SPACES:
        return False
    p = state.players[idx]
    # "the LAST action space you use": this placement emptied the player's hand of
    # workers (people_home decremented at placement, before this after-phase fires).
    if p.people_home != 0:
        return False
    # Never grant a dead-end Bake Bread.
    return _can_bake_bread(state, p)


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the optional Bake Bread sub-action (the existing primitive)."""
    return push(state, PendingBakeBread(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _ACC_ATOMIC)
