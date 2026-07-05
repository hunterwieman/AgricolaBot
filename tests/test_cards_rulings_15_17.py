"""Tests for the three cards landed on user rulings 15-17 (2026-07-05):

- Baker (C107, occupation): "When you play this card and at the start of each
  feeding phase, you can take a 'Bake Bread' action." On-play decline is WIDE
  (ruling 17: two distinct play variants); the feeding grant is a
  start_of_feeding trigger.
- Milking Place (D12, minor): "In the feeding phase of each harvest, you get 1
  food. You can no longer hold animals in your house (not even via another
  card)." Feeding income + the house-pet-capacity NEGATION (beats Animal Tamer).
- Shepherd's Whistle (E83, minor): "At the start of the breeding phase of each
  harvest, if you have at least 1 unfenced stable without an animal, you get 1
  sheep." Ruling 16 (as amended): a stable is free iff the animals fit with one
  unfenced stable removed; free -> automatic sheep; else a Pareto make-room
  choice over animals PLUS the received-vs-declined dimension (received
  dominates declined iff a sheep-conversion opportunity exists — so
  cook-a-sheep-and-replace-it survives with a Fireplace, dies without one);
  declining forfeits the sheep entirely.
"""
from __future__ import annotations

import agricola.cards.baker  # noqa: F401
import agricola.cards.milking_place  # noqa: F401
import agricola.cards.shepherds_whistle  # noqa: F401

from agricola.actions import (
    CommitBake,
    CommitPlayOccupation,
    FireTrigger,
    Proceed,
)
from agricola.cards.capacity_mods import house_pet_capacity
from agricola.cards.shepherds_whistle import _options, _stable_is_free
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingAccommodate,
    PendingBakeBread,
    PendingHarvestWindow,
    PendingPlayOccupation,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_pending_stack, with_phase

BAKER, MP, SW = "baker", "milking_place", "shepherds_whistle"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx, card_id, *, minor=True):
    p = state.players[idx]
    if minor:
        return _edit_player(state, idx,
                            minor_improvements=p.minor_improvements | {card_id})
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _with_fireplace(state, idx):
    owners = list(state.board.major_improvement_owners)
    owners[0] = idx
    return fast_replace(state, board=fast_replace(
        state.board, major_improvement_owners=tuple(owners)))


def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _walk_to_window(state, window_id):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == window_id:
            return state
        state = step(state, legal_actions(state)[0])
    return state


# ---------------------------------------------------------------------------
# Baker — the wide on-play decline (ruling 17)
# ---------------------------------------------------------------------------

def _baker_play_state(seed=0, *, grain=1, fireplace=True):
    """A WORK state with Baker in hand at a PendingPlayOccupation host."""
    state = with_phase(setup(seed), Phase.WORK)
    cp = state.current_player
    state = _edit_player(state, cp,
                         hand_occupations=frozenset({BAKER}),
                         resources=fast_replace(
                             state.players[cp].resources, grain=grain, food=2))
    if fireplace:
        state = _with_fireplace(state, cp)
    frame = PendingPlayOccupation(player_idx=cp,
                                  initiated_by_id="space:lessons",
                                  cost=Resources())
    return with_pending_stack(state, [frame]), cp


def test_baker_play_offers_bake_and_decline_variants():
    state, cp = _baker_play_state()
    plays = [a for a in legal_actions(state)
             if isinstance(a, CommitPlayOccupation) and a.card_id == BAKER]
    assert sorted(a.variant for a in plays) == ["bake", "decline_bake"]


def test_baker_play_bake_variant_pushes_a_real_bake():
    state, cp = _baker_play_state()
    state = step(state, CommitPlayOccupation(card_id=BAKER, variant="bake"))
    assert isinstance(state.pending_stack[-1], PendingBakeBread)
    f0 = state.players[cp].resources.food
    state = step(state, CommitBake(grain=1))            # Fireplace: 1 -> 2
    assert state.players[cp].resources.food == f0 + 2


def test_baker_play_decline_variant_bakes_nothing():
    state, cp = _baker_play_state()
    g0 = state.players[cp].resources.grain
    state = step(state, CommitPlayOccupation(card_id=BAKER, variant="decline_bake"))
    assert not isinstance(state.pending_stack[-1], PendingBakeBread)
    assert BAKER in state.players[cp].occupations
    assert state.players[cp].resources.grain == g0


def test_baker_play_without_usable_bake_offers_decline_only():
    state, cp = _baker_play_state(grain=0)              # nothing to bake
    plays = [a for a in legal_actions(state)
             if isinstance(a, CommitPlayOccupation) and a.card_id == BAKER]
    assert [a.variant for a in plays] == ["decline_bake"]


def test_baker_feeding_grant_fires_and_declines():
    state = _own(_with_fireplace(_harvest_state(), 0), 0, BAKER, minor=False)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, grain=1))
    state = _walk_to_window(state, "start_of_feeding")
    assert FireTrigger(card_id=BAKER) in legal_actions(state)
    f0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=BAKER))
    assert isinstance(state.pending_stack[-1], PendingBakeBread)
    state = step(state, CommitBake(grain=1))
    assert state.players[0].resources.food == f0 + 2    # payable at feeding


# ---------------------------------------------------------------------------
# Milking Place — income + the house-pet negation
# ---------------------------------------------------------------------------

def test_mp_negation_zeroes_the_house_slot_and_beats_animal_tamer():
    state = setup(0)
    assert house_pet_capacity(state.players[0]) == 1          # the default pet
    state = _own(state, 0, MP)
    assert house_pet_capacity(state.players[0]) == 0          # forbidden
    # "not even via another card": Animal Tamer's raise is overridden.
    state = _own(state, 0, "animal_tamer", minor=False)
    assert house_pet_capacity(state.players[0]) == 0


def test_mp_income_at_feeding():
    state = _own(_harvest_state(food=3), 0, MP)
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, legal_actions(state)[0])
    # 3 food + 1 income - 4 feeding = 0, no begging.
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 0


def test_mp_play_evicts_a_house_animal():
    """Playing it with a lone pet sheep (no other capacity) forces the
    accommodation choice — the sheep no longer fits anywhere."""
    state = with_phase(setup(0), Phase.WORK)
    state = _edit_player(state, 0, animals=Animals(sheep=1))
    from agricola.cards.specs import MINORS
    state = _own(state, 0, MP)
    state = MINORS[MP].on_play(state, 0)
    state = _advance_until_decision(state)
    assert isinstance(state.pending_stack[-1], PendingAccommodate)
    # The only option: keep nothing (the sheep is released).
    state = step(state, legal_actions(state)[0])
    assert state.players[0].animals.sheep == 0


# ---------------------------------------------------------------------------
# Shepherd's Whistle — ruling 16
# ---------------------------------------------------------------------------

def _sw_state(seed=0, *, stables=((0, 4),), animals=Animals(), fireplace=False):
    state = _harvest_state(seed)
    state = _own(state, 0, SW)
    state = with_grid(state, 0, {rc: Cell(cell_type=CellType.STABLE)
                                 for rc in stables})
    state = _edit_player(state, 0, animals=animals)
    if fireplace:
        state = _with_fireplace(state, 0)
    return state


def test_sw_no_unfenced_stable_nothing_happens():
    state = _own(_harvest_state(), 0, SW)          # no stable at all
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, legal_actions(state)[0])
    assert state.players[0].animals.sheep == 0


def test_sw_free_stable_grants_sheep_automatically():
    # One stable, no animals: trivially free -> +1 sheep, no choice frame.
    state = _sw_state()
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        assert not (isinstance(top, PendingHarvestWindow)
                    and top.window_id == "start_of_breeding")
        state = step(state, legal_actions(state)[0])
    assert state.players[0].animals.sheep >= 1     # granted (and maybe bred)


def test_sw_granted_sheep_can_breed():
    """The grant lands BEFORE the breeding decision: 1 existing sheep + the
    granted sheep = a pair -> a newborn (a second stable gives the newborn
    room; breeding requires accommodating it)."""
    state = _sw_state(stables=((0, 4), (1, 4)), animals=Animals(sheep=1))
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        acts = legal_actions(state)
        # Prefer breeding when offered (the frontier's max-sheep option).
        best = max(acts, key=lambda a: getattr(a, "sheep", 0))
        state = step(state, best)
    assert state.players[0].animals.sheep == 3     # 1 + granted 1 + newborn 1


def test_sw_tight_farm_offers_make_room_options():
    """Pet + 1 stable, holding 1 boar + 1 cattle: no stable is free. Options:
    cook the boar or the cattle to free the stable for the sheep; declining
    keeps both and forfeits the sheep (it is never cooked)."""
    state = _sw_state(animals=Animals(boar=1, cattle=1), fireplace=True)
    assert not _stable_is_free(state, 0)
    opts = {(a.sheep, a.boar, a.cattle) for a, _f in _options(state, 0)}
    assert opts == {(1, 1, 0), (1, 0, 1)}
    state = _walk_to_window(state, "start_of_breeding")
    fires = [a for a in legal_actions(state)
             if isinstance(a, FireTrigger) and a.card_id == SW]
    assert sorted(a.variant for a in fires) == ["s1b0c1", "s1b1c0"]
    f0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=SW, variant="s1b1c0"))
    a = state.players[0].animals
    assert (a.sheep, a.boar, a.cattle) == (1, 1, 0)
    assert state.players[0].resources.food == f0 + 3   # cattle cooked (Fireplace)


def test_sw_decline_forfeits_the_sheep_entirely():
    state = _sw_state(animals=Animals(boar=1, cattle=1), fireplace=True)
    state = _walk_to_window(state, "start_of_breeding")
    f0 = state.players[0].resources.food
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    a = state.players[0].animals
    assert (a.sheep, a.boar, a.cattle) == (0, 1, 1)    # unchanged
    assert state.players[0].resources.food == f0       # no phantom-sheep food


def test_sw_cook_and_replace_survives_when_cooking_pays():
    """Holding 2 sheep (pet + the stable) WITH a Fireplace: cooking a sheep and
    letting the Whistle replace it ends animal-identical to declining but +2
    food — the received-vs-declined dimension (ruling 16 as amended) keeps it,
    because the replaced sheep makes the food non-deferrable."""
    state = _sw_state(animals=Animals(sheep=2), fireplace=True)
    assert not _stable_is_free(state, 0)
    opts = {((a.sheep, a.boar, a.cattle), f) for a, f in _options(state, 0)}
    assert ((2, 0, 0), 2) in opts
    state = _walk_to_window(state, "start_of_breeding")
    f0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=SW, variant="s2b0c0"))
    a = state.players[0].animals
    assert (a.sheep, a.boar, a.cattle) == (2, 0, 0)     # sheep replaced
    assert state.players[0].resources.food == f0 + 2    # the cooked sheep


def test_sw_cook_and_replace_pruned_without_cooking():
    """The same holding WITHOUT any cooking improvement: the replace option is
    genuinely identical to declining (zero food), so nothing is offered and
    the window passes silently."""
    state = _sw_state(animals=Animals(sheep=2), fireplace=False)
    assert not _stable_is_free(state, 0)
    assert _options(state, 0) == []
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        assert not (isinstance(top, PendingHarvestWindow)
                    and top.window_id == "start_of_breeding")
        acts = legal_actions(state)
        best = max(acts, key=lambda a: getattr(a, "sheep", 0))
        state = step(state, best)
