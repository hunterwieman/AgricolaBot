"""Tests for Beer Stein (minor improvement, C61; Corbarius Expansion):

    "Each time you take a 'Bake Bread' action, you can use this card once to turn
     1 grain into 2 food and 1 bonus point."
    Clarification: "You must bake normally to make this exchange."
    Cost: 1 Clay. No prerequisite.

An OPTIONAL `before_bake_bread` trigger that exchanges 1 grain for 2 food + a banked
bonus point (read back at scoring). Per the Trigger-Timing ruling, a bare "each time
you take a 'Bake Bread' action" fires in the BEFORE phase (the reward is flat, so it
need not read the bake's outcome); the "must bake normally" clarification is a GATE,
not an ordering. Because the before-phase offers only FireTrigger + CommitBake (a bake
is forced) and the exchange spends 1 grain, eligibility requires grain >= 2 so a legal
bake still remains — otherwise firing would strand the mandatory bake. Each firing test
drives the real Bake Bread flow through Grain Utilization (place -> bake_bread
sub-action -> the PendingBakeBread before-phase surfaces the trigger + CommitBake).
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


def _to_bake_before_phase(s):
    """Drive place -> choose bake_bread; leaves the bake host in its BEFORE-phase,
    where the Beer Stein trigger is offered alongside the CommitBake options (no
    Stop — the bake is forced)."""
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="bake_bread"))
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


def test_registered_on_before_bake_bread():
    from agricola.cards.triggers import TRIGGERS
    entries = TRIGGERS.get("before_bake_bread", [])
    assert any(e.card_id == CARD_ID and not e.mandatory for e in entries), entries
    # And NOT on the after-phase (the timing bug this fix corrects).
    after = TRIGGERS.get("after_bake_bread", [])
    assert not any(e.card_id == CARD_ID for e in after), after


def test_prereq_always_met():
    # No prerequisite -> playable from any state.
    s = setup(seed=0)
    assert prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# Firing: exchange 1 grain -> +2 food + 1 banked bonus point, BEFORE the bake
# ---------------------------------------------------------------------------

def test_fires_before_bake_bread():
    s = _bake_setup(owner=0, grain=2)   # exchange 1 (leaves 1) then bake that 1
    s = _to_bake_before_phase(s)
    grain0 = s.players[0].resources.grain
    food0 = s.players[0].resources.food
    assert grain0 == 2                   # nothing consumed yet (before-phase)
    # The before-phase surfaces the optional Beer Stein trigger AND CommitBake (no Stop).
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert CommitBake(grain=1) in la
    assert Stop() not in la              # bake is forced, no decline path at this frame
    # Fire the exchange: a pure state edit -1 grain, +2 food, +1 banked point.
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].resources.grain == grain0 - 1   # 2 - 1 exchanged = 1
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    # A legal bake still remains (the stranding guard did its job) and can be committed.
    assert CommitBake(grain=1) in legal_actions(s)
    s = step(s, CommitBake(grain=1))
    assert s.players[0].resources.grain == 0            # 1 baked
    # Finish the turn (pop bake host after-phase, then the Grain Utilization host).
    s = step(s, Stop())
    s = step(s, Stop())
    assert s.pending_stack == ()


def test_scores_banked_point():
    s = _bake_setup(owner=0, grain=2)
    s = _to_bake_before_phase(s)
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
# Optionality: declinable by baking without firing
# ---------------------------------------------------------------------------

def test_decline():
    s = _bake_setup(owner=0, grain=2)
    s = _to_bake_before_phase(s)
    grain0 = s.players[0].resources.grain
    food0 = s.players[0].resources.food
    s = step(s, CommitBake(grain=1))   # bake without firing -> decline the exchange
    s = step(s, Stop())                # pop the bake host after-phase
    s = step(s, Stop())                # pop the Grain Utilization host; turn ends
    assert s.pending_stack == ()
    assert s.players[0].resources.grain == grain0 - 1   # only the bake spent grain
    assert s.players[0].resources.food == food0 + 2     # bake payout (Fireplace 2:1)
    assert s.players[0].card_state.get(CARD_ID, 0) == 0  # no point banked


# ---------------------------------------------------------------------------
# Eligibility boundaries — the stranding guard
# ---------------------------------------------------------------------------

def test_not_offered_at_one_grain_would_strand_bake():
    # Exactly 1 grain: firing (-1) would leave 0 grain, stranding the MANDATORY bake.
    # The guard (grain >= 2) suppresses the exchange; only CommitBake is offered.
    s = _bake_setup(owner=0, grain=1)
    s = _to_bake_before_phase(s)
    assert s.players[0].resources.grain == 1
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert CommitBake(grain=1) in la     # the bake itself is still available


def test_not_offered_when_unowned():
    s = _bake_setup(owner=None, grain=2)
    s = _to_bake_before_phase(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_once_per_bake_action():
    # After firing once, the trigger is stamped in triggers_resolved -> not offered
    # again within the same Bake Bread action (even with grain still available).
    s = _bake_setup(owner=0, grain=3)   # exchange 1, still 2 left before baking
    s = _to_bake_before_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].resources.grain == 2     # 3 - 1 exchanged
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert s.players[0].card_state.get(CARD_ID, 0) == 1   # only banked once


def test_re_eligible_on_a_new_bake_action():
    # "Each time you take a Bake Bread action" — a fresh PendingBakeBread has an
    # empty triggers_resolved, so the card re-becomes eligible on the next action.
    s = _bake_setup(owner=0, grain=4)
    s = _to_bake_before_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))   # fire on action #1 (4 -> 3)
    s = step(s, CommitBake(grain=1))             # bake normally (3 -> 2)
    s = step(s, Stop())                          # pop bake host after-phase
    s = step(s, Stop())                          # end the Grain Utilization turn
    assert s.pending_stack == ()
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    assert s.players[0].resources.grain == 2     # 4 - 1 exchanged - 1 baked

    # Force a second independent Bake Bread action via a fresh bake frame.
    from agricola.pending import PendingBakeBread, push
    s = with_current_player(s, 0)
    s = push(s, PendingBakeBread(player_idx=0, initiated_by_id="space:grain_utilization"))
    # The fresh frame's before-phase re-offers the exchange (grain 2 >= 2).
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))       # fire on action #2
    assert s.players[0].card_state.get(CARD_ID, 0) == 2   # banked twice total
    assert s.players[0].resources.grain == 1              # 2 - 1 exchanged
