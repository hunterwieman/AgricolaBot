import agricola.cards.writing_boards  # noqa: F401

"""Tests for Writing Boards (minor improvement, C #4; Corbarius Expansion).

Card text: "You immediately get 1 wood for each occupation you have in front of
you." Cost 1 food, PASSING (traveling minor -- circulates to the opponent's hand
after the on-play effect). The grant equals the player's current
occupation count at play time — 0 wood with no occupations, no self-counting
(playing a minor never touches `occupations`).

Mirrors tests/test_cards_minors.py: the minor is played by pushing
PendingPlayMinor onto the stack directly (the established factory pattern for
testing pendings before/independent of the in-game entry points).
"""
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import _can_afford_cost, legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "writing_boards"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, hand=frozenset({CARD_ID}), food=1, occ=frozenset()):
    """A WORK state where the current player holds the card, with `occ`
    occupations played and `food` food. Opponent's hand emptied for isolation."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_minors=hand,
        occupations=occ,
        resources=fast_replace(cs.players[cp].resources, food=food),
    )
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_writing_boards_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.passing_left is True           # traveling minor (passing_left='X')
    assert spec.vps == 0
    assert spec.prereq is None                 # no prerequisite
    assert spec.min_occupations == 0 and spec.max_occupations is None


# ---------------------------------------------------------------------------
# Real-flow effect: 1 wood per occupation, varying counts
# ---------------------------------------------------------------------------

def test_play_grants_one_wood_per_occupation():
    cs, cp = _card_state(occ=frozenset({"a", "b", "c"}))   # 3 occupations
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    assert p.resources.wood == wood0 + 3       # +1 wood per occupation
    assert p.resources.food == 0               # paid 1 food
    assert CARD_ID not in p.minor_improvements  # passing -> not kept
    assert CARD_ID not in p.hand_minors         # left hand


def test_play_with_no_occupations_grants_zero_wood():
    cs, cp = _card_state(occ=frozenset())       # no occupations played
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    assert p.resources.wood == wood0           # 0 wood granted
    assert p.resources.food == 0               # still paid 1 food


def test_play_one_occupation_grants_one_wood():
    cs, cp = _card_state(occ=frozenset({"only"}))
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    assert cs.players[cp].resources.wood == wood0 + 1


def test_passes_to_opponent():
    cs, cp = _card_state(occ=frozenset({"a"}))
    opp = 1 - cp
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    # Passing: never enters the tableau; circulates to the opponent's hand.
    assert CARD_ID not in cs.players[cp].minor_improvements
    assert CARD_ID in cs.players[opp].hand_minors


# ---------------------------------------------------------------------------
# Cost / affordability boundary
# ---------------------------------------------------------------------------

def test_no_prereq_always_met():
    # No prerequisite — playable regardless of occupation count (incl. zero).
    cs, cp = _card_state(occ=frozenset())
    assert prereq_met(MINORS[CARD_ID], cs, cp)
    cs2, cp2 = _card_state(occ=frozenset({"a", "b"}))
    assert prereq_met(MINORS[CARD_ID], cs2, cp2)


def test_playable_requires_one_food():
    # With 1 food -> affordable & playable.
    cs, cp = _card_state(food=1)
    assert _can_afford_cost(cs.players[cp], MINORS[CARD_ID].cost)
    assert playable_minors(cs, cp) == [CARD_ID]
    # With 0 food -> cost unaffordable -> not playable.
    cs0, cp0 = _card_state(food=0)
    assert not _can_afford_cost(cs0.players[cp0], MINORS[CARD_ID].cost)
    assert playable_minors(cs0, cp0) == []


# ---------------------------------------------------------------------------
# Enumeration scoping: PendingPlayMinor offers exactly the one play
# ---------------------------------------------------------------------------

def test_enumerator_offers_the_play():
    cs, cp = _card_state(occ=frozenset({"a"}))
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, CARD_ID)]
