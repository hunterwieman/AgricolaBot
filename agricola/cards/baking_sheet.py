"""Baking Sheet (minor improvement, A30; Artifex Expansion; no cost).

Card text: "Each time you take a 'Bake Bread' action, you can use this card to
exchange exactly 1 grain for 2 food and 1 bonus point."
Clarification: "You must bake normally to make this exchange."
Prerequisite: "No Grain Field" (you have no field with grain on it). Printed 0 VP
(the bonus point is earned per exchange, not a flat printed score).

A "Points Provider" card, the same shape as Bucksaw — an OPTIONAL after-action
trigger that converts a resource and banks a bonus point per use:

- **each Bake Bread** → an OPTIONAL trigger (`register`, not `register_auto` — the
  text says "you CAN use this card", so the player chooses) on the bake host's
  AFTER-phase (`after_bake_bread`). The before-phase of `PendingBakeBread` offers
  only FireTrigger + CommitBake (no Proceed/Stop), so the after-phase is reachable
  only once a normal bake has been committed — which is exactly what auto-satisfies
  the "you must bake normally to make this exchange" clarification (no separate
  guard is needed; the trigger only fires from a live, post-CommitBake frame).
- when fired it pays exactly 1 grain and gains 2 food immediately, and BANKS 1
  bonus point in the per-card CardStore.
- **the bonus point** → BANKED in CardStore and read at scoring
  (`register_scoring`), exactly like Bucksaw / Big Country: a use-count-dependent
  quantity, so a flat `vps=` on the minor spec would wrongly award it without ever
  exchanging.

Once per Bake Bread action is automatic: `_apply_fire_trigger` stamps
`triggers_resolved` before applying, and `_eligible` reads it (each new Bake Bread
action gets a fresh `PendingBakeBread` with an empty `triggers_resolved`, so the
card re-becomes eligible per action — "each time you take a Bake Bread action").
The food (a resource bank) and the point (a CardStore bank) are always
accommodatable, so firing never dead-ends.

"No Grain Field" — the prerequisite is checked at PLAY time: the player must own no
field cell that currently holds grain (a vegetable field, with grain == 0, does not
count). See CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "baking_sheet"


# ---------------------------------------------------------------------------
# Prerequisite: "No Grain Field" — no field cell currently holds grain.
# ---------------------------------------------------------------------------

def _no_grain_field(state: GameState, idx: int) -> bool:
    grid = state.players[idx].farmyard.grid
    return all(
        not (cell.cell_type is CellType.FIELD and cell.grain > 0)
        for row in grid
        for cell in row
    )


# ---------------------------------------------------------------------------
# Trigger: optional, fires on the bake host's after-phase, once per action.
# ---------------------------------------------------------------------------

def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional, once per Bake Bread action, only when 1 grain is available to
    # exchange. (The "must bake normally" clarification is satisfied structurally:
    # the after_bake_bread phase is only reached after a CommitBake.)
    return CARD_ID not in triggers_resolved and state.players[idx].resources.grain >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(grain=-1, food=2),
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    # The banked bonus points (1 per fired exchange).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, prereq=_no_grain_field)
register("after_bake_bread", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
