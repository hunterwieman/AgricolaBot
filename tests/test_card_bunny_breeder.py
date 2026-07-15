"""Tests for Bunny Breeder (occupation, E139; Ephipparius Expansion; players 3+).

Card text: "Select a future round space, subtract the number of the current round
from it, and place this many food on that space. At the start of that round, you
get the food."

A play-variant occupation: one route per future round, the variant-aware on_play
schedules (selected - current) food onto that round via `schedule_resources`.
"""
import agricola.cards.bunny_breeder  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import CommitPlayOccupation
from agricola.cards.bunny_breeder import CARD_ID, _variants
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, round_number=3):
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = dataclasses.replace(cs, round_number=round_number)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({CARD_ID}),
                     occupations=frozenset())
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayOccupation(
        player_idx=cp, initiated_by_id="space:lessons", cost=Resources()),))
    return cs, cp


def _commit(cs, variant):
    return next(a for a in legal_actions(cs)
               if isinstance(a, CommitPlayOccupation)
               and a.card_id == CARD_ID and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration + the future-round variant list
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_OCCUPATION_VARIANTS


def test_variants_are_the_future_rounds():
    cs, _cp = _state(round_number=3)
    assert [v for v, _s in _variants(cs, cs.current_player)] == [
        str(r) for r in range(4, 15)]


def test_variants_noop_in_last_round():
    cs, _cp = _state(round_number=14)
    assert _variants(cs, cs.current_player) == [("none", Resources())]


# ---------------------------------------------------------------------------
# The scheduling: (selected - current) food onto the selected round's slot
# ---------------------------------------------------------------------------

def test_schedules_difference_onto_selected_round():
    cs, cp = _state(round_number=3)
    out = step(cs, _commit(cs, "10"))
    p = out.players[cp]
    # Slot r-1 holds round r's promised goods (Well convention).
    assert p.future_resources[9] == Resources(food=7)      # 10 - 3
    # No other slot was touched.
    assert all(p.future_resources[i] == Resources()
               for i in range(14) if i != 9)
    assert CARD_ID in p.occupations


def test_next_round_places_one_food():
    cs, cp = _state(round_number=6)
    out = step(cs, _commit(cs, "7"))                        # 7 - 6 = 1 food
    assert out.players[cp].future_resources[6] == Resources(food=1)


def test_far_round_places_large_amount():
    cs, cp = _state(round_number=1)
    out = step(cs, _commit(cs, "14"))                       # 14 - 1 = 13 food
    assert out.players[cp].future_resources[13] == Resources(food=13)
