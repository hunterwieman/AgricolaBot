"""Tests for Chimney Sweep (occupation, D154).

Card text: "Renovating to stone costs you 2 stone less. During scoring, you get 1 bonus
point for each other player living in a stone house."

- A −2-stone reduction on renovate, gated on the renovation target being STONE
  (`ctx.to_material`). Verified at the `effective_payments` chokepoint.
- A scoring term: +1 per OTHER player in a stone house. Verified via the registered
  scoring fn AND through the real `score` entry point (ownership-gated).
"""
import agricola.cards.chimney_sweep  # noqa: F401  (registers the reduction + scoring)

from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.legality import effective_payments
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from tests.factories import with_house


def _state_owning(*card_ids):
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids),
                      resources=Resources(wood=20, clay=20, reed=20, stone=20))
    return fast_replace(state, players=(p0, state.players[1]))


def _set(frontier):
    return set(frontier)


def _chimney_score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == "chimney_sweep")


def test_registration():
    assert "chimney_sweep" in OCCUPATIONS
    assert any(cid == "chimney_sweep" for cid, _fn in REDUCTIONS.get("renovate", ()))
    assert any(cid == "chimney_sweep" for cid, _fn in SCORING_TERMS)


def test_renovate_to_stone_minus_two_stone():
    state = _state_owning("chimney_sweep")
    ctx = CostCtx("renovate", Resources(stone=3, reed=1), to_material=HouseMaterial.STONE)
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=1, reed=1)}


def test_renovate_to_clay_unaffected():
    # "Renovating to stone" only — a wood->clay renovate is not discounted.
    state = _state_owning("chimney_sweep")
    ctx = CostCtx("renovate", Resources(clay=3, reed=1), to_material=HouseMaterial.CLAY)
    assert _set(effective_payments(state, 0, ctx)) == {Resources(clay=3, reed=1)}


def test_scoring_counts_opponent_in_stone_house():
    fn = _chimney_score_fn()
    state = _state_owning("chimney_sweep")
    # Opponent NOT in a stone house -> 0.
    assert fn(with_house(state, 1, HouseMaterial.CLAY), 0) == 0
    # Opponent in a stone house -> +1.
    assert fn(with_house(state, 1, HouseMaterial.STONE), 0) == 1


def test_scoring_wired_into_score_and_gated_on_ownership():
    base = with_house(setup(0), 1, HouseMaterial.STONE)   # opponent in a stone house
    owner = fast_replace(base, players=(
        fast_replace(base.players[0], occupations=frozenset({"chimney_sweep"})),
        base.players[1]))
    # The only difference is owning Chimney Sweep -> exactly +1 for player 0.
    assert score(owner, 0)[0] - score(base, 0)[0] == 1
