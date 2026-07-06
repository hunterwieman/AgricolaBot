"""Field Cultivator (occupation, D126; Dulcinaria Expansion; players 1+;
Building Resource Provider).

Card text (verbatim): "Pile 1 wood, 1 clay, 1 reed, 1 stone, 1 reed, 1 clay,
and 1 wood on this card. Each time you harvest a field tile, you can also take
the top good from the pile."

Occupation (no cost beyond the play route's; no printed VPs). WHAT THE CARD
DOES: at play, seven building resources are piled on the card in the printed
order (wood on top, then clay, reed, stone, reed, clay, wood at the bottom).
From then on, every field tile the owner harvests lets them also take the
current top good of the pile; once all seven are taken the card is spent.

THE PILE IS NOTIONAL. The printed sequence is fixed and public, so no goods
move at play (the on-play is a no-op) and nothing is escrowed from the general
supply: the module constant ``PILE`` carries the sequence, the ONLY state is
how many goods have been taken (a CardStore int, absent = 0), and each taken
good comes from the GENERAL SUPPLY at the moment of the take.

TIMING — an UNSCOPED per-occasion trigger (``register_harvest_occasion_trigger``,
``agricola/cards/harvest_windows.py``). Per user ruling 12 (2026-07-04): "each
time you harvest a field tile" is unscoped harvest-verb wording — there is no
"in the field phase of each harvest" anchor — so the card reacts to ANY
harvesting occasion: a real harvest's field-phase take
(``occasion.source == "take"``) AND a card-played field-phase effect (Bumper
Crop's mid-WORK ``source="card:bumper_crop"`` occasion) alike. The gate is the
occasion itself, never ``state.phase``.

COUNTING & THE VARIANT SET — user ruling 2026-07-06:

- "Each time you harvest a field TILE" is per-TILE counting (the counting
  doctrine, ``harvest_windows.py`` occasion-registry header; the Lynchet
  precedent): count the occasion's manifest ENTRIES — each entry is one FIELD
  tile the event took a crop from — ignoring amounts. A 3-grain field
  harvested for 1 (or for 2 via a take-modifier fold-in) is ONE tile; two
  1-crop fields are TWO tiles. Grain and vegetable tiles count alike ("a
  field tile" names no crop).
- Harvesting k tiles in one occasion grants up to k takes AT ONCE (rulings
  5/11, 2026-07-05: all field-phase harvesting is ONE simultaneous event, so
  the k take opportunities arrive together — the Food Merchant per-grain-buys
  shape). Each take is optional ("you CAN also take"): the trigger's variants
  are j in 1..min(k, pile remaining), one FireTrigger per j, and Proceed
  declines (j = 0). The chosen j receives the next j goods off the pile
  top-down — the fixed order leaves nothing else to choose — and choosing j
  in ONE fire is exact: a take neither harvests anything nor changes what the
  pile yields next, so per-take sequential choices collapse loss-lessly into
  the count.
- ONCE PER OCCASION comes from the host frame's ``triggers_resolved``; a
  later occasion hosts afresh from the advanced counter. Forgone takes are
  NOT recoverable: declining moves no counter, and each occasion's cap is its
  own tile count.

A Grain-Thief-replaced field contributes NO tile — user ruling 2026-07-06
(ruling 22): a replaced field is not harvested and emits no manifest entry,
so the manifest read here excludes it for free.

Card-game only (occupation + occasion-trigger registries, both
ownership-gated; CardStore is a card-only field): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_trigger
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "field_cultivator"

# The printed pile, top-down: a take always yields the next entry. Fixed and
# public, so the only per-game state is how many have been taken.
PILE: tuple[str, ...] = ("wood", "clay", "reed", "stone", "reed", "clay", "wood")


def _taken(state: GameState, idx: int) -> int:
    """How many pile goods the owner has taken so far (absent entry = 0 —
    the pile starts full at play, with no on-play CardStore write needed)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


def _tiles(occasion) -> int:
    """The occasion's field-TILE count: one BOARD-field entry ("cell:r,c") = one
    tile, whatever the amount; grain and veg alike. A card-field entry
    ("card:<id>" — Beanfield et al., when they land) is NOT a field tile (user
    ruling 32, 2026-07-06) and never counts here."""
    return sum(1 for e in occasion.entries if e.source.startswith("cell:"))


def _variants(state: GameState, idx: int, occasion) -> list[str]:
    """One variant per take count j in 1..min(tiles harvested, pile remaining)."""
    cap = min(_tiles(occasion), len(PILE) - _taken(state, idx))
    return [str(j) for j in range(1, cap + 1)]


def _eligible(state: GameState, idx: int, occasion) -> bool:
    """>= 1 tile harvested this occasion AND >= 1 good left on the pile —
    exactly 'some variant exists'."""
    return bool(_variants(state, idx, occasion))


def _apply(state: GameState, idx: int, occasion, variant: str) -> GameState:
    """Take the next j goods off the pile top-down (from the general supply —
    the pile is notional) and advance the taken counter by j."""
    j = int(variant)
    taken = _taken(state, idx)
    counts: dict[str, int] = {}
    for tag in PILE[taken:taken + j]:
        counts[tag] = counts.get(tag, 0) + 1
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(**counts),
        card_state=p.card_state.set(CARD_ID, taken + j),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_harvest_occasion_trigger(CARD_ID, _eligible, _apply, variants_fn=_variants)
