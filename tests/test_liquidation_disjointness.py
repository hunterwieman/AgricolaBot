"""TRIPWIRE — the work-phase liquidation one-way invariant.

The engine's payment machinery is built on a ONE-WAY assumption: goods
convert INTO food, never food into building resources, and only crops and
animals are consumed by work-phase food raising. Wood / clay / reed / stone
can never enter or leave a work-phase food-payment bundle, so every
affordability check and every preserve argument in the engine may treat the
building-resource pile as untouchable by feeding.

A card that breaks this — Large Pottery (D60, "At any time: Clay → 2 Food"),
or any sibling in the Basketmaker's Wife / Grocer / Clay Carrier classes —
invalidates affordability and preserve arguments across the engine.

**When either test below fails, that card has arrived.** Do not weaken the
asserts, add the card to `_SKIP`, or re-derive safety locally: a conversion
involving building resources outside the harvest is now possible — STOP and
inform the user before proceeding; every affordability and preserve argument
in the engine was built on the one-way assumption, and the user must decide
how the payment machinery extends.

Unlike the original version of this tripwire (which checked a card-less
player and so could never fire — every converter is ownership-gated), these
tests grant ownership: test 1 gives one player EVERY implemented card at
once and pins that no registered span converter is live outside a harvest
window; test 2 grants each implemented card one at a time and pins that no
single card slips a conversion into a work-phase bundle.
"""
import agricola.cards  # noqa: F401  -- populate the registries

from agricola.cards.harvest_windows import available_span_converters
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.legality import _food_payment_commits
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_majors, with_resources

# Cards whose mere OWNERSHIP (granted without being played, as these tests
# do) crashes the payment machinery — each entry needs a confirmed crash
# reason in a comment. Empty is the goal state.
_SKIP: set = set()


def _goods_rich_work_state():
    """A WORK-phase state where player 0 is rich in every good, with a
    Fireplace (so animals are cookable too) and an emptied hand (ownership
    is injected per-test)."""
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
    return s


def _with_ownership(s, occupations: frozenset, minors: frozenset):
    p0 = fast_replace(s.players[0], occupations=occupations,
                      minor_improvements=minors)
    return fast_replace(s, players=(p0, s.players[1]))


def test_no_span_converter_live_outside_harvest_even_owning_every_card():
    """Owning EVERY implemented card at once, no registered span converter is
    live during a WORK-phase placement: `available_span_converters` returns
    () whenever the state is out of the harvest span, regardless of
    ownership. A non-empty result here means a converter has escaped the
    harvest window — see the module docstring: STOP and inform the user."""
    s = _goods_rich_work_state()
    s = _with_ownership(s, frozenset(OCCUPATIONS), frozenset(MINORS))
    live = available_span_converters(s, 0)
    assert not live, (
        "span converter(s) live OUTSIDE a harvest window: "
        f"{[entry[0] for entry in live]} — a conversion involving building "
        "resources outside the harvest is now possible; STOP and inform the "
        "user before proceeding (see this file's docstring)"
    )


def test_bundles_stay_conversion_free_per_card():
    """Granting each implemented card ONE AT A TIME, every work-phase
    food-payment bundle stays conversion-free and consumes only crops /
    animals. The failing card id names the converter that broke the one-way
    assumption — see the module docstring: STOP and inform the user."""
    base = _goods_rich_work_state()
    card_ids = ([(cid, "occ") for cid in sorted(OCCUPATIONS)]
                + [(cid, "minor") for cid in sorted(MINORS)])
    assert card_ids, "registries empty — the import wiring is broken"

    for cid, kind in card_ids:
        if cid in _SKIP:
            continue
        if kind == "occ":
            s = _with_ownership(base, frozenset({cid}), frozenset())
        else:
            s = _with_ownership(base, frozenset(), frozenset({cid}))
        for needed in (1, 2, 3):
            bundles = _food_payment_commits(s, 0, needed, Cost())
            assert bundles, (
                f"[{cid}] no bundle raises {needed} food in a goods-rich state"
            )
            for b in bundles:
                assert not b.conversions, (
                    f"[{cid}] a named converter fired in a WORK-phase bundle "
                    f"({b.conversions}) — a conversion involving building "
                    "resources outside the harvest is now possible; STOP and "
                    "inform the user before proceeding (see this file's "
                    "docstring)"
                )
                # CommitFoodPayment carries only crop/animal fields; building
                # resources could enter solely via `conversions`, asserted
                # empty above. This second assert documents the invariant
                # directly.
                assert b.grain + b.veg + b.sheep + b.boar + b.cattle > 0, (
                    f"[{cid}] a bundle raised food from nothing — building "
                    "resources may have entered the payment machinery"
                )
