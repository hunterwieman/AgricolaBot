import agricola.cards.seed_researcher  # noqa: F401  (register the card)

"""Tests for Seed Researcher (occupation, C97; Corbarius Expansion).

Card text (verbatim): "Each time any people return from both the \"Grain
Seeds\" and \"Vegetable Seeds\" action spaces, you get 2 food and you can play
1 occupation, without paying an occupation cost."

Shape: the round-end ladder's ``returning_home`` window (ruling 49,
2026-07-12), PRE-reset so live occupancy is the event data. Two registrations:
an AUTO (+2 food to the owner) and an OPTIONAL FireTrigger (a free
PendingPlayOccupation, cost=Resources()), both gated on BOTH spaces holding a
worker — ANY players' workers ("any people"). These tests drive the REAL
round-end walk (`_advance_until_decision` on a drained WORK state), mirroring
test_card_swimming_class.py / test_card_silage.py.
"""
import agricola.cards.consultant  # noqa: F401  (a real occupation to play free)

from agricola.actions import CommitPlayOccupation, FireTrigger, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import get_space, with_space

CARD_ID = "seed_researcher"
_OCC = "consultant"   # plays free of its own (on-play: +3 clay in 2p)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _with_hand_occupation(state, idx, occ_id):
    p = state.players[idx]
    return _edit_player(state, idx,
                        hand_occupations=p.hand_occupations | {occ_id})


def _set_workers(state, space_id, workers, *, reveal=False):
    sp = get_space(state.board, space_id)
    if reveal:
        sp = fast_replace(sp, revealed=True)
    assert sp.revealed  # a worker can only sit on a revealed space
    return fast_replace(state, board=with_space(
        state.board, space_id, fast_replace(sp, workers=workers)))


def _drained_work_state(*, round_number=1, grain_workers=(0, 0),
                        veg_workers=(0, 0), seed=0):
    """A WORK state with every person placed (people_home=0) and the two
    named spaces' worker tuples set directly (pre-reset occupancy is what the
    returning_home window reads). Vegetable Seeds is a Stage 3 round card, so
    it is revealed here whenever a worker is put on it."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number,
                         starting_player=0)
    state = _set_workers(state, "grain_seeds", grain_workers)
    state = _set_workers(state, "vegetable_seeds", veg_workers, reveal=True)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _walk_to_window(state):
    """Advance to P0's returning_home window frame (the ladder pauses there)."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no returning_home window surfaced (top={top!r}, phase={state.phase})")
    assert top.window_id == "returning_home" and top.player_idx == 0
    return state


def _no_returning_home_pause(state):
    """Advance and assert the walk never pauses at a returning_home window."""
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == "returning_home"
        for f in state.pending_stack)
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS                     # a playable occupation
    # "you get 2 food" -> an AUTO on the returning_home window ...
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("returning_home", ()))
    # ... and "you can play 1 occupation" -> an OPTIONAL trigger there too.
    entry = CARDS[CARD_ID]
    assert entry.event == "returning_home"
    assert entry.mandatory is False                   # "you can"


# --- The fire, through the real round-end walk ("any people") -----------------

def test_mixed_workers_fire_auto_and_offer_trigger():
    """My worker on Grain Seeds + the OPPONENT's on Vegetable Seeds ("any
    people"): the walk pauses at the returning_home window with the +2 food
    already landed (autos precede the frames) and the free play on offer."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    state = _own_occ(state, 0)
    state = _with_hand_occupation(state, 0, _OCC)
    food_before = state.players[0].resources.food

    state = _walk_to_window(state)
    assert state.players[0].resources.food == food_before + 2
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


def test_both_workers_opponents_still_pays_owner():
    """"Any people" pinned hard: BOTH qualifying workers are the opponent's —
    the owner (P0) still gets the 2 food and the free-play offer; the opponent
    gets nothing even though their workers did all the qualifying."""
    state = _drained_work_state(grain_workers=(0, 1), veg_workers=(0, 1))
    state = _own_occ(state, 0)
    state = _with_hand_occupation(state, 0, _OCC)
    p0_food = state.players[0].resources.food
    p1_food = state.players[1].resources.food

    state = _walk_to_window(state)
    assert state.players[0].resources.food == p0_food + 2
    assert state.players[1].resources.food == p1_food     # opponent: nothing
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


def test_free_occupation_play_end_to_end():
    """Firing pushes a FREE PendingPlayOccupation (cost=Resources()); the
    commit plays the hand occupation for 0 food — the owner already has one
    occupation played (this card), so a paid route would charge 1 food — then
    the frame flips to after (Stop), the window swallows a re-offer
    (Proceed only), and the walk completes."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    state = _own_occ(state, 0)
    state = _with_hand_occupation(state, 0, _OCC)
    state = _walk_to_window(state)

    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources()                    # FREE play
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert CommitPlayOccupation(card_id=_OCC) in legal_actions(state)

    food_before_play = state.players[0].resources.food
    state = step(state, CommitPlayOccupation(card_id=_OCC))
    p = state.players[0]
    assert p.resources.food == food_before_play       # nothing debited
    assert _OCC in p.occupations                      # hand -> tableau
    assert _OCC not in p.hand_occupations
    assert p.resources.clay == 3                      # consultant's on-play ran
    assert state.pending_stack[-1].phase == "after"
    assert Stop() in legal_actions(state)

    state = step(state, Stop())                       # pop the play frame
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert legal_actions(state) == [Proceed()]        # once per round: no re-offer

    state = step(state, Proceed())
    state = _no_returning_home_pause(state)           # the walk completed


# --- Eligibility boundaries ---------------------------------------------------

def test_one_space_occupied_is_nothing():
    """"From BOTH spaces": either space alone qualifies nothing — no food, no
    window pause."""
    for grain, veg in (((1, 0), (0, 0)), ((0, 0), (0, 1))):
        state = _drained_work_state(grain_workers=grain, veg_workers=veg)
        state = _own_occ(state, 0)
        state = _with_hand_occupation(state, 0, _OCC)
        food_before = state.players[0].resources.food
        out = _no_returning_home_pause(state)
        assert out.players[0].resources.food == food_before
        assert _OCC in out.players[0].hand_occupations


def test_neither_space_occupied_is_nothing():
    state = _drained_work_state()
    state = _own_occ(state, 0)
    state = _with_hand_occupation(state, 0, _OCC)
    food_before = state.players[0].resources.food
    out = _no_returning_home_pause(state)
    assert out.players[0].resources.food == food_before


def test_no_playable_occupation_auto_still_fires_without_trigger():
    """An empty hand kills the free-play offer (never a dead-end fire) but
    NOT the choice-free +2 food: the auto lands and the walk never hosts."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    state = _own_occ(state, 0)                        # hand stays empty
    food_before = state.players[0].resources.food
    out = _no_returning_home_pause(state)
    assert out.players[0].resources.food == food_before + 2


# --- Optionality — declining = not firing ---------------------------------------

def test_free_play_is_declinable():
    """Proceed without firing: the 2 food (mandatory) stays, the occupation
    stays in hand (the optional play was declined)."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    state = _own_occ(state, 0)
    state = _with_hand_occupation(state, 0, _OCC)
    food_before = state.players[0].resources.food
    state = _walk_to_window(state)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)

    state = step(state, Proceed())
    state = _no_returning_home_pause(state)
    p = state.players[0]
    assert p.resources.food == food_before + 2        # the auto was not optional
    assert _OCC in p.hand_occupations                 # play declined
    assert _OCC not in p.occupations


# --- Scoping: fires each qualifying round ----------------------------------------

def test_fires_each_qualifying_round():
    """"Each time": a second qualifying round pays another +2 (no per-game
    latch)."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    state = _own_occ(state, 0)                        # empty hand: auto-only
    food_before = state.players[0].resources.food
    state = _no_returning_home_pause(state)
    assert state.players[0].resources.food == food_before + 2

    # Re-arm round 2 on the SAME state: drained WORK, both spaces re-occupied.
    state = fast_replace(state, pending_stack=(), phase=Phase.WORK,
                         round_number=2)
    state = _set_workers(state, "grain_seeds", (1, 0))
    state = _set_workers(state, "vegetable_seeds", (0, 1))
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    state = _no_returning_home_pause(state)
    assert state.players[0].resources.food == food_before + 4


# --- Ownership gates ----------------------------------------------------------------

def test_unowned_does_nothing():
    """Nobody played the card: the same qualifying board pays nobody."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    foods = [p.resources.food for p in state.players]
    out = _no_returning_home_pause(state)
    assert [p.resources.food for p in out.players] == foods


def test_hand_only_is_inert():
    """A hand copy cannot fire — ownership means PLAYED."""
    state = _drained_work_state(grain_workers=(1, 0), veg_workers=(0, 1))
    state = _with_hand_occupation(state, 0, CARD_ID)  # in hand, never played
    state = _with_hand_occupation(state, 0, _OCC)
    food_before = state.players[0].resources.food
    out = _no_returning_home_pause(state)
    assert out.players[0].resources.food == food_before
