"""Working Gloves (minor improvement, E60; Ephipparius Expansion; Food Provider).

Card text (verbatim): "When you play this card, you get 1 food. Each time you pay an
occupation cost, you can pay 1 building resource of your choice in place of (up to)
2 food."
Cost: none. Prerequisite: none. No printed VPs. Kept (not traveling).

ON PLAY — +1 food (a plain goods gain).

THE SUBSTITUTION — a COST CONVERSION under `action_kind="play_occupation"` (ruling 67,
2026-07-20): "each time you pay an occupation cost" is exactly the play-occupation
chokepoint, where every way to pay the OCCUPATION COST PROPER (the frame's
route-supplied `PendingPlayOccupation.cost`) is enumerated, filtered for
affordability, and Pareto-pruned. One variant per building-resource type: 1 of that
resource replaces min(2, cost.food) food.

USER RULINGS built in (2026-07-20):
- **Always the maximum replacement.** "(up to) 2 food" — replacing fewer food for the
  same 1-resource price is strictly dominated (the Pareto prune would drop it anyway),
  so only the min(2, cost.food) variant is emitted. The occupation cost proper never
  exceeds 2 food anywhere in the catalog (the 2026-07-17 full-catalog scan: base
  Lessons ramps cap at 2 at 3-4 players; Moonshine/Writing Desk grant at 2; nothing
  raises occupation costs), so this card can always cover the whole food component.
- **Surcharges and individual printed costs are untouchable.** Roof Ballaster's
  optional food, Lover's/Game Catcher's printed costs, and every other "in addition
  to the occupation cost" payment live OUTSIDE the modifier pipeline (added at the
  debit, never in the conversion's `cost` argument) — separate costs, never reduced
  or modified, even when the code debits them in the same commit.
- **No dominated offers next to Forest School.** Both cards are conversions in the
  same pipeline, so their outputs compete in one frontier: on a 2-food cost this
  card's (1 wood) payment dominates Forest School's (2 wood) — pruned; on a 1-food
  cost the two wood variants are identical — de-duplicated. Firing both against one
  cost is inexpressible (a payment vector replaces each food unit at most once), so
  the trigger-model over-production loophole cannot arise.

The variants are emitted unfiltered (the expand1 contract — the chokepoint's
affordability filter handles a resource the player doesn't hold), and "each time you
pay an occupation cost" is inherently once per play (each payment enumeration is one
play's frontier). Card-only registries — the Family game is byte-identical and the
C++ differential gates are untouched. See forest_school.py (the sibling conversion)
and frame_builder.py (the conversion pattern).
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "working_gloves"

_TYPES = ("wood", "clay", "reed", "stone")


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card, you get 1 food." """
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _expand(state: GameState, idx: int, ctx, cost: Resources) -> list[Resources]:
    """Unchanged cost + one variant per building-resource type: 1 of it in place of
    min(2, cost.food) food. Only the maximum replacement is emitted (a smaller one is
    strictly dominated at the same 1-resource price — user ruling 2026-07-20)."""
    out = [cost]
    k = min(2, cost.food)
    if k >= 1:
        for rtype in _TYPES:
            out.append(cost - Resources(food=k) + Resources(**{rtype: 1}))
    return out


register_minor(CARD_ID, cost=Cost(), on_play=_on_play)
register_conversion("play_occupation", CARD_ID, _expand)
