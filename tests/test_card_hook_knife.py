"""Tests for Hook Knife (minor B35): once per game, reaching 8 housed sheep (2-player)
banks 2 bonus points — via the decision-boundary one-shot sweep, after accommodation."""
import agricola.cards.hook_knife  # noqa: F401  (registers the card)

import dataclasses

from agricola.cards.hook_knife import CARD_ID
from agricola.cards.triggers import BOUNDARY_ONE_SHOTS
from agricola.engine import _advance_until_decision, _fire_boundary_one_shots
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import GameState

from scripts.profile_states import STATES
from tests.factories import with_animals


def _own(state: GameState, idx: int, card_id: str) -> GameState:
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    from agricola.cards.specs import MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert CARD_ID in BOUNDARY_ONE_SHOTS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- The boundary sweep -----------------------------------------------------

def test_fires_at_eight_housed_sheep():
    # mid_round_6_basic player 0 has two cap-4 pastures (+ flexible slots) -> 8 sheep fit.
    s = _own(STATES["mid_round_6_basic"](), 0, CARD_ID)
    s = with_animals(s, 0, sheep=8)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 2
    assert CARD_ID in out.players[0].fired_once


def test_no_fire_below_threshold():
    s = _own(STATES["mid_round_6_basic"](), 0, CARD_ID)
    s = with_animals(s, 0, sheep=7)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0


def test_over_capacity_sheep_do_not_fire():
    # 8 sheep but the default farm can house only 1 (the house pet): not "on your farm",
    # so no award — the accommodation guard (the un-trimmed-grant case).
    s = _own(setup(0), 0, CARD_ID)          # no pastures -> capacity 1
    s = with_animals(s, 0, sheep=8)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0


def test_fires_only_once():
    s = _own(STATES["mid_round_6_basic"](), 0, CARD_ID)
    s = with_animals(s, 0, sheep=8)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 2
    # Even with more sheep later, the game-long latch prevents a re-bank.
    out2 = with_animals(out, 0, sheep=8)
    out2 = _fire_boundary_one_shots(out2)
    assert out2.players[0].card_state.get(CARD_ID, 0) == 2


def test_unowned_never_fires():
    s = with_animals(STATES["mid_round_6_basic"](), 0, sheep=8)   # no one owns the card
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0


# --- Wired into the decision-boundary walk ----------------------------------

def test_fires_through_advance_until_decision():
    s = _own(STATES["mid_round_6_basic"](), 0, CARD_ID)
    s = with_animals(s, 0, sheep=8)
    out = _advance_until_decision(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 2


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score = _score_fn()
    state = setup(0)
    assert score(state, 0) == 0
    p = dataclasses.replace(state.players[0],
                            card_state=state.players[0].card_state.set(CARD_ID, 2))
    state = dataclasses.replace(state, players=(p, state.players[1]))
    assert score(state, 0) == 2
