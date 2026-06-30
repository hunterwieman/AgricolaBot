"""Bucksaw (minor improvement, A37; Artifex Expansion; cost 1 wood).

Card text: "Each time you renovate, you can also pay 1 wood to get 1 bonus point
and 1 grain." Printed 0 VP (the point is earned per renovate, not flat).

A "Points Provider" card combining two established shapes:

- **each renovate** → an OPTIONAL trigger (`register`, not `register_auto` — the
  text says "you CAN also pay", so the player chooses) on `after_renovate`. When
  fired it pays 1 wood and gains 1 grain immediately, and BANKS 1 bonus point in
  the per-card CardStore. (Mirrors Mining Hammer's `after_renovate` granted effect;
  the "pay 1 wood → get 1 grain" swap is an effect-internal charge subtracted
  directly in `_apply`, like Paper Maker — NOT a build cost routed through the
  cost-modifier pipeline.)
- **the bonus point** → BANKED in CardStore and read at scoring (`register_scoring`),
  exactly like Big Country: a renovate-count-dependent quantity, so a flat `vps=`
  on the minor spec would wrongly award it without ever renovating.

Once per renovate is automatic: `_apply_fire_trigger` stamps `triggers_resolved`
before applying, and `_eligible` reads it. The grain (a resource bank) and the
point (a CardStore bank) are always accommodatable, so firing never dead-ends.

`after_renovate` (not before) matches the renovate-hook convention (Mining Hammer /
Roughcaster / Millwright all hook the renovate after-phase). See
CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "bucksaw"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional, once per renovate, only when the 1-wood charge is payable.
    return CARD_ID not in triggers_resolved and state.players[idx].resources.wood >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=1) + Resources(grain=1),
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    # The banked bonus points (1 per fired renovate).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register("after_renovate", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
