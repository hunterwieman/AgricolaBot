"""Tests for Pig Owner (occupation A153): the first time the owner has 5 housed wild
boars, they bank 3 bonus points — via the decision-boundary one-shot sweep, after
accommodation. The Hook Knife shape (boar/5/3 instead of sheep/8/2)."""
import agricola.cards.pig_owner  # noqa: F401  (registers the card)

import dataclasses

from agricola.cards.pig_owner import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import BOUNDARY_ONE_SHOTS
from agricola.engine import _advance_until_decision, _fire_boundary_one_shots
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import GameState

from scripts.profile_states import STATES
from tests.factories import with_animals


def _own(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in BOUNDARY_ONE_SHOTS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# --- The boundary sweep -----------------------------------------------------

def test_fires_at_five_housed_boar():
    s = _own(STATES["mid_round_6_basic"](), 0)     # cap-4 pastures + slots hold 5 boar
    s = with_animals(s, 0, boar=5)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 3
    assert CARD_ID in out.players[0].fired_once


def test_no_fire_below_threshold():
    s = _own(STATES["mid_round_6_basic"](), 0)
    s = with_animals(s, 0, boar=4)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0


def test_over_capacity_boar_do_not_fire():
    # 5 boar but the default farm can house only the house pet: not "on your farm".
    s = _own(setup(0), 0)
    s = with_animals(s, 0, boar=5)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0


def test_fires_only_once():
    s = _own(STATES["mid_round_6_basic"](), 0)
    s = with_animals(s, 0, boar=5)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 3
    out2 = _fire_boundary_one_shots(with_animals(out, 0, boar=5))
    assert out2.players[0].card_state.get(CARD_ID, 0) == 3


def test_unowned_never_fires():
    s = with_animals(STATES["mid_round_6_basic"](), 0, boar=5)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0


def test_fires_through_advance_until_decision():
    s = _own(STATES["mid_round_6_basic"](), 0)
    s = with_animals(s, 0, boar=5)
    out = _advance_until_decision(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 3


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score = _score_fn()
    state = setup(0)
    assert score(state, 0) == 0
    p = dataclasses.replace(state.players[0],
                            card_state=state.players[0].card_state.set(CARD_ID, 3))
    state = dataclasses.replace(state, players=(p, state.players[1]))
    assert score(state, 0) == 3
