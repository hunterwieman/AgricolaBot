"""Scholar (occupation, B97; Base Revised; players 1+).

Card text: "Once you live in a stone house, at the start of each round, you can play
an occupation for an occupation cost of 1 food, or a minor improvement (by paying its
cost)."

Category 7 (start-of-round phase hook), the COLLAPSED PLAY-VARIANT trigger
(CARD_IMPLEMENTATION_PLAN.md Category 7): once in a stone house, at round start the
owner may play an occupation from hand (flat 1-food cost) OR a minor (its printed
cost). The route is chosen AT the fire: the PendingPreparation enumerator surfaces a
distinct `FireTrigger("scholar", variant="occupation")` (when a hand occupation is
playable and you have 1 food) and `FireTrigger("scholar", variant="minor")` (when a
hand minor is playable), with "do neither" = the host's Proceed. Firing pushes the
standard PendingPlayOccupation(cost=1 food) or PendingPlayMinor accordingly — the
two existing play-card pendings (II.4), so no new sub-decision machinery. Once-per-
round via `used_this_round` (II.3). On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_play_variant_trigger,
    register_start_of_round_hook,
)
from agricola.constants import HouseMaterial
from agricola.legality import playable_minors, playable_occupations
from agricola.pending import PendingPlayMinor, PendingPlayOccupation, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "scholar"
_OCC_COST = Resources(food=1)   # Scholar's flat occupation cost (not the Lessons ramp)


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The play routes currently legal for Scholar: 'occupation' when a hand
    occupation is playable and the flat 1-food cost is affordable; 'minor' when a
    hand minor is playable. Empty list → nothing to play this round."""
    p = state.players[idx]
    variants: list[str] = []
    if playable_occupations(state, idx) and p.resources.food >= 1:
        variants.append("occupation")
    if playable_minors(state, idx):
        variants.append("minor")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.house_material is HouseMaterial.STONE
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    # Latch once-per-round, then push the chosen play-card pending. The play frame's
    # own enumerator offers the legal CommitPlay{Occupation,Minor}s.
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    if variant == "occupation":
        return push(state, PendingPlayOccupation(
            player_idx=idx, initiated_by_id="card:scholar", cost=_OCC_COST))
    return push(state, PendingPlayMinor(
        player_idx=idx, initiated_by_id="card:scholar"))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_start_of_round_hook(CARD_ID)
