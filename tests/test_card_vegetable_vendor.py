"""Tests for Vegetable Vendor (occupation, E141; Ephipparius Expansion; players 3+).

Card text: "Each time you use the "Major Improvement" or "Vegetable Seeds" action
space, you also get 1 vegetable or a "Major or Minor Improvement" action,
respectively."

Two before-window clauses: a +1-vegetable auto on the Major Improvement action
space, and an optional granted "Major or Minor Improvement" composite action on
the Vegetable Seeds space (the Angler/Merchant granted-composite idiom).
"""
import agricola.cards.vegetable_vendor  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction, FireTrigger, PlaceWorker, Proceed,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingMajorMinorImprovement
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_space

CARD_ID = "vegetable_vendor"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cards_state(*, clay=0):
    """A CARDS WORK state where the current player owns Vegetable Vendor, holds
    `clay`, and both target spaces are revealed."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], occupations=frozenset({CARD_ID}),
                     hand_occupations=frozenset(), hand_minors=frozenset(),
                     resources=Resources(clay=clay))
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset(),
                       hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_space(cs, "major_improvement", revealed=True, revealed_round=1)
    cs = with_space(cs, "vegetable_seeds", revealed=True, revealed_round=8)
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert CARD_ID in CARDS   # the vegetable-seeds trigger's apply is id-keyed


# ---------------------------------------------------------------------------
# Clause 1 — Major Improvement grants +1 vegetable (before the improvement)
# ---------------------------------------------------------------------------

def test_major_improvement_grants_one_vegetable():
    cs, cp = _cards_state(clay=2)             # 2 clay affords a Fireplace
    veg0 = cs.players[cp].resources.veg
    cs = step(cs, PlaceWorker(space="major_improvement"))
    # The +1 veg auto fires at the push (before-window), before any improvement.
    assert cs.players[cp].resources.veg == veg0 + 1


def test_vegetable_grant_does_not_fire_on_vegetable_seeds():
    # The +1 veg is scoped to the Major Improvement space only; Vegetable Seeds
    # grants its own veg (the space effect) but not the Major-Improvement bonus.
    cs, cp = _cards_state(clay=2)
    veg0 = cs.players[cp].resources.veg
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    # Only the space host is up (no auto veg yet — that comes at Proceed).
    assert cs.players[cp].resources.veg == veg0


# ---------------------------------------------------------------------------
# Clause 2 — Vegetable Seeds grants a "Major or Minor Improvement" action
# ---------------------------------------------------------------------------

def test_vegetable_seeds_offers_the_composite_grant():
    cs, cp = _cards_state(clay=2)             # a Fireplace is affordable -> not dead
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                    # optional -> decline


def test_firing_the_grant_pushes_the_composite():
    cs, cp = _cards_state(clay=2)
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement)
    assert top.initiated_by_id == f"card:{CARD_ID}"
    # The composite offers its build-major / play-minor children.
    names = {a.name for a in legal_actions(cs) if isinstance(a, ChooseSubAction)}
    assert "build_major" in names


def test_grant_not_offered_when_composite_would_be_dead():
    # No clay, no hand minor -> no affordable major and no playable minor, so the
    # grant is withheld (never a dead composite); only the space's Proceed remains.
    cs, cp = _cards_state(clay=0)
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la


def test_vegetable_seeds_still_grants_its_own_vegetable_on_proceed():
    cs, cp = _cards_state(clay=0)
    veg0 = cs.players[cp].resources.veg
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    cs = step(cs, Proceed())                  # decline the grant, take the space
    # Drain any trailing after-phase / Stop.
    while cs.pending_stack:
        cs = step(cs, legal_actions(cs)[0])
    assert cs.players[cp].resources.veg == veg0 + 1
