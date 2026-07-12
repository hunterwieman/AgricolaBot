"""Straw Manure (minor improvement, D70; Dulcinaria Expansion; Crop Provider).

Card text (verbatim): "Before the field phase of each harvest, you can pay 1
grain from your supply to add 1 vegetable to each of up to 2 vegetable fields."

Cost: none (card JSON cost=null). Printed VPs: 0 (vps=null). Prerequisite:
"2 Fields". Not passing.

TIMING — window #3 ``before_field_phase`` (HARVEST_WINDOWS_DESIGN.md §1 ladder
lists Straw Manure as the sole census member of window #3, and §11 "Fields mutate
outside the field phase" names it explicitly: "Straw Manure adds vegetables at
#3"). The printed "Before the field phase of each harvest" maps to the ladder's
``before_field_phase`` window, which opens inside the per-player FIELD segment
(ruling 3, 2026-07-03: the starting player resolves their WHOLE FIELD segment —
windows #3..#7 — before the other player's begins, so the two players' #3 frames
never coexist) and BEFORE window #5's mechanical crop take. Adding vegetables here
means they are on the fields when the take runs, so the take then harvests one
vegetable from each boosted field like any other planted field — exactly the
printed sequence.

DECLINABLE ("you can") — an optional trigger surfaced on the per-player
``PendingHarvestWindow`` frame; ``Proceed`` declines. Once per window is automatic
(the frame's ``triggers_resolved`` records the fire, so it cannot fire twice in
one harvest's window #3).

THE CHOICE — "add 1 vegetable to each of up to 2 vegetable fields" is a choice of
WHICH vegetable fields (and how many, 1 or 2) to boost; the grain cost is a flat 1
regardless of how many fields are chosen. The fields are NOT interchangeable — the
identity of the boosted targets changes the game state (and what window #5's take
then reads per field) — so the choice is modeled as a play-VARIANT trigger
(``register_play_variant_trigger``) enumerating the actual target subsets, not
merely a count. Each variant is one non-empty subset (size 1 or 2) of the player's
vegetable fields, joined by ``"|"``: a grid field is the token ``"r-c"`` (cells in
row-major order), a card-field is the token ``"card:<card_id>"`` (id-sorted, after
the cells). A card target is always its own distinct token keyed by card id, never
merged with a grid cell holding the same vegetable count — vegetables added to a
card feed card-level readers (``card_holds``) and the card's own triggers, so the
two are different game states even when the take yields the same crop. Declining
(adding to zero fields, which pays 1 grain for nothing) is never a distinct variant
— it is the frame's ``Proceed``, so no grain is spent when nothing is added.

"Vegetable field" — anything from the broad "field" category currently holding at
least 1 vegetable. **Ruling 45 (2026-07-12), verbatim: ""field TILES" means the
plowed fields on the farmyard grid; "field" is the BROADER category and includes
card-fields. So a card-field counts for field-count readers — the Fields scoring
category and any "you need N fields" requirement — while per-TILE readers still
exclude it (ruling 32 unchanged)."** This card says "vegetable fields", never
"tiles", so its targets are: a FIELD grid cell with ``cell.veg > 0``, and an owned
card-field with ``card_holds(p, cid, "veg") >= 1`` (a Beanfield with vegetables on
it IS a vegetable field). A grain field, a wood/stone-planted card-field, and an
empty field of either kind are not legal targets. "Add 1 vegetable" increments a
grid target's ``veg`` by 1, or adds 1 veg to a card target's veg-bearing stack
(``stack_with`` + ``stacks_to_store``); fields carry no hard crop cap in this
engine — the 2-veg sowing limit bounds only the sow action, not card effects that
add crops.

"2 Fields" prerequisite — a play-time HAVE-check that the player owns at least 2
fields, never spent: FIELD grid cells (any field tiles, planted or not; the same
shape as Cesspit's "2 Fields") PLUS owned card-fields at 1 per card (ruling 45
above — bare "Fields" is the broad category; per ruling 47, 2026-07-12, a
multi-stack card-field is "considered 1 field" and counts exactly once). Distinct
from the veg-field targets the trigger reads at harvest time.

Family states are untouched — the card exists only in Cards mode and every
card-field path is ownership-gated (a player with no card-fields reads/writes no
CardStore) — so the C++ differential gates are unaffected. The only card state this
module writes is a chosen card-field target's stack (+1 veg); no scoring term.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "straw_manure"
WINDOW_ID = "before_field_phase"

_GRAIN_COST = 1
_MAX_TARGETS = 2


def _prereq_two_fields(state: GameState, idx: int) -> bool:
    """Prerequisite "2 Fields": at least 2 fields — FIELD grid cells (any field
    tiles, planted or empty; the crop is irrelevant — matches Cesspit's "2
    Fields") plus owned card-fields at 1 per card (ruling 45, 2026-07-12: bare
    "fields" is the broad category and includes card-fields; ruling 47,
    2026-07-12: a multi-stack card counts once)."""
    from agricola.cards.card_fields import card_field_count

    p = state.players[idx]
    grid = p.farmyard.grid
    fields = sum(
        1 for row in grid for cell in row if cell.cell_type is CellType.FIELD
    )
    return fields + card_field_count(p) >= 2


def _veg_field_cells(state: GameState, idx: int) -> list[tuple[int, int]]:
    """The player's grid vegetable fields (FIELD cells holding >= 1 veg),
    row-major."""
    grid = state.players[idx].farmyard.grid
    return [
        (r, c)
        for r in range(len(grid))
        for c in range(len(grid[r]))
        if grid[r][c].cell_type is CellType.FIELD and grid[r][c].veg > 0
    ]


def _veg_card_fields(state: GameState, idx: int) -> list[str]:
    """The player's vegetable card-fields (owned card-fields holding >= 1 veg),
    sorted by card id. Per ruling 45 (2026-07-12) a veg-holding card-field IS a
    "vegetable field" — this card never says "tile" — so it is a legal +1-veg
    target; a wood/stone/grain-holding or empty card-field is not."""
    from agricola.cards.card_fields import card_holds, owned_card_fields

    p = state.players[idx]
    return [
        cid for cid in owned_card_fields(p) if card_holds(p, cid, "veg") >= 1
    ]


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Usable iff the player can pay the 1 grain AND has at least one vegetable
    field — grid or card (ruling 45, 2026-07-12) — to add to (adding to zero
    fields is never worth 1 grain and is not a legal "use" — it is the frame's
    Proceed). Ownership and the once-per-window guard are enforced by the host
    enumerator (``_owns`` + ``triggers_resolved``)."""
    if state.players[idx].resources.grain < _GRAIN_COST:
        return False
    return (
        len(_veg_field_cells(state, idx)) + len(_veg_card_fields(state, idx)) >= 1
    )


def _variants(state: GameState, idx: int) -> list[str]:
    """Every non-empty subset (size 1 or up to 2) of the player's vegetable
    fields, as tokens joined by ``"|"``: grid cells as ``"r-c"`` (row-major),
    card-fields as ``"card:<card_id>"`` (id-sorted, after the cells; ruling 45,
    2026-07-12). Each card target is its own distinct token — never merged with
    a same-count grid cell (the docstring's non-interchangeability note). Empty
    when the grain is unaffordable or there is no vegetable field (the
    enumerator then surfaces no fire, only Proceed)."""
    if state.players[idx].resources.grain < _GRAIN_COST:
        return []
    tokens = [f"{r}-{c}" for (r, c) in _veg_field_cells(state, idx)]
    tokens += [f"card:{cid}" for cid in _veg_card_fields(state, idx)]
    out: list[str] = list(tokens)                         # boost exactly this one
    for i, a in enumerate(tokens):
        for b in tokens[i + 1:]:                          # boost this pair
            out.append(f"{a}|{b}")
    return out


def _parse(variant: str) -> list[tuple]:
    """Variant tokens back to targets: ``"r-c"`` -> ("cell", (r, c));
    ``"card:<id>"`` -> ("card", card_id)."""
    targets: list[tuple] = []
    for token in variant.split("|"):
        if token.startswith("card:"):
            targets.append(("card", token[len("card:"):]))
        else:
            r, c = token.split("-")
            targets.append(("cell", (int(r), int(c))))
    return targets


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Pay 1 grain from supply; add 1 vegetable to each chosen vegetable field.

    The chosen targets are always current vegetable fields (the variant
    enumerator only ever produced veg-holding grid cells / card-fields for this
    state), and there are at most 2 of them (``_MAX_TARGETS``), all distinct.
    The grain cost is flat regardless of the target count. A grid target's cell
    gains 1 veg; a card target (ruling 45, 2026-07-12) gains 1 veg on its
    veg-bearing stack — today at most one stack of a card can hold veg (only
    1-stack specs whitelist veg sows, and a stack never mixes crops with
    wood/stone), so "the first veg-bearing stack in canonical order" is
    unambiguous; the store write re-canonicalizes either way."""
    from agricola.cards.card_fields import (
        GOODS,
        card_field_stacks,
        stack_with,
        stacks_to_store,
    )

    targets = _parse(variant)
    assert 1 <= len(targets) <= _MAX_TARGETS, f"illegal straw_manure targets {variant!r}"
    p = state.players[idx]
    resources = p.resources - Resources(grain=_GRAIN_COST)

    cell_targets = {t for kind, t in targets if kind == "cell"}
    farmyard = p.farmyard
    if cell_targets:
        new_grid = tuple(
            tuple(
                fast_replace(cell, veg=cell.veg + 1) if (r, c) in cell_targets else cell
                for c, cell in enumerate(row)
            )
            for r, row in enumerate(farmyard.grid)
        )
        farmyard = fast_replace(farmyard, grid=new_grid)

    card_state = p.card_state
    veg_i = GOODS.index("veg")
    for kind, cid in targets:
        if kind != "card":
            continue
        # Targets are distinct cards (the enumerator never pairs a card with
        # itself), so reading each card's stacks off the pre-apply player is safe.
        stacks = list(card_field_stacks(p, cid))
        for i, stack in enumerate(stacks):
            if stack[veg_i] >= 1:
                stacks[i] = stack_with(stack, "veg", 1)
                break
        else:
            raise AssertionError(f"straw_manure card target {cid!r} holds no veg")
        card_state = stacks_to_store(card_state, cid, stacks)

    p = fast_replace(p, resources=resources, farmyard=farmyard, card_state=card_state)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), prereq=_prereq_two_fields)
# Optional play-variant trigger on window #3 (before_field_phase): pay 1 grain,
# add 1 veg to each of up to 2 chosen vegetable fields; once per harvest.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
