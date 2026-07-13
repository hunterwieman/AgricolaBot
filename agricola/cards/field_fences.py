"""Field Fences (minor improvement, C16; Consul Dirigens; players -).

Card text: "You can immediately take a 'Build Fences' action, during which you do not have
to pay wood for fences that you build next to field tiles."
Cost: 2 Food. No prerequisite; kept (not traveling); no printed VPs.

Two mechanisms:
- an OPTIONAL GRANT of a Build Fences action (on play): "you CAN take a Build Fences action"
  is optional, so `_on_play` pushes the thin generic `PendingGrantedSubAction(subaction=
  "build_fences")` choose-or-decline wrapper (NOT the build host directly — that would force
  the build). The wrapper offers
  ChooseSubAction("build_fences") when a pasture is buildable under this grant's discount, else
  only Stop (decline). Choosing build_fences pushes the real multi-shot `PendingBuildFences`
  with `initiated_by_id="card:field_fences"` and `build_fences_action=True` (the LITERAL Build
  Fences action — action-scoped frees like Hedge Keeper's +3 still apply, seeded then via
  `free_fence_budget_for`); in CARDS mode the deferred-tally settle pays the (discounted) bill
  at the Proceed flip. The on_play runs AFTER the play host flips to its after-phase, so the
  wrapper lands on top of it (the nested walk: optionally build, the inner host pops, the
  wrapper pops, the play host's after-phase Stop pops it).
- a POSITIONAL per-edge discount SCOPED TO THIS GRANT: every new fence edge "next to a field
  tile" costs no wood. A new edge is next to a field iff the cell on the FAR side of it (the
  one outside the pasture) is a FIELD; since pasture cells are never fields (only EMPTY/STABLE
  are enclosable — `_enclosable_cells_bm`), "the far side is a field" is just "either bordering
  cell is a field," so the edge fn needs no cells_bm. The discount is gated on
  `initiated_by_id == "card:field_fences"`, so it applies ONLY during this card's own granted
  action — never a Fencing-space or Farm-Redevelopment build. Because the discount makes more
  commits affordable, a Field-Fences-initiated Build Fences has a possibly LARGER legal set
  than a normal one; the during-building enumerator AND the forfeit anticipation
  (`_any_legal_pasture_commit`) both thread the frame's `initiated_by_id` through the
  positional fold, so both see the discount.

The 2-food cost is paid on the play-minor path. Card-only state (empty registries in the
Family game), so the Family game is byte-identical and the C++ gates are untouched. See
COST_MODIFIER_DESIGN.md §9 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_free_fence_edges
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.fences import NUM_COLS, NUM_ROWS
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "field_fences"
FRAME_ID = "card:field_fences"   # the granted Build Fences frame's initiated_by_id


def _on_play(state: GameState, idx: int) -> GameState:
    from agricola.pending import PendingGrantedSubAction, push
    # "You CAN take a Build Fences action" — OPTIONAL. Push the generic choose-or-decline
    # wrapper (not the build host directly); it offers ChooseSubAction("build_fences") when a
    # pasture is buildable under this grant's field-adjacency discount, else only Stop
    # (decline). The wrapper's build_fences choice pushes the real PendingBuildFences with
    # initiated_by_id FRAME_ID, seeding any other card's free-fence budget at that point.
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id=FRAME_ID, subaction="build_fences"))


def _field_adjacent_edges(farmyard, h_new: int, v_new: int, *, initiated_by_id, **_kw):
    """The new edges next to a field tile — free ONLY during this card's own grant."""
    if initiated_by_id != FRAME_ID:
        return (0, 0)
    grid = farmyard.grid

    def _is_field(r: int, c: int) -> bool:
        return (0 <= r < NUM_ROWS and 0 <= c < NUM_COLS
                and grid[r][c].cell_type == CellType.FIELD)

    h_free = 0
    b = h_new
    while b:
        bit = b & -b
        r, c = divmod(bit.bit_length() - 1, NUM_COLS)       # h-edge between (r-1,c) and (r,c)
        if _is_field(r - 1, c) or _is_field(r, c):
            h_free |= bit
        b &= b - 1
    v_free = 0
    b = v_new
    while b:
        bit = b & -b
        r, c = divmod(bit.bit_length() - 1, NUM_COLS + 1)   # v-edge between (r,c-1) and (r,c)
        if _is_field(r, c - 1) or _is_field(r, c):
            v_free |= bit
        b &= b - 1
    return (h_free, v_free)


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)), on_play=_on_play)
register_free_fence_edges(CARD_ID, _field_adjacent_edges)
