import agricola.cards.mud_patch  # noqa: F401

"""Tests for Mud Patch (minor improvement, A11; Artifex Expansion).

Card text (verbatim): "When you play this card, you immediately get 1 wild boar.
You can hold 1 wild boar on each of your unplanted field tiles."

USER RULINGS (both 2026-07-21): the capacity is per UNPLANTED field tile (the
printed reading — not all tiles); the typed-slot fold direction (per-species
independent strip).

Two effects: an on-play grant of 1 boar routed through `helpers.grant_animals`
(the accommodation barrier surfaces the keep-or-cook choice on overflow), and a
boar-only card slot equal to the number of unplanted board FIELD tiles
(`register_typed_slots`, realized by the greedy strip). The subtle part is
EVICTION: the slot count DROPS when the owner sows a board field or plays Stone
Clearing onto empty fields, so Mud Patch re-arms the barrier at those own-action
seams (`after_sow` / `after_play_minor` autos, gated on holding a boar).

Coverage: registration; unplanted-tile count (planted / card-field / stone
excluded); tableau-only; capacity rises on plow; the boar-only strip; the
on-play boar arriving through the barrier over capacity; and the eviction end to
end through a real Grain Utilization sow.
"""
import dataclasses

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitSow,
    PlaceWorker,
)
from agricola.cards.capacity_mods import TYPED_SLOT_CARDS, typed_slot_counts
from agricola.cards.mud_patch import CARD_ID, _slots, _unplanted_field_tiles
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.engine import _advance_until_decision, step
from agricola.helpers import accommodates
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

# Throwaway state for the (state, player_state) accommodation-helper signature;
# this card reads only the player's farm, so any state is inert as the state arg.
_S = setup(0)

from tests.factories import (
    with_animals,
    with_fields,
    with_grid,
    with_resources,
    with_space,
)

# A card pool carrying mud_patch (plus filler ids) so the real-flow test runs in
# a card-mode state; the sow machinery + autos are identical to a real game.
_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx=0):
    p = state.players[idx]
    return dataclasses.replace(
        state,
        players=tuple(
            fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
            if i == idx else state.players[i]
            for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    import json

    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                 # no cost
    assert spec.vps == 0                        # no printed VPs
    assert spec.prereq is None                  # no prerequisite
    assert not spec.passing_left                # kept, not passing
    from agricola.cards.mud_patch import _on_play
    assert spec.on_play is _on_play             # on-play grant wired

    # The boar-only typed slot is registered.
    slot_fns = [fn for cid, fn in TYPED_SLOT_CARDS if cid == CARD_ID]
    assert len(slot_fns) == 1
    assert slot_fns[0](_S, _S.players[0]) == Animals()  # bare farm: no fields

    # Both eviction autos are registered.
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("after_sow", [])}
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("after_play_minor", [])}

    rows = json.load(open("agricola/cards/data/revised_minor_improvements.json"))
    row = next(r for r in rows if r["name"] == "Mud Patch")
    assert row["deck"] == "A" and row["number"] == 11
    assert row["cost"] is None and row["prerequisites"] is None


# ---------------------------------------------------------------------------
# Slot count = unplanted BOARD field tiles only
# ---------------------------------------------------------------------------

def test_slots_count_unplanted_board_tiles_only():
    """Only bare board FIELD tiles count: grain / veg / stone fields are planted,
    and card-fields are not field TILES (ruling 32)."""
    state = setup(0)
    # Two bare fields, one grain field, one veg field, one stone field.
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD),               # unplanted
        (0, 1): Cell(cell_type=CellType.FIELD),               # unplanted
        (0, 2): Cell(cell_type=CellType.FIELD, grain=3),      # planted
        (0, 3): Cell(cell_type=CellType.FIELD, veg=2),        # planted
        (0, 4): Cell(cell_type=CellType.FIELD, stone=1),      # stone -> planted
    })
    p = state.players[0]
    assert _unplanted_field_tiles(p) == 2
    assert _slots(state, p) == Animals(boar=2)

    # A card-field never counts as a field TILE — the count is grid-only, so it
    # is unchanged by anything off the grid (nothing added here beyond the grid).
    assert typed_slot_counts(state, _own(state).players[0]) == Animals(boar=2)


def test_slots_hold_boar_only():
    """The card grants boar slots only — never sheep or cattle."""
    state = _own(with_fields(setup(0), 0, [(0, 0), (0, 1)]))
    counts = typed_slot_counts(state, state.players[0])
    assert counts == Animals(boar=2)
    assert counts.sheep == 0 and counts.cattle == 0

    # And the boar slots don't help a non-boar animal: with 2 field slots + the
    # 1 house pet, 2 boar + 1 sheep fits (boar on the card, sheep as pet) but
    # 2 boar + 2 sheep does not (only one flexible pet slot for the sheep).
    p = state.players[0]
    assert accommodates(state, p, 1, 2, 0)
    assert not accommodates(state, p, 2, 2, 0)


# ---------------------------------------------------------------------------
# Tableau-only: no slots while merely held in hand
# ---------------------------------------------------------------------------

def test_tableau_only():
    state = with_fields(setup(0), 0, [(0, 0), (0, 1)])
    # Not owned (setup deals nothing into minor_improvements): no boar slots.
    assert typed_slot_counts(state, state.players[0]) == Animals()
    # Merely in hand is still not owned.
    p = state.players[0]
    in_hand = dataclasses.replace(
        state,
        players=tuple(
            fast_replace(p, hand_minors=p.hand_minors | {CARD_ID}) if i == 0
            else state.players[i] for i in range(2)))
    assert typed_slot_counts(in_hand, in_hand.players[0]) == Animals()
    # In the tableau: 2 boar slots.
    assert typed_slot_counts(state, _own(state).players[0]) == Animals(boar=2)


# ---------------------------------------------------------------------------
# Capacity rises when a new field is plowed
# ---------------------------------------------------------------------------

def test_capacity_rises_when_field_plowed():
    state = _own(with_fields(setup(0), 0, [(0, 0), (0, 1)]))
    p = state.players[0]
    # 2 field slots + 1 house pet: 2 boar fit; a 3rd boar does not.
    assert typed_slot_counts(state, p) == Animals(boar=2)
    assert accommodates(state, p, 0, 3, 0)     # 2 on card, 1 house pet
    assert not accommodates(state, p, 0, 4, 0)

    # Plow a 3rd field -> 3 boar slots -> a 4th boar now fits.
    state = with_fields(state, 0, [(0, 0), (0, 1), (0, 2)])
    p2 = state.players[0]
    assert typed_slot_counts(state, p2) == Animals(boar=3)
    assert accommodates(state, p2, 0, 4, 0)


# ---------------------------------------------------------------------------
# On-play: the boar arrives through the accommodation barrier
# ---------------------------------------------------------------------------

def test_on_play_boar_arrives_over_capacity_surfaces_barrier():
    """Owner at capacity (no fields, house pet full with 1 boar); playing Mud
    Patch grants a 2nd boar that cannot fit, so the barrier surfaces the
    keep-or-cook choice."""
    from agricola.cards.mud_patch import _on_play

    state = _own(setup(0))
    state = dataclasses.replace(state, current_player=0, starting_player=0)
    state = with_animals(state, 0, boar=1)      # the house pet slot is full

    state = _on_play(state, 0)
    assert state.players[0].animals.boar == 2   # the boar landed (transient over-cap)

    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0

    # The offered options keep at most 1 boar (the excess is cooked) — never 2.
    keeps = [a.boar for a in legal_actions(state)
             if isinstance(a, CommitAccommodate)]
    assert keeps and max(keeps) <= 1


# ---------------------------------------------------------------------------
# Eviction end to end: sowing the last unplanted field forces accommodation
# ---------------------------------------------------------------------------

def _sow_last_field(state):
    """Drive a real Grain Utilization grain sow of P0's single empty field and
    return the resulting state (with the after_sow auto having fired)."""
    state = with_space(state, "grain_utilization", revealed=True, workers=(0, 0))
    state = step(state, PlaceWorker(space="grain_utilization"))
    state = step(state, ChooseSubAction(name="sow"))
    sow = next(a for a in legal_actions(state)
               if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    return step(state, sow)


def _eviction_setup(*, own):
    """A card-mode WORK state: P0 has one empty field (1 boar slot) + the house
    pet -> holds 2 boar; grain=1 to sow; optionally owns Mud Patch."""
    state, _env = setup_env(seed=0, card_pool=_POOL)
    state = dataclasses.replace(state, current_player=0, starting_player=0)
    if own:
        state = _own(state)
    state = with_fields(state, 0, [(0, 0)])
    state = with_animals(state, 0, boar=2)
    state = with_resources(state, 0, grain=1)
    return state


def test_eviction_via_sow_forces_accommodation():
    """Owner holds 2 boar (1 on the field slot, 1 house pet). Sowing that last
    empty field drops the field slot to 0, so the held boar no longer fits and
    the barrier surfaces the keep-or-cook choice."""
    state = _eviction_setup(own=True)
    # Pre-sow: the 2 boar fit (card slot + house pet), so no barrier is armed.
    assert accommodates(state, state.players[0], 0, 2, 0)

    state = _sow_last_field(state)
    # The sow really ran (the field now holds grain).
    assert state.players[0].farmyard.grid[0][0].grain == 3
    # The boar is still on the farm, now over capacity -> accommodation surfaces.
    assert state.players[0].animals.boar == 2
    top = state.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0

    # Resolving it keeps at most the 1 boar the house pet can hold.
    keep1 = next(a for a in legal_actions(state)
                 if isinstance(a, CommitAccommodate) and a.boar == 1)
    state = step(state, keep1)
    assert state.players[0].animals.boar == 1


def test_no_eviction_when_card_not_owned():
    """Control: with the card NOT in the tableau, the after_sow auto never fires,
    so an ordinary sow does not push an accommodation frame."""
    state = _eviction_setup(own=False)
    state = _sow_last_field(state)
    assert state.players[0].farmyard.grid[0][0].grain == 3   # the sow ran
    assert not any(isinstance(f, PendingAccommodate) for f in state.pending_stack)
