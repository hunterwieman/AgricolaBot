"""Wheel Plow (minor improvement, A18; Artifex Expansion; cost 2 wood, prereq 2
occupations).

Card text: "Once this game, when you use the 'Farmland' or 'Cultivation' action space with
the first person you place in a round, you can plow 2 additional fields."

A once-per-GAME grant of up to 2 extra plows, gated on the placement being the player's
FIRST this round. Mirrors Plow Hero's first-placement gate (`_is_first_placement_this_round`)
and Swing/Turnwrest Plow's multi-shot grant, but with two scoping differences:
  - ONCE PER GAME, not a per-use refresh: a `used` latch in the per-card CardStore (set when
    the grant is taken — i.e. when the trigger fires) is the gate, so the FireTrigger is
    offered at most once across the whole game.
  - exactly 2 additional fields (a `max_plows=2` multi-shot PendingPlow); the player may
    still plow fewer (an early Proceed, or a stranding-forced stop after one).

"When you use [space] ... you can" fires the trigger in the BEFORE phase (Trigger-Timing
ruling, CARD_AUTHORING_GUIDE.md §2), before the space's mandatory base plow. The trigger
fires ONCE per use (`triggers_resolved`) and ONCE per game (the CardStore latch); its
apply_fn latches `used` and pushes ONE multi-shot PendingPlow (no multi-fire machinery).

Stranding guard (identical to Turnwrest Plow, same on both spaces): eligibility requires
`_can_plow_twice` and the grant sets `must_preserve_base=True` (each commit restricted to
non-stranding `safe_plow_cells`, re-checked per commit). `_can_plow_twice`, NOT a thrice-check
— each extra plow need only leave the base plow legal. On Farmland the base plow is mandatory;
on Cultivation it is declinable, but the same guard is loss-less there (spending the
once-per-game grant where the FREE base plow could plow the cell is dominated, and no card
rewards declining the base PLOW — Lazy Sowman A94 rewards declining the SOW, untouched here).

"First person you place in a round" is read without new state: the before_action_space
trigger fires after the placing worker has been decremented from `people_home`, so exactly
one worker placed ⟺ `people_home == people_total − 1` (see Plow Hero for the full
derivation, including the newborn/Wish interaction). Both spaces are non-atomic (always
hosted), so no `register_action_space_hook` is needed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow_twice
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wheel_plow"
SPACES = frozenset({"farmland", "cultivation"})
_EXTRA_PLOWS = 2


def _used(state: GameState, idx: int) -> bool:
    return state.players[idx].card_state.get(CARD_ID, False)


def _is_first_placement_this_round(state: GameState, idx: int) -> bool:
    """True iff the placement now being resolved is the player's first this round (the
    before_action_space trigger fires after the placing worker left people_home). See
    Plow Hero for the derivation."""
    p = state.players[idx]
    return p.people_home == p.people_total - 1


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved or _used(state, idx):   # once per use AND once per game
        return False
    sid = state.pending_stack[-1].space_id
    if sid not in SPACES:
        return False
    if not _is_first_placement_this_round(state, idx):       # only with the first worker
        return False
    # The grant must leave the base plow legal (`_can_plow_twice` + must_preserve_base=True) —
    # on BOTH spaces. On Cultivation the base plow is declinable (you may sow), but spending
    # this once-per-game grant where the FREE base plow could plow the same cell is strictly
    # dominated, and no card rewards declining the base PLOW (Lazy Sowman A94 rewards declining
    # the SOW, untouched here), so the same restriction is loss-less there too.
    return _can_plow_twice(state.players[idx])


def _apply(state: GameState, idx: int) -> GameState:
    # Latch the once-per-game use, then push the 2-field multi-shot grant with the cells
    # restricted to the non-stranding safe set (must_preserve_base) on both spaces so the base
    # plow stays legal.
    p = fast_replace(state.players[idx],
                     card_state=state.players[idx].card_state.set(CARD_ID, True))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
        must_preserve_base=True, max_plows=_EXTRA_PLOWS))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=2)
register("before_action_space", CARD_ID, _eligible, _apply)
