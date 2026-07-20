import agricola.cards.sleight_of_hand  # noqa: F401  -- registers the card

"""Tests for Sleight of Hand (minor improvement, E78; Ephipparius Expansion).

Card text: "When you play this card, you can immediately exchange up to 4 building
resources for an equal number of other building resources." Clarifications: "It
is a single exchange. You can't trade wood-for-wood, for example."

The on-play exchange surfaces WIDE (user ruling 2026-07-20, the Facades Carving
idiom): one CommitPlayMinor per canonical (give, get) exchange plus an
always-present zero-surcharge decline route ("none"). A canonical exchange is a
(give-multiset, get-multiset) pair over {wood, clay, reed, stone} with
|give| = |get| = k in 1..4, GIVE bounded by current holdings, and DISJOINT type
support (no type on both sides). The GIVE side folds into the play payment as a
surcharge; the GET side is granted by the 3-arg on_play. Cost is empty, so the
play payment IS the give side. Prereq: 3 Occupations (a HAVE-check). Tests drive
the real PendingPlayMinor frame through legal_actions / step.
"""
import json
from pathlib import Path

import agricola.cards.social_benefits  # noqa: F401  -- ordinary-minor control

from agricola.actions import CommitPlayMinor
from agricola.cards.social_benefits import CARD_ID as SOCIAL_BENEFITS
from agricola.cards.sleight_of_hand import (
    BUILDING_RESOURCES,
    CARD_ID,
    DECLINE,
    _parse_side,
    _variants,
)
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env

from tests.factories import with_pending_stack, with_resources, with_round

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, SOCIAL_BENEFITS) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Sleight of Hand")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _at_play_minor_frame(round_number=1, hand=(CARD_ID,), n_occ=3, **res):
    """A prefabricated state at a PendingPlayMinor frame for the current player,
    holding `hand`, `n_occ` occupations (default 3 -> prereq met), and exactly the
    given resources (others zero)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(
        state.players[cp],
        hand_minors=frozenset(hand),
        occupations=frozenset(f"o{i}" for i in range(n_occ)),
    )
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_round(state, round_number)
    # with_resources replaces the resource vector but keeps occupations intact.
    state = with_resources(state, cp, **res)
    state = with_pending_stack(
        state,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state, cid=CARD_ID):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == cid]


def _variants_offered(state, cid=CARD_ID):
    return {a.variant for a in _plays(state, cid)}


def _sides(variant):
    """(give-dict, get-dict) for an exchange variant string."""
    give_s, _, get_s = variant.partition(">")
    return _parse_side(give_s), _parse_side(get_s)


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the catalog row this module encodes (cost / prereq / text verbatim)."""
    assert _ROW["cost"] is None                       # no cost
    assert _ROW["prerequisites"] == "3 Occupations"
    assert _ROW["text"] == (
        "When you play this card, you can immediately exchange up to 4 building "
        "resources for an equal number of other building resources.")
    assert _ROW["vps"] is None
    assert _ROW["passing_left"] is None
    # The module docstring quotes the printed text verbatim (line-wrapped).
    import agricola.cards.sleight_of_hand as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                        # no cost
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.min_occupations == 3                  # "3 Occupations"
    assert spec.max_occupations is None
    assert spec.prereq is None                        # occupation-count only
    assert spec.vps == 0
    assert spec.passing_left is False
    assert CARD_ID in PLAY_MINOR_VARIANTS             # the wide on-play choice


# ---------------------------------------------------------------------------
# Prerequisite: 3 Occupations
# ---------------------------------------------------------------------------

def test_prereq_occupation_boundary():
    spec = MINORS[CARD_ID]
    below, cp = _at_play_minor_frame(n_occ=2, wood=4)
    assert not prereq_met(spec, below, cp)            # 2 occupations: no
    at, cp = _at_play_minor_frame(n_occ=3, wood=4)
    assert prereq_met(spec, at, cp)                   # 3 occupations: yes


def test_prereq_gates_the_real_frame():
    """2 occupations -> not offered at all; 3 -> it is."""
    state, cp = _at_play_minor_frame(n_occ=2, wood=4)
    assert CARD_ID not in playable_minors(state, cp)
    assert not _plays(state)
    state, cp = _at_play_minor_frame(n_occ=3, wood=4)
    assert CARD_ID in playable_minors(state, cp)
    assert _plays(state)


# ---------------------------------------------------------------------------
# Variant enumeration: disjoint support, size bounds, holdings bound
# ---------------------------------------------------------------------------

def test_decline_always_present():
    """The zero-surcharge decline route is always in the list, even with no
    building resources."""
    state, cp = _at_play_minor_frame()                # all resources zero
    variants = _variants(state, cp)
    assert (DECLINE, Resources()) in variants


def test_no_building_resources_only_decline():
    """A player holding no building resource is offered only the decline route."""
    state, cp = _at_play_minor_frame(food=9, grain=9, veg=9)  # nothing tradeable
    assert _variants_offered(state) == {DECLINE}
    plays = _plays(state)
    assert len(plays) == 1
    assert plays[0].variant == DECLINE
    assert plays[0].payment == Resources()            # decline has no surcharge


def test_no_variant_has_a_type_on_both_sides():
    """Disjoint support: give and get never share a resource type; sizes match."""
    state, cp = _at_play_minor_frame(wood=4, clay=4, reed=4, stone=4)
    for v, _surcharge in _variants(state, cp):
        if v == DECLINE:
            continue
        give, get = _sides(v)
        assert set(give) & set(get) == set(), v      # disjoint support
        assert sum(give.values()) == sum(get.values()), v   # |give| == |get|


def test_k_capped_at_four_even_with_large_holdings():
    """No exchange ever moves more than 4 resources per side, however much is
    held."""
    state, cp = _at_play_minor_frame(wood=9, clay=9, reed=9, stone=9)
    for v, surcharge in _variants(state, cp):
        if v == DECLINE:
            continue
        give, get = _sides(v)
        assert 1 <= sum(give.values()) <= 4, v
        assert 1 <= sum(get.values()) <= 4, v
        # The surcharge equals the give side.
        assert surcharge == Resources(**give), v


def test_surcharge_equals_give_side():
    """Each exchange's surcharge is exactly its give multiset (building resources
    only, no food)."""
    state, cp = _at_play_minor_frame(wood=3, clay=2)
    for v, surcharge in _variants(state, cp):
        if v == DECLINE:
            continue
        give, _get = _sides(v)
        assert surcharge == Resources(**give), v
        assert surcharge.food == 0


def test_give_bounded_by_holdings():
    """A player with 1 wood (and nothing else) is never offered a give of 2 wood,
    and can only ever give 1 wood -> 1 of {clay, reed, stone}."""
    state, cp = _at_play_minor_frame(wood=1)
    offered = _variants_offered(state)
    assert offered == {DECLINE, "w1>c1", "w1>r1", "w1>s1"}
    for v, _s in _variants(state, cp):
        if v == DECLINE:
            continue
        give, _get = _sides(v)
        assert give.get("wood", 0) <= 1, v


def test_give_bounded_multi_type_holdings():
    """With wood=2, clay=1 the give side never exceeds holdings on any type."""
    state, cp = _at_play_minor_frame(wood=2, clay=1)
    for v, _s in _variants(state, cp):
        if v == DECLINE:
            continue
        give, _get = _sides(v)
        assert give.get("wood", 0) <= 2, v
        assert give.get("clay", 0) <= 1, v
        assert give.get("reed", 0) == 0, v            # holds no reed
        assert give.get("stone", 0) == 0, v           # holds no stone


def test_full_enumeration_count_under_large_holdings():
    """Holdings >= 4 of every type make the give side unbounded within k, giving
    the full canonical enumeration: 308 exchanges + 1 decline (user ruling
    2026-07-20 accepts ~300)."""
    state, cp = _at_play_minor_frame(wood=4, clay=4, reed=4, stone=4)
    variants = _variants(state, cp)
    assert len(variants) == 309
    strings = [v for v, _s in variants]
    assert strings.count(DECLINE) == 1
    assert len(set(strings)) == len(strings)          # no duplicate variant strings


# ---------------------------------------------------------------------------
# Determinism / stable ordering
# ---------------------------------------------------------------------------

def test_deterministic_and_sorted():
    state, cp = _at_play_minor_frame(wood=4, clay=4, reed=4, stone=4)
    first = _variants(state, cp)
    second = _variants(state, cp)
    assert first == second                            # deterministic across calls
    strings = [v for v, _s in first]
    assert strings == sorted(strings)                 # stably ordered by string


# ---------------------------------------------------------------------------
# End-to-end play: a real multi-resource exchange debits give and grants get
# ---------------------------------------------------------------------------

def test_commit_multi_resource_exchange():
    """give 2 wood + 1 clay, get 3 reed: after the play, -2 wood / -1 clay / +3
    reed, card moved to the tableau."""
    state, cp = _at_play_minor_frame(wood=3, clay=2, reed=0, stone=0)
    (act,) = [a for a in _plays(state) if a.variant == "w2c1>r3"]
    assert act.payment == Resources(wood=2, clay=1)   # surcharge folded, no card cost
    state = step(state, act)
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert CARD_ID not in p.hand_minors
    assert p.resources.wood == 1                       # 3 - 2 given
    assert p.resources.clay == 1                       # 2 - 1 given
    assert p.resources.reed == 3                       # +3 received
    assert p.resources.stone == 0


def test_commit_single_exchange_conserves_count():
    """A 1-for-1 swap: -1 wood, +1 stone; total building-resource count unchanged."""
    state, cp = _at_play_minor_frame(wood=1, clay=1)
    before = state.players[cp].resources
    (act,) = [a for a in _plays(state) if a.variant == "w1>s1"]
    state = step(state, act)
    r = state.players[cp].resources
    assert r.wood == before.wood - 1
    assert r.stone == before.stone + 1
    assert r.clay == before.clay                       # untouched
    total_before = sum(getattr(before, t) for t in BUILDING_RESOURCES)
    total_after = sum(getattr(r, t) for t in BUILDING_RESOURCES)
    assert total_after == total_before                 # equal-number exchange


def test_commit_decline_changes_nothing():
    """Playing via the decline route moves the card to the tableau with no
    resource change."""
    state, cp = _at_play_minor_frame(wood=2, clay=1)
    before = state.players[cp].resources
    (act,) = [a for a in _plays(state) if a.variant == DECLINE]
    state = step(state, act)
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert CARD_ID not in p.hand_minors
    assert p.resources == before                       # nothing exchanged


# ---------------------------------------------------------------------------
# The seam does not widen ordinary minors
# ---------------------------------------------------------------------------

def test_ordinary_minor_unaffected():
    """Social Benefits (no variants_fn): exactly one play, variant=None. (Its
    prereq is 'At Most 1 Occupation', so n_occ=1 here.)"""
    state, _cp = _at_play_minor_frame(hand=(SOCIAL_BENEFITS,), n_occ=1, reed=1)
    plays = _plays(state, SOCIAL_BENEFITS)
    assert len(plays) == 1
    assert plays[0].variant is None
