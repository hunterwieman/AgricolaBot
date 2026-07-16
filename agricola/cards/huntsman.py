"""Huntsman (occupation, B147; Bubulcus Expansion; players 3+).

Card text (verbatim): "Each time after you use a wood accumulation space, you can
pay 1 grain to get 1 wild boar."
No cost / prerequisite / passing / printed VPs.

TIMING — "Each time AFTER you use ..." names the after window explicitly → an
``after_action_space`` trigger. In the 2-player engine the only wood
accumulation space is Forest (Copse / Grove / 3-Hollow are 3–4-player
board-extension spaces, never on the 2-player board — the Wood Cutter note),
so the trigger is filtered to ``space_id == "forest"``. Forest is an atomic
accumulation space, so ``register_action_space_hook`` hosts it (the Angler
idiom) — the ``after_action_space`` frame the trigger attaches to only exists
once this card is owned.

FIRING KIND — "you can pay 1 grain" is OPTIONAL → an optional trigger
(``register``, not ``register_auto``); not firing is the host's Stop. Once per
use via the host frame's ``triggers_resolved``.

THE EFFECT — pay 1 grain, get 1 wild boar. Paying grain (not food) needs no
liquidation path — eligibility requires >= 1 grain. The boar is handed over
through ``helpers.grant_animals`` (add + flag), so an over-capacity grant
reconciles through the accommodation barrier at the next decision boundary (the
Game Trade immediate-grant idiom); never a raw ``p.animals + ...``.

Card-game only (ownership-gated registries; grant_animals' card-only flag is
default-skipped): the Family game is byte-identical and the C++ gates are
untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "huntsman"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if getattr(state.pending_stack[-1], "space_id", None) not in WOOD_ACCUMULATION_SPACES:
        return False
    return state.players[idx].resources.grain >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(grain=1))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return grant_animals(state, idx, Animals(boar=1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
