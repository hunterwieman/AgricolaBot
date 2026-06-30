"""Tests for Catcher (occupation A107, Artifex).

Card text: "Each time you place your 1st/2nd/3rd person in a round on a building
resource accumulation space with exactly 5/4/3 building resources, you get 1 food."

The +1 food is a `before_action_space` automatic effect, hosted on each of the five
building resource accumulation spaces (forest, clay_pit, reed_bank, the two quarries —
all atomic, so the card must host them). The required goods count is PAIRED to which
person you place this round: 1st->exactly 5, 2nd->exactly 4, 3rd->exactly 3; the 4th/5th
person never fire. The count is read BEFORE the space's own pickup (before-phase), and
the "Nth person placed" index is `people_total − people_home` (people_home is already
decremented for the placing worker when the before_action_space trigger fires).
"""
import agricola.cards.catcher  # noqa: F401  (registers the card; not in cards/__init__.py)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "catcher"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own(state, idx):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _with_people(state, idx, *, total, home, newborns=0):
    p = fast_replace(state.players[idx], people_total=total, people_home=home,
                     newborns=newborns)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_accumulated(state, space_id, count, *, kind="wood"):
    """Put `count` building resources of one kind on a building accumulation space."""
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(state.board, space_id,
                        fast_replace(sp, accumulated=Resources(**{kind: count}))))


def _place_and_finish(state, space_id):
    """Drive the full hosted lifecycle for a building space: place -> Proceed -> Stop."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    # +1 food (if eligible) is a choiceless auto applied at hosting -> before-phase is a
    # singleton Proceed (no FireTrigger surfaced).
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS


def test_registered_as_before_hook_on_all_building_spaces():
    for sid in ("forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert CARD_ID in OWN_ACTION_HOOK_CARDS[sid]
    events = {event for event, entries in AUTO_EFFECTS.items()
              if any(e.card_id == CARD_ID for e in entries)}
    assert events == {"before_action_space"}


def test_on_play_is_noop():
    s = _own(_card_state(), 0)
    before = s.players[0].resources
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources == before


# ---------------------------------------------------------------------------
# The paired threshold — fires for the right person at the right count
# ---------------------------------------------------------------------------

def test_first_person_fires_at_exactly_5():
    # 1st person of the round -> needs exactly 5 building resources.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=2)        # nobody placed yet
    s = _set_accumulated(s, "forest", 5)
    before_food = s.players[0].resources.food
    before_wood = s.players[0].resources.wood

    out = _place_and_finish(s, "forest")
    assert out.players[0].resources.food == before_food + 1     # Catcher +1
    assert out.players[0].resources.wood == before_wood + 5     # normal forest take


def test_first_person_no_fire_at_4_or_6():
    # 1st person needs EXACTLY 5; 4 and 6 must not fire (==, not >=).
    for count in (4, 6):
        s = _own(_card_state(), 0)
        s = _with_people(s, 0, total=2, home=2)
        s = _set_accumulated(s, "forest", count)
        before_food = s.players[0].resources.food
        out = _place_and_finish(s, "forest")
        assert out.players[0].resources.food == before_food, count


def test_second_person_fires_at_exactly_4():
    # 2nd person of the round (one worker already placed) -> needs exactly 4.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=1)        # 1 already placed this round
    s = _set_accumulated(s, "clay_pit", 4, kind="clay")
    before_food = s.players[0].resources.food

    out = _place_and_finish(s, "clay_pit")
    assert out.players[0].resources.food == before_food + 1


def test_second_person_no_fire_at_5():
    # With the 2nd person, a count of 5 (the 1st-person threshold) must NOT fire.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=1)
    s = _set_accumulated(s, "clay_pit", 5, kind="clay")
    before_food = s.players[0].resources.food
    out = _place_and_finish(s, "clay_pit")
    assert out.players[0].resources.food == before_food


def test_third_person_fires_at_exactly_3():
    # 3rd person of the round (two already placed) -> needs exactly 3.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=3, home=1)        # 2 already placed this round
    s = _set_accumulated(s, "reed_bank", 3, kind="reed")
    before_food = s.players[0].resources.food

    out = _place_and_finish(s, "reed_bank")
    assert out.players[0].resources.food == before_food + 1


def test_third_person_no_fire_at_4_or_5():
    for count in (4, 5):
        s = _own(_card_state(), 0)
        s = _with_people(s, 0, total=3, home=1)
        s = _set_accumulated(s, "reed_bank", count, kind="reed")
        before_food = s.players[0].resources.food
        out = _place_and_finish(s, "reed_bank")
        assert out.players[0].resources.food == before_food, count


def test_fourth_person_never_fires():
    # 4th person of the round -> no threshold; never fires regardless of count.
    # Use forest (a permanent, round-1-revealed building space) so this is a real flow.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=4, home=1)        # 3 already placed this round
    for count in (3, 4, 5):
        s2 = _set_accumulated(s, "forest", count)
        before_food = s2.players[0].resources.food
        out = _place_and_finish(s2, "forest")
        assert out.players[0].resources.food == before_food, count


# ---------------------------------------------------------------------------
# Same-round newborn must NOT inflate the person index (regression: a Wish-for-Children
# birth bumps people_total but not people_home, so the index subtracts newborns).
# ---------------------------------------------------------------------------

def test_same_round_newborn_does_not_inflate_person_index():
    # 1 real worker placed this round + a same-round newborn (people_total bumped to 3,
    # newborns=1, people_home NOT bumped for the newborn). Placing the 2nd real WORKER on
    # forest (home 1 -> 0) is the 2nd-person index -> needs EXACTLY 4. Without the `- newborns`
    # term the index would read 3 (needs 3) and this would wrongly miss.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=3, home=1, newborns=1)
    s = _set_accumulated(s, "forest", 4)
    before = s.players[0].resources.food
    out = _place_and_finish(s, "forest")
    assert out.players[0].resources.food == before + 1     # 2nd worker, count 4 -> fires


def test_same_round_newborn_does_not_fire_at_pre_fix_threshold():
    # The pre-fix code computed index 3 (needs exactly 3) for the state above; confirm a
    # count of 3 does NOT fire now (the 2nd worker needs 4, not 3).
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=3, home=1, newborns=1)
    s = _set_accumulated(s, "forest", 3)
    before = s.players[0].resources.food
    out = _place_and_finish(s, "forest")
    assert out.players[0].resources.food == before


# ---------------------------------------------------------------------------
# Space gating + ownership
# ---------------------------------------------------------------------------

def test_does_not_fire_on_non_building_space():
    # day_laborer is not a building accumulation space; it is also not hooked, so the
    # placement takes the atomic fast path (no host frame, no +1 food).
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=2)
    before_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="day_laborer"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before_food + 2   # only the 2 food the space gives


def test_unowned_does_not_host_or_fire():
    s = _card_state()
    # Not owned -> the building spaces are not hosted.
    for sid in ("forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert not should_host_space(s, sid, 0)
    s = _with_people(s, 0, total=2, home=2)
    s = _set_accumulated(s, "forest", 5)
    before_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="forest"))   # atomic fast path, no host
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before_food


def test_owned_hosts_all_building_spaces():
    s = _own(_card_state(), 0)
    for sid in ("forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert should_host_space(s, sid, 0)
    assert not should_host_space(s, "day_laborer", 0)   # not a building space
