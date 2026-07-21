"""Ash Trees (minor improvement, E74; Ephipparius; players -).

Card text: "When you play this card, immediately place (up to) 5 fences from your supply on
it. When you build fences, fences taken from this card cost you nothing."
Prerequisite: 2 planted fields (>= 2 fields each holding at least one crop — grain or veg).

Models fence pieces moving between LOCATIONS (the four a fence piece can be in: on the board /
removed / on a card / in supply). On play, up to 5 fences move FROM the player's SUPPLY pile
(`fences_in_supply`) ONTO the card — a persistent free-fence POOL in the player's CardStore
(keyed "ash_trees"). They remain part of the player's 15 (so the total can never exceed 15):
`helpers.buildable_fences` counts the pool as placeable, but placing one costs no wood. The
pool is the THIRD free-fence source (COST_MODIFIER_DESIGN.md §9.4), spent greedily AFTER
positional frees (Briar Hedge / Field Fences) and the per-action budget (Hedge Keeper), and
DECREMENTED as used (engine `_execute_build_pasture` CARDS branch via `spend_fence_pools`).
Its pieces come from the card, so the supply pile is NOT decremented for them, while
positional/budget frees waive only the wood and still draw a supply piece.

- on_play: move `min(5, fences_in_supply)` from the supply pile onto the card pool.
- prereq: 2+ planted fields (planted = sown, per the owner's ruling) — grid FIELD cells with
  a crop, PLUS the player's planted card-fields (ruling 45, 2026-07-12; verbatim quote in
  `_prereq_two_planted_fields`). A wood-planted Wood Field counts: it is a planted field.

No on-going effect beyond the pool. Card-only state (the pool lives in CardStore, default
empty → the Family game is byte-identical and the C++ gates are untouched). See
COST_MODIFIER_DESIGN.md §9 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_free_fence_pool
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "ash_trees"
POOL_KEY = "ash_trees"     # the CardStore slot holding the on-card fence pool
MAX_FENCES = 5


def _prereq_two_planted_fields(state: GameState, idx: int) -> bool:
    """Prerequisite "2 planted fields" — a play-time HAVE-check. Grid FIELD
    cells holding a crop count, and so do the player's planted card-fields.
    Ruling 45 (2026-07-12), verbatim: ""field TILES" means the plowed fields
    on the farmyard grid; "field" is the BROADER category and includes
    card-fields. So a card-field counts for field-count readers — the Fields
    scoring category and any "you need N fields" requirement — while per-TILE
    readers still exclude it (ruling 32 unchanged)." A wood-planted Wood Field
    IS a planted field (its own text says "plant"), and a multi-stack card
    counts exactly once (ruling 47, 2026-07-12)."""
    from agricola.cards.card_fields import planted_card_field_count
    p = state.players[idx]
    grid = p.farmyard.grid
    # A stone-holding field (Stone Clearing) IS planted — "considered planted
    # until the stone is gone" (its errata; user ruling 2026-07-20).
    planted = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].field_planted
    )
    return planted + planted_card_field_count(p) >= 2


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    moved = min(MAX_FENCES, p.fences_in_supply)     # "up to 5 from your supply"
    p = fast_replace(
        p,
        fences_in_supply=p.fences_in_supply - moved,
        card_state=p.card_state.set(POOL_KEY, moved),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, prereq=_prereq_two_planted_fields, on_play=_on_play)
register_free_fence_pool(CARD_ID, POOL_KEY)
