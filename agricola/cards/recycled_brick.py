"""Recycled Brick (minor improvement, D77; Dulcinaria Expansion; Building Resource Provider).

Card text: "Each time any player (including you) renovates to stone, you get 1 clay
for each newly renovated room."
Cost: 1 Food. Prerequisite: 3 Occupations. 0 VPs. Kept (not traveling).

A mandatory, choice-free payout keyed on a renovation whose TARGET is stone → an
AUTOMATIC effect (`register_auto`), never a FireTrigger (ruling 21, 2026-07-05: a
mandatory choice-free effect is an AUTO).

Timing — `after_renovate` (the after-window of the House-/Farm-Redevelopment
renovate host). This is an OUTCOME-dependent read, so the after phase is correct per
the flat-vs-outcome rule (CARD_AUTHORING_GUIDE.md §2): a renovate's TARGET material is
only knowable post-application (the Roughcaster precedent — a `before_renovate` read
cannot tell a clay->stone renovate apart from a wood->clay one). At `after_renovate`
the renovating player's ``house_material`` reads STONE exactly when the renovation
targeted stone (clay->stone, or a Conservator-extended wood->stone renovate — its
target IS stone, so it counts too). A wood->clay renovate leaves the house CLAY, so
eligibility is False and nothing is paid.

"Any player (including you)" → `any_player=True`, so the effect fires for its OWNER on
EITHER player's renovate (Twibil is the first any_player sub-action auto and the
template; owner routing lives in `apply_auto_effects`). The RENOVATING player is the
top frame's (`PendingRenovate`) ``player_idx`` — the frame is still on top, flipped to
``phase="after"``, when the auto fires (`_enter_after_phase`). The BENEFICIARY is the
auto's ``owner_idx`` (the ``idx`` handed to the eligibility / apply fns). They MAY
differ: on the opponent's renovate, ``top.player_idx`` is the opponent while ``idx`` is
this card's owner. So the renovation outcome (house material, room count) is read from
the RENOVATOR (``top.player_idx``); the clay is granted to the OWNER (``idx``).

"1 clay for each newly renovated room" — a renovation renovates ALL of the renovator's
rooms at once (rooms always share the current house material), so "newly renovated
room" = every room in the renovator's house. The payout is therefore 1 clay per ROOM
cell on the renovator's farmyard. Clay is a raw resource (a direct add, no animal
accommodation needed).

Played via a minor-improvement entry point; on_play is a no-op (the hook is the whole
card). Card-only registries are empty in the Family game (no cards owned), so the
Family game is byte-identical and the C++ differential gates are untouched. Mirrors
twibil.py (the `any_player=True` sub-action auto + owner routing) and roughcaster.py /
roof_ladder.py (the `after_renovate` grant).
"""
from __future__ import annotations

from agricola.cards.specs import _noop_on_play, register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType, HouseMaterial
from agricola.pending import PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "recycled_brick"


def _renovator_idx(state: GameState) -> int | None:
    """The renovating player: the top frame is the `PendingRenovate` host (flipped to
    its after-phase), whose ``player_idx`` is the renovator. Returns None if the top
    frame is not a renovate host (defensive — `after_renovate` only fires with one on
    top)."""
    if not state.pending_stack:
        return None
    top = state.pending_stack[-1]
    if not isinstance(top, PendingRenovate):
        return None
    return top.player_idx


def _room_count(player) -> int:
    """Number of ROOM cells on the player's farmyard grid (mirrors scoring.py)."""
    grid = player.farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _eligible(state: GameState, idx: int) -> bool:
    """`idx` is the OWNER (any_player). Fire whenever the current renovation targeted
    STONE — read from the RENOVATOR (the renovate host's ``player_idx``), which post-
    application has ``house_material == STONE`` exactly for a renovate-to-stone."""
    rnv = _renovator_idx(state)
    if rnv is None:
        return False
    return state.players[rnv].house_material == HouseMaterial.STONE


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the OWNER (`idx`) 1 clay per room of the RENOVATOR's house — every room
    was just renovated to stone."""
    rnv = _renovator_idx(state)
    if rnv is None:                       # defensive; eligibility already gated it
        return state
    n = _room_count(state.players[rnv])
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),   # printed cost: 1 food
    min_occupations=3,                         # prerequisite: 3 occupations
    on_play=_noop_on_play,                     # no on-play effect
)
register_auto("after_renovate", CARD_ID, _eligible, _apply, any_player=True)
