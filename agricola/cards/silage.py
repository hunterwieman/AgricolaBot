"""Silage (minor improvement, A84; Artifex Expansion; Livestock Provider).

Card text (verbatim): "In each returning home phase after which there is no
harvest, you can pay exactly 1 grain—even from a field-to breed exactly one
type of animal."
(The em-dash/hyphen inconsistency around "even from a field" is the
catalog's.) Cost: none (free). Prerequisite: "2 Fields". No printed VPs.

WHAT THE CARD DOES — in the returning home phase of every NON-harvest round,
the owner may (once) spend 1 grain — from supply OR off a field — to breed
exactly one animal type: +1 newborn of a type they hold a breeding pair of,
provided the newborn can be accommodated.

TIMING — the printed anchor names the phase, so the effect rides the
round-end ladder's ``returning_home`` window (user ruling 49, 2026-07-12:
"in the returning home phase" is a distinct rung of the round-end ladder;
``agricola/cards/round_end.py``). That rung fires PRE-reset — the live board
is its event data — which is harmless here: Silage reads no board occupancy.
"After which there is no harvest": the returning home phase of a
HARVEST_ROUNDS round (4/7/9/11/13/14) is immediately followed by that round's
harvest, so eligibility requires ``round_number not in HARVEST_ROUNDS``
(at the ladder, ``round_number`` still names the round just completing).

THE CHOICE — an optional play-variant TRIGGER on the window's frame, one
``FireTrigger(card_id, variant="<source>:<type>")`` per (payable grain
source) x (breedable type):

- ``"supply"`` — 1 grain from the player's supply.
- ``"grain<h>"`` — 1 grain off a grid FIELD holding exactly h grain (the
  Craft Brewery height-group idiom, user ruling 2026-07-06: same-height
  fields are interchangeable; the canonical field is the first in row-major
  scan order).
- ``"cf_<card_id>"`` — 1 grain off that grain-holding card-field (user
  rulings 45/46, 2026-07-12: a card-field is "a field" and may pay the field
  grain, but is never merged into a grid height group — taking its grain
  moves card state and can fire card-level reactions).

A type is BREEDABLE when the player holds at least its pair threshold — 2,
sheep via the ``capacity_mods.sheep_min_parents`` seam (Dolly's Mother E84's
single-parent lowering reads through it) — AND the newborn is accommodatable
(+1 of that type fits: ``helpers.accommodates``, the standard
``extract_slots`` + sheep-slot strip + ``can_accommodate`` check). The
breeding rule "you must be able to accommodate the newborn — no newborn
otherwise" is inherent, so an unaccommodatable type is simply not offered.

NOT A BREEDING PHASE — the fire adds the newborn directly: no
``breeding_outcome`` event is emitted and no breed frame is pushed, so the
phase-anchored breeding reactors (Fodder Planter D115, Slurry Spreader C71 —
"in the breeding phase of each harvest") are structurally silent. Ruling 39's
post-breed cooking floor is HARVEST-scoped (a conversion floor inside the
harvest breeding phase) and does not apply to this mid-round breed.

NOT A HARVEST — paying the grain off a field is a REMOVAL, not a harvest
(user ruling 12's lexicon, 2026-07-03: a "harvest" is a harvesting OCCASION):
no occasion is emitted, so harvest-verb reactors (Grain Sieve, Cherry
Orchard / Melon Patch's "harvest" reactions) get nothing. The "remove" verb
DOES fire: the card-field path routes through
``card_fields.remove_card_crop`` — the ruling-44 chokepoint (2026-07-12) —
so emptying a Crop Rotation Field's last grain this way offers its
vegetable re-sow at this very instant, mid-returning-home. A grid field is
decremented directly (the Craft Brewery idiom; grid cells host no removal
reactors).

ONCE PER ROUND comes free from the window frame's ``triggers_resolved``
(one ``returning_home`` window per round, a fresh frame each round);
DECLINING is the frame's ``Proceed`` (no SkipTrigger, the standard shape).

Prerequisite "2 Fields" — grid FIELD cells plus owned card-fields, planted
or not. User ruling 45 (2026-07-12), verbatim: '"field TILES" means the
plowed fields on the farmyard grid; "field" is the BROADER category and
includes card-fields. So a card-field counts for field-count readers — the
Fields scoring category and any "you need N fields" requirement — while
per-TILE readers still exclude it (ruling 32 unchanged).'

Card-game only (ownership-gated card registries; no CardStore use of its
own): the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import HARVEST_ROUNDS, CellType
from agricola.helpers import accommodates
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "silage"

_ANIMALS = ("sheep", "boar", "cattle")


def _prereq(state: GameState, idx: int) -> bool:
    """"2 Fields" — grid FIELD cells plus owned card-fields, planted or not
    (ruling 45, 2026-07-12 — quoted in the module docstring; ruling 47: a
    multi-stack card-field still counts exactly once). The Cesspit idiom."""
    from agricola.cards.card_fields import card_field_count  # load-order safe

    p = state.players[idx]
    fields = sum(
        1 for row in p.farmyard.grid for cell in row
        if cell.cell_type is CellType.FIELD
    ) + card_field_count(p)
    return fields >= 2


def _grain_sources(state: GameState, idx: int) -> list:
    """The payable grain sources, as variant source tokens: "supply" (>= 1
    supply grain), one "grain<h>" per grain-height group among the grid FIELD
    cells (Craft Brewery's height idiom, ascending), one "cf_<card_id>" per
    grain-holding card-field (rulings 45/46 — per card, never height-merged;
    sorted by card id)."""
    from agricola.cards.card_fields import card_holds, owned_card_fields

    p = state.players[idx]
    out = []
    if p.resources.grain >= 1:
        out.append("supply")
    heights = {
        cell.grain
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type is CellType.FIELD and cell.grain >= 1
    }
    out.extend(f"grain{h}" for h in sorted(heights))
    out.extend(f"cf_{cid}" for cid in owned_card_fields(p)
               if card_holds(p, cid, "grain") >= 1)
    return out


def _breedable_types(state: GameState, idx: int) -> list:
    """The types the player can breed right now: holds >= the pair threshold
    (2; sheep via the `sheep_min_parents` seam — Dolly's Mother lowers it to
    1) AND the newborn is accommodatable (+1 of the type fits —
    `helpers.accommodates`, the standard capacity check). The breeding rule
    "you must be able to accommodate the newborn" is inherent: no newborn
    otherwise, so an unaccommodatable type is not offered."""
    from agricola.cards.capacity_mods import sheep_min_parents

    p = state.players[idx]
    a = p.animals
    out = []
    for animal in _ANIMALS:
        threshold = sheep_min_parents(p) if animal == "sheep" else 2
        if getattr(a, animal) < threshold:
            continue
        if not accommodates(p,
                            a.sheep + (animal == "sheep"),
                            a.boar + (animal == "boar"),
                            a.cattle + (animal == "cattle")):
            continue
        out.append(animal)
    return out


def _variants(state: GameState, idx: int) -> list:
    """Every currently-fireable "<source>:<type>" variant, source-major
    (supply, then grid heights ascending, then card-fields by id; types in
    sheep/boar/cattle order)."""
    types = _breedable_types(state, idx)
    if not types:
        return []
    return [f"{src}:{animal}"
            for src in _grain_sources(state, idx)
            for animal in types]


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"After which there is no harvest" (a HARVEST_ROUNDS round's returning
    home phase is followed by that round's harvest) + at least one payable
    grain source + at least one breedable type. Ownership is the window
    machinery's gate; once-per-round is the frame's `triggers_resolved`."""
    if state.round_number in HARVEST_ROUNDS:
        return False
    return bool(_grain_sources(state, idx)) and bool(_breedable_types(state, idx))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """One fire: +1 newborn of the chosen type, then debit the 1 grain at the
    chosen source. The newborn lands FIRST because the card-field path's
    `remove_card_crop` chokepoint may push a decision frame (Crop Rotation
    Field's re-sow offer when this payment removed its last grain — ruling
    44, 2026-07-12), and the pushed frame must land on the fully-updated
    state (the Craft Brewery ordering). No breeding_outcome event, no breed
    frame, no harvest occasion (see the module docstring)."""
    source, animal = variant.split(":", 1)

    p = state.players[idx]
    p = fast_replace(p, animals=fast_replace(
        p.animals, **{animal: getattr(p.animals, animal) + 1}))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))

    if source == "supply":
        p = state.players[idx]
        p = fast_replace(p, resources=p.resources - Resources(grain=1))
        return fast_replace(
            state,
            players=tuple(p if i == idx else state.players[i] for i in range(2)))

    if source.startswith("cf_"):
        # The ruling-44 chokepoint: a non-take remover fires the card's own
        # removal reactor at THIS instant (it may push a decision frame).
        from agricola.cards.card_fields import remove_card_crop

        return remove_card_crop(state, idx, source[len("cf_"):], "grain", 1)

    # "grain<h>" — the first row-major FIELD holding exactly h grain (the
    # height group's canonical field), decremented directly: a removal, not
    # a harvest (no occasion; grid cells host no removal reactors).
    height = int(source[len("grain"):])
    p = state.players[idx]
    target = None
    for r, row in enumerate(p.farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type is CellType.FIELD and cell.grain == height:
                target = (r, c)
                break
        if target is not None:
            break
    assert target is not None, (
        f"silage: no field holding {height} grain (variant {variant!r})")
    tr, tc = target
    grid = tuple(
        tuple(
            fast_replace(cell, grain=cell.grain - 1) if (r, c) == (tr, tc) else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _action_label(variant: str) -> str | None:
    """Web-UI label (mechanical, terse): "supply:sheep" -> "1 grain (supply)
    → breed sheep"; "grain2:cattle" -> "1 grain (2-grain field) → breed
    cattle"; "cf_crop_rotation_field:boar" -> "1 grain (Crop Rotation Field)
    → breed boar"."""
    if ":" not in variant:
        return None
    source, animal = variant.split(":", 1)
    if source == "supply":
        src = "supply"
    elif source.startswith("cf_"):
        src = source[len("cf_"):].replace("_", " ").title()
    elif source.startswith("grain") and source[len("grain"):].isdigit():
        src = f"{source[len('grain'):]}-grain field"
    else:
        return None
    return f"1 grain ({src}) → breed {animal}"


# Cost null -> free; prereq "2 Fields" (ruling 45); vps null -> 0.
register_minor(CARD_ID, prereq=_prereq)

# The optional once-per-round breed on the round-end ladder's returning_home
# window (ruling 49), variant-expanded: (grain source) x (breedable type).
register("returning_home", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_action_labeler(CARD_ID, _action_label)
