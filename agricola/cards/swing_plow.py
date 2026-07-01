"""Swing Plow (minor improvement, C19; Consul Dirigens Expansion; cost 3 wood,
prereq 3 occupations).

Card text: "Place 4 field tiles on this card. Each time you use the 'Farmland' action
space, you can also plow up to 2 fields from this card."

Two limits, both enforced here:
  - a LIFETIME pool of 4 field tiles, tracked as a uses-left counter in the per-card
    CardStore (starts at 4, decremented by the number of fields actually plowed, like
    Moldboard Plow's uses-left);
  - a PER-USE cap of 2 (you may plow "up to 2 fields" each Farmland use), enforced by the
    granted plow being a MULTI-SHOT PendingPlow with `max_plows = min(2, tiles_left)`.

Mechanically the Moldboard Plow template extended to a multi-shot grant. "Each time you
use [space]" fires the trigger in the BEFORE phase (the Trigger-Timing ruling,
CARD_AUTHORING_GUIDE.md §2), before Farmland's own mandatory base plow. The trigger fires
ONCE per use (the standard `card_id not in triggers_resolved` gate); its apply_fn pushes a
single multi-shot PendingPlow that commits up to `min(2, tiles_left)` fields — one
CommitPlow each, with a Proceed to finish early — so no multi-fire-trigger machinery is
involved. The lifetime tile counter is debited by the actual number of fields plowed
(`num_plowed`) via an `after_plow` automatic effect that fires when the grant frame flips
to its after-phase (so an early Proceed or a stranding-forced stop only spends what was
really used).

Farmland is an enforce-first DELEGATING host whose base plow is mandatory and
non-declinable, so this granted plow must not strand it: eligibility requires `_can_plow_twice`
(the grant must leave the base plow a legal target) and the granted plow sets
`must_preserve_base=True`, restricting EACH of its (up to two) commits to the non-stranding
`safe_plow_cells` — re-checked per commit against the board the previous one produced. The
guard is `_can_plow_twice`, NOT a thrice-check: the extra plows are optional, so each granted
plow need only leave the mandatory base plow legal; requiring room for both grants + the base
at once would wrongly refuse the grant when only 2 plows total fit. Farmland is non-atomic
(always hosted), so no `register_action_space_hook` is needed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_auto
from agricola.legality import _can_plow_twice
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "swing_plow"
SPACES = frozenset({"farmland"})
_INITIAL_TILES = 4
_PER_USE_CAP = 2


def _tiles_left(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, _INITIAL_TILES)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Once per use (triggers_resolved); Farmland only; tiles remain; and — because this
    # before-trigger precedes the mandatory base plow on the delegating Farmland host — a
    # second sequential plow must exist so the grant cannot strand it (_can_plow_twice).
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _tiles_left(state, idx) > 0
            and _can_plow_twice(state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    # Push ONE multi-shot granted plow capped at min(2, tiles_left). The per-commit cell
    # restriction (must_preserve_base) keeps Farmland's mandatory base plow legal. The
    # lifetime tile debit happens in _debit_tiles when the grant finishes (after_plow).
    tiles = _tiles_left(state, idx)
    return push(state, PendingPlow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
        must_preserve_base=True,                 # Farmland's base plow is mandatory
        max_plows=min(_PER_USE_CAP, tiles)))


def _is_our_finished_grant(state: GameState, idx: int) -> bool:
    """after_plow fires for EVERY plow's after-flip (base plow, other grants, this one);
    debit only when the just-finished frame is THIS card's grant."""
    return (bool(state.pending_stack)
            and state.pending_stack[-1].initiated_by_id == f"card:{CARD_ID}")


def _debit_tiles(state: GameState, idx: int) -> GameState:
    """Spend `num_plowed` lifetime tiles (the fields actually plowed by this grant)."""
    top = state.pending_stack[-1]
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(
        CARD_ID, _tiles_left(state, idx) - top.num_plowed))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3)), min_occupations=3)
register("before_action_space", CARD_ID, _eligible, _apply)
register_auto("after_plow", CARD_ID, _is_our_finished_grant, _debit_tiles)
