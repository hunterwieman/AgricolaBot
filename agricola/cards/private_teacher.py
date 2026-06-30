"""Private Teacher (occupation, C131; Corbarius Expansion; players 3+).

Card text: "Each time you use the \"Grain Seeds\" action space when any \"Lessons\"
action space is occupied, you can also play an occupation for an occupation cost of
1 food."

Clarification (verbatim): "If the played occupation has an effect when using
\"Grain Seeds\", it also triggers immediately."

Category 4 (action-space hook). "Each time you use [space]" is the Trigger-Timing
ruling for `before_action_space`: the grant is offered BEFORE Grain Seeds' own
effect resolves (a board read — is Lessons occupied? — is not "immediately after"),
and is OPTIONAL/declinable ("you can also play") so it is an ordinary `register`
trigger whose decline is the host's Proceed.

Grain Seeds is an atomic space, so it is given a host frame via
`register_action_space_hook` — without it no `PendingActionSpace` would be pushed
and there would be nothing to fire on.

The gate is the occupancy of a DIFFERENT space (Lessons), not Grain Seeds' own
state: read `get_space(board, "lessons").workers` directly. In the 2-player card
game there is exactly one Lessons space and the firing player is the worker on Grain
Seeds, so it is the opponent's worker on Lessons that makes the trigger live.
(`_is_available` is NOT used — that would require `revealed` and respect the
occupancy-override path, which is the wrong question here; we just want "is any
worker on Lessons.")

Firing pushes the existing `PendingPlayOccupation` primitive with a flat 1-food
cost — the same play-card pending Lessons/Scholar use, so no new sub-decision
machinery. Eligibility additionally gates on a playable, payable occupation actually
existing (`playable_occupations` + `_payable_occupation`, liquidation-aware), so the
trigger is never offered as a dead end. The flat 1-food cost rides on the frame
(`cost`); `_execute_play_occupation` reads and debits it.

The clarification needs no special handling: because we fire `before_action_space`
(BEFORE Grain Seeds' grain take resolves) and any occupation the player then plays
registers its own `before_action_space` hook, the host's trigger loop re-polls the
same Grain Seeds frame and surfaces that new occupation's effect automatically.

Played via Lessons; on-play is a no-op. Card-only state (all registries empty in the
Family game) → byte-identical Family game / untouched C++ gates. See
assistant_tiller.py (the atomic-space `before_action_space` grant template),
scholar.py (the PendingPlayOccupation(cost=1 food) play-card push + the
playable/payable gate), and forest_school.py (the cross-space Lessons occupancy read).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _payable_occupation, playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "private_teacher"
SPACES = frozenset({"grain_seeds"})
_OCC_COST = Resources(food=1)   # Private Teacher's flat occupation cost


def _lessons_occupied(state: GameState) -> bool:
    """Is any worker on a Lessons action space? A direct board read (not
    `_is_available`): in 2p the lone Lessons space is occupied iff the opponent has a
    worker there while the firing player is on Grain Seeds."""
    return get_space(state.board, "lessons").workers != (0, 0)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _lessons_occupied(state)
            and bool(playable_occupations(state, idx))
            and _payable_occupation(state, idx, state.players[idx], _OCC_COST))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id="card:private_teacher", cost=_OCC_COST))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
