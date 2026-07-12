"""Lettuce Patch (minor improvement, C70; Consul Dirigens Expansion).

Card text (verbatim): "This card is a field that can only grow vegetables. You
can immediately turn each vegetable you harvested from this card into 4 food."

Cost: none (free). Printed VPs: 1. Prerequisite: 3 Occupations. Kept (not
passing). Category: Crop Provider.

THE FIELD. "This card is a field" — a registered card-field
(`agricola/cards/card_fields.py`): one stack, sowable with vegetables only
("can only grow vegetables" — the sow whitelist is `(("veg", 2),)`; one sow
spends 1 vegetable from supply and plants 2, RULES.md), harvested by the
field-phase take like any field (one `source="card:lettuce_patch"` manifest
entry per take). Per user rulings 45 + 47 (2026-07-12) the card counts as
exactly 1 field for every field-count reader (the Fields scoring category,
"N fields" requirements, "vegetable field" tests); per user ruling 32
(2026-07-06) it is NEVER a "field tile" — per-TILE readers exclude it.

THE CONVERT — an optional per-occasion trigger
(`register_harvest_occasion_trigger`). User ruling 43 (2026-07-12): "the
'immediately' convert is offered at the take occasion, ALONGSIDE the other
optional triggers that fire on the field phase's harvesting action (the
PendingHarvestOccasion stretch — Food Merchant's home); 'immediately' does not
jump the queue." So the offer surfaces on the per-occasion
`PendingHarvestOccasion` host right after the occasion's automatic
consequences, exactly where Food Merchant's buys live.

SCOPING — UNSCOPED (user ruling 12's lexicon, 2026-07-04): "each vegetable you
harvested from this card" is bare harvest-verb wording with no phase anchor
("during the field phase of each harvest"), so the trigger reacts to ANY
harvesting occasion — a real harvest's take AND a card-driven bare take
(Bumper Crop's mid-WORK `source="card:bumper_crop"` occasion) alike. The gate
is the occasion itself, never `state.phase`.

THE VARIANT SET — the Food Merchant per-unit precedent ("each X ... you can Y"
distributes per unit): variants "1".."k" where k is the vegetable UNITS this
occasion harvested from THIS card (the sum of `amount` over the occasion's
entries with `source == "card:lettuce_patch"` and `crop == "veg"`); variant j
turns j of them into food — j vegetables leave the supply, 4*j food arrives.
The harvested vegetables just landed in the player's supply, and that is where
the convert spends them; a same-occasion earlier consumer could already have
spent some, so each offered variant is capped by the current supply (no
unpayable variant is ever surfaced — the Food Merchant affordability
precedent), and eligibility is exactly "some variant exists" (k >= 1 AND
supply vegetables >= 1). k > 1 arises only when a take-modifier folds an extra
unit from this card into the same take (Stable Manure's donated +1 — user
ruling 46, 2026-07-12). Once per occasion via the host frame's
`triggers_resolved`; declining is the host's `Proceed`.

Card-only state is the card-field stack itself (the shared CardStore shape —
`card_fields.py`); the Family game constructs none of it, so the Family game
is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.harvest_windows import register_harvest_occasion_trigger
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "lettuce_patch"


def _veg_from_card(occasion) -> int:
    """The vegetable units this occasion harvested from THIS card — the sum of
    amounts over its `source == "card:lettuce_patch"` vegetable entries (the
    single stack normally yields one entry of amount 1; a take-modifier
    fold-in raises the amount)."""
    return sum(e.amount for e in occasion.entries
               if e.source == f"card:{CARD_ID}" and e.crop == "veg")


def _variants(state: GameState, idx: int, occasion) -> list[str]:
    """One variant per convertible count j in 1..k, capped by the supply
    vegetables actually still there to spend (a same-occasion earlier consumer
    could have taken some)."""
    k = min(_veg_from_card(occasion), state.players[idx].resources.veg)
    return [str(j) for j in range(1, k + 1)]


def _eligible(state: GameState, idx: int, occasion) -> bool:
    """Some vegetable was harvested from this card this occasion AND at least
    one is still in supply to convert — exactly 'some variant exists'."""
    return bool(_variants(state, idx, occasion))


def _apply(state: GameState, idx: int, occasion, variant: str) -> GameState:
    """Turn j harvested vegetables into food: j vegetables leave the supply,
    4*j food arrives (no cost layer on occasion triggers — the Food Merchant
    precedent: the goods move here)."""
    j = int(variant)
    p = state.players[idx]
    p = fast_replace(
        p, resources=p.resources - Resources(veg=j) + Resources(food=4 * j))
    return fast_replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, min_occupations=3, vps=1)
register_card_field(CARD_ID, stacks=1, sow_amounts=(("veg", 2),))
register_harvest_occasion_trigger(CARD_ID, _eligible, _apply, variants_fn=_variants)
