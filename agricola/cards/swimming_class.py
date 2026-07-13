"""Swimming Class (minor improvement, A35; Artifex Expansion; players -).

Card text: "In the returning home phase of each round, if you return a person
from the 'Fishing' accumulation space, you get 2 bonus points for each newborn
that you return home."
Clarification: "If you used Adoptive Parents A092, there is no longer a newborn
to return home."
Cost: 1 Food. Prerequisite: 2 Occupations. No printed VPs (the points are
earned per round). Not passing.

Category: Points Provider. "In the returning home phase" → the round-end
ladder's ``returning_home`` window (ruling 49, 2026-07-12: the returning-home
phase is the round's LAST phase, distinct from and preceding the harvest — so
the effect is UNCONDITIONED on the round kind and fires on harvest rounds too,
before the harvest). That window fires BEFORE the mechanical return-home reset
(the ladder's pre/post-reset boundary — the design the user generalized from
this very card), so the STILL-PLACED BOARD is the event data:

- "if you return a person from the 'Fishing' accumulation space" reads the
  live occupancy of the ``fishing`` space for this player
  (``get_space(board, "fishing").workers[idx] > 0``);
- "each newborn that you return home" reads ``PlayerState.newborns`` — this
  round's family growths, NOT yet cleared at the returning-home phase (they
  clear in the next round's preparation), i.e. exactly the newborns going home
  with everyone else.

"you get" is mandatory and choice-free → an automatic effect (`register_auto`
on the "returning_home" event), never a FireTrigger (ruling 21, 2026-07-05: a
mandatory choice-free effect is an AUTO, never a forced offer). No
immediate-VP mechanism exists, so each fire banks ``2 x newborns`` in the
per-card CardStore counter, read back at end-game by a `register_scoring` term
(the Furniture Carpenter banked-VP idiom); the bank accumulates across rounds.

Adoptive Parents (A092) is UNIMPLEMENTED. Per the printed clarification, a
newborn taken as an adult via Adoptive Parents is no longer a newborn
returning home — when that card is built, it must interact here (its effect
must leave this card's newborn read seeing no newborn).

Played via an improvement space; the play itself is a no-op (the per-round
window effect is the whole card), so on_play stays the default. The "2
Occupations" prerequisite is a ``min_occupations=2`` have-check (NOT a cost);
the 1 Food is the spendable cost.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState, get_space

CARD_ID = "swimming_class"


def _eligible(state: GameState, idx: int) -> bool:
    """At the pre-reset ``returning_home`` window: this player has a person
    still placed on the Fishing accumulation space, and at least one newborn
    is returning home alongside it."""
    return (get_space(state.board, "fishing").workers[idx] > 0
            and state.players[idx].newborns > 0)


def _apply(state: GameState, idx: int) -> GameState:
    """Bank 2 bonus points per returning newborn in the per-card counter."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, banked + 2 * p.newborns))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)),
               min_occupations=2)
register_auto("returning_home", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
