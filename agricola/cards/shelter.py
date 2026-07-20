"""Shelter (minor improvement, A1; Artifex Expansion; Farm Planner; players -).

Card text (verbatim): "You can immediately build a stable at no cost, but only
if you place it in a pasture covering exactly 1 farmyard space."
Cost: none. Prerequisite: none. PASSING (traveling minor — `passing_left=True`:
after the on-play effect the card moves to the opponent's hand; the hand-transfer
in `_execute_play_minor` PRECEDES `on_play`, so the pushed build resolves for the
player who played it).

USER RULINGS (2026-07-20):
- **Optional on-play grant → surfaces WIDE.** "You can immediately build a
  stable" is an OPTIONAL grant, so per the standing "on-play optional choices
  surface WIDE" ruling the choice is surfaced via the minor play-variant seam
  (`register_play_minor_variant`), never an after-play trigger:
    - **"build"** — offered only when a QUALIFYING cell exists (see below) AND
      the player has >= 1 stable in supply (`helpers.stables_in_supply`). Zero
      surcharge; the stable is free, so there is no affordability gate.
    - **"decline"** — always offered (zero surcharge). "You can" includes not
      building; declining keeps the (costless) card playable even when no stable
      can be placed.
- **Qualifying cells** — the cells of pastures covering EXACTLY 1 farmyard space
  that do not already contain a stable (max 1 stable per cell). Derived from
  `player.farmyard.pastures` (a pasture's `cells` + `num_stables`), NEVER from
  `cell_type` alone: a fenced-but-empty cell reads EMPTY, so cell_type cannot
  tell you a cell's pasture membership — only the pasture decomposition can. A
  1-cell pasture encloses exactly one EMPTY-or-STABLE cell (rooms/fields cannot
  be fenced, `_enclosable_cells_bm`), so `num_stables == 0` on a 1-cell pasture
  means its single cell is EMPTY and therefore a legal stable target — the
  offer can never deadlock at num_built=0. Computed at variant/push time; farm
  geometry cannot change between the offer and the push (same instant).
- **Firing** — "build" pushes the reusable `PendingBuildStables` primitive with
  `cost=Resources()` (free stable), `max_builds=1` (exactly one stable), and
  `allowed_cells=<qualifying cells>`. The multi-shot host's enumerator
  (`_enumerate_pending_build_stables`) intersects those cells with the legal
  stable cells, offers CommitBuildStable there, then Proceed once num_built>=1.
  Placing the free stable in a 1-cell pasture doubles that pasture's capacity
  (`capacity = 2 * num_cells * 2**num_stables`).

Card-only: no `CardStore`, no scoring term (no VP). `allowed_cells` is a
Family-constant canonical-skip field, so the Family game is byte-identical and
the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.helpers import stables_in_supply
from agricola.pending import PendingBuildStables, push
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "shelter"
FRAME_ID = "card:shelter"
_FREE = Resources()


def _qualifying_cells(player: PlayerState) -> tuple:
    """Cells of pastures covering exactly 1 farmyard space that do not already
    contain a stable. Derived from the pasture decomposition (cells +
    num_stables), never from cell_type (a fenced empty cell reads EMPTY, so it
    cannot reveal pasture membership). A 1-cell pasture with num_stables==0
    encloses one EMPTY cell (rooms/fields cannot be enclosed), so every returned
    cell is a legal stable target."""
    return tuple(
        next(iter(p.cells))
        for p in player.farmyard.pastures
        if len(p.cells) == 1 and p.num_stables == 0
    )


def _variants(state: GameState, idx: int):
    """Wide on-play choice: "decline" (always, zero surcharge) + "build" (zero
    surcharge, offered only when a qualifying 1-cell pasture has room for a free
    stable AND a stable is in supply). The free stable has no affordability
    gate."""
    out = [("decline", _FREE)]
    p = state.players[idx]
    if _qualifying_cells(p) and stables_in_supply(p) >= 1:
        out.append(("build", _FREE))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """"build" pushes the free, single, cell-restricted stable grant; "decline"
    is a no-op. Qualifying cells are recomputed here — same instant as the
    offer, so geometry is identical."""
    if variant == "build":
        return push(state, PendingBuildStables(
            player_idx=idx, initiated_by_id=FRAME_ID,
            cost=_FREE, max_builds=1,
            # A card-effect build, NOT the literal "Build Stables" action — the
            # same classification as the identically-worded grants (Pole Barns,
            # Stable, Stallwright), per the field's §9.6 purpose: cards keyed to
            # the literal action must not fire on a grant.
            build_stables_action=False,
            allowed_cells=_qualifying_cells(state.players[idx])))
    return state


# No cost, no prereq, no printed VP; passing (traveling minor).
register_minor(
    CARD_ID,
    cost=Cost(),
    passing_left=True,
    on_play=_on_play,
)
register_play_minor_variant(CARD_ID, _variants)
