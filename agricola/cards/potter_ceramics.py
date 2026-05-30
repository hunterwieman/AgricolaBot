"""Potter Ceramics (minor improvement).

Effect: Each time before a Bake Bread action, the owner may exchange
exactly 1 clay for 1 grain. Available at most once per Bake Bread action.

Task 5 implements this card as the canonical worked example for the
pending-stack's trigger machinery. It exercises:
  - The trigger registry (TRIGGERS / CARDS) via register().
  - The legality-extension registry via register_bake_bread_extension(),
    which broadens _can_bake_bread to accept "clay >= 1 + baker + Potter
    Ceramics" as a valid baking precondition (the trigger will swap clay
    for grain mid-action).
  - The pending-stack's per-frame `triggers_resolved` scoping (Potter
    re-becomes-eligible on every new Bake Bread action because each new
    PendingBakeBread has an empty `triggers_resolved` set).

The card has no on-placement effect, so it does NOT participate in the
"compound card interaction" limitation (see ENGINE_IMPLEMENTATION.md §6 —
card-trigger machinery & deferred design questions). It does its work
entirely through the trigger machinery.
"""
from __future__ import annotations

import dataclasses

from agricola.cards.triggers import register
from agricola.legality import register_bake_bread_extension, _owns_baker
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState


CARD_ID = "potter_ceramics"


# ---------------------------------------------------------------------------
# Trigger: fires "before_bake_bread" each Bake Bread action
# ---------------------------------------------------------------------------

def _eligible(state: GameState, player_idx: int, triggers_resolved: frozenset) -> bool:
    """Whether Potter Ceramics can fire its before-Bake-Bread trigger now.

    Conditions:
      - Has not already fired this Bake Bread action.
      - Player has played the card.
      - Player has at least 1 clay to exchange.
    """
    if CARD_ID in triggers_resolved:
        return False
    p = state.players[player_idx]
    if CARD_ID not in p.minor_improvements:
        return False
    return p.resources.clay >= 1


def _apply(state: GameState, player_idx: int) -> GameState:
    """Apply the trigger: -1 clay, +1 grain."""
    p = state.players[player_idx]
    new_resources = p.resources + Resources(clay=-1, grain=1)
    new_player = fast_replace(p, resources=new_resources)
    new_players = tuple(
        new_player if i == player_idx else state.players[i]
        for i in range(2)
    )
    return fast_replace(state, players=new_players)


# Register the trigger with the event-keyed and card-id-keyed registries.
register(
    event="before_bake_bread",
    card_id=CARD_ID,
    eligibility_fn=_eligible,
    apply_fn=_apply,
)


# ---------------------------------------------------------------------------
# _can_bake_bread extension
# ---------------------------------------------------------------------------

def _can_bake_bread_extension(state: GameState, p: PlayerState) -> bool:
    """Broaden _can_bake_bread: a player who owns Potter Ceramics + a baker
    can bake even with 0 grain, provided they have at least 1 clay (the
    trigger will swap clay for grain).
    """
    if CARD_ID not in p.minor_improvements:
        return False
    if p.resources.clay < 1:
        return False
    return _owns_baker(state, p)


register_bake_bread_extension(_can_bake_bread_extension)
