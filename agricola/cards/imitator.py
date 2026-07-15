"""Imitator (occupation, deck E #129; Ephipparius Expansion; players 3+).

Card text (verbatim): "If you have a person on the "Day Laborer" action space,
you can use non-accumulating round 1-9 action spaces even if they are occupied."
Category: Actions Booster. No printed VPs.

One mechanism — a LEGALITY RELAXATION on worker placement, registered via
`register_occupancy_override` (the Sleeping Corner / Forest School seam, consulted
by `legality._is_available` ONLY on the occupied branch, so the Family game pays
nothing). The owner may place on an OCCUPIED action space when ALL hold:

- **"you have a person on the 'Day Laborer' action space"** — the owner holds
  >= 1 worker on `day_laborer`.
- **"non-accumulating"** — the space is not an accumulation space
  (`space_id not in constants.ACCUMULATION_SPACES`; the card-game set, which
  already excludes Meeting Place).
- **"round 1-9 action spaces"** — the space is a STAGE (round) card revealed in
  rounds 1–9. `ActionSpaceState.revealed_round` stamps the revealing round
  (permanents get 0, an unrevealed card None), so the test is `1 <= revealed_round
  <= 9` — which naturally excludes the permanents (round 0) and the rounds-10–14
  round spaces. (Rounds 1–9 are exactly stages 1–3, so which of a stage's cards
  fell in which round doesn't matter — all are <= 9.)

Two guards mirror the Sleeping Corner precedent: the current player must hold NO
worker on the target themselves (`workers[ap] == 0` — the relaxation is for
placing onto an OPPONENT's space, not stacking on your own), which in the
occupied branch means exactly that an opponent holds it. Written as a player-side
read so it stays correct under a future 4-player variant.

Card-only (the override registry is empty in the Family game), so the Family game
is byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import ACCUMULATION_SPACES
from agricola.legality import register_occupancy_override
from agricola.state import GameState, get_space

CARD_ID = "imitator"


def _occupancy_override(state: GameState, space_id: str) -> bool:
    """The current player may place on an occupied space iff they own Imitator,
    hold a worker on Day Laborer, the space is a non-accumulating round-1-9 stage
    card, and they do not already occupy it."""
    ap = state.current_player
    if CARD_ID not in state.players[ap].occupations:
        return False
    if space_id in ACCUMULATION_SPACES:                     # "non-accumulating"
        return False
    rr = get_space(state.board, space_id).revealed_round    # "round 1-9"
    if rr is None or not (1 <= rr <= 9):
        return False
    if get_space(state.board, space_id).workers[ap] != 0:   # not one I already hold
        return False
    return get_space(state.board, "day_laborer").workers[ap] >= 1


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_occupancy_override(_occupancy_override)
