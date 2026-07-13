"""Early Cattle (minor improvement, C83; Corbarius Expansion; players -).

Card text: "When you play this card, you immediately get 2 cattle."
Cost: none. Prerequisite: 1 Pasture. Printed VPs: -3. Not passing.

Category 2 (on-play one-shot animal gain). The 2 cattle are granted via
``helpers.grant_animals`` — the single choke point for decision-free card animal
gains (Young Animal Market, Haydryer, Game Trade): the cattle are added even if
they exceed housing capacity, and the engine's accommodation barrier
(``engine._reconcile_accommodation``, run at every decision boundary) surfaces
the keep-or-cook choice if they don't fit.

The "1 Pasture" prerequisite is a HAVE-check on the BFS-derived enclosed-pasture
decomposition (``farmyard.pastures``) — a pasture is not its own ``CellType``,
so the check is ``len(farmyard.pastures) >= 1`` (the Blade Shears shape). The
printed -3 VPs ride ``MinorSpec.vps`` (negative printed VPs are supported —
Brewery Pond / Cesspit precedent) and are summed at scoring like any kept minor.

Per the user (2026-07-13), the "immediately" wording carries no special timing —
it just says the on-play effect resolves before the ``after_play_minor`` window,
which is true of every instant card effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.helpers import grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "early_cattle"


def _prereq(state: GameState, idx: int) -> bool:
    """Playable iff the player has at least one enclosed pasture."""
    return len(state.players[idx].farmyard.pastures) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Gain 2 cattle (via grant_animals, so the accommodation barrier handles
    cattle that don't fit)."""
    return grant_animals(state, idx, Animals(cattle=2))


register_minor(CARD_ID, prereq=_prereq, vps=-3, on_play=_on_play)
