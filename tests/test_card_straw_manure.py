import agricola.cards.straw_manure  # noqa: F401
# Tests for Straw Manure (minor improvement, D70; Dulcinaria Expansion).
#
# Card text (verbatim): "Before the field phase of each harvest, you can pay 1
# grain from your supply to add 1 vegetable to each of up to 2 vegetable fields."
# Cost: none. VPs: none printed. Prerequisite: "2 Fields". Not passing.
#
# TIMING: harvest window #3 `before_field_phase` — an optional play-variant
# trigger surfaced on the per-player PendingHarvestWindow host BEFORE that
# player's crop take (window #5), inside the per-player FIELD segment (ruling 3,
# 2026-07-03: each player resolves their whole FIELD segment before the other).
# Variants: each non-empty subset (size 1 or 2) of the player's vegetable
# fields, encoded "r-c" joined by "|". Flat 1-grain cost either way. Once per
# harvest (the frame's triggers_resolved); Proceed declines (no grain spent).
#
# Drivers mirror tests/test_card_home_brewer.py / tests/test_harvest_windows.py.

import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.straw_manure import CARD_ID, WINDOW_ID
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup
from agricola.state import Cell, GameState

from tests.factories import with_fields, with_grid, with_phase, with_resources


# --- Helpers ----------------------------------------------------------------

def _own_minor(state, player_idx, card_id):
    p = state.players[player_idx]
    p = dataclasses.replace(p, minor_improvements=p.minor_improvements | {card_id})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, grain=0, veg_cells=(), owned=True, owner=0) -> GameState:
    """A HARVEST_FIELD-phase state with `owner` (optionally) owning Straw Manure,
    holding `grain`, and each cell in `veg_cells` a vegetable field with 2 veg.
    Both players are given plenty of food so feeding is painless."""
    state = setup(seed=0)
    state = fast_replace(state, starting_player=owner)
    if owned:
        state = _own_minor(state, owner, CARD_ID)
    state = with_resources(state, owner, food=10, grain=grain)
    state = with_resources(state, 1 - owner, food=10)
    overrides = {(r, c): Cell(cell_type=CellType.FIELD, veg=2) for (r, c) in veg_cells}
    if overrides:
        state = with_grid(state, owner, overrides)
    return with_phase(state, Phase.HARVEST_FIELD)


def _walk_to_window(state, *, window_id=WINDOW_ID, owner=0):
    """Drive the harvest walk until the top frame is a PendingHarvestWindow for
    `window_id`/`owner`, or the harvest ends (returning that post-harvest state)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == window_id and top.player_idx == owner):
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _sm_variants(state):
    """Sorted Straw Manure FireTrigger variants currently legal."""
    return sorted(
        a.variant for a in legal_actions(state)
        if isinstance(a, FireTrigger) and a.card_id == CARD_ID
    )


def _cell(state, idx, r, c):
    return state.players[idx].farmyard.grid[r][c]


# --- Registration / spec ------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                # card JSON cost=null -> free
    assert spec.vps == 0                      # vps=null -> 0
    assert spec.passing_left is False
    assert spec.prereq is not None            # "2 Fields"
    # A play-variant trigger on window #3.
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert WINDOW_ID == "before_field_phase"
    assert CARD_ID in HARVEST_WINDOW_CARDS[WINDOW_ID]


def test_prereq_two_fields():
    s = setup(0)
    # Bare setup: 0 fields -> fails.
    assert not prereq_met(MINORS[CARD_ID], s, 0)
    # 1 field -> still fails.
    assert not prereq_met(MINORS[CARD_ID], with_fields(s, 0, [(0, 0)]), 0)
    # 2 fields (unsown — any field tiles count) -> satisfied.
    assert prereq_met(MINORS[CARD_ID], with_fields(s, 0, [(0, 0), (0, 1)]), 0)


# --- Variant enumeration ------------------------------------------------------

def test_variants_single_veg_field():
    state = _walk_to_window(_harvest_state(grain=1, veg_cells=((0, 1),)))
    assert _sm_variants(state) == ["0-1"]


def test_variants_two_veg_fields_singles_and_pair():
    state = _walk_to_window(_harvest_state(grain=1, veg_cells=((0, 1), (1, 2))))
    assert _sm_variants(state) == ["0-1", "0-1|1-2", "1-2"]


def test_variants_three_veg_fields_capped_at_pairs():
    """With 3 veg fields: 3 singles + 3 pairs, never a triple ("up to 2")."""
    state = _walk_to_window(
        _harvest_state(grain=1, veg_cells=((0, 1), (1, 2), (2, 3))))
    variants = _sm_variants(state)
    assert len(variants) == 6
    assert all(len(v.split("|")) <= 2 for v in variants)


def test_grain_field_is_not_a_target():
    """A grain field is not a vegetable field — never a legal target."""
    state = _harvest_state(grain=1, veg_cells=((0, 1),))
    state = with_grid(state, 0, {(1, 1): Cell(cell_type=CellType.FIELD, grain=3)})
    state = _walk_to_window(state)
    assert _sm_variants(state) == ["0-1"]     # the grain field (1,1) never appears


# --- Real-flow effect ---------------------------------------------------------

def test_fire_single_target_pays_one_grain_adds_one_veg():
    state = _walk_to_window(_harvest_state(grain=2, veg_cells=((0, 1), (1, 2))))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="0-1"))
    assert state.players[0].resources.grain == 1        # 2 - 1 paid
    assert _cell(state, 0, 0, 1).veg == 3               # boosted
    assert _cell(state, 0, 1, 2).veg == 2               # untouched


def test_fire_pair_costs_same_flat_grain():
    """Boosting 2 fields still costs exactly 1 grain (flat, not per field)."""
    state = _walk_to_window(_harvest_state(grain=1, veg_cells=((0, 1), (1, 2))))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="0-1|1-2"))
    assert state.players[0].resources.grain == 0        # exactly 1 paid
    assert _cell(state, 0, 0, 1).veg == 3
    assert _cell(state, 0, 1, 2).veg == 3


def test_added_veg_is_on_the_field_for_the_take():
    """Window #3 precedes window #5's crop take: a boosted field goes into the
    take with the extra vegetable on it. A 1-veg field boosted to 2 is NOT
    emptied by the take (2 -> 1), where unboosted it would have been (1 -> 0)."""
    state = _harvest_state(grain=1)
    state = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD, veg=1)})
    state = _walk_to_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="0-1"))
    assert _cell(state, 0, 0, 1).veg == 2               # 1 + boost
    state = step(state, Proceed())                      # close window #3
    # Walk on until the take has run (the FEED phase is past the FIELD band).
    state = _advance_until_decision(state)
    while state.phase == Phase.HARVEST_FIELD:
        state = step(state, legal_actions(state)[0])
    assert state.phase == Phase.HARVEST_FEED
    assert _cell(state, 0, 0, 1).veg == 1               # take removed 1, field lives
    assert state.players[0].resources.veg == 1          # the take's harvest


# --- Eligibility boundaries ---------------------------------------------------

def test_not_offered_without_grain():
    state = _walk_to_window(_harvest_state(grain=0, veg_cells=((0, 1),)))
    assert not (state.pending_stack
                and isinstance(state.pending_stack[-1], PendingHarvestWindow))


def test_not_offered_without_veg_fields():
    """Grain in hand but no vegetable field -> nothing to add to -> no offer."""
    state = _harvest_state(grain=5)
    state = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD, grain=3)})
    state = _walk_to_window(state)
    assert not (state.pending_stack
                and isinstance(state.pending_stack[-1], PendingHarvestWindow))


def test_not_offered_when_unowned():
    state = _walk_to_window(
        _harvest_state(grain=2, veg_cells=((0, 1),), owned=False))
    assert not (state.pending_stack
                and isinstance(state.pending_stack[-1], PendingHarvestWindow))


def test_exactly_one_grain_suffices():
    state = _walk_to_window(_harvest_state(grain=1, veg_cells=((0, 1),)))
    assert _sm_variants(state) == ["0-1"]


# --- Once per window / optionality ---------------------------------------------

def test_once_per_harvest():
    """After one fire, no Straw Manure variant is offered again this window,
    even with grain and targets to spare."""
    state = _walk_to_window(_harvest_state(grain=5, veg_cells=((0, 1), (1, 2))))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="0-1"))
    assert _sm_variants(state) == []
    assert legal_actions(state) == [Proceed()]


def test_decline_via_proceed_spends_nothing():
    """Proceed pays no grain and adds no vegetable. (The step's advance runs
    the inline take immediately after the frame pops, so the field shows the
    ordinary un-boosted post-take contents: 2 sown - 1 taken = 1. Had the card
    fired, it would read 2.)"""
    state = _walk_to_window(_harvest_state(grain=2, veg_cells=((0, 1),)))
    state = step(state, Proceed())
    assert state.players[0].resources.grain == 2            # no grain paid
    assert _cell(state, 0, 0, 1).veg == 1                   # no boost: 2 - take
    assert state.players[0].resources.veg == 1              # the take's harvest only


def test_not_offered_after_field_segment():
    """Declined at window #3, the card is never re-offered later in the harvest
    (it lives before the field phase, not on the feeding or later seams)."""
    state = _walk_to_window(_harvest_state(grain=2, veg_cells=((0, 1),)))
    state = step(state, Proceed())
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        assert _sm_variants(state) == []
        state = step(state, legal_actions(state)[0])
    assert state.players[0].resources.grain == 2


# --- Owner gating within the FIELD band -----------------------------------------

def test_fires_in_owners_band_when_owner_is_not_starting_player():
    """Owner 1 with starting player 0: the frame appears in player 1's FIELD
    band pass (after player 0's whole segment), for player 1 only."""
    state = setup(seed=0)
    state = fast_replace(state, starting_player=0)
    state = _own_minor(state, 1, CARD_ID)
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=10, grain=1)
    state = with_grid(state, 1, {(0, 1): Cell(cell_type=CellType.FIELD, veg=2)})
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _walk_to_window(state, owner=1)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == WINDOW_ID and top.player_idx == 1
    state = step(state, FireTrigger(card_id=CARD_ID, variant="0-1"))
    assert state.players[1].resources.grain == 0
    assert _cell(state, 1, 0, 1).veg == 3
    # The non-owner (player 0) was never touched.
    assert state.players[0].resources.grain == 0
