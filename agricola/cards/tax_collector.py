"""Tax Collector (occupation, deck E #126; Ephipparius Expansion; players 1+).

Card text: "Once you live in a stone house, at the start of each round, you get
your choice of 2 wood, 2 clay, 1 reed, or 1 stone."

Category 7 (start-of-round phase hook), the MANDATORY-WITH-CHOICE firing kind
(II.1), mirroring Childless: "you get" makes the income not declinable, but it
carries a choice of which goods, so it is a `mandatory`-tagged trigger on the
preparation ladder's `start_of_round` window (ruling 54, 2026-07-14 —
`agricola/cards/preparation.py`) rather than a plain automatic effect. "Once you
live in a stone house" is a STANDING condition checked each round (the same
printed formula as Scholar / Plow Driver), not a one-shot: renovate to stone and
it starts firing; it fires EVERY round thereafter. While eligible and unfired it
gates the window choice host's Proceed; firing pushes a PendingCardChoice over
the four printed options, and the resolver grants exactly the chosen goods and
pops the choice frame — the gate then reopens. Once-per-round is carried by the
host frame's `triggers_resolved` (the frame is fresh each round's window visit).
On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_card_choice_resolver,
)
from agricola.constants import HouseMaterial
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "tax_collector"

# The four printed options, in printed order. The option string doubles as the
# web-UI label ("Choose: 2 wood").
_OPTIONS = ("2 wood", "2 clay", "1 reed", "1 stone")
_GRANTS = {
    "2 wood": Resources(wood=2),
    "2 clay": Resources(clay=2),
    "1 reed": Resources(reed=1),
    "1 stone": Resources(stone=1),
}


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.players[idx].house_material is HouseMaterial.STONE)


def _apply(state: GameState, idx: int) -> GameState:
    # Push the forced pick over the four printed options; the fire is already
    # stamped into the host frame's triggers_resolved, so the Proceed gate
    # reopens once the choice resolves.
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id="card:tax_collector",
        options=_OPTIONS))


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _GRANTS[chosen])
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return pop(state)   # resolver owns the PendingCardChoice frame


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply, mandatory=True)
register_card_choice_resolver(CARD_ID, _resolve)
