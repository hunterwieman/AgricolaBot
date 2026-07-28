"""Straw Hat (minor improvement, E10; Ephipparius Expansion; cost 1 reed).

Card text: "At the end of the work phases of rounds 3 and 6, you can move your
person from the "Farmland" action space to an unoccupied action space and take
that action, or get 1 food."

Governing rulings (user, 2026-07-27 — ruling 83):

1. **The 1-food branch is UNCONDITIONAL** — offered at the end of work of rounds
   3 and 6 whether or not a person stands on Farmland (the relocation branch is
   what needs the person there).
2. **The relocation inherits the jump-family destination readings wholesale**
   (ruling 81): "unoccupied" is read at the fire time and STRICTLY — via
   `legality.space_occupied`, the occupancy-READING definition (a worker OR a
   "considered occupied" marker blocks; an occupancy-exemption card never
   un-occupies); the destination's own action must be legal per the SAME
   per-space placement predicate a normal `PlaceWorker` uses (never a dead-end
   use); and the destination resolves as a FULL use — its frames stack above
   this window's host, its before/after card events fire, and the ladder
   resumes after.
3. **The Steam Machine interaction cuts both ways** (the last-use commitment,
   `PlayerState.last_use_committed`): if the player's Steam Machine has already
   FIRED this work phase (committing that use as the phase's last), the
   relocation branch is gone — only the 1 food (and declining) remain. If it
   has NOT fired, a relocation onto an accumulation space is a new last use and
   Steam Machine's own `after_action_space` trigger surfaces at the destination
   with no code here — its eligibility (accumulation space + `people_home == 0`
   + latch unset + can bake) holds there naturally.

Ordinal bookkeeping (ruling 79): the move MINTS no number — `_move_board_worker`
rewrites the worker's standing-worker ledger entry to the destination, so the
person keeps the number it was placed with, and an ordinal reader firing at the
destination (Catcher / Wheel Plow / Plow Hero / Fir Cutter, via
`helpers.acting_placement_number`) reads that PRESERVED number — which can be
lower than the round's mint counter. A relocation counts as "placing" for those
readers (ruling 79 item 4), which falls out of the destination's windows firing.

MECHANICS. An optional trigger on the round-end ladder's `end_of_work` window
(rulings 49/50 — still DURING the work phase; the Apiary/Sundial rung), latched
to rounds 3 and 6 by eligibility; once per window via the frame's
`triggers_resolved`; declining is the window host's Proceed. The two branches
are play-variants (the Cottager idiom): variant "food" plus one variant per
legal destination space. The relocation fire sets `current_player` to the owner
before running the destination (`initiate_space_use` acts for the current
player, and at end-of-work the last actor may be the opponent) and leaves it —
rounds 3 and 6 are non-harvest, nothing between this window and the next
round's WORK entry reads `current_player`, and that entry re-anchors it to the
starting player.

Destination legality is evaluated on a probe state with `current_player` set to
the owner (the per-space predicates read `state.current_player`), composing the
strict unoccupancy read FIRST so a predicate's occupancy-exemption branch can
never admit an occupied destination. Farmland itself is excluded by that same
read (the mover stands on it).
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.cards.worker_moves import relocate_and_use
from agricola.legality import CARD_GAME_LEGALITY, space_occupied
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "straw_hat"
_ROUNDS = frozenset({3, 6})


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"...of rounds 3 and 6". Never a dead-end: the 1-food variant is
    unconditional (ruling 83 item 1), so an eligible fire always has a variant.
    Ownership is the window machinery's gate; once-per-window is the frame's
    ``triggers_resolved``."""
    return state.round_number in _ROUNDS


def _variants(state: GameState, idx: int) -> list:
    """"food", plus one variant per legal relocation destination. Destinations
    exist only while a person of the owner stands on Farmland and no use has
    been committed as the phase's last (ruling 83 item 3 — a fired Steam
    Machine forecloses the move, leaving the food); each must be strictly
    unoccupied AND legal per its own placement predicate, probed as the owner.

    CARD action spaces join the destination universe (ruling 86 item 5 —
    "Straw Hat, Archway, and others should allow the jumping worker to move to
    one of these action spaces as well as the normal action spaces on the
    board"): each registered, played, un-occupied card space the owner could
    place on ("for you only" = own cards; a `for_all` card = either player's),
    one variant per `placeable_fn` entry — a picks-bearing entry (Collector's
    wide goods choice) surfaces as a (variant, picks) tuple, one FireTrigger
    per combination, mirroring the space's own placements. When the toll seam
    lands (ruling 86 items 1/2), the non-owner filter here additionally gates
    on the toll being payable, exactly like a placement."""
    variants: list = ["food"]
    p = state.players[idx]
    if (get_space(state.board, "farmland").workers[idx] >= 1
            and not p.last_use_committed):
        probe = fast_replace(state, current_player=idx)
        variants += [
            sid for sid, predicate in CARD_GAME_LEGALITY.items()
            if not space_occupied(state, sid) and predicate(probe)
        ]
        from agricola.cards.card_spaces import (
            CARD_ACTION_SPACES, card_space_occupied, played_card_owner,
            toll_payable,
        )
        for card_id in sorted(CARD_ACTION_SPACES):
            spec = CARD_ACTION_SPACES[card_id]
            owner = played_card_owner(state, card_id)
            if owner is None:
                continue                       # in a hand / undealt — no space
            if owner != idx and not spec.for_all:
                continue                       # "for you only"
            if (owner != idx and spec.toll is not None
                    and not toll_payable(state, idx, spec.toll)):
                continue                       # ruling 86: the toll gates the
                                               # arrival however the worker moves
            if card_space_occupied(state, card_id):
                continue
            dest = f"card:{card_id}"
            for picks in spec.placeable_fn(state, idx, owner):
                variants.append(dest if picks is None else (dest, picks))
    return variants


def _apply(state: GameState, idx: int, variant: str, picks=None) -> GameState:
    """Fire one branch: the 1 food, or move the Farmland person to `variant`
    and take that action (the shared jump helper — the ledger entry follows
    the person, the destination resolves fully above this window's host). A
    "card:<id>" variant is a card-space destination (ruling 86 item 5);
    `picks` is its wide payload (Collector), threaded by the picks-bearing
    FireTrigger."""
    if variant == "food":
        p = state.players[idx]
        p = fast_replace(p, resources=p.resources + Resources(food=1))
        return fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(len(state.players))))
    state = fast_replace(state, current_player=idx)
    return relocate_and_use(state, idx, "farmland", variant, picks=picks)


def _action_label(variant: str):
    """Terse per-variant labels for the web UI's trigger buttons."""
    if variant == "food":
        return "get 1 food"
    if variant.startswith("card:"):
        return f"move to {variant.split(':', 1)[1].replace('_', ' ').title()}"
    from agricola.constants import SPACE_DISPLAY_NAMES
    return f"move to {SPACE_DISPLAY_NAMES.get(variant, variant)}"


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)))
register("end_of_work", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_action_labeler(CARD_ID, _action_label)
