"""Tests for Stonecutter (occupation, A143).

Card text: "Every improvement, room, and renovation costs you 1 stone less."

A −1-stone reduction on build_major, play_minor, build_room, and renovate. Verified at
the `effective_payments` chokepoint (the real cost-resolution entry point) for each of the
four action kinds, plus the floor-at-0 behaviour on a stoneless cost.
"""
import agricola.cards.stonecutter  # noqa: F401  (registers the reductions)

from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.legality import effective_payments
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup


def _state_owning(*card_ids):
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids),
                      resources=Resources(wood=20, clay=20, reed=20, stone=20))
    return fast_replace(state, players=(p0, state.players[1]))


def _set(frontier):
    return set(frontier)


def test_registration():
    assert "stonecutter" in OCCUPATIONS
    for kind in ("build_major", "play_minor", "build_room", "renovate"):
        assert any(cid == "stonecutter" for cid, _fn in REDUCTIONS.get(kind, ()))


def test_build_major_minus_one_stone():
    state = _state_owning("stonecutter")
    ctx = CostCtx("build_major", Resources(stone=3, wood=1), major_idx=4)  # Well
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=2, wood=1)}


def test_play_minor_minus_one_stone():
    state = _state_owning("stonecutter")
    ctx = CostCtx("play_minor", Resources(stone=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=1)}


def test_build_room_minus_one_stone():
    state = _state_owning("stonecutter")
    ctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=4, reed=2)}


def test_renovate_minus_one_stone():
    state = _state_owning("stonecutter")
    ctx = CostCtx("renovate", Resources(stone=3, reed=1), to_material=HouseMaterial.STONE)
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=2, reed=1)}


def test_stoneless_cost_unaffected():
    # A cheap Fireplace (2 clay) has no stone — the reduction floors at 0, no change.
    state = _state_owning("stonecutter")
    ctx = CostCtx("build_major", Resources(clay=2), major_idx=0)
    assert _set(effective_payments(state, 0, ctx)) == {Resources(clay=2)}


def test_not_applied_without_the_card():
    state = _state_owning()   # nobody owns Stonecutter
    ctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=5, reed=2)}
