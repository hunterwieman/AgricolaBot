"""Tests for Stockyard (minor improvement, B12; Bubulcus Expansion).

Card text (verbatim): "This card can hold up to 3 animals of the same type. (It
is not considered a pasture)."
Cost 1 Wood + 1 Stone; no prereq; printed 1 VP.

One effect (user design direction 2026-07-20): an extra ANONYMOUS single-type
capacity bin of 3, folded into `helpers.extract_slots`' capacity list AFTER every
pasture-only fold. "Of the same type" is the solver's one-type-per-bin semantics;
"(It is not considered a pasture)" holds structurally — pasture count/scoring and
pasture-referencing effects read `farmyard.pastures`, never this list.
"""
import dataclasses

import agricola.cards.stockyard  # noqa: F401  (register the card)

from agricola.actions import CommitBreed
from agricola.constants import Phase
from agricola.cards.stockyard import CARD_ID
from agricola.engine import _advance_until_decision, step
from agricola.helpers import (
    accommodates,
    breeding_frontier,
    extract_slots,
    pareto_frontier,
)
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestBreed
from agricola.resources import Animals
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import with_phase, with_resources

# Throwaway state for the (state, player_state) accommodation-helper signature;
# these tests own no game-global-fact cards, so any state is inert there.
_S = setup(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    from agricola.cards.capacity_mods import ANIMAL_CAP_SLOT_CARDS
    from agricola.cards.specs import MINORS

    spec = MINORS[CARD_ID]
    assert spec.vps == 1                                   # printed 1 VP
    assert spec.cost.resources.wood == 1                   # cost 1 wood
    assert spec.cost.resources.stone == 1                  # cost 1 stone
    # no other resource is part of the cost
    assert spec.cost.resources.clay == 0 and spec.cost.resources.reed == 0
    assert spec.prereq is None                             # no prerequisite
    # the capacity bin is registered as a one-type holder of capacity 3
    caps_fns = [fn for cid, fn in ANIMAL_CAP_SLOT_CARDS if cid == CARD_ID]
    assert len(caps_fns) == 1
    assert caps_fns[0](setup(seed=0).players[0]) == (3,)

    rows = json.load(open("agricola/cards/data/revised_minor_improvements.json"))
    row = next(r for r in rows if r["name"] == "Stockyard")
    assert row["deck"] == "B" and row["number"] == 12
    assert row["vps"] == 1 and row["cost"] == "1 Wood,1 Stone"
    assert row["prerequisites"] is None


# ---------------------------------------------------------------------------
# extract_slots — the bin appears only when the card is in the tableau
# ---------------------------------------------------------------------------

def test_extract_slots_adds_bin_only_when_owned():
    base = setup(seed=0)

    # Not owned at all: bare farm has no pastures and 1 flexible slot (house pet).
    caps, flex = extract_slots(base, base.players[0])
    assert caps == [] and flex == 1

    # Card merely HELD in hand: still not owned -> no bin.
    caps, flex = extract_slots(base, _in_hand(base, 0).players[0])
    assert caps == [] and flex == 1

    # Card in the tableau: exactly one extra single-type bin of capacity 3.
    caps, flex = extract_slots(base, _own(base, 0).players[0])
    assert caps == [3] and flex == 1


# ---------------------------------------------------------------------------
# accommodates — single-type bin
# ---------------------------------------------------------------------------

def test_accommodates_single_type_bin():
    """Otherwise-empty farm with the card (bin of 3 + 1 house pet):
    - 3 sheep + 1 boar (4 animals) FITS: 3 sheep on the bin, the boar as pet;
    - 2 sheep + 2 boar (also 4 animals) does NOT: the bin holds one type only,
      so whichever type sits in the bin, 2 of the other type overflow into a
      single house slot."""
    p = _own(setup(seed=0), 0).players[0]
    assert accommodates(_S, p, 3, 1, 0)          # 3 sheep in bin, boar as house pet
    assert not accommodates(_S, p, 2, 2, 0)      # single-type bin -> 2 of a type overflow

    # Non-owner control: the bare farm holds only the 1 house pet.
    q = setup(seed=0).players[0]
    assert not accommodates(_S, q, 3, 1, 0)
    assert not accommodates(_S, q, 2, 0, 0)


# ---------------------------------------------------------------------------
# pareto_frontier — acquisition uses the card capacity
# ---------------------------------------------------------------------------

def test_pareto_frontier_uses_card_capacity():
    """An animal-market gain of 4 sheep onto an empty farm: with the card the
    owner keeps all 4 (3 on the bin + 1 house pet); the non-owner keeps only 1
    (the house pet), cooking the rest."""
    base = setup(seed=0)
    owner = _own(base, 0).players[0]
    plain = base.players[0]

    carded = pareto_frontier(base, owner, Animals(sheep=4), rates=(2, 0, 0))
    bare = pareto_frontier(base, plain, Animals(sheep=4), rates=(2, 0, 0))

    assert max(a.sheep for a, _ in carded) == 4
    assert (Animals(sheep=4, boar=0, cattle=0), 0) in carded
    assert max(a.sheep for a, _ in bare) == 1


# ---------------------------------------------------------------------------
# breeding_frontier + real breed flow — a newborn can be housed on the card
# ---------------------------------------------------------------------------

def test_breeding_frontier_houses_newborn():
    """Owner with 2 sheep and no pastures: the newborn (2 -> 3) fits on the
    bin (capacity 3)."""
    owner = _animals(_own(setup(seed=0), 0), 0, sheep=2).players[0]
    frontier = breeding_frontier(_S, owner)
    assert any(a.sheep == 3 for a, _ in frontier)

    # Non-owner control: 2 sheep don't even fit the bare farm, and there is
    # nowhere to put a 3rd -> no sheep=3 outcome.
    plain = _animals(setup(seed=0), 0, sheep=2).players[0]
    assert all(a.sheep < 3 for a, _ in breeding_frontier(_S, plain))


def test_breed_flow_offers_third_sheep():
    """Drive a real harvest: owner with 2 sheep (housed on the bin) is offered
    CommitBreed(sheep=3), and it resolves with the newborn on the card."""
    state = _own(_harvest_state(), 0)
    state = _animals(state, 0, sheep=2)
    state = _to_p0_breed_frame(state)
    breed3 = [a for a in legal_actions(state)
              if isinstance(a, CommitBreed) and a.sheep == 3]
    assert breed3, f"no breed-to-3 offered: {legal_actions(state)}"
    state = step(state, breed3[0])
    assert state.players[0].animals.sheep == 3


# ---------------------------------------------------------------------------
# Scoring — not a pasture; printed VP counts
# ---------------------------------------------------------------------------

def test_pasture_scoring_unaffected():
    """A player with no pastures scores the no-pasture value (-1) whether or not
    the card is in play: the holder is not a pasture."""
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
