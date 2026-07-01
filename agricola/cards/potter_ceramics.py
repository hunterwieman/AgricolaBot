"""Potter Ceramics (minor improvement, D66; Consul Dirigens Expansion).

Card text (verbatim): "Each time before you take a 'Bake Bread' action, you
can exchange 1 clay for 1 grain."
Clarification: "You must bake if you make this exchange."

Cost: none (free). No prerequisite, no printed VPs, not a passing card.

Effect: each time before a Bake Bread action, the owner MAY exchange exactly
1 clay for 1 grain. Available at most once per Bake Bread action. This is an
OPTIONAL ("you can") exchange, so it is a declinable `register()` FireTrigger
— NOT a mandatory `register_auto` — that fires on the `before_bake_bread`
sub-action event.

The "you must bake if you make this exchange" clarification is satisfied
STRUCTURALLY, not by a separate guard: the swap fires inside a PendingBakeBread
frame, which the host only pushes when a Bake Bread action is being taken, and
that frame's before-phase only exits via CommitBake (Stop appears only in the
after-phase). So "exchange the clay, then walk away without baking" is
impossible — no special handling needed (the same property Hand Truck relies on).

This card was originally implemented as the canonical worked example for the
pending-stack's trigger machinery (it predates the play-card path), so the
trigger + the `_can_bake_bread` extension below already existed. The only
addition to make it a playable, dealable minor is the `register_minor` wiring
at the bottom of this module. It exercises:
  - The trigger registry (TRIGGERS / CARDS) via register().
  - The legality-extension registry via register_bake_bread_extension(),
    which broadens _can_bake_bread to accept "clay >= 1 + baker + Potter
    Ceramics" as a valid baking precondition (the trigger will swap clay
    for grain mid-action), so the owner can take a Bake Bread action even
    at 0 grain in order to first swap for grain and then bake it.
  - The pending-stack's per-frame `triggers_resolved` scoping (Potter
    re-becomes-eligible on every new Bake Bread action because each new
    PendingBakeBread has an empty `triggers_resolved` set) — the "each time"
    semantics.

The card has no on-placement effect, so it does NOT participate in the
"compound card interaction" limitation (see ENGINE_IMPLEMENTATION.md §6 —
card-trigger machinery & deferred design questions). It does its work
entirely through the trigger machinery.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
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


# ---------------------------------------------------------------------------
# Playable-minor wiring
# ---------------------------------------------------------------------------
# Free, no prerequisite, not a passing card, 0 printed VPs (the card data has
# cost / prereq / vps / passing_left all null → every register_minor default).
# Makes Potter Ceramics dealable + playable; its effect rides on the trigger above.
register_minor(CARD_ID)
