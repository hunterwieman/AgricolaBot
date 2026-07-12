"""Cherry Orchard (minor improvement, E68; Ephipparius Expansion; Crop Provider).

Card text (verbatim): "This card is a field on which you can only sow and
harvest wood as you would grain. Each time you harvest the last wood from this
card, you also get 1 vegetable."
No cost. No prerequisite. No printed VP.

WHAT THE CARD DOES. The card itself is a field — it occupies no farmyard cell,
but wood is sown onto it (1 wood from supply plants 3, copying grain's sow
amount per the printed "as you would grain") and the field phase of each
harvest takes 1 wood from it back to supply, exactly like a grain field. It is
a card-field (`agricola/cards/card_fields.py`): one stack, wood-only.
Whenever a harvesting event takes the card's LAST wood, the owner also gains
1 vegetable from the general supply.

THE FIELD (rulings 45 + 47, 2026-07-12; ruling 32, 2026-07-06). The card
counts as exactly 1 field for every field-count reader — the Fields scoring
category, "N fields" requirements — but is NEVER a "field tile" (ruling 32:
per-TILE readers filter to "cell:" sources; this card's manifest entries carry
source "card:cherry_orchard"). Sowing it rides the standard sow enumerator:
any GENERIC sow grant reaches it, but a crops-explicit grant ("sow crops")
cannot plant wood here (ruling 48, 2026-07-12 — `PendingSow.crops_only`).

THE VEGETABLE — an occasion AUTO (`register_harvest_occasion_auto`). "You
also get 1 vegetable" is mandatory and choice-free, so it is an AUTOMATIC
effect fired with no player input — never a forced FireTrigger button (user
ruling 21, 2026-07-05: mandatory + choice-free = automatic). Eligibility
reads the post-take state alongside the occasion manifest: the occasion has
an entry with source "card:cherry_orchard" and crop "wood" (wood left this
card in THIS event) AND `card_holds(...) == 0` (the take removed the last of
it — the seam fires occasion effects after the take applied).

SCOPING — UNSCOPED (user ruling 12's harvest-verb lexicon, 2026-07-04).
"Each time you harvest the last wood from this card" is bare harvest-verb
wording with no phase anchor, so it fires on ANY harvesting occasion: a real
harvest's field-phase take AND a card-played field-phase effect (Bumper
Crop's mid-WORK bare take) alike — the gate is the occasion, never
`state.phase`. Per the E-deck harvest-verb lexicon note
(CARD_DEFERRED_PLANS.md §5), the deck deliberately contrasts this card's
"harvest" (E68/E69) with E70's "remove": "harvest" here means crops moving to
supply via the field-phase effect or a literal card harvest — NOT the wider
any-departure sense.

Card-game only (the card-field and occasion-auto registries are both
ownership-gated and never fire in the Family game), so the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import card_holds, register_card_field
from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "cherry_orchard"


def _eligible(state: GameState, idx: int, occasion) -> bool:
    """The occasion took wood FROM THIS CARD, and it was the last: `state` is
    post-take, so 'harvested the last wood' = a wood entry with this card's
    source in the manifest AND the card now holding none."""
    return (any(e.source == f"card:{CARD_ID}" and e.crop == "wood"
                for e in occasion.entries)
            and card_holds(state.players[idx], CARD_ID, "wood") == 0)


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """"You also get 1 vegetable" — from the general supply."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID)   # free, no prerequisite, no printed VP
register_card_field(CARD_ID, stacks=1, sow_amounts=(("wood", 3),))
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
