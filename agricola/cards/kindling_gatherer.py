"""Kindling Gatherer (occupation, deck E #118; Ephipparius; players 1+).

Card text: "Each time you get food from an action space, you get 1 additional
wood."

User rulings (2026-07-14):

1. Only food the SPACE ITSELF yields counts. Food provided by a CARD when
   using a space (e.g. Fish Farmer's "+2 food on the Reed Bank/Clay Pit/
   Forest", Brook) does NOT trigger this card — "the card provides the 2
   extra food, not the space."
2. Implemented as a fixed space list: at 2 players, `day_laborer` (2 food,
   permanent) and `fishing` (the food accumulation space). A catalog sweep
   (2026-07-14) confirmed Sugar Baker (D101, unimplemented) is the only card
   that places food on a non-food action space (Grain Utilization) — if
   Sugar Baker is ever implemented, revisit this list / hard-code that
   interaction. Traveling Players joins the list at 4 players. Food
   physically placed on Fishing by cards (Fishing Net) needs no special
   handling — Fishing is on the list and its take sweeps everything.

Mandatory, choice-free automatic effect on the BEFORE window ("each time you
get food from …" bundles with the get; a flat reward fires before, per the
standing ruling): +1 wood when using Day Laborer or Fishing. Both spaces are
atomic, so they must be explicitly hosted via `register_action_space_hook`.
Eligibility gates on food actually being gotten: Day Laborer always yields
2 food; Fishing only pays when it holds at least 1 food (it refills every
preparation phase, so this is nearly always true). The reward is a flat
1 wood per use, never per unit of food. Played via Lessons; its on-play is a
no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "kindling_gatherer"

# The action spaces that themselves yield food in the 2-player game (ruling 2:
# a fixed list — day_laborer is a permanent 2-food space, fishing is the food
# accumulation space).
FOOD_SPACES = frozenset({"day_laborer", "fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space via the
    # host frame's `space_id`. Day Laborer always yields 2 food. Fishing only
    # yields food when it holds some — gate on that, since the card pays only
    # when food is actually gotten.
    space_id = state.pending_stack[-1].space_id
    if space_id == "day_laborer":
        return True
    if space_id == "fishing":
        return get_space(state.board, "fishing").accumulated_amount >= 1
    return False


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _sugar_baker_deposit_eligible(state: GameState, idx: int) -> bool:
    """The hard-coded Sugar Baker interaction (user-approved 2026-07-14: "we can
    hard code a specific interaction if it really is just this one case" — the
    catalog sweep confirmed it is). Sugar Baker places 1 food ON the Grain
    Utilization space for the next visitor (held as `sugar_baker_owed` in its
    owner's CardStore, granted by Sugar Baker's own any-player before-auto).
    That food comes FROM the space, so collecting it is "getting food from an
    action space" and pays this card's wood. Either player may own the Sugar
    Baker; the visitor (the acting player, this card's owner) is who collects.
    """
    if state.pending_stack[-1].space_id != "grain_utilization":
        return False
    return any(p.card_state.get("sugar_baker_owed", 0) > 0 for p in state.players)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
# order=-1: must READ the deposit before Sugar Baker's collection auto (default
# order 0) grants it to the visitor and clears the debt in the same window.
register_auto("before_action_space", CARD_ID, _sugar_baker_deposit_eligible, _apply,
              order=-1)
register_action_space_hook(CARD_ID, FOOD_SPACES)
