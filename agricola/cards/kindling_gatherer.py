"""Kindling Gatherer (occupation, deck E #118; Ephipparius; players 1+).

Card text: "Each time you get food from an action space, you get 1 additional
wood."

User rulings (2026-07-14):

1. Only food the SPACE ITSELF yields counts. Food provided by a CARD when
   using a space (e.g. Fish Farmer's "+2 food on the Reed Bank/Clay Pit/
   Forest", Brook) does NOT trigger this card — "the card provides the 2
   extra food, not the space."
2. Hooked as a fixed space list: at 2 players, `day_laborer` (2 food,
   permanent) and `fishing` (the food accumulation space). A catalog sweep
   (2026-07-14) confirmed Sugar Baker (D101, unimplemented) is the only card
   that places food on a non-food action space (Grain Utilization) — if
   Sugar Baker is ever implemented, revisit this list / hard-code that
   interaction. Traveling Players joins the list at 4 players. Food
   physically placed on Fishing by cards (Fishing Net) needs no special
   handling — Fishing is on the list and its take sweeps everything.

Mandatory, choice-free automatic effect on the AFTER window (Refactor A):
"each time you get food from an action space" keys on what the space actually
yielded, so it reads the food swept into the player across the take. +1 wood
when using Day Laborer or Fishing. Both spaces are atomic, so they must be
explicitly hosted via `register_action_space_hook`; the food they yield is
stamped on the host frame's `taken` at the Proceed take. Eligibility gates on
food actually gotten — `taken.food >= 1`: Day Laborer always yields 2 food
(`taken.food == 2`); Fishing only pays when it held food, so an empty Fishing
sweeps 0 and pays nothing. Reading `taken.food` subsumes the old day_laborer/
fishing space-id switch uniformly (no special-casing), and — because card-
provided food is granted OUTSIDE the take and never enters `taken` — it also
enforces ruling 1 (only food the SPACE ITSELF yields counts) for free. The
reward is a flat 1 wood per use, never per unit of food. Played via Lessons;
its on-play is a no-op.

The separate Sugar Baker interaction below stays a BEFORE-window auto: that food
is a deposit ON the (non-atomic) Grain Utilization space, collected during the
before-window by Sugar Baker's own auto — it never flows through an atomic take,
so there is no `taken` to read and the CardStore-deposit read is retained.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import FOOD_PROVIDING_ACTION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "kindling_gatherer"


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at an after_action_space host frame: the space's own food yield is
    # the `taken.food` delta stamped across the take (Day Laborer's fixed 2, or
    # Fishing's swept pile). Non-atomic hosts (e.g. Grain Utilization, reached via
    # the Sugar Baker before-auto below) carry no `taken` → ineligible here. Gates
    # on food actually gotten, so an empty Fishing (taken.food == 0) pays nothing.
    taken = getattr(state.pending_stack[-1], "taken", None)
    return taken is not None and taken.food >= 1


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
register_auto("after_action_space", CARD_ID, _eligible, _apply)
# The Sugar Baker deposit is collected in the BEFORE window (see the docstring): a
# separate before-auto, order=-1 so it READS the deposit before Sugar Baker's own
# collection auto (default order 0) grants it to the visitor and clears the debt.
register_auto("before_action_space", CARD_ID, _sugar_baker_deposit_eligible, _apply,
              order=-1)
register_action_space_hook(CARD_ID, FOOD_PROVIDING_ACTION_SPACES)
