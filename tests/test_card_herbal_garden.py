"""Tests for Herbal Garden (minor E36): 2 VP, prereq 1 pasture, standing "one pasture must
be empty" restriction (the capacity fold is exercised in test_cards_empty_pasture.py)."""
import agricola.cards.herbal_garden  # noqa: F401  (registers the card)

from agricola.cards.capacity_mods import EMPTY_PASTURE_CARDS
from agricola.cards.herbal_garden import _on_play
from agricola.cards.specs import MINORS, prereq_met
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import setup

from scripts.profile_states import STATES


def test_registration():
    spec = MINORS["herbal_garden"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 2
    assert any(cid == "herbal_garden" for cid, _ in EMPTY_PASTURE_CARDS)


def test_prereq_requires_a_pasture():
    s = setup(0)                          # no pastures at start
    assert prereq_met(MINORS["herbal_garden"], s, 0) is False
    s2 = STATES["mid_round_6_basic"]()    # has pastures
    assert prereq_met(MINORS["herbal_garden"], s2, 0) is True


def test_on_play_flags_accommodation_when_animals_present():
    state = STATES["mid_round_6_basic"]()
    p = fast_replace(state.players[0], animals=Animals(sheep=2))
    state = fast_replace(state, players=(p, state.players[1]))
    out = _on_play(state, 0)
    assert out.players[0].animals_need_accommodation is True


def test_on_play_no_flag_when_no_animals():
    state = STATES["mid_round_6_basic"]()
    p = fast_replace(state.players[0], animals=Animals())
    state = fast_replace(state, players=(p, state.players[1]))
    out = _on_play(state, 0)
    assert out.players[0].animals_need_accommodation is False
