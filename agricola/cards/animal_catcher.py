"""Animal Catcher (occupation, C168; Corbarius Expansion; players 4+).

Card text: "Each time you use the 'Day Laborer' action space, instead of 2 food,
you can get 3 different animals from the general supply. If you do, you must pay 1
food each harvest left to play."

TIMING / KIND. "Each time you use [the space] … you can" → an OPTIONAL trigger in
the BEFORE phase of the Day Laborer host (the Trigger-Timing ruling), surfaced as a
FireTrigger the player may take or decline (declining is the host's Proceed, which
lets Day Laborer's normal +2 food run). Owner-gated ("you"); once per use via the
host frame's ``triggers_resolved``. Day Laborer is a TRUE-ATOMIC permanent space
(its handler grants a fixed +2 food with no host frame of its own), so it must be
explicitly hosted via `register_action_space_hook` for the trigger to attach.

EFFECT — two INDEPENDENT halves (ACTION_REPLACEMENT_DESIGN.md):
1. Suppress Day Laborer's own reward — `helpers.suppress_space_reward` marks the
   host ``suppressed``; `_apply_proceed` then SKIPS the +2-food handler, so the
   space grants nothing and its ``taken`` delta reads Resources(). Because
   `taken.food == 0`, "each time you get food from an action space" reactors
   (Kindling Gatherer) do NOT fire — the payoff of the delta-based ``taken`` design,
   with no special-casing here.
2. Animal Catcher's OWN reward — "3 different animals" = 1 sheep + 1 boar + 1 cattle
   (the three types) from the general supply, granted via `helpers.grant_animals`
   so the accommodation barrier reconciles them if they overflow. This reward never
   touches the suppressed food channel.

THE TAX — "you must pay 1 food each harvest left to play" (per swap). Modeled as a
CardStore counter incremented on each swap, plus a `register_feeding_requirement`
fold of ``+counter`` at the feeding chokepoint. Because the fold reads the LIVE
counter at each feeding, a swap in some round raises the counter so every LATER
harvest owes 1 more, while earlier harvests (reading the smaller counter) are
unaffected — exactly "1 food each harvest left to play" summed per swap, per the
user ruling that the cost applies each time the player uses the effect.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_feeding_requirement
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.helpers import grant_animals, suppress_space_reward
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "animal_catcher"
_SPACES = frozenset({"day_laborer"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    # Always available on Day Laborer: the +2 food is unconditionally replaceable,
    # and the animal grant (via grant_animals) is always doable (the barrier houses
    # or cooks any overflow).
    return state.pending_stack[-1].space_id == "day_laborer"


def _apply(state: GameState, idx: int) -> GameState:
    # 1) Suppress Day Laborer's +2 food (space grants nothing -> taken.food == 0).
    state = suppress_space_reward(state)
    # 2) The alternate reward: 3 different animals from the general supply.
    state = grant_animals(state, idx, Animals(sheep=1, boar=1, cattle=1))
    # 3) Latch the per-swap tax: bump the CardStore counter the feeding fold reads.
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(
        CARD_ID, p.card_state.get(CARD_ID, 0) + 1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _feeding_fold(state: GameState, idx: int, need: int) -> int:
    # +1 food per swap taken so far (the live counter — see the docstring's TAX note).
    return need + state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _SPACES)             # Day Laborer is true-atomic
register_feeding_requirement(CARD_ID, _feeding_fold)
