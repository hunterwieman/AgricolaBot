"""Cookery Outfitter (occupation, A101; Artifex Expansion; players 1+).

Card text: "During scoring, you get 1 bonus point for each cooking improvement
you have."

Clarification (errata): "Ovens do not count towards this card." The cooking
improvements that count are therefore the Fireplaces (major-improvement indices
0 and 1) and the Cooking Hearths (indices 2 and 3) ONLY; the Clay Oven (index 5)
and Stone Oven (index 6) do NOT count.

A pure end-game scoring term — no on-play effect (it is still played via Lessons;
its on-play is a no-op). Category 1 (end-game scoring). No stored state — derived
from the major-improvement ownership on the board.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import COOKING_HEARTH_INDICES, FIREPLACE_INDICES
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "cookery_outfitter"

# Cooking improvements that score: Fireplaces + Cooking Hearths only (ovens excluded).
_COOKING_INDICES = FIREPLACE_INDICES + COOKING_HEARTH_INDICES


def _score(state: GameState, idx: int) -> int:
    owners = state.board.major_improvement_owners
    return sum(1 for i in _COOKING_INDICES if owners[i] == idx)


# Pure scoring occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_scoring(CARD_ID, _score)
