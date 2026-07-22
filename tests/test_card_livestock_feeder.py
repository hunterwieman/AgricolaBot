import agricola.cards.livestock_feeder  # noqa: F401

"""Tests for Livestock Feeder (occupation, deck C #86; Consul Dirigens; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 grain. Each
grain in your supply can hold 1 animal of any type. (these animals count as
accommodated on your farm.)"

Ruling 74 (user, 2026-07-21): one FLEXIBLE slot per grain in supply
(`register_flexible_slots`, the Petting Zoo seam), and STRUCTURAL eviction — the
accommodation barrier (`engine._reconcile_accommodation`) consults the
volatile-capacity registry at every decision boundary; this card's registered
`_grain_dropped` keeps a last-boundary grain watermark in its CardStore entry,
reports a drop iff current grain < stored, and refreshes the stored value at
every owner boundary (writing only on change).
"""
from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitPlayOccupation,
    CommitSow,
    PlaceWorker,
)
from agricola.cards.capacity_mods import (
    FLEXIBLE_SLOT_CARDS,
    VOLATILE_CAPACITY_CARDS,
    extra_flexible_slots,
)
from agricola.cards.livestock_feeder import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import _advance_until_decision, _reconcile_accommodation, step
from agricola.helpers import accommodates, extract_slots, grant_animals
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import (
    with_animals,
    with_current_player,
    with_fields,
    with_majors,
    with_resources,
    with_space,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _no_accommodate_frame(state):
    return not any(isinstance(f, PendingAccommodate) for f in state.pending_stack)


def _accommodate_triples(state):
    return {(a.sheep, a.boar, a.cattle) for a in legal_actions(state)
            if isinstance(a, CommitAccommodate)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _fn in FLEXIBLE_SLOT_CARDS)
    assert any(cid == CARD_ID for cid, _fn in VOLATILE_CAPACITY_CARDS)


# ---------------------------------------------------------------------------
# On play: immediately get 1 grain
# ---------------------------------------------------------------------------

def test_on_play_grants_one_grain():
    s = setup(0)
    before = s.players[0].resources
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources == before + Resources(grain=1)
    assert out.players[1].resources == s.players[1].resources
    # No animals granted, no flag, and no watermark yet (that is the barrier's job
    # at the first decision boundary).
    assert not out.players[0].animals_need_accommodation
    assert out.players[0].card_state.get(CARD_ID) is None


_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def test_played_via_lessons_real_flow():
    """CARDS mode, the real Lessons flow: the card enters the tableau, +1 grain,
    and the first boundary after play stores the watermark at the current grain
    (missing stored value == current: no drop, no frame)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    grain_before = cs.players[cp].resources.grain

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))

    assert CARD_ID in cs.players[cp].occupations
    assert CARD_ID not in cs.players[cp].hand_occupations
    assert cs.players[cp].resources.grain == grain_before + 1
    # First owner boundary already ran inside step: watermark == current grain.
    assert cs.players[cp].card_state.get(CARD_ID) == cs.players[cp].resources.grain
    assert _no_accommodate_frame(cs)


# ---------------------------------------------------------------------------
# Capacity math: one flexible slot per grain, mixed types
# ---------------------------------------------------------------------------

def test_capacity_one_flexible_slot_per_grain_mixed_types():
    s = setup(0)
    s = with_resources(s, 0, grain=3)
    base_caps, base_flex = extract_slots(s, s.players[0])
    owner = _own_occ(s, 0).players[0]
    caps, flex = extract_slots(s, owner)
    assert caps == base_caps                     # pasture capacities untouched
    assert flex == base_flex + 3                 # +1 flexible slot per grain
    assert extra_flexible_slots(owner) == 3
    # Mixed types across the slots: house pet (1) + 3 grain slots = 4 animals of
    # three DIFFERENT types on a bare farm (a single-type bin never could).
    assert accommodates(s, owner, 2, 1, 1)
    assert not accommodates(s, owner, 2, 2, 1)   # 5 animals exceed the 4 slots
    assert not accommodates(s, s.players[0], 2, 1, 1)   # non-owner: pet only
    # Zero grain -> zero slots.
    z = with_resources(s, 0, grain=0)
    assert extra_flexible_slots(_own_occ(z, 0).players[0]) == 0


def test_card_in_hand_grants_nothing():
    s = setup(0)
    s = with_resources(s, 0, grain=3)
    held = fast_replace(s.players[0], hand_occupations=frozenset({CARD_ID}))
    assert extra_flexible_slots(held) == 0
    assert extract_slots(s, held) == extract_slots(s, s.players[0])


def test_market_flow_takes_extra_animals_on_grain_slots():
    """Real animal-market flow: with 2 grain the owner's frontier offers keeping
    all 3 accumulated sheep (pet + 2 grain slots); a non-owner maxes at 1."""
    def market_state(owned):
        s = setup(0)
        s = with_current_player(s, 0)
        s = with_space(s, "sheep_market", revealed=True, accumulated_amount=3)
        s = with_resources(s, 0, grain=2)
        if owned:
            s = _own_occ(s, 0)
        return step(s, PlaceWorker(space="sheep_market"))

    owner_triples = _accommodate_triples(market_state(owned=True))
    assert (3, 0, 0) in owner_triples
    non_owner_triples = _accommodate_triples(market_state(owned=False))
    assert max(t[0] for t in non_owner_triples) == 1

    s = step(market_state(owned=True), CommitAccommodate(sheep=3, boar=0, cattle=0))
    assert s.players[0].animals == Animals(sheep=3)


# ---------------------------------------------------------------------------
# Eviction end-to-end: spend grain via a real sow -> the barrier asks
# ---------------------------------------------------------------------------

def test_eviction_via_sow_real_flow():
    """House 2 sheep on pet + the 1 grain slot; sow the grain via the real Grain
    Utilization flow. At the next decision boundary the volatile re-check reports
    the drop and a PendingAccommodate surfaces with the keep-which choice;
    resolving cooks the excess sheep (Fireplace: 2 food)."""
    s = setup(0)
    s = with_current_player(s, 0)
    s = _own_occ(s, 0)
    s = with_resources(s, 0, grain=1)
    s = with_animals(s, 0, sheep=2)              # pet(1) + grain slot(1): exactly fits
    s = with_fields(s, 0, [(0, 2)])              # an empty field to sow into
    s = with_space(s, "grain_utilization", revealed=True)
    s = with_majors(s, owner_by_idx={0: 0})      # Fireplace: excess sheep -> 2 food
    assert accommodates(s, s.players[0], 2, 0, 0)

    s = step(s, PlaceWorker(space="grain_utilization"))
    # First owner boundary: the watermark is stored at the current grain, no drop.
    assert s.players[0].card_state.get(CARD_ID) == 1
    assert _no_accommodate_frame(s)

    s = step(s, ChooseSubAction(name="sow"))
    s = step(s, CommitSow(grain=1, veg=0))       # grain 1 -> 0: the slot vanishes

    top = s.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0
    assert s.players[0].card_state.get(CARD_ID) == 0   # watermark refreshed at the drop
    assert (1, 0, 0) in _accommodate_triples(s)  # the keep-which choice is surfaced

    food_before = s.players[0].resources.food
    s = step(s, CommitAccommodate(sheep=1, boar=0, cattle=0))
    p = s.players[0]
    assert p.animals == Animals(sheep=1)
    assert p.resources.food == food_before + 2   # the released sheep was cooked
    assert _no_accommodate_frame(s)


# ---------------------------------------------------------------------------
# The watermark: rise refreshes it; a partial drop that still fits asks nothing
# ---------------------------------------------------------------------------

def test_partial_drop_that_still_fits_raises_no_frame():
    """Grain 1 -> 2 (Grain Seeds; the boundary refreshes the watermark upward)
    then 2 -> 1 (sow): the drop is reported, but 2 sheep still fit pet + 1 grain
    slot, so NO accommodate frame appears."""
    s = setup(0)
    s = with_current_player(s, 0)
    s = _own_occ(s, 0)
    s = with_resources(s, 0, grain=1)
    s = with_animals(s, 0, sheep=2)
    s = with_fields(s, 0, [(0, 2)])
    s = with_space(s, "grain_utilization", revealed=True)
    s, pushed = _reconcile_accommodation(s)      # establish the watermark
    assert not pushed and s.players[0].card_state.get(CARD_ID) == 1

    s = step(s, PlaceWorker(space="grain_seeds"))    # grain 1 -> 2
    assert s.players[0].resources.grain == 2
    assert s.players[0].card_state.get(CARD_ID) == 2  # (d): refreshed upward
    assert _no_accommodate_frame(s)

    s = with_current_player(s, 0)                # p0 acts again (prefab turn order)
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="sow"))
    s = step(s, CommitSow(grain=1, veg=0))       # grain 2 -> 1: drop, but still fits

    assert s.players[0].animals == Animals(sheep=2)   # nothing evicted
    assert _no_accommodate_frame(s)
    assert s.players[0].card_state.get(CARD_ID) == 1


def test_rise_then_drop_back_is_not_masked():
    """The (d) soundness case: grain 1 -> 2, a 3rd sheep housed on the new slot,
    then grain 2 -> 1. A stale watermark of 1 would compare 1 < 1 and miss the
    violation; the per-boundary refresh means the drop IS caught and the
    accommodate frame surfaces."""
    s = setup(0)
    s = with_current_player(s, 0)
    s = _own_occ(s, 0)
    s = with_resources(s, 0, grain=1)
    s = with_animals(s, 0, sheep=2)
    s = with_fields(s, 0, [(0, 2)])
    s = with_space(s, "grain_utilization", revealed=True)
    s, _ = _reconcile_accommodation(s)           # watermark = 1

    s = step(s, PlaceWorker(space="grain_seeds"))    # grain -> 2; watermark -> 2
    assert s.players[0].card_state.get(CARD_ID) == 2

    # A decision-free grant fills the new slot (the documented choke point); it
    # fits (pet + 2 grain slots = 3), so the barrier clears the flag frame-free.
    s = grant_animals(s, 0, Animals(sheep=1))
    s = _advance_until_decision(s)
    assert s.players[0].animals == Animals(sheep=3)
    assert _no_accommodate_frame(s)

    s = with_current_player(s, 0)
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="sow"))
    s = step(s, CommitSow(grain=1, veg=0))       # grain 2 -> 1: 3 sheep, 2 slots

    top = s.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0
    assert (2, 0, 0) in _accommodate_triples(s)
    s = step(s, CommitAccommodate(sheep=2, boar=0, cattle=0))
    assert s.players[0].animals == Animals(sheep=2)


# ---------------------------------------------------------------------------
# Quiet boundaries do not churn state; non-owners pay nothing
# ---------------------------------------------------------------------------

def test_quiet_owner_boundary_is_object_identical():
    s = setup(0)
    s = _own_occ(s, 0)
    s = with_resources(s, 0, grain=2)
    s1, pushed = _reconcile_accommodation(s)
    assert not pushed
    assert s1.players[0].card_state.get(CARD_ID) == 2   # first boundary writes
    s2, pushed = _reconcile_accommodation(s1)
    assert not pushed
    assert s2 is s1                                     # no grain movement: no write


def test_non_owner_pays_nothing():
    """With the card registered but owned by nobody, the barrier walk leaves the
    state object untouched, and a non-owner's grain changes never create a
    CardStore entry."""
    s = setup(0)
    out, pushed = _reconcile_accommodation(s)
    assert not pushed and out is s
    s = with_current_player(s, 0)
    s = step(s, PlaceWorker(space="grain_seeds"))       # a real grain change
    for i in (0, 1):
        assert s.players[i].card_state.get(CARD_ID) is None
    assert _no_accommodate_frame(s)
