"""Junior Artist (occupation, B152; Bubulcus Expansion; players 4+).

Card text (verbatim): "Each time after you use the 'Day Laborer' action space,
you can pay 1 food to use an unoccupied 'Traveling Players' or 'Lessons' action
space with the same person."
Category: Actions Booster. No printed VPs. On-play is a no-op.

GOVERNING RULING (user, 2026-07-26 — ruling 81):

1. The jump is an OPTIONAL trigger in the SOURCE's ``after_action_space``
   window; firing it moves the acting worker's board marker from Day Laborer to
   the chosen destination and runs the destination's FULL action via the shared
   jump helper (``agricola.cards.worker_moves.relocate_and_use`` →
   ``engine.initiate_space_use``): the destination's frames stack above the
   source's after-window host, resolve completely (a relocation IS a use — the
   destination's before/after events fire), and the walk returns to the
   source's after-window, whose Stop ends the turn.
2. Destination-unoccupied is read AT THE TRIGGER TIME ("an unoccupied ...
   space") — enforced here as a strict workers-all-zero read of the
   destination, never ``_is_available``'s occupancy-override branch (an
   occupancy-exemption card must not make an occupied space count as
   "unoccupied" for this text).
3. No placement number is minted — the moved worker keeps the number of the
   placement that started the turn; ``placements_this_round`` is never touched
   (the PHYSICAL-ordinal rule, ruling 79).

MECHANICS. Day Laborer is true-atomic, so the card hooks it
(``register_action_space_hook``, own-use) to get a host frame while owned —
the Sheep Inspector / Canal Boatman shape. The two printed destinations make
this a play-variant trigger (the Cottager idiom): the after-window surfaces one
``FireTrigger("junior_artist", variant=<space_id>)`` per currently-legal
destination, and declining is the host's Stop with the trigger unfired
(granted actions are optional). A destination is legal iff:

- it exists on this board (``CARD_GAME_LEGALITY`` membership — board-shape
  note below);
- it is strictly unoccupied at the trigger time (ruling item 2); and
- its own action is legal on the POST-PAYMENT state: the card-game per-space
  placement predicate (``CARD_GAME_LEGALITY[space_id]``), evaluated on a
  hypothetical state with the 1 food already debited. The post-payment read is
  load-bearing for Lessons: the placement predicate is exactly what guarantees
  the no-decline ``PendingPlayOccupation`` is never pushed as a dead-end
  (``_enumerate_pending_play_occupation`` offers NO exit before the play), and
  the state the Lessons frames will actually see is the one after this card's
  food is paid. A gate on the pre-payment state could strand the worker: with
  2 food and one prior occupation, paying 1 for the jump leaves 1 — fine; with
  1 food it would leave 0 against Lessons' 1-food cost, a zero-action stuck
  state. The hypothetical-debit gate makes that unreachable.

THE 1-FOOD PAYMENT — the Canal Boatman shape (``canal_boatman.py``:
``food >= 1`` on hand + direct debit at the fire), NOT Plow Hero's
liquidation-aware raise-resume (``_liquidatable_to`` + ``PendingFoodPayment``).
Reason: the raise-resume does not compose with the destination-legality gate.
Plow Hero's granted plow is payment-independent — any way of raising its food
leaves the grant legal — but here the destination's OWN legality depends on
the goods left after the raise (Lessons' occupation cost), and the interactive
raise can legally stop at exactly the 1 food needed, resuming straight into
the Lessons dead-end above. Gating that exactly would need "does some
liquidation raise the jump food AND leave the occupation cost payable" —
joint-liquidation machinery that does not exist. The narrowing is marginal in
practice: Day Laborer itself just paid +2 food, so food-on-hand < 1 in this
window requires another same-window effect to have drained it first.

BOARD-SHAPE NOTE: ``traveling_players`` DOES NOT EXIST on the 2-player board
(no such id in ``SPACE_IDS`` / ``CARD_GAME_LEGALITY``), so that branch never
surfaces at 2p — the destination loop guards on legality-table membership.
This is a board fact, not an approximation: the Traveling Players branch
becomes live when a 3+/4-player board adds the space (and its placement
predicate) to the tables. The Lessons branch is fully live in the 2-player
card game.

No once-per-turn cap beyond the host's ``triggers_resolved`` (once per
after-window — no errata narrows it further); neither destination is itself a
jump source, so no chain-back exists. Players 4+, so the card is registered
but never dealt in the 2-player game (tests inject it — the Lodger precedent).
Card-game only (ownership-gated registries; no new engine state), so the
Family trace and the C++ differential gates are untouched. See
CARD_ENGINE_IMPLEMENTATION.md §2 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.cards.worker_moves import relocate_and_use
from agricola.legality import CARD_GAME_LEGALITY
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "junior_artist"
_SOURCE = "day_laborer"
# Printed order. Each destination is offered only when present on this board's
# legality table (traveling_players: 3+/4-player boards only — module docstring).
_DESTINATIONS = ("traveling_players", "lessons")
_FOOD_COST = 1


def _post_payment_state(state: GameState, idx: int) -> GameState | None:
    """The hypothetical state after the 1-food jump payment, or None when the
    food is not on hand (the Canal Boatman payment shape — module docstring).
    Destination predicates are evaluated on THIS state: it is exactly the state
    ``relocate_and_use`` will hand the destination's frames, so gate and
    destination enumerator agree."""
    p = state.players[idx]
    if p.resources.food < _FOOD_COST:
        return None
    hp = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
    return fast_replace(state, players=tuple(
        hp if i == idx else state.players[i] for i in range(len(state.players))))


def _variants(state: GameState, idx: int) -> list[str]:
    """The currently-legal jump destinations, in printed order. A destination
    qualifies iff it exists on this board, is strictly unoccupied at the
    trigger time (ruling 81 item 2 — a plain workers-all-zero read), and its
    own action is legal on the post-payment state (the card-game placement
    predicate — the never-a-dead-end gate; for Lessons: a playable occupation
    in hand whose cost is payable with the food left after the jump)."""
    hyp = _post_payment_state(state, idx)
    if hyp is None:
        return []
    out: list[str] = []
    for sid in _DESTINATIONS:
        predicate = CARD_GAME_LEGALITY.get(sid)
        if predicate is None:      # not on this board (traveling_players at 2p)
            continue
        # "an unoccupied ... space": strictly workers-all-zero (ruling item 2);
        # occupancy-override cards never widen this, and with zero workers the
        # predicate's internal `_is_available` reduces to the same read (plus
        # revealed / space-block markers — a space "considered occupied" by a
        # marker is not unoccupied either).
        if any(get_space(state.board, sid).workers):
            continue
        # The predicate reads `state.current_player`; the hook is own-use, so
        # the host exists only on the owner's turn and current_player == idx.
        if not predicate(hyp):
            continue
        out.append(sid)
    return out


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "Each time after you use the 'Day Laborer' action space": the host must
    # be Day Laborer and the owner's own use (the hook is own-use, so the host
    # only exists on the owner's turn — the player check is belt-and-braces,
    # the Sheep Inspector shape). "with the same person": the acting worker
    # must still stand on the source to be moved. Once per window via the
    # host's `triggers_resolved` (checked by `_eligible_fire_triggers`).
    # Never a dead-end: >= 1 legal destination after the payment.
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) != _SOURCE:
        return False
    if getattr(top, "player_idx", None) != idx:
        return False
    if get_space(state.board, _SOURCE).workers[idx] < 1:
        return False
    return bool(_variants(state, idx))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one jump: pay 1 food (direct debit — eligibility guaranteed it is
    on hand), then move the acting worker Day Laborer -> the chosen destination
    and run that space's full action (``relocate_and_use``: the vacated source
    re-opens, the relocated hooks fire, the destination's frames stack above
    this host, and the walk returns here). Mints no placement number
    (ruling 81 item 3)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    return relocate_and_use(state, idx, _SOURCE, variant)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# "Each time AFTER you use ..." — the after-window of the owner's own Day
# Laborer use (ruling 81 item 1).
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
# Day Laborer is true-atomic: without this own-use hook no host frame is ever
# pushed while the card is owned, and the trigger could never surface.
register_action_space_hook(CARD_ID, frozenset({_SOURCE}))
