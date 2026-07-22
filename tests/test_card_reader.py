"""Tests for Reader (occupation, D085; Dulcinaria Expansion).

Card text (project canonical, per the JSON row): "As soon as you have 7 occupations
in front of you (including this one), this card provides room for one person."
(Printed compendium original: "6 ... In the draft variant, you need 7 occupations to
play this.")

Project ruling (user 2026-07-16): draft-only, so the +1 PEOPLE-capacity benefit is
hardcoded to activate at >= 7 occupations. Verified as the raw bonus and end-to-end
as the family-growth-with-room legality flip.

NOTE: the draft PLAY prerequisite (need 7 occupations to play) is not yet enforced —
occupations carry no per-card play prereq in the engine — so this suite covers only
the capacity behaviour.
"""
import agricola.cards.reader  # noqa: F401  (registers the card)

from agricola.cards.reader import _capacity_bonus
from agricola.cards.specs import OCCUPATIONS
from agricola.legality import _housing_capacity, _legal_basic_wish_for_children
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_people, with_space

CARD_ID = "reader"


def _set_occupations(state, idx, card_ids):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=frozenset(card_ids)) if i == idx
        else state.players[i] for i in range(2)))


_SEVEN = {CARD_ID, "a", "b", "c", "d", "e", "f"}       # 7 including Reader
_SIX = {CARD_ID, "a", "b", "c", "d", "e"}              # 6 including Reader


# --- Registration -----------------------------------------------------------

def test_registration_and_noop_on_play():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


# --- The capacity bonus (raw) -----------------------------------------------

def test_no_bonus_below_seven_occupations():
    s = _set_occupations(setup(seed=0), 0, _SIX)       # 6 occupations
    assert _capacity_bonus(s, 0) == 0


def test_plus_one_at_seven_occupations():
    s = _set_occupations(setup(seed=0), 0, _SEVEN)
    assert _capacity_bonus(s, 0) == 1


# --- End-to-end: the family-growth-with-room gate flips ----------------------

def test_gate_flips_at_seven_occupations():
    """2 rooms, 2 people: no spare capacity -> Basic Wish illegal. At 7 occupations
    Reader's +1 makes capacity 3 > 2 -> legal."""
    base = with_space(with_current_player(setup(seed=0), 0),
                      "basic_wish_for_children", revealed=True)
    base = with_people(base, 0, total=2)               # == 2 rooms

    six = _set_occupations(base, 0, _SIX)
    assert _housing_capacity(six, 0) == 2
    assert _legal_basic_wish_for_children(six) is False

    seven = _set_occupations(base, 0, _SEVEN)
    assert _housing_capacity(seven, 0) == 3
    assert _legal_basic_wish_for_children(seven) is True
