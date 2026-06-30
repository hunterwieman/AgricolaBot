"""Flail (minor improvement, C26; Consul Dirigens Expansion; Actions Booster).

Card text: "When you play this card, you immediately get 2 food. Each time you
use the 'Farmland' or 'Cultivation' action space, you can also take a 'Bake
Bread' action."

Cost 1 wood. No prerequisite, no printed VPs, not a passing (traveling) card.

Two distinct effects:

  - On play: a one-time +2 food when the card enters the tableau (the
    ``register_minor(on_play=…)`` hook; the food_basket idiom).
  - Each time you use Farmland or Cultivation: an OPTIONAL granted Bake Bread
    action (the oven_firing_boy idiom). "Each time you use [space]" has no
    "immediately after" qualifier, so by the trigger-timing ruling it fires on
    the ``before_action_space`` event. The bake consumes the player's own grain
    (via a baking improvement), not the space's output, so before vs. after is
    observationally identical — same rationale as Oven Firing Boy.

The granted Bake Bread is OPTIONAL (a declinable ``FireTrigger`` via ``register``,
not ``register_auto``) because a granted sub-action is optional unless the text
says "you must". Eligibility gates on a bake actually being usable
(``_can_bake_bread``: a baking improvement + grain, or a card extension), so it
never grants an unresolvable bake. The text says "a 'Bake Bread' action"
(singular), so the grant fires at most once per space use — enforced by the
``CARD_ID not in triggers_resolved`` guard.

Both Farmland and Cultivation are NON-atomic action spaces whose parent frames
(``PendingSubActionSpace`` with ``space_id == "farmland"`` and
``PendingCultivation``) already host the ``before_action_space`` event and expose
``space_id``, so — unlike Oven Firing Boy's atomic Forest — no
``register_action_space_hook`` is needed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_bake_bread
from agricola.pending import PendingBakeBread, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "flail"
SPACES = frozenset({"farmland", "cultivation"})


def _on_play(state: GameState, idx: int) -> GameState:
    """One-time +2 food when the card is played."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _can_bake_bread(state, state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBakeBread(player_idx=idx, initiated_by_id="card:flail"))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    on_play=_on_play,
)
register("before_action_space", CARD_ID, _eligible, _apply)
