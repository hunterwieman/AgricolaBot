"""Bookcase (minor improvement, C68; Consul Dirigens Expansion; cost 2 wood).

Card text: "Each time after you play an occupation, you get 1 vegetable."
Printed 0 VP. Prerequisite to play: 1 occupation already in the tableau.

Category 5 (play-occupation hook) but the simplest possible shape: an
unconditional, choiceless income. Each occupation the OWNER plays grants exactly
1 vegetable, so this is a `register_auto` (mandatory, choiceless) on
`after_play_occupation` — not a declinable `register` trigger (no decision to
make, no dead-end to gate against; a vegetable always fits the supply, with no
accommodation or threshold).

Three correctness points:

- **Owner-gated** (`any_player=False`, the default): "each time YOU play an
  occupation" — the +1 veg fires only on the owner's own occupation plays, never
  the opponent's. `apply_auto_effects` only runs an owner-gated entry for the
  acting player, and `_owns` further requires the card be in the owner's tableau.
- **AFTER the occupation is played.** `after_play_occupation` fires in the
  after-window of the play-occupation host (`_enter_after_phase` →
  `apply_auto_effects(state, "after_play_occupation", idx)`), opened only once the
  played occupation is already in the tableau and its on_play has run. So the +1
  veg never affects or is consumed by the occupation it triggers on.
- **Prerequisite, not a recurring gate.** "1 occupation" is a HAVE-check enforced
  at play time via `min_occupations=1` (prereq_met) — it does NOT limit how many
  later occupation plays grant the vegetable.

On-play is a no-op; 0 VP; not passing. See CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "bookcase"


def _eligible(state: GameState, idx: int) -> bool:
    # Unconditional: a vegetable always fits the supply (no accommodation, no
    # threshold). Ownership + own-action gating is handled by apply_auto_effects.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(veg=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=1)
register_auto("after_play_occupation", CARD_ID, _eligible, _apply)
