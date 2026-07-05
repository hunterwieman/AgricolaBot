"""Tumbrel (minor improvement, B54; Bubulcus Expansion; cost 1 wood).

Card text: "When you play this card, you immediately get 2 food. Each time after
you take an unconditional 'Sow' action, you get 1 food for each stable you have."

Two effects:

  - On play (one-shot): +2 food immediately (modeled as `on_play`).
  - A repeating income on every Sow: after each unconditional Sow action, gain
    1 food per BUILT stable you have. The text literally states the "after"
    phase, so this is an AUTOMATIC effect on `after_sow` (register_auto) — a pure
    food gain with no downside, never surfaced as a declinable FireTrigger. The
    after-phase fires once per Sow action at the CommitSow before->after flip
    (via _enter_after_phase -> apply_auto_effects("after_sow", ...)), for both
    Grain Utilization and Cultivation sows.

"Stables you have" = BUILT stables (`helpers.stables_built(farmyard)`). When
the player has no stables the after-sow grant is a harmless +0 food.

"Unconditional Sow" distinguishes the standard Sow sub-action (Grain Utilization /
Cultivation) from a card-granted *conditional* sow. No conditional-sow card exists
in the implemented set, so every `after_sow` event is an unconditional sow and the
auto fires on all of them. (If a conditional-sow card is ever added, this eligibility
must inspect the PendingSow's provenance to exclude it; mirrors garden_hoe.py /
drill_harrow.py.)

The eligibility is unconditional (True): even with zero stables the grant is a
harmless +0, so there is nothing to gate. Stateless — no CardStore — so the Family
game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.helpers import stables_built
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "tumbrel"


def _on_play(state: GameState, idx: int) -> GameState:
    """On play: immediately gain 2 food."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    """Unconditional: every after_sow event qualifies (zero-stable grant is +0)."""
    return True


def _apply(state: GameState, idx: int) -> GameState:
    """after_sow: gain 1 food per BUILT stable (= 4 - unbuilt-in-supply)."""
    p = state.players[idx]
    built_stables = stables_built(p.farmyard)
    p = fast_replace(p, resources=p.resources + Resources(food=built_stables))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register_auto("after_sow", CARD_ID, _eligible, _apply)
