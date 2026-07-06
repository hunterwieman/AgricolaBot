"""Tests for Stone Importer (occupation, C124; Corbarius Expansion).

Card text (verbatim, from agricola/cards/data/revised_occupations.json):
"In the breeding phase of the 1st/2nd/3rd/4th/5th/6th harvest, you can use this
card to buy exactly 2 stone for 2/2/3/3/4/1 food."
No cost / prerequisite / VPs printed. No on-play effect.

Implemented as an OPTIONAL TRIGGER on the breed frame's PRE-COMMIT stretch
(event ``"breeding"`` on ``PendingHarvestBreed``) per **user ruling 20
(2026-07-05): in-breeding-phase card effects fire BEFORE the CommitBreed
decision, not after** — once CommitBreed resolves, that event is closed (only
outcome-reactive triggers + Stop remain). Firing pays the current harvest's
printed food price (2/2/3/3/4/1 by harvest ordinal) and grants exactly 2 stone,
once per breeding phase (the frame's ``triggers_resolved``); declining is
committing the breed without firing.

These tests drive REAL harvests through the walk (mirroring
tests/test_harvest_seam_hosts.py's ``_breed_state`` / ``_to_p0_breed_frame``
drivers — the walk must ENTER breeding from Phase.HARVEST_FIELD; a bare
empty-stack BREED state reads as breeding-already-done).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.stone_importer  # noqa: F401  (import triggers registration)

import agricola.cards as _cards_pkg
from agricola.actions import CommitBreed, FireTrigger, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.stone_importer import _eligible, _price, _PRICES
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestBreed
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_phase, with_resources, with_round

CARD_ID = "stone_importer"

# The printed schedule: harvest rounds in play order -> the food price.
_ROUND_PRICES = {4: 2, 7: 2, 9: 3, 11: 3, 13: 4, 14: 1}


# --- Helpers (the seam tests' breed-walk drivers) ----------------------------

def _edit_player(state, idx, **kw):
    p = dataclasses.replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _breed_state(*, round_number=4, owner_food=20, give_occ=True):
    """A HARVEST_FIELD-phase state on the given harvest round (the walk must
    ENTER breeding itself — a bare empty-stack BREED state reads as
    breeding-already-done). Both players food-rich (feeding needs 4), P0 owning
    Stone Importer unless give_occ is False."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = with_round(state, round_number)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=owner_food)
    state = with_resources(state, 1, food=20)
    if give_occ:
        state = _own_occ(state, 0)
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


def _scan_offers(state):
    """Drive the WHOLE harvest, recording where FireTrigger(stone_importer) is
    offered as (phase, frame player_idx, breed_chosen) tuples. Steps the first
    non-stone-importer action at each decision, so nothing ever fires."""
    offers = set()
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        acts = legal_actions(state)
        if FireTrigger(card_id=CARD_ID) in acts:
            top = state.pending_stack[-1] if state.pending_stack else None
            offers.add((
                state.phase,
                getattr(top, "player_idx", None),
                getattr(top, "breed_chosen", None),
                type(top).__name__,
            ))
        nxt = next(a for a in acts
                   if a != FireTrigger(card_id=CARD_ID))
        state = step(state, nxt)
    return offers


# --- Registration (spec vs the JSON row) -------------------------------------

def _json_row():
    path = Path(_cards_pkg.__file__).parent / "data" / "revised_occupations.json"
    rows = json.loads(path.read_text())
    (row,) = [r for r in rows if r.get("name") == "Stone Importer"]
    return row


def test_registration_spec_matches_json():
    row = _json_row()
    assert row["type"] == "Occupation"
    assert row["deck"] == "C"
    assert row["number"] == 124
    assert row["expansion"] == "Corbarius Expansion"
    # No cost / prereq / VP fields printed on the row.
    assert "cost" not in row and "prereq" not in row and "vps" not in row
    # The verbatim text this module implements — the price ladder's source.
    assert row["text"] == (
        "In the breeding phase of the 1st/2nd/3rd/4th/5th/6th harvest, you can "
        "use this card to buy exactly 2 stone for 2/2/3/3/4/1 food."
    )
    assert _PRICES == (2, 2, 3, 3, 4, 1)
    assert CARD_ID in OCCUPATIONS


def test_registered_as_pre_breed_trigger():
    """Optional trigger (declinable) on the breed frame's pre-commit event
    "breeding" (user ruling 20, 2026-07-05) — NOT mandatory (the text is "you
    can"), NOT a play-variant (no choice beyond fire/decline), NOT an
    outcome-reactive trigger."""
    entry = CARDS[CARD_ID]
    assert entry.event == "breeding"
    assert entry.mandatory is False
    assert CARD_ID not in PLAY_VARIANT_TRIGGERS


def test_on_play_is_noop_and_no_scoring_term():
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state
    assert not any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- The price ladder ---------------------------------------------------------

def test_price_ladder_by_harvest_round():
    """1st..6th harvest = rounds 4/7/9/11/13/14 -> 2/2/3/3/4/1 food (during a
    harvest, round_number still equals the harvest's round)."""
    state = setup(seed=0)
    for rnd, price in _ROUND_PRICES.items():
        assert _price(with_round(state, rnd)) == price
    # Defensive: a non-harvest round has no price and no eligibility.
    state5 = with_round(_own_occ(with_resources(state, 0, food=20), 0), 5)
    assert _price(state5) is None
    assert _eligible(state5, 0, frozenset()) is False


# --- Ruling 20: offered before CommitBreed, gone after ------------------------

def test_offered_before_commit_gone_after():
    state = _to_p0_breed_frame(_breed_state(round_number=4))
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert any(isinstance(a, CommitBreed) for a in acts)
    assert Stop() not in acts
    # Decline by committing the breed without firing: the event is closed.
    food0 = state.players[0].resources.food
    state = step(state, next(a for a in acts if isinstance(a, CommitBreed)))
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in acts
    assert all(not isinstance(a, CommitBreed) for a in acts)
    assert Stop() in acts
    # Unfired for the rest of the phase: through Stop, nothing was bought.
    state = step(state, Stop())
    assert state.players[0].resources.stone == 0
    assert state.players[0].resources.food == food0


def test_never_offered_outside_p0_pre_breed_stretch():
    """Across the whole harvest walk the buy surfaces ONLY at P0's own breed
    frame before its commit — never in the field/feed phases, never post-commit,
    never on the opponent's frame."""
    offers = _scan_offers(_breed_state(round_number=4))
    assert offers == {(Phase.HARVEST_BREED, 0, False, "PendingHarvestBreed")}


# --- Firing: pay the price, take exactly 2 stone ------------------------------

def test_fire_debits_food_and_grants_two_stone_first_harvest():
    state = _to_p0_breed_frame(_breed_state(round_number=4))
    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == food0 - 2
    assert state.players[0].resources.stone == 2
    # Once per breeding phase: no re-offer; CommitBreed still to come.
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in acts
    assert any(isinstance(a, CommitBreed) for a in acts)
    # The opponent is untouched.
    assert state.players[1].resources.stone == 0


def test_price_at_fifth_harvest_is_four_food():
    state = _to_p0_breed_frame(_breed_state(round_number=13))
    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == food0 - 4
    assert state.players[0].resources.stone == 2


def test_price_at_final_harvest_is_one_food():
    state = _to_p0_breed_frame(_breed_state(round_number=14))
    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == food0 - 1
    assert state.players[0].resources.stone == 2


# --- Eligibility boundaries ---------------------------------------------------

def test_unaffordable_not_offered():
    """At the 5th harvest (price 4), 3 food is short and the buy is withheld;
    exactly 4 food is enough (the boundary)."""
    state = _to_p0_breed_frame(_breed_state(round_number=13))
    short = with_resources(state, 0, food=3)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(short)
    exact = with_resources(state, 0, food=4)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(exact)
    # Firing at the boundary spends it all.
    exact = step(exact, FireTrigger(card_id=CARD_ID))
    assert exact.players[0].resources.food == 0
    assert exact.players[0].resources.stone == 2


def test_unowned_never_offered():
    """No seat owns Stone Importer -> the buy never surfaces anywhere in the
    harvest."""
    assert _scan_offers(_breed_state(round_number=4, give_occ=False)) == set()


def test_opponents_frame_does_not_offer_p0s_card():
    """When P1's pre-commit breed frame is up, P0's card is not offered there
    (covered structurally by the scan test; pinned directly here)."""
    state = _advance_until_decision(_breed_state(round_number=4))
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestBreed) and top.player_idx == 1
                and not top.breed_chosen):
            assert FireTrigger(card_id=CARD_ID) not in legal_actions(state)
            return
        acts = legal_actions(state)
        state = step(state, next(a for a in acts
                                 if a != FireTrigger(card_id=CARD_ID)))
    raise AssertionError("no P1 breed frame surfaced")


def test_eligibility_gates_on_ownership_and_food():
    state = _breed_state(round_number=4)
    assert _eligible(state, 0, frozenset()) is True
    assert _eligible(state, 1, frozenset()) is False        # non-owner seat
    assert _eligible(with_resources(state, 0, food=1), 0, frozenset()) is False
