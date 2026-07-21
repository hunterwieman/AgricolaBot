import agricola.cards.woolgrower  # noqa: F401

"""Tests for Woolgrower (occupation, A148; Artifex Expansion; Farm Planner; 4+).

Card text (verbatim): "This card can hold a number of sheep equal to the number
of completed feeding phases."

A pure standing capacity card (no on-play effect): sheep-only slots equal to the
GLOBAL, game-time count of completed feeding phases
(`helpers.completed_feeding_phases`), realized via the per-species typed-slot
registry (`register_typed_slots`) + the greedy strip at the accommodation entry
points — the same machinery Cattle Farm / Sheep Agent use (user rulings
2026-07-21: one shared game-time count, ticking when a harvest's feeding resolves
regardless of any player's participation).

Four-player only ([4]) — implemented for forward-compat, unit-tested only.

Coverage: registration (incl. presence in `animal_holder_card_ids()`); zero
capacity before any completed feeding phase; 1 slot at round-4 breeding; growth
across rounds; SHEEP-only; tableau-only (owned vs in-hand vs minor); and the Sheep
Agent interaction (both stack, Woolgrower excluded from Sheep Agent's tally).
"""
import dataclasses

from agricola.cards.woolgrower import CARD_ID, _slots
from agricola.constants import Phase
from agricola.helpers import accommodates, completed_feeding_phases
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup


# ---------------------------------------------------------------------------
# Helpers — the count is a pure function of (round_number, phase, harvest_cursor),
# so we stamp those fields directly (mirroring
# tests/test_completed_feeding_phases.py).
# ---------------------------------------------------------------------------

def _at(round_number, phase, cursor=None):
    s = setup(0)
    return fast_replace(s, round_number=round_number, phase=phase,
                        harvest_cursor=cursor)


def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx, occ_ids=(CARD_ID,)):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | set(occ_ids))


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
    # Woolgrower holds sheep via its typed slot, so it IS a registered animal
    # holder — the exact fact that excludes it from Sheep Agent's tally.
    assert CARD_ID in animal_holder_card_ids()

    rows = json.load(open("agricola/cards/data/revised_occupations.json"))
    row = next(r for r in rows if r["name"] == "Woolgrower")
    assert row["deck"] == "A" and row["number"] == 148
    assert row["card_category"] == "Farm Planner" and row["players"] == "4+"


# ---------------------------------------------------------------------------
# The slot count (`_slots`) tracks completed feeding phases
# ---------------------------------------------------------------------------

def test_zero_before_any_completed_feeding_phase():
    """Before any harvest's feeding has resolved, the card holds zero sheep."""
    p = lambda st: _own(st, 0).players[0]
    for st in (_at(1, Phase.WORK), _at(4, Phase.WORK),
               _at(4, Phase.HARVEST_FIELD), _at(4, Phase.RETURN_HOME)):
        assert completed_feeding_phases(st) == 0
        assert _slots(st, p(st)) == Animals(sheep=0)


def test_one_slot_at_round_four_breeding():
    """The first feeding phase completes as the round-4 harvest reaches breeding →
    exactly 1 sheep slot."""
    st = _at(4, Phase.HARVEST_BREED)
    assert completed_feeding_phases(st) == 1
    assert _slots(st, _own(st, 0).players[0]) == Animals(sheep=1)


def test_growth_across_rounds():
    """The slot count grows as feeding phases accumulate over the game."""
    cases = {
        (5, Phase.WORK, None): 1,     # harvest 4 done
        (8, Phase.WORK, None): 2,     # harvests 4, 7
        (12, Phase.WORK, None): 4,    # harvests 4, 7, 9, 11
        (14, Phase.HARVEST_BREED, None): 6,   # 4,7,9,11,13,14
        (14, Phase.BEFORE_SCORING, None): 6,
    }
    for (rnd, phase, cur), expected in cases.items():
        st = _at(rnd, phase, cur)
        assert completed_feeding_phases(st) == expected
        assert _slots(st, _own(st, 0).players[0]) == Animals(sheep=expected)


# ---------------------------------------------------------------------------
# SHEEP-only, and the slots actually house animals
# ---------------------------------------------------------------------------

def test_slots_are_sheep_only():
    """At 2 completed feeding phases the owner holds 2 card sheep + the 1 house
    pet = 3 sheep, but the slots never take boar/cattle (only the pet does)."""
    st = _at(8, Phase.WORK)          # 2 completed feeding phases
    owner = _own(st, 0).players[0]
    assert _slots(st, owner) == Animals(sheep=2)

    assert accommodates(st, owner, 3, 0, 0)       # 2 card slots + 1 house pet
    assert not accommodates(st, owner, 4, 0, 0)   # one sheep too many
    # The card slots are sheep-only: 2 boar / 2 cattle do NOT fit (only the pet).
    assert accommodates(st, owner, 0, 1, 0)
    assert not accommodates(st, owner, 0, 2, 0)
    assert not accommodates(st, owner, 0, 0, 2)

    # Non-owner control: the bare farm holds only the 1 house pet.
    plain = st.players[0]
    assert not accommodates(st, plain, 2, 0, 0)


def test_capacity_tracks_the_count_not_a_fixed_number():
    """A control that pins the state→count dependency: the SAME owner fits more
    sheep at a later phase purely because the count rose."""
    early = _at(4, Phase.HARVEST_BREED)             # count 1
    late = _at(12, Phase.WORK)                       # count 4
    owner_e = _own(early, 0).players[0]
    owner_l = _own(late, 0).players[0]
    assert accommodates(early, owner_e, 2, 0, 0) and not accommodates(early, owner_e, 3, 0, 0)
    assert accommodates(late, owner_l, 5, 0, 0) and not accommodates(late, owner_l, 6, 0, 0)


# ---------------------------------------------------------------------------
# Tableau-only — only a PLAYED (owned) occupation grants slots
# ---------------------------------------------------------------------------

def test_tableau_only():
    from agricola.cards.capacity_mods import typed_slot_counts

    st = _at(8, Phase.WORK)          # 2 completed feeding phases if owned

    # Not owned: no card slot even though feeding phases have completed.
    assert typed_slot_counts(st, st.players[0]) == Animals()

    # Merely held in hand: still not owned → no slot.
    in_hand = _edit_player(st, 0,
                           hand_occupations=st.players[0].hand_occupations | {CARD_ID})
    assert typed_slot_counts(in_hand, in_hand.players[0]) == Animals()

    # Owned: the slots exist.
    owner = _own(st, 0)
    assert typed_slot_counts(owner, owner.players[0]) == Animals(sheep=2)


# ---------------------------------------------------------------------------
# Interaction with Sheep Agent — both stack; Woolgrower excluded from the tally
# ---------------------------------------------------------------------------

def test_sheep_agent_interaction():
    """A player owning both Woolgrower and Sheep Agent gets Woolgrower's sheep
    slots (the feeding-phase count) PLUS Sheep Agent's slots, but Woolgrower does
    NOT count toward Sheep Agent's occupation tally (it "is already able to hold
    animals")."""
    import agricola.cards.sheep_agent  # noqa: F401
    from agricola.cards.capacity_mods import typed_slot_counts
    from agricola.cards.sheep_agent import CARD_ID as SHEEP_AGENT, _slots as sa_slots

    st = _at(8, Phase.WORK)          # 2 completed feeding phases
    owner = _own(st, 0, (CARD_ID, SHEEP_AGENT)).players[0]

    # Sheep Agent's tally counts only itself: Woolgrower is a holder → excluded.
    assert sa_slots(st, owner) == Animals(sheep=1)
    # Woolgrower's own count = the feeding-phase count.
    assert _slots(st, owner) == Animals(sheep=2)
    # Both stack by plain summation: 2 (Woolgrower) + 1 (Sheep Agent) = 3.
    assert typed_slot_counts(st, owner) == Animals(sheep=3)
