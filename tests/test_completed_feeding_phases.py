"""Unit pins for `helpers.completed_feeding_phases` — the GLOBAL, game-time
feeding-phase count (user rulings 2026-07-21: one shared count, ticking when
the harvest's feeding resolves on game time regardless of any player's
participation — a Layabout-style skip, even by every player, does not stall
it; that ruling is structural here, since the derivation reads only round
arithmetic + the walk position and never looks at players).

Synthetic states: the count is a pure function of (round_number, phase,
harvest_cursor), so we stamp those fields directly onto a setup state.
"""
import agricola.cards  # populate registries (parity with real runs)  # noqa: F401

from agricola.cards.harvest_windows import sentinel_position
from agricola.constants import Phase
from agricola.helpers import completed_feeding_phases
from agricola.replace import fast_replace
from agricola.setup import setup


def _at(round_number, phase, cursor=None):
    s = setup(0)
    return fast_replace(s, round_number=round_number, phase=phase,
                        harvest_cursor=cursor)


def test_before_any_harvest():
    assert completed_feeding_phases(_at(1, Phase.WORK)) == 0
    assert completed_feeding_phases(_at(4, Phase.WORK)) == 0
    assert completed_feeding_phases(_at(4, Phase.RETURN_HOME)) == 0


def test_within_first_harvest():
    feed_done = sentinel_position("feeding", 1)
    assert completed_feeding_phases(_at(4, Phase.HARVEST_FIELD)) == 0
    # First player's feed band: not complete.
    assert completed_feeding_phases(
        _at(4, Phase.HARVEST_FEED, sentinel_position("feeding", 0))) == 0
    # Final player's payment still up (cursor AT the sentinel): not complete.
    assert completed_feeding_phases(_at(4, Phase.HARVEST_FEED, feed_done)) == 0
    # Walk advanced past the final payment (their after_feeding window): complete.
    assert completed_feeding_phases(_at(4, Phase.HARVEST_FEED, feed_done + 1)) == 1
    # Defensive: mid-FEED with no cursor -> not complete.
    assert completed_feeding_phases(_at(4, Phase.HARVEST_FEED, None)) == 0
    assert completed_feeding_phases(_at(4, Phase.HARVEST_BREED)) == 1


def test_between_harvests():
    # PREPARATION has already incremented round_number, so the just-finished
    # harvest sits in the < round_number base (no +1 branch needed).
    assert completed_feeding_phases(_at(5, Phase.PREPARATION)) == 1
    assert completed_feeding_phases(_at(5, Phase.WORK)) == 1
    assert completed_feeding_phases(_at(7, Phase.WORK)) == 1
    assert completed_feeding_phases(_at(8, Phase.WORK)) == 2
    assert completed_feeding_phases(_at(12, Phase.WORK)) == 4


def test_late_game_and_scoring():
    assert completed_feeding_phases(_at(13, Phase.HARVEST_BREED)) == 5
    assert completed_feeding_phases(_at(14, Phase.WORK)) == 5
    assert completed_feeding_phases(_at(14, Phase.HARVEST_FIELD)) == 5
    assert completed_feeding_phases(_at(14, Phase.BEFORE_SCORING)) == 6
