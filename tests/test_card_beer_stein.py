"""Tests for Beer Stein (minor improvement, C61; Corbarius Expansion):

    "Each time you take a 'Bake Bread' action, you can use this card once to turn
     1 grain into 2 food and 1 bonus point."
    Clarification: "You must bake normally to make this exchange."
    Cost: 1 Clay. No prerequisite.

An OPTIONAL `after_bake_bread` trigger that exchanges 1 grain for 2 food + a banked
bonus point (read back at scoring). Mechanically identical to Baking Sheet (A30),
differing only in cost (1 clay) and the absence of a prerequisite. Each firing test
drives the real Bake Bread flow through Grain Utilization (place -> bake_bread
sub-action -> CommitBake flips PendingBakeBread to its after-phase), so the firing
point — and the "must bake normally" structural guarantee — is exercised end-to-end.
"""
import agricola.cards.beer_stein  # noqa: F401  (registers the card; not yet in cards/__init__.py)

from agricola.actions import ChooseSubAction, CommitBake, FireTrigger, PlaceWorker, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_majors,
    with_resources,
)

CARD_ID = "beer_stein"


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _bake_setup(*, owner=0, current_player=0, grain=2, seed=0):
    """Family round-1 WORK state with a legal Grain Utilization placement (grain
    + a Fireplace so the player can bake), and `owner` (idx or None) holding the
    Beer Stein minor."""
    s = setup(seed=seed)
    s = with_current_player(s, current_player)
    s = with_resources(s, current_player, grain=grain)
    s = with_majors(s, owner_by_idx={0: current_player})   # Fireplace (idx 0)
    if owner is not None:
        s = _own_minor(s, owner)
    return s


def _bake_to_after_phase(s):
    """Drive place -> choose bake_bread -> CommitBake(1); leaves the bake host in
    its after-phase (where the Beer Stein trigger is offered alongside Stop)."""
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="bake_bread"))
    s = step(s, CommitBake(grain=1))
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 0                                  # the point is banked, not printed
    assert spec.cost == Cost(resources=Resources(clay=1))  # 1 clay
    assert spec.prereq is None                            # no prerequisite
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_registered_on_after_bake_bread():
    from agricola.cards.triggers import TRIGGERS
    entries = TRIGGERS.get("after_bake_bread", [])
    assert any(e.card_id == CARD_ID and not e.mandatory for e in entries), entries


def test_prereq_always_met():
    # No prerequisite -> playable from any state.
    s = setup(seed=0)
    assert prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# Firing: exchange 1 grain -> +2 food + 1 banked bonus point
# ---------------------------------------------------------------------------

def test_fires_after_bake_bread():
    s = _bake_setup(owner=0, grain=2)   # 1 grain baked normally leaves 1 to exchange
    s = _bake_to_after_phase(s)
    grain_after_bake = s.players[0].resources.grain
    food_after_bake = s.players[0].resources.food
    assert grain_after_bake == 1        # 2 - 1 baked
    # The after-phase surfaces the optional Beer Stein trigger (alongside Stop).
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    # No pending pushed — a pure state edit: -1 grain, +2 food, +1 banked point.
    assert s.players[0].resources.grain == grain_after_bake - 1
    assert s.players[0].resources.food == food_after_bake + 2
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    # Finish the turn (pop bake host after-phase, then the Grain Utilization host).
    s = step(s, Stop())
    s = step(s, Stop())
    assert s.pending_stack == ()


def test_scores_banked_point():
    s = _bake_setup(owner=0, grain=2)
    s = _bake_to_after_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    # A direct read of the registered scoring term confirms the +1 it contributes.
    fn = next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)
    assert fn(s, 0) == 1
    # And the +1 is included in the player's full end-game score (vs a cleared bank).
    cleared = fast_replace(
        s.players[0], card_state=s.players[0].card_state.set(CARD_ID, 0))
    s_cleared = fast_replace(
        s, players=tuple(cleared if i == 0 else s.players[i] for i in range(2)))
    assert score(s, 0)[0] == score(s_cleared, 0)[0] + 1


# ---------------------------------------------------------------------------
# Optionality: declinable via the host's Stop
# ---------------------------------------------------------------------------

def test_decline():
    s = _bake_setup(owner=0, grain=2)
    s = _bake_to_after_phase(s)
    grain0 = s.players[0].resources.grain
    food0 = s.players[0].resources.food
    s = step(s, Stop())   # decline + pop the bake host after-phase
    s = step(s, Stop())   # pop the Grain Utilization host; turn ends
    assert s.pending_stack == ()
    assert s.players[0].resources.grain == grain0   # nothing exchanged
    assert s.players[0].resources.food == food0
    assert s.players[0].card_state.get(CARD_ID, 0) == 0   # no point banked


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_grain_to_exchange():
    # Exactly 1 grain: baking it normally leaves 0 -> nothing left to exchange.
    s = _bake_setup(owner=0, grain=1)
    s = _bake_to_after_phase(s)
    assert s.players[0].resources.grain == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert legal_actions(s) == [Stop()]


def test_not_offered_when_unowned():
    s = _bake_setup(owner=None, grain=2)
    s = _bake_to_after_phase(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_once_per_bake_action():
    # After firing once, the trigger is stamped in triggers_resolved -> not offered
    # again within the same Bake Bread action (even with grain still available).
    s = _bake_setup(owner=0, grain=3)   # bake 1, exchange 1, still 1 left
    s = _bake_to_after_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].resources.grain == 1     # 3 - 1 baked - 1 exchanged
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert s.players[0].card_state.get(CARD_ID, 0) == 1   # only banked once


def test_re_eligible_on_a_new_bake_action():
    # "Each time you take a Bake Bread action" — a fresh PendingBakeBread has an
    # empty triggers_resolved, so the card re-becomes eligible on the next action.
    # grain=4: action #1 bakes 1 + exchanges 1 (2 left), action #2 bakes 1 (1 left).
    s = _bake_setup(owner=0, grain=4)
    s = _bake_to_after_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))   # fire on action #1
    s = step(s, Stop())                          # pop bake host
    s = step(s, Stop())                          # end the Grain Utilization turn
    assert s.pending_stack == ()
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    assert s.players[0].resources.grain == 2     # 4 - 1 baked - 1 exchanged

    # Force a second independent Bake Bread action via a fresh bake frame.
    from agricola.pending import PendingBakeBread, push
    from agricola.resolution import _execute_bake
    s = with_current_player(s, 0)
    s = push(s, PendingBakeBread(player_idx=0, initiated_by_id="space:grain_utilization"))
    s = _execute_bake(s, 0, CommitBake(grain=1))   # bake normally -> after-phase
    assert s.players[0].resources.grain == 1       # 1 left to exchange
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))       # fire on action #2
    assert s.players[0].card_state.get(CARD_ID, 0) == 2   # banked twice total
