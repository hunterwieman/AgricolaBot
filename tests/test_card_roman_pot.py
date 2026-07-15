"""Tests for Roman Pot (minor improvement, E56; Ephipparius Expansion).

Card text: "Place 4 food from the general supply on this card. At the start of
each work phase, if you are the last player in turn order, move 1 food from this
card to your supply."
Cost 1 clay; no prereq; 1 VP.

Two parts, driven through real engine flows:
  ON PLAY — 4 food seeded, via the real PendingPlayMinor -> CommitPlayMinor flow.
  START-OF-WORK DRIP — a mandatory start_of_work auto (the Trout Pool precedent),
    fired by the preparation ladder (`_complete_preparation`): the LAST player in
    turn order moves 1 food from the card to supply, gated on the card holding
    food. The last-player test uses the general formula and both starting-player
    assignments to confirm it is not seat-hardcoded.
"""
from __future__ import annotations

import agricola.cards.roman_pot  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "roman_pot"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _held(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _prep_state(idx, *, held, starting_player, from_round=1):
    """A PREPARATION state (entering round from_round+1) where seat idx owns Roman
    Pot with `held` food and the given starting player."""
    s = setup(0)
    p = fast_replace(
        s.players[idx],
        minor_improvements=s.players[idx].minor_improvements | {CARD_ID},
        card_state=s.players[idx].card_state.set(CARD_ID, held),
    )
    s = fast_replace(s, players=tuple(p if i == idx else s.players[i] for i in range(2)))
    return fast_replace(s, phase=Phase.PREPARATION, round_number=from_round,
                        starting_player=starting_player)


# --------------------------------------------------------------------------- registration

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=1))
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0
    # A start_of_work AUTO (mandatory, choice-free) — not an optional trigger.
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("start_of_work", ()))
    assert all(e.card_id != CARD_ID for e in TRIGGERS.get("start_of_work", []))


# --------------------------------------------------------------------------- on_play (real flow)

def test_play_seeds_four_food_paying_clay():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}),
                     resources=Resources(clay=1))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.clay == 0          # paid 1 clay
    assert _held(cs, cp) == 4             # on_play placed 4 food on the card


# --------------------------------------------------------------------------- start-of-work drip

def test_last_player_gets_food():
    # starting_player=0 -> turn order [0, 1] -> P1 is last.
    s = _prep_state(1, held=4, starting_player=0)
    before = s.players[1].resources.food
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.phase is Phase.WORK
    assert out.players[1].resources.food == before + 1
    assert _held(out, 1) == 3             # 4 -> 3 on the card


def test_starting_player_gets_nothing():
    # starting_player=0 -> P0 is FIRST, not last -> no drip.
    s = _prep_state(0, held=4, starting_player=0)
    before = s.players[0].resources.food
    out = _complete_preparation(s)
    assert out.players[0].resources.food == before
    assert _held(out, 0) == 4             # untouched


def test_general_formula_with_starting_player_one():
    # starting_player=1 -> turn order [1, 0] -> P0 is last.
    s = _prep_state(0, held=4, starting_player=1)
    before = s.players[0].resources.food
    out = _complete_preparation(s)
    assert out.players[0].resources.food == before + 1   # P0 is last -> paid
    assert _held(out, 0) == 3
    # And the OTHER seat (P1) as owner with sp=1 is first -> nothing.
    s2 = _prep_state(1, held=4, starting_player=1)
    before2 = s2.players[1].resources.food
    out2 = _complete_preparation(s2)
    assert out2.players[1].resources.food == before2
    assert _held(out2, 1) == 4


def test_stops_paying_when_card_empty():
    # Last player, only 1 food left -> drips it, then dries up.
    s = _prep_state(1, held=1, starting_player=0)
    before = s.players[1].resources.food
    out = _complete_preparation(s)
    assert out.players[1].resources.food == before + 1
    assert _held(out, 1) == 0
    # Next work phase: empty card -> no more drip.
    s2 = fast_replace(out, phase=Phase.PREPARATION)
    f2 = s2.players[1].resources.food
    out2 = _complete_preparation(s2)
    assert out2.players[1].resources.food == f2
    assert _held(out2, 1) == 0


def test_only_owning_last_player_paid():
    # P1 owns + is last (sp=0); P0 owns nothing. Only P1 drips.
    s = _prep_state(1, held=4, starting_player=0)
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food
    out = _complete_preparation(s)
    assert out.players[1].resources.food == f1 + 1
    assert out.players[0].resources.food == f0     # non-owner unaffected
    assert _held(out, 0) == 0                        # P0 never had the card
