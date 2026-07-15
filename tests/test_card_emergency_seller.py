import agricola.cards.emergency_seller  # noqa: F401

"""Emergency Seller (occupation, E106): "When you play this card, you can
immediately turn as many building resources into food as you have people: Each
wood or clay is worth 2 food; each reed or stone is worth 3 food."

Play-variant occupation (the Roof Ballaster mechanism), full WIDE enumeration
per the user decision of 2026-07-14. Tests drive real Lessons plays.
"""
from math import comb

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.emergency_seller import _variants
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_resources

_POOL = CardPool(
    occupations=("emergency_seller", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _play_setup(seed=5, *, occupations=(), **res):
    """Drive a real Lessons play to the PendingPlayOccupation decision, with
    emergency_seller as the sole hand occupation and exactly the given resources."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=frozenset(occupations),
                     hand_occupations=frozenset({"emergency_seller"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_resources(cs, cp, **res)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs, cp


def _offered_variants(state):
    return {a.variant for a in legal_actions(state)
            if isinstance(a, CommitPlayOccupation) and a.card_id == "emergency_seller"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
    assert "emergency_seller" in OCCUPATIONS
    assert "emergency_seller" in PLAY_OCCUPATION_VARIANTS


# ---------------------------------------------------------------------------
# Variant enumeration
# ---------------------------------------------------------------------------

def test_variant_set_two_people_one_wood_one_reed():
    # 2 people, 1 wood + 1 reed on hand: exactly the multisets of size <= 2 over
    # what's held — nothing, the wood, the reed, or both.
    cs, cp = _play_setup(wood=1, reed=1)
    assert cs.players[cp].people_total == 2
    assert _offered_variants(cs) == {
        "w0c0r0s0", "w1c0r0s0", "w0c0r1s0", "w1c0r1s0",
    }


def test_people_cap_binds():
    # 2 people, 3 wood: no variant converts more than 2 total.
    cs, cp = _play_setup(wood=3)
    offered = _offered_variants(cs)
    assert "w3c0r0s0" not in offered
    assert offered == {"w0c0r0s0", "w1c0r0s0", "w2c0r0s0"}


def test_no_resources_only_zero_variant():
    # Nothing convertible on hand: the decline is still offered (never empty).
    cs, cp = _play_setup()
    assert _offered_variants(cs) == {"w0c0r0s0"}


def test_variant_count_closed_form():
    # With resources abundant (each >= people_total), the count is the number of
    # solutions of w+c+r+s <= n, i.e. C(n+4, 4). User-approved worst case: 126 at n=5.
    cs, cp = _play_setup(wood=9, clay=9, reed=9, stone=9)
    p = fast_replace(cs.players[cp], people_total=5)
    cs5 = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    variants = _variants(cs5, cp)
    assert len(variants) == comb(5 + 4, 4) == 126
    assert len({v for v, _ in variants}) == 126        # keys unique (executor dict-keys them)

    # Holdings-clipped case: 3 people, 1 wood + 2 reed -> w in {0,1}, r in {0,1,2},
    # every combination within the cap of 3 -> 6 variants.
    cs3, cp3 = _play_setup(wood=1, reed=2)
    p3 = fast_replace(cs3.players[cp3], people_total=3)
    cs3 = fast_replace(cs3, players=tuple(
        p3 if i == cp3 else cs3.players[i] for i in range(2)))
    assert len(_variants(cs3, cp3)) == 6


def test_surcharge_matches_variant():
    # The declared surcharge is exactly the converted resources.
    cs, cp = _play_setup(wood=1, stone=1)
    surcharges = dict(_variants(cs, cp))
    assert surcharges["w1c0r0s1"] == Resources(wood=1, stone=1)
    assert surcharges["w0c0r0s0"] == Resources()


# ---------------------------------------------------------------------------
# Accounting through the real play flow
# ---------------------------------------------------------------------------

def test_wood_conversion_debits_wood_grants_2_food():
    # 1st occupation (base cost 0): converting 1 wood nets +2 food, -1 wood.
    cs, cp = _play_setup(wood=1)
    cs = step(cs, CommitPlayOccupation(card_id="emergency_seller", variant="w1c0r0s0"))
    assert not any(isinstance(f, PendingFoodPayment) for f in cs.pending_stack)
    p = cs.players[cp]
    assert p.resources.wood == 0
    assert p.resources.food == 2
    assert "emergency_seller" in p.occupations
    assert "emergency_seller" not in p.hand_occupations


def test_reed_conversion_grants_3_food():
    cs, cp = _play_setup(reed=1)
    cs = step(cs, CommitPlayOccupation(card_id="emergency_seller", variant="w0c0r1s0"))
    p = cs.players[cp]
    assert p.resources.reed == 0
    assert p.resources.food == 3


def test_mixed_conversion_rates():
    # 1 wood (2) + 1 clay (2) + 1 stone (3) = 7 food at 3+ people... but people_total
    # is 2 at setup, so convert wood + stone only: 2 + 3 = 5.
    cs, cp = _play_setup(wood=1, clay=1, stone=1)
    cs = step(cs, CommitPlayOccupation(card_id="emergency_seller", variant="w1c0r0s1"))
    p = cs.players[cp]
    assert p.resources.wood == 0 and p.resources.stone == 0
    assert p.resources.clay == 1                      # unconverted, untouched
    assert p.resources.food == 5


def test_zero_variant_plays_with_no_conversion():
    cs, cp = _play_setup(wood=2)
    cs = step(cs, CommitPlayOccupation(card_id="emergency_seller", variant="w0c0r0s0"))
    p = cs.players[cp]
    assert p.resources.wood == 2
    assert p.resources.food == 0
    assert "emergency_seller" in p.occupations


def test_second_occupation_cost_nets_correctly():
    # 2nd occupation: base play cost 1 food. With 1 food + 1 wood, converting the
    # wood: debit 1 food (base) + 1 wood (surcharge), grant 2 food -> food = 2, wood = 0.
    cs, cp = _play_setup(occupations={"priest"}, food=1, wood=1)
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="emergency_seller", variant="w1c0r0s0") in la
    cs = step(cs, CommitPlayOccupation(card_id="emergency_seller", variant="w1c0r0s0"))
    assert not any(isinstance(f, PendingFoodPayment) for f in cs.pending_stack)
    p = cs.players[cp]
    assert p.resources.food == 2
    assert p.resources.wood == 0
    assert "emergency_seller" in p.occupations
