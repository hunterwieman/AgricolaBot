"""Seasonal Worker (occupation, A114; Base Revised; players 1+).

Card text: "Each time you use the \"Day Laborer\" action space, you get 1 additional
grain. From round 6 on, you can choose to get 1 vegetable instead."

Category 3 (action-space hook) but the MANDATORY-WITH-CHOICE firing kind (II.1): the
extra crop is not optional, yet from round 6 it carries a choice (grain or veg), so
it is a single `mandatory`-tagged trigger on the Day Laborer space-host whose
PendingCardChoice OPTIONS are round-dependent — `("grain",)` before round 6 (a
singleton the agent auto-resolves, i.e. always +1 grain) and `("grain", "veg")` from
round 6 on. The round-6 rule lives in the options, not the firing kind. It fires on
the host's `after_action_space` event ("each time you use" → after the space's
income), gating the host's Stop until it fires.

Day Laborer is an atomic space, so it must be HOSTED when this card is owned
(`register_action_space_hook`) for the PendingActionSpace frame to surface the
trigger. Played via Lessons; on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md
Category 3 / II.1.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_card_choice_resolver,
)
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "seasonal_worker"
SPACES = frozenset({"day_laborer"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Always mandatory on Day Laborer (the choice, not the firing, is round-gated).
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES)


def _apply(state: GameState, idx: int) -> GameState:
    # Options are round-dependent: grain-only pre-round-6, grain-or-veg from round 6.
    options = ("grain", "veg") if state.round_number >= 6 else ("grain",)
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id="card:seasonal_worker", options=options))


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    p = state.players[idx]
    gain = Resources(grain=1) if chosen == "grain" else Resources(veg=1)
    p = fast_replace(p, resources=p.resources + gain)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return pop(state)   # resolver owns the PendingCardChoice frame


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply, mandatory=True)
register_action_space_hook(CARD_ID, SPACES)   # required so atomic Day Laborer is hosted
register_card_choice_resolver(CARD_ID, _resolve)
