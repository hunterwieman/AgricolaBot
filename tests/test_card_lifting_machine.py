"""Tests for Lifting Machine (minor improvement, A70; Artifex Expansion).

Card text (verbatim): "At the end of each round that does not end with a
harvest, you can move 1 vegetable from one of your fields to your supply.
(This is not considered a field phase.)"
Cost 1 Wood. Prerequisite: 3 Fields. No printed VPs.

The move is an optional trigger on the round-end ladder's LAST rung —
``end_of_round`` (ruling 49, 2026-07-12) — variant-expanded over the
veg-bearing fields: grid fields grouped by veg count ("veg<X>", the Craft
Brewery which-field idiom, ruling 2026-07-06), card-fields as per-card
"cf_<id>" tags (rulings 45/46, 2026-07-12). "That does not end with a
harvest" is the card's own eligibility clause (``round_number not in
HARVEST_ROUNDS``); once-per-round rides the window host's
``triggers_resolved``; declining is Proceed without firing.

The card-field path routes through ``card_fields.remove_card_crop`` — the
NON-take-removal chokepoint (ruling 44, 2026-07-12) — so emptying a Crop
Rotation Field's last vegetable pushes its sow-or-decline choice AT this
instant (the re-sow offers GRAIN: "respectively"). NOT a field phase / NOT a
harvest (printed + ruling 12's lexicon, 2026-07-03): no harvesting occasion
is emitted, so Melon Patch's harvest-verb reaction stays silent when this
card empties it.

These tests drive the REAL round-end walk: a drained WORK state (all people
placed) advanced through ``_advance_until_decision`` pauses at the
``end_of_round`` PendingHarvestWindow host.
"""
from __future__ import annotations

import agricola.cards.lifting_machine       # noqa: F401  (register the card)
import agricola.cards.beanfield             # noqa: F401  (a plain card-field)
import agricola.cards.crop_rotation_field   # noqa: F401  (the chokepoint reactor)
import agricola.cards.melon_patch           # noqa: F401  (the harvest-verb witness)

from agricola.actions import CommitCardChoice, FireTrigger, Proceed
from agricola.cards.card_fields import (
    card_field_stacks,
    card_holds,
    stacks_to_store,
)
from agricola.cards.lifting_machine import CARD_ID, _eligible, _variants
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import HARVEST_ROUNDS, CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingCardChoice,
    PendingHarvestOccasion,
    PendingHarvestWindow,
    PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import add_resources


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, cid):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {cid})


def _own_card_field(state, idx, cid, stacks):
    """Give player `idx` card-field `cid` holding `stacks`."""
    p = state.players[idx]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {cid},
        card_state=stacks_to_store(p.card_state, cid, stacks),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_fields(state, idx, veg_fields, grain_fields=None):
    """Set cells to FIELD: `veg_fields` maps (r, c) -> veg held;
    `grain_fields` maps (r, c) -> grain held. Cells not named are untouched."""
    grain_fields = grain_fields or {}
    p = state.players[idx]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD, veg=veg_fields[(r, c)])
            if (r, c) in veg_fields else
            fast_replace(cell, cell_type=CellType.FIELD, grain=grain_fields[(r, c)])
            if (r, c) in grain_fields else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


def _field_veg(state, idx, r, c):
    return state.players[idx].farmyard.grid[r][c].veg


def _drained_work_state(seed=0, round_number=1):
    """A WORK state with every person placed — advancing runs the round-end
    ladder (test_round_end_ladder's idiom)."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _lift_actions(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _at_end_of_round_window(state, idx=0):
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestWindow)
            and top.window_id == "end_of_round" and top.player_idx == idx)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)           # "1 Wood"
    assert spec.min_occupations == 0
    assert spec.prereq is not None                            # "3 Fields"
    assert spec.vps == 0                                      # none printed
    entry = CARDS[CARD_ID]
    assert entry.event == "end_of_round"                      # ruling 49's rung
    assert not entry.mandatory                                # "you can"
    assert CARD_ID in PLAY_VARIANT_TRIGGERS                   # which-field choice


def test_prereq_three_fields_incl_card_fields():
    """The HAVE-check: grid FIELD cells + owned card-fields (ruling 45,
    2026-07-12 — a "you need N fields" requirement counts card-fields, each
    exactly once), planted or not."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)                     # 0 fields
    three = _set_fields(state, 0, {}, {(0, 1): 0, (0, 2): 0, (0, 3): 0})
    assert prereq_met(spec, three, 0)                         # 3 grid fields
    two = _set_fields(state, 0, {}, {(0, 1): 0, (0, 2): 0})
    assert not prereq_met(spec, two, 0)                       # 2 grid fields
    # Ruling 45: an owned (even unplanted) card-field is the third field.
    assert prereq_met(spec, _own_minor(two, 0, "beanfield"), 0)


# --- The variants encoding (unit) --------------------------------------------

def test_variants_grouped_by_veg_count_then_cards():
    """One "veg<X>" per veg-count group (ascending; same-count fields
    collapse), then "cf_<id>" per veg-holding card-field, by id."""
    state = setup(seed=0)
    state = _set_fields(state, 0, {(0, 1): 2, (0, 2): 1, (1, 0): 1})
    assert _variants(state, 0) == ["veg1", "veg2"]
    state = _own_card_field(state, 0, "beanfield", [(0, 2, 0, 0)])
    assert _variants(state, 0) == ["veg1", "veg2", "cf_beanfield"]


def test_variants_empty_without_veg():
    """No fields, empty fields, grain-only fields, and a veg-less card-field
    all yield no variants — the move is withheld."""
    state = setup(seed=0)
    assert _variants(state, 0) == []
    state = _set_fields(state, 0, {(0, 1): 0}, {(0, 2): 2})
    state = _own_minor(state, 0, "beanfield")                 # unplanted card
    assert _variants(state, 0) == []


def test_eligibility_suppressed_on_harvest_rounds():
    """"That does not end with a harvest" — the bearer's own clause: on every
    HARVEST_ROUND the trigger is ineligible even with veg on a field."""
    for rn in sorted(HARVEST_ROUNDS):
        state = fast_replace(setup(seed=0), round_number=rn)
        state = _set_fields(state, 0, {(0, 1): 2})
        assert not _eligible(state, 0, frozenset())
    state = fast_replace(setup(seed=0), round_number=5)
    state = _set_fields(state, 0, {(0, 1): 2})
    assert _eligible(state, 0, frozenset())


# --- The grid fire, through the real round-end walk ---------------------------

def test_grid_fire_moves_veg_and_is_once_per_round():
    """The walk pauses at the end_of_round window; firing "veg2" moves 1 veg
    from the (first row-major) 2-veg field to supply, emits NO harvesting
    occasion, and cannot re-fire this round (only Proceed remains)."""
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _set_fields(state, 0, {(0, 1): 2, (0, 2): 1})
    state = _advance_until_decision(state)
    assert _at_end_of_round_window(state)
    assert _lift_actions(state) == [
        FireTrigger(card_id=CARD_ID, variant="veg1"),
        FireTrigger(card_id=CARD_ID, variant="veg2"),
    ]
    assert Proceed() in legal_actions(state)

    state = step(state, FireTrigger(card_id=CARD_ID, variant="veg2"))
    p = state.players[0]
    assert _field_veg(state, 0, 0, 1) == 1        # the 2-veg field, decremented
    assert _field_veg(state, 0, 0, 2) == 1        # the other field untouched
    assert p.resources.veg == 1                   # ... into the supply
    # NOT a field phase (printed): no harvesting occasion was emitted.
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)
    # Once per round: the host's triggers_resolved blocks a re-fire.
    assert _at_end_of_round_window(state)
    assert legal_actions(state) == [Proceed()]

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # round 1: no harvest
    assert state.round_end_cursor is None


def test_grid_canonical_field_is_first_in_row_major_order():
    """Two same-count fields collapse to one variant; the move lands on the
    row-major-first one (the group's canonical field)."""
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _set_fields(state, 0, {(1, 2): 1, (0, 3): 1})
    state = _advance_until_decision(state)
    assert _lift_actions(state) == [FireTrigger(card_id=CARD_ID, variant="veg1")]
    state = step(state, FireTrigger(card_id=CARD_ID, variant="veg1"))
    assert _field_veg(state, 0, 0, 3) == 0        # (0,3) scans before (1,2)
    assert _field_veg(state, 0, 1, 2) == 1
    assert state.players[0].resources.veg == 1


# --- The card-field fire (rulings 45/46) --------------------------------------

def test_card_field_fire_beanfield():
    """A veg-holding card-field IS "one of your fields": firing
    "cf_beanfield" moves 1 veg off the card into supply — no frame pushed
    (Beanfield has no removal reaction)."""
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _own_card_field(state, 0, "beanfield", [(0, 2, 0, 0)])
    state = _advance_until_decision(state)
    assert _at_end_of_round_window(state)
    assert _lift_actions(state) == [
        FireTrigger(card_id=CARD_ID, variant="cf_beanfield")]

    state = step(state, FireTrigger(card_id=CARD_ID, variant="cf_beanfield"))
    p = state.players[0]
    assert card_field_stacks(p, "beanfield") == ((0, 1, 0, 0),)
    assert p.resources.veg == 1
    assert _at_end_of_round_window(state)         # no reaction frame pushed


# --- The chokepoint (ruling 44): emptying a Crop Rotation Field ---------------

def test_emptying_crop_rotation_field_offers_resow_here():
    """Ruling 44: Lifting Machine removing Crop Rotation Field's LAST veg is
    a non-take removal — the sow-or-decline choice surfaces at THIS instant
    (a PendingCardChoice on top of the window host); the re-sow offers GRAIN
    ("respectively"), and sowing swaps in 3 grain."""
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _own_card_field(state, 0, "crop_rotation_field", [(0, 1, 0, 0)])
    state = add_resources(state, 0, grain=1)      # the sow costs the supply grain
    state = _advance_until_decision(state)

    state = step(state, FireTrigger(
        card_id=CARD_ID, variant="cf_crop_rotation_field"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.initiated_by_id == "card:crop_rotation_field"
    assert top.options == ("sow_grain", "decline")
    # The move itself already applied (supply credited before the push).
    assert state.players[0].resources.veg == 1
    assert card_holds(state.players[0], "crop_rotation_field", "veg") == 0
    # Still no harvesting occasion — a removal, not a harvest.
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)

    state = step(state, CommitCardChoice(0))      # sow_grain
    p = state.players[0]
    assert card_field_stacks(p, "crop_rotation_field") == ((3, 0, 0, 0),)
    assert p.resources.grain == 0                 # the sow cost the supply grain
    assert _at_end_of_round_window(state)         # popped back to the host

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION


def test_emptying_crop_rotation_field_decline():
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _own_card_field(state, 0, "crop_rotation_field", [(0, 1, 0, 0)])
    state = add_resources(state, 0, grain=1)
    state = _advance_until_decision(state)
    state = step(state, FireTrigger(
        card_id=CARD_ID, variant="cf_crop_rotation_field"))
    state = step(state, CommitCardChoice(1))      # decline
    p = state.players[0]
    assert "crop_rotation_field" not in dict(p.card_state.items)  # empty card
    assert p.resources.grain == 1                 # unspent
    assert p.resources.veg == 1                   # the moved veg
    assert _at_end_of_round_window(state)


# --- NOT a harvest: the harvest-verb witness -----------------------------------

def test_melon_patch_harvest_reaction_does_not_fire():
    """Melon Patch reacts to "each time you HARVEST the last vegetable from
    this card" — the harvest verb (occasion seam). Lifting Machine emits no
    occasion (printed: not a field phase; ruling 12's lexicon), so emptying
    Melon Patch this way grants NO plow: no occasion host, no PendingPlow, no
    choice frame — play stays at the window host."""
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _own_card_field(state, 0, "melon_patch", [(0, 1, 0, 0)])
    state = _advance_until_decision(state)

    state = step(state, FireTrigger(card_id=CARD_ID, variant="cf_melon_patch"))
    p = state.players[0]
    assert card_holds(p, "melon_patch", "veg") == 0   # emptied...
    assert p.resources.veg == 1                       # ...into the supply
    assert not any(
        isinstance(f, (PendingHarvestOccasion, PendingPlow, PendingCardChoice))
        for f in state.pending_stack)
    assert _at_end_of_round_window(state)


# --- Suppression on harvest rounds, through the real walk ----------------------

def test_harvest_round_no_window_offered():
    """On a harvest round the trigger is ineligible, so the round-end ladder
    pushes no window host — the walk runs straight into the harvest."""
    state = _drained_work_state(round_number=4)
    state = _own_minor(state, 0, CARD_ID)
    state = _set_fields(state, 0, {(0, 1): 2})
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                           Phase.HARVEST_BREED)
    assert not any(isinstance(f, PendingHarvestWindow)
                   for f in state.pending_stack)


# --- Declining -----------------------------------------------------------------

def test_decline_leaves_everything_unchanged():
    state = _drained_work_state()
    state = _own_minor(state, 0, CARD_ID)
    state = _set_fields(state, 0, {(0, 1): 2})
    state = _advance_until_decision(state)
    assert _lift_actions(state) != []             # it was on offer
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert _field_veg(state, 0, 0, 1) == 2        # untouched
    assert state.players[0].resources.veg == 0
    assert state.phase == Phase.PREPARATION


# --- Unowned ---------------------------------------------------------------------

def test_unowned_no_window():
    """Veg fields alone push no frame — the walk sails to PREPARATION."""
    state = _drained_work_state()
    state = _set_fields(state, 0, {(0, 1): 2})
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert not any(isinstance(f, PendingHarvestWindow)
                   for f in state.pending_stack)
    assert state.players[0].resources.veg == 0


def test_opponent_ownership_not_offered_to_p0():
    """P1 owning the card (with no veg field) yields no frame at all; P0's
    veg field is not P1's to lift from."""
    state = _drained_work_state()
    state = _own_minor(state, 1, CARD_ID)
    state = _set_fields(state, 0, {(0, 1): 2})
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert not any(isinstance(f, PendingHarvestWindow)
                   for f in state.pending_stack)


# --- The labeler ------------------------------------------------------------------

def test_action_labels():
    """The web-UI labeler (display.register_action_labeler): where the
    vegetable comes from — a count group or a named card-field."""
    from agricola.cards.display import variant_label

    assert variant_label(CARD_ID, "veg1") == "1 veg from a 1-veg field"
    assert variant_label(CARD_ID, "veg2") == "1 veg from a 2-veg field"
    assert variant_label(CARD_ID, "cf_beanfield") == "1 veg from Beanfield"
    assert (variant_label(CARD_ID, "cf_crop_rotation_field")
            == "1 veg from Crop Rotation Field")
