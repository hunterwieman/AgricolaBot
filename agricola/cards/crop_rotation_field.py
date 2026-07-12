"""Crop Rotation Field (minor improvement, E70; Ephipparius Expansion).

Card text (verbatim): "This card is a field. Each time you remove the last
grain or vegetable from this card, you can immediately sow vegetable or grain
on this card, respectively."

Cost: none (free). Prerequisite: 1 Occupation. No printed VPs. Category: Crop
Provider.

THE FIELD. A registered card-field (`agricola/cards/card_fields.py`): one
stack, sowable with grain (plants 3) or vegetables (plants 2) — the
unrestricted-field shape. Per user ruling 45 (2026-07-12) the card counts as
exactly 1 field for every field-count reader (the Fields scoring category,
"N fields" requirements, "grain field" tests) and is NEVER a "field tile"
(user ruling 32, 2026-07-06 — per-tile readers filter to "cell:" sources);
per user ruling 47 (2026-07-12) it holds exactly 1 independently-sowable
stack. The sow enumerator, the field-phase take, scoring, and the
take-modifier folds all reach it through the shared card-field machinery —
this module only registers the spec.

THE RE-SOW — an UNSCOPED per-occasion optional trigger
(`register_harvest_occasion_trigger`, `agricola/cards/harvest_windows.py`).
User ruling 44 (2026-07-12, verbatim): "the granted opposite-crop sow on
itself surfaces at the SAME trigger location as Lettuce Patch's convert — the
removal-occasion optional stretch. Normal sow semantics (costs the supply
crop), targets only this card, declinable ('you can'). Its firing condition
stays the wider 'remove' verb (any last-crop departure, the E-deck lexicon) —
when a future non-take remover (e.g. Game Provider) empties the card, the sow
is offered at THAT removal's instant."

"Respectively" maps: removed the last GRAIN -> may sow VEGETABLE; removed the
last VEGETABLE -> may sow GRAIN.

ELIGIBILITY (post-take state — the occasion-trigger contract): the occasion
carries an entry with source "card:crop_rotation_field" whose crop X is grain
or veg, AND the card now holds 0 of X (that occasion removed its last X), AND
the card has an EMPTY stack (the sow needs room — a Heresy-Teacher-shaped
mixed stack may still hold the other crop below the one removed), AND the
player has >= 1 of the OPPOSITE crop in supply (normal sow semantics — the
sow costs the supply crop).

APPLY — one step, no PendingSow frame: deduct 1 opposite crop from supply and
fill the empty stack with the standard planted amount (veg -> 2, grain -> 3)
via `stacks_to_store` / `stack_with`. The fire/decline choice on the occasion
host IS the whole decision — one card, one crop, one stack, nothing further
to choose. The granted sow is the card's OWN effect, not a "Sow" action: no
before/after_sow hooks fire.

THE "REMOVE" VERB (the E-deck lexicon; HARVEST_HANDOFF.md §5 — a deliberate
contrast with Cherry Orchard E68 / Melon Patch E69, whose reactions say
"harvest"): "remove" is ANY departure of the crop from the card, not just a
harvest. The trigger is therefore UNSCOPED — it fires on any occasion that
removed the card's last crop: a real harvest's field-phase take AND a
card-driven bare take (Bumper Crop's mid-WORK field-phase effect) alike.
Today the take is the ONLY path that removes crops from a card-field, and
every take emits an occasion — so this occasion trigger IS the complete
implementation. A future non-take remover (e.g. Game Provider's field-crop
discard) must host this reactor at its own removal instant (the
`card_fields.py` module header carries the same note).

Card-game only (minor + card-field + occasion-trigger registries, all
ownership-gated; the CardStore content is card-only): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import (
    CROP_SOW_AMOUNTS,
    EMPTY_STACK,
    card_field_stacks,
    card_holds,
    register_card_field,
    stack_with,
    stacks_to_store,
)
from agricola.cards.harvest_windows import register_harvest_occasion_trigger
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "crop_rotation_field"

# The "respectively" map: last GRAIN removed -> may sow VEG, and vice versa.
_OPPOSITE = {"grain": "veg", "veg": "grain"}


def _sowable_crop(state: GameState, idx: int, occasion) -> str | None:
    """The crop the granted sow may plant off this occasion, or None.

    Post-take reading: an occasion entry with source
    "card:crop_rotation_field" whose crop X is grain or veg with
    `card_holds(X) == 0` means the occasion removed the card's last X; the
    sow then plants the OPPOSITE crop, requiring an EMPTY stack on the card
    and >= 1 of that opposite crop in the player's supply (see the module
    docstring's ELIGIBILITY)."""
    p = state.players[idx]
    for e in occasion.entries:
        if e.source != f"card:{CARD_ID}" or e.crop not in _OPPOSITE:
            continue
        if card_holds(p, CARD_ID, e.crop) != 0:
            continue
        opposite = _OPPOSITE[e.crop]
        if getattr(p.resources, opposite) < 1:
            continue
        if not any(s == EMPTY_STACK for s in card_field_stacks(p, CARD_ID)):
            continue
        return opposite
    return None


def _eligible(state: GameState, idx: int, occasion) -> bool:
    return _sowable_crop(state, idx, occasion) is not None


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """Sow the opposite crop on this card: 1 from supply fills the empty
    stack with the standard planted amount (grain 3 / veg 2). No PendingSow
    frame is pushed — the fire on the occasion host is the whole decision —
    and no before/after_sow hooks fire (the card's own effect, not a "Sow"
    action)."""
    crop = _sowable_crop(state, idx, occasion)
    assert crop is not None, "FireTrigger dispatched while ineligible"
    p = state.players[idx]
    stacks = list(card_field_stacks(p, CARD_ID))
    slot = stacks.index(EMPTY_STACK)
    stacks[slot] = stack_with(EMPTY_STACK, crop, CROP_SOW_AMOUNTS[crop])
    p = fast_replace(
        p,
        resources=p.resources - Resources(**{crop: 1}),
        card_state=stacks_to_store(p.card_state, CARD_ID, stacks),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, min_occupations=1)
register_card_field(CARD_ID, stacks=1, sow_amounts=(("grain", 3), ("veg", 2)))
register_harvest_occasion_trigger(CARD_ID, _eligible, _apply)
