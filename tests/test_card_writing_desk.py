import agricola.cards.writing_desk  # noqa: F401
"""Writing Desk (minor improvement, D28; Consul Dirigens; cost 1 wood; prereq 2 occupations; 1 VP).

Card text: "Each time you use a 'Lessons' action space, you can play 1 additional
occupation for an occupation cost of 2 food."

An OPTIONAL `before_action_space` FireTrigger on the NON-ATOMIC, already-hosted Lessons
space. "Each time you use" maps to the BEFORE-window: the grant is offered alongside the
mandatory occupation-play choice, and taking that mandatory play CLOSES the before-window
(implicitly declining the grant). So the additional occupation is played FIRST, at a FLAT
2-food cost (not the Lessons ramp). The enforce-first ordering is load-bearing: it blocks
playing Paper Maker as the mandatory occupation and then having it subsidize the grant
(Paper Maker only pays for occupations played AFTER it enters play).

These tests drive the real Lessons flow (no direct frame pokes) so the firing point is
exercised end-to-end: registration, the before-phase extra play + the 2-food debit, the
>=2-playable-occupation stranding guard, the 2-food affordability / ownership / own-action
boundaries, the mandatory-play-declines-the-grant property (the Paper Maker block), and
once-per-use scoping.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation, PendingSubActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_resources, with_space

CARD_ID = "writing_desk"

_POOL = CardPool(
    occupations=("consultant", "priest", "stable_architect") + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so plays come only from what a test grants.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_occ(state, idx, *card_ids):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _lessons_before(cs, idx):
    """Place a worker at Lessons and stop in the BEFORE-phase, where Writing Desk's grant
    is offered alongside the mandatory occupation-play ChooseSubAction."""
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    assert isinstance(cs.pending_stack[-1], PendingSubActionSpace)
    assert cs.pending_stack[-1].phase == "before"
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_writing_desk_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))   # 1 wood (NOT the prereq)
    assert spec.min_occupations == 2                         # prereq: 2 occupations
    assert spec.vps == 1
    assert spec.passing_left is False
    # Optional before_action_space trigger; Lessons is already hosted, so NO action hook.
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert CARD_ID in bas
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("lessons", set())


def test_writing_desk_prereq_needs_two_occupations():
    cs = _card_state()
    spec = MINORS[CARD_ID]
    # 0/1 occupation -> prereq unmet; 2 -> met.
    assert not prereq_met(spec, cs, 0)
    p1 = fast_replace(cs.players[0], occupations=frozenset({"consultant"}))
    cs1 = fast_replace(cs, players=tuple(p1 if i == 0 else cs.players[i] for i in range(2)))
    assert not prereq_met(spec, cs1, 0)
    p2 = fast_replace(cs.players[0], occupations=frozenset({"consultant", "priest"}))
    cs2 = fast_replace(cs, players=tuple(p2 if i == 0 else cs.players[i] for i in range(2)))
    assert prereq_met(spec, cs2, 0)


# ---------------------------------------------------------------------------
# Real-flow effect: an additional occupation for 2 food, played first
# ---------------------------------------------------------------------------

def test_offered_in_before_phase():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant", "priest")
    cs = with_resources(cs, 0, food=2)
    cs = _lessons_before(cs, 0)
    la = legal_actions(cs)
    # The grant AND the mandatory play's choice are both offered in the before-window.
    assert FireTrigger(card_id=CARD_ID) in la
    assert ChooseSubAction(name="play_occupation") in la


def test_fire_plays_additional_occupation_for_two_food():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant", "priest")
    cs = with_resources(cs, 0, food=5, clay=0)
    cs = _lessons_before(cs, 0)
    food_before = cs.players[0].resources.food

    cs = step(cs, FireTrigger(card_id=CARD_ID))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources(food=2)                # FLAT 2-food cost
    assert top.phase == "before"
    assert cs.players[0].resources.food == food_before  # charged at the commit, not the fire

    # Play the granted occupation — the FIRST occupation this use.
    cs = step(cs, CommitPlayOccupation(card_id="priest"))
    p = cs.players[0]
    assert "priest" in p.occupations
    assert "priest" not in p.hand_occupations
    assert p.resources.food == food_before - 2          # 2 food debited
    cs = step(cs, Stop())                               # pop the granted play's after-phase

    # Back in the host before-phase: grant fired (not re-offered); mandatory play remains.
    assert isinstance(cs.pending_stack[-1], PendingSubActionSpace)
    assert cs.pending_stack[-1].phase == "before"
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert ChooseSubAction(name="play_occupation") in la

    # Do the mandatory Lessons play with the remaining occupation.
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    assert "consultant" in cs.players[0].occupations


# ---------------------------------------------------------------------------
# The enforce-first property: taking the mandatory play declines the grant
# (this is what blocks the Paper Maker subsidy)
# ---------------------------------------------------------------------------

def test_taking_mandatory_play_declines_the_grant():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant", "priest")
    cs = with_resources(cs, 0, food=5)
    cs = _lessons_before(cs, 0)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(cs)    # offered before the play
    # Take the mandatory play first — this closes the before-window.
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    cs = step(cs, Stop())                                       # pop the play's after-phase
    # The host auto-advances to its after-phase; the grant is a before-trigger -> gone.
    assert cs.pending_stack[-1].phase == "after"
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_a_second_playable_occupation():
    # Only one playable occupation: firing would consume it and strand the mandatory
    # (non-declinable) Lessons play -> the >=2 stranding guard suppresses the grant.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = with_resources(cs, 0, food=10)
    cs = _lessons_before(cs, 0)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)
    # ...and the mandatory play itself is still available (not stranded).
    assert ChooseSubAction(name="play_occupation") in legal_actions(cs)


def test_not_offered_when_cannot_afford_two_food():
    # Two playable occupations but no way to raise 2 food (0 food, nothing to liquidate).
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant", "priest")
    cs = with_resources(cs, 0, food=0, grain=0, veg=0)
    p0 = fast_replace(cs.players[0], animals=cs.players[0].animals.__class__())
    cs = fast_replace(cs, players=tuple(p0 if i == 0 else cs.players[i] for i in range(2)))
    cs = _lessons_before(cs, 0)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


def test_not_offered_when_unowned():
    cs = _card_state()                                   # owns no Writing Desk
    cs = _give_hand_occ(cs, 0, "consultant", "priest")
    cs = with_resources(cs, 0, food=5)
    cs = _lessons_before(cs, 0)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


def test_not_offered_on_opponents_lessons_use():
    # Player 0 owns Writing Desk; player 1 uses Lessons -> 0's trigger does not fire.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 1, "consultant", "priest")
    cs = with_resources(cs, 1, food=5)
    cs = _lessons_before(cs, 1)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


# ---------------------------------------------------------------------------
# Once per Lessons use (per-use latch), available again on a new use
# ---------------------------------------------------------------------------

def test_fires_once_per_use_then_not_again_same_use():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant", "priest", "stable_architect")
    cs = with_resources(cs, 0, food=5)
    cs = _lessons_before(cs, 0)
    cs = step(cs, FireTrigger(card_id=CARD_ID))          # fire the extra play
    cs = step(cs, CommitPlayOccupation(card_id="priest"))
    cs = step(cs, Stop())                                # pop the additional play host
    # Back at the Lessons host before-phase; already fired this use -> not re-offered.
    assert isinstance(cs.pending_stack[-1], PendingSubActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


def test_available_again_on_a_second_lessons_use():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, "consultant", "priest", "stable_architect")
    cs = with_resources(cs, 0, food=10)
    # First Lessons use: decline the grant, just do the mandatory play.
    cs = _lessons_before(cs, 0)
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    cs = step(cs, Stop())                                # pop the play's after-phase
    cs = step(cs, Stop())                                # pop the Lessons host
    assert not cs.pending_stack
    # Second Lessons use (fresh host frame): still >=2 playable -> offered again.
    cs = _lessons_before(cs, 0)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(cs)
