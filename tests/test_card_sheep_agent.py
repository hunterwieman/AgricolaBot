"""Tests for Sheep Agent (occupation, D86; Dulcinaria Expansion; Farm Planner).

Card text (verbatim): "You can keep 1 sheep on each occupation card in front of
you (including this one), unless it is already able to hold animals."

A pure standing capacity card (no on-play effect): one sheep-only slot per PLAYED
occupation not already able to hold animals, PLUS one for Sheep Agent itself
("(including this one)"). Realized via the per-species typed-slot registry
(`register_typed_slots`) + the greedy strip at the accommodation entry points, the
same machinery as Dolly's Mother (user ruling 2026-07-21 — the typed-slot fold +
holder-predicate direction).

Coverage: registration; self-only → 1 slot; each non-holder occupation adds 1; a
holder occupation is excluded (self still counts); minors add nothing; hand
occupations add nothing; the slots actually house extra sheep via
`accommodates` / `pareto_frontier`; breeding houses a newborn via the slots; and
the stack with Dolly's Mother (a MINOR typed-slot card).
"""
import agricola.cards.sheep_agent  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import CommitBreed
from agricola.cards.sheep_agent import CARD_ID, _slots
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import accommodates, grant_animals, pareto_frontier
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingHarvestBreed
from agricola.resources import Animals
from agricola.setup import setup

from tests.factories import with_phase, with_resources

# Throwaway state for the (state, player_state) accommodation-helper signature;
# Sheep Agent's count reads only the player's tableau, so any state is inert here.
_S = setup(0)


# ---------------------------------------------------------------------------
# Helpers (mirroring tests/test_card_dollys_mother.py)
# ---------------------------------------------------------------------------

# Arbitrary NON-holder occupation ids (not registered in any animal-holder
# registry) — Sheep Agent's `_slots` counts occupations purely by holder
# membership, so plain ids exercise the counting logic faithfully.
OCC_A = "test_nonholder_occ_a"
OCC_B = "test_nonholder_occ_b"


def _edit_player(state, idx, **kw):
    import agricola.replace as rep
    p = rep.fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, occ_ids):
    return _edit_player(state, idx, occupations=frozenset(occ_ids))


def _animals(state, idx, **kw):
    return _edit_player(state, idx, animals=Animals(**kw))


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


def _harvest_state():
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    import json
    from agricola.cards.capacity_mods import (
        TYPED_SLOT_CARDS, animal_holder_card_ids)
    from agricola.cards.specs import OCCUPATIONS

    assert CARD_ID in OCCUPATIONS                      # registered as an occupation
    assert any(cid == CARD_ID for cid, _ in TYPED_SLOT_CARDS)
    # Sheep Agent itself IS a registered animal holder (via its typed slot) — the
    # exact fact the "(including this one)" clause has to override.
    assert CARD_ID in animal_holder_card_ids()

    rows = json.load(open("agricola/cards/data/revised_occupations.json"))
    row = next(r for r in rows if r["name"] == "Sheep Agent")
    assert row["deck"] == "D" and row["number"] == 86
    assert row["card_category"] == "Farm Planner" and row["players"] == "1+"


# ---------------------------------------------------------------------------
# The slot count (`_slots`)
# ---------------------------------------------------------------------------

def test_self_only_one_slot():
    """Only Sheep Agent played → 1 sheep slot (itself, via "(including this one)")."""
    p = _own_occ(setup(seed=0), 0, {CARD_ID}).players[0]
    assert _slots(_S, p) == Animals(sheep=1)


def test_each_nonholder_occupation_adds_one():
    """Each additional non-holder occupation adds one sheep slot."""
    base = setup(seed=0)
    assert _slots(base, _own_occ(base, 0, {CARD_ID, OCC_A}).players[0]) == Animals(sheep=2)
    assert _slots(base, _own_occ(base, 0, {CARD_ID, OCC_A, OCC_B}).players[0]) \
        == Animals(sheep=3)


def test_holder_occupation_excluded_self_still_counts():
    """A holder occupation (a throwaway typed-slot registrant) does NOT earn a
    slot — "unless it is already able to hold animals" — while Sheep Agent itself
    still counts."""
    from agricola.cards.capacity_mods import (
        TYPED_SLOT_CARDS, animal_holder_card_ids)

    THROWAWAY = "test_throwaway_holder_occ"
    TYPED_SLOT_CARDS.append((THROWAWAY, lambda state, p: Animals(boar=1)))
    try:
        assert THROWAWAY in animal_holder_card_ids()
        p = _own_occ(setup(seed=0), 0, {CARD_ID, THROWAWAY, OCC_A}).players[0]
        # sheep_agent (itself) + OCC_A (non-holder) count; THROWAWAY excluded.
        assert _slots(_S, p) == Animals(sheep=2)
    finally:
        TYPED_SLOT_CARDS[:] = [e for e in TYPED_SLOT_CARDS if e[0] != THROWAWAY]


def test_minors_add_nothing():
    """The text says occupation cards — minor improvements never earn a slot."""
    p = _edit_player(setup(seed=0), 0,
                     occupations=frozenset({CARD_ID}),
                     minor_improvements=frozenset({OCC_A, OCC_B, "some_minor"}))
    assert _slots(p, p.players[0]) == Animals(sheep=1)


def test_hand_occupations_add_nothing():
    """"In front of you" = played; occupations still in hand do not count."""
    p = _edit_player(setup(seed=0), 0,
                     occupations=frozenset({CARD_ID}),
                     hand_occupations=frozenset({OCC_A, OCC_B}))
    assert _slots(p, p.players[0]) == Animals(sheep=1)


# ---------------------------------------------------------------------------
# The slots actually house animals
# ---------------------------------------------------------------------------

def test_accommodates_uses_the_slots():
    """On the bare farm (1 house pet), the owner fits (1 pet + N card slots)
    sheep and no more; a non-owner fits only the pet."""
    from agricola.cards.capacity_mods import typed_slot_counts

    owner = _own_occ(setup(seed=0), 0, {CARD_ID, OCC_A, OCC_B}).players[0]
    assert typed_slot_counts(_S, owner) == Animals(sheep=3)   # 3 slots
    assert accommodates(_S, owner, 4, 0, 0)     # 3 card slots + 1 house pet
    assert not accommodates(_S, owner, 5, 0, 0)
    assert accommodates(_S, owner, 0, 1, 0)     # 1 boar still fits the house pet
    # The slots are sheep-only: 2 boar do NOT fit (only the 1 pet).
    assert not accommodates(_S, owner, 0, 2, 0)
    # Non-owner control: 2 sheep do not fit the bare farm.
    q = setup(seed=0).players[0]
    assert not accommodates(_S, q, 2, 0, 0)


def test_pareto_frontier_houses_extra_sheep():
    """The owner's keep-sets are the bare-farm keep-sets plus the N carded sheep,
    food unchanged. (Keeping every sheep Pareto-dominates cooking any while
    capacity allows, so the frontier is a single all-kept point.)"""
    base = setup(seed=0)
    owner = _animals(_own_occ(base, 0, {CARD_ID, OCC_A, OCC_B}), 0, sheep=3)
    carded = pareto_frontier(owner, owner.players[0], Animals(sheep=1), rates=(2, 0, 0))
    plain = pareto_frontier(base, _animals(base, 0, sheep=3).players[0],
                            Animals(sheep=1), rates=(2, 0, 0))
    # Bare farm keeps at most 1 sheep; the owner keeps all 4 (3 slots + pet).
    assert max(a.sheep for a, _ in plain) == 1
    assert max(a.sheep for a, _ in carded) == 4
    assert (Animals(sheep=4, boar=0, cattle=0), 0) in carded


def test_breeding_houses_newborn_via_slots():
    """Owner with 2 sheep breeds to 3 on the bare farm — the newborn takes a card
    slot; a non-owner cannot house the 3rd sheep."""
    state = _own_occ(_harvest_state(), 0, {CARD_ID, OCC_A})   # 2 sheep slots
    state = _animals(state, 0, sheep=2)
    state = _to_p0_breed_frame(state)
    breed3 = [a for a in legal_actions(state)
              if isinstance(a, CommitBreed) and a.sheep == 3]
    assert breed3, f"no breed-to-3 offered for the owner: {legal_actions(state)}"
    state = step(state, breed3[0])
    assert state.players[0].animals.sheep == 3

    # Non-owner control: 2 sheep on the bare farm (house pet only) can't house a
    # 3rd, so breeding-to-3 is never offered.
    q = _animals(_harvest_state(), 0, sheep=2)
    q = _to_p0_breed_frame(q)
    assert all(a.sheep <= 1 for a in legal_actions(q)
               if isinstance(a, CommitBreed))


def test_barrier_uses_the_slots():
    """A decision-free extra sheep FITS an owner's bare farm (no keep-or-cook
    frame); the same grant to a non-owner surfaces the accommodation frame."""
    for owned in (True, False):
        state = setup(seed=0)
        if owned:
            state = _own_occ(state, 0, {CARD_ID})   # 1 card slot
        state = _animals(state, 0, sheep=1)          # house pet holds this one
        state = grant_animals(state, 0, Animals(sheep=1))
        state = _advance_until_decision(state)
        frame = any(isinstance(f, PendingAccommodate) and f.player_idx == 0
                    for f in state.pending_stack)
        assert frame == (not owned)
        if owned:
            assert state.players[0].animals.sheep == 2


# ---------------------------------------------------------------------------
# Interaction with Dolly's Mother (a MINOR typed-slot card)
# ---------------------------------------------------------------------------

def test_stacks_with_dollys_mother_minor():
    """Sheep Agent (occupation) + Dolly's Mother (minor) stack their sheep slots,
    and Dolly's Mother — a minor — does NOT count toward Sheep Agent's occupation
    count."""
    import agricola.cards.dollys_mother  # noqa: F401
    from agricola.cards.capacity_mods import typed_slot_counts
    from agricola.cards.dollys_mother import CARD_ID as DOLLY

    p = _edit_player(setup(seed=0), 0,
                     occupations=frozenset({CARD_ID}),
                     minor_improvements=frozenset({DOLLY})).players[0]
    # Sheep Agent's own count ignores the minor (1 = itself only).
    assert _slots(_S, p) == Animals(sheep=1)
    # Both stack: Sheep Agent's 1 + Dolly's Mother's 1 = 2 sheep slots total.
    assert typed_slot_counts(_S, p) == Animals(sheep=2)
