"""Mantlepiece (minor improvement, B33; Base Revised; cost 1 Stone).

Card text: "When you play this card, you immediately get 1 bonus point for each
complete round left to play. You may no longer renovate your house."
Prerequisite: Clay or Stone House. Printed VPs: -3.

On play: bank `14 − round_number` bonus points in CardStore (the same pattern as Big
Country); a scoring term reads them back at end-game. The renovation prohibition is
enforced in `_can_renovate` (legality.py) by checking card ownership — no extra state
needed, since ownership is permanent and already on PlayerState.

"Complete rounds left to play" — the current round is in progress, so the count is
14 − round_number (0 if played in round 14). Same semantics as Big Country.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "mantlepiece"


def _prereq(state: GameState, idx: int) -> bool:
    return state.players[idx].house_material in (HouseMaterial.CLAY, HouseMaterial.STONE)


def _complete_rounds_left(state: GameState) -> int:
    return 14 - state.round_number


def _on_play(state: GameState, idx: int) -> GameState:
    n = _complete_rounds_left(state)
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=1)),
    prereq=_prereq,
    vps=-3,
    on_play=_on_play,
)
register_scoring(CARD_ID, _score)
# "You may no longer renovate" — the renovate-forbid registry (legality) drives
# _legal_renovate_targets to [] for the owner (was a hardcoded check in _can_renovate).
from agricola.legality import register_renovate_forbid  # noqa: E402
register_renovate_forbid(CARD_ID)
