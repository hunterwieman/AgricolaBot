"""Tests for Butler (occupation, C100; Corbarius Expansion).

Card text: "If you play this card in round 11 or before, during scoring, you get 4
bonus points if you then have more rooms than people."

Butler combines a play-TIME gate (round ≤ 11, snapshotted in CardStore at play) with
a derived end-game read (strictly more rooms than people_total). Coverage:
registration, the snapshot via the real Lessons play flow, the round-11 gate boundary
(11 in / 12 out), the strict-`>` rooms-vs-people boundary, and the default-0 (never
snapshotted) behavior.
"""
import agricola.cards.butler  # noqa: F401

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import register_scoring  # noqa: F401  (ensures import path)
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, CardStore
from tests.factories import with_grid

CARD_ID = "butler"

_POOL = CardPool(
    occupations=("butler",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _set_round(state, n):
    return fast_replace(state, round_number=n)


def _set_card_state(state, idx, store):
    p = fast_replace(state.players[idx], card_state=store)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_people(state, idx, total):
    p = fast_replace(state.players[idx], people_total=total)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_rooms(state, idx, room_cells):
    """Make exactly `room_cells` ROOM cells (on top of whatever else is present)."""
    return with_grid(state, idx, {(r, c): Cell(cell_type=CellType.ROOM)
                                  for (r, c) in room_cells})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_butler_registered_as_occupation_and_scoring():
    assert CARD_ID in OCCUPATIONS
    from agricola.scoring import SCORING_TERMS
    assert CARD_ID in {card_id for card_id, _fn in SCORING_TERMS}


# ---------------------------------------------------------------------------
# on_play snapshot via the real Lessons flow
# ---------------------------------------------------------------------------

def _play_butler_via_lessons(seed):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"butler"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="butler"))
    return cs, cp


def test_butler_snapshots_gate_in_when_played_round_1():
    cs, cp = _play_butler_via_lessons(5)
    assert cs.round_number == 1
    assert cs.players[cp].card_state.get(CARD_ID) == 1   # gated in (round ≤ 11)
    assert "butler" in cs.players[cp].occupations


def test_butler_snapshots_gate_in_at_round_11_boundary():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    cs = _set_round(cs, 11)
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"butler"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="butler"))
    assert cs.players[cp].card_state.get(CARD_ID) == 1   # round 11 still gates in


def test_butler_snapshots_gate_out_at_round_12():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    cs = _set_round(cs, 12)
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"butler"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="butler"))
    assert cs.players[cp].card_state.get(CARD_ID) == 0   # round 12 → never eligible


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _own_butler(state, idx):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {"butler"})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_butler_scores_4_when_gated_in_and_more_rooms_than_people():
    s = setup(0)
    s = _own_butler(s, 0)
    s = _set_card_state(s, 0, CardStore().set(CARD_ID, 1))   # gated in
    s = _set_people(s, 0, 2)
    s = _set_rooms(s, 0, [(0, 0), (0, 1), (0, 2)])           # +3 rooms (default has 2)
    from agricola.cards.butler import _num_rooms
    assert _num_rooms(s.players[0]) == 5                      # 5 rooms > 2 people
    _t, bd = score(s, 0)
    assert bd.card_points == 4


def test_butler_scores_0_when_rooms_equal_people_strict():
    """Strict >: 2 rooms vs 2 people is NOT more rooms than people."""
    s = setup(0)
    s = _own_butler(s, 0)
    s = _set_card_state(s, 0, CardStore().set(CARD_ID, 1))   # gated in
    s = _set_people(s, 0, 2)                                  # default farm = 2 rooms
    from agricola.cards.butler import _num_rooms
    assert _num_rooms(s.players[0]) == 2
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_butler_scores_0_when_more_people_than_rooms():
    s = setup(0)
    s = _own_butler(s, 0)
    s = _set_card_state(s, 0, CardStore().set(CARD_ID, 1))   # gated in
    s = _set_people(s, 0, 4)                                  # 2 rooms < 4 people
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_butler_scores_0_when_gated_out_even_with_more_rooms():
    """Even with the rooms>people condition met, a round-12 play (gate 0) scores 0."""
    s = setup(0)
    s = _own_butler(s, 0)
    s = _set_card_state(s, 0, CardStore().set(CARD_ID, 0))   # gated OUT
    s = _set_people(s, 0, 2)
    s = _set_rooms(s, 0, [(0, 0), (0, 1), (0, 2)])           # 3 rooms > 2 people
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_butler_scores_0_when_never_snapshotted():
    """A state that never ran on_play (gate flag absent) scores 0 by default."""
    s = setup(0)
    s = _own_butler(s, 0)                                     # owned but no card_state
    s = _set_people(s, 0, 2)
    s = _set_rooms(s, 0, [(0, 0), (0, 1), (0, 2)])           # rooms>people, but no gate
    assert s.players[0].card_state.get(CARD_ID, 0) == 0
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_butler_scoring_is_per_player_scoped():
    """Only the owner with the gate-in flag scores; the opponent scores 0."""
    s = setup(0)
    s = _own_butler(s, 0)
    s = _set_card_state(s, 0, CardStore().set(CARD_ID, 1))
    s = _set_people(s, 0, 2)
    s = _set_rooms(s, 0, [(0, 0), (0, 1), (0, 2)])
    _t0, bd0 = score(s, 0)
    _t1, bd1 = score(s, 1)
    assert bd0.card_points == 4
    assert bd1.card_points == 0
