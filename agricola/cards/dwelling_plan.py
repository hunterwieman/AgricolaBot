"""Dwelling Plan (minor improvement, D2; Dulcinaria Expansion; cost 1 food).

Card text: "You can immediately take a 'Renovation' action."

No prerequisite, no printed VPs, not a passing/traveling card.

Category 4 (granted sub-action) — an OPTIONAL on-play grant of a single Renovate
primitive. "You can ... take" is the standard optional wording, so the renovation
is DECLINABLE.

Optionality is the whole trap here. PendingRenovate's before-phase enumerator
(`_enumerate_pending_renovate`) offers a CommitRenovate per legal target but NO
Stop — the renovate cannot be declined once that frame is pushed. So we must NOT
push PendingRenovate unconditionally from on_play (that is Shifting Cultivation's
shape, correct only for a MANDATORY primitive). Instead the grant is an OPTIONAL
`after_play_minor` trigger: the play-minor host (`PendingPlayMinor`) pivots to its
after-phase after this minor is played, and that after-phase already surfaces
`FireTrigger("dwelling_plan")` (= renovate) alongside `Stop` (= decline). The
player chooses; declining is just picking Stop instead of firing.

Sequencing (load-bearing): `_execute_play_minor` adds `dwelling_plan` to
`minor_improvements` and flips the host to its after-phase BEFORE running on_play,
so the card IS owned by the time the after-phase enumerates triggers — `_owns`
passes and the trigger is offered. on_play itself is a no-op here.

Eligibility gates on `_can_renovate` (at least one legal, payable renovate target
through the cost-modifier chokepoint) so the grant is never offered when firing it
would dead-end on the no-Stop PendingRenovate frame. The host's `triggers_resolved`
guard fires it at most once.

See CARD_IMPLEMENTATION_PLAN.md Category 4; mirrors the optional-renovate grant
shape of Cottager's renovate variant and the after_play_X granted-primitive shape
of Bread Paddle.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_renovate
from agricola.pending import PendingRenovate, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "dwelling_plan"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the renovate only when it is unfired this play and a legal, payable
    renovate target exists (so the pushed no-Stop PendingRenovate never dead-ends)."""
    return (CARD_ID not in triggers_resolved
            and _can_renovate(state, state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    # Push the standard Renovate primitive; its enumerator offers the CommitRenovate
    # targets and resolves cost through the cost-modifier chokepoint (exactly like
    # House Redevelopment) — nothing to compute or store here.
    return push(state, PendingRenovate(player_idx=idx, initiated_by_id="card:dwelling_plan"))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)))
register("after_play_minor", CARD_ID, _eligible, _apply)
