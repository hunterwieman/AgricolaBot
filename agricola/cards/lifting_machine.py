"""Lifting Machine (minor improvement, A70; Artifex Expansion; Crop Provider).

Card text (verbatim): "At the end of each round that does not end with a
harvest, you can move 1 vegetable from one of your fields to your supply.
(This is not considered a field phase.)"
Cost: 1 Wood. Prerequisite: 3 Fields. No printed VPs. Kept (not passing).

THE TIMING — "at the end of each round" is the round-end ladder's LAST rung,
``end_of_round`` (user ruling 49, 2026-07-12: the returning-home phase is the
round's last PHASE, and "the end of the round" is a distinct, LATER instant —
`agricola/cards/round_end.py`). The ladder runs on harvest rounds too (the
round end precedes the harvest), so "that does not end with a harvest" is this
card's OWN eligibility clause, exactly as round_end.py prescribes:
``round_number not in HARVEST_ROUNDS``.

THE MOVE is an optional trigger ("you can") on that window's choice host
(PendingHarvestWindow, event "end_of_round"): declining is implicit (Proceed
without firing), and once-per-round rides the host's ``triggers_resolved``.

WHICH FIELD — surfaced WIDE via play variants, the Craft Brewery which-field
idiom (user ruling 2026-07-06: fields holding the same count of the named crop
are interchangeable, so the choice is encoded by count, not by cell):

- one ``"veg<X>"`` per veg-count group present among the player's grid FIELD
  cells (X >= 1); firing decrements the FIRST ROW-MAJOR field of that group
  (the group's canonical field) and adds 1 vegetable to supply;
- one ``"cf_<card_id>"`` per veg-holding card-field — per user rulings 45/46
  (2026-07-12) a veg-holding card-field IS "one of your fields", but it is
  NEVER merged into a grid group (taking its vegetable moves card state and
  can fire card-level reactions), so each card is its own variant.

The card path routes through ``card_fields.remove_card_crop`` — the
NON-take-removal chokepoint (user ruling 44, 2026-07-12: a non-take remover
hosts the removal reaction at ITS instant) — so moving a Crop Rotation Field's
LAST vegetable off it pushes its sow-or-decline choice RIGHT HERE, at the end
of the round. The supply vegetable is credited BEFORE the chokepoint call, so
a pushed reaction frame lands on the fully-updated state (the Craft Brewery
bank-first pattern).

"(THIS IS NOT CONSIDERED A FIELD PHASE.)" — printed on the card, and exactly
ruling 12's lexicon (2026-07-03: a "harvest" is a harvesting OCCASION): the
vegetable moves directly — the cell/stack is decremented, NO harvesting
occasion is emitted, so no phase-keyed or harvest-verb reactor fires (Melon
Patch's "each time you harvest the last vegetable" stays silent when this
card empties it). But the move IS a REMOVAL — the E-deck "remove" verb, any
departure — which is precisely why Crop Rotation Field's "remove" reaction
DOES fire through the chokepoint while the harvest-verb reactions do not
(the same contrast Craft Brewery's exchange draws).

THE PREREQUISITE — "3 Fields" is a HAVE-check, never spent: grid FIELD cells
plus owned card-fields, planted or not (user ruling 45, 2026-07-12: "field" is
the broader category and includes card-fields, each counting exactly once —
ruling 47; the Seed Pellets prereq, copied).

Card-game only (minor + trigger + variant + labeler registries, all
ownership-gated): the Family game is byte-identical and the C++ gates are
untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import HARVEST_ROUNDS, CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "lifting_machine"


def _three_fields(state: GameState, idx: int) -> bool:
    """Prereq: at least 3 fields, planted or not — grid FIELD cells plus owned
    card-fields (ruling 45, 2026-07-12: "field" includes card-fields, so a
    "you need N fields" requirement counts them; ruling 47: each card counts
    exactly once)."""
    from agricola.cards.card_fields import card_field_count  # local: load-order safe
    p = state.players[idx]
    grid = p.farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) + card_field_count(p) >= 3


def _variants(state: GameState, idx: int) -> list:
    """One variant tag per veg-count group present among the player's FIELD
    cells — "veg<X>" = "move the vegetable off a field holding X vegetables"
    (the Craft Brewery which-field idiom, user ruling 2026-07-06: same-count
    fields are interchangeable, so the choice is surfaced by count, not by
    cell) — plus one PER-CARD tag "cf_<card_id>" for each veg-holding
    card-field (rulings 45/46, 2026-07-12: a card is "one of your fields" but
    never interchangeable with a grid one). Sorted counts, then cards by id;
    empty when nothing holds a vegetable (the move is withheld)."""
    from agricola.cards.card_fields import card_holds, owned_card_fields

    p = state.players[idx]
    counts = {
        cell.veg
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.veg >= 1
    }
    out = [f"veg{n}" for n in sorted(counts)]
    out.extend(sorted(
        f"cf_{cid}" for cid in owned_card_fields(p)
        if card_holds(p, cid, "veg") >= 1))
    return out


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """"Each round that does not end with a harvest" — the bearer's own
    eligibility clause (round_end.py's prescription; the ladder itself runs on
    harvest rounds too) — and at least one veg-bearing field to move from."""
    return (state.round_number not in HARVEST_ROUNDS
            and bool(_variants(state, idx)))


def _add_supply_veg(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Move 1 vegetable from the chosen field to supply — the first row-major
    FIELD holding the chosen count for a "veg<X>" variant (the group's
    canonical field), or the named card-field for a "cf_<id>" variant. NOT a
    field phase (printed) and NOT a harvest (ruling 12's lexicon, 2026-07-03):
    the cell/stack is decremented directly, no occasion is emitted. The card
    path routes through `remove_card_crop` — the supply vegetable is credited
    FIRST because the chokepoint may push a decision frame (Crop Rotation
    Field's re-sow offer when this move removed its last vegetable — ruling
    44, 2026-07-12), and the pushed frame must land on the fully-updated
    state."""
    if variant.startswith("cf_"):
        from agricola.cards.card_fields import remove_card_crop

        state = _add_supply_veg(state, idx)
        return remove_card_crop(state, idx, variant[len("cf_"):], "veg", 1)

    count = int(variant[len("veg"):])
    p = state.players[idx]

    target = None
    for r, row in enumerate(p.farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type == CellType.FIELD and cell.veg == count:
                target = (r, c)
                break
        if target is not None:
            break
    assert target is not None, (
        f"lifting_machine: no field holding {count} veg (variant {variant!r})"
    )

    tr, tc = target
    grid = tuple(
        tuple(
            fast_replace(cell, veg=cell.veg - 1) if (r, c) == (tr, tc) else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return _add_supply_veg(state, idx)


def _action_label(variant: str) -> str | None:
    """Web-UI label for a which-field variant (mechanical, terse): "veg2" ->
    "1 veg from a 2-veg field"; "cf_<id>" -> "1 veg from <Title Case Slug>"."""
    if variant.startswith("cf_"):
        return "1 veg from " + variant[len("cf_"):].replace("_", " ").title()
    if variant.startswith("veg") and variant[len("veg"):].isdigit():
        return f"1 veg from a {int(variant[len('veg'):])}-veg field"
    return None


# Cost 1 wood; prerequisite 3 Fields (grid + card-fields, ruling 45); no
# printed VPs.
register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               prereq=_three_fields)

# The optional once-per-round move on the round-end ladder's last rung
# (ruling 49) — variant-expanded over the veg-bearing fields.
register("end_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_action_labeler(CARD_ID, _action_label)
