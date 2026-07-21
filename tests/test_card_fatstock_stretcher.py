"""Tests for Fatstock Stretcher (minor D56): "Each time you turn a sheep or
wild boar into food using a cooking improvement, you get 1 additional food."

Implemented as +1 to the sheep/boar cooking rates, only where the base
conversion exists (user ruling 2026-07-21) — see the card module docstring.
"""
import agricola.cards.fatstock_stretcher  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import CommitConvert
from agricola.cards.cooking_mods import COOKING_RATE_BONUSES
from agricola.cards.fatstock_stretcher import CARD_ID
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.helpers import cooking_rates
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup

from tests.factories import (
    with_animals,
    with_majors,
    with_people,
    with_phase,
    with_resources,
)


def _own(state, idx=0, *, in_hand=False):
    """Give player `idx` the card — played (default) or merely in hand."""
    p = state.players[idx]
    if in_hand:
        p = fast_replace(p, hand_minors=p.hand_minors | {CARD_ID})
    else:
        p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.prereq is None
    assert CARD_ID in COOKING_RATE_BONUSES


# --- Unit: cooking_rates with the card owned --------------------------------

def test_fireplace_rates_boosted():
    # Fireplace base (2, 2, 3, 2) -> (3, 3, 3, 2): sheep and boar +1, no more.
    s = with_majors(_own(setup(0)), owner_by_idx={0: 0})
    assert cooking_rates(s, 0) == (3, 3, 3, 2)


def test_cooking_hearth_rates_boosted():
    # Cooking Hearth base (2, 3, 4, 3) -> (3, 4, 4, 3).
    s = with_majors(_own(setup(0)), owner_by_idx={2: 0})
    assert cooking_rates(s, 0) == (3, 4, 4, 3)


def test_no_improvement_no_bonus():
    # Base (0, 0, 0, 1) stays (0, 0, 0, 1): no conversion exists, no bonus
    # (user ruling 2026-07-21 — no improvement means no cook).
    s = _own(setup(0))
    assert cooking_rates(s, 0) == (0, 0, 0, 1)


def test_card_in_hand_changes_nothing():
    # In hand, not played: Fireplace rates stay at base.
    s = with_majors(_own(setup(0), in_hand=True), owner_by_idx={0: 0})
    assert cooking_rates(s, 0) == (2, 2, 3, 2)


def test_opponent_rates_unchanged():
    # P0 owns the card + a Fireplace; P1 owns the other Fireplace. Only P0's
    # rates are boosted.
    s = with_majors(_own(setup(0), 0), owner_by_idx={0: 0, 1: 1})
    assert cooking_rates(s, 0) == (3, 3, 3, 2)
    assert cooking_rates(s, 1) == (2, 2, 3, 2)


# --- Integration: harvest feeding cooks a boar at the boosted rate ----------

def _feed_state(*, with_card):
    """P0: 1 adult (need=2), 0 food, 1 boar, a Fireplace; at the feed phase."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if with_card:
        state = _own(state, 0)
    state = with_majors(state, owner_by_idx={0: 0})           # Fireplace
    state = with_people(state, 0, total=1, home=1, newborns=0)  # need=2
    state = with_resources(state, 0, food=0)
    state = with_animals(state, 0, boar=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def test_feed_cook_boar_yields_boosted_food():
    # With the card, the Fireplace boar-cook is worth 3 (2 + 1): cooking the
    # boar pays the need of 2 and banks 1 surplus food.
    state = step(_feed_state(with_card=True),
                 CommitConvert(grain=0, veg=0, sheep=0, boar=1, cattle=0))
    p = state.players[0]
    assert p.animals.boar == 0
    assert p.begging_markers == 0
    assert p.resources.food == 1        # 3 produced - 2 paid


def test_feed_cook_boar_base_rate_without_card():
    # Control: without the card the same cook produces exactly 2 — no surplus.
    state = step(_feed_state(with_card=False),
                 CommitConvert(grain=0, veg=0, sheep=0, boar=1, cattle=0))
    p = state.players[0]
    assert p.animals.boar == 0
    assert p.begging_markers == 0
    assert p.resources.food == 0        # 2 produced - 2 paid
