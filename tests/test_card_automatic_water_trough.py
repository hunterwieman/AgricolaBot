"""Tests for Automatic Water Trough (minor C9, traveling): "If you can
accommodate the animal, you can immediately buy 1 sheep/wild boar/cattle for
0/1/2 food." Cost 1 wood.

Surfaced WIDE via the minor play-variant seam (one CommitPlayMinor per eligible
animal + a decline variant); the accommodation gate is PERMISSIVE (a way to
house the new animal may displace/cook existing animals — user ruling
2026-07-13), and a displacing purchase resolves through a PendingAccommodate
whose min_keep filter forbids discarding the purchase itself.
"""
import agricola.cards.automatic_water_trough  # noqa: F401  (registers the card)
import agricola.cards.milking_place  # noqa: F401  (the house-pet negation, for the gate test)

from agricola.actions import CommitAccommodate, CommitPlayMinor
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_pending_stack

CARD_ID = "automatic_water_trough"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _at_play_minor_frame(res, *, animals=Animals(), extra_minors=()):
    """A CARDS state at a PendingPlayMinor with the card in the current
    player's hand, `res` resources, and `animals` on their (fresh) farm."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}),
                     resources=res, animals=animals,
                     minor_improvements=state.players[cp].minor_improvements
                     | set(extra_minors))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp,
                                 initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _variants_offered(state):
    return sorted(a.variant for a in legal_actions(state)
                  if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)


def _commit(state, variant):
    return next(a for a in legal_actions(state)
                if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.passing_left is True
    assert spec.vps == 0
    assert CARD_ID in PLAY_MINOR_VARIANTS


# ---------------------------------------------------------------------------
# The wide variants: decline always; animals gated by food + accommodation
# ---------------------------------------------------------------------------

def test_all_variants_offered_with_food_and_room():
    # Fresh farm (house-pet slot open) + 2 food: every animal is housable and
    # affordable (sheep 0 / boar 1 / cattle 2 food surcharges).
    state, _cp = _at_play_minor_frame(Resources(wood=1, food=2))
    assert _variants_offered(state) == ["boar", "cattle", "decline", "sheep"]


def test_food_prices_gate_the_variants():
    # 1 wood, no food, nothing liquidatable: only the 0-food sheep (+ decline).
    state, _cp = _at_play_minor_frame(Resources(wood=1))
    assert _variants_offered(state) == ["decline", "sheep"]
    # 1 food: boar becomes payable, cattle still not.
    state, _cp = _at_play_minor_frame(Resources(wood=1, food=1))
    assert _variants_offered(state) == ["boar", "decline", "sheep"]


def test_accommodation_gate_blocks_all_purchases():
    # Milking Place negates the house-pet slot; with no pastures/stables there
    # is NO way to house any animal -> only decline survives the gate.
    state, _cp = _at_play_minor_frame(Resources(wood=1, food=2),
                                      extra_minors=("milking_place",))
    assert _variants_offered(state) == ["decline"]


# ---------------------------------------------------------------------------
# Resolving a purchase
# ---------------------------------------------------------------------------

def test_buy_sheep_that_fits_no_frame():
    state, cp = _at_play_minor_frame(Resources(wood=1, food=2))
    out = step(state, _commit(state, "sheep"))
    p = out.players[cp]
    assert p.animals.sheep == 1
    assert p.resources.food == 2                 # sheep costs 0 food
    assert p.resources.wood == 0                 # the card's 1-wood cost
    assert CARD_ID in out.players[1 - cp].hand_minors   # traveled to opponent
    assert not any(isinstance(f, PendingAccommodate) for f in out.pending_stack)


def test_cattle_surcharge_debited():
    state, cp = _at_play_minor_frame(Resources(wood=1, food=2))
    out = step(state, _commit(state, "cattle"))
    p = out.players[cp]
    assert p.animals.cattle == 1
    assert p.resources.food == 0                 # 2-food surcharge paid
    assert p.resources.wood == 0


def test_decline_buys_nothing():
    state, cp = _at_play_minor_frame(Resources(wood=1, food=2))
    out = step(state, _commit(state, "decline"))
    p = out.players[cp]
    assert p.animals == Animals()
    assert p.resources.food == 2                 # no surcharge
    assert CARD_ID in out.players[1 - cp].hand_minors


# ---------------------------------------------------------------------------
# The min_keep-filtered accommodation on displacement
# ---------------------------------------------------------------------------

def test_displacing_buy_offers_only_configs_keeping_the_purchase():
    # A pet boar occupies the only slot; buying a sheep must displace it. The
    # filtered frame offers keep-the-sheep configs ONLY — never a config that
    # keeps the boar by discarding the purchased sheep.
    state, cp = _at_play_minor_frame(Resources(wood=1, food=2),
                                     animals=Animals(boar=1))
    out = step(state, _commit(state, "sheep"))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingAccommodate)
    assert top.min_keep == Animals(sheep=1)
    options = [a for a in legal_actions(out) if isinstance(a, CommitAccommodate)]
    assert options
    assert all(a.sheep >= 1 for a in options)
    resolved = step(out, options[0])
    p = resolved.players[cp]
    assert p.animals.sheep == 1 and p.animals.boar == 0
    assert not any(isinstance(f, PendingAccommodate)
                   for f in resolved.pending_stack)


def test_cook_one_buy_replacement_with_fireplace():
    # At sheep capacity (1 pet sheep, no pastures) with a Fireplace: buying a
    # sheep for 0 food surfaces the keep-1-sheep config, cooking the displaced
    # sheep for 2 food — the user-confirmed legitimate "cook 1, buy 1" play.
    state, cp = _at_play_minor_frame(Resources(wood=1),
                                     animals=Animals(sheep=1))
    state = with_majors(state, owner_by_idx={0: cp})   # Fireplace (idx 0)
    out = step(state, _commit(state, "sheep"))
    assert isinstance(out.pending_stack[-1], PendingAccommodate)
    (option,) = [a for a in legal_actions(out) if isinstance(a, CommitAccommodate)]
    assert option.sheep == 1
    resolved = step(out, option)
    p = resolved.players[cp]
    assert p.animals.sheep == 1
    assert p.resources.food == 2                 # the cooked displaced sheep
