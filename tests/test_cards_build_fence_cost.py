"""Tests for the Cards deferred-tally build-fence cost path + Hedge Keeper
(occupation A88) — COST_MODIFIER_DESIGN.md §9.2 / increment 2b.

In CARDS mode a Build Fences action does NOT debit wood per pasture commit: each
commit accrues its (post-free) wood onto the `PendingBuildFences` frame, and the
whole-action bill is settled once at the Proceed flip (engine `_settle_build_fences`),
before the after-grants fire. Hedge Keeper seeds a per-action `free_fence_budget`
of 3 (a `before_build_fences` automatic effect) on a LITERAL Build Fences action, so
the first 3 paid edges of the action cost no wood.

These tests drive the REAL fencing flow (the Fencing space), per CARD_AUTHORING_GUIDE
§5, in an explicit CARDS-mode state with Hedge Keeper owned.

FREE-FENCE-AWARE LEGALITY (§9.2 shared-affordability + placement-anticipation): the
free budget now *enables* a marginal tight-wood build, not merely *discounts* a
gross-affordable one. The legality affordability gates on `paid = max(0, edges -
free_budget)`, not the gross edge count — so a player with 2 wood + Hedge Keeper (3
free) can build a 5-edge layout, paying 2 wood. The budget the not-yet-pushed frame
*would* seed is anticipated at placement (`_any_legal_pasture_commit`) and read off
the frame during building (`_enumerate_pending_build_fences`), both through the single
shared `free_fence_budget_for` seed function. The cache is bypassed in Cards mode (its
key is free-budget-blind); Family still uses it and is byte-identical (budget 0). The
tight-wood tests at the bottom exercise this; the discount tests above give ample wood.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitChooseCost,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.briar_hedge import CARD_ID as BRIAR_HEDGE_ID
from agricola.cards.hedge_keeper import CARD_ID
from agricola.cards.millwright import CARD_ID as MILLWRIGHT_ID
from agricola.cards.rammed_clay import CARD_ID as RAMMED_CLAY_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildFences, PendingChooseCost
from agricola.replace import fast_replace
from agricola.resources import Resources

from tests.factories import with_animals, with_resources
from tests.test_fencing import _fencing_setup, _with_initial_pasture


# Top-right pasture shapes (in the default RESTRICTED universe on a fresh farm).
_TOP_1x2_34 = frozenset({(0, 3), (0, 4)})           # new pasture, adjacent to (0,2)
_PRE_1x1 = [(0, 2)]                                  # pre-existing single pasture
_2x3_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)})
_TOP_1x2_subdiv = frozenset({(0, 3), (0, 4)})       # 2-edge subdivision of the 2x3


def _cards_setup(*, wood, own_card=True, pre_pasture=None):
    """A CARDS-mode fencing state: Fencing revealed, ample wood, optionally owning
    Hedge Keeper (in `occupations`, the played tableau — only a played card fires)
    and optionally with a pre-existing pasture."""
    state = _fencing_setup(wood=wood)
    state = fast_replace(state, mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    if own_card:
        p = state.players[0]
        p = fast_replace(p, occupations=p.occupations | {CARD_ID})
        state = fast_replace(
            state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
        )
    return state


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    return state


def _finish(state):
    """Proceed (flips PBF -> after; the CARDS settle pays the accrued bill, then
    the after-autos fire) then drain the two Stops."""
    state = step(state, Proceed())
    state = step(state, Stop())      # pop PendingBuildFences
    state = step(state, Stop())      # pop PendingSubActionSpace
    return state


def _wood(state, idx=0):
    return state.players[idx].resources.wood


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect (passive cost-discount occupation).
    s = _fencing_setup(wood=1)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


# ---------------------------------------------------------------------------
# The budget is seeded on a literal Build Fences action
# ---------------------------------------------------------------------------

def test_budget_seeded_on_literal_build_fences():
    state = _cards_setup(wood=20)
    state = _enter_build_fences(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.build_fences_action is True
    assert top.free_fence_budget == 3        # Hedge Keeper seeded +3


def test_no_budget_without_card():
    state = _cards_setup(wood=20, own_card=False)
    state = _enter_build_fences(state)
    assert state.pending_stack[-1].free_fence_budget == 0


# ---------------------------------------------------------------------------
# The discount — the spec's worked example: a 5-edge build costs 2 wood (5 - 3)
# ---------------------------------------------------------------------------

def test_five_edge_build_costs_two_wood():
    # Pre-existing 1x1 at (0,2); a new adjacent top 1x2 at (0,3),(0,4) encloses
    # exactly 5 new fence edges. With Hedge Keeper's 3 free, the player pays 2 wood.
    state = _cards_setup(wood=20, pre_pasture=_PRE_1x1)
    assert _wood(state) == 20
    state = _enter_build_fences(state)
    # Mid-action: no debit yet (deferred); the accrued bill is 5 - 3 = 2.
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    top = state.pending_stack[-1]
    assert _wood(state) == 20                 # nothing debited per-commit in CARDS
    assert top.accrued_cost.wood == 2         # 5 edges - 3 free
    assert top.free_fence_budget == 0         # budget consumed
    # Settle at Proceed pays the 2 wood.
    state = _finish(state)
    assert _wood(state) == 18                 # 20 - 2


def test_five_edge_build_full_price_without_card():
    # Same geometry, no Hedge Keeper: the full 5 wood is paid at settle.
    state = _cards_setup(wood=20, own_card=False, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 5
    state = _finish(state)
    assert _wood(state) == 15                 # 20 - 5


# ---------------------------------------------------------------------------
# A <=3-edge build is fully covered by the budget — 0 wood
# ---------------------------------------------------------------------------

def test_small_build_costs_zero_wood():
    # Pre-existing 2x3; subdividing off the top 1x2 adds only 2 new edges (<= 3),
    # fully covered by the budget -> 0 wood paid.
    state = _cards_setup(wood=20, pre_pasture=[(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)])
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_subdiv))
    top = state.pending_stack[-1]
    assert top.accrued_cost.wood == 0         # 2 edges, all free
    assert top.free_fence_budget == 1         # 3 - 2
    state = _finish(state)
    assert _wood(state) == 20                 # nothing paid


# ---------------------------------------------------------------------------
# The budget is per-ACTION, applied across multiple commits within one action
# ---------------------------------------------------------------------------

def test_budget_spans_multiple_commits_in_one_action():
    # First commit: a fresh top-right 1x1 ... actually use two adjacent pastures so
    # the budget is consumed across commits. Pre-existing (0,2); commit a top 1x2
    # (5 edges) then a subdivision below is not adjacent; instead build the 1x2 then
    # subdivide it. First commit 5 edges -> 3 free, 2 accrued, budget 0; the second
    # (subdivision, 2 edges) is then fully paid (budget exhausted).
    state = _cards_setup(wood=20, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))   # 5 edges
    assert state.pending_stack[-1].accrued_cost.wood == 2
    assert state.pending_stack[-1].free_fence_budget == 0
    # A subdivision of the just-built 1x2 (split into two 1x1s) adds new edges, now
    # at full price since the budget is exhausted.
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 3)})))
    top = state.pending_stack[-1]
    sub_edges = top.fences_built - 5
    assert top.accrued_cost.wood == 2 + sub_edges   # 2 (discounted) + full-price subdiv
    state = _finish(state)
    assert _wood(state) == 20 - (2 + sub_edges)


# ---------------------------------------------------------------------------
# Free-fence-AWARE legality: the budget ENABLES a tight-wood build (§9.2)
# ---------------------------------------------------------------------------
# The 5-edge layout: a pre-existing 1x1 at (0,2) plus the adjacent top 1x2 at
# (0,3),(0,4) encloses exactly 5 new edges. With 2 wood + Hedge Keeper (3 free)
# the paid cost is 5 - 3 = 2 wood, so the build is now affordable; without Hedge
# Keeper the gross 5 wood is unaffordable and the layout is illegal.

def test_zero_wood_fencing_offered_with_free_fences():
    # The free-fence-aware placement guard (§9.2 step): a 0-wood Cards player with Hedge Keeper
    # + a subdividable pasture can build a fully-free subdivision (<=3 edges, covered by the 3
    # budget), so the Fencing space IS offered even at 0 wood.
    state = _cards_setup(wood=0, pre_pasture=[(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)])
    placements = [a for a in legal_actions(state)
                  if isinstance(a, PlaceWorker) and a.space == "fencing"]
    assert placements, "0-wood Hedge Keeper player can build a free subdivision -> Fencing offered"


def test_zero_wood_fencing_not_offered_without_free_fences():
    # Same 0 wood, NO free-fence card: nothing is buildable, so Fencing is not offered (the
    # guard's intent preserved — `_any_legal_pasture_commit` correctly finds nothing affordable).
    state = _cards_setup(wood=0, own_card=False,
                         pre_pasture=[(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)])
    placements = [a for a in legal_actions(state)
                  if isinstance(a, PlaceWorker) and a.space == "fencing"]
    assert not placements, "0-wood, no free fences -> nothing buildable -> Fencing not offered"


def test_placement_offered_with_tight_wood_and_card():
    # 2 wood + Hedge Keeper: Build Fences is available at placement (a 1x1 alone is
    # free, but more to the point the anticipated budget makes tight builds legal).
    state = _cards_setup(wood=2, pre_pasture=_PRE_1x1)
    placements = [a for a in legal_actions(state)
                  if isinstance(a, PlaceWorker) and a.space == "fencing"]
    assert placements, "Fencing should be offered at placement with 2 wood + Hedge Keeper"


def test_five_edge_layout_legal_with_card_tight_wood():
    # 2 wood + Hedge Keeper: the 5-edge CommitBuildPasture is OFFERED during building
    # (paid = 5 - 3 = 2 <= 2 wood).
    state = _cards_setup(wood=2, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    assert state.pending_stack[-1].free_fence_budget == 3
    commits = {a.cells for a in legal_actions(state)
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 in commits, "the 5-edge layout should be legal (2 wood pays 5-3)"


def test_five_edge_layout_illegal_without_card_tight_wood():
    # 2 wood, NO Hedge Keeper: the 5-edge layout costs the full 5 wood, unaffordable,
    # so it is NOT offered during building.
    state = _cards_setup(wood=2, own_card=False, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    assert state.pending_stack[-1].free_fence_budget == 0
    commits = {a.cells for a in legal_actions(state)
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 not in commits, "the 5-edge layout is unaffordable at 2 wood, no card"


def test_tight_wood_five_edge_build_pays_two_ending_at_zero():
    # The full flow: 2 wood + Hedge Keeper builds the 5-edge layout, settles 2 wood at
    # Proceed, ending at 0 wood.
    state = _cards_setup(wood=2, pre_pasture=_PRE_1x1)
    assert _wood(state) == 2
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    top = state.pending_stack[-1]
    assert _wood(state) == 2                  # nothing debited per-commit in CARDS
    assert top.accrued_cost.wood == 2         # 5 edges - 3 free
    assert top.free_fence_budget == 0         # budget consumed
    state = _finish(state)
    assert _wood(state) == 0                  # 2 - 2, ended at zero


# ---------------------------------------------------------------------------
# Millwright-on-fences: a PLAIN conversion on the running total (COST_MODIFIER_DESIGN.md §9.2)
# ---------------------------------------------------------------------------
# Millwright (occupation) lets you replace up to 2 of the fence bill's building resources with
# grain (1:1), capped PER ACTION. It is a normal `build_fence` conversion checked against the
# WHOLE-ACTION RUNNING TOTAL — both during building (`_check_entry_legal`'s
# `running = accrued_cost.wood + this_pasture_paid`) and at the Proceed settle
# (`effective_payments` over the final `accrued_cost.wood`). So:
#   * during building it ENABLES a grain-funded build the wood alone couldn't afford (the §2
#     running-total fix — the earlier settle-only gate that hid Millwright here is gone), and
#   * at settle a >1-option bill surfaces a `PendingChooseCost` (action_kind="build_fence")
#     wood/grain menu; picking the convert option debits (N-k) wood + k grain, then the
#     after-grants fire. A bill with one affordable payment settles inline (no menu).
# The 2-grain cap is counted ONCE against the whole-action total, never re-granted per pasture.
# Without Millwright the settle frontier is a singleton (no menu).

def _millwright_setup(*, wood, grain, pre_pasture=None):
    """A CARDS-mode fencing state owning Millwright (NOT Hedge Keeper, so the whole
    bill is paid — no free fences) with the given wood + grain on hand."""
    state = _fencing_setup(wood=wood)
    state = with_resources(state, 0, wood=wood, grain=grain)
    state = fast_replace(state, mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    p = state.players[0]
    p = fast_replace(p, occupations=p.occupations | {MILLWRIGHT_ID})
    state = fast_replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    return state


def _grain(state, idx=0):
    return state.players[idx].resources.grain


def test_millwright_settle_surfaces_payment_menu():
    # 5-edge build (pre-1x1 at (0,2) + adjacent top 1x2) -> accrued 5 wood. Millwright +
    # ample wood/grain: the Proceed settle pauses on a PendingChooseCost with >1 options.
    state = _millwright_setup(wood=20, grain=5, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    assert state.pending_stack[-1].free_fence_budget == 0   # Millwright frees nothing
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 5   # full bill accrued (no frees)
    assert _wood(state) == 20                                # nothing debited yet
    # Proceed: the settle finds >1 payment and pauses on the menu (no debit, no after yet).
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingChooseCost)
    assert top.action_kind == "build_fence"
    # Underneath the menu the paused before-phase build host survives.
    assert isinstance(state.pending_stack[-2], PendingBuildFences)
    assert state.pending_stack[-2].phase == "before"
    options = {a.payment for a in legal_actions(state)
               if isinstance(a, CommitChooseCost)}
    # Up to 2 of the 5 wood may become grain (1:1), per-action budget 2.
    assert options == {
        Resources(wood=5),                       # all wood (decline the conversion)
        Resources(wood=4, grain=1),              # 1 wood -> 1 grain
        Resources(wood=3, grain=2),              # 2 wood -> 2 grain
    }
    assert _wood(state) == 20                                # still nothing debited


def test_millwright_settle_choose_convert_two_then_grants_fire():
    # Choose the convert-2-to-grain option: debits 3 wood + 2 grain, the menu pops, the
    # paused settle completes (accrued zeroed), the after-grants fire, the action ends.
    state = _millwright_setup(wood=20, grain=5, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    state = step(state, Proceed())
    assert isinstance(state.pending_stack[-1], PendingChooseCost)
    state = step(state, CommitChooseCost(payment=Resources(wood=3, grain=2)))
    # The menu popped; the build host flipped to its after-phase (grants fired). The
    # remaining stack is PendingBuildFences (after) + PendingSubActionSpace; both drained
    # by Stop, exactly as the singleton path's _finish does.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.phase == "after"                  # _enter_after_phase ran (grants fired)
    assert top.accrued_cost.wood == 0            # settle completed: accrued zeroed
    assert _wood(state) == 17                     # 20 - 3 wood
    assert _grain(state) == 3                     # 5 - 2 grain
    state = step(state, Stop())                   # pop PendingBuildFences
    state = step(state, Stop())                   # pop PendingSubActionSpace
    assert not any(isinstance(f, (PendingBuildFences, PendingChooseCost))
                   for f in state.pending_stack)


def test_millwright_settle_choose_all_wood_pays_n_wood():
    # Choosing the all-wood option pays the full N (=5) wood, 0 grain.
    state = _millwright_setup(wood=20, grain=5, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    state = step(state, Proceed())
    state = step(state, CommitChooseCost(payment=Resources(wood=5)))
    assert isinstance(state.pending_stack[-1], PendingBuildFences)
    assert state.pending_stack[-1].phase == "after"
    assert _wood(state) == 15                      # 20 - 5 wood
    assert _grain(state) == 5                       # grain untouched


def test_no_menu_without_millwright_singleton_settle():
    # Regression: WITHOUT Millwright the settle is a singleton (no PendingChooseCost) even
    # with grain on hand — Proceed debits inline and flips straight to the after-phase.
    state = _cards_setup(wood=20, own_card=False, pre_pasture=_PRE_1x1)
    state = with_resources(state, 0, wood=20, grain=5)   # grain present but unusable
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 5
    state = step(state, Proceed())
    # No menu — straight to the after-phase build host (singleton inline debit).
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.phase == "after"
    assert _wood(state) == 15                        # 20 - 5 wood, no conversion
    assert _grain(state) == 5                         # grain untouched (no Millwright)


def test_millwright_enables_grain_funded_build_during_building():
    # The §2 running-total fix: Millwright is now VISIBLE to the per-pasture during-building
    # affordability (checked on the running total), so it ENABLES a build the wood alone
    # couldn't afford. 3 wood + 2 grain + Millwright: the 5-edge layout's running total is 5,
    # payable as 3 wood + 2 grain (Millwright converts 2). The OLD settle-only gate hid
    # Millwright during building, so 5 > 3 wood made this layout illegal; now it is offered.
    state = _millwright_setup(wood=3, grain=2, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    assert state.pending_stack[-1].free_fence_budget == 0   # Millwright frees nothing
    commits = {a.cells for a in legal_actions(state)
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 in commits, "5-edge build is grain-fundable (3 wood + 2 grain), now legal"
    # Build it and settle: the only affordable payment is 3 wood + 2 grain (a singleton — all-
    # wood and 4-wood+1-grain need >3 wood), so it pays inline, ending at 0 wood / 0 grain.
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 5
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences) and top.phase == "after"   # singleton inline settle
    assert _wood(state) == 0                      # 3 - 3
    assert _grain(state) == 0                     # 2 - 2


def test_millwright_two_grain_cap_bounds_during_building():
    # The per-action cap is 2: with 1 wood + 5 grain the 5-edge layout is STILL not offered,
    # because Millwright can convert only 2 of the 5 wood (1 wood + 2 grain = 3 < 5). This is
    # now the running total honoring the cap — not the old "Millwright invisible" gate. Extra
    # grain beyond 2 does not help, proving the cap is counted once against the whole action.
    state = _millwright_setup(wood=1, grain=5, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    commits = {a.cells for a in legal_actions(state)
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 not in commits, "5-edge needs >2 of the wood as grain; the 2-cap blocks it"


# ---------------------------------------------------------------------------
# Rammed Clay: clay substitutes for wood, 1:1, UNLIMITED (COST_MODIFIER_DESIGN.md §9)
# ---------------------------------------------------------------------------
# Rammed Clay (minor) — "You can use clay instead of wood to build fences" (both in one
# action, any split). A plain per-edge conversion (no per-action cap): the fence bill's wood
# may be paid as any wood/clay mix. So the settle surfaces every affordable wood/clay split as
# a PendingChooseCost menu, and — because affordability is the running total — clay ENABLES a
# wood-tight build. On play it also gives +1 clay.

def _rammed_clay_setup(*, wood, clay, pre_pasture=None):
    """A CARDS-mode fencing state owning Rammed Clay (NOT Hedge Keeper) with the given
    wood + clay on hand."""
    state = _fencing_setup(wood=wood)
    state = with_resources(state, 0, wood=wood, clay=clay)
    state = fast_replace(state, mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    p = state.players[0]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {RAMMED_CLAY_ID})
    state = fast_replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    return state


def _clay(state, idx=0):
    return state.players[idx].resources.clay


def test_rammed_clay_on_play_gives_clay():
    from agricola.cards.specs import MINORS
    assert RAMMED_CLAY_ID in MINORS
    s = _fencing_setup(wood=1)
    before = _clay(s)
    s2 = MINORS[RAMMED_CLAY_ID].on_play(s, 0)
    assert _clay(s2) == before + 1


def test_rammed_clay_settle_menu_lists_every_split():
    # 5-edge build -> accrued 5 wood. With ample wood + clay the settle menu lists all 6
    # wood/clay splits (Pareto-incomparable — wood and clay are different goods).
    state = _rammed_clay_setup(wood=20, clay=20, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 5
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingChooseCost) and top.action_kind == "build_fence"
    options = {a.payment for a in legal_actions(state)
               if isinstance(a, CommitChooseCost)}
    assert options == {Resources(wood=5 - k, clay=k) for k in range(6)}


def test_rammed_clay_enables_clay_funded_build_during_building():
    # The running-total fix applied to a conversion: 2 wood + 3 clay can build the 5-edge
    # layout (pay 2 wood + 3 clay), which is unaffordable on wood alone. The during-building
    # legality offers it; the settle pays the only affordable split (2 wood + 3 clay) inline.
    state = _rammed_clay_setup(wood=2, clay=3, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    commits = {a.cells for a in legal_actions(state)
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 in commits, "5-edge is clay-fundable (2 wood + 3 clay), now legal"
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences) and top.phase == "after"   # singleton inline settle
    assert _wood(state) == 0                      # 2 - 2
    assert _clay(state) == 0                       # 3 - 3


def test_clay_does_not_pay_fences_without_rammed_clay():
    # Regression: clay funds fences ONLY with Rammed Clay. 2 wood + 3 clay, no card -> the
    # 5-edge layout (full 5 wood) is unaffordable and not offered.
    state = _cards_setup(wood=2, own_card=False, pre_pasture=_PRE_1x1)
    state = with_resources(state, 0, wood=2, clay=3)
    state = _enter_build_fences(state)
    commits = {a.cells for a in legal_actions(state)
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 not in commits, "clay can't pay fences without Rammed Clay"


# ---------------------------------------------------------------------------
# Briar Hedge: POSITIONAL per-edge frees — board-perimeter edges cost no wood (§9.4 source 1)
# ---------------------------------------------------------------------------
# Briar Hedge (minor) — "You do not need to pay wood for fences that you build on the edge of
# your farmyard board." Ungated (any fence build). A fresh top-1x2 adjacent to a pre-1x1 at
# (0,2) encloses 5 new edges, of which 3 sit on the board edge (the two top edges + the right
# edge of (0,4)) and 2 are interior (the two bottom edges) -> 2 wood paid with Briar Hedge.
# An INTERIOR 1x1 at (1,1) has 0 perimeter edges, so Briar Hedge frees nothing there.

_INTERIOR_1x1 = frozenset({(1, 1)})     # a fresh first pasture with NO board-edge edges


def _briar_setup(*, wood, pre_pasture=None):
    """A CARDS-mode fencing state owning Briar Hedge with the given wood (no other fence
    card). The prereq (1 animal of each type) gates PLAY, not the effect, so the owned card
    frees perimeter edges regardless of animals held."""
    state = _fencing_setup(wood=wood)
    state = fast_replace(state, mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    p = state.players[0]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {BRIAR_HEDGE_ID})
    state = fast_replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    return state


def test_briar_hedge_prereq_one_of_each_animal():
    from agricola.cards.specs import MINORS, prereq_met
    spec = MINORS[BRIAR_HEDGE_ID]
    s = _fencing_setup(wood=1)                                  # no animals
    assert not prereq_met(spec, s, 0)
    assert prereq_met(spec, with_animals(s, 0, sheep=1, boar=1, cattle=1), 0)
    assert not prereq_met(spec, with_animals(s, 0, sheep=1, boar=1), 0)   # missing cattle


def test_briar_hedge_perimeter_edges_free():
    # 5-edge layout: 3 board-edge edges free -> accrued 2 wood (the 2 interior edges).
    state = _briar_setup(wood=20, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    top = state.pending_stack[-1]
    assert top.accrued_cost.wood == 2          # 5 new edges - 3 on the board edge
    assert _wood(state) == 20                    # nothing debited per-commit in CARDS
    state = _finish(state)
    assert _wood(state) == 18                    # 20 - 2


def test_briar_hedge_frees_nothing_for_interior_pasture():
    # A fresh interior 1x1 at (1,1) has 4 edges, NONE on the board edge -> Briar Hedge frees
    # nothing, full 4 wood accrued.
    state = _briar_setup(wood=20)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_INTERIOR_1x1))
    assert state.pending_stack[-1].accrued_cost.wood == 4    # no perimeter edges, full price
    state = _finish(state)
    assert _wood(state) == 16                                 # 20 - 4


def test_briar_hedge_enables_tight_wood_perimeter_build():
    # 2 wood + Briar Hedge: the 5-edge layout is offered (pays 2 after the 3 perimeter frees)
    # and built, ending at 0 wood. Without the card it needs the full 5 wood (illegal at 2).
    state = _briar_setup(wood=2, pre_pasture=_PRE_1x1)
    commits = {a.cells for a in legal_actions(_enter_build_fences(state))
               if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 in commits, "5-edge build pays 2 wood after perimeter frees"
    no_card = _cards_setup(wood=2, own_card=False, pre_pasture=_PRE_1x1)
    no_card_commits = {a.cells for a in legal_actions(_enter_build_fences(no_card))
                       if isinstance(a, CommitBuildPasture)}
    assert _TOP_1x2_34 not in no_card_commits, "without Briar Hedge the full 5 wood is unaffordable"
    # Full flow to zero wood.
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 2
    state = _finish(state)
    assert _wood(state) == 0                                   # 2 - 2
