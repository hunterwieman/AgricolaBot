"""Furnisher (occupation, deck D #96; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "When you play this card, you immediately get 2 wood. After
each new room you build, you can build or play 1 improvement for 1 wood less."
Clarification (verbatim): "The improvement does not need to cost any wood."

GOVERNING RULINGS — USER RULING 74, 2026-07-21 (CARD_DEFERRED_PLANS.md):
"Furnisher (D96) — triggers on every room build, not just named Build Rooms
actions (user). The grants resolve without interruption (user): one trigger;
firing opens up to N consecutive improvement plays (N = rooms built that action;
build-major or play-minor, each -1 wood via `granted_by`-scoped reductions),
then the card is done for that action. The improvement need not cost wood
(printed clarification). Needs the multi-use counter on
`PendingGrantedSubAction`."

How each clause maps onto the machinery:

- **Every room build**: the trigger registers on the ``after_build_rooms`` event
  — the build-rooms host's after-window — with NO gate on the frame's
  ``build_rooms_action`` flag, so a card-granted single-room build (Cottager's
  "build exactly 1 room", flag False) qualifies too, with N = 1. The
  after-window opens exactly once per rooms-adding action (at the host's
  ``Proceed`` work-complete flip, reachable only once ``num_built >= 1``), so
  "after each new room you build" resolves once per action with the full N.

- **Without interruption**: ONE optional trigger in the after-window; firing
  pushes ``PendingGrantedSubAction(initiated_by_id="card:furnisher",
  subactions=("build_major", "play_minor"), max_uses=N)`` — the use-budget
  wrapper shape (ruling 74; see the ``max_uses``/``uses_done`` docstring in
  pending.py). Each use is ONE improvement (build a major OR play a hand
  minor); ``Stop`` ends early; when uses run out only ``Stop`` remains. The
  uses resolve consecutively with nothing interleaving — structural, because
  the wrapper sits on top of the stack until it pops. Once fired, the host's
  ``triggers_resolved`` latch makes the card done for that action.

- **The card's OWN effect, never the named actions**: choosing ``build_major``
  pushes the bare ``PendingBuildMajor`` and choosing ``play_minor`` pushes
  ``PendingPlayMinor`` with ``minor_improvement_action=False`` — the wrapper's
  defaults (``major_allowed=None``, ``minor_is_action=False``) — so
  named-action readers (Merchant's repeat, Small Trader) never fire on these.

- **The -1 wood**: a ``register_reduction`` on BOTH "build_major" and
  "play_minor", each gated on ``ctx.granted_by == "card:furnisher"`` — the
  grant's provenance, threaded from the pushed frame's ``initiated_by_id``
  (the build_major/renovate pattern; wired for play_minor with ruling 74). A
  normal build/play by the owner (an improvement space, another card's grant)
  carries a different ``granted_by`` and gets NO discount. Per the printed
  clarification the grant is NOT gated on the improvement costing wood — a
  wood-free improvement plays through it (the reduction floors to no-op).

ELIGIBILITY (never a dead-end): the trigger is offered only when at least one
use is takeable right now — some major is unbuilt and payable, or some hand
minor is playable, each priced under the GRANT-scoped ctx (so an improvement
affordable only via the -1 wood still makes the trigger eligible). This
mirrors ``legality._granted_subaction_eligible``'s build_major / play_minor
branches exactly (same predicates, same granted_by), so trigger-eligible iff
the pushed wrapper would offer >= 1 category.

On-play: +2 wood ("you immediately get 2 wood").

Played via Lessons. Card-only registries are empty in the Family game, so the
Family game is byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _build_major_ctx, can_pay, playable_minors
from agricola.pending import PendingBuildRooms, PendingGrantedSubAction, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "furnisher"
_GRANTED_BY = f"card:{CARD_ID}"


def _on_play(state: GameState, idx: int) -> GameState:
    """'When you play this card, you immediately get 2 wood.'"""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the trigger in the build-rooms after-window iff >= 1 use is
    takeable under the GRANT-scoped pricing — mirroring
    ``_granted_subaction_eligible``'s build_major and play_minor branches with
    ``granted_by=_GRANTED_BY``, so the pushed wrapper is never a dead-end.
    Once per action is the host's ``triggers_resolved`` (checked by the firing
    machinery; self-checked here too, mirroring the exemplars). Ownership is
    the enumerator's gate."""
    if CARD_ID in triggers_resolved:
        return False
    owners = state.board.major_improvement_owners
    if any(
        owners[i] is None
        and can_pay(state, idx, _build_major_ctx(i, granted_by=_GRANTED_BY))
        for i in range(10)
    ):
        return True
    return bool(playable_minors(state, idx, granted_by=_GRANTED_BY))


def _apply(state: GameState, idx: int) -> GameState:
    """Open the use-budget wrapper: up to N consecutive improvement builds/
    plays, N = rooms built in the completed action (the host frame's own
    ``num_built`` counter — the host is still stack-top at apply time, the
    firing machinery records the latch before calling us). The wrapper's
    defaults give the bare frames: ``major_allowed=None`` (full board) and
    ``minor_is_action=False`` (not the named Minor Improvement action)."""
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms), top
    return push(state, PendingGrantedSubAction(
        player_idx=idx,
        initiated_by_id=_GRANTED_BY,
        subactions=("build_major", "play_minor"),
        max_uses=top.num_built,
    ))


def _less_1_wood_granted(state, idx, ctx, cost: Resources) -> Resources:
    """'... for 1 wood less' — ONLY on a build/play riding this card's grant
    (``ctx.granted_by`` is the pushed frame's provenance). The fold floors at
    0, so a wood-free improvement is unaffected (the printed clarification)."""
    if ctx.granted_by != _GRANTED_BY:
        return cost
    return cost - Resources(wood=1)


register_occupation(CARD_ID, _on_play)

# "After each new room you build, you can build or play 1 improvement ..." —
# an OPTIONAL trigger on the rooms build's after-window, on EVERY rooms
# addition regardless of `build_rooms_action` (ruling 74).
register("after_build_rooms", CARD_ID, _eligible, _apply)

# "... for 1 wood less" — grant-scoped on both improvement kinds (ruling 74).
register_reduction("build_major", CARD_ID, _less_1_wood_granted)
register_reduction("play_minor", CARD_ID, _less_1_wood_granted)
