import agricola.cards.cattle_farm  # noqa: F401

"""Tests for Cattle Farm (minor improvement, C12; Corbarius Expansion).

Card text (verbatim): "For each pasture you have, you can keep 1 cattle on this
card."
Cost 1 Wood; no prereq; no printed VP.

One effect: a per-species (cattle-only) card slot count equal to the number of
pastures the player has, registered via `register_typed_slots` and realized by the
greedy strip in helpers.py. The slot count is derived from `farmyard.pastures`
(never `cell_type`), is monotone (pastures are permanent — no eviction path), and
the card is never itself a pasture (pasture count/scoring read farmyard geometry).
"""
import dataclasses

from agricola.actions import CommitBreed
from agricola.cards.cattle_farm import CARD_ID
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import (
    accommodates,
    breeding_frontier,
    extract_slots,
)
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingHarvestBreed
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _in_hand(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, hand_minors=p.hand_minors | {CARD_ID})


def _animals(state, idx, **kw):
    return _edit_player(state, idx, animals=Animals(**kw))


def _set_pastures(state, idx, cells_per_pasture):
    """Install the given pastures (one iterable of cells each) onto the farmyard
    cache — a 1x1 pasture is capacity 2 (2 * cells * 2^stables). Mirrors the
    direct-cache pattern used by tests/test_card_fellow_grazer.py."""
    fy = state.players[idx].farmyard
    pastures = tuple(
        Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
        for cells in cells_per_pasture)
    fy = fast_replace(fy, pastures=pastures)
    return _edit_player(state, idx, farmyard=fy)


def _harvest_state():
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
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
    from agricola.cards.specs import MINORS

    spec = MINORS[CARD_ID]
    assert spec.vps == 0                                   # no printed VP
    assert spec.cost.resources.wood == 1                   # cost 1 wood
    # no other resource is part of the cost
    assert spec.cost.resources.clay == 0
    assert spec.cost.resources.reed == 0
    assert spec.cost.resources.stone == 0
    assert spec.cost.animals == Animals()
    assert spec.prereq is None                             # no prerequisite

    # the typed slot is registered and yields cattle == pasture count.
    slot_fns = [fn for cid, fn in TYPED_SLOT_CARDS if cid == CARD_ID]
    assert len(slot_fns) == 1
    base = setup(seed=0).players[0]
    assert slot_fns[0](base) == Animals(cattle=0)          # 0 pastures -> 0 cattle
    owner_2p = _set_pastures(_own(setup(seed=0), 0), 0,
                             [[(0, 0)], [(0, 1)]]).players[0]
    assert slot_fns[0](owner_2p) == Animals(cattle=2)      # 2 pastures -> 2 cattle

    rows = json.load(open("agricola/cards/data/revised_minor_improvements.json"))
    row = next(r for r in rows if r["name"] == "Cattle Farm")
    assert row["deck"] == "C" and row["number"] == 12
    assert row["cost"] == "1 Wood"
    assert row["vps"] is None and row["prerequisites"] is None


# ---------------------------------------------------------------------------
# typed_slot_counts — cattle per pasture, only when owned
# ---------------------------------------------------------------------------

def test_typed_slot_counts_scale_with_pastures():
    from agricola.cards.capacity_mods import typed_slot_counts

    base = setup(seed=0)

    # Not owned: no card slot even with pastures present.
    with_pastures = _set_pastures(base, 0, [[(0, 0)], [(0, 1)]])
    assert typed_slot_counts(with_pastures.players[0]) == Animals()

    # Card merely HELD in hand: still not owned -> no slot.
    assert typed_slot_counts(_in_hand(with_pastures, 0).players[0]) == Animals()

    # Owned, zero pastures -> zero card cattle capacity.
    owner0 = _own(base, 0)
    assert typed_slot_counts(owner0.players[0]) == Animals(cattle=0)

    # Owned, N pastures -> +N cattle slots.
    owner1 = _set_pastures(_own(base, 0), 0, [[(0, 0)]])
    assert typed_slot_counts(owner1.players[0]) == Animals(cattle=1)
    owner3 = _set_pastures(_own(base, 0), 0, [[(0, 0)], [(0, 1)], [(0, 2)]])
    assert typed_slot_counts(owner3.players[0]) == Animals(cattle=3)


def test_zero_pastures_no_card_capacity():
    """Owned with zero pastures adds no cattle capacity: only the 1 house pet
    holds a cattle, exactly like a bare farm."""
    owner0 = _own(setup(seed=0), 0).players[0]
    plain = setup(seed=0).players[0]
    assert accommodates(owner0, 0, 0, 1)          # the house pet
    assert not accommodates(owner0, 0, 0, 2)      # card gives nothing at 0 pastures
    assert not accommodates(plain, 0, 0, 2)       # same as the non-owner


# ---------------------------------------------------------------------------
# accommodates — the card slot stacks ON TOP of the pasture's own capacity,
# and holds CATTLE only
# ---------------------------------------------------------------------------

def test_card_capacity_on_top_of_pasture():
    """One 1x1 pasture (capacity 2) + the card + the house pet: 4 cattle fit
    (2 in the pasture, 1 on the card, 1 as the pet); 5 do not."""
    owner = _set_pastures(_own(setup(seed=0), 0), 0, [[(0, 0)]]).players[0]

    # extract_slots itself is unchanged by a typed holder — the strip applies at
    # the accommodation entry points, not in extract_slots.
    caps, flex = extract_slots(owner)
    assert caps == [2] and flex == 1              # the real pasture + house pet only

    assert accommodates(owner, 0, 0, 4)           # 2 pasture + 1 card + 1 pet
    assert not accommodates(owner, 0, 0, 5)       # one cattle too many

    # Non-owner control: the same 1x1 pasture holds only 2 + the 1 pet = 3.
    plain = _set_pastures(setup(seed=0), 0, [[(0, 0)]]).players[0]
    assert accommodates(plain, 0, 0, 3)
    assert not accommodates(plain, 0, 0, 4)


def test_card_slot_is_cattle_only():
    """The card slot holds CATTLE only. With one 1x1 pasture (cap 2) + card + pet,
    4 cattle fit but 4 sheep do NOT: sheep can use the pasture (2) and the pet (1)
    but never the cattle-only card slot -> the 4th sheep overflows."""
    owner = _set_pastures(_own(setup(seed=0), 0), 0, [[(0, 0)]]).players[0]

    assert accommodates(owner, 0, 0, 4)           # 4 cattle fit (card slot usable)
    assert not accommodates(owner, 4, 0, 0)       # 4 sheep do NOT (card slot unusable)
    assert accommodates(owner, 3, 0, 0)           # 3 sheep fit (pasture 2 + pet 1)
    # boar is likewise excluded from the cattle slot.
    assert not accommodates(owner, 0, 4, 0)
    assert accommodates(owner, 0, 3, 0)


# ---------------------------------------------------------------------------
# breeding — a newborn cattle can be housed on the card
# ---------------------------------------------------------------------------

def test_breeding_frontier_houses_newborn_cattle():
    """Owner with one 1x1 pasture holding 2 cattle: the newborn (2 -> 3) fits
    (2 in the pasture, the 3rd on the card slot)."""
    owner = _animals(_set_pastures(_own(setup(seed=0), 0), 0, [[(0, 0)]]),
                     0, cattle=2).players[0]
    frontier = breeding_frontier(owner)
    assert any(a.cattle == 3 for a, _ in frontier)

    # Non-owner control: pasture holds only 2 cattle, the pet is the sole extra
    # slot, so 3 cattle DO still fit for the non-owner (pasture 2 + pet 1). Push
    # to a case the card decides: 3 cattle in a full pasture + pet, breeding to 4
    # needs the card slot.
    owner4 = _animals(_set_pastures(_own(setup(seed=0), 0), 0, [[(0, 0)]]),
                      0, cattle=3).players[0]
    assert any(a.cattle == 4 for a, _ in breeding_frontier(owner4))
    plain4 = _animals(_set_pastures(setup(seed=0), 0, [[(0, 0)]]),
                      0, cattle=3).players[0]
    assert all(a.cattle < 4 for a, _ in breeding_frontier(plain4))


def test_breed_flow_offers_fourth_cattle():
    """Drive a real harvest: owner with a full 1x1 pasture (2 cattle) + 1 more as
    the pet (3 cattle total) is offered CommitBreed(cattle=4), housing the newborn
    on the card, whereas the non-owner tops out at 3."""
    state = _own(_harvest_state(), 0)
    state = _set_pastures(state, 0, [[(0, 0)]])
    state = _animals(state, 0, cattle=3)
    state = _to_p0_breed_frame(state)
    breed4 = [a for a in legal_actions(state)
              if isinstance(a, CommitBreed) and a.cattle == 4]
    assert breed4, f"no breed-to-4 offered: {legal_actions(state)}"
    state = step(state, breed4[0])
    assert state.players[0].animals.cattle == 4


# ---------------------------------------------------------------------------
# Scoring — the card is not a pasture; no printed VP
# ---------------------------------------------------------------------------

def test_card_is_not_a_pasture():
    """The pasture score is identical with and without the card in play: the
    holder is never counted as a pasture. Checked at 0 pastures (both -1) and at
    one real pasture (identical nonzero score)."""
    base = setup(seed=0)
    _, bd_plain0 = score(base, 0)
    _, bd_owner0 = score(_own(base, 0), 0)
    assert bd_plain0.pastures == -1               # 0 pastures -> -1
    assert bd_owner0.pastures == -1               # card in play adds no pasture

    with_p = _set_pastures(base, 0, [[(0, 0)]])
    _, bd_plain1 = score(with_p, 0)
    _, bd_owner1 = score(_own(with_p, 0), 0)
    assert bd_owner1.pastures == bd_plain1.pastures   # card does not add a pasture


def test_no_printed_vp():
    """No printed VP: the card contributes nothing to card_points."""
    base = setup(seed=0)
    _, bd_plain = score(base, 0)
    _, bd_owner = score(_own(base, 0), 0)
    assert bd_owner.card_points - bd_plain.card_points == 0
