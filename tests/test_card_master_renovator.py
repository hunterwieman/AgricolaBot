"""Tests for Master Renovator (occupation, deck E #87; Ephipparius Expansion).

Card text (verbatim): "At the end of the work phases of rounds 7 and 9, you
can take a "Renovation" action without placing a person and pay 1 building
resource of your choice less."

USER RULING (2026-07-14): "at the end of the work phases" = the round-end
ladder's ``end_of_work`` rung (position 0 — still during the work phase,
running once every worker is placed).

The tests drive the REAL round-end walk (`_advance_until_decision` on a
drained WORK state — the tests/test_round_end_ladder.py idiom): the ladder
pauses at the `end_of_work` window frame on rounds 7/9 when the grant is
eligible; firing pushes a `PendingRenovate` with the card's provenance, whose
enumerator surfaces the discounted payment frontier (the `CostCtx.granted_by`
seam, commit 700d16a). Rounds 7 and 9 are harvest rounds — the round-end
ladder runs BEFORE the harvest, so assertions stop once the renovate has
resolved (the walk then runs into the harvest's own frames). The
no-discount-on-a-space-renovate pin drives a real House Redevelopment
placement (the tests/test_cost_modifiers.py idiom).
"""
from __future__ import annotations

import agricola.cards.master_renovator  # noqa: F401  (registers the card)

import dataclasses

import pytest

from agricola.actions import (
    ChooseSubAction, CommitRenovate, FireTrigger, PlaceWorker, Proceed, Stop,
)
from agricola.cards.cost_mods import CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import (
    with_current_player, with_house, with_resources, with_space,
)

CARD_ID = "master_renovator"


# ---------------------------------------------------------------------------
# Helpers (the test_round_end_ladder.py / test_card_informant.py idioms)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occupation(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _hand_occupation(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx,
                        hand_occupations=p.hand_occupations | {card_id})


def _drained_work_state(seed=0, round_number=7):
    """A WORK state with every person placed — the round-end ladder runs next
    (its WORK segment opens with the end_of_work window)."""
    state = setup(seed)
    state = dataclasses.replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _mr_state(*, round_number=7, owned=True, house=HouseMaterial.WOOD, **res):
    """A drained WORK state; P0 (optionally) owns Master Renovator with the
    given house material and supply."""
    state = _drained_work_state(round_number=round_number)
    if owned:
        state = _own_occupation(state, 0, CARD_ID)
    state = with_house(state, 0, house)
    if res:
        state = with_resources(state, 0, **res)
    return state


def _walk_to_window(state):
    """Advance to P0's end_of_work window frame (the ladder pauses there)."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no end_of_work window surfaced (top={top!r}, phase={state.phase})")
    assert top.window_id == "end_of_work" and top.player_idx == 0
    return state


def _no_end_of_work_pause(state):
    """Advance and assert the walk never pauses at an end_of_work window
    (the trigger was ineligible / unowned, so no frame was ever pushed)."""
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == "end_of_work"
        for f in state.pending_stack)
    return state


def _mr_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _renovate_payments(state):
    return [a for a in legal_actions(state) if isinstance(a, CommitRenovate)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    entry = CARDS[CARD_ID]
    assert entry.event == "end_of_work"       # the ruled rung (2026-07-14)
    assert entry.mandatory is False           # "you can"
    # The discount conversion is registered on the renovate cost (subset check).
    assert any(cid == CARD_ID
               for _order, cid, _fn, _rec in CONVERSIONS.get("renovate", ()))


def test_on_play_is_noop():
    state = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state


# ---------------------------------------------------------------------------
# Round gating: only the end of rounds 7 and 9's work phases
# ---------------------------------------------------------------------------

def test_not_offered_outside_rounds_7_and_9():
    """Round 5's round end: affordable, owned — but the wrong round, so the
    window never hosts and the walk reaches PREPARATION untouched."""
    state = _mr_state(round_number=5, clay=2, reed=1)
    out = _no_end_of_work_pause(state)
    assert out.players[0].resources.clay == 2
    assert out.players[0].house_material == HouseMaterial.WOOD


def test_offered_at_end_of_round_7_work_phase():
    state = _walk_to_window(_mr_state(round_number=7, clay=2, reed=1))
    assert _mr_fires(state) == [FireTrigger(card_id=CARD_ID)]
    assert Proceed() in legal_actions(state)  # declinable


def test_round_9_fires_again_and_covers_the_stone_tier():
    """Round 9 is a fresh window frame — the grant fires again. A CLAY house
    renovates to STONE: printed 2 stone + 1 reed, discount variants 1 stone
    + 1 reed and 2 stone + 0 reed (the printed cost is Pareto-dominated)."""
    state = _walk_to_window(_mr_state(
        round_number=9, house=HouseMaterial.CLAY, stone=2, reed=1))
    state = step(state, FireTrigger(card_id=CARD_ID))
    payments = _renovate_payments(state)
    assert {a.payment for a in payments} == {
        Resources(stone=1, reed=1), Resources(stone=2)}
    assert all(a.to_material == HouseMaterial.STONE for a in payments)
    state = step(state, CommitRenovate(
        payment=Resources(stone=2), to_material=HouseMaterial.STONE))
    p = state.players[0]
    assert p.house_material == HouseMaterial.STONE
    assert p.resources.stone == 0             # paid exactly 2 stone
    assert p.resources.reed == 1              # the reed was the "1 less"


# ---------------------------------------------------------------------------
# The fire: a granted renovate with the discounted payment frontier
# ---------------------------------------------------------------------------

def test_fire_pushes_granted_renovate_with_discounted_frontier():
    """2-room WOOD house, 2 clay + 1 reed held: printed cost 2 clay + 1 reed;
    the discount surfaces (1 clay + 1 reed) and (2 clay + 0 reed) — one per
    nonzero component — and the printed cost is Pareto-dominated away.
    Committing the clay-discounted payment debits exactly it and upgrades
    the house; the whole exchange happens without placing a person."""
    state = _walk_to_window(_mr_state(round_number=7, clay=2, reed=1))
    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingRenovate)
    assert top.initiated_by_id == f"card:{CARD_ID}"

    payments = _renovate_payments(state)
    assert {a.payment for a in payments} == {
        Resources(clay=1, reed=1), Resources(clay=2)}

    state = step(state, CommitRenovate(
        payment=Resources(clay=1, reed=1), to_material=HouseMaterial.CLAY))
    p = state.players[0]
    assert p.house_material == HouseMaterial.CLAY
    assert p.resources.clay == 1              # debited exactly 1 clay...
    assert p.resources.reed == 0              # ...and the 1 reed

    # The renovate host flips to its after phase; Stop returns to the window,
    # where the frame's triggers_resolved swallows a re-offer (once per window).
    assert Stop() in legal_actions(state)
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(state) == [Proceed()]

    # Proceeding runs the rest of the ladder into round 7's harvest.
    state = step(state, Proceed())
    assert state.players[0].house_material == HouseMaterial.CLAY


def test_discount_makes_an_otherwise_unaffordable_renovate_reachable():
    """1 clay + 1 reed held: the printed 2 clay + 1 reed is unaffordable, but
    the discounted (1 clay + 1 reed) is — the grant is offered, and that is
    the frontier's only entry."""
    state = _walk_to_window(_mr_state(round_number=7, clay=1, reed=1))
    state = step(state, FireTrigger(card_id=CARD_ID))
    payments = _renovate_payments(state)
    assert [a.payment for a in payments] == [Resources(clay=1, reed=1)]


def test_ineligible_when_unaffordable_even_with_discount():
    """0 clay + 1 reed: no payment — printed or discounted — is affordable,
    so the grant is never offered (no dead-end) and the walk runs on into
    round 7's harvest untouched."""
    state = _mr_state(round_number=7, clay=0, reed=1)
    out = _no_end_of_work_pause(state)
    assert out.players[0].house_material == HouseMaterial.WOOD
    assert out.players[0].resources.reed == 1


def test_ineligible_with_a_stone_house():
    """A STONE house has no renovate target — the grant is never offered."""
    state = _mr_state(round_number=7, house=HouseMaterial.STONE,
                      clay=5, stone=5, reed=5)
    out = _no_end_of_work_pause(state)
    assert out.players[0].house_material == HouseMaterial.STONE


# ---------------------------------------------------------------------------
# Declining, ownership, and the opponent
# ---------------------------------------------------------------------------

def test_declinable_leaves_everything_unchanged():
    state = _walk_to_window(_mr_state(round_number=7, clay=2, reed=1))
    assert _mr_fires(state) != []             # it was on offer
    state = step(state, Proceed())
    p = state.players[0]
    assert p.house_material == HouseMaterial.WOOD
    assert p.resources.clay == 2
    assert p.resources.reed == 1


def test_unowned_never_hosts():
    state = _mr_state(round_number=7, owned=False, clay=2, reed=1)
    _no_end_of_work_pause(state)


def test_hand_only_is_inert():
    state = _mr_state(round_number=7, owned=False, clay=2, reed=1)
    state = _hand_occupation(state, 0, CARD_ID)
    _no_end_of_work_pause(state)


def test_opponent_unaffected():
    """Only the owner gets a window frame; the non-owner's house and supply
    are untouched by the owner's discounted renovate."""
    state = _mr_state(round_number=7, clay=2, reed=1)
    state = with_resources(state, 1, clay=2, reed=1)   # P1 could afford one too
    p1_before = state.players[1]
    state = _walk_to_window(state)                     # the frame is P0's
    state = step(state, FireTrigger(card_id=CARD_ID))
    state = step(state, CommitRenovate(
        payment=Resources(clay=1, reed=1), to_material=HouseMaterial.CLAY))
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert state.pending_stack[-1].player_idx == 0     # no P1 frame beneath
    assert len(state.pending_stack) == 1
    assert state.players[1].resources == p1_before.resources
    assert state.players[1].house_material == p1_before.house_material


# ---------------------------------------------------------------------------
# The discount is scoped to THIS grant — a space renovate pays full price
# ---------------------------------------------------------------------------

def test_normal_house_redevelopment_renovate_not_discounted():
    """Owning Master Renovator does NOT discount a House Redevelopment
    renovate (the conversion is scoped to ctx.granted_by, which is None for
    every space-initiated renovate): the frontier is the printed cost only."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_house(state, 0, HouseMaterial.WOOD)
    state = with_resources(state, 0, clay=2, reed=1)
    state = with_space(state, "house_redevelopment", revealed=True)
    state = _own_occupation(state, 0, CARD_ID)

    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    payments = _renovate_payments(state)
    assert [a.payment for a in payments] == [Resources(clay=2, reed=1)]


# ---------------------------------------------------------------------------
# The conversion generator (unit pins)
# ---------------------------------------------------------------------------

def test_expand_passes_ungranted_ctx_through_unchanged():
    from agricola.cards.master_renovator import _expand
    from agricola.legality import _renovate_ctx

    state = setup(0)
    p = state.players[0]
    cost = Resources(clay=2, reed=1)
    ctx = _renovate_ctx(p, HouseMaterial.CLAY)             # granted_by=None
    assert _expand(state, 0, ctx, cost) == [cost]
    other = _renovate_ctx(p, HouseMaterial.CLAY, granted_by="card:cottager")
    assert _expand(state, 0, other, cost) == [cost]        # someone else's grant


def test_expand_offers_one_variant_per_nonzero_component_never_negative():
    from agricola.cards.master_renovator import _expand
    from agricola.legality import _renovate_ctx

    state = setup(0)
    p = state.players[0]
    ctx = _renovate_ctx(p, HouseMaterial.CLAY, granted_by=f"card:{CARD_ID}")
    out = _expand(state, 0, ctx, Resources(clay=2, reed=1))
    assert out == [
        Resources(clay=2, reed=1),        # the unchanged cost (contract)
        Resources(clay=1, reed=1),        # 1 clay less
        Resources(clay=2, reed=0),        # 1 reed less
    ]
    # A zero component is never offered (and nothing goes negative).
    out = _expand(state, 0, ctx, Resources(reed=1))
    assert out == [Resources(reed=1), Resources()]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
