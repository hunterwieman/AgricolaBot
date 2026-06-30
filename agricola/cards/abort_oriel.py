"""Abort Oriel (minor improvement, Corbarius Expansion; deck C #32; players -).

Card text: "You can no longer play this card when any player (including you) has 5
or more cards in front of them."
Clarification: "This card may be played as one's fifth card."

Cost: 2 Clay. Printed 3 VPs (kept-card scoring, handled by the engine via `vps=`).

This is a pure points-provider with a PLAY-time prerequisite and no on-play
effect, no triggers, and no hooks. The 3 VPs are scored automatically from the
spec's `vps` (scoring.py), so there is no `register_scoring` term.

The prerequisite — "no player has 5+ cards in front of them" — turns on two
points the verbatim text makes precise:

- "Cards in front of you" = the played occupations + minor improvements
  (`len(occupations) + len(minor_improvements)`). Built MAJOR improvements are
  tiles, not cards in front, so `major_improvement_owners` is NOT counted.

- The bound is over EVERY player (the text says "any player (including you)"), so
  the opponent reaching 5+ cards also blocks the play.

- The threshold is strict `< 5` (block at >= 5), which exactly realizes the
  clarification "may be played as one's fifth card": the prerequisite is checked
  against the CURRENT state BEFORE this card joins the tableau
  (legality.py -> prereq_met), so a player holding exactly 4 cards in front (and
  no one at 5+) passes the check, and this becomes their 5th card. The next play
  attempt — now with someone at 5 — fails.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "abort_oriel"


def _cards_in_front(player) -> int:
    """Cards played in front of a player: occupations + minor improvements.

    Built major improvements are tiles, not cards, and are not counted."""
    return len(player.occupations) + len(player.minor_improvements)


def _prereq(state: GameState, idx: int) -> bool:
    """Playable iff NO player (including the opponent) currently has 5 or more
    cards in front of them. Strict `< 5`, so a player at exactly 4 may play this
    as their 5th card (the prerequisite reads the pre-play state)."""
    return all(_cards_in_front(p) < 5 for p in state.players)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2)),
    prereq=_prereq,
    vps=3,
)
