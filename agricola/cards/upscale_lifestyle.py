"""Upscale Lifestyle (minor improvement, B1; Bubulcus Expansion; cost 3 Wood).

Card text (verbatim): "You immediately get 5 clay and a "Renovation" action. If
you take the action, you must pay the renovation cost."

TRAVELING (passing) minor (`passing_left=YES`): after its immediate effect the
card passes to the opponent's hand rather than staying in the tableau. No
prerequisite, no printed VPs.

Two on-play clauses:

- **"immediately get 5 clay"** — a one-time goods gain (the Consultant pattern),
  applied first so the clay is available to pay the renovation.
- **"a 'Renovation' action. If you take the action, you must pay the renovation
  cost."** — an OPTIONAL granted Renovate at NORMAL cost. Because the card is
  PASSING it leaves the tableau before any after-phase, so an ownership-gated
  `after_play_minor` trigger cannot host the grant; instead `on_play` pushes the
  generic `PendingGrantedSubAction(subaction="renovate")` choose-or-decline wrapper
  (the Dwelling Plan / Field Fences pattern — not ownership-gated, so it works
  after the card has passed). The wrapper offers `ChooseSubAction("renovate")` only
  when a renovate is legal + payable (its enumerator gates on `_can_renovate`, so
  the no-Stop `PendingRenovate` never dead-ends — exactly matching "you must pay the
  renovation cost"), alongside `Stop` (= decline). Choosing pushes the standard
  `PendingRenovate`; its cost resolves through the cost-modifier chokepoint like
  House Redevelopment (nothing free here — contrast Renovation Company A13).

Card-only registries; the Family game is byte-identical.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.pending import PendingGrantedSubAction, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "upscale_lifestyle"


def _on_play(state: GameState, idx: int) -> GameState:
    # "immediately get 5 clay" first (available to pay the renovation), then push the
    # optional-renovate wrapper. The wrapper gates its offer on _can_renovate (normal
    # cost) — correct here, since the player "must pay the renovation cost".
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=5))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id="card:upscale_lifestyle",
        subactions=("renovate",)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3)),
               passing_left=True, on_play=_on_play)
