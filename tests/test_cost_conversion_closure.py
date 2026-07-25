"""Guard test for `agricola.cards.cost_mods.expand_conversions` (COST_MODIFIER_DESIGN.md
§4.7 / §8 — the chaining-rule backstop the doc/`expand_conversions` docstring promised but
that never existed).

WHAT `expand_conversions` DOES, AND THE OPTIMISATION IT TAKES
------------------------------------------------------------
When a build's printed cost is resolved into the payment vectors a player may actually use,
each owned *conversion* cost card (Frame Builder, Millwright, Rammed Clay, ...) contributes a
"replace some of the cost with something else" option. Conversions chain: one conversion's
output can feed another (Frame Builder turns 2 clay into 1 wood; Millwright then turns that
wood into 1 grain). `expand_conversions` does NOT compute the full transitive closure over
these chains — it applies each owned conversion's generator EXACTLY ONCE, in registration
order with the consuming "sink" (Millwright) applied last, to the growing candidate set. The
claim §4.7 makes is that this one-pass shortcut reaches the same payments as the full
budget-respecting closure.

THE INDEPENDENT ORACLE
----------------------
`full_closure` below is an algorithmically-independent reference: a breadth-first search over
`(cost, set-of-conversions-already-applied)` states that applies each owned conversion AT MOST
ONCE per derivation path but explores EVERY ordering (not just the fixed sink-last order). This
is the "budget-respecting closure": each conversion's whole budget is enumerated inside a single
generator call, so "at most once per path" honours every current card's budget (Frame Builder's
"once per action", Millwright's "up to 2 per action", Rammed Clay's "any split", ...), while the
all-orderings exploration is what would surface a payment the fixed sink-last pass cannot reach.

WHAT THIS TEST ACTUALLY ASSERTS, AND WHY IT IS NOT A RAW WHOLE-SET COMPARISON
----------------------------------------------------------------------------
§4.7 / §8 phrase the guard as "apply-each-once-sink-last == the full budget-respecting closure".
Taken as a *raw whole-set* equality that was true when it was written, because only ONE feeder
(Frame Builder) plus the Millwright sink existed — `test_single_feeder_raw_set_is_exact` pins
that: with exactly Frame Builder + Millwright owned, one-pass and the closure produce byte-equal
raw candidate sets.

It is NO LONGER a raw whole-set equality for the current catalogue, and cannot be made one. Two
distinct cost cards now BOTH turn part of a cost into wood — Frame Builder (2 clay/stone -> 1
wood) and Brushwood Collector (the reed requirement -> 1 wood). With two wood-producing feeders
plus the Millwright sink, the closure reaches payments via a producer -> sink -> producer
interleaving (e.g. Frame Builder, then Millwright consuming a clay+reed into grain, then
Brushwood Collector turning the surviving reed into wood) that no single fixed ordering of a
one-pass fold can reach. Every such extra payment is strictly Pareto-DOMINATED by one the
one-pass already has, so it is pruned by `effective_payments`' `pareto_min_over_goods` and is
never offered to a player. The property that actually matters for correctness — and the faithful
reading of §4.7's "never silently wrong" — is therefore that the two agree on the payments a
player is *offered*: the Pareto-minimal frontier. `test_offered_frontier_matches_closure`
asserts exactly that, over every action kind that has registered conversions and a corpus of
GAME-REACHABLE base costs, with a player owning every conversion card at once.

THE MASTER RENOVATOR ORDERING FIX (a latent gap, now closed)
------------------------------------------------------------
Master Renovator's "pay 1 building resource of your choice less" is a building-resource CONSUMER
(a discount), not a producer. It used to register at `order=0` — the producer tier — and sort
before the wood-producing Brushwood Collector, so the chain "Brushwood turns the reed into 1 wood,
then Master Renovator discounts that wood" (paying 0 reed) escaped the one-pass, which offered only
the strictly-worse 1-reed payment. That WAS a genuinely non-dominated payment the shortcut dropped
— reachable only on a renovate cost carrying >= 2 reed, and a real renovate always costs exactly 1
reed (where Master Renovator discounts the single reed directly), so it never surfaced in play.
Master Renovator now carries `order=CONSUMER_ORDER` (cost_mods.py), applied after the producers,
and `test_master_renovator_ordering_closed` pins the fix: on the >= 2-reed base the one-pass offered
frontier now equals the closure and offers the 0-reed payment it used to miss. This is why the
general guard needs no renovate special case.

This test is test-only: no engine behaviour changes, Family-inert, no C++ impact.
"""
from __future__ import annotations

import agricola.cards  # noqa: F401  — importing the package populates every card registry
from agricola.cards.cost_mods import (
    CONVERSIONS,
    expand_conversions,
    owned_conversions,
)
from agricola.cost import CostCtx, pareto_min_over_goods
from agricola.pending import PendingHouseRedevelopment
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

# Every card id that registers a conversion, read LIVE from the registry (never hardcoded —
# the set has drifted from the ~7 the design doc names, e.g. Master Renovator was added later).
CONVERSION_CARD_IDS = sorted(
    {card_id for rows in CONVERSIONS.values() for (_order, card_id, _fn, _rec) in rows}
)

# The action kinds that actually have registered conversions (also live from the registry).
CONVERSION_ACTION_KINDS = sorted(CONVERSIONS)

# grant-provenance candidates, derived generically from the owned cards: a grant-scoped
# conversion (Master Renovator, Site Manager) fires only when `ctx.granted_by` matches its own
# `"card:<id>"` provenance, so cycling `granted_by` over every owned card's provenance (plus
# None for space-initiated actions) makes each grant-scoped conversion active in some context.
GRANTED_BY_CANDIDATES = [None] + [f"card:{cid}" for cid in CONVERSION_CARD_IDS]

# A hard cap so a mis-defined closure (a future non-budgeted / total-increasing generator) fails
# loudly instead of hanging. The real closure over these corpora settles in well under this.
_CLOSURE_ITERATION_CAP = 2_000_000


def _state_owning_all_conversions(*, house_redevelopment: bool) -> object:
    """A deterministic `setup(0)` state whose player 0 owns EVERY conversion card.

    `_owns` (the only ownership gate the conversion folds consult) accepts a card id in either
    `occupations` or `minor_improvements`, so listing them all as occupations grants ownership
    regardless of a card's real type. When `house_redevelopment` is set, a
    `PendingHouseRedevelopment` frame is placed on the stack: Hunting Trophy's conversion is
    scoped to "an improvement built via House Redevelopment", i.e. it only fires while such a
    frame is live, so this makes its conversion active too.
    """
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(CONVERSION_CARD_IDS))
    state = fast_replace(state, players=(p0, state.players[1]))
    if house_redevelopment:
        state = fast_replace(state, pending_stack=(
            PendingHouseRedevelopment(player_idx=0, initiated_by_id="house_redevelopment"),
        ))
    return state


def full_closure(action_kind: str, state, idx: int, ctx, base: Resources) -> set:
    """Independent budget-respecting closure of the owned conversions over `base`.

    Algorithmically distinct from `expand_conversions` (a single left-to-right fold that applies
    each generator once): a BFS whose state is `(cost, frozenset-of-applied-conversion-indices)`.
    From `(base, {})` it applies each not-yet-applied conversion — so each conversion is used at
    most once along any path (honouring its per-action budget, which a single generator call
    already enumerates in full), while EVERY ordering is explored. Returns every cost reached.

    Finite because every current generator is budget-bounded and never increases a cost's total
    resource count, and the applied-set grows monotonically along each path; the iteration cap is
    a defensive backstop against a future generator that breaks those properties.
    """
    convs = owned_conversions(action_kind, state, idx)
    start = (base, frozenset())
    seen = {start}
    stack = [start]
    reached = {base}
    iterations = 0
    while stack:
        iterations += 1
        assert iterations < _CLOSURE_ITERATION_CAP, (
            f"closure did not terminate for {action_kind} base={base} — a conversion "
            f"generator is likely unbudgeted or increases the cost total"
        )
        cost, applied = stack.pop()
        for i, fn in enumerate(convs):
            if i in applied:
                continue
            for new_cost in fn(state, idx, ctx, cost):
                reached.add(new_cost)
                nxt = (new_cost, applied | {i})
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return reached


def _offered(cands) -> set:
    """The payments actually surfaced to a player: the Pareto-minimal frontier over goods,
    exactly the reduction `effective_payments` applies to `expand_conversions`' output."""
    return set(pareto_min_over_goods(list(cands)))


# Game-reachable base costs, per action kind — what an action's cost adapter can actually
# produce (renovate: num_rooms of the target material + exactly 1 reed; build_room: 5 of the
# house material + 2 reed; build_stable: 2 wood; build_fence: N geometry-derived wood;
# build_major: the real major-improvement costs; play_minor / play_occupation: representative
# small card costs). These are what `effective_payments` is ever asked to resolve.
_REALISTIC_BASES: dict[str, list[Resources]] = {
    "renovate": [
        Resources(clay=1, reed=1), Resources(clay=2, reed=1), Resources(clay=3, reed=1),
        Resources(clay=4, reed=1), Resources(clay=5, reed=1),
        Resources(stone=2, reed=1), Resources(stone=4, reed=1), Resources(stone=5, reed=1),
    ],
    "build_room": [
        Resources(wood=5, reed=2), Resources(clay=5, reed=2), Resources(stone=5, reed=2),
    ],
    "build_stable": [Resources(wood=2)],
    "build_fence": [Resources(wood=n) for n in (1, 2, 3, 4, 5, 6, 8, 10)],
    "build_major": [
        Resources(clay=3), Resources(wood=1, clay=1), Resources(clay=2, stone=3),
        Resources(wood=2), Resources(clay=1, stone=1), Resources(wood=3, clay=2),
        Resources(stone=1, reed=2), Resources(wood=2, stone=2), Resources(clay=2, reed=2),
        Resources(stone=3), Resources(wood=1, stone=2),
    ],
    "play_minor": [
        Resources(), Resources(wood=1), Resources(clay=1), Resources(reed=1),
        Resources(stone=1), Resources(wood=1, clay=1), Resources(wood=2),
        Resources(wood=2, clay=1),
    ],
    "play_occupation": [
        Resources(), Resources(food=1), Resources(food=2), Resources(food=3),
    ],
}


def _bases_for(action_kind: str) -> list[Resources]:
    # Fall back to a broad mix if a newly-registered action kind has no curated corpus yet,
    # so the test still exercises it (and fails loudly) rather than silently skipping.
    return _REALISTIC_BASES.get(action_kind, [
        Resources(wood=2, clay=2, reed=2, stone=2), Resources(clay=5, reed=2),
        Resources(wood=6), Resources(food=3, wood=1),
    ])


def test_registry_populated():
    """Sanity: the package import actually populated the conversion registry (so the parametric
    tests below are not vacuously iterating over nothing)."""
    assert CONVERSION_CARD_IDS, "no conversion cards registered — did the card import fail?"
    assert CONVERSION_ACTION_KINDS, "no action kinds with conversions"
    # The catalogue has drifted past the design doc's ~7; assert we are exercising the fuller set.
    assert "master_renovator" in CONVERSION_CARD_IDS
    assert "brushwood_collector" in CONVERSION_CARD_IDS


def test_offered_frontier_matches_closure():
    """THE GUARD (§4.7 / §8). Owning every conversion card, over every action kind that has
    conversions and every game-reachable base cost, the payment frontier `expand_conversions`
    yields (after the Pareto-min `effective_payments` applies) equals the frontier of the
    independent all-orderings budget-respecting closure. Goes red if a future card makes a
    genuinely NON-dominated payment reachable that the fixed sink-last one-pass misses — a longer
    chain or a second sink.
    """
    for action_kind in CONVERSION_ACTION_KINDS:
        bases = _bases_for(action_kind)
        for house_redev in (False, True):
            state = _state_owning_all_conversions(house_redevelopment=house_redev)
            for granted_by in GRANTED_BY_CANDIDATES:
                for base in bases:
                    ctx = CostCtx(action_kind, base, granted_by=granted_by)
                    one_pass = expand_conversions(action_kind, state, 0, ctx, base)
                    closure = full_closure(action_kind, state, 0, ctx, base)
                    # one-pass is always a subset of the closure; the content of the assertion
                    # is that nothing NON-dominated is lost.
                    assert _offered(one_pass) == _offered(closure), (
                        f"offered frontier diverges: action_kind={action_kind} "
                        f"granted_by={granted_by} house_redev={house_redev} base={base}\n"
                        f"  closure-only: {_offered(closure) - _offered(one_pass)}\n"
                        f"  one-pass-only: {_offered(one_pass) - _offered(closure)}"
                    )


def test_single_feeder_raw_set_is_exact():
    """The design's original claim, pinned: with exactly one feeder (Frame Builder) plus the
    Millwright sink owned, the one-pass shortcut equals the closure at the RAW whole-set level
    (not merely after Pareto-min) — for every renovate/build_room base. Raw exactness is a
    single-feeder property; it is `test_offered_frontier_matches_closure` that carries the guard
    once a second wood-producing feeder (Brushwood Collector) coexists.
    """
    state = setup(0)
    p0 = fast_replace(state.players[0],
                      occupations=frozenset({"frame_builder", "millwright"}))
    state = fast_replace(state, players=(p0, state.players[1]))
    for action_kind in ("renovate", "build_room"):
        for base in _bases_for(action_kind):
            ctx = CostCtx(action_kind, base)
            one_pass = set(expand_conversions(action_kind, state, 0, ctx, base))
            closure = full_closure(action_kind, state, 0, ctx, base)
            assert one_pass == closure, (
                f"single-feeder raw set diverges: {action_kind} base={base}\n"
                f"  closure-only: {closure - one_pass}\n"
                f"  one-pass-only: {one_pass - closure}"
            )


def test_master_renovator_ordering_closed():
    """The Master Renovator ordering gap is CLOSED by tiering it as a consumer.

    Master Renovator's "1 building resource less" is a discount — a CONSUMER. It used to
    register at the producer tier (`order=0`) and sort before the wood-producing Brushwood
    Collector, so the chain "Brushwood turns the reed into 1 wood, then Master Renovator
    discounts that wood" (paying 0 reed) was unreachable to the one-pass, which only offered a
    (strictly worse) 1-reed payment. That is a genuinely NON-dominated payment the one-pass
    dropped — harmless only because a real renovate always costs exactly 1 reed (where Master
    Renovator can discount the single reed directly), so it never surfaced in play.

    Master Renovator now carries `order=CONSUMER_ORDER`, so it applies AFTER the producers and
    the one-pass reaches the chain. On a >= 2-reed base — the case that used to diverge — the
    one-pass offered frontier now equals the full all-orderings closure, and it offers the
    previously-missed 0-reed payment (`clay=5`), pruning the dominated 1-reed one.

    Regression guard: revert Master Renovator to the producer tier and the 0-reed payment drops
    back out of the one-pass, reopening `closure - one_pass == {clay=5}` and failing this test.
    """
    state = _state_owning_all_conversions(house_redevelopment=False)
    grant = "card:master_renovator"

    two_reed_base = Resources(clay=5, reed=2)
    ctx = CostCtx("renovate", two_reed_base, granted_by=grant)
    one_pass = _offered(expand_conversions("renovate", state, 0, ctx, two_reed_base))
    closure = _offered(full_closure("renovate", state, 0, ctx, two_reed_base))
    assert one_pass == closure, (
        "gap not closed after tiering Master Renovator as a consumer:\n"
        f"  closure-only: {closure - one_pass}\n"
        f"  one-pass-only: {one_pass - closure}"
    )
    assert Resources(clay=5) in one_pass          # the Brushwood->Master-Renovator 0-reed payment
    assert Resources(clay=5, reed=1) not in one_pass  # its dominated 1-reed sibling is pruned
