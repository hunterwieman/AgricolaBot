"""Dwelling Plan (minor improvement, D2; Dulcinaria Expansion; cost 1 food).

Card text: "You can immediately take a 'Renovation' action."

TRAVELING (passing) minor — D2 is a number-001-009 card (`passing_left='X'` in the
catalog): after its immediate effect it passes to the opponent's hand rather than
staying in the tableau. No prerequisite, no printed VPs.

Category 4 (granted sub-action) — an OPTIONAL on-play grant of a single Renovate
primitive. "You can ... take" is the standard optional wording, so the renovation
is DECLINABLE.

Mechanism — because the card is PASSING, an ownership-gated `after_play_minor`
trigger cannot host the grant: `_execute_play_minor` moves a traveling card to the
opponent's hand BEFORE the after-phase, so the owner no longer `_owns` it and the
trigger would never fire (it would silently do nothing). Instead `on_play` pushes
the generic `PendingGrantedSubAction(subaction="renovate")` choose-or-decline
wrapper — the optional-grant pattern shared with Field Fences / Trellis, which is
NOT ownership-gated (it is a pushed frame, so it works regardless of the card
having passed). The wrapper offers `ChooseSubAction("renovate")` when a renovate is
legal + payable (its enumerator gates on `_can_renovate`, so the no-Stop
`PendingRenovate` is never a dead-end), alongside `Stop` (= decline). Choosing
pushes the standard `PendingRenovate` with this card's provenance; its cost resolves
through the cost-modifier chokepoint exactly like House Redevelopment.

That a passing card with an optional sub-action grant NEEDS the wrapper (not an
after-trigger) is the reason the generic frame exists. See PendingGrantedSubAction
(pending.py) and the Field Fences / Trellis build-fences grants.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.pending import PendingGrantedSubAction, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "dwelling_plan"


def _on_play(state: GameState, idx: int) -> GameState:
    # Push the generic optional-grant wrapper for a renovate; its enumerator gates the
    # offer on _can_renovate (never a dead-end) and hosts the decline (Stop). Works even
    # though this passing card has already left the tableau — the wrapper isn't
    # ownership-gated. The wrapper lands on the marked, still-before-phase play host
    # (the Shifting-Cultivation nesting), which flips once the wrapper pops — the
    # deferred after-flip, user ruling 2026-07-14.
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id="card:dwelling_plan", subaction="renovate"))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)),
               passing_left=True, on_play=_on_play)
