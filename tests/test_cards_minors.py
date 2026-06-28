"""Tests for the minor-play machinery (CARD_IMPLEMENTATION_PLAN.md II.4):
PendingPlayMinor, CommitPlayMinor / Stop, the MinorSpec / MINORS registry,
prereq_met (occupation-count fields + custom predicate), Cost affordability,
the passing-minor circulation, and the first minor (Market Stall).

The in-game entry points (Meeting Place / the improvement-space minor branches)
land next, so these drive PendingPlayMinor by pushing it onto the stack directly
(the established factory pattern for testing pendings).
"""
import pytest

from agricola.cards.specs import MINORS, MinorSpec, prereq_met, register_minor
from agricola.engine import step
from agricola.legality import _can_afford_cost, legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, cp_minors=frozenset(), cp_res=None, cp_occ=frozenset()):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {"hand_minors": cp_minors, "occupations": cp_occ}
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


@pytest.fixture
def kept_minor():
    """A throwaway NON-passing minor registered for the test, removed after.

    Lets us exercise the keep-in-tableau branch (and a wood cost) without a real
    non-passing minor card yet. Tests run serially; the fixture cleans up MINORS.
    """
    cid = "_test_kept_minor"
    register_minor(cid, cost=Cost(resources=Resources(wood=1)),
                   on_play=lambda s, i: s)
    yield cid
    del MINORS[cid]


# ---------------------------------------------------------------------------
# Registry + prerequisite logic
# ---------------------------------------------------------------------------

def test_market_stall_registered():
    assert "market_stall" in MINORS
    assert MINORS["market_stall"].passing_left is True


def test_prereq_met_occupation_bounds_and_custom():
    cs, cp = _card_state(cp_occ=frozenset({"a", "b"}))  # 2 occupations
    assert prereq_met(MinorSpec("x", min_occupations=2), cs, cp)
    assert not prereq_met(MinorSpec("x", min_occupations=3), cs, cp)
    assert prereq_met(MinorSpec("x", max_occupations=2), cs, cp)       # <=2 ok
    assert not prereq_met(MinorSpec("x", max_occupations=1), cs, cp)   # at most 1 -> no
    assert prereq_met(MinorSpec("x", min_occupations=2, max_occupations=2), cs, cp)  # exactly 2
    # "No occupations" (max 0) with 2 played -> false; with 0 -> true.
    cs0, cp0 = _card_state(cp_occ=frozenset())
    assert prereq_met(MinorSpec("x", max_occupations=0), cs0, cp0)
    assert not prereq_met(MinorSpec("x", max_occupations=0), cs, cp)
    # Custom predicate is AND-ed in.
    rich = MinorSpec("x", prereq=lambda s, i: s.players[i].resources.wood >= 5)
    assert not prereq_met(rich, cs, cp)


def test_can_afford_cost_resources_and_animals():
    cs, cp = _card_state(cp_res=Resources(grain=1))
    p = cs.players[cp]
    assert _can_afford_cost(p, Cost(resources=Resources(grain=1)))
    assert not _can_afford_cost(p, Cost(resources=Resources(grain=2)))
    assert not _can_afford_cost(p, Cost(animals=Animals(sheep=1)))      # has no sheep
    p2 = fast_replace(p, animals=Animals(sheep=2))
    assert _can_afford_cost(p2, Cost(animals=Animals(sheep=1)))


# ---------------------------------------------------------------------------
# playable_minors + enumeration
# ---------------------------------------------------------------------------

def test_playable_minors_filters_registered_affordable():
    # Has market_stall + grain -> playable.
    cs, cp = _card_state(cp_minors=frozenset({"market_stall"}), cp_res=Resources(grain=1))
    assert playable_minors(cs, cp) == ["market_stall"]
    # No grain -> cost unaffordable -> not playable.
    cs, cp = _card_state(cp_minors=frozenset({"market_stall"}), cp_res=Resources(grain=0))
    assert playable_minors(cs, cp) == []
    # Unregistered hand card -> not playable.
    cs, cp = _card_state(cp_minors=frozenset({"m3"}), cp_res=Resources(grain=5))
    assert playable_minors(cs, cp) == []


def test_enumerator_offers_plays_only():
    cs, cp = _card_state(cp_minors=frozenset({"market_stall"}), cp_res=Resources(grain=1))
    cs = _push_minor(cs, cp)
    # PendingPlayMinor plays exactly one minor — no Stop here. The skip (where
    # allowed) is the PARENT frame's Stop, not this frame's.
    assert legal_actions(cs) == [sole_play_minor(cs, "market_stall")]


# ---------------------------------------------------------------------------
# Playing a passing minor (Market Stall)
# ---------------------------------------------------------------------------

def test_play_market_stall_passes_to_opponent():
    cs, cp = _card_state(cp_minors=frozenset({"market_stall"}), cp_res=Resources(grain=2))
    opp = 1 - cp
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    p = cs.players[cp]
    assert p.resources.grain == 1 and p.resources.veg == 1     # paid 1 grain, gained 1 veg
    assert "market_stall" not in p.minor_improvements          # passing -> not kept
    assert "market_stall" not in p.hand_minors                 # left my hand
    assert "market_stall" in cs.players[opp].hand_minors       # circulated to opponent


# (Declining a minor is a parent-level Stop, not a PendingPlayMinor action — it
# is exercised by the optional entry points, e.g. Meeting Place, when they land.)


# ---------------------------------------------------------------------------
# Playing a non-passing minor (kept in tableau)
# ---------------------------------------------------------------------------

def test_play_non_passing_minor_kept_in_tableau(kept_minor):
    cs, cp = _card_state(cp_minors=frozenset({kept_minor}), cp_res=Resources(wood=2))
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, kept_minor))
    p = cs.players[cp]
    assert kept_minor in p.minor_improvements                  # kept
    assert kept_minor not in p.hand_minors                     # left hand
    assert p.resources.wood == 1                               # paid 1 wood
