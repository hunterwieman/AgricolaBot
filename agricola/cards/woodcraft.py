"""Woodcraft (minor improvement, C58; Corbarius Expansion; players -).

Card text: "Each time you use a wood accumulation space, if immediately
afterward you have at most 5 wood in your supply, you get 1 food."

Prerequisite: 1 Occupation. No spendable cost, no printed VPs, not passing.

Clarification (card JSON): "This effect is checked before cards that trigger
'after', e.g. Tree Guard C102." This only orders Woodcraft ahead of OTHER
after-triggers; it does not change that this is an `after_action_space` effect.

Mechanism. "Each time you use a wood accumulation space, if immediately
afterward you have at most 5 wood ... you get 1 food" is a mandatory,
choice-free income effect → an automatic effect (`register_auto`), not a
declinable FireTrigger. It MUST ride the `after_action_space` event, not
`before_action_space`: the "at most 5 wood" threshold is read AFTER the space's
own wood pickup lands (engine `_apply_proceed` runs the atomic Forest handler,
then `_enter_after_phase` fires the after-autos), so firing before would read
pre-income wood and pay food incorrectly. In the 2-player game the only wood
accumulation space is Forest.

An automatic after-effect fires exactly once per action-space flip, so no
`triggers_resolved` guard is needed (unlike Basket, a declinable conversion).
Played via Lessons / a minor-play space; the on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "woodcraft"

# Wood accumulation spaces this card fires on. 2-player: Forest only (Copse /
# Grove are 3–4-player board-extension spaces, never on the 2-player board).
WOOD_SPACES = frozenset({"forest"})

# "at most 5 wood in your supply" — read AFTER the space's wood income.
_WOOD_THRESHOLD = 5


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at the after_action_space host flip; the top frame is the
    # action-space host, so `space_id` names the space just used and the wood
    # income has already landed.
    top = state.pending_stack[-1]
    return (
        top.space_id in WOOD_SPACES
        and state.players[idx].resources.wood <= _WOOD_THRESHOLD
    )


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(
        state.players[idx],
        resources=state.players[idx].resources + Resources(food=1),
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


# Prereq "1 Occupation" → min_occupations=1. No spendable cost, no VPs, not passing.
register_minor(CARD_ID, cost=Cost(), min_occupations=1)
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_SPACES)
