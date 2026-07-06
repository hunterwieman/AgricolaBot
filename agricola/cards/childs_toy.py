"""Child's Toy (minor improvement, E30; Ephipparius Expansion; Points Provider).

Card text (verbatim): "During the feeding phase of each harvest, your newborns
require 2 food (instead of 1)."

Cost: 1 Wood/1 Clay. Prerequisite: "Exactly 2 Adults". VPs: 2. Not passing.

WHAT THE CARD DOES — a pure points-for-a-drawback trade: the card is worth 2
points, and in exchange the owner's newborns lose the newborn feeding discount.
Normally a person born this round eats only 1 food at a harvest held at the end
of its birth round (RULES.md Feeding Phase); with this card the owner's
newborns eat the full 2, like adults. Only the owner is affected ("your
newborns"), and only at harvest feeding.

MECHANISM — a feeding-requirement fold (`register_feeding_requirement`,
agricola/cards/harvest_windows.py). The base requirement is
``2*people_total − newborns`` (2 per adult + 1 per newborn), so the fold
returns ``need + newborns``: each newborn's cost rises by exactly 1, to 2.
Ownership gating happens at the chokepoint itself — `helpers.feeding_requirement`
applies a registered fold only for a player who owns the card — so the fold
body carries no ownership check. Timing fidelity: `feeding_requirement` is
consulted only at the harvest FEED phase (the PendingHarvestFeed enumerator's
`food_owed` and the CommitConvert feed executor's need/begging computation),
which is exactly the printed "during the feeding phase of each harvest";
newborns are cleared at PREPARATION, so the card bites precisely when a birth
round ends in a harvest — the only moment the discount it removes ever applied.

COST "1 Wood/1 Clay" — an ALTERNATIVE ("/") cost: pay EITHER 1 wood OR 1 clay,
not both (MinorSpec.alt_costs; the Chophouse "2 Wood / 2 Clay" shape). The
printed 1-wood cost is `cost`; the 1-clay alternative rides on `alt_costs`,
and the play path enumerates one CommitPlayMinor per affordable alternative.

PREREQUISITE "Exactly 2 Adults" — a play-time HAVE-check that the player has
exactly 2 adults at the moment of playing: adults = people_total − newborns
(newborns are people but not adults). It is not re-checked afterward — the
family may grow past 2 adults later; the prerequisite only gates the play.

Family game: inert. The fold registry is ownership-gated at the chokepoint and
no player ever owns a minor improvement in the Family game, so `feeding_requirement`
is unchanged there.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_feeding_requirement
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "childs_toy"


def _prereq_exactly_2_adults(state: GameState, idx: int) -> bool:
    """"Exactly 2 Adults" — adults = people_total − newborns, checked at play time."""
    p = state.players[idx]
    return p.people_total - p.newborns == 2


def _fold(state: GameState, idx: int, need: int) -> int:
    """Raise each newborn's feeding cost from 1 to 2 (base already charges 1)."""
    return need + state.players[idx].newborns


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    alt_costs=(Cost(resources=Resources(clay=1)),),
    prereq=_prereq_exactly_2_adults,
    vps=2,
)
register_feeding_requirement(CARD_ID, _fold)
