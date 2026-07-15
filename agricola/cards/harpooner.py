"""Harpooner (occupation, A138; Base Revised; players 3+).

Card text (verbatim): "Each time you use the 'Fishing' accumulation space you
can also pay 1 wood to get 1 food for each person you have, and 1 reed"
No cost / prerequisite / passing / printed VPs.

TIMING — "Each time you use ... you can also ..." → the trigger-timing ruling
puts a bare "each time you use [space]" in the BEFORE window of the space
(before_action_space). The reward is FLAT — 1 food per person plus 1 reed, none
of it reading what the Fishing take produced — so before is correct (an
after-window is only for rewards that must read the action's output/target).
Fishing is an atomic accumulation space, so ``register_action_space_hook`` hosts
it (Wood Cutter / Angler idiom) — the ``before_action_space`` frame the trigger
attaches to only exists once this card is owned.

FIRING KIND — "you can also pay 1 wood" is OPTIONAL → an optional trigger
(``register``, not ``register_auto``); not firing is the host's own Proceed. Once
per use via the host frame's ``triggers_resolved``.

THE EFFECT — pay 1 wood; gain (people_total food + 1 reed). "each person you
have" is the player's family size, ``people_total`` (placed and home members
alike). Paying wood (not food) needs no liquidation path: eligibility simply
requires >= 1 wood. The wood is not a resource the Fishing take needs, so firing
before the take strands nothing.

Card-game only (ownership-gated registries): the Family game is byte-identical
and the C++ gates are untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "harpooner"
_SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per Fishing use
        return False
    if getattr(state.pending_stack[-1], "space_id", None) not in _SPACES:
        return False
    return state.players[idx].resources.wood >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(
        wood=-1, food=p.people_total, reed=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _SPACES)
