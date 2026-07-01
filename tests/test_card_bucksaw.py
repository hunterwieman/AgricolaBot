"""Tests for Bucksaw (minor improvement, A37):

    "Each time you renovate, you can also pay 1 wood to get 1 bonus point and 1 grain."

An OPTIONAL `before_renovate` trigger that pays 1 wood for +1 grain + a banked bonus
point (read back at scoring). The text is a bare, flat "each time you renovate" with
no reference to the renovate's target or outcome, so per the ruling in
CARD_AUTHORING_GUIDE.md ("Each time you [do X]" fires BEFORE X unless the text says
"after") it hooks the PendingRenovate BEFORE-phase — offered alongside the
CommitRenovate options, before the renovate commits. Each test drives the real
renovate flow through House Redevelopment so the firing point is exercised end-to-end.
"""
import agricola.cards.bucksaw  # noqa: F401  (registers the card; not yet in cards/__init__.py)

from agricola.actions import ChooseSubAction, CommitRenovate, FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("bucksaw",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _renovate_setup(material, *, idx=0, **resources):
    """A card-mode state with house_redevelopment revealed and the given house."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    return cs


def _at_before_phase(cs):
    """Drive to the PendingRenovate BEFORE-phase (after ChooseSubAction, before commit)."""
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_bucksaw_registered():
    assert "bucksaw" in MINORS
    assert MINORS["bucksaw"].vps == 0          # the point is banked, not printed
    assert MINORS["bucksaw"].cost == _expected_cost()
    assert any(cid == "bucksaw" for cid, _ in SCORING_TERMS)


def _expected_cost():
    from agricola.resources import Cost
    return Cost(resources=Resources(wood=1))


# ---------------------------------------------------------------------------
# Timing: the trigger is offered in the BEFORE-phase, alongside CommitRenovate
# ---------------------------------------------------------------------------

def test_bucksaw_offered_in_before_phase():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=1)
    cs = _own_minor(cs, 0, "bucksaw")
    cs = _at_before_phase(cs)
    # We are at the PendingRenovate BEFORE-phase: the frame has not committed yet.
    assert type(cs.pending_stack[-1]).__name__ == "PendingRenovate"
    assert cs.pending_stack[-1].phase == "before"
    legal = legal_actions(cs)
    # The optional Bucksaw trigger is surfaced BEFORE the renovate commits, alongside
    # the CommitRenovate option(s) — not after them in a separate after-phase.
    assert FireTrigger(card_id="bucksaw") in legal
    assert any(isinstance(a, CommitRenovate) for a in legal)


# ---------------------------------------------------------------------------
# Firing: pay 1 wood -> +1 grain + 1 banked bonus point
# ---------------------------------------------------------------------------

def test_bucksaw_fires_on_renovate():
    # Wood->clay renovate costs 2 clay + 1 reed; give an extra wood for Bucksaw.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=1)
    cs = _own_minor(cs, 0, "bucksaw")
    wood0 = cs.players[0].resources.wood
    grain0 = cs.players[0].resources.grain
    cs = _at_before_phase(cs)
    # The renovate before-hook surfaces the optional Bucksaw trigger (alongside the
    # CommitRenovate options).
    assert FireTrigger(card_id="bucksaw") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="bucksaw"))
    # No pending pushed — a pure state edit. Paid 1 wood, gained 1 grain.
    assert cs.players[0].resources.wood == wood0 - 1
    assert cs.players[0].resources.grain == grain0 + 1
    assert cs.players[0].card_state.get("bucksaw", 0) == 1   # 1 banked point
    # Now commit the renovate itself, then finish the turn.
    cs = step(cs, sole_renovate(cs))   # flips PendingRenovate to its after-phase
    cs = run_actions(cs, [Stop(), Proceed(), Stop()])
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.CLAY


def test_bucksaw_scores_banked_point():
    from agricola.scoring import score
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=1)
    cs = _own_minor(cs, 0, "bucksaw")
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        FireTrigger(card_id="bucksaw"),   # fire in the before-phase
        sole_renovate,                    # then commit the renovate
        Stop(),      # pop PendingRenovate after-phase
        Proceed(),   # flip the host to its after-phase
        Stop(),      # pop the host
    ])
    assert cs.players[0].card_state.get("bucksaw", 0) == 1
    # A direct read of the registered scoring term confirms the +1 it contributes.
    fn = next(fn for cid, fn in SCORING_TERMS if cid == "bucksaw")
    assert fn(cs, 0) == 1
    # And the +1 is included in the player's full end-game score (vs a cleared bank).
    cleared = fast_replace(
        cs.players[0], card_state=cs.players[0].card_state.set("bucksaw", 0))
    cs_cleared = fast_replace(
        cs, players=tuple(cleared if i == 0 else cs.players[i] for i in range(2)))
    assert score(cs, 0)[0] == score(cs_cleared, 0)[0] + 1


# ---------------------------------------------------------------------------
# Optionality: declinable by just committing the renovate without firing
# ---------------------------------------------------------------------------

def test_bucksaw_decline():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=1)
    cs = _own_minor(cs, 0, "bucksaw")
    wood0 = cs.players[0].resources.wood
    grain0 = cs.players[0].resources.grain
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,   # commit the renovate without firing Bucksaw (declined)
        Stop(),      # pop PendingRenovate after-phase
        Proceed(),   # flip the host to its after-phase
        Stop(),      # pop the host
    ])
    assert cs.pending_stack == ()
    assert cs.players[0].resources.wood == wood0       # nothing paid
    assert cs.players[0].resources.grain == grain0     # nothing gained
    assert cs.players[0].card_state.get("bucksaw", 0) == 0   # no point banked
    assert cs.players[0].house_material == HouseMaterial.CLAY


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_bucksaw_not_offered_without_wood():
    # Renovate consumes only clay + reed (never wood), so with 0 wood the player still
    # renovates fine — but can't pay Bucksaw's 1-wood charge -> Bucksaw not offered.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=0)
    cs = _own_minor(cs, 0, "bucksaw")
    cs = _at_before_phase(cs)
    legal = legal_actions(cs)
    assert FireTrigger(card_id="bucksaw") not in legal
    # The mandatory renovate is still offered (no stranding — renovate needs no wood).
    assert any(isinstance(a, CommitRenovate) for a in legal)


def test_bucksaw_not_offered_when_unowned():
    # A player who has not played Bucksaw never sees the trigger.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=5)
    cs = _at_before_phase(cs)
    assert FireTrigger(card_id="bucksaw") not in legal_actions(cs)


def test_bucksaw_once_per_renovate():
    # After firing once, the trigger is stamped in triggers_resolved -> not offered
    # again within the same renovate action.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=2)
    cs = _own_minor(cs, 0, "bucksaw")
    cs = _at_before_phase(cs)
    cs = step(cs, FireTrigger(card_id="bucksaw"))
    assert FireTrigger(card_id="bucksaw") not in legal_actions(cs)
    assert cs.players[0].card_state.get("bucksaw", 0) == 1   # only banked once
