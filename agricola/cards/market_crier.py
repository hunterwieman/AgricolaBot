"""Market Crier (occupation, C142; Consul Dirigens Expansion; players 3+).

Card text: "Each time you use the 'Grain Seeds' action space, you can get an
additional 1 grain and 1 vegetable. If you do, each other player gets 1 grain
from the general supply."

Printed for 3+ players, but the card is well-defined for the 2-player game with
no scaling: "each other player" is exactly the single opponent. No errata or
clarifications.

An OPTIONAL `before_action_space` trigger on the atomic Grain Seeds space — the
same atomic-host shape as Corn Scoop (A67, +1 grain after Grain Seeds), but with
two differences that make it a declinable FireTrigger rather than a forced
automatic effect:

  - It is OPTIONAL, not mandatory. The grant is "you CAN get ... If you do, each
    other player gets 1 grain." Giving the opponent 1 grain is a real downside
    the owner may want to decline (e.g. late game, when handing a rival grain
    matters more than your own extra grain/veg). So it is registered with the
    optional `register` (a declinable FireTrigger, decline = the host's Proceed),
    NOT `register_auto` (mandatory). Corn Scoop, a pure self-grant with no
    downside, is correctly mandatory; Market Crier is not.

  - The self-grant and the opponent-grant are COUPLED. "If you do, each other
    player gets 1 grain" means you cannot take your grain+veg without also giving
    the opponent grain — so both resolve together in the single `_apply` (the
    Milk Jug A50 "other = 1 - idx" two-sided pattern), never as two separable
    choices.

TIMING: a bare "each time you use [space]" (no "immediately after") fires on the
space's `before_action_space` event per the Trigger-Timing ruling. Grain Seeds is
an atomic accumulation space, so its host frame is surfaced only when an owner is
acting (`register_action_space_hook`); the once-per-use semantics come from the
host's `triggers_resolved` guard. There is no resource gate — the grant is a pure
gain for the owner (the opponent's grain is the only "cost", and it is paid from
the general supply, not the owner), so the fire is offered whenever Grain Seeds is
used. No build cost, prerequisite, VPs, or passing.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "market_crier"
SPACES = frozenset({"grain_seeds"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    # Coupled grant: the owner gets +1 grain +1 veg, and (because "if you do")
    # each other player gets +1 grain from the general supply. Both sides resolve
    # together — you cannot take your grain/veg and skip giving the opponent grain.
    other = 1 - idx
    players = list(state.players)
    players[idx] = fast_replace(
        players[idx], resources=players[idx].resources + Resources(grain=1, veg=1))
    players[other] = fast_replace(
        players[other], resources=players[other].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(players))


register_occupation(CARD_ID, lambda state, idx: state)     # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
