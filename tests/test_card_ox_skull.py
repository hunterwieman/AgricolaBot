"""Tests for Ox Skull (minor E37): on-play +1 food, +3 at scoring with no cattle, and a
before-scoring keep/discard offer at exactly 1 cattle."""
import agricola.cards.ox_skull  # noqa: F401  (registers the card)

from agricola.actions import CommitCardChoice
from agricola.cards.ox_skull import CARD_ID, _before_scoring_options
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import BEFORE_SCORING_CARDS, CARD_CHOICE_RESOLVERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.pending import PendingCardChoice
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_phase


def _own(state, idx, **player_kwargs):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {CARD_ID},
                     **player_kwargs)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _before_scoring_state(cattle):
    s = _own(setup(0), 0, animals=Animals(cattle=cattle))
    return with_phase(s, Phase.BEFORE_SCORING)


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources()      # no cost
    assert spec.vps == 0                            # bonus points via the scoring term
    assert CARD_ID in BEFORE_SCORING_CARDS
    assert CARD_ID in CARD_CHOICE_RESOLVERS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- Prereq / on-play / scoring ---------------------------------------------

def test_prereq_requires_cattle():
    s = setup(0)
    assert prereq_met(MINORS[CARD_ID], s, 0) is False
    s2 = _own(setup(0), 0, animals=Animals(cattle=1))
    assert prereq_met(MINORS[CARD_ID], s2, 0) is True


def test_on_play_gives_one_food():
    s = _own(setup(0), 0, animals=Animals(cattle=1), resources=Resources())
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.food == 1


def test_scoring_three_only_when_no_cattle():
    score = _score_fn()
    assert score(_own(setup(0), 0, animals=Animals(cattle=0)), 0) == 3
    assert score(_own(setup(0), 0, animals=Animals(cattle=1)), 0) == 0
    assert score(_own(setup(0), 0, animals=Animals(cattle=3)), 0) == 0


# --- Before-scoring offer (unit) --------------------------------------------

def test_offer_only_at_one_cattle():
    assert _before_scoring_options(_own(setup(0), 0, animals=Animals(cattle=0)), 0) == ()
    assert _before_scoring_options(_own(setup(0), 0, animals=Animals(cattle=1)), 0) == ("keep", "discard")
    assert _before_scoring_options(_own(setup(0), 0, animals=Animals(cattle=2)), 0) == ()


# --- The before-scoring window (real walk) ----------------------------------

def test_window_offers_choice_at_one_cattle():
    out = _advance_until_decision(_before_scoring_state(cattle=1))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.options == ("keep", "discard")
    assert top.initiated_by_id == "card:ox_skull"


def test_discard_removes_cattle_and_earns_three():
    out = _advance_until_decision(_before_scoring_state(cattle=1))
    out = step(out, CommitCardChoice(index=1))       # discard
    assert out.players[0].animals.cattle == 0
    assert not out.pending_stack                       # window closed, terminal
    assert _score_fn()(out, 0) == 3


def test_keep_leaves_cattle_and_is_not_re_offered():
    out = _advance_until_decision(_before_scoring_state(cattle=1))
    out = step(out, CommitCardChoice(index=0))       # keep
    assert out.players[0].animals.cattle == 1
    assert not any(isinstance(f, PendingCardChoice) for f in out.pending_stack)
    assert _score_fn()(out, 0) == 0


def test_no_window_at_zero_cattle():
    out = _advance_until_decision(_before_scoring_state(cattle=0))
    assert not any(isinstance(f, PendingCardChoice) for f in out.pending_stack)


def test_family_reaches_scoring_without_a_window():
    # No owner -> the BEFORE_SCORING boundary returns terminal directly (byte-identical).
    s = with_phase(setup(0), Phase.BEFORE_SCORING)
    out = _advance_until_decision(s)
    assert not out.pending_stack
    assert out.phase == Phase.BEFORE_SCORING
