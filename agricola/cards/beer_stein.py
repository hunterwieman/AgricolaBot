"""Beer Stein (minor improvement, C61; Corbarius Expansion; cost 1 clay; no prereq).

Card text: "Each time you take a 'Bake Bread' action, you can use this card once to
turn 1 grain into 2 food and 1 bonus point."
Clarification: "You must bake normally to make this exchange."
Printed 0 VP (the bonus point is earned per exchange, not a flat printed score).

A "Food Provider" card with IDENTICAL mechanics to Baking Sheet (A30) — an OPTIONAL
trigger that converts a resource and banks a bonus point per use. Beer Stein differs
from Baking Sheet only in its cost (1 clay vs none) and its lack of a prerequisite
(Baking Sheet requires "No Grain Field").

- **each Bake Bread** → an OPTIONAL trigger (`register`, not `register_auto` — the
  text says "you CAN use this card", so the player chooses) on the bake host's
  BEFORE-phase (`before_bake_bread`). The Trigger-Timing ruling is that a bare
  "each time you take a 'Bake Bread' action" fires in the BEFORE phase, before the
  bake resolves — the reward is FLAT ("turn 1 grain into 2 food and 1 bonus point"),
  so it never needs to read what the bake produced and has no reason to be `after`.
  The "you must bake normally to make this exchange" clarification is a GATE (a real
  bake must happen), NOT an ordering that pushes the exchange after the bake: the
  `PendingBakeBread` before-phase offers only FireTrigger + CommitBake (no Stop), so
  a bake is still structurally forced after the exchange fires.
- **the stranding guard** → because a bake is forced and the exchange spends 1 grain
  BEFORE that bake, eligibility must ensure a legal bake still remains after the −1.
  A normal bake needs ≥1 grain, so the exchange requires `grain >= 2`: one grain is
  consumed by the exchange and at least one remains to satisfy the mandatory bake.
  (At `grain == 1` firing would leave 0 grain and strand the forced CommitBake.)
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
register_scoring), and CARD_AUTHORING_GUIDE.md ("Each time you [take / use / do X]"
fires BEFORE X — including the Beer Stein gate-not-ordering blockquote).
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
# Trigger: optional, fires on the bake host's before-phase, once per action.
# ---------------------------------------------------------------------------

def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional, once per Bake Bread action. Fires BEFORE the bake, so it must leave
    # enough grain for the still-mandatory bake: the exchange spends 1 grain and a
    # normal bake needs ≥1 more, so require grain >= 2 (else firing strands the
    # forced CommitBake). This grain>=2 guard also satisfies the "must bake normally"
    # gate — a real bake is structurally forced after the exchange.
    return CARD_ID not in triggers_resolved and state.players[idx].resources.grain >= 2


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
register("before_bake_bread", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
