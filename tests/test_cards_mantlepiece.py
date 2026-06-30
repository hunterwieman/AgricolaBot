"""Tests for Mantlepiece (minor improvement, B33).

Card text: "When you play this card, you immediately get 1 bonus point for each
complete round left to play. You may no longer renovate your house."
Cost 1 stone; prerequisite: clay or stone house; printed VPs: −3.

Coverage:
  - registration (MINORS has the card; cost / prereq / vps fields)
  - on-play: correct number of bonus points banked in CardStore
  - scoring: banked points contribute to end-game score; printed −3 VPs applied
  - renovation permanently blocked after the card is owned
  - renovation NOT blocked without the card (family byte-identity preserved)
  - prereq: clay and stone houses pass; wood house fails
"""
from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.mantlepiece import CARD_ID, _complete_rounds_left
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_house, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("mantlepiece",) + tuple(f"m{i}" for i in range(20)),
)


def _own_minor(state, idx, card_id):
    p = fast_replace(
        state.players[idx],
        minor_improvements=state.players[idx].minor_improvements | {card_id},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _play_mantlepiece(cs):
    """Drive playing Mantlepiece via major_improvement space (the standard minor-play entry
    point). Caller must ensure the space is revealed and the player has the card in hand."""
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources.stone == 1
    assert spec.vps == -3


# ---------------------------------------------------------------------------
# Prerequisite
# ---------------------------------------------------------------------------

def test_prereq_clay_house():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_stone_house():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.STONE)
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_wood_house_fails():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.WOOD)
    assert not prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# On-play: bonus points banked
# ---------------------------------------------------------------------------

def test_on_play_banks_rounds_remaining():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    expected_rounds = _complete_rounds_left(cs)
    cs = with_house(cs, cp, HouseMaterial.CLAY)
    cs = with_resources(cs, cp, stone=1, food=1)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = _play_mantlepiece(cs)
    assert cs.players[cp].card_state.get(CARD_ID, 0) == expected_rounds


def test_on_play_round14_banks_zero():
    s = setup(0)
    # Manufacture a round-14 state so there are 0 complete rounds left.
    s = fast_replace(s, round_number=14)
    s = _own_minor(s, 0, CARD_ID)
    # CardStore wasn't populated via on_play here; verify _complete_rounds_left is 0
    assert _complete_rounds_left(s) == 0


# ---------------------------------------------------------------------------
# Scoring: banked points + printed VPs
# ---------------------------------------------------------------------------

def test_scoring_banked_plus_printed():
    s = setup(0)
    s = _own_minor(s, 0, CARD_ID)
    # Bank 6 points manually (simulates playing in round 8: 14-8=6).
    p = fast_replace(s.players[0], card_state=s.players[0].card_state.set(CARD_ID, 6))
    s = fast_replace(s, players=(p, s.players[1]))
    _total, bd = score(s, 0)
    # 6 banked + (−3 printed vps) = net +3 from card_points
    assert bd.card_points == 3


def test_scoring_zero_banked_printed_negative():
    s = setup(0)
    s = _own_minor(s, 0, CARD_ID)
    # No banked points (played in round 14).
    _total, bd = score(s, 0)
    assert bd.card_points == -3


# ---------------------------------------------------------------------------
# Renovation blocked
# ---------------------------------------------------------------------------

def _renovation_legal(state, player_idx):
    """Return True if a renovate sub-action would be legal for this player right now."""
    from agricola.legality import _can_renovate
    return _can_renovate(state, state.players[player_idx])


def test_renovation_blocked_after_owning_mantlepiece():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    # Renovating clay→stone costs 1 reed + N stone for N rooms (2 rooms = 1 reed + 2 stone).
    s = with_resources(s, 0, stone=5, reed=5)
    assert _renovation_legal(s, 0)    # sanity: would normally be legal

    s_owned = _own_minor(s, 0, CARD_ID)
    assert not _renovation_legal(s_owned, 0)


def test_renovation_not_blocked_without_card():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    s = with_resources(s, 0, stone=5, reed=5)
    assert _renovation_legal(s, 0)


def test_opponent_renovation_unaffected():
    s = setup(0)
    # p0 owns Mantlepiece; p1's renovation should be unaffected.
    s = with_house(s, 0, HouseMaterial.CLAY)
    s = with_house(s, 1, HouseMaterial.CLAY)
    s = with_resources(s, 1, stone=5, reed=5)
    s = _own_minor(s, 0, CARD_ID)
    assert _renovation_legal(s, 1)
