"""Tests for the harvest timing-window ladder (stage 1 — the skeleton).

Design of record: design_docs/cards/HARVEST_WINDOWS_DESIGN.md. The harvest walk
(`engine._advance_harvest`) threads the ordered HARVEST_WINDOWS ladder through the
FIELD take and the FEED/BREED frames: simple windows fire their automatic effects
mechanically (starting player first) and push a per-player PendingHarvestWindow
choice frame only for a player with an eligible registered trigger.

These tests register FAKE cards (ids prefixed `_test_hw_`) through the real
registration API at module import — the ownership gate makes them inert for every
other test (nobody else ever owns them), the same containment real card modules
rely on. Registry assertions elsewhere are subset-style per convention, so the
extra entries are harmless.
"""
from agricola.actions import FireTrigger, Proceed
from agricola.canonical import to_canonical
from agricola.cards.harvest_windows import (
    FIELD_BAND_LEN,
    HARVEST_WINDOWS,
    WALK_LENGTH,
    WINDOW_INDEX,
    register_harvest_window_hook,
)
from agricola.cards.triggers import register, register_auto
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_phase, with_sown_fields


# ---------------------------------------------------------------------------
# Fake window cards (registered once, at module import — ownership-gated)
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


def _append_seq(state, idx, tag):
    p = state.players[idx]
    seq = p.card_state.get("_test_hw_seq", ())
    return _edit_player(state, idx, card_state=p.card_state.set(
        "_test_hw_seq", seq + (tag,)))


# An AUTO at start_of_harvest and another at after_harvest, each recording the
# player's crops-still-on-fields total — proving the windows straddle the take.
SNAP_CARD = "_test_hw_snapshotter"
register_auto("start_of_harvest", SNAP_CARD, lambda s, i: True,
              lambda s, i: _append_seq(s, i, ("soh", _grid_grain_total(s, i))))
register_auto("after_harvest", SNAP_CARD, lambda s, i: True,
              lambda s, i: _append_seq(s, i, ("ah", _grid_grain_total(s, i))))
register_harvest_window_hook(SNAP_CARD, "start_of_harvest")
register_harvest_window_hook(SNAP_CARD, "after_harvest")

# Two AUTOs straddling the FEED payment frames, recording firing order.
# (This pair replaced immediately_after_feeding/after_feeding when those two
# windows merged — ruling 2026-07-05: the same instant.)
ORDER_CARD = "_test_hw_orderer"
register_auto("start_of_feeding", ORDER_CARD, lambda s, i: True,
              lambda s, i: _append_seq(s, i, "sof"))
register_auto("after_feeding", ORDER_CARD, lambda s, i: True,
              lambda s, i: _append_seq(s, i, "af"))
register_harvest_window_hook(ORDER_CARD, "start_of_feeding")
register_harvest_window_hook(ORDER_CARD, "after_feeding")

# An optional TRIGGER at end_of_harvest: +1 stone, declinable, once per window.
EOH_CARD = "_test_hw_eoh_trigger"
register("end_of_harvest", EOH_CARD,
         lambda s, i, resolved: True,
         lambda s, i: _edit_player(
             s, i, resources=s.players[i].resources + Resources(stone=1)))
register_harvest_window_hook(EOH_CARD, "end_of_harvest")


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with enough food that feeding is painless."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# ---------------------------------------------------------------------------
# Family fast path: no window card owned → byte-identical, cursor never set
# ---------------------------------------------------------------------------

def test_family_harvest_banded_cursor_pauses_only():
    """Ruling 40 (2026-07-12): a Family harvest's cursor is set exactly while
    a band frame is up — the four payment/breeding pauses (after_feeding /
    after_breeding resume points per pass: 14, 17, 20, 23) — and None
    everywhere else (the walk never pauses a cardless FIELD band)."""
    state = with_sown_fields(_harvest_state(), 0, grain_fields=((0, 1), (0, 2)))
    seen_cursors = set()
    state = _advance_until_decision(state)
    seen_cursors.add(state.harvest_cursor)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, legal_actions(state)[0])
        seen_cursors.add(state.harvest_cursor)
    assert seen_cursors == {None, 14, 17, 20, 23}
    assert state.phase == Phase.PREPARATION
    # No window frame ever appeared, and the canonical JSON has no cursor key.
    assert "harvest_cursor" not in to_canonical(state)


def test_family_field_take_still_takes_one_crop_per_field():
    state = with_sown_fields(_harvest_state(), 0, grain_fields=((0, 1), (0, 2)))
    before = _grid_grain_total(state, 0)
    state = _advance_until_decision(state)          # runs the take, lands in FEED
    assert state.phase == Phase.HARVEST_FEED
    assert _grid_grain_total(state, 0) == before - 2
    assert state.players[0].resources.grain == 2


# ---------------------------------------------------------------------------
# Window autos: ordering across the ladder
# ---------------------------------------------------------------------------

def test_window_autos_straddle_the_take():
    """start_of_harvest reads the still-sown fields; after_harvest reads the
    post-take fields — the ladder orders them around window #5."""
    state = with_sown_fields(_harvest_state(), 0, grain_fields=((0, 1),))  # 3 grain sown
    state = _own_occ(state, 0, SNAP_CARD)
    state = _run_harvest(state)
    seq = state.players[0].card_state.get("_test_hw_seq", ())
    assert seq == (("soh", 3), ("ah", 2))


def test_start_of_feeding_precedes_after_feeding():
    state = _own_occ(_harvest_state(), 1, ORDER_CARD)
    state = _run_harvest(state)
    assert state.players[1].card_state.get("_test_hw_seq", ()) == ("sof", "af")


def test_unowned_window_cards_never_fire():
    state = _run_harvest(_harvest_state())
    for idx in (0, 1):
        assert state.players[idx].card_state.get("_test_hw_seq", ()) == ()


# ---------------------------------------------------------------------------
# Window triggers: frames, SP-first order, decline, once-per-window
# ---------------------------------------------------------------------------

def test_trigger_frame_pushed_and_fireable():
    state = _own_occ(_harvest_state(), 0, EOH_CARD)
    state = _advance_until_decision(state)          # FEED frames
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow):
            break
        state = step(state, legal_actions(state)[0])
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "end_of_harvest"
    assert top.player_idx == 0
    # The cursor pins the resume point at the NEXT window — a VIRTUAL-walk
    # index: with the three per-player bands (rulings 3 + 40) the position
    # after end_of_harvest is the walk's last, after_harvest.
    assert state.harvest_cursor == WALK_LENGTH - 1

    acts = legal_actions(state)
    assert FireTrigger(card_id=EOH_CARD) in acts and Proceed() in acts

    stone_before = state.players[0].resources.stone
    state = step(state, FireTrigger(card_id=EOH_CARD))
    assert state.players[0].resources.stone == stone_before + 1
    # Once per window: the trigger is spent; only Proceed remains.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert state.harvest_cursor is None


def test_trigger_frames_starting_player_decides_first():
    state = _harvest_state()
    state = fast_replace(state, starting_player=1)
    state = _own_occ(_own_occ(state, 0, EOH_CARD), 1, EOH_CARD)
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow):
            break
        state = step(state, legal_actions(state)[0])
    # Two frames out; the starting player (1) decides first.
    assert [f.player_idx for f in state.pending_stack
            if isinstance(f, PendingHarvestWindow)] == [0, 1]
    state = step(state, Proceed())                  # SP declines
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.player_idx == 0
    state = step(state, FireTrigger(card_id=EOH_CARD))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION


def test_declining_grants_nothing():
    state = _own_occ(_harvest_state(), 0, EOH_CARD)
    stone_before = state.players[0].resources.stone

    def pick(acts):
        proceeds = [a for a in acts if isinstance(a, Proceed)]
        return proceeds[0] if proceeds else acts[0]

    state = _run_harvest(state, pick)
    assert state.players[0].resources.stone == stone_before


# ---------------------------------------------------------------------------
# The ladder itself
# ---------------------------------------------------------------------------

def test_ladder_shape():
    # Ordering is rules-derived and load-bearing (HARVEST_WINDOWS_DESIGN.md §1):
    # spot-check the anchors rather than the whole tuple (subset-style, so a new
    # window insertion doesn't break unrelated work).
    assert WINDOW_INDEX["immediately_before_harvest"] == 0
    assert (WINDOW_INDEX["start_of_harvest"]
            < WINDOW_INDEX["before_field_phase"]
            < WINDOW_INDEX["start_of_field_phase"]
            < WINDOW_INDEX["field_phase"]
            < WINDOW_INDEX["end_of_field_phase"]
            < WINDOW_INDEX["after_field_phase"]
            < WINDOW_INDEX["start_of_feeding"]
            < WINDOW_INDEX["feeding"]
            < WINDOW_INDEX["after_feeding"]
            < WINDOW_INDEX["start_of_breeding"]
            < WINDOW_INDEX["breeding"]
            < WINDOW_INDEX["after_breeding"]
            < WINDOW_INDEX["end_of_harvest"]
            < WINDOW_INDEX["after_harvest"])
    # Rulings 2026-07-05: "immediately after each harvest" = "after each harvest"
    # and "immediately after the feeding phase" = "after the feeding phase" —
    # ONE window each, no separate immediately_* entries.
    assert "immediately_after_harvest" not in WINDOW_INDEX
    assert "immediately_after_feeding" not in WINDOW_INDEX
    assert HARVEST_WINDOWS[-1] == "after_harvest"
