"""Tests for Wholesale Market (minor improvement, D57; Dulcinaria Expansion).

Card text: "Place 1 food on each remaining round space. At the start of these
rounds, you get the food."
Cost: 2 Wood, 2 Vegetable. No prerequisite. VPs: 3. Not passing.

Category-8 deferred-goods card (mirrors tests/test_card_trellises.py): the whole
effect runs at play (on_play), scheduling +1 food onto EVERY remaining round space
R+1..14 (no count cap — unlike Trellises). Collection rides on `future_resources`,
paid out at the start of each scheduled round by `_complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.wholesale_market  # noqa: F401  (registers the card; not in __init__)

from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Phase
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_wholesale_market_registered():
    assert "wholesale_market" in MINORS
    spec = MINORS["wholesale_market"]
    assert spec.cost == Cost(resources=Resources(wood=2, veg=2))
    assert spec.vps == 3
    assert spec.passing_left is False
    assert spec.prereq is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    # Pure on-play minor — no trigger/hook machinery.
    for entries in TRIGGERS.values():
        assert "wholesale_market" not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# on_play scheduling — +1 food on EVERY remaining round space (no cap)
# ---------------------------------------------------------------------------

def test_on_play_schedules_all_remaining_rounds_from_round_1():
    s = setup(0)                       # R=1 → schedule rounds 2..14
    out = MINORS["wholesale_market"].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0                   # round 1 (current) untouched
    assert all(f[i] == 1 for i in range(1, 14))   # rounds 2..14
    assert sum(f) == 13


def test_on_play_starts_after_current_round_midgame():
    # Mid-game (R=7): scheduling starts at R+1=8, never re-credits the current round.
    s = fast_replace(setup(0), round_number=7)
    out = MINORS["wholesale_market"].on_play(s, 0)
    f = _food(out, 0)
    assert f[6] == 0                   # round 7 (current) untouched
    assert all(f[i] == 1 for i in range(7, 14))   # rounds 8..14
    assert sum(f) == 7


def test_on_play_last_round_schedules_nothing():
    # Round 14 is the final round — no remaining round spaces, so nothing scheduled.
    s = fast_replace(setup(0), round_number=14)
    out = MINORS["wholesale_market"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_round_13_schedules_only_round_14():
    s = fast_replace(setup(0), round_number=13)
    out = MINORS["wholesale_market"].on_play(s, 0)
    f = _food(out, 0)
    assert f[13] == 1                  # round 14
    assert sum(f) == 1                 # only the single remaining round


def test_on_play_only_affects_the_player():
    s = setup(0)
    out = MINORS["wholesale_market"].on_play(s, 0)
    # The opponent's schedule is untouched.
    assert sum(_food(out, 1)) == 0


def test_on_play_is_additive():
    # Playing twice (impossible in a real game, but verifies additive stacking)
    # doubles the food on each remaining slot.
    s = setup(0)
    out = MINORS["wholesale_market"].on_play(s, 0)
    out = MINORS["wholesale_market"].on_play(out, 0)
    f = _food(out, 0)
    assert all(f[i] == 2 for i in range(1, 14))


# ---------------------------------------------------------------------------
# End-to-end: play the minor at a real PendingPlayMinor, then collect at round start
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("wholesale_market",) + tuple(f"m{i}" for i in range(20)),
)


def test_play_minor_flow_and_round_start_collection():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    # Give the player the card in hand and the resources to pay (2 wood, 2 veg).
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"wholesale_market"}),
                     resources=Resources(wood=2, veg=2))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))

    # Drive a real PendingPlayMinor and commit the card.
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "wholesale_market"))

    # Card left the hand; cost paid; food scheduled on every remaining round.
    pl = cs.players[cp]
    assert "wholesale_market" in pl.minor_improvements
    assert "wholesale_market" not in pl.hand_minors
    assert pl.resources.wood == 0
    assert pl.resources.veg == 0
    f = _food(cs, cp)
    assert f[0] == 0
    assert all(f[i] == 1 for i in range(1, 14))   # rounds 2..14

    # Collection at the start of round 2: _complete_preparation pays out the slot.
    food_before = cs.players[cp].resources.food
    prep = fast_replace(cs, round_number=1, phase=Phase.PREPARATION)
    prep = _complete_preparation(prep)
    while prep.pending_stack:                       # resolve the reveal nature step
        prep = step(prep, legal_actions(prep)[0])
    assert prep.round_number == 2
    assert prep.players[cp].resources.food == food_before + 1
    # The round-2 slot is consumed; rounds 3..14 still hold their food.
    f2 = _food(prep, cp)
    assert f2[1] == 0
    assert all(f2[i] == 1 for i in range(2, 14))
