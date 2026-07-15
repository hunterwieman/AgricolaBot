"""Tests for Cheese Fondue (minor improvement, E57; Ephipparius): "Each time you bake
at least 1 grain into bread, you get 1 additional food if you have at least 1 sheep
and (another) 1 additional food if you have at least 1 cattle." Cost 1 Clay; no
prereq; 1 VP.

A flat, animal-conditioned `before_bake_bread` automatic effect (the Dutch Windmill
shape). The reward reads the owner's ANIMAL holdings (unchanged by a bake), so it is
FLAT and fires in the BEFORE phase, per the Trigger-Timing ruling; the "at least 1
grain" is a GATE satisfied structurally by the forced CommitBake. Coverage:
registration (before, NOT after); +1/+1 stacking on sheep / cattle; the +food lands
in the PendingBakeBread before-phase (before CommitBake); no grant with neither
animal; boar does not count; not owned -> no grant.
"""
from __future__ import annotations

import agricola.cards.cheese_fondue  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitBake, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_animals, with_majors, with_resources, with_space

CARD_ID = "cheese_fondue"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own(state, idx):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _to_before_bake(cs):
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="bake_bread"))
    return cs


def _setup(*, own=True, **animals):
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})    # Fireplace (baker: 1 grain -> 2 food)
    cs = with_resources(cs, 0, grain=1)
    if animals:
        cs = with_animals(cs, 0, **animals)
    if own:
        cs = _own(cs, 0)
    return cs


# ---------------------------------------------------------------------------
# Registration — before_bake_bread, NOT after
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=1))
    assert spec.vps == 1
    before = {e.card_id for e in AUTO_EFFECTS.get("before_bake_bread", [])}
    after = {e.card_id for e in AUTO_EFFECTS.get("after_bake_bread", [])}
    assert CARD_ID in before
    assert CARD_ID not in after


# ---------------------------------------------------------------------------
# The +food lands in the BEFORE phase (before CommitBake), stacking on animals
# ---------------------------------------------------------------------------

def test_sheep_only_gives_one_food_before_bake():
    cs = _setup(sheep=1)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.food == food_before + 1   # +1 (sheep)
    # A real bake still follows (before-phase forces CommitBake).
    assert any(isinstance(a, CommitBake) for a in legal_actions(cs))
    cs = step(cs, CommitBake(grain=1))                        # Fireplace: +2 food
    assert cs.players[0].resources.food == food_before + 3
    assert cs.players[0].resources.grain == 0


def test_cattle_only_gives_one_food():
    cs = _setup(cattle=1)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert cs.players[0].resources.food == food_before + 1   # +1 (cattle)


def test_sheep_and_cattle_stack_to_two_food():
    cs = _setup(sheep=1, cattle=1)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert cs.players[0].resources.food == food_before + 2   # +1 sheep +1 cattle


def test_multiple_animals_still_cap_at_one_each():
    cs = _setup(sheep=4, cattle=3)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert cs.players[0].resources.food == food_before + 2   # "at least 1" — not per-head


# ---------------------------------------------------------------------------
# No grant with neither sheep nor cattle; boar does not count
# ---------------------------------------------------------------------------

def test_no_animals_no_food():
    cs = _setup()   # no animals
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.food == food_before   # unchanged


def test_boar_does_not_count():
    cs = _setup(boar=3)   # only boar — neither sheep nor cattle
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert cs.players[0].resources.food == food_before   # boar is not sheep/cattle


# ---------------------------------------------------------------------------
# Not owned -> no grant
# ---------------------------------------------------------------------------

def test_unowned_no_food():
    cs = _setup(sheep=1, cattle=1, own=False)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.food == food_before   # card not owned
