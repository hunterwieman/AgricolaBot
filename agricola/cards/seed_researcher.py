"""Seed Researcher (occupation, C97; Corbarius Expansion; players 1+).

Card text (verbatim): "Each time any people return from both the \"Grain Seeds\"
and \"Vegetable Seeds\" action spaces, you get 2 food and you can play 1
occupation, without paying an occupation cost."

WHEN IT FIRES — at the returning-home moment of a round in which BOTH the
Grain Seeds and Vegetable Seeds action spaces are occupied. "Any people": one
worker on each space, no matter WHOSE workers they are (the owner's, the
opponent's, or one of each) — the card cares that people return from both
spaces, not that they are the owner's. The engine's home for this is the
round-end ladder's ``returning_home`` window (user ruling 49, 2026-07-12: the
returning-home phase is the round's LAST phase, a distinct rung of the
round-end ladder; ``agricola/cards/round_end.py``). That window fires
PRE-reset — the still-placed board is the event data (the generalized Swimming
Class design) — so eligibility reads live occupancy directly:
``get_space(board, sid).workers != (0, 0)`` for both spaces. Vegetable Seeds
is a Stage 3 round card; a worker can only be on it once it is revealed, so
occupancy subsumes the reveal check.

TWO REGISTRATIONS (one card text, two firing kinds):

- "you get 2 food" is mandatory and choice-free -> an AUTOMATIC effect
  (`register_auto` on "returning_home"; ruling 21, 2026-07-05: a mandatory
  choice-free effect is an auto, never a forced offer). It pays the card's
  OWNER — the opponent's worker may be what qualifies the fire, but the
  opponent gets nothing.
- "you can play 1 occupation, without paying an occupation cost" is an
  OPTIONAL grant -> a FireTrigger (`register` on "returning_home"). Firing
  pushes ``PendingPlayOccupation(cost=Resources())`` — the empty cost, so
  `_execute_play_occupation` debits nothing and the occupation plays FREE
  (the Scholar / Forestry Studies precedent for a non-Lessons free play).
  Because the pushed frame's enumerator offers a CommitPlayOccupation per
  playable hand occupation with no decline of its own, eligibility gates on
  ``playable_occupations`` being non-empty — never a dead-end fire. Declining
  IS not firing: the window host's Proceed exits (optionality lives at the
  host; no SkipTrigger).

"Each time" — once per qualifying round, enforced for free by the window
frame's ``triggers_resolved`` (a fresh frame each round), and the auto fires
once per round because the window is walked once per round. Fires on harvest
rounds too (the returning-home phase precedes the harvest; the text carries no
round condition). No on-play effect; hand-only copies are inert (ownership is
gated by the registries' `_owns`).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_auto
from agricola.legality import playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "seed_researcher"

_SPACES = ("grain_seeds", "vegetable_seeds")


def _both_occupied(state: GameState) -> bool:
    """"Any people return from both ... spaces": at the pre-reset
    returning_home window, each of the two spaces holds a worker — ANY
    player's (occupancy is the whole test; an unrevealed Vegetable Seeds can
    hold no worker, so no separate reveal check is needed)."""
    return all(
        get_space(state.board, sid).workers != (0, 0) for sid in _SPACES)


def _auto_eligible(state: GameState, idx: int) -> bool:
    return _both_occupied(state)


def _grant_food(state: GameState, idx: int) -> GameState:
    """"you get 2 food" — to the card's OWNER (whoever's workers qualified)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _trigger_eligible(state: GameState, idx: int, _resolved) -> bool:
    """The free occupation play: both spaces occupied AND a playable hand
    occupation exists to spend it on (never a dead-end fire). Once-per-round
    is the window frame's `triggers_resolved` (filtered centrally)."""
    return _both_occupied(state) and bool(playable_occupations(state, idx))


def _push_free_play(state: GameState, idx: int) -> GameState:
    """Play 1 occupation for free — cost=Resources() (the empty cost), so
    `_execute_play_occupation` debits nothing ("without paying an occupation
    cost")."""
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", cost=Resources()))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("returning_home", CARD_ID, _auto_eligible, _grant_food)
register("returning_home", CARD_ID, _trigger_eligible, _push_free_play)
