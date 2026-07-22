"""Baker (occupation, C107) — the food-shortfall liquidation half of the
(payment × variant) stranding pair-gate (user ruling 75, 2026-07-21, ruled on
the sibling Stable Master case): "a wide display of (payment × build/no-build)
pairs — the build variant is offered only with payments that leave the build
doable; the decline variant with every payment."

Baker's exposure: the bake variant's `_can_bake_bread` gate runs PRE-play, but
a food-short occupation cost detours through `PendingFoodPayment`, and a
liquidation bundle can cook the only grain the granted bake needs (grain at
the 1:1 base rate) — reaching a `PendingBakeBread` with zero legal actions.
The pair-gate is consulted at BOTH decision points: the play-occupation
enumerator withholds the bake pair when NO liquidation bundle keeps the bake
doable, and the `PendingFoodPayment` enumerator withholds exactly the bundles
that cook it when some other bundle survives.

Baker's on-play mechanics themselves (the wide bake/decline variants, the
feeding-phase grant) are covered in tests/test_cards_rulings_15_17.py.
"""
from __future__ import annotations

import agricola.cards.baker  # noqa: F401

from agricola.actions import (
    CommitBake,
    CommitFoodPayment,
    CommitPlayOccupation,
)
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread, PendingFoodPayment, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup

from tests.factories import with_pending_stack, with_phase

BAKER = "baker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _with_fireplace(state, idx):
    owners = list(state.board.major_improvement_owners)
    owners[0] = idx
    return fast_replace(state, board=fast_replace(
        state.board, major_improvement_owners=tuple(owners)))


def _play_state(*, grain, food=0, animals=Animals()):
    """A WORK state at a PendingPlayOccupation host with a 1-FOOD play cost,
    Baker in hand, a Fireplace owned, and the given grain/food/animals — the
    food-short shape whose cost must be raised by liquidation."""
    state = with_phase(setup(0), Phase.WORK)
    cp = state.current_player
    state = _edit_player(state, cp,
                         hand_occupations=frozenset({BAKER}),
                         animals=animals,
                         resources=fast_replace(
                             state.players[cp].resources,
                             grain=grain, food=food))
    state = _with_fireplace(state, cp)
    frame = PendingPlayOccupation(player_idx=cp,
                                  initiated_by_id="space:lessons",
                                  cost=Resources(food=1))
    return with_pending_stack(state, [frame]), cp


def _baker_plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayOccupation) and a.card_id == BAKER]


# ---------------------------------------------------------------------------
# The liquidation stranding case
# ---------------------------------------------------------------------------

def test_only_liquidation_cooks_the_grain_bake_pair_withheld():
    """1 grain + 0 food: the sole way to raise the 1-food cost cooks the only
    grain the granted bake needs -> the bake pair is withheld; the decline
    pair (raised by the same liquidation) is still offered."""
    state, _cp = _play_state(grain=1)
    assert [a.variant for a in _baker_plays(state)] == ["decline_bake"]


def test_second_grain_keeps_the_bake_pair_and_the_play_completes():
    """2 grain + 0 food: the liquidation cooks one grain and one remains for
    the bake -> the pair is offered and the whole line (liquidate -> re-run
    debit -> granted bake) completes."""
    state, cp = _play_state(grain=2)
    assert sorted(a.variant for a in _baker_plays(state)) == [
        "bake", "decline_bake"]
    state = step(state, CommitPlayOccupation(card_id=BAKER, variant="bake"))
    assert isinstance(state.pending_stack[-1], PendingFoodPayment)
    bundles = legal_actions(state)
    assert bundles == [CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)]
    state = step(state, bundles[0])       # raise 1 food; the re-run debits it
    assert BAKER in state.players[cp].occupations
    assert isinstance(state.pending_stack[-1], PendingBakeBread)
    assert legal_actions(state)           # the granted bake is NOT stranded
    state = step(state, CommitBake(grain=1))
    assert state.players[cp].resources.grain == 0
    assert state.players[cp].resources.food == 2   # Fireplace bake: grain -> 2


def test_food_payment_frame_filters_the_grain_cooking_bundle():
    """1 grain + 1 sheep + 0 food: two Pareto bundles raise the 1 food (cook
    the grain / cook the sheep at the Fireplace rate). The bake pair IS
    offered (the sheep bundle keeps the bake doable), and at the
    PendingFoodPayment frame under the bake commit ONLY the sheep bundle
    surfaces — the grain-cooking bundle would strand the granted bake."""
    state, cp = _play_state(grain=1, animals=Animals(sheep=1))
    assert sorted(a.variant for a in _baker_plays(state)) == [
        "bake", "decline_bake"]
    baking = step(state, CommitPlayOccupation(card_id=BAKER, variant="bake"))
    assert isinstance(baking.pending_stack[-1], PendingFoodPayment)
    bundles = legal_actions(baking)
    assert bundles == [CommitFoodPayment(grain=0, veg=0, sheep=1, boar=0, cattle=0)]
    baking = step(baking, bundles[0])
    assert isinstance(baking.pending_stack[-1], PendingBakeBread)
    assert legal_actions(baking)          # the bake survived the liquidation
    baking = step(baking, CommitBake(grain=1))
    assert baking.players[cp].resources.food == 3   # sheep 2 (raise) - 1 (cost) + bake 2

    # Control: under the DECLINE commit the gate passes every bundle — both
    # Pareto points stay on offer (the ruled "decline with every payment").
    declining = step(state, CommitPlayOccupation(
        card_id=BAKER, variant="decline_bake"))
    assert isinstance(declining.pending_stack[-1], PendingFoodPayment)
    assert len(legal_actions(declining)) == 2
