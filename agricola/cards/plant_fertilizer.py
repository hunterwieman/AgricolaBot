"""Plant Fertilizer (minor improvement, C8; Corbarius Expansion; traveling).

Card text: "In each field with exactly 1 good, you can immediately place 1
additional good of the same type."
Cost: none. Prerequisite: none. VPs: 0. TRAVELING (passing) card.

Clarifications (card, verbatim): "Boar held on unplanted fields (from Mud Patch
A011) do not apply for this effect.  《If there is exactly 1 wood on the Wood
Field D075, another wood may be added on either the same or a different
stack.》" Mud Patch is not implemented and not in the current pool, so no
boar-on-field handling is needed. The Wood Field sentence is load-bearing twice
over: it confirms in print that CARD-FIELDS are "fields" for this card and that
wood (hence stone) counts as its "good", and it makes the added good's stack
placement a real choice on a multi-stack card (below).

Category 2 (on-play one-shot) + passing. The effect is applied automatically at
play time: it is a guaranteed-beneficial pure-goods grant with no downside, so
it needs no declinable FireTrigger frame (the project's "pure-goods you-can
grant with no downside may stay automatic" convention, matching Calcium
Fertilizers). The one genuine decision it can contain — WHERE a multi-stack
card's extra good lands — is not a decline and surfaces as play variants,
never as a trigger.

WHICH FIELDS QUALIFY — two passes over the same "exactly 1 good" threshold:

- GRID fields (the original pass, unchanged): a FIELD cell holding exactly one
  crop token of a single type — grain == 1 (and veg == 0), XOR veg == 1 (and
  grain == 0). This is stricter than "a field growing a single crop type": a
  freshly-sown field holds 3 grain or 2 veg and does NOT qualify; only a field
  harvested down to its last token does (each harvest_field decrements a
  planted crop by 1). A field carrying both grain and veg is two goods and is
  also skipped. The result of fertilizing is 2 of that crop.
- CARD-FIELDS (user rulings 45 + 47, both 2026-07-12). Ruling 45, verbatim:
  ""field TILES" means the plowed fields on the farmyard grid; "field" is the
  BROADER category and includes card-fields. So a card-field counts for
  field-count readers — the Fields scoring category and any "you need N
  fields" requirement — while per-TILE readers still exclude it (ruling 32
  unchanged)." This card says "field", not "field tile", so card-fields are in.
  Ruling 47 (2026-07-12): a multi-stack card-field (Wood Field, Rock Garden)
  "is considered 1 field" — it qualifies at CARD level: its TOTAL goods across
  all stacks == exactly 1 (any good — grain, veg, wood, or stone; the printed
  clarification names wood). A Wood Field with 1 wood on EACH of its two
  stacks holds 2 goods and gains nothing. The qualifying card gains +1 of the
  same good.

THE PLACEMENT CHOICE (the clarification's "either the same or a different
stack"). On a single-stack card — or a multi-stack card with no empty stack —
there is no choice: the good joins the stack already holding one. On a
multi-stack card holding exactly 1 good WITH at least one empty stack, the
placement is a real fork: "same" makes one 2-good stack (harvested over two
field phases, 1 per phase); "new" makes two 1-good stacks (both harvested next
field phase). Per user ruling 24 (2026-07-06) a minor's on-play choice
surfaces WIDE as distinct CommitPlayMinor variants — the Facades Carving
PLAY_MINOR_VARIANTS mechanism: one zero-surcharge variant per combination of
per-qualifying-card placements, encoded "<card_id>:same|<card_id>:new" over
the qualifying cards in sorted-id order (a single qualifying Wood Field gives
the two variants "wood_field:same" / "wood_field:new"). The grid pass and
every no-choice card placement are identical across variants and apply in all
of them. When NO multi-stack card qualifies, the variants_fn returns the
single variant None, which the seam threads into a CommitPlayMinor identical
to the pre-variant commit (variant=None is the action field's default,
default-skipped on the wire and label-invisible in the web UI) — simple /
no-card-field states keep exactly the old single automatic action.

Crops live on Cell.grain / Cell.veg (NOT player.resources). Fields never lie
inside a pasture, so the cached pasture decomposition rides along on the grid
fast_replace (mirrors Calcium Fertilizers / the mechanical harvest take).
Card-field contents live in the owner's CardStore as canonical
(grain, veg, wood, stone) stacks (agricola/cards/card_fields.py); the add goes
through stack_with + stacks_to_store, keeping the store canonical.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "plant_fertilizer"


def _choice_cards(player_state) -> list[str]:
    """The owned card-fields whose extra good has a real placement choice:
    multi-stack (ruling 47), holding exactly 1 good in TOTAL, with at least
    one empty stack (the printed Wood Field clarification's "either the same
    or a different stack"). Sorted card ids — the canonical order the variant
    encoding uses."""
    from agricola.cards.card_fields import (
        CARD_FIELDS, EMPTY_STACK, card_field_stacks, owned_card_fields)
    out = []
    for cid in owned_card_fields(player_state):
        if CARD_FIELDS[cid].stacks < 2:
            continue
        stacks = card_field_stacks(player_state, cid)
        if sum(sum(s) for s in stacks) != 1:
            continue
        if any(s == EMPTY_STACK for s in stacks):
            out.append(cid)
    return out


def _variants(state: GameState, idx: int) -> list:
    """One zero-surcharge play variant per combination of per-choice-card
    placements ("same" = the occupied stack, "new" = an empty one), the cards
    '|'-joined in sorted-id order. With no choice card the single variant is
    None — the seam then emits the plain variant-less CommitPlayMinor, so
    states without a qualifying multi-stack card see the unchanged automatic
    play action."""
    choice = _choice_cards(state.players[idx])
    if not choice:
        return [(None, Resources())]
    routes = [""]
    for cid in choice:
        routes = [(f"{r}|" if r else "") + f"{cid}:{pl}"
                  for r in routes for pl in ("same", "new")]
    return [(r, Resources()) for r in routes]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """For each field (grid or card) holding exactly 1 good, add a second of
    the same good.

    Grid pass (unchanged): grain == 1 (xor) veg == 1 is the eligibility; the
    matched crop goes to 2. Any other field — unplanted, >1 token, or two crop
    types — is left untouched.

    Card pass (rulings 45/47): card TOTAL == exactly 1 (any good) -> +1 of
    that good, joining the occupied stack, or opening an empty stack where the
    chosen `variant` says "new" for that card. `variant` must name exactly the
    cards `_choice_cards` finds (the enumerator guarantees it; asserted for
    direct callers — None means "no choice card exists")."""
    from agricola.cards.card_fields import (
        EMPTY_STACK, GOODS, card_field_stacks, owned_card_fields,
        stack_with, stacks_to_store)
    p = state.players[idx]
    placements = (dict(part.split(":") for part in variant.split("|"))
                  if variant else {})
    assert set(placements) == set(_choice_cards(p)) and all(
        pl in ("same", "new") for pl in placements.values()), variant
    # --- grid pass ---
    new_grid = []
    grid_changed = False
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            if cell.cell_type is CellType.FIELD:
                if cell.grain == 1 and cell.veg == 0:
                    new_row.append(fast_replace(cell, grain=2))
                    grid_changed = True
                    continue
                if cell.veg == 1 and cell.grain == 0:
                    new_row.append(fast_replace(cell, veg=2))
                    grid_changed = True
                    continue
            new_row.append(cell)
        new_grid.append(tuple(new_row))
    # --- card-field pass ---
    store = p.card_state
    cards_changed = False
    for cid in owned_card_fields(p):
        stacks = card_field_stacks(p, cid)
        totals = tuple(sum(s[i] for s in stacks) for i in range(4))
        if sum(totals) != 1:
            continue
        good = GOODS[totals.index(1)]
        if placements.get(cid) == "new":        # the chosen empty stack
            i = stacks.index(EMPTY_STACK)
            new_stacks = (stacks[:i]
                          + (stack_with(EMPTY_STACK, good, 1),)
                          + stacks[i + 1:])
        else:                                   # the (sole) occupied stack
            new_stacks = tuple(
                stack_with(s, good, 1) if sum(s) else s for s in stacks)
        store = stacks_to_store(store, cid, new_stacks)
        cards_changed = True
    if not (grid_changed or cards_changed):
        return state
    if grid_changed:
        p = fast_replace(
            p, farmyard=fast_replace(p.farmyard, grid=tuple(new_grid)))
    if cards_changed:
        p = fast_replace(p, card_state=store)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), passing_left=True, on_play=_on_play)

# The multi-stack placement choice surfaces WIDE (user ruling 24, 2026-07-06)
# via the PLAY_MINOR_VARIANTS seam; the None route keeps no-choice states on
# the plain variant-less commit.
register_play_minor_variant(CARD_ID, _variants)
