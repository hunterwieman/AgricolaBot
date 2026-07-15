"""Tests for Plumber (occupation, B128; Bubulcus Expansion; players 3+).

Card text: "Each time after you use the "Major Improvement" action space, you can
take a "renovation" action, paying 2 clay or 2 stone less for the renovation."

The Master Renovator grant-scoped-renovate pattern on the Major Improvement
space's after-window (the PendingSubActionSpace wrapper, space_id
"major_improvement"): an optional `after_action_space` trigger pushes a
PendingRenovate whose cost is reduced by 2 clay/stone, scoped via
CostCtx.granted_by so a House Redevelopment renovate pays full price.
"""
import agricola.cards.plumber  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction, CommitRenovate, FireTrigger, PlaceWorker, Stop,
)
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.plumber import CARD_ID, _eligible, _reduce
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import _renovate_ctx, effective_payments, legal_actions
from agricola.pending import PendingRenovate, PendingSubActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_pending_stack, with_space
from tests.test_utils import sole_build_major

_PROVENANCE = f"card:{CARD_ID}"
_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _base(*, own=True, house=HouseMaterial.WOOD, minors=frozenset(), **res):
    """A CARDS state with (optionally) the owner set up, house + supply given."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_occupations": frozenset(), "hand_minors": frozenset(),
               "resources": Resources(**res), "minor_improvements": minors}
    if own:
        changes["occupations"] = frozenset({CARD_ID})
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset(),
                       hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_house(cs, cp, house)
    return cs, cp


def _after_frame(cs, cp, *, space="major_improvement"):
    """Park the state at the given space's after-window (the wrapper's after-phase)."""
    return with_pending_stack(cs, (PendingSubActionSpace(
        player_idx=cp, initiated_by_id=f"space:{space}",
        subaction_complete=True, phase="after"),))


def _fires(cs):
    return [a for a in legal_actions(cs)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _renovate_payments(cs):
    return [a.payment for a in legal_actions(cs) if isinstance(a, CommitRenovate)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    entry = CARDS[CARD_ID]
    assert entry.event == "after_action_space"
    assert entry.mandatory is False               # "you can"
    assert any(cid == CARD_ID for cid, _fn in REDUCTIONS.get("renovate", ()))


# ---------------------------------------------------------------------------
# The full flow: use Major Improvement, then the discounted renovate
# ---------------------------------------------------------------------------

def test_full_flow_surfaces_and_discounts_the_renovate():
    # 2 clay (a Fireplace) + 1 reed. After building, the discounted wood->clay
    # renovate (2 clay + 1 reed, -2 clay) costs just 1 reed.
    cs, cp = _base(clay=2, reed=1)
    cs = with_space(cs, "major_improvement", revealed=True, revealed_round=1)
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))         # Fireplace (idx 0)
    # Drain the nested after-phases back to the Major Improvement after-window.
    for _ in range(6):
        if _fires(cs):
            break
        cs = step(cs, Stop())
    assert _fires(cs) == [FireTrigger(card_id=CARD_ID)]
    assert Stop() in legal_actions(cs)             # declinable

    cs = step(cs, FireTrigger(card_id=CARD_ID))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingRenovate)
    assert top.initiated_by_id == _PROVENANCE
    # The reduction replaces the cost: the frontier is the single discounted payment.
    assert _renovate_payments(cs) == [Resources(reed=1)]

    cs = step(cs, CommitRenovate(payment=Resources(reed=1),
                                 to_material=HouseMaterial.CLAY))
    p = cs.players[cp]
    assert p.house_material is HouseMaterial.CLAY
    assert p.resources.reed == 0                   # paid the 1 reed
    assert p.resources.clay == 0                   # the 2 clay were fully discounted


# ---------------------------------------------------------------------------
# Eligibility (tested at a parked after-window)
# ---------------------------------------------------------------------------

def test_offered_at_the_after_window():
    cs, cp = _base(clay=2, reed=1)
    cs = _after_frame(cs, cp)
    assert _eligible(cs, cp, frozenset())
    assert _fires(cs) == [FireTrigger(card_id=CARD_ID)]


def test_discount_makes_an_otherwise_unaffordable_renovate_reachable():
    # 0 clay + 1 reed: printed 2 clay + 1 reed is unaffordable, but -2 clay makes
    # it 1 reed, so the grant is offered (and that is the only frontier entry).
    cs, cp = _base(clay=0, reed=1)
    cs = _after_frame(cs, cp)
    assert _eligible(cs, cp, frozenset())
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    assert _renovate_payments(cs) == [Resources(reed=1)]


def test_not_offered_when_unaffordable_even_with_discount():
    # 0 clay, 0 reed: even the -2-clay cost still needs 1 reed -> unpayable.
    cs, cp = _base(clay=0, reed=0)
    cs = _after_frame(cs, cp)
    assert not _eligible(cs, cp, frozenset())


def test_not_offered_with_a_stone_house():
    cs, cp = _base(house=HouseMaterial.STONE, clay=9, stone=9, reed=9)
    cs = _after_frame(cs, cp)
    assert not _eligible(cs, cp, frozenset())


def test_mantlepiece_blocks_the_grant():
    cs, cp = _base(clay=2, reed=1, minors=frozenset({"mantlepiece"}))
    cs = _after_frame(cs, cp)
    assert not _eligible(cs, cp, frozenset())


def test_not_offered_on_a_different_space():
    cs, cp = _base(clay=2, reed=1)
    cs = _after_frame(cs, cp, space="farmland")    # a different space's after-window
    assert not _eligible(cs, cp, frozenset())
    assert _fires(cs) == []


def test_unowned_is_inert():
    cs, cp = _base(own=False, clay=2, reed=1)
    cs = _after_frame(cs, cp)
    assert _fires(cs) == []


# ---------------------------------------------------------------------------
# The discount is scoped to THIS grant (House Redevelopment pays full price)
# ---------------------------------------------------------------------------

def test_house_redevelopment_renovate_not_discounted():
    cs, cp = _base(clay=2, reed=1)
    cs = with_space(cs, "house_redevelopment", revealed=True, revealed_round=6)
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    # granted_by is None for a space renovate -> the reduction is skipped.
    assert _renovate_payments(cs) == [Resources(clay=2, reed=1)]


# ---------------------------------------------------------------------------
# The reduction generator (unit pins)
# ---------------------------------------------------------------------------

def test_reduce_passes_ungranted_ctx_through_unchanged():
    cs, cp = _base(clay=2, reed=1)
    p = cs.players[cp]
    cost = Resources(clay=2, reed=1)
    assert _reduce(cs, cp, _renovate_ctx(p, HouseMaterial.CLAY), cost) == cost
    other = _renovate_ctx(p, HouseMaterial.CLAY, granted_by="card:cottager")
    assert _reduce(cs, cp, other, cost) == cost


def test_effective_payments_apply_the_floored_discount():
    # clay tier (-2 clay) and stone tier (-2 stone), each floored at 0.
    cs, cp = _base(house=HouseMaterial.CLAY, reed=1, stone=1)
    p = cs.players[cp]
    ctx = _renovate_ctx(p, HouseMaterial.STONE, granted_by=_PROVENANCE)
    # 2-room clay->stone = 2 stone + 1 reed; -2 stone => 1 reed.
    assert effective_payments(cs, cp, ctx) == [Resources(reed=1)]
