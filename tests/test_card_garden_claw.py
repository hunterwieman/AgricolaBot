"""Tests for Garden Claw (minor improvement, C47; Corbarius Expansion).

Card text: "Place 1 food on each remaining round space, up to three times the
number of planted fields you have. At the start of these rounds, you get the food."
Cost: 1 Wood. No prerequisite. VPs: 0. Not passing.

Category-8 deferred-goods card (mirrors tests/test_card_trellises.py): the whole
effect runs at play (on_play), scheduling +1 food onto rounds R+1..R+3*P where
P = the number of PLANTED fields (FIELD cell holding grain or veg) at play-time.
Collection rides on `future_resources`, paid out at the start of each scheduled
round by `_complete_preparation`. The "up to ... remaining round space" cap is the
1..14 slot clamp in `schedule_resources`, so the effective count is
min(remaining rounds, 3*P).
"""
from __future__ import annotations

import agricola.cards.garden_claw  # noqa: F401  (registers the card; not in __init__)

from agricola.cards.card_fields import stacks_to_store
from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Phase
from tests.factories import with_fields, with_pending_stack, with_sown_fields
from tests.test_utils import sole_play_minor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_garden_claw_registered():
    assert "garden_claw" in MINORS
    spec = MINORS["garden_claw"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None          # no prerequisite
    # Pure on-play minor — no trigger/hook machinery.
    for entries in TRIGGERS.values():
        assert "garden_claw" not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# on_play scheduling — P planted fields → +1 food on the next 3*P round spaces
# ---------------------------------------------------------------------------

def test_on_play_schedules_three_per_planted_field():
    # 1 planted field at R=1 → 3 scheduled rounds: 2, 3, 4.
    s = with_sown_fields(setup(0), 0, grain_fields=[(0, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0                     # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == 1     # rounds 2,3,4
    assert f[4] == 0                     # round 5 not scheduled
    assert sum(f) == 3


def test_on_play_count_is_three_times_planted_fields():
    # 2 planted fields (1 grain + 1 veg) at R=1 → 6 scheduled rounds: 2..7.
    s = with_sown_fields(setup(0), 0, grain_fields=[(0, 0)], veg_fields=[(0, 1)])
    out = MINORS["garden_claw"].on_play(s, 0)
    f = _food(out, 0)
    assert [f[i] for i in range(1, 7)] == [1, 1, 1, 1, 1, 1]
    assert f[0] == 0 and f[7] == 0
    assert sum(f) == 6


def test_on_play_veg_field_counts_as_planted():
    # A veg-only field is planted, same as a grain field.
    s = with_sown_fields(setup(0), 0, veg_fields=[(0, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 3       # 1 planted field → 3 food slots


def test_on_play_unplanted_field_does_not_count():
    # An EMPTY (plowed but unsown) field is NOT planted → schedules nothing.
    s = with_fields(setup(0), 0, [(0, 0), (0, 1)])
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_zero_planted_fields_schedules_nothing():
    s = setup(0)
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_clamps_past_round_14():
    # Round 13 with 2 planted fields → would want 6 rounds (14..19), but only round
    # 14 remains; rounds 15..19 dropped by the 1..14 slot clamp (the "remaining round
    # spaces" cap, for free).
    s = with_sown_fields(fast_replace(setup(0), round_number=13), 0,
                         grain_fields=[(0, 0)], veg_fields=[(0, 1)])
    out = MINORS["garden_claw"].on_play(s, 0)
    f = _food(out, 0)
    assert f[13] == 1                    # round 14
    assert sum(f) == 1                   # only 1 remaining round, not 6


def test_on_play_starts_after_current_round_midgame():
    # Mid-game (R=7): scheduling starts at R+1=8, never re-credits the current round.
    s = with_sown_fields(fast_replace(setup(0), round_number=7), 0,
                         grain_fields=[(0, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    f = _food(out, 0)
    assert f[6] == 0                     # round 7 (current) untouched
    assert f[7] == f[8] == f[9] == 1     # rounds 8, 9, 10
    assert sum(f) == 3


def test_on_play_scoped_to_the_playing_player():
    # Only the playing player's schedule is touched; the opponent's is untouched.
    s = with_sown_fields(setup(0), 0, grain_fields=[(0, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 3
    assert sum(_food(out, 1)) == 0


def test_on_play_counts_only_own_planted_fields():
    # Opponent's planted fields don't inflate the count.
    s = with_sown_fields(setup(0), 1, grain_fields=[(0, 0), (0, 1)])  # opp planted
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0       # player 0 has no planted fields


# ---------------------------------------------------------------------------
# Card-fields (ruling 45, 2026-07-12): "planted fields" is a field-count
# reader — a card-field holding ANYTHING is a planted field (1 per card,
# ruling 47; a wood-planted card counts — it IS planted).
# ---------------------------------------------------------------------------

def _own_card_field(state, idx, cid, stacks=None):
    """Give player `idx` the card-field `cid` in play, optionally with contents."""
    p = state.players[idx]
    store = (stacks_to_store(p.card_state, cid, stacks)
             if stacks is not None else p.card_state)
    p = fast_replace(p, minor_improvements=p.minor_improvements | {cid},
                     card_state=store)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_on_play_card_field_raises_the_planted_count():
    # 1 grid planted field + 1 veg-holding Beanfield -> P=2 -> 6 slots (2..7).
    s = with_sown_fields(setup(0), 0, grain_fields=[(0, 0)])
    s = _own_card_field(s, 0, "beanfield", [(0, 2, 0, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    f = _food(out, 0)
    assert [f[i] for i in range(1, 7)] == [1, 1, 1, 1, 1, 1]
    assert sum(f) == 6


def test_on_play_card_field_alone_schedules():
    # Boundary the pre-ruling-45 code failed: NO grid fields — a veg-holding
    # Beanfield alone is 1 planted field -> 3 slots.
    s = _own_card_field(setup(0), 0, "beanfield", [(0, 2, 0, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 3


def test_on_play_wood_planted_card_field_counts_once():
    # A wood-planted Wood Field IS planted (its own text says "plant wood on
    # this card") and counts exactly once, however many stacks (ruling 47).
    s = _own_card_field(setup(0), 0, "wood_field", [(0, 0, 3, 0), (0, 0, 3, 0)])
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 3       # P=1 (one card), not 2 (two stacks)


def test_on_play_unsown_card_field_does_not_count():
    # A never-sown Beanfield holds nothing — not planted -> schedules nothing.
    s = _own_card_field(setup(0), 0, "beanfield")
    out = MINORS["garden_claw"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


# ---------------------------------------------------------------------------
# End-to-end: play the minor at a real PendingPlayMinor, then collect at round start
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("garden_claw",) + tuple(f"m{i}" for i in range(20)),
)


def test_play_minor_flow_and_round_start_collection():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    # Give the player the card in hand, the wood to pay, and 1 planted field.
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"garden_claw"}),
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_sown_fields(cs, cp, grain_fields=[(0, 0)])   # R=1 → schedule rounds 2,3,4

    # Drive a real PendingPlayMinor and commit the card.
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "garden_claw"))

    # Card left the hand; cost paid; food scheduled on rounds 2,3,4.
    pl = cs.players[cp]
    assert "garden_claw" in pl.minor_improvements
    assert "garden_claw" not in pl.hand_minors
    assert pl.resources.wood == 0
    f = _food(cs, cp)
    assert f[1] == 1 and f[2] == 1 and f[3] == 1 and f[0] == 0 and f[4] == 0

    # Collection at the start of round 2: _complete_preparation pays out the slot.
    food_before = cs.players[cp].resources.food
    prep = fast_replace(cs, round_number=1, phase=Phase.PREPARATION)
    prep = _complete_preparation(prep)
    while prep.pending_stack:                       # resolve the reveal nature step
        prep = step(prep, legal_actions(prep)[0])
    assert prep.round_number == 2
    assert prep.players[cp].resources.food == food_before + 1
