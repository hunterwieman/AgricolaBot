"""Artichoke Field (minor improvement, E72; Ephipparius Expansion; players -).

Card text (verbatim): "This card is a field. During the field phase of each
harvest, if you harvest at least 1 good from this card, you also get 1 food."

Cost: 1 Wood. Prerequisite: 2 Occupations. Printed VPs: 1. Kept (not passing).
Category: Crop Provider.

Two effects:

- **"This card is a field"** — a registered card-field
  (`agricola/cards/card_fields.py`): ONE stack, unrestricted crops — it can be
  sown with grain (planting 3) or vegetables (planting 2), exactly like a
  plowed grid field, and the field-phase take harvests 1 crop from it per
  harvest. Per ruling 45 (2026-07-12) it counts as exactly **1 field** for
  every field-count reader (the Fields scoring category, "N fields"
  requirements, "grain field" tests — via the `card_field_count` /
  `crop_card_field_count` helpers), and per ruling 32 (2026-07-06) it is NEVER
  a "field TILE" — per-tile readers exclude it. One stack per ruling 47
  (2026-07-12): only cards printed "as though it were N fields" get more.

- **The food grant** — a per-occasion harvest AUTO
  (`register_harvest_occasion_auto`): "you also get 1 food" is mandatory and
  choice-free, and per user ruling 21 (2026-07-05) "mandatory + choice-free =
  automatic, never a forced singleton button" — the food arrives with no
  player input, right after the harvesting occasion applies. Eligibility is
  two-part:

  - **Field-phase scoped** (`state.phase == Phase.HARVEST_FIELD`): "During the
    field phase of each harvest" anchors the clause to the FIELD PHASE — the
    window, not the one take action — exactly ruling 12's lexicon (2026-07-04)
    and the Crack Weeder precedent. So a card-granted additional harvest that
    reaches this card during a real harvest's field phase would pay too, while
    a card-played field-phase EFFECT run mid-WORK (Bumper Crop — ruling 4,
    the harvest-window rulings in CARD_DEFERRED_PLANS.md: it "triggers the
    field-phase effect, not the phase and not a harvest") harvests the card's
    crop but earns NO food, because the phase is WORK.
  - **The card was harvested**: the occasion's manifest carries at least one
    `HarvestEntry` with `source == "card:artichoke_field"`, ANY crop — the
    text says "at least 1 good", so grain and vegetables both qualify.

  The grant is a flat +1 food per qualifying occasion — "if you harvest at
  least 1 good" is a threshold, not a unit counter, so a take-modifier that
  makes the card's entry `amount == 2` (Scythe Worker's extra grain, ruling 46
  2026-07-12) still pays exactly 1. Once per occasion is structural: the auto
  seam (`apply_harvest_occasion_autos`) fires each card at most once per
  occasion.

Card state is the card-field stack in the owner's CardStore (written only
through the card-fields machinery); the Family game never constructs it, so
the Family wire/canonical formats and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_minor
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "artichoke_field"


def _eligible(state: GameState, idx: int, occasion) -> bool:
    # "During the field phase of each harvest" — the phase gate (ruling 12's
    # lexicon; a mid-WORK Bumper Crop take earns nothing) — AND "you harvest
    # at least 1 good from this card": any manifest entry sourced from this
    # card, any crop.
    return state.phase == Phase.HARVEST_FIELD and any(
        e.source == f"card:{CARD_ID}" for e in occasion.entries)


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """"You also get 1 food" — flat, per qualifying occasion (a threshold,
    not a unit count: an entry of amount 2 still pays exactly 1)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               min_occupations=2, vps=1)
register_card_field(CARD_ID, stacks=1, sow_amounts=(("grain", 3), ("veg", 2)))
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
