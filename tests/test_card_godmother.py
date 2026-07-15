import agricola.cards.godmother  # noqa: F401
"""Tests for Godmother (occupation, Ephipparius E113).

Card text (verbatim): "Each time you take a "Family Growth" action, you also
get 1 vegetable."

A flat, choice-free reward -> automatic effects on the BEFORE windows:
`before_family_growth` (every growth that runs through the PendingFamilyGrowth
primitive — the cards-mode Basic Wish sub-action, card-granted growths) plus a
`before_action_space` auto + action-space hook for Urgent Wish for Children,
which is ATOMIC in both modes (its resolver grows the family inline without
ever pushing a growth frame, so the sub-action event can never fire there).
The two registrations are mutually exclusive by construction; the Urgent Wish
test pins that a single use pays exactly +1.
"""

import agricola.cards.autumn_mother  # noqa: F401  (the card-granted-growth flow)

from agricola.actions import (
    ChooseSubAction,
    CommitFamilyGrowth,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingActionSpace,
    PendingFamilyGrowth,
    PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space

from tests.factories import with_grid, with_phase, with_resources

CARD_ID = "godmother"
_URGENT = "urgent_wish_for_children"
_BASIC = "basic_wish_for_children"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx, cards=(CARD_ID,)):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | set(cards))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s, s.current_player


def _prep_basic_wish(cs, cp):
    """Reveal Basic Wish and give `cp` a 3rd room (growth needs a free room)."""
    cs = _reveal(cs, _BASIC)
    return with_grid(cs, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})


# --- Registration -----------------------------------------------------------

def test_registered_occupation_autos_and_hook():
    assert CARD_ID in OCCUPATIONS
    # Subset checks, never exact-set.
    assert any(e.card_id == CARD_ID and not e.any_player
               for e in AUTO_EFFECTS.get("before_family_growth", ()))
    assert any(e.card_id == CARD_ID and not e.any_player
               for e in AUTO_EFFECTS.get("before_action_space", ()))
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(_URGENT, set())


def test_on_play_is_a_noop():
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state


# --- Basic Wish (cards mode): the frame-pushed growth -------------------------

def test_basic_wish_growth_pays_one_veg_before_the_commit():
    cs, cp = _card_state()
    cs = _own(_prep_basic_wish(cs, cp), cp)
    cs = _edit_player(cs, cp, hand_minors=frozenset())
    veg0 = cs.players[cp].resources.veg
    pt0 = cs.players[cp].people_total

    cs = step(cs, PlaceWorker(space=_BASIC))
    assert legal_actions(cs) == [ChooseSubAction(name="family_growth")]
    cs = step(cs, ChooseSubAction(name="family_growth"))
    # BEFORE timing: the veg lands at the growth frame's push, ahead of the commit.
    assert cs.players[cp].resources.veg == veg0 + 1
    assert cs.players[cp].people_total == pt0
    assert legal_actions(cs) == [CommitFamilyGrowth()]
    cs = step(cs, CommitFamilyGrowth())
    assert cs.players[cp].people_total == pt0 + 1
    cs = step(cs, Stop())      # pop the growth's after-phase
    assert legal_actions(cs) == [Proceed()]
    cs = step(cs, Proceed())
    cs = step(cs, Stop())      # pop the parent's after-phase
    # Exactly +1 over the whole turn.
    assert cs.players[cp].resources.veg == veg0 + 1


# --- Urgent Wish (atomic in both modes): the hosted-space path ----------------

def test_urgent_wish_single_use_pays_exactly_one_veg():
    cs, cp = _card_state()
    cs = _own(_reveal(cs, _URGENT), cp)
    assert should_host_space(cs, _URGENT, cp)
    veg0 = cs.players[cp].resources.veg
    pt0 = cs.players[cp].people_total

    cs = step(cs, PlaceWorker(space=_URGENT))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.space_id == _URGENT
    assert top.phase == "before"
    # The before_action_space auto has fired at the placement.
    assert cs.players[cp].resources.veg == veg0 + 1
    assert legal_actions(cs) == [Proceed()]
    cs = step(cs, Proceed())   # the atomic resolver: inline growth, NO growth frame
    assert not any(isinstance(f, PendingFamilyGrowth) for f in cs.pending_stack)
    assert cs.players[cp].people_total == pt0 + 1
    assert cs.pending_stack[-1].phase == "after"
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())
    # Exactly +1: the atomic handler pushed no growth frame, so the
    # before_family_growth auto never fired on top of the space auto.
    assert cs.players[cp].resources.veg == veg0 + 1
    # And the growth landed on the space (parent + newborn).
    assert get_space(cs.board, _URGENT).workers[cp] == 2


# --- Card-granted growth (Autumn Mother's window trigger) ---------------------

def _walk_to_window(state, window_id, player_idx=0):
    """Advance until the given player's harvest-window frame is on top,
    stepping the first non-Autumn-Mother legal action everywhere else."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == window_id and top.player_idx == player_idx):
            return state, True
        acts = legal_actions(state)
        picked = next(
            (a for a in acts
             if not (isinstance(a, FireTrigger) and a.card_id == "autumn_mother")),
            acts[0])
        state = step(state, picked)
    return state, False


def test_card_granted_growth_pays_one_veg():
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = fast_replace(state, starting_player=0)
    state = _own(state, 0, cards=(CARD_ID, "autumn_mother"))
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    for idx in (0, 1):
        state = with_resources(state, idx, food=10)

    state, seen = _walk_to_window(state, "immediately_before_harvest")
    assert seen
    veg0 = state.players[0].resources.veg
    pt0 = state.players[0].people_total

    state = step(state, FireTrigger(card_id="autumn_mother"))
    # The growth frame was pushed by the trigger; the before-auto paid at the push.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth) and top.place_on_space is False
    assert state.players[0].resources.veg == veg0 + 1
    assert state.players[0].people_total == pt0
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == pt0 + 1
    assert state.players[0].resources.veg == veg0 + 1     # still exactly +1


# --- Boundaries ---------------------------------------------------------------

def test_no_veg_on_other_actions():
    cs, cp = _card_state()
    cs = _own(cs, cp)
    veg0 = cs.players[cp].resources.veg
    cs = step(cs, PlaceWorker(space="forest"))
    # Not hooked -> atomic fast path, no host frame, no veg.
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.veg == veg0


def test_opponents_growth_pays_nothing():
    cs, cp = _card_state()
    opp = 1 - cp
    # The NON-acting player owns Godmother; the acting player grows.
    cs = _own(_prep_basic_wish(cs, cp), opp)
    cs = _edit_player(cs, cp, hand_minors=frozenset())
    veg_owner0 = cs.players[opp].resources.veg
    veg_actor0 = cs.players[cp].resources.veg

    cs = step(cs, PlaceWorker(space=_BASIC))
    cs = step(cs, ChooseSubAction(name="family_growth"))
    cs = step(cs, CommitFamilyGrowth())
    assert cs.players[opp].resources.veg == veg_owner0
    assert cs.players[cp].resources.veg == veg_actor0


def test_hand_only_is_inert():
    cs, cp = _card_state()
    cs = _reveal(cs, _URGENT)
    p = cs.players[cp]
    cs = _edit_player(cs, cp,
                      hand_occupations=p.hand_occupations | {CARD_ID})
    assert not should_host_space(cs, _URGENT, cp)
    veg0 = cs.players[cp].resources.veg
    pt0 = cs.players[cp].people_total
    cs = step(cs, PlaceWorker(space=_URGENT))
    # Atomic fast path: growth happens, no host frame, no veg.
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].people_total == pt0 + 1
    assert cs.players[cp].resources.veg == veg0
