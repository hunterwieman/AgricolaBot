"""Tests for Rock Beater (occupation, E150).

Card text: "You can use an action space providing both stone and a different building
resource even if it is occupied by another player. Stone rooms cost you 2 stone less
each."

Only the second clause is live in the 2-player engine (the first is inert — no 2-player
space provides stone + a different building resource; see the module docstring). "Stone
rooms cost 2 stone less each" is a −2-stone reduction on build_room, gated on a STONE
house (a room's material is the house's material). Verified at the `effective_payments`
chokepoint: it applies in a stone house and NOT in a clay house.
"""
import agricola.cards.rock_beater  # noqa: F401  (registers the reduction)

from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.legality import effective_payments
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup


def _state_owning(*card_ids, material=HouseMaterial.STONE):
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids),
                      house_material=material,
                      resources=Resources(wood=20, clay=20, reed=20, stone=20))
    return fast_replace(state, players=(p0, state.players[1]))


def _set(frontier):
    return set(frontier)


def test_registration():
    assert "rock_beater" in OCCUPATIONS
    assert any(cid == "rock_beater" for cid, _fn in REDUCTIONS.get("build_room", ()))


def test_stone_room_minus_two_stone():
    state = _state_owning("rock_beater", material=HouseMaterial.STONE)
    ctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=3, reed=2)}


def test_no_reduction_in_clay_house():
    # A clay room costs clay, not stone; and the gate is off (house isn't stone).
    state = _state_owning("rock_beater", material=HouseMaterial.CLAY)
    ctx = CostCtx("build_room", Resources(clay=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(clay=5, reed=2)}


def test_not_applied_without_the_card():
    state = _state_owning(material=HouseMaterial.STONE)   # nobody owns Rock Beater
    ctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=5, reed=2)}
