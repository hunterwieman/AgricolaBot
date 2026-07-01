"""Turnwrest Plow (minor improvement, D20; Consul Dirigens Expansion; cost 3 wood,
prereq 2 occupations).

Card text: "Place 2 field tiles on this card. Each time you use the 'Farmland' or
'Cultivation' action space, you can also plow up to 2 fields from this card."

Swing Plow's shape with TWO differences: a 2-tile lifetime pool (not 4) and the grant also
fires on Cultivation (not Farmland only). Two limits enforced identically to Swing Plow:
  - LIFETIME pool of 2 field tiles in the per-card CardStore (debited by fields actually
    plowed via an `after_plow` automatic effect);
  - PER-USE cap of 2 via a MULTI-SHOT PendingPlow with `max_plows = min(2, tiles_left)`.

"Each time you use [space]" fires the trigger in the BEFORE phase (Trigger-Timing ruling),
ONCE per use (`card_id not in triggers_resolved`); its apply_fn pushes ONE multi-shot
PendingPlow (no multi-fire machinery).

Stranding guard, by space:
Both spaces use the SAME guard — eligibility `_can_plow_twice` and `must_preserve_base=True`
(each commit restricted to non-stranding `safe_plow_cells`, re-checked per commit). The guard
is `_can_plow_twice`, NOT a thrice-check: each extra plow need only leave the base plow legal
(the extra plows are optional). On Farmland the base plow is mandatory. On Cultivation it is
declinable (you may sow), but spending a LIMITED card-tile plow where the FREE base plow could
plow the same cell is strictly dominated, and no card rewards declining the base PLOW (Lazy
Sowman A94 rewards declining the SOW, which this restriction never constrains), so the same
guard is loss-less there — see CARD_AUTHORING_GUIDE.md.

Both spaces are non-atomic (always hosted), so no `register_action_space_hook` is needed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_auto
from agricola.legality import _can_plow_twice
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "turnwrest_plow"
SPACES = frozenset({"farmland", "cultivation"})
_INITIAL_TILES = 2
_PER_USE_CAP = 2


def _tiles_left(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, _INITIAL_TILES)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    sid = state.pending_stack[-1].space_id
    if sid not in SPACES or _tiles_left(state, idx) <= 0:
        return False
    # The grant must leave the base plow legal (`_can_plow_twice` + must_preserve_base=True) —
    # on BOTH spaces. On Cultivation the base plow is declinable (you may sow), but spending a
    # LIMITED card-tile plow where the FREE base plow could plow the same cell is strictly
    # dominated, and no card rewards declining the base PLOW (Lazy Sowman A94 rewards declining
    # the SOW, untouched here), so the same restriction is loss-less there too.
    return _can_plow_twice(state.players[idx])


def _apply(state: GameState, idx: int) -> GameState:
    # Push ONE multi-shot granted plow capped at min(2, tiles_left), with the cells restricted
    # to the non-stranding safe set (must_preserve_base) on both spaces so the base plow stays
    # legal. The lifetime tile debit happens in _debit_tiles (after_plow).
    tiles = _tiles_left(state, idx)
    return push(state, PendingPlow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
        must_preserve_base=True, max_plows=min(_PER_USE_CAP, tiles)))


def _is_our_finished_grant(state: GameState, idx: int) -> bool:
    """after_plow fires for every plow's after-flip; debit only when the just-finished
    frame is THIS card's grant."""
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


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3)), min_occupations=2)
register("before_action_space", CARD_ID, _eligible, _apply)
register_auto("after_plow", CARD_ID, _is_our_finished_grant, _debit_tiles)
