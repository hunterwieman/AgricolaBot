"""Thunderbolt (minor improvement, E4; Ephipparius Expansion; traveling/passing).

Card text (verbatim): "Immediately remove all grain from one of your fields to
the general supply. Gain 2 wood for each grain you just removed."

Cost: none (free). Prerequisite: 1 Grain Field. No printed VPs. Category:
Building Resource Provider. PASSING (traveling — after the on-play effect the
card is passed to the opponent, never kept in the tableau).

USER RULINGS (2026-07-17):
- The effect is MANDATORY (no "you can") with a CHOICE of WHICH field. It is
  surfaced as play-VARIANTS with NO skip variant: you cannot play the card and
  decline the removal — every variant removes all grain from some field.
- BOARD fields are enumerated BY GRAIN COUNT, not by cell: one variant per
  DISTINCT grain count among the player's grain-bearing board fields (two fields
  holding the same count are treated as equivalent — the established engine
  convention, mirroring the sow commit's fungible board fields). The executor
  picks a deterministic representative: the LOWEST (row, col) field holding that
  count.
- Each grain-bearing CARD field is its OWN variant, labeled by card id (never
  collapsed with a board field, even at an equal count): card-crop removal must
  route through the `remove_card_crop` chokepoint (ruling 44, 2026-07-12) so its
  registered removal reactions fire (Crop Rotation Field's re-sow).
- Ruling 45 (standing): "field(s)" wording includes card fields, so the PREREQ
  counts a grain-bearing card field too.
- Ruling 66: the on-play "immediately" adds/changes nothing.

MECHANICS. `register_play_minor_variant` surfaces one zero-surcharge
`CommitPlayMinor` per variant (there is no play COST, and the choice carries no
surcharge — the variant only names the field). The 3-arg `on_play` reads the
chosen variant:

- "board:<count>" — zero the grain of the lowest-(row, col) FIELD cell holding
  `<count>` grain. This is a plain FIELD-cell crop edit: it changes no
  `cell_type` and no fence, so the cached pasture decomposition is untouched and
  rides along via `fast_replace` (ENGINE_IMPLEMENTATION.md — the `Farmyard.pastures`
  caller-discipline contract: all non-pasture-changing Farmyard mutations leave
  `pastures` alone). "To the general supply" means the grain simply leaves play
  state (no general-supply tracking exists).
- "card:<card_id>" — remove ALL grain from that owned card-field through
  `card_fields.remove_card_crop`, the non-take-removal chokepoint, so emptying
  the card's last grain fires its registered removal reactor (Crop Rotation
  Field's sow-or-decline offer). Every grain-bearing card-field in the catalog
  is single-stack, so removing the card's whole grain total is one chokepoint
  call.

Either way the player then gains 2 wood per grain removed. On the card path the
wood is granted BEFORE `remove_card_crop`, so if the chokepoint pushes a
decision frame (Crop Rotation Field's re-sow) that frame lands on the
already-updated state — the Craft Brewery ordering (`craft_brewery.py`,
`_side_effect`).

Card-game only: the minor spec, the play-variant registry entry, and any grain
on a card-field are all card-only / unowned in the Family game, so it stays
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import (
    card_holds,
    owned_card_fields,
    remove_card_crop,
)
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "thunderbolt"


def _board_grain_counts(p) -> set:
    """The distinct grain counts among this player's grain-bearing board FIELD
    cells (the equivalence classes the variants enumerate — ruling 2026-07-17,
    fields with the same count are interchangeable)."""
    return {
        cell.grain
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain >= 1
    }


def _grain_card_fields(p) -> list:
    """This player's owned card-fields currently holding >= 1 grain, in the
    canonical card-id order (`owned_card_fields` is sorted). Each is its OWN
    variant (ruling 45: a grain-holding card-field is "a field")."""
    return [cid for cid in owned_card_fields(p) if card_holds(p, cid, "grain") >= 1]


def _prereq(state: GameState, idx: int) -> bool:
    """1 Grain Field: at least one grain-bearing field — a board FIELD cell with
    grain, OR (ruling 45) a grain-holding card-field."""
    p = state.players[idx]
    return bool(_board_grain_counts(p)) or bool(_grain_card_fields(p))


def _variants(state: GameState, idx: int) -> list:
    """One zero-surcharge play-variant per removable field: "board:<count>" for
    each distinct grain count among the board fields, then "card:<card_id>" for
    each grain-holding card-field. Computed defensively from live state; the
    prereq guarantees the list is non-empty (a played Thunderbolt always has a
    field to strike). No skip variant — the removal is mandatory."""
    p = state.players[idx]
    variants = [f"board:{n}" for n in sorted(_board_grain_counts(p))]
    variants += [f"card:{cid}" for cid in _grain_card_fields(p)]
    return [(v, Resources()) for v in variants]


def _gain_wood(state: GameState, idx: int, n: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    if variant.startswith("card:"):
        cid = variant[len("card:"):]
        removed = card_holds(state.players[idx], cid, "grain")
        assert removed >= 1, f"thunderbolt: card-field {cid!r} holds no grain"
        # +2 wood per grain FIRST, so a chokepoint-pushed decision frame (Crop
        # Rotation Field's re-sow) lands on the already-updated state.
        state = _gain_wood(state, idx, 2 * removed)
        return remove_card_crop(state, idx, cid, "grain", removed)

    assert variant.startswith("board:"), f"thunderbolt: bad variant {variant!r}"
    count = int(variant[len("board:"):])
    p = state.players[idx]

    target = None
    for r, row in enumerate(p.farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type == CellType.FIELD and cell.grain == count:
                target = (r, c)
                break
        if target is not None:
            break
    assert target is not None, (
        f"thunderbolt: no board field holds {count} grain (variant {variant!r})"
    )

    tr, tc = target
    # Zero the representative field's grain. A pure crop edit on a FIELD cell —
    # no cell_type/fence change — so `pastures` rides along untouched via
    # fast_replace (the Farmyard.pastures caller-discipline contract).
    grid = tuple(
        tuple(
            fast_replace(cell, grain=0) if (r, c) == (tr, tc) else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return _gain_wood(state, idx, 2 * count)


# Free (no cost); passing/traveling; prereq = 1 grain field; no printed VP.
register_minor(CARD_ID, passing_left=True, prereq=_prereq, on_play=_on_play)
register_play_minor_variant(CARD_ID, _variants)
