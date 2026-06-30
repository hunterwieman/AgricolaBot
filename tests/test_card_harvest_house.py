"""Harvest House (B71) — conditional on-play one-shot minor.

Card text: "When you play this card, if the number of completed harvests is equal
to the number of occupations you played, you immediately get 1 food, 1 grain,
and 1 vegetable." Cost 1 wood / 1 clay / 1 reed; 2 VPs; kept (not passing).

Tests:
  - registration (spec present, cost / vps / not-passing correct);
  - the grant fires via a REAL play-minor engine flow when
    completed_harvests == n_occupations;
  - it does NOT fire when the counts differ (card still kept for its VPs);
  - the strict-`<` harvest count: round R's own harvest is not yet counted
    (a card played in WORK of a harvest round R sees harvests of rounds < R).
"""
import agricola.cards.harvest_house  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("harvest_house",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _setup_play(seed, *, round_number, occupations):
    """A WORK state at `round_number` with the current player holding Harvest House
    in hand, `occupations` already played, and enough resources to pay its cost."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cs = fast_replace(cs, round_number=round_number)
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=1, clay=1, reed=1)
    p = fast_replace(
        cs.players[cp],
        hand_minors=frozenset({"harvest_house"}),
        occupations=frozenset(occupations),
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _play_harvest_house(cs):
    """Drive the real Major-Improvement -> play-minor flow to play Harvest House."""
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "harvest_house"))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "harvest_house" in MINORS
    spec = MINORS["harvest_house"]
    assert spec.cost.resources == Resources(wood=1, clay=1, reed=1)
    assert spec.vps == 2
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Grant fires when completed_harvests == n_occupations (via real engine flow)
# ---------------------------------------------------------------------------

def test_grant_fires_when_counts_equal():
    # Round 5 -> harvest 4 completed = 1; one occupation played -> 1 == 1 -> fires.
    cs, cp = _setup_play(5, round_number=5, occupations={"o0"})
    before = cs.players[cp].resources
    cs = _play_harvest_house(cs)
    after = cs.players[cp].resources
    # Cost (1 wood/1 clay/1 reed) was paid; grant adds +1 food/grain/veg.
    assert after.food == before.food + 1
    assert after.grain == before.grain + 1
    assert after.veg == before.veg + 1
    # Kept (not passing) -> scores its 2 VPs.
    assert "harvest_house" in cs.players[cp].minor_improvements
    assert "harvest_house" not in cs.players[1 - cp].hand_minors


def test_zero_zero_case_fires():
    # Round 1 (no harvest yet) -> 0 completed; 0 occupations -> 0 == 0 -> fires.
    cs, cp = _setup_play(5, round_number=1, occupations=set())
    before = cs.players[cp].resources
    cs = _play_harvest_house(cs)
    after = cs.players[cp].resources
    assert after.food == before.food + 1
    assert after.grain == before.grain + 1
    assert after.veg == before.veg + 1


# ---------------------------------------------------------------------------
# Grant does NOT fire when the counts differ
# ---------------------------------------------------------------------------

def test_no_grant_when_more_occupations_than_harvests():
    # Round 5 -> 1 completed harvest; 2 occupations -> 1 != 2 -> no goods.
    cs, cp = _setup_play(5, round_number=5, occupations={"o0", "o1"})
    before = cs.players[cp].resources
    cs = _play_harvest_house(cs)
    after = cs.players[cp].resources
    # Only the cost was paid; no immediate goods granted.
    assert after.food == before.food
    assert after.grain == before.grain
    assert after.veg == before.veg
    # Still played and kept for its VPs.
    assert "harvest_house" in cs.players[cp].minor_improvements


def test_no_grant_when_fewer_occupations_than_harvests():
    # Round 8 -> harvests {4,7} completed = 2; 0 occupations -> 2 != 0 -> no goods.
    cs, cp = _setup_play(5, round_number=8, occupations=set())
    before = cs.players[cp].resources
    cs = _play_harvest_house(cs)
    after = cs.players[cp].resources
    assert after.food == before.food
    assert after.grain == before.grain
    assert after.veg == before.veg


# ---------------------------------------------------------------------------
# Strict-`<` harvest count: round R's own harvest is not yet counted
# ---------------------------------------------------------------------------

def test_current_round_harvest_not_counted():
    # Round 7 is itself a harvest round, but harvest 7 has NOT resolved during
    # WORK of round 7 -> only harvest 4 counts -> 1 completed.
    # With 1 occupation: 1 == 1 -> fires (proves round 7 is excluded; were it
    # counted the total would be 2 and this would not fire).
    cs, cp = _setup_play(5, round_number=7, occupations={"o0"})
    before = cs.players[cp].resources
    cs = _play_harvest_house(cs)
    after = cs.players[cp].resources
    assert after.food == before.food + 1
    assert after.grain == before.grain + 1
    assert after.veg == before.veg + 1

    # Conversely, with 2 occupations at round 7 the counts differ (1 != 2) -> no
    # goods, confirming harvest 7 is NOT double-counted into the total.
    cs2, cp2 = _setup_play(6, round_number=7, occupations={"o0", "o1"})
    b2 = cs2.players[cp2].resources
    cs2 = _play_harvest_house(cs2)
    a2 = cs2.players[cp2].resources
    assert a2.food == b2.food and a2.grain == b2.grain and a2.veg == b2.veg


# ---------------------------------------------------------------------------
# 2 VPs scored when kept
# ---------------------------------------------------------------------------

def test_scores_two_vps():
    cs, cp = _setup_play(5, round_number=5, occupations={"o0"})
    base, _ = score(cs, cp)
    cs = _play_harvest_house(cs)
    after, _ = score(cs, cp)
    # The +2 from the kept improvement (goods don't directly score, but the VPs do).
    assert after >= base + 2
