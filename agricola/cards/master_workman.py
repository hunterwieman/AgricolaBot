"""Master Workman (occupation, Artifex A126; players 1+).

Card text (verbatim): "Each time before you use an action space card on round
spaces 1/2/3/4, you get 1 wood/clay/reed/stone."

A round space's stage card carries ``ActionSpaceState.revealed_round == N`` — the
round whose preparation revealed it (user decision 2026-07-15, the reveal-order
card family this card belongs to; permanents get 0, unrevealed None). "Round space
N" therefore means exactly the space with ``revealed_round == N``. The reward is
positional: the round-1 space gives wood, round-2 clay, round-3 reed, round-4
stone (``_RESOURCE_BY_ROUND``).

Timing / kind: "Each time BEFORE you use an action space card …" — an explicit
before window, and a mandatory, choice-free, flat good gain → an automatic effect
(``register_auto`` on ``before_action_space``), exactly the Wood Cutter / Corn
Scoop idiom. Eligibility reads the hosted space's ``revealed_round`` off the top
frame's ``space_id``; the apply grants the round's matched resource.

No ``register_action_space_hook`` is needed: the round-1–4 spaces are the four
stage-1 cards (``STAGE_CARDS[1]`` — Major Improvement, Fencing, Grain Utilization,
Sheep Market; stage 1 spans rounds 1–4), and every one of them is a NON-atomic
host that already pushes a ``before_action_space`` frame with a ``space_id`` (Major
Improvement via its ``PendingSubActionSpace`` action-space surface, Fencing / Grain
Utilization / Sheep Market via their own hosts). There is no atomic space among
them to host. Played via Lessons; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "master_workman"

# Round space N -> the resource its use grants (wood/clay/reed/stone for 1/2/3/4).
_RESOURCE_BY_ROUND = {1: "wood", 2: "clay", 3: "reed", 4: "stone"}


def _round_of_current_space(state: GameState) -> int | None:
    """The ``revealed_round`` of the space whose before-window is firing now.

    Consulted only at a ``before_action_space`` host frame, so the top frame is a
    space host exposing ``space_id`` (contract:
    test_all_action_space_host_frames_expose_space_id)."""
    space_id = state.pending_stack[-1].space_id
    return get_space(state.board, space_id).revealed_round


def _eligible(state: GameState, idx: int) -> bool:
    return _round_of_current_space(state) in _RESOURCE_BY_ROUND


def _apply(state: GameState, idx: int) -> GameState:
    resource = _RESOURCE_BY_ROUND[_round_of_current_space(state)]
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(**{resource: 1}))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
