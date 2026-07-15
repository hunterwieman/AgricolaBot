"""Foreign Aid (minor improvement, D50; Consul Dirigens Expansion; Food Provider).

Card text (verbatim): "When you play this card, you immediately get 6 food. You
may no longer use the action spaces of rounds 12 to 14."

Cost: none (free). Printed VPs: 0. Prerequisite: "Play in Round 11 or Before".
Not passing. Category: Food Provider.

TWO EFFECTS:

1. ON PLAY — +6 food immediately (the standard player-edit idiom; no decision).

2. A STANDING PROHIBITION — the owner "may no longer use the action spaces of
   rounds 12 to 14". A stage card revealed for round N carries
   ``ActionSpaceState.revealed_round == N`` (user decision 2026-07-15; permanents
   get 0 at setup, unrevealed get None), so ``revealed_round in {12, 13, 14}``
   names exactly the rounds-12–14 stage spaces and never touches permanents
   (Meeting Place, Day Laborer, the accumulation spaces stay usable — the owner
   is never stranded). The prohibition rides the subtractive placement seam
   ``register_placement_forbid``: ``_forbid(state, owner_idx, space_id) -> True``
   DROPS that space from ``owner_idx``'s legal placements. The predicate
   self-gates on Foreign Aid ownership, so the Family game and every non-owner
   pay nothing and stay byte-identical.

PREREQUISITE — "Play in Round 11 or Before" is a HAVE-check at play time
(``state.round_number <= 11``), never spent. It stops the card from being played
in rounds 12–14, where its own prohibition would already forbid the just-revealed
spaces (the printed restriction, encoded straight).

Card-only state is empty (no CardStore use), and the placement-forbid registry is
empty in the Family game, so the Family game is byte-identical and the C++ gates
are untouched (``legal_actions`` filtering is not part of the differential
contract). See CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.legality import register_placement_forbid
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "foreign_aid"

# The rounds whose action spaces the owner may no longer use.
_FORBIDDEN_ROUNDS = frozenset({12, 13, 14})


def _prereq(state: GameState, idx: int) -> bool:
    """"Play in Round 11 or Before" — a HAVE-check at play time, never spent."""
    return state.round_number <= 11


def _on_play(state: GameState, idx: int) -> GameState:
    """+6 food immediately (the standard player-edit idiom)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=6))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _forbid(state: GameState, owner_idx: int, space_id: str) -> bool:
    """Forbid the owner any action space revealed for rounds 12/13/14. Self-gates
    on Foreign Aid ownership so non-owners (and the whole Family game) are
    untouched; permanents (``revealed_round == 0``) and unrevealed spaces
    (``revealed_round is None``) are never in the set, so they stay placeable."""
    if CARD_ID not in state.players[owner_idx].minor_improvements:
        return False
    return get_space(state.board, space_id).revealed_round in _FORBIDDEN_ROUNDS


# Cost null -> free; prereq "Play in Round 11 or Before"; vps 0.
register_minor(CARD_ID, prereq=_prereq, vps=0, on_play=_on_play)
register_placement_forbid(_forbid)
