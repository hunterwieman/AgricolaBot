import agricola.cards.firewood  # noqa: F401  (register the card; not in cards/__init__)

"""Tests for Firewood (minor improvement, C75; Corbarius Expansion).

Card text: "In the returning home phase of each round, place 1 wood on this
card. Each time before you build a Fireplace, Cooking Hearth, or oven, move up
to 4 wood from this card to your supply."  Cost: 2 Food.

User rulings 2026-07-21: the deposit is an unconditional returning_home AUTO
(wood from the general supply); the withdrawal is an optional trigger on both
before_build_major and before_play_minor, take-max (move exactly min(4, stock)),
and firing restricts the pending build to the qualifying targets — the majors
{Fireplace 0/1, Cooking Hearth 2/3, Clay Oven 5, Stone Oven 6} and the hand
minors whose slug ends _oven/_fireplace.

Deposit tests drive the REAL round-end walk (the Swimming Class harness);
withdrawal tests drive the REAL Major/Minor Improvement space flow (the Wood
Workshop harness).
"""
import agricola.cards.iron_oven  # noqa: F401
import agricola.cards.simple_oven  # noqa: F401
import agricola.cards.market_stall  # noqa: F401

from agricola.actions import (
    ChooseSubAction, CommitBuildMajor, CommitPlayMinor, FireTrigger,
    PlaceWorker,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import sole_build_major, sole_play_minor

CARD_ID = "firewood"

JOINERY = 7          # a non-qualifying major (2 wood + 2 stone)
FIREPLACE_CHEAP = 0  # a qualifying major (2 clay)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("iron_oven", "simple_oven", "market_stall")
           + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _stock(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _card_state(seed=5, *, hand=frozenset(), played=frozenset({CARD_ID}),
                res=None, stock=0):
    """Card-mode state with major_improvement forced revealed + the current
    player's played minors / hand / resources / Firewood stock set; opponent's
    hand cleared. Returns (state, current_player)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(p,
                     hand_minors=hand,
                     minor_improvements=played,
                     resources=res if res is not None else Resources())
    if stock:
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, stock))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _at_build_major(**kwargs):
    """Drive the composite to a before-phase PendingBuildMajor frame."""
    cs, cp = _card_state(**kwargs)
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    return cs, cp


def _at_play_minor(**kwargs):
    """Drive the composite to a before-phase PendingPlayMinor frame."""
    cs, cp = _card_state(**kwargs)
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    return cs, cp


def _drained_work_state(*, round_number=1, seed=0, owner=True):
    """A Family WORK state with every person placed, player 0 owning Firewood
    (unless owner=False) — the Swimming Class round-end harness."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    if owner:
        p = state.players[0]
        state = _edit_player(
            state, 0, minor_improvements=p.minor_improvements | {CARD_ID})
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _fire(state):
    ft = FireTrigger(card_id=CARD_ID)
    assert ft in legal_actions(state), "Firewood's FireTrigger not offered"
    return step(state, ft)


def _major_commit_idxs(state):
    return {a.major_idx for a in legal_actions(state)
            if isinstance(a, CommitBuildMajor)}


def _minor_commit_ids(state):
    return {a.card_id for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor)}


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(food=2)   # cost: 2 Food
    assert spec.vps == 0                              # no printed VP
    assert spec.min_occupations == 0                  # no prerequisite
    assert spec.prereq is None
    # The deposit: an AUTO on the returning_home window.
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("returning_home", ()))
    # The withdrawal: an OPTIONAL trigger on BOTH before-events.
    for event in ("before_build_major", "before_play_minor"):
        entries = [e for e in TRIGGERS.get(event, ()) if e.card_id == CARD_ID]
        assert entries, f"{CARD_ID} not registered on {event}"
        assert not entries[0].mandatory
    assert CARD_ID in CARDS   # FireTrigger dispatch entry exists


# --- The deposit, through the real round-end walk ----------------------------

def test_deposit_each_round_accumulates():
    """The returning_home window places 1 general-supply wood on the card each
    round — the stock increments per round and the supply is not debited."""
    state = _drained_work_state()
    wood_before = state.players[0].resources.wood
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # round 1: no harvest
    assert _stock(state, 0) == 1
    assert state.players[0].resources.wood == wood_before   # general supply
    # Re-arm round 2 on the SAME state (keeping card_state): drained WORK.
    state = fast_replace(state, pending_stack=(), phase=Phase.WORK,
                         round_number=2)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    state = _advance_until_decision(state)
    assert _stock(state, 0) == 2


def test_deposit_fires_on_harvest_round_too():
    """Unconditioned on the round kind: the returning-home phase precedes the
    harvest (ruling 49), so round 4 deposits before the harvest begins."""
    state = _drained_work_state(round_number=4)
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)
    assert _stock(state, 0) == 1


def test_no_deposit_when_unowned():
    state = _drained_work_state(owner=False)
    state = _advance_until_decision(state)
    assert _stock(state, 0) == 0


# --- Withdrawal on a major build ---------------------------------------------

def test_fire_on_build_major_moves_wood_and_restricts_menu():
    """Stock 3, clay+wood+stone in supply: pre-fire both Fireplace (qualifying)
    and Joinery (non-qualifying) are committable; firing adds min(4,3)=3 wood,
    empties the card, and prunes the menu to fireplace/hearth/oven majors."""
    cs, cp = _at_build_major(stock=3, res=Resources(clay=2, wood=2, stone=2))
    pre = _major_commit_idxs(cs)
    assert FIREPLACE_CHEAP in pre
    assert JOINERY in pre                      # affordable before the fire

    cs = _fire(cs)
    assert cs.players[cp].resources.wood == 2 + 3   # take-max: all 3 moved
    assert _stock(cs, cp) == 0
    post = _major_commit_idxs(cs)
    assert post                                # a qualifying commit remains
    assert post <= {0, 1, 2, 3, 5, 6}          # Joinery (7) etc. vanished
    assert JOINERY not in post
    # The fire is once-per-frame: no second FireTrigger.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)

    cs = step(cs, sole_build_major(cs, FIREPLACE_CHEAP))
    assert cs.board.major_improvement_owners[FIREPLACE_CHEAP] == cp


def test_take_max_caps_at_four():
    """Stock 6 -> firing moves exactly 4 wood; 2 stay on the card."""
    cs, cp = _at_build_major(stock=6, res=Resources(clay=2))
    cs = _fire(cs)
    assert cs.players[cp].resources.wood == 4
    assert _stock(cs, cp) == 2


def test_take_max_moves_whole_smaller_stock():
    """Stock 2 -> firing moves exactly 2 wood; the card empties."""
    cs, cp = _at_build_major(stock=2, res=Resources(clay=2))
    cs = _fire(cs)
    assert cs.players[cp].resources.wood == 2
    assert _stock(cs, cp) == 0


def test_declining_keeps_nonqualifying_build_legal():
    """The restriction applies only AFTER firing: without firing, the player
    commits Joinery directly and the stock is untouched."""
    cs, cp = _at_build_major(stock=3, res=Resources(clay=2, wood=2, stone=2))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(cs)   # offered ...
    cs = step(cs, sole_build_major(cs, JOINERY))               # ... declined
    assert cs.board.major_improvement_owners[JOINERY] == cp
    assert _stock(cs, cp) == 3


# --- Withdrawal on a minor play ----------------------------------------------

def test_fire_on_play_minor_moves_wood_and_restricts_menu():
    """iron_oven (qualifying, 3 stone) + market_stall (non-qualifying, 1 grain)
    both playable pre-fire; firing adds the wood and restricts the commits to
    the oven minor only."""
    cs, cp = _at_play_minor(stock=1,
                            hand=frozenset({"iron_oven", "market_stall"}),
                            res=Resources(stone=3, grain=1))
    pre = _minor_commit_ids(cs)
    assert {"iron_oven", "market_stall"} <= pre

    cs = _fire(cs)
    assert cs.players[cp].resources.wood == 1     # min(4, 1) = 1
    assert _stock(cs, cp) == 0
    assert _minor_commit_ids(cs) == {"iron_oven"}   # market_stall vanished

    cs = step(cs, sole_play_minor(cs, "iron_oven"))
    assert "iron_oven" in cs.players[cp].minor_improvements


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_with_zero_stock():
    cs, _cp = _at_build_major(stock=0, res=Resources(clay=2))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


def test_not_offered_when_all_qualifying_majors_owned():
    """All six fireplace/hearth/oven majors owned by the opponent -> the
    restriction would strand the frame, so the trigger is not offered (Joinery
    keeps the build_major branch itself reachable)."""
    cs, cp = _card_state(stock=3, res=Resources(wood=2, stone=2))
    owners = list(cs.board.major_improvement_owners)
    for i in (0, 1, 2, 3, 5, 6):
        owners[i] = 1 - cp
    cs = fast_replace(cs, board=fast_replace(
        cs.board, major_improvement_owners=tuple(owners)))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    assert JOINERY in _major_commit_idxs(cs)      # the frame is live ...
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)   # ... no fire


def test_not_offered_without_qualifying_hand_minor():
    """Only a non-oven minor in hand -> no fire at the play-minor frame."""
    cs, _cp = _at_play_minor(stock=1,
                             hand=frozenset({"market_stall"}),
                             res=Resources(grain=1))
    assert "market_stall" in _minor_commit_ids(cs)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)


def test_not_offered_when_oven_minor_unaffordable_even_with_wood():
    """iron_oven (3 stone) in hand but no stone: even the doctored +wood state
    can't pay it (wood is not stone), so the trigger is withheld — never
    strand the no-decline frame."""
    cs, _cp = _at_play_minor(stock=4,
                             hand=frozenset({"iron_oven", "market_stall"}),
                             res=Resources(grain=1))
    assert _minor_commit_ids(cs) == {"market_stall"}
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)
