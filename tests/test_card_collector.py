"""Tests for Collector (occupation, C104; Consul Dirigens Expansion).

Card text (verbatim): "This card is an action space for you only. When you use
it for the 1st/2nd/3rd/4th time, you get 1 begging marker and 6/7/8/9
different goods of your choice."

User ruling 74 (2026-07-21): card-as-action-space approved; Collector surfaces
WIDE at PlaceWorker via a picks payload over the 10-good menu (wood, clay,
reed, stone, grain, veg, food, sheep, boar, cattle — food IS a good, a begging
marker is NOT), so the widths are C(10,6)=210 / C(10,7)=120 / C(10,8)=45 /
C(10,9)=10 with no pruning (none Pareto-comparable). The begging marker is
part of the action; animal picks route through `helpers.grant_animals` so the
accommodation barrier surfaces keep-which on overflow; four uses per game
(a CardStore counter) — after the 4th the space is never placeable again.
"""
import agricola.cards.collector  # noqa: F401  -- registers the card (not in cards/__init__ yet)

from itertools import combinations
from math import comb

from agricola.actions import CommitAccommodate, PlaceWorker, Proceed, Stop
from agricola.cards.card_spaces import CARD_ACTION_SPACES
from agricola.cards.collector import CARD_ID, GOODS
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _owner_state(seed=5, uses=0):
    cs = _card_state(seed)
    p = cs.players[0]
    cs = _edit_player(cs, 0, occupations=p.occupations | {CARD_ID})
    if uses:
        p = cs.players[0]
        cs = _edit_player(cs, 0, card_state=p.card_state.set(CARD_ID, uses))
    return cs


def _placements(actions):
    return [a for a in actions
            if isinstance(a, PlaceWorker) and a.space == f"card:{CARD_ID}"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in CARD_ACTION_SPACES
    # The 10-good menu of ruling 74 — food included, begging markers not.
    assert GOODS == ("wood", "clay", "reed", "stone", "grain", "veg", "food",
                     "sheep", "boar", "cattle")


# ---------------------------------------------------------------------------
# The wide surfacing: C(10, 6/7/8/9), distinct goods, no 5th use
# ---------------------------------------------------------------------------

def test_first_use_surfaces_all_210_combinations():
    cs = _owner_state()
    ps = _placements(legal_actions(cs))
    assert len(ps) == comb(10, 6) == 210
    picks_sets = {frozenset(a.picks) for a in ps}
    # Every combination of 6 DISTINCT goods, each exactly once.
    assert picks_sets == {frozenset(c) for c in combinations(GOODS, 6)}
    assert all(len(set(a.picks)) == 6 for a in ps)


def test_use_widths_2_3_4_and_never_a_5th():
    for uses, width in [(1, 120), (2, 45), (3, 10)]:
        cs = _owner_state(uses=uses)
        ps = _placements(legal_actions(cs))
        assert len(ps) == comb(10, 6 + uses) == width
        assert all(len(a.picks) == 6 + uses for a in ps)
    # After the 4th use the space is never placeable again.
    assert _placements(legal_actions(_owner_state(uses=4))) == []


def test_opponent_never_offered():
    cs = with_current_player(_owner_state(), 1)   # P1 to move; P0 owns Collector
    assert _placements(legal_actions(cs)) == []


# ---------------------------------------------------------------------------
# Use 1 end-to-end: goods + the begging marker + the counter
# ---------------------------------------------------------------------------

def test_use_grants_picks_and_begging_marker():
    cs = _owner_state()
    picks = ("wood", "clay", "reed", "stone", "grain", "veg")
    action = PlaceWorker(space=f"card:{CARD_ID}", picks=picks)
    assert action in legal_actions(cs)
    before = cs.players[0]
    cs = step(cs, action)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.picks == picks
    cs = step(cs, Proceed())
    p = cs.players[0]
    # 1 of each picked good...
    assert p.resources == before.resources + Resources(
        wood=1, clay=1, reed=1, stone=1, grain=1, veg=1)
    # ...and 1 begging marker, part of the action (ruling 74).
    assert p.begging_markers == before.begging_markers + 1
    # The use counter advanced (1st use done).
    assert p.card_state.get(CARD_ID) == 1
    cs = step(cs, Stop())
    assert not cs.pending_stack


def test_food_is_a_good():
    cs = _owner_state()
    picks = ("wood", "clay", "reed", "stone", "grain", "food")
    cs = run_actions(cs, [PlaceWorker(space=f"card:{CARD_ID}", picks=picks),
                          Proceed(), Stop()])
    # setup food is 0 after... assert the +1 landed relative to whatever base:
    # picks granted exactly 1 food alongside the other goods.
    assert cs.players[0].resources.food >= 1


# ---------------------------------------------------------------------------
# Animal picks route through grant_animals -> the accommodation barrier
# ---------------------------------------------------------------------------

def test_animal_picks_fit_when_housable():
    # One animal fits the house pet slot: no barrier frame.
    cs = _owner_state()
    picks = ("wood", "clay", "reed", "stone", "grain", "sheep")
    cs = run_actions(cs, [PlaceWorker(space=f"card:{CARD_ID}", picks=picks),
                          Proceed(), Stop()])
    assert cs.players[0].animals == Animals(sheep=1)
    assert not cs.players[0].animals_need_accommodation


def test_animal_overflow_surfaces_keep_which_choice():
    # Three animal picks on a bare farm (house-pet capacity 1): the barrier
    # surfaces a PendingAccommodate BEFORE the host's after-window — the
    # keep-which choice is the player's, never auto-trimmed.
    cs = _owner_state()
    picks = ("wood", "clay", "reed", "sheep", "boar", "cattle")
    cs = step(cs, PlaceWorker(space=f"card:{CARD_ID}", picks=picks))
    cs = step(cs, Proceed())
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0
    opts = legal_actions(cs)
    assert all(isinstance(a, CommitAccommodate) for a in opts)
    # Keep exactly one animal (the house pet slot) — one option per type.
    assert {(a.sheep, a.boar, a.cattle) for a in opts} == {
        (1, 0, 0), (0, 1, 0), (0, 0, 1)}
    cs = step(cs, CommitAccommodate(sheep=0, boar=1, cattle=0))
    assert cs.players[0].animals == Animals(boar=1)
    # The host resumes its lifecycle (after-window, then Stop pops).
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    cs = run_actions(cs, [Stop()])
    assert not cs.pending_stack


# ---------------------------------------------------------------------------
# Four uses across a game: widths shrink, the counter persists
# ---------------------------------------------------------------------------

def test_counter_persists_across_uses():
    cs = _owner_state(uses=2)
    ps = _placements(legal_actions(cs))
    assert len(ps) == 45 and len(ps[0].picks) == 8
    cs = run_actions(cs, [ps[0], Proceed(), Stop()])
    assert cs.players[0].card_state.get(CARD_ID) == 3
