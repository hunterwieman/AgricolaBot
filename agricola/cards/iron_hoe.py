"""Iron Hoe (minor improvement, E20; Ephipparius Expansion; Farm Planner).

Card text (verbatim): "At the end of each work phase, if you occupy both the
"Grain Seeds" and "Vegetable Seeds" action spaces, you can plow 1 field."
Cost: 1 Wood. No prerequisite. No printed VPs.

TIMING — "at the end of each work phase" is the round-end ladder's
``end_of_work`` rung (user ruling, 2026-07-14, recorded in
``agricola/cards/round_end.py``: position 0 — still DURING the work phase,
running once every worker is placed; the same rung Master Renovator uses). It
fires PRE-reset, so the live board — every worker still on its space — is the
event data, exactly as the ladder's ``returning_home`` design intends.

THE CONDITION — "if you occupy both the 'Grain Seeds' and 'Vegetable Seeds'
action spaces": the owner has a worker on BOTH spaces right now. Read straight
off the still-placed board (``get_space(board, sid).workers[idx] > 0`` — the
Heirloom occupancy idiom); this is readable only because ``end_of_work``
precedes the return-home reset that clears placements.

THE GRANT — "you can plow 1 field" is an OPTIONAL trigger ("you can"; a granted
sub-action is optional even when worded plainly): firing pushes a standard
single ``PendingPlow`` with this card's provenance. Declining is the window's
``Proceed`` (no SkipTrigger). Once-per-window comes from the frame's
``triggers_resolved``. Eligibility also requires a legal plow target
(``_can_plow``) so the grant is never a dead-end.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "iron_hoe"
_SEED_SPACES = ("grain_seeds", "vegetable_seeds")


def _occupies_both_seed_spaces(state: GameState, idx: int) -> bool:
    """The owner has a worker on BOTH Grain Seeds and Vegetable Seeds — read
    off the still-placed board (``end_of_work`` is pre-reset)."""
    return all(
        get_space(state.board, sid).workers[idx] > 0 for sid in _SEED_SPACES
    )


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """Both seed spaces occupied by the owner AND a legal plow exists (never a
    dead-end). Ownership is the window machinery's gate; once-per-window is the
    frame's ``triggers_resolved``."""
    return (
        _occupies_both_seed_spaces(state, idx)
        and _can_plow(state.players[idx])
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Push the granted plow ("without placing a person" is inherent — the
    window trigger involves no worker)."""
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))

# The optional plow on the round-end ladder's end_of_work rung, gated on the
# owner occupying both seed spaces (read pre-reset).
register("end_of_work", CARD_ID, _eligible, _apply)
