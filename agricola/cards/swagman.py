"""Swagman (occupation, A129; Artifex Expansion; players 3+).

Card text (verbatim): "Immediately after each time you use the 'Farm Expansion'
or 'Grain Seeds' action space, you can use the respective other space with the
same person (even if it is occupied)."
Clarification: "The person ends on the second action space used."
Errata: "The 'jump' to a second action space may only be done once per turn."
Category: Actions Booster. No printed VPs. No cost beyond the occupation play.

GOVERNING RULING (user, 2026-07-26 — ruling 81):

1. The jump is an OPTIONAL trigger in the SOURCE space's ``after_action_space``
   window (so it can be taken before other after-window triggers). Firing it
   moves the acting worker's board marker source → destination and runs the
   destination's FULL action; the destination's frames stack above the source's
   after-window host, resolve completely, and the walk returns to the source's
   after-window for its remaining triggers. All of that lives in the shared jump
   helper ``worker_moves.relocate_and_use`` — this module's apply fn only
   latches the errata's once-per-turn budget and names source/destination.
2. Under the placement-ordinal ruling (79), the jump mints NO placement number:
   ``placements_this_round`` is untouched (``relocate_and_use`` is not a
   placement chokepoint — the worker keeps the number of the placement that
   started the turn).
3. The vacated source re-opens (occupancy is solely worker presence — the
   ``_move_board_worker`` semantics).

MECHANICS. An optional trigger on ``after_action_space``, live only when the
top host frame is the OWNER's own use of one of the named pair
(``farm_expansion`` — the non-atomic ``PendingFarmExpansion`` host — or
``grain_seeds``, an atomic space hosted via this card's
``register_action_space_hook`` entry). Eligibility conjuncts, each load-bearing:

- Own use of a pair member: the host frame's ``space_id`` is in the pair and
  its ``player_idx`` is the owner (belt-and-braces — the enumerator already
  routes ownership through the host's player).
- Once per TURN (the errata): the ``used_this_turn`` latch, stamped at the
  fire and cleared by the engine at every turn boundary
  (``engine._advance_current_player``). This is what stops the infinite chain:
  after a Farm Expansion → Grain Seeds jump, the destination's own after-window
  opens and would otherwise offer the jump straight back.
- "Even if it is occupied": destination occupancy is deliberately NOT checked —
  the jump pierces it (worker markers stack on the space's ``workers`` tuple).
- The destination's own action must be legal right now (never a dead-end fire):
  the SUBSTANTIVE half of the destination's placement predicate — the same
  helpers ``legality._legal_farm_expansion`` composes — minus its
  ``_is_available`` occupancy gate, which this card pierces (both spaces are
  permanents, revealed from setup, so availability held nothing else). For
  ``grain_seeds`` ("take 1 grain") that substantive predicate is trivially
  true; for ``farm_expansion`` it is a buildable room or a buildable 2-wood
  stable (``_can_build_room`` / ``_can_build_stable`` — reused, not
  reimplemented, so cost-modifier cards keep working).

Declining is the host's after-phase Stop (no SkipTrigger). Players 3+, so the
card is registered but never dealt in the 2-player game — tests inject it (the
Lodger precedent). No on-play effect. Card-game only (ownership-gated
registries, no new engine state): the Family trace and the C++ differential
gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.cards.worker_moves import relocate_and_use
from agricola.legality import _can_build_room, _can_build_stable
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "swagman"

# "the respective other space": source -> destination, both directions.
_OTHER = {"farm_expansion": "grain_seeds", "grain_seeds": "farm_expansion"}


def _destination_action_legal(state: GameState, idx: int, dest: str) -> bool:
    """Can the destination's own action actually be taken right now?

    The substantive half of the destination's placement predicate, occupancy
    (``_is_available``) deliberately excluded — the card pierces it, and both
    spaces are always-revealed permanents so availability carried nothing else.
    """
    if dest == "grain_seeds":
        return True                      # "take 1 grain" is always resolvable
    # farm_expansion: exactly _legal_farm_expansion's substantive body — a
    # buildable room, or a buildable stable at the space's 2-wood base cost.
    p = state.players[idx]
    return _can_build_room(state, p) or _can_build_stable(state, p, Resources(wood=2))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    top = state.pending_stack[-1]
    if getattr(top, "player_idx", None) != idx:      # own use only (belt-and-braces)
        return False
    src = getattr(top, "space_id", None)
    if src not in _OTHER:                            # a pair member's host
        return False
    if CARD_ID in state.players[idx].used_this_turn:  # errata: once per turn
        return False
    return _destination_action_legal(state, idx, _OTHER[src])


def _apply(state: GameState, idx: int) -> GameState:
    """Fire the jump: latch the errata's once-per-turn budget, then hand the
    whole move-and-use to the shared helper (ruling 81 item 1) — marker moved
    source → destination, relocated hooks fired, the destination's full action
    run. No placement number is minted (ruling 79 — the helper never touches
    ``placements_this_round``), and the vacated source re-opens by worker
    absence alone."""
    src = state.pending_stack[-1].space_id
    p = state.players[idx]
    p = fast_replace(p, used_this_turn=p.used_this_turn | {CARD_ID})
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    return relocate_and_use(state, idx, src, _OTHER[src])


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# The optional jump trigger in the source's after-window (ruling 81 item 1).
register("after_action_space", CARD_ID, _eligible, _apply)
# grain_seeds is ATOMIC — hook it so an owner's use is hosted (before/after
# windows exist). farm_expansion needs no hook: it is non-atomic, always hosted
# by PendingFarmExpansion.
register_action_space_hook(CARD_ID, {"grain_seeds"})
