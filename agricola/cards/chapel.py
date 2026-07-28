"""Chapel (minor improvement, A39; Artifex Expansion; cost 3 wood + 2 clay,
prereq 2 occupations, 3 printed VPs).

Card text: "This is an action space for all. A player who uses it gets 3 bonus
points. If another player uses it, they must first pay you 1 grain."

The first FOR-ALL card action space, and the toll seam's first consumer
(ruling 86, 2026-07-27):

- **"For all"** — either player may place here (`for_all=True`); standard
  occupancy, one worker total per round.
- **The toll** — a non-owner "must first pay you 1 grain": unpayable → the
  placement (or a Straw Hat / Archway arrival — the toll is owed PER USE
  however the worker arrives) is ILLEGAL; payable → the grain transfers
  payer→owner at `engine.initiate_card_space_use`, BEFORE the host push fires
  any before-window effect (ruling 86 item 8: no benefit of the use can fund
  the toll). A plain have-the-grain gate is exact — no at-any-time conversion
  produces grain (contrast the FOOD tolls, which await the raise path). The
  received grain is an OBTAIN for the owner (ruling 86 item 7) — the
  `pay_card_space_toll` transfer is the site that fires the obtain-reactor
  seam when it lands.
- **The action** — the USER (either player) banks 3 bonus points per use, in
  their own `card_state` under the "chapel_bonus" key, scored end-game via
  `register_scoring_any_player` (the ownership-INDEPENDENT scoring list —
  the `_owns`-gated terms cannot score a non-owner's banked points). Always
  carryable, so the owner-side legality check is vacuous here.
"""
from __future__ import annotations

from agricola.cards.card_spaces import register_card_action_space
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring_any_player
from agricola.state import GameState

CARD_ID = "chapel"
_BONUS_KEY = "chapel_bonus"
_POINTS_PER_USE = 3


def _use(state: GameState, placer_idx: int, owner_idx: int, picks) -> GameState:
    """The space's action: the USER banks 3 bonus points (their own store)."""
    p = state.players[placer_idx]
    banked = p.card_state.get(_BONUS_KEY, 0)
    p = fast_replace(p, card_state=p.card_state.set(
        _BONUS_KEY, banked + _POINTS_PER_USE))
    return fast_replace(state, players=tuple(
        p if i == placer_idx else state.players[i]
        for i in range(len(state.players))))


def _score(state: GameState, idx: int) -> int:
    """Each player's own banked Chapel points (0 if they never used it)."""
    return state.players[idx].card_state.get(_BONUS_KEY, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3, clay=2)),
               min_occupations=2, vps=3)
register_card_action_space(
    CARD_ID, _use, for_all=True,
    toll=Cost(resources=Resources(grain=1)))
register_scoring_any_player(CARD_ID, _score)
