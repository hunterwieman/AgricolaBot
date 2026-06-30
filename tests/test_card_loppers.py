"""Tests for Loppers (minor A34; Artifex).

"Each time you build 1 or more fences, you can also use this card to exchange 1
wood and 1 fence in your supply for 2 food and 1 bonus point."
Cost: 1 wood. Prereq: 2 occupations.

The card is an OPTIONAL after-build-fences trigger: after at least one fence is
built (Proceed flips PendingBuildFences to its after-phase), the host offers
`FireTrigger(card_id="loppers")` alongside `Stop`. Firing spends 1 wood + 1 fence
from the stored supply pile (`fences_in_supply`) for 2 food + 1 banked bonus
point; declining is just `Stop`. Tests drive the REAL fencing flow (Fencing space
and Farm Redevelopment), per CARD_AUTHORING_GUIDE §5.

A 2x2 corner pasture costs exactly 8 fence pieces, so it always satisfies "1 or
more fences" and is the standard build used here.
"""
import agricola.cards.loppers  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.loppers import CARD_ID, _eligible, _score
from agricola.cards.specs import MINORS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from tests.factories import with_house, with_resources, with_round
from tests.test_fencing import _fencing_setup
from tests.test_utils import sole_renovate

# A top-right 2x2 (4 cells, 8 fence pieces) — in the default RESTRICTED universe.
_2x2_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx=0, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_supply(state, n, idx=0):
    p = fast_replace(state.players[idx], fences_in_supply=n)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    return state


def _build_2x2(state):
    """Enter build-fences, commit the 2x2, Proceed to the after-phase (where the
    Loppers FireTrigger is offered). Stops short of Stop so the caller decides
    whether to fire."""
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())   # flip PendingBuildFences -> after-phase
    return state


def _food(state, idx=0):
    return state.players[idx].resources.food


def _wood(state, idx=0):
    return state.players[idx].resources.wood


def _has_fire(state, idx=0):
    return any(
        isinstance(a, FireTrigger) and a.card_id == CARD_ID
        for a in legal_actions(state)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.cost.animals == Animals()
    assert spec.min_occupations == 2
    assert spec.vps == 0          # the bonus point is banked, not on printed vps
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# The exchange — firing the optional trigger
# ---------------------------------------------------------------------------

def test_fire_exchanges_wood_and_fence_for_food_and_point():
    # Plenty of wood so the 2x2 (8 wood) leaves >=1 wood to spend on the exchange.
    state = _own(_fencing_setup(wood=12))
    state = _build_2x2(state)
    # After-phase: the Loppers FireTrigger must be offered.
    assert _has_fire(state)
    wood_before = _wood(state)
    food_before = _food(state)
    supply_before = state.players[0].fences_in_supply
    # Fire it.
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert _wood(state) == wood_before - 1
    assert _food(state) == food_before + 2
    assert state.players[0].fences_in_supply == supply_before - 1
    assert state.players[0].card_state.get(CARD_ID) == 1   # 1 point banked
    assert _score(state, 0) == 1
    # Pop the host.
    state = step(state, Stop())


def test_decline_does_nothing():
    # Same flow, but Stop without firing -> no exchange, no banked point.
    state = _own(_fencing_setup(wood=12))
    state = _build_2x2(state)
    assert _has_fire(state)
    wood_before = _wood(state)
    food_before = _food(state)
    supply_before = state.players[0].fences_in_supply
    state = step(state, Stop())            # decline + pop PendingBuildFences
    state = step(state, Stop())            # pop PendingSubActionSpace
    assert _wood(state) == wood_before
    assert _food(state) == food_before
    assert state.players[0].fences_in_supply == supply_before
    assert _score(state, 0) == 0


def test_no_offer_without_card():
    # Build the same 2x2 but DON'T own the card -> no FireTrigger ever surfaces.
    state = _fencing_setup(wood=12)
    state = _build_2x2(state)
    assert not _has_fire(state)


# ---------------------------------------------------------------------------
# Once-per-build-fences-action scoping
# ---------------------------------------------------------------------------

def test_fires_at_most_once_per_action():
    state = _own(_fencing_setup(wood=12))
    state = _build_2x2(state)
    assert _has_fire(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # After firing once, triggers_resolved contains "loppers" -> no longer offered,
    # even though wood + fences remain to pay again.
    assert state.players[0].resources.wood >= 1
    assert state.players[0].fences_in_supply >= 1
    assert not _has_fire(state)
    state = step(state, Stop())
    assert _score(state, 0) == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries (never a dead-end)
# ---------------------------------------------------------------------------

def test_not_offered_when_no_wood_to_spend():
    # Exactly 8 wood: the 2x2 consumes all of it, leaving 0 -> can't pay the
    # exchange's 1 wood -> not offered.
    state = _own(_fencing_setup(wood=8))
    state = _build_2x2(state)
    assert state.players[0].resources.wood == 0
    assert not _has_fire(state)


def test_not_offered_when_no_fence_in_supply():
    # Wood is fine, but the stored supply pile is empty -> not offered.
    state = _own(_fencing_setup(wood=12))
    state = _set_supply(state, 8)          # 2x2 will drain 8 -> 0 left in supply
    state = _build_2x2(state)
    assert state.players[0].fences_in_supply == 0
    assert state.players[0].resources.wood >= 1
    assert not _has_fire(state)


def test_eligible_predicate_direct():
    # Direct unit checks of _eligible across the boundaries.
    state = _own(_fencing_setup(wood=12))
    p0 = state.players[0]
    # wood>=1 and supply>=1 and not yet fired -> eligible.
    assert _eligible(state, 0, frozenset())
    # already fired this action -> not eligible.
    assert not _eligible(state, 0, frozenset({CARD_ID}))
    # no wood -> not eligible.
    s_nowood = fast_replace(
        state, players=tuple(
            fast_replace(p0, resources=p0.resources - Resources(wood=p0.resources.wood))
            if i == 0 else state.players[i] for i in range(2)))
    assert not _eligible(s_nowood, 0, frozenset())
    # no fence in supply -> not eligible.
    s_nofence = _set_supply(state, 0)
    assert not _eligible(s_nofence, 0, frozenset())


# ---------------------------------------------------------------------------
# Other entry point: Farm Redevelopment ("Overhaul")
# ---------------------------------------------------------------------------

def test_via_farm_redevelopment():
    from tests.factories import with_space
    state = _fencing_setup(wood=20)
    state = with_house(state, 0, material=HouseMaterial.WOOD)
    state = with_resources(state, 0, wood=20, clay=4, reed=2)
    state = _own(state)
    state = with_space(state, "farm_redevelopment", revealed=True)
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, sole_renovate(state))
    state = step(state, Stop())                                  # pop PendingRenovate
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())                              # flip PBF -> after
    assert _has_fire(state)
    food_before = _food(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert _food(state) == food_before + 2
    assert _score(state, 0) == 1
    state = step(state, Stop())                                 # pop PBF
    state = step(state, Proceed())                             # flip FarmRedev -> after
    state = step(state, Stop())                                # pop FarmRedev
