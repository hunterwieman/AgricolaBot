import agricola.cards.truffle_searcher  # noqa: F401

"""Tests for Truffle Searcher (occupation, B86; Bubulcus Expansion; Farm Planner).

Card text (verbatim): "This card can hold a number of wild boar equal to the
number of completed feeding phases."

A pure standing capacity card (no on-play effect): a boar-only card slot count
equal to the GLOBAL number of completed feeding phases
(`helpers.completed_feeding_phases`, user rulings 2026-07-21 — one shared,
game-time count), registered via `register_typed_slots` and realized by the
greedy strip at the accommodation entry points. The count is monotone
non-decreasing (a completed harvest never un-completes), so the card capacity
never drops — no eviction path.

Coverage: registration; zero capacity through the round-4 WORK/FIELD/FEED
phases; capacity 1 at the round-4 BREEDING phase (synthetic breeding_frontier +
a real driven breed flow housing a newborn boar); capacity growth across
harvests (4 by round 12); boar-only slots; tableau-only (hand contributes
nothing); and non-owner controls.
"""
import dataclasses

from agricola.actions import CommitBreed
from agricola.cards.harvest_windows import sentinel_position
from agricola.cards.truffle_searcher import CARD_ID, _slots
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import (
    accommodates,
    breeding_frontier,
    completed_feeding_phases,
    extract_slots,
)
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingHarvestBreed
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup

from tests.factories import with_phase, with_resources

# Throwaway state for accommodation-helper calls whose count is fixed by an
# explicit stamp on the SAME state passed in (never this one). Used only where
# the completed-feeding count is irrelevant to the assertion.
_S = setup(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _in_hand(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, hand_occupations=p.hand_occupations | {CARD_ID})


def _animals(state, idx, **kw):
    return _edit_player(state, idx, animals=Animals(**kw))


def _set_pastures(state, idx, cells_per_pasture):
    """Install the given pastures (one iterable of cells each) onto the farmyard
    cache — a 1x1 pasture is capacity 2 (2 * cells * 2^stables). Mirrors the
    direct-cache pattern used by tests/test_card_cattle_farm.py."""
    fy = state.players[idx].farmyard
    pastures = tuple(
        Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
        for cells in cells_per_pasture)
    fy = fast_replace(fy, pastures=pastures)
    return _edit_player(state, idx, farmyard=fy)


def _at(state, round_number, phase, cursor=None):
    """Stamp the (round_number, phase, harvest_cursor) that fix
    `completed_feeding_phases` (mirrors tests/test_completed_feeding_phases.py)."""
    return dataclasses.replace(state, round_number=round_number, phase=phase,
                               harvest_cursor=cursor)


def _harvest_state():
    """A round-4 harvest about to run (so its feeding phase is the FIRST to
    complete → completed_feeding_phases becomes 1 at the breeding step)."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0, round_number=4)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    return state


def _to_p0_breed_frame(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestBreed) and top.player_idx == 0
                and not top.breed_chosen):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("no P0 breed frame surfaced")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    import json
    from agricola.cards.capacity_mods import TYPED_SLOT_CARDS
    from agricola.cards.specs import OCCUPATIONS

    assert CARD_ID in OCCUPATIONS                      # registered as an occupation

    slot_fns = [fn for cid, fn in TYPED_SLOT_CARDS if cid == CARD_ID]
    assert len(slot_fns) == 1
    assert slot_fns[0] is _slots

    rows = json.load(open("agricola/cards/data/revised_occupations.json"))
    row = next(r for r in rows if r["name"] == "Truffle Searcher")
    assert row["deck"] == "B" and row["number"] == 86
    assert row["card_category"] == "Farm Planner" and row["players"] == "1+"


def test_slots_track_completed_feeding_phases():
    """`_slots` returns boar == the GLOBAL completed-feeding-phase count, off
    `state` (not `player_state`)."""
    base = setup(seed=0)
    owner = _own(base, 0).players[0]

    s0 = _at(base, 4, Phase.WORK)
    assert completed_feeding_phases(s0) == 0
    assert _slots(s0, owner) == Animals(boar=0)

    s1 = _at(base, 4, Phase.HARVEST_BREED)
    assert completed_feeding_phases(s1) == 1
    assert _slots(s1, owner) == Animals(boar=1)

    s4 = _at(base, 12, Phase.WORK)
    assert completed_feeding_phases(s4) == 4
    assert _slots(s4, owner) == Animals(boar=4)


# ---------------------------------------------------------------------------
# Zero capacity before any feeding phase completes
# ---------------------------------------------------------------------------

def test_zero_capacity_before_first_feeding():
    """Through rounds 1-4 WORK and the round-4 FIELD / FEED phases (before the
    final feed payment resolves) no feeding phase has completed, so the card adds
    NO boar slot: an owner on the bare farm holds only the 1 house pet."""
    from agricola.cards.capacity_mods import typed_slot_counts

    base = setup(seed=0)
    feed_done = sentinel_position("feeding", 1)
    pre_feeding = [
        _at(base, 1, Phase.WORK),
        _at(base, 4, Phase.WORK),
        _at(base, 4, Phase.HARVEST_FIELD),
        # Final player's feed payment still up (cursor AT the sentinel): not complete.
        _at(base, 4, Phase.HARVEST_FEED, feed_done),
    ]
    for s in pre_feeding:
        assert completed_feeding_phases(s) == 0                 # sanity on the stamp
        owner = _own(s, 0).players[0]
        assert typed_slot_counts(s, owner) == Animals()        # no card slot yet
        assert accommodates(s, owner, 0, 1, 0)                 # only the house pet
        assert not accommodates(s, owner, 0, 2, 0)             # card gives nothing


# ---------------------------------------------------------------------------
# Capacity 1 at the round-4 breeding phase — a newborn boar is housable
# ---------------------------------------------------------------------------

def test_capacity_one_at_round4_breeding_frontier():
    """At the round-4 BREEDING phase one feeding phase has completed → 1 card
    boar slot. Owner with a full 1x1 pasture (cap 2) + 1 boar as the pet (3 boar)
    breeds to 4, housing the newborn on the card; the non-owner tops out at 3."""
    breed_state = _at(setup(seed=0), 4, Phase.HARVEST_BREED)
    assert completed_feeding_phases(breed_state) == 1

    owner = _animals(_set_pastures(_own(breed_state, 0), 0, [[(0, 0)]]),
                     0, boar=3).players[0]
    # extract_slots is unchanged by a typed holder (the strip is at the entry points).
    caps, flex = extract_slots(breed_state, owner)
    assert caps == [2] and flex == 1
    assert any(a.boar == 4 for a, _ in breeding_frontier(breed_state, owner))

    plain = _animals(_set_pastures(breed_state, 0, [[(0, 0)]]),
                     0, boar=3).players[0]
    assert all(a.boar < 4 for a, _ in breeding_frontier(breed_state, plain))


def test_breed_flow_offers_fourth_boar():
    """Drive a real round-4 harvest: an owner with a full 1x1 pasture (2 boar) +
    1 more as the pet (3 boar) is offered CommitBreed(boar=4) at the breeding
    step — the newborn housed on the card, since round-4 feeding has completed —
    whereas the non-owner tops out at 3."""
    state = _own(_harvest_state(), 0)
    state = _set_pastures(state, 0, [[(0, 0)]])
    state = _animals(state, 0, boar=3)
    state = _to_p0_breed_frame(state)
    # The driven harvest is AT the round-4 breed frame, so one feeding phase is done.
    assert completed_feeding_phases(state) == 1
    breed4 = [a for a in legal_actions(state)
              if isinstance(a, CommitBreed) and a.boar == 4]
    assert breed4, f"no breed-to-4 offered: {legal_actions(state)}"
    state = step(state, breed4[0])
    assert state.players[0].animals.boar == 4

    # Non-owner control: same farm, no card → 3 boar max (pasture 2 + pet 1).
    q = _set_pastures(_harvest_state(), 0, [[(0, 0)]])
    q = _animals(q, 0, boar=3)
    q = _to_p0_breed_frame(q)
    assert all(a.boar <= 3 for a in legal_actions(q)
               if isinstance(a, CommitBreed))


# ---------------------------------------------------------------------------
# Capacity grows across harvests
# ---------------------------------------------------------------------------

def test_capacity_grows_across_harvests():
    """Owner on the bare farm (1 house pet). The card slot count tracks the
    completed-feeding count: 1 by round 5, 4 by round 12 — so 5 boar fit at
    round 12 (4 card + 1 pet) but not 6."""
    from agricola.cards.capacity_mods import typed_slot_counts

    base = setup(seed=0)
    for rnd, expected in [(5, 1), (8, 2), (12, 4)]:
        s = _at(base, rnd, Phase.WORK)
        assert completed_feeding_phases(s) == expected     # sanity on the stamp
        owner = _own(s, 0).players[0]
        assert typed_slot_counts(s, owner) == Animals(boar=expected)

    s12 = _at(base, 12, Phase.WORK)
    owner12 = _own(s12, 0).players[0]
    assert accommodates(s12, owner12, 0, 5, 0)     # 4 card slots + 1 house pet
    assert not accommodates(s12, owner12, 0, 6, 0)


# ---------------------------------------------------------------------------
# The card slot holds BOAR only
# ---------------------------------------------------------------------------

def test_card_slot_is_boar_only():
    """At round 12 (4 card slots) on the bare farm: 5 boar fit (4 card + 1 pet),
    but 2 sheep do NOT — sheep can use the house pet only, never the boar-only
    card slots — and likewise 2 cattle do not."""
    s = _at(setup(seed=0), 12, Phase.WORK)
    owner = _own(s, 0).players[0]

    assert accommodates(s, owner, 0, 5, 0)         # 5 boar fit (card slots usable)
    assert not accommodates(s, owner, 2, 0, 0)     # 2 sheep do NOT (card unusable)
    assert accommodates(s, owner, 1, 0, 0)         # 1 sheep fits the house pet
    assert not accommodates(s, owner, 0, 0, 2)     # cattle likewise excluded
    assert accommodates(s, owner, 0, 0, 1)


# ---------------------------------------------------------------------------
# Tableau-only — the hand contributes nothing; non-owner control
# ---------------------------------------------------------------------------

def test_hand_and_nonowner_contribute_nothing():
    """The card grants slots only when PLAYED (in `occupations`). Held in hand,
    or not owned at all, it adds nothing — even at round 12 (4 completed feeding
    phases)."""
    from agricola.cards.capacity_mods import typed_slot_counts

    s = _at(setup(seed=0), 12, Phase.WORK)
    assert completed_feeding_phases(s) == 4

    in_hand = _in_hand(s, 0).players[0]
    assert typed_slot_counts(s, in_hand) == Animals()
    assert accommodates(s, in_hand, 0, 1, 0)       # only the house pet
    assert not accommodates(s, in_hand, 0, 2, 0)

    plain = s.players[0]
    assert typed_slot_counts(s, plain) == Animals()
    assert not accommodates(s, plain, 0, 2, 0)
