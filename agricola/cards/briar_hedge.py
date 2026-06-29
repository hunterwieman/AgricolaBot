"""Briar Hedge (minor improvement, E16; Ephipparius; players -).

Card text: "You do not need to pay wood for fences that you build on the edge of your
farmyard board."
Clarification: "You must still use your fence pieces."
Prerequisite: 1 Animal of Each Type (>= 1 sheep, >= 1 wild boar, >= 1 cattle to PLAY it).

A POSITIONAL per-edge free-fence card (COST_MODIFIER_DESIGN.md §9.4 source 1): every NEW
fence edge that lies on the board's outer boundary costs no wood. The board-edge fence
bitmaps (`PERIMETER_H_BM` / `PERIMETER_V_BM` in `fences.py`) intersected with the pasture's
new edges (`h_new` / `v_new`) are exactly those free edges. The discount is UNGATED — "fences
that you build on the edge" names no action or entry point, so it applies to ANY fence build
(the literal Build Fences action AND card-effect builds), hence the edge_fn ignores
`initiated_by_id` / `build_fences_action`.

"You must still use your fence pieces" — positional frees waive only the WOOD, never the fence
PIECE; the engine's piece-supply check (`new_count > fences_left`) is on the full edge count
regardless of frees (§9.7), so this clarification is already honored by construction.

The prerequisite is a PLAY-time HAVE-check (never spent), distinct from the cost; the EFFECT
applies whenever the card is owned, independent of current animals. No play cost, no on-play
effect. Card-only state (an empty positional registry in the Family game), so the Family game
is byte-identical and the C++ gates are untouched. See COST_MODIFIER_DESIGN.md §9.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_free_fence_edges
from agricola.cards.specs import register_minor
from agricola.fences import PERIMETER_H_BM, PERIMETER_V_BM

CARD_ID = "briar_hedge"


def _prereq_one_of_each_animal(state, idx: int) -> bool:
    a = state.players[idx].animals
    return a.sheep >= 1 and a.boar >= 1 and a.cattle >= 1


def _free_edges(farmyard, h_new: int, v_new: int, **_kw):
    """The board-perimeter subset of this pasture's new edges (ungated)."""
    return (h_new & PERIMETER_H_BM, v_new & PERIMETER_V_BM)


register_minor(CARD_ID, prereq=_prereq_one_of_each_animal)
register_free_fence_edges(CARD_ID, _free_edges)
