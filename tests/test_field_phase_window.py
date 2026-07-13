"""Tests for the FIELD during-window machinery — harvest window #5
(HARVEST_WINDOWS_DESIGN.md §4, stage 2 of the harvest-window build):

- the take-occasion manifest (`field_take` emitting HarvestOccasion/HarvestEntry),
- the per-occasion AUTO registry (`register_harvest_occasion_auto`) firing on
  both the inline take and the hosted CommitFieldTake,
- the PendingFieldPhase host: free-order triggers around the MANDATORY take
  (Proceed withheld until it fires; one take only),
- the per-player FIELD band (user ruling 3): the starting player's whole
  during-window — frame, triggers, take — completes before the other player's,
- the "field_phase" window autos anchoring BEFORE the take,
- `walk_position`'s virtual-walk decode.

Fake `_test_fp_` cards register once at import; the ownership gate keeps them
inert for every other test file (no real player ever owns them).
"""
from agricola.actions import CommitFieldTake, FireTrigger, Proceed
from agricola.cards.harvest_windows import (
    FIELD_BAND_LEN,
    FIELD_BAND_START,
    HARVEST_WINDOWS,
    WALK_LENGTH,
    WINDOW_INDEX,
    register_harvest_occasion_auto,
    register_harvest_window_hook,
    walk_position,
)
from agricola.cards.triggers import register, register_auto
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingFieldPhase
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import with_phase, with_sown_fields


# ---------------------------------------------------------------------------
# Fake cards (registered once, at module import — ownership-gated)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _grid_grain_total(state, idx):
    return sum(cell.grain
               for row in state.players[idx].farmyard.grid for cell in row
               if cell.cell_type == CellType.FIELD)


def _record(state, idx, key, item):
    p = state.players[idx]
    seq = p.card_state.get(key, ())
    return _edit_player(state, idx, card_state=p.card_state.set(key, seq + (item,)))


# A per-occasion AUTO: records each occasion's (source, crop totals, emptied
# count) into card_state — the Grain-Sieve-shaped consumer of the manifest.
OCC_AUTO_CARD = "_test_fp_occ_auto"
register_harvest_occasion_auto(
    OCC_AUTO_CARD,
    lambda s, i, occ: True,
    lambda s, i, occ: _record(s, i, "_test_fp_occasions", (
        occ.source,
        sum(e.amount for e in occ.entries if e.crop == "grain"),
        sum(e.amount for e in occ.entries if e.crop == "veg"),
        sum(1 for e in occ.entries if e.emptied),
    )))

# An optional TRIGGER on the during-window ("field_phase" event): +1 food,
# declinable, once per window. Owning it is what hosts the during-frame.
FP_TRIGGER_CARD = "_test_fp_trigger"
register("field_phase", FP_TRIGGER_CARD,
         lambda s, i, resolved: True,
         lambda s, i: _edit_player(
             s, i, resources=s.players[i].resources + Resources(food=1)))
register_harvest_window_hook(FP_TRIGGER_CARD, "field_phase")

# A during-window AUTO (flat state-reader): records the player's crops still on
# fields at fire time — proving the pre-take anchor.
FP_AUTO_CARD = "_test_fp_auto"
register_auto("field_phase", FP_AUTO_CARD, lambda s, i: True,
              lambda s, i: _record(s, i, "_test_fp_auto_snap",
                                   _grid_grain_total(s, i)))
register_harvest_window_hook(FP_AUTO_CARD, "field_phase")

# The post-take re-host pair: a trigger GATED on food >= 1 (+1 stone when
# fired) and an occasion AUTO paying +1 food per occasion — so a 0-food owner's
# trigger becomes eligible only FROM the take's own income, exercising the
# inline path's post-take trigger re-check.
FP_GATED_CARD = "_test_fp_gated_trigger"
register("field_phase", FP_GATED_CARD,
         lambda s, i, resolved: s.players[i].resources.food >= 1,
         lambda s, i: _edit_player(
             s, i, resources=s.players[i].resources + Resources(stone=1)))
register_harvest_window_hook(FP_GATED_CARD, "field_phase")

FP_FEEDER_CARD = "_test_fp_feeder"
register_harvest_occasion_auto(
    FP_FEEDER_CARD,
    lambda s, i, occ: True,
    lambda s, i, occ: _edit_player(
        s, i, resources=s.players[i].resources + Resources(food=1)))


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _walk_to_field_frame(state):
    """Advance until a PendingFieldPhase surfaces (or the harvest ends)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingFieldPhase):
            return state
        state = step(state, legal_actions(state)[0])
    return state


# ---------------------------------------------------------------------------
# The virtual walk
# ---------------------------------------------------------------------------

def test_walk_position_decodes_the_bands():
    """Rulings 3 + 40: three per-player bands (FIELD, FEED, BREED), the four
    outer moments window-major. The decoded sequence IS the design."""
    sp = 1
    decoded = [walk_position(v, sp) for v in range(WALK_LENGTH)]
    names = [(HARVEST_WINDOWS[w], bp) for w, bp in decoded]
    field = ["before_field_phase", "start_of_field_phase", "field_phase",
             "end_of_field_phase", "after_field_phase"]
    feed = ["start_of_feeding", "feeding", "after_feeding"]
    breed = ["start_of_breeding", "breeding", "after_breeding"]
    expected = (
        [("immediately_before_harvest", None), ("start_of_harvest", None)]
        + [(w, sp) for w in field] + [(w, 1 - sp) for w in field]
        + [(w, sp) for w in feed] + [(w, 1 - sp) for w in feed]
        + [(w, sp) for w in breed] + [(w, 1 - sp) for w in breed]
        + [("end_of_harvest", None), ("after_harvest", None)]
    )
    assert names == expected
    assert WALK_LENGTH == 26
    # The virtual walk ends exactly at the ladder's end.
    assert walk_position(WALK_LENGTH - 1, sp)[0] == len(HARVEST_WINDOWS) - 1


# ---------------------------------------------------------------------------
# The bare take function
# ---------------------------------------------------------------------------

def test_field_take_manifest_and_grain_precedence():
    state = with_sown_fields(_harvest_state(), 0,
                             grain_fields=[(0, 0), (0, 1)], veg_fields=[(1, 1)])
    # Deplete one grain field to 1 so the take empties it.
    p = state.players[0]
    grid = [list(r) for r in p.farmyard.grid]
    grid[0][1] = fast_replace(grid[0][1], grain=1)
    state = _edit_player(state, 0, farmyard=fast_replace(
        p.farmyard, grid=tuple(tuple(r) for r in grid)))

    g, v = state.players[0].resources.grain, state.players[0].resources.veg
    state, occ = field_take(state, 0)
    assert occ.source == "take"
    assert state.players[0].resources.grain == g + 2
    assert state.players[0].resources.veg == v + 1
    by_source = {e.source: e for e in occ.entries}
    assert by_source["cell:0,0"].crop == "grain" and not by_source["cell:0,0"].emptied
    assert by_source["cell:0,1"].emptied            # took the last grain
    assert by_source["cell:1,1"].crop == "veg"
    assert all(e.amount == 1 for e in occ.entries)


def test_field_take_is_bare_no_budget_reset_custom_source():
    """The bare function is ruling 4's Bumper-Crop entry point: no phase
    machinery — the once-per-harvest conversion budget is untouched — and the
    caller's `source` lets phase-keyed occasion consumers stay silent."""
    state = with_sown_fields(_harvest_state(), 0, grain_fields=[(0, 0)])
    state = _edit_player(state, 0, harvest_conversions_used=frozenset({"joinery"}))
    state, occ = field_take(state, 0, source="card:_test_bumper")
    assert occ.source == "card:_test_bumper"
    assert state.players[0].harvest_conversions_used == frozenset({"joinery"})


# ---------------------------------------------------------------------------
# Inline take: occasions + per-occasion autos, no frame
# ---------------------------------------------------------------------------

def test_inline_take_fires_occasion_autos():
    state = _own_occ(_harvest_state(), 0, OCC_AUTO_CARD)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    state = _advance_until_decision(state)              # runs FIELD into FEED
    assert state.phase == Phase.HARVEST_FEED
    # No during-frame existed (no field_phase trigger), yet the auto saw the
    # take occasion: 1 grain + 1 veg, nothing emptied (fresh 3/2-count fields).
    assert state.players[0].card_state.get("_test_fp_occasions") == (
        ("take", 1, 1, 0),)
    # The non-owner's auto never fired.
    assert state.players[1].card_state.get("_test_fp_occasions") is None


def test_window_autos_fire_before_the_take():
    state = _own_occ(_harvest_state(), 0, FP_AUTO_CARD)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _advance_until_decision(state)
    # The snapshot saw all 6 grain still on the fields (3 per fresh field).
    assert state.players[0].card_state.get("_test_fp_auto_snap") == (6,)
    assert _grid_grain_total(state, 0) == 4             # take happened after


# ---------------------------------------------------------------------------
# The hosted during-window: free order, mandatory take, Proceed gate
# ---------------------------------------------------------------------------

def test_frame_take_then_trigger_free_order():
    state = _own_occ(_harvest_state(), 0, FP_TRIGGER_CARD)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    assert not top.take_fired and top.occasions == ()

    acts = legal_actions(state)
    assert CommitFieldTake() in acts
    assert FireTrigger(card_id=FP_TRIGGER_CARD) in acts
    assert Proceed() not in acts                        # the take is mandatory

    g = state.players[0].resources.grain
    state = step(state, CommitFieldTake())
    top = state.pending_stack[-1]
    assert top.take_fired
    assert [o.source for o in top.occasions] == ["take"]
    assert state.players[0].resources.grain == g + 1

    # The trigger is still offered AFTER the take (free order), plus Proceed.
    acts = legal_actions(state)
    assert FireTrigger(card_id=FP_TRIGGER_CARD) in acts and Proceed() in acts
    assert CommitFieldTake() not in acts                # one take only

    food = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=FP_TRIGGER_CARD))
    assert state.players[0].resources.food == food + 1
    assert legal_actions(state) == [Proceed()]          # spent; exit only
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED
    # Ruling 40 (2026-07-12): the banded walk carries the cursor through FEED.
    assert state.harvest_cursor is not None


def test_frame_trigger_then_take_other_order():
    state = _own_occ(_harvest_state(), 0, FP_TRIGGER_CARD)
    state = with_sown_fields(state, 0, veg_fields=[(1, 1)])
    state = _walk_to_field_frame(state)
    food = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=FP_TRIGGER_CARD))
    assert state.players[0].resources.food == food + 1
    assert legal_actions(state) == [CommitFieldTake()]  # take still owed, no Proceed
    v = state.players[0].resources.veg
    state = step(state, CommitFieldTake())
    assert state.players[0].resources.veg == v + 1
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED


def test_frame_take_fires_occasion_autos_too():
    state = _own_occ(_own_occ(_harvest_state(), 0, FP_TRIGGER_CARD), 0, OCC_AUTO_CARD)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    state = step(state, CommitFieldTake())
    assert state.players[0].card_state.get("_test_fp_occasions") == (
        ("take", 1, 0, 0),)


# ---------------------------------------------------------------------------
# The per-player FIELD band (user ruling 3)
# ---------------------------------------------------------------------------

def test_sp_whole_field_phase_resolves_before_the_other_players():
    state = _harvest_state()
    sp = state.starting_player
    for i in (0, 1):
        state = _own_occ(state, i, FP_TRIGGER_CARD)
        state = with_sown_fields(state, i, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)

    # The starting player's frame alone is out; the other player's field phase
    # has not begun — their fields are untaken.
    frames = [f for f in state.pending_stack if isinstance(f, PendingFieldPhase)]
    assert [f.player_idx for f in frames] == [sp]
    assert _grid_grain_total(state, 1 - sp) == 3

    # SP takes and exits; only then does the other player's frame surface,
    # with SP's whole window (trigger unfired, take done) behind them.
    state = step(state, CommitFieldTake())
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 1 - sp
    assert _grid_grain_total(state, sp) == 2            # SP's take done
    assert _grid_grain_total(state, 1 - sp) == 3        # theirs still pending
    state = step(state, CommitFieldTake())
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED
    assert _grid_grain_total(state, 1 - sp) == 2


def test_take_income_enables_a_trigger_post_take():
    """The inline path re-checks triggers AFTER the take: an owner with 0 food
    whose per-occasion income (the feeder) pays 1 food gets the during-frame
    hosted POST-take (take_fired=True), so the food-gated trigger is offered —
    the window isn't over just because the take ran inline."""
    state = _own_occ(_own_occ(_harvest_state(), 0, FP_GATED_CARD), 0, FP_FEEDER_CARD)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, food=0))              # gated OFF at entry
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    assert top.take_fired                                  # hosted post-take
    assert [o.source for o in top.occasions] == ["take"]   # manifest carried over
    assert state.players[0].resources.food == 1            # the feeder's income
    acts = legal_actions(state)
    assert FireTrigger(card_id=FP_GATED_CARD) in acts and Proceed() in acts
    assert not any(isinstance(a, CommitFieldTake) for a in acts)  # take done
    state = step(state, FireTrigger(card_id=FP_GATED_CARD))
    assert state.players[0].resources.stone == 1
    state = step(state, Proceed())
    assert _advance_until_decision(state).phase == Phase.HARVEST_FEED


def test_no_rehost_when_trigger_stays_ineligible():
    """The post-take re-check is a no-op when nothing became eligible: a 0-food
    gated-trigger owner WITHOUT the feeder walks straight through to FEED."""
    state = _own_occ(_harvest_state(), 0, FP_GATED_CARD)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, food=0))
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED
    assert not any(isinstance(f, PendingFieldPhase) for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Family fast path: the occasion machinery is invisible without registrations
# ---------------------------------------------------------------------------

def test_family_field_phase_no_frame_mid_feed_cursor():
    state = with_sown_fields(_harvest_state(), 0, grain_fields=[(0, 0)])
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED
    # Ruling 40 (2026-07-12): a Family mid-feed state now carries the walk
    # cursor (one payment frame per band pass) — the arc's first
    # Family-visible harvest-shape change; the C++ twin mirrors it.
    assert state.harvest_cursor is not None
    assert not any(isinstance(f, PendingFieldPhase) for f in state.pending_stack)
    assert _grid_grain_total(state, 0) == 2
    # The once-per-harvest conversion budget was reset at harvest entry.
    assert state.players[0].harvest_conversions_used == frozenset()
