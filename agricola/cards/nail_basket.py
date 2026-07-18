"""Nail Basket (minor improvement, E15; Ephipparius Expansion; players -).

Card text: "Each time after you use a wood accumulation space, you can place 1 stone
from your supply on that space (for the next visitor) to take a "Build Fences" action."
Cost: 1 Reed. No prerequisite; kept (not traveling); 1 VP.

USER RULING (2026-07-17): "a wood accumulation space" is the ``WOOD_ACCUMULATION_SPACES``
frozenset in ``agricola/constants.py`` — the accumulation spaces whose per-round rate
includes wood (DERIVED from the rate dicts, so it extends automatically once the
3-4-player wood spaces are added). The action-space hook is registered over that WHOLE
set for 4-player forward compatibility; at 2 players only "forest" is on the board, so a
hook for a space id not on the board is simply inert.

TIMING / KIND. "Each time AFTER you use [a space] … you can" → an OPTIONAL trigger in the
AFTER phase of the wood-space host — the text says "after" explicitly (the one legitimate
reason to key ``after_action_space``). Surfaced as a ``FireTrigger`` the player may take or
decline; the host's after-phase ``Stop`` is the decline. Owner-gated ("you"); once per use
via the host frame's ``triggers_resolved`` (the firing machinery filters a fired card out).
A wood accumulation space is ATOMIC (Forest, and the future 3-4-player wood spaces), so it
has no host frame by default — ``register_action_space_hook`` is REQUIRED to give it a
``PendingActionSpace`` host for the trigger to attach to (forgetting it is the classic
silent failure).

ELIGIBILITY — offered only when the whole action is doable, so the grant never dead-ends:
  1. the host frame's ``space_id`` is a wood accumulation space,
  2. the owner holds >= 1 stone (the piece to place), and
  3. a legal "Build Fences" pasture commit exists right now — the engine's own
     ``_any_legal_pasture_commit``, threaded with this card's frame provenance so it
     anticipates the exact ``PendingBuildFences`` the apply fn will push (mirroring how the
     granted-fences dispatch, ``_choose_subaction_granted_subaction``'s build_fences branch,
     gates the same category).

EFFECT (firing the trigger = opting in to the whole thing):
  1. Debit 1 stone from the owner's supply.
  2. Place that stone on the space just used — add ``Resources(stone=1)`` to the space's
     ``accumulated`` Resources vector (the space identity is the frame's ``space_id``;
     editing a space's accumulated stock has precedent — Pet Lover restores animals to a
     market). The NEXT visitor to that space sweeps the WHOLE accumulated vector
     (``_resolve_building_accumulation``: ``p.resources + space.accumulated``), stone
     included — that is "for the next visitor".
  3. Take the literal "Build Fences" action: push the real multi-shot ``PendingBuildFences``
     with ``build_fences_action=True`` (the default — the LITERAL named action, so
     action-scoped free-fence sources apply) and ``initiated_by_id="card:nail_basket"``,
     seeding any owned card's per-action free-fence budget via ``free_fence_budget_for`` —
     exactly the push the granted-fences dispatch and the Fencing space's initiate perform.
     In CARDS mode the deferred-tally settle pays the fence wood at the ``Proceed`` flip; the
     player pays wood normally.

Card-game only (ownership-gated registries; no new engine state), so the Family trace and
the C++ differential gates are untouched. See CARD_ENGINE_IMPLEMENTATION.md §2/§5.2 and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "nail_basket"
FRAME_ID = "card:nail_basket"   # the granted Build Fences frame's initiated_by_id


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the grant only when it is fully doable (never a dead-end)."""
    top = state.pending_stack[-1]
    if top.space_id not in WOOD_ACCUMULATION_SPACES:
        return False
    p = state.players[idx]
    if p.resources.stone < 1:
        return False
    # A legal Build Fences pasture commit must exist now, under this card's own frame
    # provenance (so a literal-action free-fence budget is anticipated exactly as the
    # pushed frame will seed it) — mirrors the granted-fences dispatch's gate.
    from agricola.legality import _any_legal_pasture_commit
    return _any_legal_pasture_commit(
        state, p, space_id=FRAME_ID, initiated_by_id=FRAME_ID)


def _apply(state: GameState, idx: int) -> GameState:
    from agricola.cards.cost_mods import free_fence_budget_for
    from agricola.pending import PendingBuildFences, push
    space_id = state.pending_stack[-1].space_id
    # 1) Debit 1 stone from the owner's supply.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(stone=1))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    # 2) Place the stone on the space just used (for the next visitor). The next user
    #    sweeps the WHOLE accumulated Resources vector, stone included.
    sp = get_space(state.board, space_id)
    state = fast_replace(
        state, board=with_space(
            state.board, space_id,
            fast_replace(sp, accumulated=sp.accumulated + Resources(stone=1))))
    # 3) Take the literal "Build Fences" action — the real multi-shot host with this
    #    card's provenance + the seeded per-action free-fence budget (matches the
    #    granted-fences dispatch and the Fencing space initiate).
    return push(state, PendingBuildFences(
        player_idx=idx, initiated_by_id=FRAME_ID,
        free_fence_budget=free_fence_budget_for(
            state, idx, build_fences_action=True, space_id=FRAME_ID),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
