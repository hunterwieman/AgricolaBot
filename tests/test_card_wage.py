"""Tests for Wage (minor improvement, deck B #7; Bubulcus; traveling).

Card text: "You immediately get 2 food and 1 additional food for each major
improvement you have from the bottom row of the supply board." No cost, no
prerequisite, traveling (passed to the opponent after the on-play effect).

Bottom row = Clay Oven (5), Stone Oven (6), Joinery (7), Pottery (8),
Basketmaker's Workshop (9); top row = the two Fireplaces (0, 1), two Cooking
Hearths (2, 3), and the Well (4).
"""
import agricola.cards.wage  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "wage"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5, *, cp_minors=frozenset(), cp_res=None):
    """A 2-player card state with the current player's hand/resources set."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {"hand_minors": cp_minors}
    if cp_res is not None:
        changes["resources"] = cp_res
    p = fast_replace(p, **changes)
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

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.passing_left is True
    assert spec.cost == Cost()          # no cost
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# On-play effect: 2 food + 1 per owned bottom-row major
# ---------------------------------------------------------------------------

def test_on_play_base_two_food_no_majors():
    cs, cp = _state(cp_res=Resources(food=0))
    after = MINORS[CARD_ID].on_play(cs, cp)
    assert after.players[cp].resources.food == 2


def test_on_play_counts_owned_bottom_row_majors():
    cs, cp = _state(cp_res=Resources(food=0))
    cs = with_majors(cs, owner_by_idx={7: cp, 8: cp})  # Joinery + Pottery (bottom row)
    after = MINORS[CARD_ID].on_play(cs, cp)
    assert after.players[cp].resources.food == 4       # 2 + 2 bottom-row majors


def test_on_play_ignores_top_row_and_opponent_majors():
    cs, cp = _state(cp_res=Resources(food=0))
    opp = 1 - cp
    cs = with_majors(cs, owner_by_idx={
        0: cp,    # Fireplace — TOP row, not counted
        4: cp,    # Well — TOP row, not counted
        5: opp,   # Clay Oven owned by the OPPONENT — not counted
        9: cp,    # Basketmaker's Workshop — bottom row, counted
    })
    after = MINORS[CARD_ID].on_play(cs, cp)
    assert after.players[cp].resources.food == 3       # 2 + only Basketmaker's


# ---------------------------------------------------------------------------
# playable_minors: no cost -> always playable when held
# ---------------------------------------------------------------------------

def test_playable_with_no_resources():
    cs, cp = _state(cp_minors=frozenset({CARD_ID}), cp_res=Resources())
    assert playable_minors(cs, cp) == [CARD_ID]


# ---------------------------------------------------------------------------
# On-play via a real engine flow + passing circulation
# ---------------------------------------------------------------------------

def test_play_grants_food_then_passes():
    cs, cp = _state(cp_minors=frozenset({CARD_ID}), cp_res=Resources(food=0))
    cs = with_majors(cs, owner_by_idx={7: cp, 8: cp})  # 2 bottom-row majors
    opp = 1 - cp
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, CARD_ID)]
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p = cs.players[cp]
    assert p.resources.food == 4                     # 2 + 2 bottom-row majors
    assert CARD_ID not in p.minor_improvements       # traveling -> not kept
    assert CARD_ID not in p.hand_minors              # left my hand
    assert CARD_ID in cs.players[opp].hand_minors    # circulated to opponent
