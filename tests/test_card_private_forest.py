"""Tests for Private Forest (minor improvement, C74; Consul Dirigens Expansion).

Card text: "Place 1 wood on each remaining even-numbered round space. At the start
of these rounds, you get the wood."
Cost: 2 Food. Prerequisite: 1 Occupation. VPs: none. Not passing.

Category 8 (deferred goods) — byte-identical effect to Thick Forest (B74), differing
only in cost (a spendable 2 Food, not Thick Forest's 5-clay prereq) and prereq
(1 occupation). The wood rides on `future_resources` and is collected at the start of
each scheduled even round in `engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.private_forest  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import GameState

CARD_ID = "private_forest"


def _wood(state: GameState, idx: int):
    return [r.wood for r in state.players[idx].future_resources]


def _give_occ_count(state: GameState, idx: int, n: int) -> GameState:
    """Give player `idx` exactly `n` placeholder occupations (for the count prereq)."""
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(f"_occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_private_forest_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=2))  # spendable 2 Food
    assert spec.min_occupations == 1                        # prereq: 1 occupation
    assert spec.vps == 0
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# on_play effect — schedule 1 wood on each remaining even round
# ---------------------------------------------------------------------------

def test_on_play_schedules_remaining_even_rounds():
    s = setup(0)   # R=1 → even rounds 2,4,6,8,10,12,14
    out = MINORS[CARD_ID].on_play(s, 0)
    w = _wood(out, 0)
    for slot in range(14):
        rnd = slot + 1
        assert w[slot] == (1 if (rnd > 1 and rnd % 2 == 0) else 0)
    assert sum(w) == 7


def test_on_play_strict_lower_bound_skips_current_even_round():
    # Entering on an EVEN round: that round's space was already collected at its
    # start, so the strict R+1 bound must NOT re-schedule it.
    s = fast_replace(setup(0), round_number=4)   # remaining even rounds: 6,8,10,12,14
    out = MINORS[CARD_ID].on_play(s, 0)
    w = _wood(out, 0)
    assert w[3] == 0                              # round 4 (current) NOT scheduled
    for rnd in (6, 8, 10, 12, 14):
        assert w[rnd - 1] == 1
    assert sum(w) == 5


def test_on_play_clamps_past_14():
    s = fast_replace(setup(0), round_number=13)   # only even round left is 14
    out = MINORS[CARD_ID].on_play(s, 0)
    w = _wood(out, 0)
    assert w[13] == 1
    assert sum(w) == 1


def test_on_play_additive_with_existing_schedule():
    # schedule_resources is additive: a pre-existing wood promise stacks.
    s = setup(0)
    p = s.players[0]
    slots = list(p.future_resources)
    slots[1] = slots[1] + Resources(wood=2)       # round 2 already has 2 wood
    p = fast_replace(p, future_resources=tuple(slots))
    s = fast_replace(s, players=(p, s.players[1]))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _wood(out, 0)[1] == 3                   # 2 existing + 1 scheduled


# ---------------------------------------------------------------------------
# Prerequisite — hold >=1 occupation (have-check, not spent)
# ---------------------------------------------------------------------------

def test_prereq_requires_one_occupation():
    s = setup(0)
    assert not prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 0), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 1), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 3), 0)  # >=1, no upper cap


# ---------------------------------------------------------------------------
# Real round-start collection flow
# ---------------------------------------------------------------------------

def test_scheduled_wood_collected_at_round_start():
    # Schedule from round 1, then enter round 2 (PREPARATION → WORK) and confirm the
    # owner receives exactly the 1 wood promised for round 2, and the slot is cleared.
    s = setup(0)
    s = _give_occ_count(s, 0, 1)
    s = MINORS[CARD_ID].on_play(s, 0)
    assert _wood(s, 0)[1] == 1                      # round 2 slot armed

    before_wood = s.players[0].resources.wood
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    # The round-2 wood was distributed into supply and its slot cleared in place.
    assert out.players[0].resources.wood == before_wood + 1
    assert _wood(out, 0)[1] == 0   # the round-2 carrier slot is now empty


def test_no_wood_collected_on_odd_round():
    # Entering round 3 (an odd round) collects nothing from this card.
    s = setup(0)
    s = _give_occ_count(s, 0, 1)
    s = MINORS[CARD_ID].on_play(s, 0)
    before_wood = s.players[0].resources.wood
    s = fast_replace(s, round_number=2, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 3
    assert out.players[0].resources.wood == before_wood   # round 3 not scheduled
