"""TRIPWIRE — the work-phase liquidation disjointness invariant (ruling 82).

The one-direction structural-safety arguments in `full_peasant.py` and
`large_scale_farmer.py` (their jumps INTO Fencing / Farm Expansion skip the
destination-preserve check) rest on ONE fact:

    A work-phase food raise can consume only CROPS and ANIMALS — never
    wood / clay / reed / stone. (The building-resource span converters —
    Joinery et al. — are harvest-window-scoped and never active during a
    placement.)

**This test is the executable note left for the card that breaks it** (user
directive, 2026-07-26): **Large Pottery (D60 — "At any time: Clay → 2 Food")**
is an ANYTIME building-resource converter; implementing it (or any sibling —
the Clay Carrier D122 family, any anytime wood/reed/stone converter) makes a
work-phase bundle consume a building resource, and this test MUST then fail.

When it fires, do not weaken the assert — re-derive the safe directions:
- `full_peasant._fee_payable`'s Fencing branch and
  `large_scale_farmer._jump_ok`'s Farm-Expansion branch lose their structural
  safety the moment the new converter's INPUT overlaps the destination's cost
  (wood/reed for those two; clay alone leaves them safe but the INVARIANT is
  gone — re-prove or add the preserve check per direction).
- The CARD_IMPLEMENTATION_PROGRESS.md entry for D60 carries the matching
  ⚠ REVISIT note.
"""
import agricola.cards  # noqa: F401  -- populate the registries

from agricola.legality import _food_payment_commits
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_majors, with_resources


def test_work_phase_liquidation_never_consumes_building_resources():
    """A WORK-phase state rich in every good, with a Fireplace (so animals are
    cookable too): every bundle the food-payment machinery can offer consumes
    crops/animals only — no bundle touches wood/clay/reed/stone, and no
    harvest-span converter fires outside its harvest window."""
    pool = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                    minors=tuple(f"m{i}" for i in range(20)))
    s, _env = setup_env(11, card_pool=pool)
    s = with_current_player(s, 0)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    s = fast_replace(s, players=(p0, s.players[1]))
    s = with_resources(s, 0, food=0, grain=2, veg=2,
                       wood=5, clay=5, reed=5, stone=5)
    p = s.players[0]
    s = fast_replace(s, players=(
        fast_replace(p, animals=fast_replace(p.animals, sheep=2)),
        s.players[1]))
    s = with_majors(s, owner_by_idx={0: 0})       # a Fireplace: animals cookable

    for needed in (1, 2, 3):
        bundles = _food_payment_commits(s, 0, needed, Cost())
        assert bundles, f"no bundle raises {needed} food in a goods-rich state"
        for b in bundles:
            assert not b.conversions, (
                "a named converter fired in a WORK-phase bundle — an anytime "
                f"converter has joined the payment machinery ({b.conversions}); "
                "the ruling-82 one-direction safety arguments in full_peasant / "
                "large_scale_farmer must be RE-DERIVED (see this file's docstring)"
            )
            # CommitFoodPayment carries only crop/animal fields; building
            # resources could enter solely via `conversions`, asserted empty
            # above. This second assert documents the invariant directly.
            assert b.grain + b.veg + b.sheep + b.boar + b.cattle > 0
