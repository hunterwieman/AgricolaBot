"""Baking Course (minor improvement, D64; Dulcinaria Expansion).

Card text (verbatim): "At the end of each round that does not end with a
harvest, you can take a "Bake Bread" action. "Bake Bread" action: Grain →
2 Food"

Cost: free. Prerequisite: 1 Occupation. No printed VP. Not passing.

USER RULING 51 (2026-07-12, verbatim): "its second sentence (\"'Bake Bread'
action: Grain → 2 Food\") is the card supplying an UNLIMITED grain→2-food
conversion rate during ALL Bake Bread actions, 'just like the fireplace
does' — a standing baking source (the BAKING_SPEC_EXTENSIONS seam), NOT a
rate scoped to the bake the card's first sentence grants. The grant itself
is an optional end_of_round bake (non-harvest rounds, ruling 49's rung)."

TWO EFFECTS, per that ruling:

1. **The standing baking source.** A `BAKING_SPEC_EXTENSIONS` entry
   contributes an uncapped (cap None) rate-2 spec whenever the OWNER bakes —
   in every Bake Bread action, whatever pushed the frame (an action space's
   bake branch, another card's granted bake, or this card's own end-of-round
   grant). The greedy allocator in `_execute_bake` composes it with any
   better-rate oven automatically (the oven's grain first, the rest at 2).
   Because a standing source must also make the Bake Bread action REACHABLE
   for an oven-less owner ("just like the fireplace does" — a fireplace
   satisfies `_can_bake_bread` via `_owns_baker`), the card additionally
   registers a `register_bake_bread_extension` predicate: the owner with
   >= 1 grain can take a Bake Bread action with no major improvement. This
   is an implication of ruling 51, not a separate mechanism choice — without
   it the "ALL Bake Bread actions" rate would be unreachable at the bake
   choose-points for an oven-less owner.

2. **The end-of-round grant.** The round-end ladder's ``end_of_round`` rung
   (user ruling 49, 2026-07-12: the returning-home phase is the round's LAST
   phase, and "the end of the round" is a DISTINCT, LATER instant — the final
   window of `agricola/cards/round_end.py`'s step table). An ordinary
   optional trigger registered on that event; the walk pushes the per-player
   ``PendingHarvestWindow`` choice host when the owner's trigger is eligible.
   "That does not end with a harvest" is the card's own eligibility clause
   (the ladder runs on harvest rounds too — the round_end.py module note):
   ``state.round_number not in HARVEST_ROUNDS``. Eligibility also requires a
   committable bake — grain >= 1 suffices, since this card itself guarantees
   a baking source. Firing pushes the standard ``PendingBakeBread`` (the REAL
   Bake Bread action — before/after-bake card hooks fire normally, and the
   granted sub-action's decline path is the window host's fire-or-``Proceed``
   choice, per the standing invariant that optionality lives at the parent).
   Once per round via the host frame's ``triggers_resolved`` ("a Bake Bread
   action", singular).

Card-only state is nil (no CardStore use); every registration self-gates on
ownership, so unowned the card is inert and the Family game is untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.constants import HARVEST_ROUNDS
from agricola.legality import (
    register_bake_bread_extension,
    register_baking_spec_extension,
)
from agricola.pending import PendingBakeBread, push
from agricola.state import GameState, PlayerState

CARD_ID = "baking_course"
WINDOW_ID = "end_of_round"


def _baking_spec(state: GameState, player_idx: int) -> list[tuple]:
    """The standing source (ruling 51): uncapped grain -> 2 food while the
    owner has the card in play. (cap None, rate 2) — the fireplace's rate
    without the fireplace."""
    p = state.players[player_idx]
    return [(None, 2)] if CARD_ID in p.minor_improvements else []


def _can_bake_bread_extension(state: GameState, p: PlayerState) -> bool:
    """Broaden `_can_bake_bread`: the owner IS a baking source, so grain
    alone suffices to take a Bake Bread action (no major improvement
    needed) — ruling 51's "just like the fireplace does"."""
    return CARD_ID in p.minor_improvements and p.resources.grain >= 1


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """The printed condition (this round does not end with a harvest —
    HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}; the round-end walk runs before
    the next round's preparation increments `round_number`, so during round
    N's ladder it still reads N) + a committable bake: grain >= 1 is enough
    because this card itself guarantees a rate-2 source. Ownership and the
    once-per-round guard are the host enumerator's."""
    return (state.round_number not in HARVEST_ROUNDS
            and state.players[idx].resources.grain >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    """The grant: push the standard Bake Bread primitive (a real Bake Bread
    action — hooks fire normally). Declining happened at the fire/Proceed
    choice on the window host, so the pushed frame itself is committed."""
    return push(state, PendingBakeBread(
        player_idx=idx, initiated_by_id="card:baking_course"))


# Free; prerequisite 1 occupation; no printed VP; the on-play is a no-op (both
# effects are standing registrations gated on ownership).
register_minor(CARD_ID, min_occupations=1)

# Effect 1 — the standing rate-2 baking source + the action's reachability.
register_baking_spec_extension(_baking_spec, CARD_ID)
register_bake_bread_extension(_can_bake_bread_extension)

# Effect 2 — the optional end-of-round bake (ruling 49's rung); once per round
# via the host frame's triggers_resolved.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
