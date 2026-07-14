"""Hand Truck (minor improvement, B67; Bubulcus Expansion; players -).

Card text: "Each time before you take a 'Bake Bread' action, you also get 1
grain for each of your people occupying an accumulation space."
Clarification: "You must bake if you receive the grain."

Cost: 1 wood. No prerequisite, no printed VPs, not a passing card.

Bake-bread hook, automatic income. "You also get" + the must-bake clarification
make this a MANDATORY, choice-free effect → an automatic effect
(``register_auto``) on the ``before_bake_bread`` sub-action event, not a
declinable ``FireTrigger`` like Potter Ceramics. It fires once per
``PendingBakeBread`` push (engine._fire_subaction_before_auto, since
``bake_bread`` is a sub-action host in SUBACTION_PENDING_IDS), i.e. once per Bake
Bread action, across every bake host (Grain Utilization / Side Job / Clay Oven /
Stone Oven).

Timing — BEFORE the bake's own effect. The grain must arrive before CommitBake
so it is bakeable this action ("before you take" + must-bake), which the
before-phase delivers.

The "must bake if you receive the grain" clarification is satisfied for free by
the engine: a ``before_bake_bread`` effect only runs inside a PendingBakeBread
frame, which is reachable only after the player chose to bake at the parent, and
the before-phase's only exit is CommitBake (Stop appears only in the
after-phase). So "take the grain, then decline the bake" is structurally
impossible — no special handling needed.

Crucially, the whole POINT of the clarification is that a player can take a Bake
Bread action even at **0 grain** in order to first harvest Hand Truck's grain and
then bake it. So Hand Truck must make Bake Bread LEGAL when the owner has 0 grain,
a baker, and ≥1 person on an accumulation space — otherwise ``_can_bake_bread``
(grain ≥ 1) gates the action away and the grant can never fire on an empty supply.
This is exactly Potter Ceramics' situation, solved the same way: a
``register_bake_bread_extension`` that broadens ``_can_bake_bread`` for this card.

Count = "each of YOUR people occupying an accumulation space": the OWNER's own
workers (``ActionSpaceState.workers[idx]``) summed over the nine spaces in
``helpers.accumulation_spaces(state)`` (the 5 building-resource spaces and 4 food/animal
spaces — meeting_place is excluded, as it accumulates nothing in the card game;
user ruling 2026-07-02). The bake host (Grain Utilization / Side Job / the ovens) is
not an accumulation space, so the worker that initiated this bake is correctly
not self-counted. Eligibility gates on count > 0 so an empty +0-grain grant is
never applied. See CARD_AUTHORING_GUIDE.md and wood_pile.py (the same
worker-counting idiom for an immediate grant).
"""
from __future__ import annotations

from agricola.helpers import accumulation_spaces
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.legality import _owns_baker, register_bake_bread_extension
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState, get_space

CARD_ID = "hand_truck"

def _people_on_accumulation_spaces(state: GameState, idx: int) -> int:
    """Count the OWNER's workers currently on accumulation spaces."""
    return sum(get_space(state.board, sid).workers[idx]
               for sid in accumulation_spaces(state))


def _eligible(state: GameState, idx: int) -> bool:
    # Ownership is already enforced by apply_auto_effects; gate only on there being
    # at least one of the owner's people on an accumulation space, so a 0-grain
    # no-op grant is never applied.
    return _people_on_accumulation_spaces(state, idx) > 0


def _apply(state: GameState, idx: int) -> GameState:
    count = _people_on_accumulation_spaces(state, idx)
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=count))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _can_bake_bread_extension(state: GameState, p: PlayerState) -> bool:
    """Broaden _can_bake_bread: a player who owns Hand Truck + a baker can take a Bake
    Bread action even with 0 grain, provided they have >= 1 person on an accumulation
    space (the before_bake_bread hook will then supply >= 1 grain to bake). Mirrors
    Potter Ceramics' clay->grain extension."""
    if CARD_ID not in p.minor_improvements:
        return False
    if not _owns_baker(state, p):
        return False
    idx = next(i for i in range(len(state.players)) if state.players[i] is p)
    return _people_on_accumulation_spaces(state, idx) > 0


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_bake_bread", CARD_ID, _eligible, _apply)
register_bake_bread_extension(_can_bake_bread_extension)
