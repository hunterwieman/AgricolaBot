"""Pet Lover (occupation, D138; Dulcinaria Expansion; players 3+).

Card text: "Each time you use an accumulation space providing exactly 1 animal,
you can leave it on the space and get one from the general supply instead, as
well as 3 food and 1 grain."

Clarification (Unofficial Compendium): "You may use the Animal Dealer A147 to
acquire a second animal of the taken type."

TIMING / KIND. "Each time you use [a space] … you can" → an OPTIONAL trigger in
the BEFORE phase of the animal-market host (the Trigger-Timing ruling), surfaced
as a FireTrigger the player may take or decline (the market's CommitAccommodate is
the decline — it pivots the host to its after-phase, closing the before-window).
Owner-gated ("you"); once per use via the host frame's ``triggers_resolved``. The
animal markets are NON-ATOMIC (always hosted, firing before_action_space), so no
register_action_space_hook is needed.

ELIGIBILITY — "an accumulation space providing exactly 1 animal". Each of the three
animal markets stages the animals swept off the space onto the host frame's
``gained`` at initiate (`_initiate_sheep_market` etc.), BEFORE the before-window —
so ``gained`` is exactly "how many animals the space is providing" and ``gained == 1``
is the card's "providing exactly 1 animal", read in the before-window like Cowherd /
Animal Dealer read the same field.

EFFECT — two INDEPENDENT halves (ACTION_REPLACEMENT_DESIGN.md):
1. Suppress the market's own take — `helpers.suppress_space_reward` leaves the 1
   animal on the space (restores ``accumulated_amount``, overriding the base "you
   must take all animals / cannot leave animals on the space" rule) and zeroes
   ``gained``. The now-trivial CommitAccommodate just flips to the after-phase.
2. Pet Lover's OWN reward — 1 animal of the SAME type from the general supply
   (via `helpers.grant_animals`, so the accommodation barrier reconciles it if it
   overflows — the German Heath Keeper idiom for a supply animal at a market), plus
   3 food and 1 grain. This reward never touches ``gained``.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.constants import FOOD_ANIMAL_ACCUMULATION_RATES
from agricola.helpers import grant_animals, suppress_space_reward
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "pet_lover"
_MARKET_SPACES = frozenset({"sheep_market", "pig_market", "cattle_market"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    if top.space_id not in _MARKET_SPACES:
        return False
    # "providing exactly 1 animal": `gained` is the count swept off the space,
    # staged at initiate before this before-window (only market frames carry it).
    return top.gained == 1


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    animal_name = FOOD_ANIMAL_ACCUMULATION_RATES[space_id][0]   # "sheep"/"boar"/"cattle"
    # 1) Suppress the space's own reward: leave the 1 animal on the space, gained -> 0.
    state = suppress_space_reward(state)
    # 2) Pet Lover's own reward (separate from the suppressed channel): 1 animal of
    #    the same type from the general supply + 3 food + 1 grain.
    state = grant_animals(state, idx, Animals(**{animal_name: 1}))
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=3, grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
