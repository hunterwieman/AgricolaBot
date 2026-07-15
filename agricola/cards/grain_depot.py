"""Grain Depot (minor improvement, B65; Bubulcus Expansion; Crop Provider).

Card text (verbatim): "If you paid wood/clay/stone for this card, place 1 grain on
each of the next 2/3/4 round spaces. At the start of these rounds, you get the
grain."
Cost: 2 Wood / 2 Clay / 2 Stone (an ALTERNATIVE cost — pay ONE). Prerequisite:
none. VPs: none. Not passing.

The REWARD is COUPLED to which alternative you paid — the slash-correlation rule
(RULES.md "Slashes / respectively"): wood -> next 2 round spaces, clay -> next 3,
stone -> next 4. This is a real alternative COST (it must stay cost-modifier-
visible), so — exactly like Canvas Sack C40 — the card uses the `alt_costs` path
with `cost_labels`: the three ways to pay are
`(Cost(wood=2), Cost(clay=2), Cost(stone=2))` labeled `("wood", "clay", "stone")`,
each surfaced as its own `CommitPlayMinor` through `effective_payments`, and the
chosen label is threaded into the 3-arg on_play, which schedules the matching
number of grain onto the NEXT N round spaces (R+1..R+N of `future_resources`).
`schedule_resources` clamps to the 1..14 range, so late-game plays silently drop
out-of-range round spaces. (A play-variant surcharge would BYPASS cost modifiers —
wrong here, where the slash is a genuine cost, not an effect price.)
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "grain_depot"

# paid resource -> how many of the next round spaces get 1 grain.
_ROUNDS_FOR = {"wood": 2, "clay": 3, "stone": 4}


def _on_play(state: GameState, idx: int, which: str) -> GameState:
    R = state.round_number
    n = _ROUNDS_FOR[which]
    return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(grain=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    alt_costs=(Cost(resources=Resources(clay=2)), Cost(resources=Resources(stone=2))),
    cost_labels=("wood", "clay", "stone"),
    on_play=_on_play,
)
