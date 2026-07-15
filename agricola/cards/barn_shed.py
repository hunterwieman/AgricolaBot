"""Barn Shed (minor improvement, Ephipparius E66; cost 2 wood; prereq 3 occupations).

Card text (verbatim): "Each time another player (or, in a solo game, you) uses the
'Forest' accumulation space, you get 1 grain."

An opponent-action hook — the Milk Jug idiom — with one twist: it fires only on
ANOTHER player's use of Forest, never the owner's (the "or, in a solo game, you"
clause is for 1-player games; in the 2-player game the owner's own Forest use never
triggers it). Modeled as an ``any_player`` automatic effect (``register_auto`` with
``any_player=True``) on ``before_action_space``, so it runs for its OWNER even on
the other player's turn. Eligibility excludes own use by requiring
``state.current_player != idx`` (idx is the owner; ``current_player`` is the acting
player), giving the "another player" restriction.

Forest is ATOMIC, so ``register_action_space_hook({"forest"}, any_player=True)``
hosts it on EITHER player's turn (the host frame must be pushed on the opponent's
Forest use for the before-window to fire). Fires on the before window per the
standing trigger-timing ruling; the flat +1 grain is independent of Forest's own
output. Played via an improvement space; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "barn_shed"

_HOOK_SPACES = frozenset({"forest"})


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the OWNER (any_player). Fire only when the OTHER player is the one
    # using Forest ("another player") — never the owner's own use.
    return (state.pending_stack[-1].space_id == "forest"
            and state.current_player != idx)


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=3)
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
register_action_space_hook(CARD_ID, _HOOK_SPACES, any_player=True)
