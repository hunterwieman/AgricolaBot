"""Tests for Pumpernickel (minor improvement, deck E #7; Ephipparius; traveling).

Card text: "You immediately get 4 food. (Effectively, you are turning 1 grain
into 4 food.)" Cost 1 grain, no prerequisite, traveling (passed to the opponent
after the on-play effect).
"""
import agricola.cards.pumpernickel  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "pumpernickel"

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
    assert spec.cost.resources == Resources(grain=1)
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# On-play effect: +4 food
# ---------------------------------------------------------------------------

def test_on_play_adds_four_food():
    cs, cp = _state(cp_res=Resources(food=0))
    opp = 1 - cp
    opp_food0 = cs.players[opp].resources.food
    after = MINORS[CARD_ID].on_play(cs, cp)
    assert after.players[cp].resources.food == 4
    assert after.players[opp].resources.food == opp_food0  # opponent untouched


# ---------------------------------------------------------------------------
# playable_minors gates on cost (real legality path)
# ---------------------------------------------------------------------------

def test_playable_only_when_cost_met():
    # Holds the card and has 1 grain -> playable.
    cs, cp = _state(cp_minors=frozenset({CARD_ID}), cp_res=Resources(grain=1))
    assert playable_minors(cs, cp) == [CARD_ID]
    # No grain -> cost unaffordable.
    cs, cp = _state(cp_minors=frozenset({CARD_ID}), cp_res=Resources(grain=0))
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play via a real engine flow + passing circulation
# ---------------------------------------------------------------------------

def test_play_grants_four_food_then_passes():
    cs, cp = _state(cp_minors=frozenset({CARD_ID}), cp_res=Resources(grain=2, food=0))
    opp = 1 - cp
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, CARD_ID)]
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p = cs.players[cp]
    assert p.resources.food == 4                     # +4 food
    assert p.resources.grain == 1                    # paid 1 of the 2 grain
    assert CARD_ID not in p.minor_improvements       # traveling -> not kept
    assert CARD_ID not in p.hand_minors              # left my hand
    assert CARD_ID in cs.players[opp].hand_minors    # circulated to opponent
