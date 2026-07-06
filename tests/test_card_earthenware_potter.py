"""Tests for Earthenware Potter (occupation, D99; Dulcinaria Expansion).

Card text (verbatim): "If you play this card in round 4 or before, after the
final harvest, you get 1 bonus point for each person for which you then pay 1
clay."

Mechanism under test (user rulings 2026-07-06):
- "after the final harvest" = the ``after_harvest`` window at round 14 (the
  harvest ladder's last window, resolved immediately before scoring);
- the player freely chooses how many people to pay for: one play-variant per
  k in 1..min(clay, people_total) (newborns are people — included in
  people_total); declining entirely is the window frame's ``Proceed``.

The on-play snapshots the play round into the CardStore under CARD_ID (the
Butler idiom); firing variant k debits k clay and banks k bonus points under a
second CardStore key, read back by the scoring term. Played round 5+ → the
trigger is permanently ineligible (the printed condition). These tests drive
the REAL engine: the play via Lessons in card mode, the round-14 harvest walk
for the window, and the negative walks (early harvest / late play / unowned).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.earthenware_potter  # noqa: F401  (register the card)

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
)
from agricola.cards.earthenware_potter import (
    CARD_ID,
    _VP_KEY,
    _eligible,
    _variants,
)
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState

from tests.factories import with_people, with_phase, with_resources

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _with_occupation_played(state, player_idx, play_round):
    """Give a player the PLAYED card with its play-round snapshot, as _on_play
    would have left it (the end-to-end play flow is tested separately)."""
    p = state.players[player_idx]
    p = dataclasses.replace(
        p,
        occupations=p.occupations | {CARD_ID},
        card_state=p.card_state.set(CARD_ID, play_round),
    )
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, clay=0, food=20, owned=True, play_round=3,
                   round_number=14) -> GameState:
    """A HARVEST_FIELD-phase state in the given round, P0 owning Earthenware
    Potter (played in `play_round`) with the given clay; P1 food-rich so only
    P0's frames are interesting."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(
        state, starting_player=0, round_number=round_number)
    if owned:
        state = _with_occupation_played(state, 0, play_round)
    state = with_resources(state, 0, food=food, clay=clay)
    state = with_resources(state, 1, food=99)
    return state


def _walk_to_after_harvest(state):
    """Drive the harvest walk until P0's after_harvest window frame is on top.
    Returns (state, reached) — reached False if the harvest completed without
    ever pushing that frame."""
    state = _advance_until_decision(state)
    while state.phase in _HARVEST_PHASES:
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"
                and top.player_idx == 0):
            return state, True
        state = step(state, legal_actions(state)[0])
    return state, False


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _play_via_lessons(round_number=None, seed=5):
    """Play Earthenware Potter through the REAL Lessons flow in card mode.
    Returns (state_after_commit, playing_player_idx)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    if round_number is not None:
        cs = dataclasses.replace(cs, round_number=round_number)
    cp = cs.current_player
    p = cs.players[cp]
    p = dataclasses.replace(
        p, hand_occupations=frozenset({CARD_ID}), occupations=frozenset())
    cs = dataclasses.replace(
        cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    assert CommitPlayOccupation(card_id=CARD_ID) in legal_actions(cs)
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))
    return cs, cp


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_harvest", set())
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("after_harvest", ()))
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


def test_json_row_matches_module():
    """The docstring's verbatim quote is the JSON row's text."""
    data_path = (Path(__file__).resolve().parent.parent
                 / "agricola" / "cards" / "data" / "revised_occupations.json")
    rows = json.loads(data_path.read_text())
    row = next(r for r in rows if r["name"] == "Earthenware Potter")
    assert row["type"] == "Occupation"
    assert row["deck"] == "D"
    assert row["number"] == 99
    import agricola.cards.earthenware_potter as mod
    # Whitespace-normalized: the docstring wraps the (verbatim) quote across lines.
    assert " ".join(row["text"].split()) in " ".join(mod.__doc__.split())


# --- On-play: the play-round snapshot, via the real play flow ----------------

def test_play_records_round_1():
    cs, cp = _play_via_lessons()  # round 1
    p = cs.players[cp]
    assert CARD_ID in p.occupations
    assert CARD_ID not in p.hand_occupations
    assert p.card_state.get(CARD_ID) == 1


def test_play_records_round_5():
    """Playing in round 5 records 5 — the snapshot is unconditional; the <= 4
    gate is applied at window eligibility (tested below)."""
    cs, cp = _play_via_lessons(round_number=5)
    assert cs.players[cp].card_state.get(CARD_ID) == 5


# --- The window offer (the round-14 walk) -------------------------------------

def test_offered_at_final_harvest_with_variants():
    """Played round 3, clay 2, 2 people → the after_harvest window frame is
    pushed at round 14 and offers k=1, k=2, and Proceed."""
    state, reached = _walk_to_after_harvest(_harvest_state(clay=2, play_round=3))
    assert reached
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID, variant="1") in acts
    assert FireTrigger(card_id=CARD_ID, variant="2") in acts
    assert Proceed() in acts
    # k is capped by people_total (2): no k=3 even if clay allowed it.
    assert FireTrigger(card_id=CARD_ID, variant="3") not in acts


def test_variants_capped_by_clay():
    state, reached = _walk_to_after_harvest(_harvest_state(clay=1))
    assert reached
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID, variant="1") in acts
    assert FireTrigger(card_id=CARD_ID, variant="2") not in acts


def test_variants_capped_by_people():
    """Clay 5 but only 2 people → k stops at 2."""
    state, reached = _walk_to_after_harvest(_harvest_state(clay=5))
    assert reached
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID, variant="2") in acts
    assert FireTrigger(card_id=CARD_ID, variant="3") not in acts


def test_newborns_count_as_people():
    """people_total includes newborns — 3 people (1 newborn), clay 5 → k up
    to 3."""
    state = _harvest_state(clay=5)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state, reached = _walk_to_after_harvest(state)
    assert reached
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID, variant="3") in acts
    assert FireTrigger(card_id=CARD_ID, variant="4") not in acts


# --- Firing / declining -------------------------------------------------------

def test_fire_k2_debits_clay_and_banks_points():
    state, reached = _walk_to_after_harvest(_harvest_state(clay=3))
    assert reached
    state = step(state, FireTrigger(card_id=CARD_ID, variant="2"))
    p = state.players[0]
    assert p.resources.clay == 1              # 3 - 2 paid
    assert p.card_state.get(_VP_KEY, 0) == 2  # 2 banked points
    assert p.card_state.get(CARD_ID) == 3     # the play-round snapshot is untouched
    # Once per window: only Proceed remains (clay left, but the trigger is resolved).
    assert legal_actions(state) == [Proceed()]


def test_decline_via_proceed_banks_nothing():
    state, reached = _walk_to_after_harvest(_harvest_state(clay=3))
    assert reached
    state = step(state, Proceed())
    p = state.players[0]
    assert p.resources.clay == 3
    assert p.card_state.get(_VP_KEY, 0) == 0


def test_after_final_window_game_reaches_scoring():
    """The window sits immediately before scoring: after it resolves, the
    round-14 walk exits the harvest into the pre-scoring phase."""
    state, reached = _walk_to_after_harvest(_harvest_state(clay=1))
    assert reached
    state = step(state, FireTrigger(card_id=CARD_ID, variant="1"))
    while state.phase in _HARVEST_PHASES:
        state = step(state, legal_actions(state)[0])
    assert state.phase not in _HARVEST_PHASES
    assert state.round_number == 14


# --- Negative cases -----------------------------------------------------------

def test_played_round_5_never_offered():
    """Played in round 5: the round-14 window never pushes a frame — the card
    does nothing (the printed condition, not a defer)."""
    state, reached = _walk_to_after_harvest(
        _harvest_state(clay=5, play_round=5))
    assert not reached


def test_not_offered_at_earlier_harvests():
    """The FINAL harvest only: the round-4 harvest's after_harvest window never
    offers the buy (played round 1, clay in hand)."""
    state, reached = _walk_to_after_harvest(
        _harvest_state(clay=5, play_round=1, round_number=4))
    assert not reached


def test_unowned_never_offered():
    state, reached = _walk_to_after_harvest(_harvest_state(clay=5, owned=False))
    assert not reached


def test_no_clay_never_offered():
    state, reached = _walk_to_after_harvest(_harvest_state(clay=0))
    assert not reached


def test_not_offered_to_non_owner_seat():
    """P1 owning the card must not push a window frame for P0."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0, round_number=14)
    state = _with_occupation_played(state, 1, 2)   # opponent owns it
    state = with_resources(state, 0, food=20, clay=5)
    state = with_resources(state, 1, food=99, clay=5)
    saw_p0_frame = False
    state = _advance_until_decision(state)
    while state.phase in _HARVEST_PHASES:
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"
                and top.player_idx == 0):
            saw_p0_frame = True
        state = step(state, legal_actions(state)[0])
    assert not saw_p0_frame


# --- Eligibility / variants unit checks ----------------------------------------

def test_eligibility_gates():
    # Baseline: owned, played round 3, round 14, clay 1 → eligible.
    state = _harvest_state(clay=1, play_round=3)
    assert _eligible(state, 0, frozenset()) is True
    # Non-owner seat.
    assert _eligible(state, 1, frozenset()) is False
    # Played round 5 → the printed condition fails.
    assert _eligible(_harvest_state(clay=1, play_round=5), 0, frozenset()) is False
    # Play round exactly 4 is still in ("round 4 or before").
    assert _eligible(_harvest_state(clay=1, play_round=4), 0, frozenset()) is True
    # Not the final harvest.
    assert _eligible(
        _harvest_state(clay=1, round_number=7), 0, frozenset()) is False
    # No clay.
    assert _eligible(_harvest_state(clay=0), 0, frozenset()) is False


def test_variants_unit():
    assert _variants(_harvest_state(clay=1), 0) == ["1"]
    assert _variants(_harvest_state(clay=5), 0) == ["1", "2"]  # 2 people cap
    assert _variants(_harvest_state(clay=2), 0) == ["1", "2"]  # clay cap == people
    assert _variants(_harvest_state(clay=5, play_round=5), 0) == []
    assert _variants(_harvest_state(clay=5, round_number=7), 0) == []
    assert _variants(_harvest_state(clay=0), 0) == []
    st = with_people(_harvest_state(clay=9), 0, total=4, home=4)
    assert _variants(st, 0) == ["1", "2", "3", "4"]


# --- Scoring --------------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    assert score_fn(state, 0) == 0
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(_VP_KEY, 3))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    assert score_fn(state, 0) == 3
    assert score_fn(state, 1) == 0


def test_end_to_end_fire_then_score():
    """Fire k=2 at the final window, then the scoring term reports 2."""
    state, reached = _walk_to_after_harvest(_harvest_state(clay=2))
    assert reached
    state = step(state, FireTrigger(card_id=CARD_ID, variant="2"))
    assert _score_fn()(state, 0) == 2
