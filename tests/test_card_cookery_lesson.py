"""Tests for Cookery Lesson (minor B29): 1 point per Lessons-placement turn on which you
also cook an animal via a cooking improvement — granted at the actual cook."""
import agricola.cards.cookery_lesson  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitFoodPayment,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.cookery_lesson import (
    CARD_ID,
    _SCORED,
    _award,
    _cook_variants,
    _in_lessons,
    _react,
)
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingSubActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.resolution import note_animal_cook
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup, setup_env

from tests.factories import with_majors, with_pending_stack

_POOL = CardPool(
    occupations=("consultant", "stable_architect") + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, *, majors=None, sheep=0, boar=0, cattle=0):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {CARD_ID},
                     animals=Animals(sheep=sheep, boar=boar, cattle=cattle))
    state = fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    if majors:
        state = with_majors(state, owner_by_idx=majors)
    return state


def _lessons_stack(state, idx=0):
    frame = PendingSubActionSpace(player_idx=idx, initiated_by_id="space:lessons")
    return with_pending_stack(state, (frame,))


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    from agricola.cards.triggers import (
        ANIMAL_COOK_REACTIONS, PLAY_VARIANT_TRIGGERS, TRIGGERS,
    )
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=2))
    assert CARD_ID in ANIMAL_COOK_REACTIONS
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("after_action_space", ()))
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- Unit: cook variants / award / react ------------------------------------

def test_cook_variants_need_a_cooking_improvement_and_animal():
    assert _cook_variants(_own(setup(0), 0, sheep=2), 0) == []          # no improvement
    assert _cook_variants(_own(setup(0), 0, majors={0: 0}), 0) == []    # Fireplace, no animals
    s = _own(setup(0), 0, majors={0: 0}, sheep=2, cattle=1)             # Fireplace + animals
    assert set(_cook_variants(s, 0)) == {"sheep", "cattle"}


def test_award_is_once_per_turn():
    s = _award(_own(setup(0), 0), 0)
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    assert _SCORED in s.players[0].used_this_turn
    s = _award(s, 0)                                                     # already scored
    assert s.players[0].card_state.get(CARD_ID, 0) == 1


def test_react_awards_only_inside_a_lessons_resolution():
    assert _in_lessons(_lessons_stack(_own(setup(0), 0))) is True
    assert _in_lessons(_own(setup(0), 0)) is False
    inside = _react(_lessons_stack(_own(setup(0), 0)), 0)
    assert inside.players[0].card_state.get(CARD_ID, 0) == 1
    outside = _react(_own(setup(0), 0), 0)
    assert outside.players[0].card_state.get(CARD_ID, 0) == 0


def test_note_animal_cook_awards_for_owner_in_lessons():
    # The cook-site seam fires the reaction: a Lessons host on the stack + owner -> award.
    s = note_animal_cook(_lessons_stack(_own(setup(0), 0)), 0)
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    # No owner -> no award.
    s2 = note_animal_cook(_lessons_stack(setup(0)), 0)
    assert s2.players[0].card_state.get(CARD_ID, 0) == 0


# --- Integration: the explicit cook on the Lessons after-phase ---------------

def _drive_to_lessons_after(cs, occ="consultant"):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=occ))
    # Pop the play-occupation after-phase (only Stop) to reach the Lessons after-phase.
    if legal_actions(cs) == [Stop()]:
        cs = step(cs, Stop())
    return cs


def _card_state(*, occupations=(), hand=("consultant",), food=0, sheep=0):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        minor_improvements=frozenset({CARD_ID}),
        occupations=frozenset(occupations),
        hand_occupations=frozenset(hand),
        resources=Resources(food=food),
        animals=Animals(sheep=sheep),
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_majors(cs, owner_by_idx={0: cp})     # a Fireplace for the acting player
    return cs, cp


def test_explicit_cook_awards_and_cooks():
    cs, cp = _card_state(hand=("consultant",), food=0, sheep=2)
    cs = _drive_to_lessons_after(cs)
    assert FireTrigger(card_id=CARD_ID, variant="sheep") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id=CARD_ID, variant="sheep"))
    p = cs.players[cp]
    assert p.card_state.get(CARD_ID, 0) == 1        # the point
    assert p.animals.sheep == 1                     # cooked one sheep
    assert p.resources.food == 2                    # Fireplace sheep rate 2


def test_explicit_cook_not_offered_without_an_improvement():
    cs, cp = _card_state(hand=("consultant",), food=0, sheep=2)
    # Strip the Fireplace: no cooking improvement -> no cook variants.
    cs = with_majors(cs, owner_by_idx={0: None})
    cs = _drive_to_lessons_after(cs)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID for a in legal_actions(cs))


# --- Integration: an incidental cook paying the occupation's food cost -------

def test_incidental_cook_paying_occupation_cost_awards():
    # 2nd occupation costs 1 food; 0 food + a sheep + Fireplace -> pay by cooking the sheep,
    # which (during the Lessons resolution) earns the Cookery Lesson point.
    cs, cp = _card_state(occupations=("stable_architect",), hand=("consultant",), food=0, sheep=2)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))   # food short -> PendingFoodPayment
    cs = step(cs, CommitFoodPayment(grain=0, veg=0, sheep=1, boar=0, cattle=0))   # cook the sheep
    p = cs.players[cp]
    assert p.card_state.get(CARD_ID, 0) == 1                    # awarded at the incidental cook
    assert p.animals.sheep == 1                                 # one sheep cooked


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    import dataclasses
    score = _score_fn()
    assert score(setup(0), 0) == 0
    p = dataclasses.replace(setup(0).players[0],
                            card_state=setup(0).players[0].card_state.set(CARD_ID, 2))
    st = dataclasses.replace(setup(0), players=(p, setup(0).players[1]))
    assert score(st, 0) == 2
