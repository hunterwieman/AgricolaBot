"""Tests for Silage (minor improvement, A84; Artifex Expansion).

Card text (verbatim): "In each returning home phase after which there is no
harvest, you can pay exactly 1 grain—even from a field-to breed exactly one
type of animal." Cost: none. Prerequisite: "2 Fields". No printed VPs.

The effect rides the round-end ladder's ``returning_home`` window (ruling 49,
2026-07-12) as an optional play-variant trigger: one FireTrigger per (payable
grain source) x (breedable type), sources encoded "supply" / "grain<h>" (the
Craft Brewery grid-height idiom) / "cf_<card_id>" (per grain-holding
card-field, rulings 45/46). The card-field payment routes through
``card_fields.remove_card_crop`` — the ruling-44 chokepoint — so emptying a
Crop Rotation Field's last grain offers its veg re-sow at this instant. The
breed is NOT a breeding phase (no breeding_outcome, no breed frame — Fodder
Planter stays silent) and NOT a harvest (no occasion). These tests drive the
REAL round-end walk (`_advance_until_decision` from a drained WORK state).
"""
from __future__ import annotations

import dataclasses

import agricola.cards.silage                 # noqa: F401  (register the card)
import agricola.cards.crop_rotation_field    # noqa: F401  (card-field + reactor)
import agricola.cards.fodder_planter         # noqa: F401  (breeding-reactor witness)

from agricola.actions import CommitCardChoice, FireTrigger, Proceed
from agricola.cards.capacity_mods import register_single_parent_sheep
from agricola.cards.card_fields import card_field_stacks, stacks_to_store
from agricola.cards.silage import CARD_ID, _variants
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice, PendingHarvestWindow, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_animals, with_fields, with_grid, with_minors, with_resources


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _drained_work_state(seed=0, round_number=1):
    """A WORK state with every person placed — the round-end ladder runs next."""
    state = setup(seed)
    state = dataclasses.replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _with_stables(state, idx, cells):
    """Standalone stables = 1 flexible animal slot each (+ the house pet's 1)."""
    return with_grid(state, idx,
                     {rc: Cell(cell_type=CellType.STABLE) for rc in cells})


def _with_grain_fields(state, idx, fields):
    """Grid FIELD cells: {(r, c): grain held}."""
    return with_grid(state, idx,
                     {rc: Cell(cell_type=CellType.FIELD, grain=g)
                      for rc, g in fields.items()})


def _own_card_field(state, idx, cid, stacks):
    p = state.players[idx]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {cid},
        card_state=stacks_to_store(p.card_state, cid, stacks),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _silage_state(*, grain=0, fields=None, sheep=0, boar=0, cattle=0,
                  stables=((0, 3), (0, 4)), round_number=1, owned=True):
    """A drained WORK state; P0 (optionally) owns Silage with the given
    supply grain, grid grain fields, herd, and standalone stables (2 by
    default: with the house pet, capacity for 3 of one type)."""
    state = _drained_work_state(round_number=round_number)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, grain=grain)
    state = with_animals(state, 0, sheep=sheep, boar=boar, cattle=cattle)
    if stables:
        state = _with_stables(state, 0, stables)
    if fields:
        state = _with_grain_fields(state, 0, fields)
    return state


def _walk_to_window(state):
    """Advance to P0's returning_home window frame (the ladder pauses there)."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no returning_home window surfaced (top={top!r}, phase={state.phase})")
    assert top.window_id == "returning_home" and top.player_idx == 0
    return state


def _silage_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _no_returning_home_pause(state):
    """Advance and assert the walk never pauses at a returning_home window
    (the trigger was ineligible / unowned, so no frame was ever pushed)."""
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == "returning_home"
        for f in state.pending_stack)
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                    # cost null -> free
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is not None                # "2 Fields"
    assert spec.vps == 0                          # none printed
    entry = CARDS[CARD_ID]
    assert entry.event == "returning_home"        # ruling 49's rung
    assert entry.mandatory is False               # "you can"
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


def test_prereq_two_fields_ruling45():
    """"2 Fields": grid FIELD cells + owned card-fields, planted or not."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)                       # 0 fields
    one = with_fields(state, 0, [(0, 3)])
    assert not prereq_met(spec, one, 0)                         # 1 field
    two = with_fields(state, 0, [(0, 3), (0, 4)])
    assert prereq_met(spec, two, 0)                             # 2 grid fields
    # 1 grid field + 1 card-field (unplanted Crop Rotation Field) = 2 fields.
    mixed = with_minors(one, 0, frozenset({"crop_rotation_field"}))
    assert prereq_met(spec, mixed, 0)


# --- The variants encoding (unit) --------------------------------------------

def test_variants_source_major_ordering():
    """Sources: supply, grid heights ascending, card-fields by id; types in
    sheep/boar/cattle order. Same-height fields collapse into one tag."""
    state = _silage_state(grain=1, fields={(1, 1): 1, (1, 2): 3, (1, 3): 3},
                          sheep=2, boar=2,
                          stables=((0, 1), (0, 2), (0, 3), (0, 4)))
    state = _own_card_field(state, 0, "crop_rotation_field", [(2, 0, 0, 0)])
    assert _variants(state, 0) == [
        "supply:sheep", "supply:boar",
        "grain1:sheep", "grain1:boar",
        "grain3:sheep", "grain3:boar",
        "cf_crop_rotation_field:sheep", "cf_crop_rotation_field:boar",
    ]


def test_variants_empty_without_grain_or_pair():
    # A pair but no grain anywhere -> no variants.
    state = _silage_state(grain=0, sheep=2)
    assert _variants(state, 0) == []
    # Grain but no breeding pair -> no variants.
    state = _silage_state(grain=1, sheep=0)
    assert _variants(state, 0) == []
    # An empty field and a veg-only card-field are not grain sources.
    state = _silage_state(grain=0, fields={(1, 1): 0}, sheep=2)
    state = _own_card_field(state, 0, "crop_rotation_field", [(0, 2, 0, 0)])
    assert _variants(state, 0) == []


# --- Real-walk fires, one per source kind -------------------------------------

def test_supply_grain_fire():
    """The walk pauses at the returning_home window; firing "supply:sheep"
    debits the supply grain and the newborn arrives. Once per round: the only
    action left is Proceed, and declining it onward reaches PREPARATION."""
    state = _walk_to_window(_silage_state(grain=1, sheep=2))
    assert _silage_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="supply:sheep")]

    state = step(state, FireTrigger(card_id=CARD_ID, variant="supply:sheep"))
    p = state.players[0]
    assert p.animals.sheep == 3                   # the newborn arrived
    assert p.resources.grain == 0                 # 1 grain paid from supply
    # Once per round: the frame's triggers_resolved swallows a re-offer.
    assert legal_actions(state) == [Proceed()]

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # round 1: no harvest
    assert state.round_end_cursor is None


def test_grid_field_grain_fire():
    """"grain2:boar" decrements the first row-major 2-grain field (the height
    group's canonical field) — a removal, not a harvest — and adds the boar."""
    state = _walk_to_window(_silage_state(
        grain=0, fields={(2, 3): 2, (1, 2): 2, (1, 1): 1}, boar=2))
    assert _silage_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="grain1:boar"),
        FireTrigger(card_id=CARD_ID, variant="grain2:boar"),
    ]
    state = step(state, FireTrigger(card_id=CARD_ID, variant="grain2:boar"))
    p = state.players[0]
    assert p.animals.boar == 3
    assert p.farmyard.grid[1][2].grain == 1       # (1,2) scans before (2,3)
    assert p.farmyard.grid[2][3].grain == 2       # the other 2-grain field
    assert p.farmyard.grid[1][1].grain == 1       # the h1 field untouched
    assert p.resources.grain == 0                 # supply untouched


def test_card_field_grain_fire_via_chokepoint():
    """"cf_crop_rotation_field:cattle" removes 1 card grain through
    remove_card_crop; the card kept grain, so no removal reaction fires and
    play stays at the window."""
    state = _silage_state(grain=0, cattle=2)
    state = _own_card_field(state, 0, "crop_rotation_field", [(2, 0, 0, 0)])
    state = _walk_to_window(state)
    assert _silage_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="cf_crop_rotation_field:cattle")]
    state = step(state, FireTrigger(
        card_id=CARD_ID, variant="cf_crop_rotation_field:cattle"))
    p = state.players[0]
    assert p.animals.cattle == 3
    assert card_field_stacks(p, "crop_rotation_field") == ((1, 0, 0, 0),)
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)


def test_emptying_crop_rotation_field_offers_resow_here():
    """Ruling 44: paying with a Crop Rotation Field's LAST grain is a
    non-take removal — its sow-or-decline choice surfaces at THIS instant
    (a PendingCardChoice on top of the window frame); sowing swaps in 2 veg."""
    state = _silage_state(grain=0, sheep=2)
    state = _own_card_field(state, 0, "crop_rotation_field", [(1, 0, 0, 0)])
    state = with_resources(state, 0, veg=1)
    state = _walk_to_window(state)

    state = step(state, FireTrigger(
        card_id=CARD_ID, variant="cf_crop_rotation_field:sheep"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.initiated_by_id == "card:crop_rotation_field"
    assert top.options == ("sow_veg", "decline")
    assert state.players[0].animals.sheep == 3    # the breed already applied

    state = step(state, CommitCardChoice(0))      # sow_veg
    p = state.players[0]
    assert card_field_stacks(p, "crop_rotation_field") == ((0, 2, 0, 0),)
    assert p.resources.veg == 0                   # the sow cost the supply veg
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION


# --- Breedability gates --------------------------------------------------------

def test_pair_threshold():
    """1 sheep is below the pair threshold — nothing to offer, so the window
    never hosts; 2 sheep are offered (capacity present in both cases)."""
    state = _silage_state(grain=1, sheep=1)
    assert _variants(state, 0) == []
    out = _no_returning_home_pause(state)
    assert out.players[0].animals.sheep == 1
    state = _silage_state(grain=1, sheep=2)
    assert _variants(state, 0) == ["supply:sheep"]


def test_single_parent_sheep_does_not_reach_silage():
    """User ruling 52 (2026-07-12): Dolly's Mother's printed scope is the
    HARVEST breeding phase — its single-parent seam does NOT lower Silage's
    mid-round threshold. A single-parent card + 1 sheep: still no offer."""
    register_single_parent_sheep("_test_silage_single_parent")
    state = _silage_state(grain=1, sheep=1)
    p = state.players[0]
    state = _edit_player(
        state, 0, occupations=p.occupations | {"_test_silage_single_parent"})
    assert _variants(state, 0) == []


def test_accommodation_gating():
    """A farm with no room for the newborn (2 sheep, house pet only) never
    offers sheep — the breeding rule's "you must be able to accommodate the
    newborn" is inherent — so with no other type the trigger is ineligible."""
    state = _silage_state(grain=1, sheep=2, stables=())
    assert _variants(state, 0) == []
    out = _no_returning_home_pause(state)
    assert out.players[0].animals.sheep == 2
    assert out.players[0].resources.grain == 1
    # Positive control: with room (2 stables + the pet = 3 slots), offered.
    state = _silage_state(grain=1, sheep=2)
    assert _variants(state, 0) == ["supply:sheep"]


# --- "After which there is no harvest" -----------------------------------------

def test_suppressed_on_harvest_rounds():
    """Round 4's returning home phase is followed by the harvest: the trigger
    is ineligible, the window never hosts, and the walk runs into the harvest
    with the herd and grain untouched."""
    state = _silage_state(grain=1, sheep=2, round_number=4)
    assert _variants(state, 0) != []              # sources/types ARE present
    out = _no_returning_home_pause(state)
    assert out.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                         Phase.HARVEST_BREED)
    assert out.players[0].animals.sheep == 2
    assert out.players[0].resources.grain == 1


# --- NOT a breeding phase -------------------------------------------------------

def test_breeding_reactors_silent():
    """Fodder Planter ("in the breeding phase of each harvest, for each
    newborn... sow") is structurally silent: Silage's breed emits no
    breeding_outcome event and pushes no breed frame, so no latch is written
    and no sow grant appears."""
    state = _silage_state(grain=1, sheep=2, fields={(1, 1): 0})
    p = state.players[0]
    state = _edit_player(state, 0, occupations=p.occupations | {"fodder_planter"})
    state = with_resources(state, 0, grain=1)     # sowable grain, empty field
    state = _walk_to_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="supply:sheep"))
    assert state.players[0].animals.sheep == 3
    assert state.players[0].card_state.get("fodder_planter") is None  # no latch
    assert not any(isinstance(f, PendingSow) for f in state.pending_stack)
    assert legal_actions(state) == [Proceed()]    # no fodder_planter fire


# --- Declining / unowned ---------------------------------------------------------

def test_decline_leaves_everything_unchanged():
    state = _walk_to_window(_silage_state(grain=1, sheep=2))
    assert _silage_fires(state) != []             # it was on offer
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    p = state.players[0]
    assert p.animals.sheep == 2
    assert p.resources.grain == 1
    assert state.phase == Phase.PREPARATION


def test_unowned_never_hosts():
    state = _silage_state(grain=1, sheep=2, owned=False)
    out = _no_returning_home_pause(state)
    assert out.phase == Phase.PREPARATION
    assert out.round_end_cursor is None
    assert out.players[0].animals.sheep == 2


# --- Labels ----------------------------------------------------------------------

def test_action_labels():
    from agricola.cards.display import variant_label

    assert variant_label(CARD_ID, "supply:sheep") == "1 grain (supply) → breed sheep"
    assert (variant_label(CARD_ID, "grain2:cattle")
            == "1 grain (2-grain field) → breed cattle")
    assert (variant_label(CARD_ID, "cf_crop_rotation_field:boar")
            == "1 grain (Crop Rotation Field) → breed boar")
