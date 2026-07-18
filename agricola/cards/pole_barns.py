"""Pole Barns (minor improvement, E1; Ephipparius Expansion; Farm Planner; players -).

Card text (verbatim): "You can immediately build up to 3 stables at no cost. (You must
pay the cost of this card though.)"
Cost: 2 Wood. Prerequisite: "15 Fences Built". PASSING (traveling minor —
`passing_left='X'`: after the on-play effect the card moves to the opponent's hand; the
hand-transfer in `_execute_play_minor` PRECEDES `on_play`, so the pushed build resolves
for the player who played it).

USER RULINGS (2026-07-17):
- **This is NOT a "Build Stables action."** The card lets the player build stables as a
  CARD EFFECT, not via the named "Build Stables" action — so the pushed
  `PendingBuildStables` carries `build_stables_action=False`. Cards keyed to the literal
  "Build Stables" ACTION therefore never fire on it (mirrors Stable C2 / Stallwright E89);
  a verb-keyed card ("each time you build a stable") still fires, correctly.
- **Ruling 66:** the on-play "immediately" adds/changes nothing here.

Classification (CARD_AUTHORING_GUIDE.md framework):
- Minor; cost 2 wood; prereq "15 Fences Built"; passing.
- **Prereq — "15 Fences Built"** means all 15 fence pieces are ON the farmyard. Counted
  from the farmyard's fence arrays via `helpers.fences_built(farmyard) >= 15` — a play-time
  HAVE-check, never spent. NOT `fences_in_supply == 0`, which is wrong once a card (Ash
  Trees) holds fence pieces off-supply.
- **Timing — on-play, one-time.** "You can ... build up to 3 stables" is an OPTIONAL grant,
  and per the standing "on-play optional choices surface WIDE" ruling the choice is surfaced
  via the minor play-variant seam (`register_play_minor_variant`), not an after-play trigger:
    - **"build"** — offered only when >= 1 stable is placeable RIGHT NOW (a legal empty cell
      AND >= 1 stable in supply), checked with the engine's own free-cost stable predicate
      `_can_build_stable(state, p, Resources())`. Zero surcharge.
    - **"skip"** — always offered (zero surcharge). "up to 3" includes 0; a player who wants
      no stable declines here, and this keeps the card playable (still paying its 2-wood
      cost) even when no stable can be built.
  Both variants are zero-surcharge: the 2-wood card cost is paid by the normal play-minor
  path, and the stables themselves are free.
- **Firing** — "build" pushes the reusable `PendingBuildStables` primitive with
  `cost=Resources()` (free stables), `max_builds=3`, `build_stables_action=False`. The
  multi-shot host offers cell commits while `num_built < 3` and `Proceed` once
  `num_built >= 1`, so building 1, 2, or 3 then stopping needs no new code. Because the
  "build" variant is only offered when a stable is placeable, entering it can never deadlock
  at `num_built=0` (the enumerator offers no Proceed there).

Card-only state is empty; `build_stables_action` is an unrestricted-default canonical
skip-field. Family byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.helpers import fences_built
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "pole_barns"
FRAME_ID = "card:pole_barns"
_FREE = Resources()


def _prereq(state: GameState, idx: int) -> bool:
    """"15 Fences Built" — all 15 fence pieces placed on the farmyard, counted from the
    fence arrays (`fences_built`). A play-time HAVE-check, never spent. NOT
    `fences_in_supply == 0` (wrong once a card holds fence pieces off-supply)."""
    return fences_built(state.players[idx].farmyard) >= 15


def _variants(state: GameState, idx: int):
    """Wide on-play choice: "skip" (always, zero surcharge) + "build" (zero surcharge,
    offered only when a FREE stable is placeable now — the engine's own predicate at zero
    cost, so entering the grant never deadlocks at num_built=0)."""
    out = [("skip", _FREE)]
    if _can_build_stable(state, state.players[idx], _FREE):
        out.append(("build", _FREE))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """"build" pushes the free, up-to-3 stable grant (a card effect, not the literal Build
    Stables action); "skip" is a no-op."""
    if variant == "build":
        return push(state, PendingBuildStables(
            player_idx=idx, initiated_by_id=FRAME_ID,
            cost=_FREE, max_builds=3, build_stables_action=False))
    return state


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    prereq=_prereq,
    passing_left=True,
    on_play=_on_play,
)
register_play_minor_variant(CARD_ID, _variants)
