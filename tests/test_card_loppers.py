"""Tests for Loppers (minor A34; Artifex).

"Each time you build 1 or more fences, you can also use this card to exchange 1
wood and 1 fence in your supply for 2 food and 1 bonus point."
Cost: 1 wood. Prereq: 2 occupations.

Loppers is an OPTIONAL "each time you build 1 or more fences" exchange. Two
rulings govern it (CARD_AUTHORING_GUIDE):

  - BEFORE timing. "Each time you [use / do X]" fires in the BEFORE window of X's
    host, not after. Loppers is a FLAT exchange (it reads nothing about which
    pastures were built), so — unlike Shepherd's Crook / trimmer / asparagus_gift,
    whose grants depend on the fencing OUTCOME and correctly resolve after — it
    lives on `before_build_fences`. The `FireTrigger(card_id="loppers")` is offered
    in the before-phase of PendingBuildFences (alongside the pasture commits),
    BEFORE any pasture is committed. Declining is simply not firing it.

  - Stranding guard. Because the exchange fires BEFORE the mandatory fencing build,
    firing it must not leave the build unable to complete. It spends 1 wood + 1
    fence from the supply pile, and the host requires >= 1 legal pasture commit
    afterward. So eligibility requires that after paying (-1 wood, -1 fence) at
    least one legal pasture is STILL buildable — a build needs both enough fence
    pieces in supply AND enough wood for its segments.

Firing spends 1 wood + 1 fence from the stored supply pile (`fences_in_supply`)
for 2 food + 1 banked bonus point. Tests drive the REAL fencing flow (Fencing
space and Farm Redevelopment), per CARD_AUTHORING_GUIDE §5.

A 2x2 corner pasture costs exactly 8 fence pieces and 8 wood, so it always
satisfies "1 or more fences" and is the standard build used here. The
before-phase FireTrigger must be exercised BEFORE that commit (it fires up front),
while the wood/fence needed to still afford it must be checked against a pasture
the player could go on to build.
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
from agricola.constants import GameMode, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from tests.factories import with_house, with_resources
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


def _cards(state):
    """Flip a Family-scaffold state into CARDS mode, so the fence-scan cache (which
    ignores `fences_in_supply` in Family) is bypassed and the supply count is
    honored by the fencing-legality predicate the stranding guard uses."""
    return fast_replace(state, mode=GameMode.CARDS)


def _set_supply(state, n, idx=0):
    p = fast_replace(state.players[idx], fences_in_supply=n)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
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


def test_registered_on_before_build_fences():
    """The timing ruling: Loppers hooks the BEFORE window, not after."""
    from agricola.cards.triggers import TRIGGERS
    before = [e.card_id for e in TRIGGERS.get("before_build_fences", ())]
    after = [e.card_id for e in TRIGGERS.get("after_build_fences", ())]
    assert CARD_ID in before
    assert CARD_ID not in after


# ---------------------------------------------------------------------------
# The exchange is offered — and fired — in the BEFORE-phase
# ---------------------------------------------------------------------------

def test_offered_in_before_phase():
    # After entering build-fences (PendingBuildFences pushed, before-phase) the
    # FireTrigger is offered alongside the CommitBuildPasture options — BEFORE any
    # pasture is committed.
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    la = legal_actions(state)
    assert any(isinstance(a, FireTrigger) and a.card_id == CARD_ID for a in la)
    assert any(isinstance(a, CommitBuildPasture) for a in la)   # still in before-phase


def test_fire_then_build_completes():
    # Fire the exchange up front (before-phase), then the mandatory build still
    # completes: commit the 2x2 -> Proceed -> Stop.
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    assert _has_fire(state)
    wood_before = _wood(state)
    food_before = _food(state)
    supply_before = state.players[0].fences_in_supply

    state = step(state, FireTrigger(card_id=CARD_ID))          # fire in before-phase
    assert _wood(state) == wood_before - 1
    assert _food(state) == food_before + 2
    assert state.players[0].fences_in_supply == supply_before - 1
    assert state.players[0].card_state.get(CARD_ID) == 1       # 1 point banked
    assert _score(state, 0) == 1

    # The mandatory build still completes after the exchange (2x2 needs 8 wood; we
    # started at 12, spent 1 -> 11 left, plenty).
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())                            # flip to after-phase
    state = step(state, Stop())                               # pop PendingBuildFences


def test_decline_does_nothing():
    # Enter build-fences, commit + Proceed + Stop without ever firing -> no
    # exchange, no banked point.
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    assert _has_fire(state)
    wood_before = _wood(state)
    food_before = _food(state)
    supply_before = state.players[0].fences_in_supply

    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())
    # After Proceed flips PendingBuildFences to its after-phase, the before-only
    # FireTrigger is gone (declining = never having fired it).
    assert not _has_fire(state)
    state = step(state, Stop())

    assert _wood(state) == wood_before - 8    # only the 2x2's 8 wood
    assert _food(state) == food_before
    assert state.players[0].fences_in_supply == supply_before - 8
    assert _score(state, 0) == 0


def test_no_offer_without_card():
    # Enter build-fences without owning the card -> no FireTrigger ever surfaces.
    state = _fencing_setup(wood=12)
    state = _enter_build_fences(state)
    assert not _has_fire(state)


# ---------------------------------------------------------------------------
# Once-per-build-fences-action scoping
# ---------------------------------------------------------------------------

def test_fires_at_most_once_per_action():
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    assert _has_fire(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # After firing once, triggers_resolved contains "loppers" -> no longer offered,
    # even though wood + fences remain to pay again.
    assert state.players[0].resources.wood >= 1
    assert state.players[0].fences_in_supply >= 1
    assert not _has_fire(state)
    # Build still completes.
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())
    state = step(state, Stop())
    assert _score(state, 0) == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries — payment gate (never a dead-end)
# ---------------------------------------------------------------------------

def test_not_offered_when_no_fence_in_supply():
    # Wood is fine, but the stored supply pile is empty -> can't pay -> not offered.
    state = _own(_fencing_setup(wood=12))
    state = _set_supply(state, 0)
    state = _enter_build_fences(state)
    assert state.players[0].fences_in_supply == 0
    assert state.players[0].resources.wood >= 1
    assert not _has_fire(state)


def test_eligible_predicate_direct_payment_gate():
    # Direct unit checks of the payment gate + once-per-use flag.
    state = _own(_fencing_setup(wood=12))
    p0 = state.players[0]
    assert _eligible(state, 0, frozenset())                    # can pay, not fired
    assert not _eligible(state, 0, frozenset({CARD_ID}))       # already fired this action
    # no wood -> can't pay -> not eligible.
    s_nowood = fast_replace(
        state, players=tuple(
            fast_replace(p0, resources=p0.resources - Resources(wood=p0.resources.wood))
            if i == 0 else state.players[i] for i in range(2)))
    assert not _eligible(s_nowood, 0, frozenset())
    # no fence in supply -> can't pay -> not eligible.
    assert not _eligible(_set_supply(state, 0), 0, frozenset())


# ---------------------------------------------------------------------------
# The stranding guard — paying must leave a legal pasture buildable
# ---------------------------------------------------------------------------

def test_not_offered_when_paying_wood_would_strand_the_build():
    # A fresh farmyard's cheapest pasture needs 4 wood. With exactly 4 wood the
    # player CAN pay the exchange (>=1 wood, >=1 fence) but spending 1 would leave
    # 3 -> no legal pasture buildable -> the guard suppresses the offer.
    state = _own(_fencing_setup(wood=4))
    state = _enter_build_fences(state)
    assert state.players[0].resources.wood >= 1
    assert state.players[0].fences_in_supply >= 1
    assert not _has_fire(state)                                # stranded on wood
    # A commit is still legal (the player builds without firing).
    assert any(isinstance(a, CommitBuildPasture) for a in legal_actions(state))


def test_offered_when_wood_just_clears_the_strand():
    # With 5 wood, paying 1 leaves 4 -> the cheapest 4-wood pasture is still
    # buildable, so the exchange IS offered.
    state = _own(_fencing_setup(wood=5))
    state = _enter_build_fences(state)
    assert _has_fire(state)


def test_not_offered_when_paying_fence_would_strand_the_build():
    # CARDS mode (so the fencing-legality predicate honors `fences_in_supply`, which
    # the Family fence-scan cache ignores). The cheapest fresh-farmyard pasture needs
    # 4 fence pieces; with a 4-piece supply the player can pay (>=1 fence) but
    # spending 1 leaves 3 -> no legal pasture buildable -> guard suppresses the offer.
    state = _cards(_own(_fencing_setup(wood=12)))
    state = _set_supply(state, 4)
    assert state.players[0].resources.wood >= 1
    assert state.players[0].fences_in_supply >= 1
    assert not _eligible(state, 0, frozenset())               # stranded on fence pieces
    # One more piece clears it: paying 1 leaves 4 -> buildable.
    assert _eligible(_set_supply(state, 5), 0, frozenset())


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
    # Before-phase of the granted build fences: Loppers is offered up front.
    assert _has_fire(state)
    food_before = _food(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert _food(state) == food_before + 2
    assert _score(state, 0) == 1
    # The mandatory build still completes.
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())                             # flip PBF -> after
    state = step(state, Stop())                                # pop PBF
    state = step(state, Proceed())                             # flip FarmRedev -> after
    state = step(state, Stop())                                # pop FarmRedev
