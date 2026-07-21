"""Forest Plow (minor improvement, B17; Bubulcus Expansion; players -).

Card text: "Each time you use a wood accumulation space, you can pay 2 wood to plow
1 field. Place the paid wood on the accumulation space (for the next visitor)."
Cost: 1 Wood. No prerequisite; kept (not traveling); no VP. Category: Farm Planner.

Clarification (verbatim): "You may take less than 2 wood from the space and still use
this card's effect."

USER RULING (2026-07-20): the trigger fires AFTER the take — an explicit per-card
ruling overriding the default "each time you use [space]" = the before-window.
Rationale recorded with the ruling: the deposit is "for the next visitor", and firing
before the sweep would let the player's own take scoop the deposited wood back; the
clarification means the effect is not conditioned on how much wood the space yielded —
the 2 wood is paid from the player's supply, whatever its origin, including the
just-taken wood.

TIMING / KIND. Per the ruling above, an OPTIONAL trigger ("you can") in the AFTER
phase of the wood-space host, surfaced as a ``FireTrigger`` the player may take or
decline; the host's after-phase ``Stop`` is the decline. "A wood accumulation space"
is the ``WOOD_ACCUMULATION_SPACES`` frozenset in ``agricola/constants.py`` (derived
from the rate dicts — the same set Nail Basket keys on); the hook is registered over
that WHOLE set for 4-player forward compatibility, and at 2 players only "forest" is
on the board (a hook for a space id not on the board is inert). Wood accumulation
spaces are ATOMIC, so ``register_action_space_hook`` is REQUIRED to give them a
``PendingActionSpace`` host for the trigger to attach to. Owner-gated ("you use" —
the host frame's ``player_idx`` must be the owner); once per use via the host frame's
``triggers_resolved``.

ELIGIBILITY — offered only when the whole action is doable, so the fire never
dead-ends: the host frame's ``space_id`` is a wood accumulation space, the frame is
the owner's own use, the owner holds >= 2 wood (post-take supply — the just-taken
wood counts, per the clarification), and a plow is legal right now (``_can_plow``,
the same doability gate the other plow granters use).

EFFECT (firing the trigger = opting in to the whole thing; the fire was the decline
moment, so the paid-for plow is committed once fired):
  1. Pay 2 wood from the owner's supply.
  2. Place the paid wood on the space just used — add ``Resources(wood=2)`` to the
     space's ``accumulated`` vector. The NEXT visitor sweeps the WHOLE accumulated
     vector (refill included) — that is "for the next visitor".
  3. Plow 1 field: push the reusable ``PendingPlow`` primitive with this card's
     provenance.

Card-game only (ownership-gated registries; no new engine state), so the Family trace
and the C++ differential gates are untouched. See CARD_ENGINE_IMPLEMENTATION.md §2 and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "forest_plow"
FRAME_ID = "card:forest_plow"   # the granted plow frame's initiated_by_id
_WOOD_COST = 2


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the trigger only when the whole effect is doable (never a dead-end)."""
    if CARD_ID in triggers_resolved:                    # once per use
        return False
    top = state.pending_stack[-1]
    if top.space_id not in WOOD_ACCUMULATION_SPACES:
        return False
    if top.player_idx != idx:                           # own use only ("you use")
        return False
    p = state.players[idx]
    return p.resources.wood >= _WOOD_COST and _can_plow(p)


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    # 1) Pay 2 wood from the owner's supply (post-take, so the just-taken wood may
    #    fund it — the clarification's "take less than 2 wood and still use").
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(wood=_WOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    # 2) Place the paid wood on the space just used (for the next visitor). The next
    #    user sweeps the WHOLE accumulated Resources vector, this deposit included.
    sp = get_space(state.board, space_id)
    state = fast_replace(
        state, board=with_space(
            state.board, space_id,
            fast_replace(sp, accumulated=sp.accumulated + Resources(wood=_WOOD_COST))))
    # 3) Plow 1 field — the reusable primitive with this card's provenance. The fire
    #    was the decline moment, so the paid-for plow is committed.
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=FRAME_ID))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
