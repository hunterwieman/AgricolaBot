import agricola.cards.wildlife_reserve  # noqa: F401  (register the card)

"""Tests for Wildlife Reserve (minor improvement, C11; Consul Dirigens Expansion).

Card text (verbatim): "This card can hold up to 1 sheep, 1 wild boar, and 1
cattle."
Clarification (verbatim): "This card does not count as a pasture."
Cost 2 Wood; prerequisite 2 Occupations; printed 1 VP.

One effect: a per-species typed holder (register_typed_slots, sheep=1/boar=1/
cattle=1), realized by the greedy strip at the ownership-aware accommodation
entry points (`accommodates`, `pareto_frontier`, `breeding_frontier`) — the
multi-species sibling of Dolly's Mother's single sheep slot (user ruling
2026-07-21, the typed-slot fold direction). "Does not count as a pasture" holds
structurally — pasture count/scoring reads `farmyard.pastures`, never the
typed-slot registry — and is verified here, not coded.
"""
import dataclasses

from agricola.actions import CommitBreed
from agricola.constants import CellType, Phase
from agricola.cards.wildlife_reserve import CARD_ID
from agricola.engine import _advance_until_decision, step
from agricola.helpers import (
    accommodates,
    breeding_frontier,
    extract_slots,
    pareto_frontier,
)
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingHarvestBreed
from agricola.resources import Animals
from agricola.scoring import score
from agricola.setup import setup
from agricola.state import Cell, Farmyard

from tests.factories import with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_H = tuple(tuple([False] * 5) for _ in range(4))
_V = tuple(tuple([False] * 6) for _ in range(3))


def _edit_player(state, idx, **kw):
    import agricola.replace as rep
    p = rep.fast_replace(state.players[idx], **kw)
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


def _farm(pastures=()):
    """A bare 3x5 farmyard carrying the given pastures directly (the pig_breeder
    test idiom): extract_slots reads farmyard.pastures, so this is enough to give
    the player a pasture of a chosen capacity without laying real fences."""
    grid = [[Cell(cell_type=CellType.EMPTY) for _ in range(5)] for _ in range(3)]
    return Farmyard(grid=tuple(tuple(row) for row in grid),
                    horizontal_fences=_H, vertical_fences=_V, pastures=pastures)


def _with_pasture(state, idx, capacity):
    return _edit_player(state, idx, farmyard=_farm(
        (Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=capacity),)))


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
    assert spec.vps == 1                                   # printed 1 VP
    assert spec.cost.resources.wood == 2                   # cost 2 Wood
    # no other resource is part of the cost
    assert spec.cost.resources.clay == 0 and spec.cost.resources.stone == 0
    assert spec.cost.resources.reed == 0
    # "2 Occupations" is a min-occupations bound, not a custom prereq predicate
    assert spec.min_occupations == 2
    assert spec.prereq is None

    # one typed-slot row: 1 of each species, tableau-independent of the player.
    slot_fns = [fn for cid, fn in TYPED_SLOT_CARDS if cid == CARD_ID]
    assert len(slot_fns) == 1
    assert slot_fns[0](setup(seed=0).players[0]) == Animals(sheep=1, boar=1, cattle=1)

    rows = json.load(open("agricola/cards/data/revised_minor_improvements.json"))
    row = next(r for r in rows if r["name"] == "Wildlife Reserve")
    assert row["deck"] == "C" and row["number"] == 11
    assert row["vps"] == 1 and row["cost"] == "2 Wood"
    assert row["prerequisites"] == "2 Occupations"


# ---------------------------------------------------------------------------
# Tableau-only: a held card contributes nothing
# ---------------------------------------------------------------------------

def test_typed_slots_tableau_only():
    from agricola.cards.capacity_mods import typed_slot_counts

    base = setup(seed=0)

    # Not owned: no typed slots -> bare farm holds only the 1 house pet.
    plain = base.players[0]
    assert typed_slot_counts(plain) == Animals()
    assert extract_slots(plain) == ([], 1)
    assert not accommodates(plain, 1, 1, 1)      # 3 animals, 1 pet -> overflow
    assert accommodates(plain, 1, 0, 0)          # 1 animal on the pet

    # Held in hand only: still not in the tableau -> still no slots.
    hand = _in_hand(base, 0).players[0]
    assert typed_slot_counts(hand) == Animals()
    assert not accommodates(hand, 1, 1, 1)

    # In the tableau: exactly 1 slot per species (extract_slots is unaffected —
    # typed slots ride the strip, not the pasture/flexible-slot list).
    owner = _own(base, 0).players[0]
    assert typed_slot_counts(owner) == Animals(sheep=1, boar=1, cattle=1)
    assert extract_slots(owner) == ([], 1)


# ---------------------------------------------------------------------------
# accommodates — one slot per species + the single house pet
# ---------------------------------------------------------------------------

def test_accommodates_per_species_slots():
    """Otherwise-empty farm with the card (slots sheep1/boar1/cattle1 + 1 pet):

    - 1 sheep + 1 boar + 1 cattle FITS (each on its own species slot);
    - 2 sheep + 1 boar + 1 cattle FITS (4 animals, three species: the 3 slots
      hold one of each, the extra sheep rides the house pet);
    - the card caps EACH species at 1, so a second animal of a SECOND species
      has nowhere but the single pet — genuinely infeasible:
        * 2 sheep + 2 cattle (4 animals) does NOT fit: 1 sheep + 1 cattle
          overflow, only 1 pet;
        * 2 sheep + 2 boar + 1 cattle (5 animals) does NOT fit either."""
    p = _own(setup(seed=0), 0).players[0]

    assert accommodates(p, 1, 1, 1)          # one of each on its species slot
    assert accommodates(p, 2, 1, 1)          # extra sheep on the house pet
    assert accommodates(p, 1, 2, 1)          # symmetric: extra boar on the pet

    assert not accommodates(p, 2, 2, 0)      # two species overflow, one pet
    assert not accommodates(p, 2, 2, 1)      # ditto, with the cattle slot filled

    # Non-owner control: the bare farm holds only the 1 house pet.
    q = setup(seed=0).players[0]
    assert not accommodates(q, 1, 1, 1)
    assert not accommodates(q, 2, 1, 1)
    assert accommodates(q, 1, 0, 0)


# ---------------------------------------------------------------------------
# pareto_frontier — acquisition uses the per-species card capacity
# ---------------------------------------------------------------------------

def test_pareto_frontier_uses_card_capacity():
    """An animal-market gain of 1 sheep + 1 boar + 1 cattle onto an empty farm:
    with the card the owner keeps all three (one on each species slot); the
    non-owner keeps only one (the house pet), cooking the other two."""
    base = setup(seed=0)
    owner = _own(base, 0).players[0]
    plain = base.players[0]

    gain = Animals(sheep=1, boar=1, cattle=1)
    carded = pareto_frontier(owner, gain, rates=(2, 3, 4))
    bare = pareto_frontier(plain, gain, rates=(2, 3, 4))

    # Owner can keep the full one-of-each haul; the non-owner cannot.
    assert (Animals(sheep=1, boar=1, cattle=1), 0) in carded
    assert not any(a == Animals(sheep=1, boar=1, cattle=1) for a, _ in bare)
    assert max(a.sheep + a.boar + a.cattle for a, _ in carded) == 3
    assert max(a.sheep + a.boar + a.cattle for a, _ in bare) == 1


# ---------------------------------------------------------------------------
# breeding_frontier — a card slot houses a bred newborn (cook-proof)
# ---------------------------------------------------------------------------

def test_breeding_frontier_houses_newborn():
    """Owner with a capacity-2 pasture holding 2 sheep plus 1 boar: sheep breed
    (2 -> 3) and the boar is kept, because the card's boar slot houses the boar
    so the pasture + the sheep slot house all three sheep. The only frontier
    outcome is (sheep=3, boar=1).

    Non-owner control (same farm, no card): breeding the sheep to 3 forces the
    single boar to be cooked (the pasture holds 2 sheep and the sole pet must
    take the third), so (sheep=3, boar=1) is unreachable — the frontier offers
    either keep-the-boar (2, 1) or breed-and-cook-the-boar (3, 0)."""
    base = setup(seed=0)

    owner = _animals(_with_pasture(_own(base, 0), 0, capacity=2), 0,
                     sheep=2, boar=1).players[0]
    of = breeding_frontier(owner)
    assert any(a == Animals(sheep=3, boar=1, cattle=0) for a, _ in of)

    plain = _animals(_with_pasture(base, 0, capacity=2), 0,
                     sheep=2, boar=1).players[0]
    pf = breeding_frontier(plain)
    assert not any(a == Animals(sheep=3, boar=1, cattle=0) for a, _ in pf)
    assert all(a.boar == 0 for a, _ in pf if a.sheep == 3)   # breeding cooks the boar


def test_breed_flow_offers_third_sheep_keeping_boar():
    """Drive a real harvest: owner with a capacity-2 pasture, 2 sheep + 1 boar,
    is offered CommitBreed(sheep=3, boar=1) and it resolves with the boar kept."""
    state = _with_pasture(_own(_harvest_state(), 0), 0, capacity=2)
    state = _animals(state, 0, sheep=2, boar=1)
    state = _to_p0_breed_frame(state)
    breed = [a for a in legal_actions(state)
             if isinstance(a, CommitBreed) and a.sheep == 3 and a.boar == 1]
    assert breed, f"no breed-to-3-keeping-boar offered: {legal_actions(state)}"
    state = step(state, breed[0])
    assert state.players[0].animals.sheep == 3
    assert state.players[0].animals.boar == 1


# ---------------------------------------------------------------------------
# Scoring — not a pasture; printed VP counts
# ---------------------------------------------------------------------------

def test_pasture_scoring_unaffected():
    """A player with no pastures scores the no-pasture value (-1) whether or not
    the card is in play: the holder is not a pasture (scoring reads farmyard
    geometry, never the typed-slot registry)."""
    base = setup(seed=0)
    _, bd_plain = score(base, 0)
    _, bd_owner = score(_own(base, 0), 0)
    assert bd_plain.pastures == -1          # 0 pastures -> -1
    assert bd_owner.pastures == -1          # card in play does not add a pasture


def test_printed_vp_scored():
    """The 1 printed VP lands in card_points (the only card the owner holds)."""
    base = setup(seed=0)
    _, bd_plain = score(base, 0)
    _, bd_owner = score(_own(base, 0), 0)
    assert bd_owner.card_points - bd_plain.card_points == 1
