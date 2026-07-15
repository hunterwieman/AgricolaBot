import agricola.cards.master_fencer  # noqa: F401  (registers the card)

"""Tests for Master Fencer (occupation, Ephipparius E88): "Once you live in a
stone house, at the start of each round, you can pay 2 or 3 wood to build up
to 3 or 4 fences, respectively."

A stone-house-gated start-of-round optional play-variant trigger (Scholar /
Plow Driver's family): variants "2w_3f" (pay 2 wood, up to 3 fences) and
"3w_4f" (pay 3 wood, up to 4 fences). The wood is PREPAID at the fire; the
fences are free via the frame's `free_fence_budget`, and
`FenceRestrictions(max_edges=N)` (user-blessed 2026-07-15) forbids placing
more than N new edges across the whole grant.
"""
from agricola.actions import CommitBuildPasture, FireTrigger, Proceed, Stop
from agricola.cards.master_fencer import CARD_ID, FRAME_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import GameMode, HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.fences import NUM_COLS, compute_new_fence_edges
from agricola.legality import legal_actions
from agricola.pending import (
    FenceRestrictions,
    PendingBuildFences,
    PendingHarvestWindow,
    push,
)
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_resources
from tests.test_fencing import _with_initial_pasture

# A U-shaped pasture whose notch (0, 2) is enclosable with a SINGLE new edge
# (three sides shared with the U, the fourth is the board perimeter).
_U = [(0, 1), (0, 3), (1, 1), (1, 2), (1, 3)]
_NOTCH = frozenset({(0, 2)})            # 1 new edge
_BELOW = frozenset({(2, 2)})            # 1×1 under the U's base: 3 new edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cards_state(*, wood=0, stone=True, pre_pasture=None, supply=None, owned=True):
    """Cards-mode state: P0 owns the occupation (unless owned=False), optionally
    lives in stone, has `wood`, and optionally starts with an enclosed pasture."""
    s = fast_replace(setup(0), mode=GameMode.CARDS)
    s = with_resources(s, 0, wood=wood)
    if pre_pasture is not None:
        s = _with_initial_pasture(s, 0, pre_pasture)
    p = s.players[0]
    if owned:
        p = fast_replace(p, occupations=p.occupations | {CARD_ID})
    if stone:
        p = fast_replace(p, house_material=HouseMaterial.STONE)
    if supply is not None:
        p = fast_replace(p, fences_in_supply=supply)
    return fast_replace(s, players=(p, s.players[1]))


def _host(state, idx=0):
    """A WORK state with a start_of_round window choice host for `idx` on top
    (the synthetic-frame idiom: popping the frame ends the turn)."""
    return push(fast_replace(state, phase=Phase.WORK),
                PendingHarvestWindow(window_id="start_of_round", player_idx=idx))


def _offered_variants(state):
    return [a.variant for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _commits(state):
    return [a for a in legal_actions(state) if isinstance(a, CommitBuildPasture)]


def _new_edges(state, idx, cells):
    """New fence edges the commit `cells` would place on idx's current farmyard."""
    farmyard = state.players[idx].farmyard
    cells_bm = sum(1 << (r * NUM_COLS + c) for (r, c) in cells)
    _h, _v, cost = compute_new_fence_edges(farmyard, cells_bm)
    return cost


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    entries = {e.card_id: e for e in TRIGGERS.get("start_of_round", [])}
    assert CARD_ID in entries                      # subset check, never exact-set
    assert entries[CARD_ID].mandatory is False     # optional ("you can")
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# ---------------------------------------------------------------------------
# The stone-house gate (a standing per-round gate)
# ---------------------------------------------------------------------------

def test_no_offer_in_wood_house():
    s = _host(_cards_state(wood=5, stone=False, pre_pasture=[(1, 1)]))
    assert legal_actions(s) == [Proceed()]


def test_no_offer_in_clay_house():
    s = _cards_state(wood=5, stone=False, pre_pasture=[(1, 1)])
    p = fast_replace(s.players[0], house_material=HouseMaterial.CLAY)
    s = _host(fast_replace(s, players=(p, s.players[1])))
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Variant eligibility: wood on hand + a pasture buildable within N edges
# ---------------------------------------------------------------------------

def test_two_wood_offers_only_3_fence_variant():
    # An existing 1×1 lets an adjacent 1×1 complete with 3 new edges.
    s = _host(_cards_state(wood=2, pre_pasture=[(1, 1)]))
    assert _offered_variants(s) == ["2w_3f"]


def test_three_wood_offers_both():
    s = _host(_cards_state(wood=3, pre_pasture=[(1, 1)]))
    assert _offered_variants(s) == ["2w_3f", "3w_4f"]


def test_one_wood_offers_nothing():
    s = _host(_cards_state(wood=1, pre_pasture=[(1, 1)]))
    assert legal_actions(s) == [Proceed()]


def test_virgin_farm_2w_3f_not_offered():
    # A first pasture is a full 1×1 boundary = 4 edges > 3, so the 3-fence
    # variant has no legal pasture on a virgin farm and must not be offered.
    s = _host(_cards_state(wood=2))
    assert legal_actions(s) == [Proceed()]


def test_virgin_farm_three_wood_offers_only_4_fence_variant():
    s = _host(_cards_state(wood=3))
    assert _offered_variants(s) == ["3w_4f"]


# ---------------------------------------------------------------------------
# Firing 2w_3f: prepaid wood, free fences, the max_edges cap
# ---------------------------------------------------------------------------

def test_fire_2w_3f_debits_2_and_caps_at_3_edges():
    # wood=6 so a 5-edge candidate would be AFFORDABLE through the Cards
    # deferred tally (paid 5-3=2 <= 4 left) — only max_edges may exclude it.
    s = _host(_cards_state(wood=6, pre_pasture=[(1, 1)]))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="2w_3f"))

    assert s.players[0].resources.wood == 4        # exactly 2 debited, at the fire
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.initiated_by_id == FRAME_ID
    assert top.build_fences_action is False        # a card effect, not the literal action
    assert top.free_fence_budget == 3              # the 3 fences are free
    assert top.restrictions == FenceRestrictions(max_edges=3)

    commits = _commits(s)
    assert commits
    for a in commits:                              # every offer fits the cap
        assert _new_edges(s, 0, a.cells) <= 3
    # The 5-new-edge domino next to the 1×1 is affordable but over the cap.
    domino = frozenset({(1, 2), (1, 3)})
    assert _new_edges(s, 0, domino) == 5
    assert CommitBuildPasture(cells=domino) not in commits


def test_same_domino_offered_without_max_edges():
    # Control for the cap pin above: an otherwise-identical unrestricted card
    # grant (same free budget, same wood) DOES offer the 5-edge domino — so its
    # exclusion under the restricted frame is the max_edges filter, nothing else.
    s = _cards_state(wood=4, pre_pasture=[(1, 1)])
    s = push(fast_replace(s, phase=Phase.WORK), PendingBuildFences(
        player_idx=0, initiated_by_id=FRAME_ID,
        build_fences_action=False, free_fence_budget=3))
    assert CommitBuildPasture(cells=frozenset({(1, 2), (1, 3)})) in _commits(s)


def test_2w_3f_build_is_free_and_settle_bills_nothing():
    s = _host(_cards_state(wood=2, pre_pasture=[(1, 1)]))
    supply_before = s.players[0].fences_in_supply
    s = step(s, FireTrigger(card_id=CARD_ID, variant="2w_3f"))
    assert s.players[0].resources.wood == 0        # the prepaid 2

    s = step(s, CommitBuildPasture(cells=frozenset({(1, 2)})))   # 3 new edges
    top = s.pending_stack[-1]
    assert top.accrued_cost.wood == 0              # covered by the free budget
    assert top.fences_built == 3
    assert s.players[0].resources.wood == 0        # no per-commit debit
    assert s.players[0].fences_in_supply == supply_before - 3   # pieces from supply

    # Cap reached: any further pasture needs >= 1 new edge, so no more commits.
    assert not _commits(s)
    s = step(s, Proceed())                         # settle: bills NOTHING
    assert s.players[0].resources.wood == 0
    s = step(s, Stop())                            # pop back to the window host
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(s) == [Proceed()]         # once per round: latched


def test_virgin_farm_3w_4f_builds_the_1x1_free():
    s = _host(_cards_state(wood=3))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="3w_4f"))
    assert s.players[0].resources.wood == 0        # the prepaid 3
    s = step(s, CommitBuildPasture(cells=frozenset({(1, 1)})))   # 4 edges, all free
    top = s.pending_stack[-1]
    assert top.fences_built == 4
    assert top.accrued_cost.wood == 0
    assert s.players[0].fences_in_supply == 15 - 4
    assert not _commits(s)                         # cap exhausted
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 0        # 0 extra wood
    assert len(s.players[0].farmyard.pastures) == 1


# ---------------------------------------------------------------------------
# The cap is incremental across commits (the U-notch farm)
# ---------------------------------------------------------------------------

def test_cap_counts_edges_across_commits():
    # U-shaped pasture: the notch (0,2) completes with 1 edge; the 1×1 below the
    # base, (2,2), needs 3. Under 2w_3f (cap 3), both are offered initially; after
    # committing the 3-edge pasture the 1-edge notch no longer fits (3+1 > 3).
    s = _host(_cards_state(wood=2, pre_pasture=_U, supply=15))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="2w_3f"))
    offered = {a.cells for a in _commits(s)}
    assert _NOTCH in offered and _BELOW in offered
    s = step(s, CommitBuildPasture(cells=_BELOW))  # 3 edges: cap exhausted
    assert s.pending_stack[-1].fences_built == 3
    assert _NOTCH not in {a.cells for a in _commits(s)}
    assert not _commits(s)


def test_up_to_stopping_early_with_an_alternative_live():
    # "Up to": under 3w_4f (cap 4), commit only the 1-edge notch; the 3-edge
    # pasture below is STILL offered (1+3 <= 4), but the player may Proceed anyway.
    s = _host(_cards_state(wood=3, pre_pasture=_U, supply=15))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="3w_4f"))
    s = step(s, CommitBuildPasture(cells=_NOTCH))  # 1 edge
    assert _BELOW in {a.cells for a in _commits(s)}   # more building available
    assert Proceed() in legal_actions(s)
    s = step(s, Proceed())                         # stop early after 1 pasture
    assert s.players[0].resources.wood == 0        # only the prepaid 3, nothing more
    s = step(s, Stop())
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)


# ---------------------------------------------------------------------------
# Optionality, once per round, opponent, hand-only
# ---------------------------------------------------------------------------

def test_declinable_via_proceed():
    s = _host(_cards_state(wood=3, pre_pasture=[(1, 1)]))
    before = s.players[0]
    s = step(s, Proceed())                         # decline: nothing happened
    assert s.players[0].resources == before.resources
    assert s.players[0].farmyard == before.farmyard
    assert s.pending_stack == ()
    assert CARD_ID not in s.players[0].used_this_round


def test_once_per_round_across_host_visits():
    s = _host(_cards_state(wood=5, pre_pasture=[(1, 1)]))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="2w_3f"))
    assert CARD_ID in s.players[0].used_this_round
    s = step(s, CommitBuildPasture(cells=frozenset({(1, 2)})))
    s = step(s, Proceed())
    s = step(s, Stop())
    s = step(s, Proceed())                         # close the window host
    # A second host visit in the SAME round (fresh frame) is still latched out,
    # even with 3 wood left and a buildable pasture.
    s2 = _host(s)
    assert legal_actions(s2) == [Proceed()]


def test_opponent_unaffected():
    s = _host(_cards_state(wood=2, pre_pasture=[(1, 1)]))
    before = s.players[1]
    s = step(s, FireTrigger(card_id=CARD_ID, variant="2w_3f"))
    s = step(s, CommitBuildPasture(cells=frozenset({(1, 2)})))
    s = step(s, Proceed())
    assert s.players[1].resources == before.resources
    assert s.players[1].farmyard == before.farmyard


def test_hand_only_inert():
    # Card in HAND only (not played) → the trigger must not surface.
    s = _cards_state(wood=5, pre_pasture=[(1, 1)], owned=False)
    p = fast_replace(s.players[0], hand_occupations=frozenset({CARD_ID}))
    s = _host(fast_replace(s, players=(p, s.players[1])))
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# The REAL preparation ladder: fires at round entry, reoffers next round
# ---------------------------------------------------------------------------

def test_fires_on_real_start_of_round_window_and_reoffers_next_round():
    s = _cards_state(wood=6, pre_pasture=[(1, 1)])
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    out = _complete_preparation(s)
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round"
    assert top.player_idx == 0
    assert FireTrigger(card_id=CARD_ID, variant="2w_3f") in legal_actions(out)
    assert FireTrigger(card_id=CARD_ID, variant="3w_4f") in legal_actions(out)

    out = step(out, FireTrigger(card_id=CARD_ID, variant="2w_3f"))
    assert out.players[0].resources.wood == 4
    out = step(out, CommitBuildPasture(cells=frozenset({(1, 2)})))
    out = step(out, Proceed())                     # settle the fence grant (0 bill)
    out = step(out, Stop())                        # pop the fence frame
    out = step(out, Proceed())                     # close the window host
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()
    assert out.players[0].resources.wood == 4      # only the prepaid 2 spent

    # Next round: used_this_round clears at round entry, so it is offered again
    # (still stone-housed, 4 wood on hand, pastures to extend).
    nxt = fast_replace(out, phase=Phase.PREPARATION,
                       round_number=out.round_number + 1)
    nxt = _complete_preparation(nxt)
    top = nxt.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round"
    assert FireTrigger(card_id=CARD_ID, variant="2w_3f") in legal_actions(nxt)


def test_hand_only_inert_on_real_preparation():
    s = _cards_state(wood=6, pre_pasture=[(1, 1)], owned=False)
    p = fast_replace(s.players[0], hand_occupations=frozenset({CARD_ID}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    out = _complete_preparation(s)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert out.players[0].resources.wood == 6      # untouched
