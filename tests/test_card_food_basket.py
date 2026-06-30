"""Tests for Food Basket (minor improvement, A8; Artifex; traveling).

Card text: "You immediately get 1 grain and 1 vegetable." Cost 1 reed; prereq
"2 Occupations and 2 Improvements" (improvements = minors + owned majors);
traveling (passed to the opponent after the on-play effect).
"""
import agricola.cards.food_basket  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS, MinorSpec, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("food_basket",) + tuple(f"m{i}" for i in range(20)),
)


def _state(
    seed=5,
    *,
    cp_minors=frozenset(),
    cp_res=None,
    cp_occ=frozenset(),
    extra_minors=frozenset(),
    own_majors=(),
):
    """A 2-player card state with the current player's hand/occupations/resources
    set, and (optionally) some already-played minors / owned majors for the
    prerequisite checks."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {
        "hand_minors": cp_minors,
        "occupations": cp_occ,
        "minor_improvements": extra_minors,
    }
    if cp_res is not None:
        changes["resources"] = cp_res
    p = fast_replace(p, **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    if own_majors:
        cs = with_majors(cs, owner_by_idx={m: cp for m in own_majors})
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "food_basket" in MINORS
    spec = MINORS["food_basket"]
    assert spec.passing_left is True
    assert spec.min_occupations == 2
    assert spec.cost.resources == Resources(reed=1)
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Prerequisite: 2 occupations AND 2 improvements (minors + majors)
# ---------------------------------------------------------------------------

def test_prereq_needs_two_occupations():
    spec = MINORS["food_basket"]
    # 2 improvements (minors) but only 1 occupation -> fails on the occupation bound.
    cs, cp = _state(cp_occ=frozenset({"a"}), extra_minors=frozenset({"m1", "m2"}))
    assert not prereq_met(spec, cs, cp)
    # 2 occupations + 2 minors -> met.
    cs, cp = _state(cp_occ=frozenset({"a", "b"}), extra_minors=frozenset({"m1", "m2"}))
    assert prereq_met(spec, cs, cp)


def test_prereq_needs_two_improvements():
    spec = MINORS["food_basket"]
    # 2 occupations but 0 improvements -> fails the custom predicate.
    cs, cp = _state(cp_occ=frozenset({"a", "b"}))
    assert not prereq_met(spec, cs, cp)
    # 2 occupations + only 1 improvement -> still fails.
    cs, cp = _state(cp_occ=frozenset({"a", "b"}), extra_minors=frozenset({"m1"}))
    assert not prereq_met(spec, cs, cp)


def test_prereq_counts_minors_and_majors_together():
    spec = MINORS["food_basket"]
    # 1 minor + 1 owned major = 2 improvements; with 2 occupations -> met.
    cs, cp = _state(
        cp_occ=frozenset({"a", "b"}),
        extra_minors=frozenset({"m1"}),
        own_majors=(0,),  # owns a Fireplace
    )
    assert prereq_met(spec, cs, cp)
    # 2 owned majors (no minors) + 2 occupations -> also met.
    cs, cp = _state(cp_occ=frozenset({"a", "b"}), own_majors=(0, 2))
    assert prereq_met(spec, cs, cp)


def test_prereq_ignores_opponent_majors():
    spec = MINORS["food_basket"]
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    p = fast_replace(cs.players[cp], occupations=frozenset({"a", "b"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    # Opponent owns two majors; the current player owns none -> prereq fails.
    cs = with_majors(cs, owner_by_idx={0: opp, 2: opp})
    assert not prereq_met(spec, cs, cp)


# ---------------------------------------------------------------------------
# playable_minors gates on prereq + cost (real legality path)
# ---------------------------------------------------------------------------

def test_playable_only_when_prereq_and_cost_met():
    # Holds the card, has reed, 2 occupations + 2 improvements -> playable.
    cs, cp = _state(
        cp_minors=frozenset({"food_basket"}),
        cp_res=Resources(reed=1),
        cp_occ=frozenset({"a", "b"}),
        extra_minors=frozenset({"m1", "m2"}),
    )
    assert playable_minors(cs, cp) == ["food_basket"]
    # No reed -> cost unaffordable.
    cs, cp = _state(
        cp_minors=frozenset({"food_basket"}),
        cp_res=Resources(reed=0),
        cp_occ=frozenset({"a", "b"}),
        extra_minors=frozenset({"m1", "m2"}),
    )
    assert playable_minors(cs, cp) == []
    # Prereq unmet (only 1 occupation) -> not playable even with reed + improvements.
    cs, cp = _state(
        cp_minors=frozenset({"food_basket"}),
        cp_res=Resources(reed=1),
        cp_occ=frozenset({"a"}),
        extra_minors=frozenset({"m1", "m2"}),
    )
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play effect via a real engine flow + passing circulation
# ---------------------------------------------------------------------------

def test_play_grants_grain_and_veg_then_passes():
    cs, cp = _state(
        cp_minors=frozenset({"food_basket"}),
        cp_res=Resources(reed=2),
        cp_occ=frozenset({"a", "b"}),
        extra_minors=frozenset({"m1", "m2"}),
    )
    opp = 1 - cp
    grain0 = cs.players[cp].resources.grain
    veg0 = cs.players[cp].resources.veg
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, "food_basket")]
    cs = step(cs, sole_play_minor(cs, "food_basket"))

    p = cs.players[cp]
    assert p.resources.grain == grain0 + 1          # +1 grain
    assert p.resources.veg == veg0 + 1              # +1 veg
    assert p.resources.reed == 1                    # paid 1 of the 2 reed
    assert "food_basket" not in p.minor_improvements  # traveling -> not kept
    assert "food_basket" not in p.hand_minors         # left my hand
    assert "food_basket" in cs.players[opp].hand_minors  # circulated to opponent


def test_prereq_does_not_count_self():
    # The prereq is evaluated before the card is played, so a player exactly at
    # the threshold (2 occ + 2 other improvements) qualifies — Food Basket itself
    # is in hand, not yet an improvement.
    spec = MinorSpec(
        "food_basket",
        min_occupations=MINORS["food_basket"].min_occupations,
        prereq=MINORS["food_basket"].prereq,
    )
    cs, cp = _state(
        cp_minors=frozenset({"food_basket"}),
        cp_occ=frozenset({"a", "b"}),
        extra_minors=frozenset({"m1", "m2"}),
    )
    assert prereq_met(spec, cs, cp)
