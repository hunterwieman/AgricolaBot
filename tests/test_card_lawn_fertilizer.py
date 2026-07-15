"""Tests for Lawn Fertilizer (minor improvement, D11; Dulcinaria).

Card text: "Your pastures of size 1 can hold up to 3 animals of the same type.
(With a stable, they can hold up to 6 animals of the same type.)"

A per-pasture conditioned capacity bonus (`register_pasture_capacity_per`, the
Tinsmith Master shape). Coverage: registration; fold None by default; a size-1
stable-less pasture 2->3; a size-1 pasture WITH a stable 4->6; a larger (size-2)
pasture is unaffected; the non-owner is unaffected; and the effect flows through
`extract_slots` into `can_accommodate`.
"""
import agricola.cards.lawn_fertilizer  # noqa: F401  (registers the card)

from agricola import helpers
from agricola.cards.capacity_mods import (
    PASTURE_CAPACITY_PER_MODS,
    pasture_capacity_per_list,
)
from agricola.cards.specs import MINORS
from agricola.replace import fast_replace
from agricola.setup import setup

from scripts.profile_states import _add_pasture

CARD_ID = "lawn_fertilizer"


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def test_registered():
    assert CARD_ID in MINORS
    assert any(cid == CARD_ID for cid, _fn in PASTURE_CAPACITY_PER_MODS)


def test_fold_none_by_default():
    s = setup(0)
    assert pasture_capacity_per_list(
        s.players[0], s.players[0].farmyard.pastures) is None


def test_size1_stableless_pasture_two_to_three():
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0)])                 # 1x1, 0 stables -> capacity 2
    caps0, flex0 = helpers.extract_slots(s.players[0])
    assert caps0 == [2]

    s2 = _own_minor(s, 0)
    caps1, flex1 = helpers.extract_slots(s2.players[0])
    assert caps1 == [3]                               # 2 -> 3
    assert flex1 == flex0                             # house pet unchanged
    assert helpers.can_accommodate(caps1, flex1, 4, 0, 0)   # 3 in pasture + 1 pet
    assert not helpers.can_accommodate(caps1, flex1, 5, 0, 0)


def test_size1_pasture_with_stable_four_to_six():
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0)], num_stables=1)   # 1x1 + stable -> capacity 4
    caps0, _flex0 = helpers.extract_slots(s.players[0])
    assert caps0 == [4]

    s2 = _own_minor(s, 0)
    caps1, _flex1 = helpers.extract_slots(s2.players[0])
    assert caps1 == [6]                               # 4 -> 6


def test_larger_pasture_unaffected():
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0), (0, 1)])          # 2x1, 0 stables -> capacity 4
    caps0, _f0 = helpers.extract_slots(s.players[0])
    assert caps0 == [4]

    s2 = _own_minor(s, 0)
    caps1, _f1 = helpers.extract_slots(s2.players[0])
    assert caps1 == [4]                               # size 2 -> no bonus


def test_unowned_unchanged():
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0)])
    caps, _flex = helpers.extract_slots(s.players[0])
    assert caps == [2]                                # no card -> no bonus


def test_non_owner_unaffected():
    s = setup(0)
    s = _add_pasture(s, 1, [(0, 0)])                  # opponent's size-1 pasture
    s = _own_minor(s, 0)                              # only p0 owns the card
    caps, _flex = helpers.extract_slots(s.players[1])
    assert caps == [2]                                # opponent gets no bonus
