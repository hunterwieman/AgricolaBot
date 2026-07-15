"""Tests for Recount (minor improvement, E6; Ephipparius; traveling).

Card text: "You immediately get 1 building resource of each type of which you
have 4 or more resources in your supply already." No cost; no prereq; passing.

Coverage: registration (passing, no cost/vps); the on-play gain of +1 per
building-resource type held >= 4 (and ONLY building resources — a big grain/veg/
food stash grants nothing); the boundary at exactly 4 vs 3; real play flow +
circulation to the opponent; own-supply-only scoping.
"""
import agricola.cards.recount  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_resources
from tests.test_utils import sole_play_minor

CARD_ID = "recount"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()          # no cost
    assert spec.passing_left is True
    assert spec.vps == 0


def test_grants_one_per_building_type_at_or_above_four():
    s, _env = setup_env(0)
    # wood 4 (>=4 -> +1), clay 5 (+1), reed 3 (no), stone 4 (+1).
    s = with_resources(s, 0, wood=4, clay=5, reed=3, stone=4)
    out = MINORS[CARD_ID].on_play(s, 0)
    r = out.players[0].resources
    assert (r.wood, r.clay, r.reed, r.stone) == (5, 6, 3, 5)


def test_boundary_exactly_four_qualifies_three_does_not():
    s, _env = setup_env(0)
    s = with_resources(s, 0, wood=4, clay=3)
    out = MINORS[CARD_ID].on_play(s, 0)
    r = out.players[0].resources
    assert r.wood == 5    # 4 -> qualifies
    assert r.clay == 3    # 3 -> does not


def test_crops_and_food_never_count():
    s, _env = setup_env(0)
    # 9 grain / 9 veg / 9 food but 0 building resources -> no gain at all.
    s = with_resources(s, 0, grain=9, veg=9, food=9)
    out = MINORS[CARD_ID].on_play(s, 0)
    r0, r = s.players[0].resources, out.players[0].resources
    assert r == r0   # unchanged


def test_real_flow_gains_and_passes():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     resources=Resources(wood=4, stone=6))
    opp_p = fast_replace(cs.players[opp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp_p for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    assert p.resources.wood == 5      # 4 -> +1
    assert p.resources.stone == 7     # 6 -> +1
    assert CARD_ID not in p.minor_improvements   # traveling
    assert CARD_ID in cs.players[opp].hand_minors  # circulated


def test_scoping_reads_own_supply_only():
    s, _env = setup_env(0)
    s = with_resources(s, 0, wood=0)          # owner holds nothing
    s = with_resources(s, 1, wood=9)          # opponent is loaded
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == 0  # owner gains nothing from opp's supply
