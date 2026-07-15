import agricola.cards.clay_deliveryman  # noqa: F401
"""Clay Deliveryman (D120): 1 clay on each remaining round space in 6..14."""
from agricola.cards.specs import OCCUPATIONS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

CARD_ID = "clay_deliveryman"


def _slots(state, idx):
    return state.players[idx].future_resources


def test_registered():
    assert CARD_ID in OCCUPATIONS


def test_played_round_1_seeds_rounds_6_through_14():
    s = setup(0)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    for r in range(1, 15):
        expected = Resources(clay=1) if r >= 6 else Resources()
        assert _slots(out, 0)[r - 1] == expected, r


def test_played_round_8_seeds_only_the_remaining_band():
    s = fast_replace(setup(0), round_number=8)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    for r in range(1, 15):
        expected = Resources(clay=1) if r >= 9 else Resources()
        assert _slots(out, 0)[r - 1] == expected, r


def test_played_round_14_seeds_nothing():
    s = fast_replace(setup(0), round_number=14)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert all(slot == Resources() for slot in _slots(out, 0))


def test_opponent_untouched():
    s = setup(0)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert all(slot == Resources() for slot in _slots(out, 1))


def test_collection_pays_at_round_entry():
    from agricola.engine import _complete_preparation
    s = fast_replace(setup(0), round_number=5)
    s = OCCUPATIONS[CARD_ID].on_play(s, 0)
    clay0 = s.players[0].resources.clay
    s = _complete_preparation(s)          # enter round 6
    assert s.players[0].resources.clay == clay0 + 1
    assert _slots(s, 0)[5] == Resources()  # slot consumed
