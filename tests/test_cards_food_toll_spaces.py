"""Forest Inn (B42) + Alchemists Lab (E81) — the FOOD-tolled for-all card
spaces and the toll raise path (ruling 86: liquidation-aware gating; the
raised toll pays the OWNER before the host's before-window; the exchange /
dynamic yield land in the `taken` delta, firing the content-based reactors).
"""
from __future__ import annotations

import agricola.cards  # noqa: F401

from agricola.actions import CommitFoodPayment, PlaceWorker, Proceed
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingFoodPayment
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_animals, with_current_player, with_majors, \
    with_resources

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))


def _edit(state, idx, **ch):
    p = fast_replace(state.players[idx], **ch)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _cards_state(card_id, owner=1):
    s, _env = setup_env(11, card_pool=POOL)
    s = with_current_player(s, 0)
    for i in (0, 1):
        s = _edit(s, i, hand_occupations=frozenset(), hand_minors=frozenset())
    p = s.players[owner]
    return _edit(s, owner, minor_improvements=p.minor_improvements | {card_id})


def _placements(state, card_id):
    return [a for a in legal_actions(state)
            if isinstance(a, PlaceWorker) and a.space == f"card:{card_id}"]


def test_forest_inn_gating_and_tiers():
    s = _cards_state("forest_inn")
    s = with_resources(s, 0, food=1, wood=4)
    assert not _placements(s, "forest_inn")        # <5 wood: no tier, no arrival
    s = with_resources(s, 0, food=0, wood=7)
    assert not _placements(s, "forest_inn")        # toll not payable (no cookables)
    s = with_resources(s, 0, food=1, wood=7)
    picks = {a.picks for a in _placements(s, "forest_inn")}
    assert picks == {(5,), (7,)}                   # affordable tiers only


def test_forest_inn_inline_toll_then_exchange():
    s = _cards_state("forest_inn")
    s = with_resources(s, 0, food=1, wood=5)
    owner_food = s.players[1].resources.food
    s = step(s, PlaceWorker(space="card:forest_inn", picks=(5,)))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.phase == "before"
    assert s.players[0].resources.food == 0        # toll paid before the window
    assert s.players[1].resources.food == owner_food + 1   # ...to the owner
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 8        # 5 in -> 8 out
    assert s.players[0].resources.food == 2        # the tier's food


def test_forest_inn_food_short_raise_pays_the_owner_then_hosts():
    """0 food + a cookable sheep: the arrival is LEGAL (ruling 82/86), the
    raise frame fires first, and its resume delivers the toll to the owner
    before the host's before-window exists."""
    s = _cards_state("forest_inn")
    s = with_resources(s, 0, food=0, wood=5)
    s = with_animals(s, 0, sheep=1)
    s = with_majors(s, owner_by_idx={0: 0})        # a Fireplace: sheep cookable
    placements = _placements(s, "forest_inn")
    assert placements                              # liquidation-aware gate
    owner_food = s.players[1].resources.food
    s = step(s, PlaceWorker(space="card:forest_inn", picks=(5,)))
    assert isinstance(s.pending_stack[-1], PendingFoodPayment)
    bundles = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    assert bundles
    s = step(s, bundles[0])                        # cook the sheep, resume
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.phase == "before"
    assert s.players[1].resources.food == owner_food + 1   # the owner got the toll
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 8


def test_alchemists_lab_dynamic_yield_fires_the_content_reactors():
    s = _cards_state("alchemists_lab")
    p0 = s.players[0]
    s = _edit(s, 0, occupations=p0.occupations,
              minor_improvements=p0.minor_improvements | {"mattock"})
    s = with_resources(s, 0, food=1, wood=2, reed=1, clay=0, stone=0)
    owner_food = s.players[1].resources.food
    s = step(s, PlaceWorker(space="card:alchemists_lab"))
    assert s.players[1].resources.food == owner_food + 1   # toll transferred
    clay_before = s.players[0].resources.clay
    s = step(s, Proceed())
    r = s.players[0].resources
    assert r.wood == 3 and r.reed == 2             # +1 of each held type
    assert r.clay == clay_before + 1               # Mattock fired on the reed
    assert r.stone == 0                            # unheld type: nothing


def test_alchemists_lab_carryability_gate():
    s = _cards_state("alchemists_lab")
    s = with_resources(s, 0, food=2, wood=0, clay=0, reed=0, stone=0)
    assert not _placements(s, "alchemists_lab")    # nothing to double: no arrival
