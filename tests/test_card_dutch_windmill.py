"""Tests for Dutch Windmill (minor A63): "Each time you take a 'Bake Bread'
action in a round immediately following a harvest, you get 3 additional food."
Cost 2 wood + 2 stone, 2 VP.

Modeled as a mandatory, choice-free `before_bake_bread` automatic effect
(register_auto). The reward is a FLAT +3 food, so per the Trigger-Timing ruling
("each time you take a 'Bake Bread' action" fires in the before-phase; the after
phase is only for outcome-dependent rewards) it lands at the PendingBakeBread
push, BEFORE CommitBake. "Immediately following a harvest" is a ROUND gate, not a
timing cue: the food is granted only in the rounds {5, 8, 10, 12, 14}. No
stranding guard is needed — the effect only ADDS food, consuming nothing the
mandatory bake needs.

Covers: registration on `before_bake_bread`; the +3 food landing in the
PendingBakeBread before-phase (before CommitBake) in a post-harvest round; no
grant in a non-post-harvest round; no grant when the card is not owned.
"""
from __future__ import annotations

import agricola.cards.dutch_windmill  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitBake, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_resources, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("dutch_windmill",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, round_number=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0, round_number=round_number)
    # Drop both hands so nothing else is deterministically playable.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _to_before_bake(cs):
    """Place at Grain Utilization and choose bake_bread -> PendingBakeBread before-phase."""
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="bake_bread"))
    return cs


# ---------------------------------------------------------------------------
# Registration — the fix: before_bake_bread, not after_bake_bread
# ---------------------------------------------------------------------------

def test_dutch_windmill_registered():
    assert "dutch_windmill" in MINORS
    spec = MINORS["dutch_windmill"]
    assert spec.cost == Cost(resources=Resources(wood=2, stone=2))
    assert spec.vps == 2
    before = {e.card_id for e in AUTO_EFFECTS.get("before_bake_bread", [])}
    after = {e.card_id for e in AUTO_EFFECTS.get("after_bake_bread", [])}
    assert "dutch_windmill" in before
    assert "dutch_windmill" not in after


# ---------------------------------------------------------------------------
# The +3 food is granted in the PendingBakeBread BEFORE-phase (before CommitBake)
# ---------------------------------------------------------------------------

def test_dutch_windmill_grants_food_before_bake_in_post_harvest_round():
    cs = _card_state(round_number=5)                     # 5 immediately follows harvest 4
    cs = with_majors(cs, owner_by_idx={0: 0})           # Fireplace (a baker: 1 grain -> 2 food)
    cs = _own_minor(cs, 0, "dutch_windmill")
    cs = with_resources(cs, 0, grain=1)                 # seed grain so a real bake is reachable
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    # The auto fired at the PendingBakeBread push: +3 food on hand BEFORE any CommitBake.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBakeBread)
    assert cs.players[0].resources.food == food_before + 3
    # A real bake still follows (before-phase forces CommitBake — nothing stranded).
    assert any(isinstance(a, CommitBake) for a in legal_actions(cs))
    cs = step(cs, CommitBake(grain=1))                  # Fireplace: +2 food from the bake itself
    assert cs.players[0].resources.food == food_before + 5
    assert cs.players[0].resources.grain == 0


# ---------------------------------------------------------------------------
# No grant in a non-post-harvest round
# ---------------------------------------------------------------------------

def test_dutch_windmill_no_food_in_non_post_harvest_round():
    cs = _card_state(round_number=6)                     # 6 does NOT immediately follow a harvest
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "dutch_windmill")
    cs = with_resources(cs, 0, grain=1)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.food == food_before  # unchanged: not a post-harvest round


# ---------------------------------------------------------------------------
# No grant when the card is not owned
# ---------------------------------------------------------------------------

def test_dutch_windmill_does_not_fire_when_not_owned():
    cs = _card_state(round_number=5)                     # a post-harvest round
    cs = with_majors(cs, owner_by_idx={0: 0})           # baker present, but card NOT owned
    cs = with_resources(cs, 0, grain=1)
    food_before = cs.players[0].resources.food
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.food == food_before  # unchanged: card not owned
