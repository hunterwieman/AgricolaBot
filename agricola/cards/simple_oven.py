"""Simple Oven (minor improvement, E64; Ephipparius Expansion; Food Provider).

Card text (verbatim): "For any “Bake Bread” action, you can convert exactly 1
grain into 3 food. When you build this improvement, you can immediately take a
“Bake Bread” action."

Cost: 2 Clay. Prerequisite: none. VPs: 1. Not passing.

A BAKING IMPROVEMENT (the Clay Oven / Stone Oven family), implemented as two
standing baking seams plus a one-shot, declinable on-build bake grant:

1. **The baking rate (`register_baking_spec_extension`).** For ANY Bake Bread
   action the owner takes, contribute a `(1, 3)` spec — at most 1 grain per
   action at 3 food/grain (cap 1 encodes "convert exactly 1 grain"). The greedy
   allocator in `_execute_bake` composes it with every other owned baking
   source (a Fireplace / Cooking Hearth / other oven) automatically, spending
   the highest-rate source's grain first.

2. **Reachability (`register_bake_bread_extension`).** A baking-spec extension
   ALONE does not make `_can_bake_bread` true — that predicate checks MAJOR
   improvements only. Like Baking Course, register the predicate too: an owner
   with >= 1 grain may take a Bake Bread action with no major improvement.
   Without it the rate above would be unreachable at the bake choose-points for
   an owner who holds no major oven.

3. **The free bake on build — an OPTIONAL granted sub-action (the Dwelling Plan
   / Field Fences pattern).** "When you build this improvement, you can
   immediately take a Bake Bread action" is a one-shot, DECLINABLE grant of a
   Bake Bread primitive tied to THIS card's own play. `on_play` unconditionally
   pushes the generic `PendingGrantedSubAction(subactions=("bake_bread",))`
   wrapper — the shared home for an optional grant of a mandatory-shaped
   primitive, where the decline lives at the wrapper's Stop (never a per-frame
   flag, so the inner `PendingBakeBread` keeps its committed shape). The wrapper
   is pushed AFTER the oven is in `minor_improvements`, so the enumerator's
   `bake_bread` eligibility (`_can_bake_bread`, which now sees this oven as a
   live baking improvement) is EXACT — no anticipatory grain proxy: with grain
   it offers `ChooseSubAction("bake_bread")` + Stop, with no grain only Stop (a
   singleton the agent auto-skips). Choosing pushes the real `PendingBakeBread`
   carrying this card's provenance, so it bakes at THIS oven's rate and
   before/after-bake card hooks fire normally.

Both baking seams self-gate on ownership, and the on-build grant fires only from
this card's own play, so unowned the card is inert and the Family game (which
plays no minors) is untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.legality import (
    register_bake_bread_extension,
    register_baking_spec_extension,
)
from agricola.pending import PendingGrantedSubAction, push
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "simple_oven"
_FOOD_PER_GRAIN = 3


def _baking_spec(state: GameState, player_idx: int) -> list[tuple]:
    """"Convert exactly 1 grain into 3 food" for ANY Bake Bread action the
    owner takes: a (cap 1, rate 3) source while the card is in play. Cap 1
    encodes "exactly 1 grain"; the greedy allocator composes it with any other
    owned baking source."""
    p = state.players[player_idx]
    return [(1, _FOOD_PER_GRAIN)] if CARD_ID in p.minor_improvements else []


def _can_bake_bread_extension(state: GameState, p: PlayerState) -> bool:
    """The owner IS a baking source, so grain alone suffices to take a Bake
    Bread action (no MAJOR improvement needed) — the reachability half that a
    baking-spec extension cannot supply on its own (`_can_bake_bread` checks
    majors only), exactly as Baking Course registers."""
    return CARD_ID in p.minor_improvements and p.resources.grain >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """The one-shot on-build bake grant: push the generic optional-grant wrapper
    for a Bake Bread (the Dwelling Plan pattern). The card is already in
    `minor_improvements` by now, so the wrapper's `bake_bread` eligibility
    (`_can_bake_bread`) is exact — it offers the bake only when the player has
    grain, and only Stop (decline) otherwise. Choosing pushes the real
    `PendingBakeBread` at this oven's rate; the wrapper hosts the decline."""
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id="card:" + CARD_ID,
        subactions=("bake_bread",)))


# Cost 2 clay; no prerequisite; 1 printed VP.
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2)),
    vps=1,
    on_play=_on_play,
)

# Effect 1 — the (cap 1, rate 3) baking source for every Bake Bread action.
register_baking_spec_extension(_baking_spec)
# Effect 2 — the action's reachability for a major-oven-less owner.
register_bake_bread_extension(_can_bake_bread_extension)
# Effect 3 (the free bake on build) is the wrapper `_on_play` pushes — no
# standing registration; the shared PendingGrantedSubAction dispatch hosts the
# offer/decline and the bake push.
