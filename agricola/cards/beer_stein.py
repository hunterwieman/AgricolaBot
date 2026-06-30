"""Beer Stein (minor improvement, C61; Corbarius Expansion; cost 1 clay; no prereq).

Card text: "Each time you take a 'Bake Bread' action, you can use this card once to
turn 1 grain into 2 food and 1 bonus point."
Clarification: "You must bake normally to make this exchange."
Printed 0 VP (the bonus point is earned per exchange, not a flat printed score).

A "Food Provider" card with IDENTICAL mechanics to Baking Sheet (A30) — an OPTIONAL
after-action trigger that converts a resource and banks a bonus point per use. Beer
Stein differs from Baking Sheet only in its cost (1 clay vs none) and its lack of a
prerequisite (Baking Sheet requires "No Grain Field").

- **each Bake Bread** → an OPTIONAL trigger (`register`, not `register_auto` — the
  text says "you CAN use this card", so the player chooses) on the bake host's
  AFTER-phase (`after_bake_bread`). The before-phase of `PendingBakeBread` offers
  only FireTrigger + CommitBake (no Proceed/Stop), so the after-phase is reachable
  only once a normal bake has been committed — which is exactly what auto-satisfies
  the "you must bake normally to make this exchange" clarification (no separate
  guard is needed; the trigger only fires from a live, post-CommitBake frame).
  Using `before_bake_bread` would be wrong: it would let the exchange fire without a
  committed bake and could deplete grain the bake itself needs.
- when fired it pays exactly 1 grain and gains 2 food immediately, and BANKS 1
  bonus point in the per-card CardStore.
- **the bonus point** → BANKED in CardStore and read at scoring
  (`register_scoring`): a use-count-dependent quantity, so a flat `vps=` on the
  minor spec would wrongly award it without ever exchanging.

Once per Bake Bread action is automatic: `_apply_fire_trigger` stamps
`triggers_resolved` before applying, and `_eligible` reads it (each new Bake Bread
action gets a fresh `PendingBakeBread` with an empty `triggers_resolved`, so the
card re-becomes eligible per action — "each time you take a Bake Bread action").
The food (a resource bank) and the point (a CardStore bank) are always
accommodatable, so firing never dead-ends.

See baking_sheet.py (identical shape), loppers.py / big_country.py (CardStore bank +
register_scoring), and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "beer_stein"


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


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)))
register("after_bake_bread", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
