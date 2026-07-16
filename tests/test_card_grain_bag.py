"""Tests for Grain Bag (minor improvement, E67; Ephipparius Expansion).

Card text: "Each time you use the 'Grain Seeds' action space, you get 1 additional
grain for each baking improvement you have."

The load-bearing part is the count: baking majors + owned baking MINOR improvements,
by ownership (so a Baking Course, which bakes only at round-end, still counts —
user ruling 2026-07-15).
"""
import agricola.cards.grain_bag  # noqa: F401  (registers the card)
import agricola.cards.simple_oven  # noqa: F401  (a baking minor, for counting)
import agricola.cards.baking_course  # noqa: F401  (a round-end-only baking minor)

from agricola.cards.grain_bag import CARD_ID, _apply, _eligible
from agricola.cards.specs import MINORS
from agricola.legality import count_baking_improvements
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_pending_stack

_POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                 minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)))

# Major indices: Fireplace 0/1, Cooking Hearth 2/3, Well 4, Clay Oven 5, Stone Oven 6,
# Joinery 7, Pottery 8, Basketmaker 9. Baking majors = {0,1,2,3,5,6}.


def _state(*, majors=(), minors=frozenset()):
    cs, _ = setup_env(0, card_pool=_POOL)
    p = fast_replace(cs.players[0], resources=Resources(),
                     minor_improvements=frozenset(minors))
    cs = fast_replace(cs, players=(p, cs.players[1]))
    if majors:
        cs = with_majors(cs, owner_by_idx={m: 0 for m in majors})
    return cs


def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.vps == 1


def test_count_baking_majors_only():
    assert count_baking_improvements(_state(majors=(0,)), 0) == 1        # Fireplace
    assert count_baking_improvements(_state(majors=(0, 2)), 0) == 2      # + Cooking Hearth
    assert count_baking_improvements(_state(majors=(5, 6)), 0) == 2      # Clay + Stone Oven
    assert count_baking_improvements(_state(majors=(4,)), 0) == 0        # Well (not baking)
    assert count_baking_improvements(_state(majors=(4, 7, 8, 9)), 0) == 0  # Well/Joinery/Pottery/Basketmaker


def test_count_baking_minors_by_ownership():
    assert count_baking_improvements(_state(minors={"simple_oven"}), 0) == 1
    # Baking Course counts even though its rate is active only at round-end:
    assert count_baking_improvements(_state(minors={"baking_course"}), 0) == 1
    assert count_baking_improvements(_state(minors={"simple_oven", "baking_course"}), 0) == 2
    assert count_baking_improvements(_state(minors={"m0"}), 0) == 0      # a non-baking minor


def test_count_majors_and_minors_together():
    cs = _state(majors=(0, 2), minors={"simple_oven", "baking_course"})
    assert count_baking_improvements(cs, 0) == 4


def test_apply_grants_grain_equal_to_count():
    cs = _state(majors=(0,), minors={"simple_oven"})   # 2 baking improvements
    out = _apply(cs, 0)
    assert out.players[0].resources.grain == 2


def test_eligible_only_on_grain_seeds_with_a_baking_improvement():
    def _at(space, **kw):
        cs = _state(**kw)
        return with_pending_stack(cs, (PendingActionSpace(
            player_idx=0, initiated_by_id=f"space:{space}"),))
    assert _eligible(_at("grain_seeds", majors=(0,)), 0) is True
    assert _eligible(_at("grain_seeds"), 0) is False        # no baking improvement -> no bonus
    assert _eligible(_at("forest", majors=(0,)), 0) is False  # wrong space
