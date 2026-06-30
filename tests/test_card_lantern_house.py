"""Lantern House (minor improvement, C35; Consul Dirigens).

Card text: "During scoring, you get 1 negative point for each card left in your
hand. You cannot discard cards from your hand unplayed. If you already have, you
cannot play this card."

Cost 1 Wood, prereq "No Occupations" (max_occupations=0), printed 7 VP.

Coverage:
  - registration: spec present, cost 1 wood, vps 7, max_occupations 0.
  - scoring term: NEGATIVE one point per card left in the owner's own hand;
    gated by ownership; the printed 7 VP comes through the kept-minor vps loop
    (so card_points == 7 - hand_size for the owner).
  - eligibility boundary: prereq_met true with 0 occupations, false with >=1.
  - scoping: counts the DECIDER's own hand only, not the opponent's.
  - real flow: play through the major_improvement -> play_minor entry point,
    paying 1 wood, then verify scoring.
"""
import agricola.cards.lantern_house  # noqa: F401

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_play_minor

CARD_ID = "lantern_house"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("lantern_house",) + tuple(f"m{i}" for i in range(20)),
)


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_hand(state, idx, *, occupations=(), minors=()):
    p = fast_replace(state.players[idx],
                     hand_occupations=frozenset(occupations),
                     hand_minors=frozenset(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_occupations(state, idx, occs):
    p = fast_replace(state.players[idx], occupations=frozenset(occs))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 7
    assert spec.max_occupations == 0


# ---------------------------------------------------------------------------
# Scoring term — negative per card in hand, plus the printed 7 VP
# ---------------------------------------------------------------------------

def test_score_empty_hand_only_printed_vps():
    s = setup(0)
    s = _set_hand(s, 0, occupations=(), minors=())
    s = _own_minor(s, 0, CARD_ID)
    _t, bd = score(s, 0)
    # No cards in hand: just the printed 7 VP, no penalty.
    assert bd.card_points == 7


def test_score_penalty_one_per_hand_card():
    s = setup(0)
    s = _set_hand(s, 0, occupations=("oA", "oB"), minors=("mA",))   # 3 cards
    s = _own_minor(s, 0, CARD_ID)
    _t, bd = score(s, 0)
    # 7 printed VP minus 1 per card (3) = 4.
    assert bd.card_points == 7 - 3


def test_score_not_owned_no_term_no_vps():
    s = setup(0)
    s = _set_hand(s, 0, occupations=("oA", "oB"), minors=("mA",))
    # Not owned: neither the negative term nor the printed VP apply.
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_scoping_counts_own_hand_only():
    s = setup(0)
    # Owner (P0) holds 1 card; opponent (P1) holds a big hand.
    s = _set_hand(s, 0, minors=("mOwn",))
    s = _set_hand(s, 1, occupations=("x", "y", "z"), minors=("p", "q"))
    s = _own_minor(s, 0, CARD_ID)
    _t, bd = score(s, 0)
    # Only P0's own single hand card counts: 7 - 1 = 6.
    assert bd.card_points == 6


# ---------------------------------------------------------------------------
# Eligibility boundary — prereq "No Occupations"
# ---------------------------------------------------------------------------

def test_prereq_no_occupations():
    s = setup(0)
    assert prereq_met(MINORS[CARD_ID], s, 0)                       # 0 occupations -> ok
    s1 = _set_occupations(s, 0, ("anyocc",))
    assert not prereq_met(MINORS[CARD_ID], s1, 0)                  # 1 occupation -> blocked


# ---------------------------------------------------------------------------
# Real flow — play via the major_improvement -> play_minor entry point
# ---------------------------------------------------------------------------

def test_real_flow_play_costs_one_wood_and_scores():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=1)
    # Put Lantern House in hand alongside another minor (so a hand card remains
    # after playing — to exercise the penalty after a real play). Clear the
    # dealt occupations so the only leftover card is the spare minor.
    p = fast_replace(cs.players[cp],
                     hand_occupations=frozenset(),
                     hand_minors=frozenset({CARD_ID, "leftover_minor"}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    # Cost paid: 1 wood -> 0.
    assert cs.players[cp].resources.wood == 0
    # Kept in tableau (not a passing minor).
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors
    # One card still in hand ("leftover_minor").
    assert cs.players[cp].hand_minors == frozenset({"leftover_minor"})

    _t, bd = score(cs, cp)
    # 7 printed VP minus 1 for the leftover hand card = 6.
    assert bd.card_points == 6
