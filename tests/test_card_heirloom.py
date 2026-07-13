"""Tests for Heirloom (minor E29): printed 2 VP, prereq "your person on Day Laborer",
no effect."""
import agricola.cards.heirloom  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import with_space


def test_registration():
    spec = MINORS["heirloom"]
    assert spec.vps == 2
    assert spec.cost.resources == Resources()        # no cost
    assert spec.on_play is not None                  # a no-op default
    assert not spec.passing_left


def test_prereq_requires_own_person_on_day_laborer():
    state = setup(seed=0)
    # No one on Day Laborer -> prereq fails for both players.
    assert prereq_met(MINORS["heirloom"], state, 0) is False
    assert prereq_met(MINORS["heirloom"], state, 1) is False

    # Player 0 has a person on Day Laborer.
    s0 = with_space(state, "day_laborer", workers=(1, 0))
    assert prereq_met(MINORS["heirloom"], s0, 0) is True
    assert prereq_met(MINORS["heirloom"], s0, 1) is False   # not player 1's person

    # Player 1 has a person there instead.
    s1 = with_space(state, "day_laborer", workers=(0, 1))
    assert prereq_met(MINORS["heirloom"], s1, 0) is False
    assert prereq_met(MINORS["heirloom"], s1, 1) is True


def test_no_scoring_term_registered():
    # The 2 VP ride MinorSpec.vps; there is no separate scoring term.
    from agricola.scoring import SCORING_TERMS
    assert not any(cid == "heirloom" for cid, _ in SCORING_TERMS)
