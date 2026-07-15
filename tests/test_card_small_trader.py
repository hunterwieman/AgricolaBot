"""Tests for Small Trader (occupation, A109).

Card text: "Each time you take a 'Major or Minor Improvement' action to play an
improvement from your hand, you also get 3 food."
Clarification: "Does not work unless you literally get that action."

The +3 food fires only when you LITERALLY take the Major Improvement *action
space* and play a MINOR there. It must NOT fire when:
  - you build a major at that space (not an improvement from your hand),
  - you reach the play-minor frame via House Redevelopment's improvement step
    (or Basic Wish / Meeting Place) — "does not work unless you literally get
    that action".
"""
import agricola.cards.small_trader  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import sole_build_major, sole_play_minor, sole_renovate

_POOL = CardPool(
    occupations=("small_trader",) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "small_trader" in OCCUPATIONS
    cards = {e.card_id for e in AUTO_EFFECTS.get("after_major_minor_improvement", ())}
    assert "small_trader" in cards


# ---------------------------------------------------------------------------
# State helpers — drive the REAL Major-Improvement / House-Redev flows
# ---------------------------------------------------------------------------

def _state(space_id, *, seed=5, occ=(), minors=(), res=None):
    """Card-mode state: `space_id` revealed + free, current player given the
    occupations / hand minors / resources. Opponent's hand is emptied so it
    can never play (keeps the flow deterministic)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, space_id), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, space_id, sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     hand_minors=frozenset(minors),
                     resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# POSITIVE: Major Improvement space + play a minor from hand -> +3 food
# ---------------------------------------------------------------------------

def test_play_minor_at_major_improvement_grants_food():
    cs, cp = _state("major_improvement", occ=("small_trader",),
                    minors=("market_stall",), res=Resources(grain=1))
    before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))   # push PendingMajorMinorImprovement
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())   # pop PendingPlayMinor after-phase -> MMI flips to after (auto fires)

    # market_stall grants no food; the only food gain is Small Trader's +3.
    assert cs.players[cp].resources.food == before + 3
    assert cs.players[cp].resources.veg == 1   # market_stall: 1 grain -> 1 veg


def test_no_food_without_the_occupation():
    # Same play, but the player does NOT own Small Trader -> no +3.
    cs, cp = _state("major_improvement", occ=(),
                    minors=("market_stall",), res=Resources(grain=1))
    before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())

    assert cs.players[cp].resources.food == before


# ---------------------------------------------------------------------------
# NEGATIVE: building a MAJOR at that space gives no food (not a hand improvement)
# ---------------------------------------------------------------------------

def test_build_major_at_major_improvement_grants_no_food():
    cs, cp = _state("major_improvement", occ=("small_trader",),
                    minors=(), res=Resources(clay=2))   # Fireplace (major_idx 0) = 2 clay
    before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))               # build Fireplace
    cs = step(cs, Stop())   # pop PendingBuildMajor after-phase -> MMI flips to after

    # major_chosen (not minor_chosen) -> Small Trader's gate fails -> no food.
    assert cs.players[cp].resources.food == before


# ---------------------------------------------------------------------------
# House Redevelopment's improvement step IS a 'Major or Minor Improvement'
# action, so playing a minor there DOES grant the food (user ruling 2026-07-15:
# Small Trader keys off the ACTION, not the action space).
# ---------------------------------------------------------------------------

def test_house_redev_play_minor_grants_food():
    # house_redevelopment revealed; renovate (clay 2 + reed 1) then play a minor
    # (1 grain). The play-minor is reached via the composite 'Major or Minor
    # Improvement' action (PendingMajorMinorImprovement), so Small Trader fires.
    cs, cp = _state("house_redevelopment", occ=("small_trader",),
                    minors=("market_stall",),
                    res=Resources(clay=2, reed=1, grain=1))
    before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, sole_renovate(cs))
    cs = step(cs, Stop())                                # pop PendingRenovate after-phase
    cs = step(cs, ChooseSubAction(name="improvement"))   # -> PendingMajorMinorImprovement
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())   # pop PendingPlayMinor after-phase -> MMI flips to after

    assert cs.players[cp].resources.food == before + 3   # Small Trader fires
    assert cs.players[cp].resources.veg == 1             # market_stall still ran


# ---------------------------------------------------------------------------
# NEGATIVE: Meeting Place offers the 'Minor Improvement' action (a bare minor),
# NOT the 'Major or Minor Improvement' action — so Small Trader does NOT fire.
# ---------------------------------------------------------------------------

def test_meeting_place_play_minor_grants_no_food():
    cs, cp = _state("meeting_place", occ=("small_trader",),
                    minors=("market_stall",), res=Resources(grain=1))
    before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="meeting_place"))     # become SP (no food, Cards mode)
    cs = step(cs, ChooseSubAction(name="play_minor"))     # the 'Minor Improvement' action
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())

    assert cs.players[cp].resources.food == before   # bare minor -> no Small Trader
    assert cs.players[cp].resources.veg == 1         # market_stall still ran
