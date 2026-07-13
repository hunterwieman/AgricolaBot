"""Tests for Swimming Class (minor improvement, A35; Artifex Expansion).

Card text: "In the returning home phase of each round, if you return a person
from the 'Fishing' accumulation space, you get 2 bonus points for each newborn
that you return home."

An automatic effect (ruling 21: "you get" is choice-free) on the round-end
ladder's ``returning_home`` window (ruling 49, 2026-07-12), which fires BEFORE
the return-home reset — so eligibility reads the STILL-PLACED board (the
player's worker on the ``fishing`` space) plus ``newborns > 0``, and each fire
banks ``2 x newborns`` in the per-card CardStore counter, read back at
end-game by a scoring term (the Furniture Carpenter banked-VP idiom).

The fire tests drive the REAL round-end walk (`_advance_until_decision` on a
drained WORK state — every person placed, the owner's worker recorded on the
space under test), mirroring test_round_end_ladder.py's `_drained_work_state`.
"""
from __future__ import annotations

import agricola.cards.swimming_class  # noqa: F401  (register the card)

from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from agricola.state import get_space, with_space

CARD_ID = "swimming_class"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _drained_work_state(*, round_number=1, space_id="fishing", newborns=0,
                        seed=0):
    """A WORK state with every person placed (people_home=0), player 0's
    worker recorded on `space_id` (so pre-reset occupancy is visible), and
    `newborns` births this round for player 0 (people_total bumped to keep
    the newborns-included-in-people_total invariant — a newborn is never
    placed, so people_home stays 0)."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    sp = get_space(state.board, space_id)
    assert sp.revealed  # permanents (fishing, forest, ...) are revealed at setup
    state = fast_replace(state, board=with_space(
        state.board, space_id, fast_replace(sp, workers=(1, 0))))
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    if newborns:
        p = state.players[0]
        state = _edit_player(state, 0, newborns=newborns,
                             people_total=p.people_total + newborns)
    return state


def _banked(state, idx=0):
    return state.players[idx].card_state.get(CARD_ID, 0)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources.food == 1          # cost: 1 Food
    assert spec.cost.resources.wood == 0
    assert spec.min_occupations == 2              # prerequisite: 2 Occupations
    assert spec.vps == 0                          # no printed VP (points earned)
    # The choice-free "you get" is an AUTO on the returning_home window ...
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("returning_home", ()))
    # ... and the banked points are read back by a scoring term.
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- The fire, through the real round-end walk --------------------------------

def test_fires_on_returning_home_and_scores():
    """Worker on Fishing + 1 newborn -> the returning_home window banks +2,
    and the end-game score gains exactly those 2 points."""
    state = _own_minor(_drained_work_state(newborns=1), 0)
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # round 1: no harvest
    assert _banked(state) == 2

    total_with, _ = score(state, 0)
    cleared = _edit_player(state, 0,
                           card_state=state.players[0].card_state.set(CARD_ID, 0))
    total_without, _ = score(cleared, 0)
    assert total_with == total_without + 2


def test_two_newborns_bank_four():
    """"2 bonus points for EACH newborn": two births this round -> +4."""
    state = _own_minor(_drained_work_state(newborns=2), 0)
    state = _advance_until_decision(state)
    assert _banked(state) == 4


def test_no_fire_when_worker_elsewhere():
    """The person returned must come from the Fishing space specifically."""
    state = _own_minor(_drained_work_state(space_id="forest", newborns=1), 0)
    state = _advance_until_decision(state)
    assert _banked(state) == 0


def test_no_fire_without_newborn():
    """Fishing occupied but no newborn to return home -> nothing banked."""
    state = _own_minor(_drained_work_state(newborns=0), 0)
    state = _advance_until_decision(state)
    assert _banked(state) == 0


def test_fires_on_harvest_round_before_harvest():
    """UNCONDITIONED on the round kind (ruling 49: the returning-home phase is
    distinct from and precedes the harvest): on round 4 the points are banked
    by the time the harvest begins."""
    state = _own_minor(_drained_work_state(round_number=4, newborns=1), 0)
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)
    assert _banked(state) == 2


def test_accumulates_across_rounds():
    """The bank is cumulative: a second qualifying round adds another +2."""
    state = _own_minor(_drained_work_state(newborns=1), 0)
    state = _advance_until_decision(state)
    assert _banked(state) == 2
    # Re-arm round 2 on the SAME state (keeping card_state): drained WORK,
    # worker back on Fishing, one fresh newborn.
    state = fast_replace(state, pending_stack=(), phase=Phase.WORK,
                         round_number=2)
    sp = get_space(state.board, "fishing")
    state = fast_replace(state, board=with_space(
        state.board, "fishing", fast_replace(sp, workers=(1, 0))))
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    state = _edit_player(state, 0, newborns=1)
    state = _advance_until_decision(state)
    assert _banked(state) == 4


def test_unowned_does_not_fire():
    """The registration is global but ownership-gated: without the played
    minor, the same board + newborn banks nothing and scores nothing."""
    state = _drained_work_state(newborns=1)      # no ownership
    state = _advance_until_decision(state)
    assert _banked(state) == 0
    total, _ = score(state, 0)
    cleared = _edit_player(state, 0,
                           card_state=state.players[0].card_state.set(CARD_ID, 0))
    total_cleared, _ = score(cleared, 0)
    assert total == total_cleared
