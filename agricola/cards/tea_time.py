"""Tea Time (minor improvement, E3; Ephipparius Expansion; traveling).

Card text (verbatim): "Immediately return your person on the "Grain
Utilization" action space home; you can place it again later this round."
Cost: 1 Food. Prerequisite: Own Person on "Grain Utilization". No printed
VPs; PASSING (traveling, passing_left) — after the immediate effect it is
passed to the opponent, never kept in the tableau.

USER RULING (2026-07-20): the vacated space is OPEN — what makes a space
illegal to place on is the presence of a worker on it, nothing else; there
is no residual "used this round" block. After the return, EITHER player may
legally place on Grain Utilization again this round.

MECHANICS. The prerequisite reads the Grain Utilization space's per-player
worker count (the owner's entry must be >= 1). The on_play is MANDATORY
("Immediately return"): remove the owner's person from the space (a board
edit — rebuild the space with one fewer worker for the owner) and put that
person back in the owner's `people_home` (+1). The second clause — "you can
place it again later this round" — is permission to reuse and needs NO code:
a person in `people_home` re-enters the normal work-phase alternation
automatically, and (per the ruling above) the vacated space is placeable
again by either player because placement legality is solely worker-presence
(`_is_available`: revealed + unoccupied).

Card-game only (spec-registry gated; no new engine state), so the Family
trace and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "tea_time"
_SPACE = "grain_utilization"


def _own_person_on_grain_utilization(state: GameState, idx: int) -> bool:
    """Prerequisite: Own Person on "Grain Utilization" — the owner has a
    worker on that space right now."""
    return get_space(state.board, _SPACE).workers[idx] >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Mandatory immediate effect: return the owner's person on the Grain
    Utilization space home (board worker off; people_home +1)."""
    sp = get_space(state.board, _SPACE)
    workers = tuple(
        n - 1 if i == idx else n for i, n in enumerate(sp.workers))
    state = fast_replace(
        state,
        board=with_space(state.board, _SPACE,
                         fast_replace(sp, workers=workers)))
    p = state.players[idx]
    p = fast_replace(p, people_home=p.people_home + 1)
    return fast_replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    prereq=_own_person_on_grain_utilization,
    passing_left=True,
    on_play=_on_play,
)
