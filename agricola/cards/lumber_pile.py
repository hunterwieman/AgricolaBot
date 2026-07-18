"""Lumber Pile (minor improvement, E76; Ephipparius Expansion; Building Resource
Provider).

Card text (verbatim): "When you play this card, you can immediately return up to
3 stables from your farmyard board to your supply and get 3 wood for each."
Cost: none. Prerequisite: none. VPs: none printed. Not passing.

User ruling 66 (2026-07-17): the on-play "immediately" here adds/changes nothing
— it is the ordinary at-play resolution of this optional effect, not a distinct
earlier instant (per the standing rule that every "immediately" gets its own
ruling, CARD_AUTHORING_GUIDE.md §2 — this occurrence collapses to plain "when you
play this card, you can ...").

Timing / firing kind — "When you play this card, you can ..." is an OPTIONAL
on-play choice, and per the standing ruling (2026-07-06) such on-play choices
surface WIDE: one `CommitPlayMinor(variant=...)` per route, via the minor
play-variant seam (`register_play_minor_variant`), rather than an after-play
trigger that could interleave with other cards. Here the routes are:
  - one variant per NON-EMPTY SUBSET of the player's built-stable cells, of size
    1..min(3, num_built) — "up to 3 stables"; and
  - "skip" (return nothing), always present, and the ONLY variant when no stable
    is built.
WHICH stables are returned is a genuine strategic choice — a fenced stable
doubles its pasture's capacity (RULES.md; `Pasture.capacity = 2·cells·2^stables`),
an unfenced stable is a flexible animal slot, and the vacated cell's future
differs — so the routes are enumerated over subsets, not collapsed to a count.
The variant string encodes the chosen cells: each cell as "row,col", cells joined
by "+" (canonically sorted), e.g. "0,3+1,2"; "skip" is the empty subset.

Every variant carries a ZERO surcharge (returning stables costs nothing — it
GIVES wood): the 3-wood-per-stable reward is granted in `on_play`, never as a
(nonsensical) negative surcharge. So the card is always playable (no cost, no
prereq, nothing to pay).

`on_play(state, idx, variant)`:
  - "skip" -> no change.
  - otherwise, for each named cell, set its grid cell STABLE -> EMPTY (the reverse
    of `_execute_build_stable`'s idiom) and recompute `Farmyard.pastures` ONCE from
    the arrays via `compute_pastures_from_arrays` — the caller-discipline
    maintenance contract for pasture-changing edits (ENGINE_IMPLEMENTATION.md §4.1).
    Removing a stable changes no fence, so each pasture's cell membership is
    unchanged; only the pasture's `num_stables` (and thus its capacity) drops, which
    the recompute picks up from the grid. Then grant 3 wood per stable returned.

`stables_in_supply` is DERIVED (`4 − stables_built − card-removed`), so emptying
the STABLE cells raises the supply automatically — nothing is stored, and a
returned stable can be built again later via Farm Expansion.

Capacity can DROP (a fenced stable's pasture halves per stable removed; an
unfenced stable's flexible slot disappears), so after a non-skip return `on_play`
flags the accommodation barrier (`animals_need_accommodation=True` — the standing
eviction idiom, Milking Place / Herbal Garden) when the player holds animals. The
engine re-checks the fit at the next decision boundary and surfaces the
keep-which choice (cooking the overflow) via `PendingAccommodate` if the animals
no longer fit. Animals are never trimmed here.

Family-inertness: minors exist only under `GameMode.CARDS`; the
`PLAY_MINOR_VARIANTS` registry entry is card-only and `animals_need_accommodation`
is a canonical-default-skip field, so the Family game is byte-identical and the
C++ gates are untouched.
"""
from __future__ import annotations

from itertools import combinations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import CellType
from agricola.pasture import compute_pastures_from_arrays
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import Cell, GameState

CARD_ID = "lumber_pile"

_MAX_RETURN = 3          # "up to 3 stables"
_WOOD_PER_STABLE = 3     # "get 3 wood for each"


def _built_stable_cells(state: GameState, idx: int) -> list[tuple[int, int]]:
    """The (row, col) of every STABLE cell on this player's board, sorted for a
    canonical variant encoding."""
    grid = state.players[idx].farmyard.grid
    return sorted(
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.STABLE
    )


def _encode(cells) -> str:
    """A subset of stable cells -> the variant string "r,c+r,c+..." (cells sorted)."""
    return "+".join(f"{r},{c}" for r, c in cells)


def _decode(variant: str) -> list[tuple[int, int]]:
    """Parse a non-"skip" variant string back into its (row, col) cells."""
    out = []
    for part in variant.split("+"):
        r, c = part.split(",")
        out.append((int(r), int(c)))
    return out


def _variants(state: GameState, idx: int):
    """One zero-surcharge route per non-empty subset of built-stable cells of size
    1..min(3, num_built) — "up to 3 stables" — plus an always-present zero-surcharge
    "skip" (return nothing; the only route when no stable is built)."""
    cells = _built_stable_cells(state, idx)
    out = [("skip", Resources())]
    for k in range(1, min(_MAX_RETURN, len(cells)) + 1):
        for subset in combinations(cells, k):
            out.append((_encode(subset), Resources()))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """Return the chosen stables to supply (STABLE -> EMPTY, pastures recomputed),
    grant 3 wood each, and flag the accommodation barrier if capacity may have
    dropped below the player's animal holdings."""
    if variant == "skip":
        return state

    cells = _decode(variant)
    p = state.players[idx]

    # Empty the named STABLE cells in one shot, then recompute the pasture cache
    # ONCE from the (fence-unchanged) arrays — the pasture-changing-edit contract.
    grid = tuple(
        tuple(
            Cell(cell_type=CellType.EMPTY) if (r, c) in cells else grid_cell
            for c, grid_cell in enumerate(row)
        )
        for r, row in enumerate(p.farmyard.grid)
    )
    new_farmyard = fast_replace(
        p.farmyard,
        grid=grid,
        pastures=compute_pastures_from_arrays(
            grid, p.farmyard.horizontal_fences, p.farmyard.vertical_fences),
    )
    p = fast_replace(
        p,
        farmyard=new_farmyard,
        resources=p.resources + Resources(wood=_WOOD_PER_STABLE * len(cells)),
    )
    # Capacity may have shrunk (a fenced stable halves its pasture; an unfenced one
    # is a flexible slot). Flag the barrier so the engine evicts/cooks the overflow
    # at the next decision boundary if the animals no longer fit — never trim here.
    if p.animals != Animals():          # Animals has no __bool__ — compare, don't truth-test
        p = fast_replace(p, animals_need_accommodation=True)

    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# No cost, no prerequisite, no printed VP; the wide on-play stable-return choice.
register_minor(CARD_ID, cost=Cost(), on_play=_on_play)
register_play_minor_variant(CARD_ID, _variants)
