"""Tests for Land Heir (occupation, E119; Ephipparius Expansion).

Card text: "If you play this card in round 4 or before, place 4 wood and 4 clay
on the space for round 9. At the start of this round, you get the resources."

A Category-8 deferred-goods occupation with a play-time round gate: played in
round 4 or before it schedules 4 wood + 4 clay onto the round-9 space
(`future_resources` slot 8), collected when round 9 is entered; played round 5+
it does nothing (still playable). Covered:
- registration (in OCCUPATIONS, plain occupation);
- the on-play schedule at an early round (round-9 slot only, both goods);
- the gate boundary: round 4 exactly schedules, round 5 places nothing;
- the opponent's schedule untouched;
- a REAL play-via-Lessons flow placing the schedule;
- an end-to-end round-9 entry collection (goods land in actual supply, slot
  consumed);
- hand-only inertness (nothing scheduled, no trigger registered — the effect is
  on_play only).
"""
import agricola.cards.land_heir  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("land_heir",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wood(state, idx):
    return [r.wood for r in state.players[idx].future_resources]


def _clay(state, idx):
    return [r.clay for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_land_heir_registered_plain_occupation():
    # OccupationSpec carries only card_id + on_play (played via Lessons; the
    # round-gated schedule is the whole effect). Subset check, never exact-set.
    assert "land_heir" in OCCUPATIONS
    spec = OCCUPATIONS["land_heir"]
    assert spec.card_id == "land_heir"
    assert callable(spec.on_play)


# ---------------------------------------------------------------------------
# On-play schedule — the round gate
# ---------------------------------------------------------------------------

def test_on_play_round_2_schedules_round_9():
    s = fast_replace(setup(0), round_number=2)
    out = OCCUPATIONS["land_heir"].on_play(s, 0)
    w, c = _wood(out, 0), _clay(out, 0)
    # 4 wood + 4 clay on the round-9 slot (index 8) and nowhere else.
    assert w[8] == 4 and sum(w) == 4
    assert c[8] == 4 and sum(c) == 4
    # Nothing but wood/clay is scheduled.
    assert out.players[0].future_resources[8] == Resources(wood=4, clay=4)


def test_on_play_round_4_exactly_schedules():
    # "In round 4 or before" — round 4 is inside the gate.
    s = fast_replace(setup(0), round_number=4)
    out = OCCUPATIONS["land_heir"].on_play(s, 0)
    assert _wood(out, 0)[8] == 4 and _clay(out, 0)[8] == 4


def test_on_play_round_5_places_nothing():
    # Round 5+ fails the condition: playable, but no resources are placed.
    s = fast_replace(setup(0), round_number=5)
    out = OCCUPATIONS["land_heir"].on_play(s, 0)
    assert all(g == Resources() for g in out.players[0].future_resources)


def test_on_play_other_player_untouched():
    s = setup(0)
    out = OCCUPATIONS["land_heir"].on_play(s, 0)
    assert all(g == Resources() for g in out.players[1].future_resources)


# ---------------------------------------------------------------------------
# Real play-via-Lessons flow
# ---------------------------------------------------------------------------

def test_played_via_lessons_in_round_1_schedules_round_9():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"land_heir"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    assert cs.round_number == 1   # round 1 <= 4: the gate passes

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="land_heir"))

    assert "land_heir" in cs.players[cp].occupations
    assert cs.players[cp].future_resources[8] == Resources(wood=4, clay=4)


# ---------------------------------------------------------------------------
# End-to-end round-9 collection
# ---------------------------------------------------------------------------

def test_scheduled_goods_collected_entering_round_9():
    # Schedule at round 2, then drive the real preparation step entering round 9
    # and confirm 4 wood + 4 clay land in actual supply.
    s = fast_replace(setup(0), round_number=2)
    s = OCCUPATIONS["land_heir"].on_play(s, 0)
    before = s.players[0].resources
    prep = fast_replace(s, round_number=8, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 9
    assert out.players[0].resources.wood == before.wood + 4
    assert out.players[0].resources.clay == before.clay + 4
    # The slot is consumed once collected.
    assert out.players[0].future_resources[8] == Resources()


def test_no_collection_before_round_9():
    # Entering round 3 (or any round before 9) pays nothing from this schedule.
    s = fast_replace(setup(0), round_number=2)
    s = OCCUPATIONS["land_heir"].on_play(s, 0)
    before = s.players[0].resources
    prep = fast_replace(s, round_number=2, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 3
    assert out.players[0].resources.wood == before.wood
    assert out.players[0].resources.clay == before.clay
    assert out.players[0].future_resources[8] == Resources(wood=4, clay=4)


# ---------------------------------------------------------------------------
# Hand-only inertness
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    # In hand (not played): nothing is scheduled — the effect is on_play only,
    # and the card registers no triggers.
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"land_heir"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    assert all(g == Resources() for g in cs.players[cp].future_resources)
    assert not any(e.card_id == "land_heir"
                   for entries in TRIGGERS.values() for e in entries)
