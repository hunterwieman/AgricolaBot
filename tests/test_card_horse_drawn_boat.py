"""Horse-Drawn Boat (D41) — alternates 1 food / 1 sheep onto each remaining round
space, starting with food. Food rides future_resources (collected in
_complete_preparation); sheep ride future_rewards (collected + auto-accommodated in
_collect_future_rewards). See agricola/cards/horse_drawn_boat.py.
"""
import agricola.cards.horse_drawn_boat  # noqa: F401  (registers the MinorSpec)

from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _collect_future_rewards, _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import setup


def _with_occupations(state, idx, n):
    p = fast_replace(state.players[idx],
                     occupations=frozenset(f"o{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_horse_drawn_boat_registered():
    spec = MINORS["horse_drawn_boat"]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 3
    assert spec.passing_left is False
    assert spec.vps == 0


def test_horse_drawn_boat_prereq_needs_3_occupations():
    s = setup(0)
    assert not prereq_met(MINORS["horse_drawn_boat"], _with_occupations(s, 0, 2), 0)
    assert prereq_met(MINORS["horse_drawn_boat"], _with_occupations(s, 0, 3), 0)


def test_horse_drawn_boat_alternation_from_round_1():
    # Played in round 1 → remaining spaces are rounds 2..14.
    # Starting with food: food on R+1, R+3, ... = rounds 2,4,6,8,10,12,14 (slots 1,3,..,13)
    # then sheep on R+2, R+4, ... = rounds 3,5,7,9,11,13 (slots 2,4,..,12).
    s = setup(0)
    assert s.round_number == 1
    s2 = MINORS["horse_drawn_boat"].on_play(s, 0)
    fr = s2.players[0].future_resources
    fw = s2.players[0].future_rewards

    food_rounds = [2, 4, 6, 8, 10, 12, 14]
    sheep_rounds = [3, 5, 7, 9, 11, 13]
    for rnd in food_rounds:
        assert fr[rnd - 1] == Resources(food=1), rnd
    for rnd in sheep_rounds:
        assert fw[rnd - 1].animals == Animals(sheep=1), rnd

    # Nothing else leaks: food only on food rounds, sheep only on sheep rounds.
    assert sum(slot.food for slot in fr) == len(food_rounds)
    assert sum(w.animals.sheep for w in fw) == len(sheep_rounds)
    # Food slots carry no animals; sheep slots carry no food.
    for rnd in food_rounds:
        assert fw[rnd - 1].animals == Animals()
    for rnd in sheep_rounds:
        assert fr[rnd - 1] == Resources()
    # Round 1's own slot is untouched (already collected).
    assert fr[0] == Resources()
    assert fw[0].animals == Animals()
    # Opponent untouched.
    assert all(not slot for slot in s2.players[1].future_resources)
    assert all(not w for w in s2.players[1].future_rewards)


def test_horse_drawn_boat_alternation_anchored_to_remaining_not_parity():
    # Played in round 2 (an EVEN round) → remaining = rounds 3..14.
    # "Starting with food" is anchored to the FIRST remaining space (round 3), NOT to
    # round parity: food on rounds 3,5,7,... (ODD rounds here) and sheep on 4,6,8,...
    # This is the opposite parity from the round-1 case, proving anchor-to-remaining.
    s = setup(0)
    s = fast_replace(s, round_number=2)
    s2 = MINORS["horse_drawn_boat"].on_play(s, 0)
    fr = s2.players[0].future_resources
    fw = s2.players[0].future_rewards

    food_rounds = [3, 5, 7, 9, 11, 13]
    sheep_rounds = [4, 6, 8, 10, 12, 14]
    for rnd in food_rounds:
        assert fr[rnd - 1] == Resources(food=1), rnd
    for rnd in sheep_rounds:
        assert fw[rnd - 1].animals == Animals(sheep=1), rnd
    assert sum(slot.food for slot in fr) == len(food_rounds)
    assert sum(w.animals.sheep for w in fw) == len(sheep_rounds)


def test_horse_drawn_boat_only_remaining_rounds():
    # Played in round 13 → remaining = [14]. Only round 14 gets food (starting with food).
    s = setup(0)
    s = fast_replace(s, round_number=13)
    s2 = MINORS["horse_drawn_boat"].on_play(s, 0)
    assert s2.players[0].future_resources[13] == Resources(food=1)   # round 14
    assert sum(slot.food for slot in s2.players[0].future_resources) == 1
    assert all(w.animals == Animals() for w in s2.players[0].future_rewards)


def test_horse_drawn_boat_late_play_clamps_to_game_end():
    # Played in round 14 → no remaining round space → nothing scheduled.
    s = setup(0)
    s = fast_replace(s, round_number=14)
    s2 = MINORS["horse_drawn_boat"].on_play(s, 0)
    assert all(slot == Resources() for slot in s2.players[0].future_resources)
    assert all(not w for w in s2.players[0].future_rewards)


def test_horse_drawn_boat_additive_food_schedule():
    # Schedule does not clobber an existing future_resources slot (e.g. from the Well).
    s = setup(0)
    p = fast_replace(s.players[0],
                     future_resources=tuple(
                         Resources(food=5) if i == 1 else r       # round 2 slot
                         for i, r in enumerate(s.players[0].future_resources)))
    s = fast_replace(s, players=(p, s.players[1]))
    s2 = MINORS["horse_drawn_boat"].on_play(s, 0)
    # Round 2 is a food round (R=1): 5 pre-existing + 1 from the boat = 6.
    assert s2.players[0].future_resources[1] == Resources(food=6)


def test_horse_drawn_boat_food_collected_at_round_start():
    # Drive the real round-boundary path: entering round 2 (a food round) yields +1 food.
    s = setup(0)
    s = MINORS["horse_drawn_boat"].on_play(s, 0)
    food0 = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)  # entering round 2
    out = _complete_preparation(s)
    assert out.players[0].resources.food == food0 + 1


def test_horse_drawn_boat_sheep_collected_and_accommodated_at_round_start():
    # Round 3 is a sheep round (R=1). Collect its future_reward slot: 1 sheep fits the
    # house-pet on a default farm, so it is kept and the slot is cleared.
    s = setup(0)
    s = MINORS["horse_drawn_boat"].on_play(s, 0)
    sheep0 = s.players[0].animals.sheep
    out = _collect_future_rewards(s, 2)   # slot index 2 → round 3
    assert out.players[0].animals.sheep == sheep0 + 1
    assert out.players[0].future_rewards[2].animals == Animals()
