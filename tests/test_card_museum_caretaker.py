"""Tests for Museum Caretaker (occupation, E100; Ephipparius Expansion).

Card text: "At the start of each work phase, if you have at least 1 wood,
1 clay, 1 reed, 1 stone, 1 grain, and 1 vegetable in your supply, you get
1 bonus point."

"At the start of each work phase" is the preparation ladder's `start_of_work`
window (ruling 53, 2026-07-14). Per the user's 2026-07-14 rulings the card is
DUALLY registered on that window:

- an AUTO ("you get" is mandatory, choice-free) that banks the point when the
  six-goods criterion holds, ordered AFTER the window's other autos (order>0)
  so same-instant grants — Freemason's 2 clay/stone — land first;
- ALSO a trigger, so a criterion completed mid-window by a same-window
  TRIGGER's grant can still collect on the live window frame.

Max 1 point per round (auto + trigger share the `used_this_round` latch); the
banked points accumulate across rounds and are read back by a scoring term.

NOTE on the Cob pairing (the ruling's own example): Cob's exchange grants
+2 clay +1 food, but clay is the ONLY criterion good it grants and Cob's
printed precondition is "at least 1 clay in your supply" — so any state where
Museum Caretaker's criterion is missing exactly clay makes Cob ineligible too.
Cob can therefore never complete the criterion through the real flow; the
trigger's positive path is pinned here on a real Cob-opened window frame with
the missing good granted mid-frame (the trigger enumeration is live, so any
future same-window trigger that grants a criterion good flows through it).

Flows drive the real round entry (`_complete_preparation`, the
test_card_freemason.py / test_card_cob.py idiom) and real engine actions.
"""
from __future__ import annotations

import agricola.cards.cob  # noqa: F401  (registers the interaction partner)
import agricola.cards.freemason  # noqa: F401  (registers the ordering peer)
import agricola.cards.museum_caretaker  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import add_resources, with_resources

CARD_ID = "museum_caretaker"

_SIX = dict(wood=1, clay=1, reed=1, stone=1, grain=1, veg=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scorer():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {card_id})


def _set_house(state, idx, material):
    return _edit_player(state, idx, house_material=material)


def _set_rooms(state, idx, n):
    """Force player `idx` to have exactly `n` ROOM cells (row 0, cols 0..n-1)."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.ROOM:
                grid[r][c] = Cell(cell_type=CellType.EMPTY)
    for c in range(n):
        grid[0][c] = Cell(cell_type=CellType.ROOM)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return _edit_player(state, idx, farmyard=fy)


def _enter_round(state, *, from_round=1):
    """Run the real preparation ladder from `from_round` into `from_round+1`
    (the start_of_work window is the ladder's last rung)."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _banked(state, idx=0):
    return state.players[idx].card_state.get(CARD_ID, 0)


# ---------------------------------------------------------------------------
# Registration — the dual auto+trigger, with the explicit auto ordering
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # The mandatory "you get" is an AUTO on the start_of_work window ...
    autos = AUTO_EFFECTS.get("start_of_work", [])
    mc = next(e for e in autos if e.card_id == CARD_ID)
    fm = next(e for e in autos if e.card_id == "freemason")
    # ... explicitly ordered AFTER the window's other autos (order, not
    # import-order accident): Freemason's clay/stone must land first.
    assert mc.order > 0
    assert mc.order > fm.order
    assert autos.index(mc) > autos.index(fm)   # the sorted list fires it later
    # ALSO a trigger on the same window (same-window trigger grants can
    # complete the criterion on the live frame).
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_work", ())}
    # Banked points are read back by a scoring term.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}


# ---------------------------------------------------------------------------
# The auto — banks with all six goods, frameless; any missing good -> nothing
# ---------------------------------------------------------------------------

def test_auto_banks_with_all_six_goods():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = with_resources(s, 0, **_SIX)          # exactly 1 of each
    out = _enter_round(s)
    assert _banked(out) == 1
    # The auto fired mechanically — no frame; the ladder completed into WORK.
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert _scorer()(out, 0) == 1


def test_missing_any_one_good_banks_nothing():
    for good in _SIX:
        s = _own_occ(setup(0), 0, CARD_ID)
        s = with_resources(s, 0, **{**_SIX, good: 0})
        out = _enter_round(s)
        assert _banked(out) == 0, f"banked despite missing {good}"
        assert out.pending_stack == ()        # no trigger frame either
        assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Auto ordering — Freemason's same-window clay lands FIRST
# ---------------------------------------------------------------------------

def test_freemason_clay_counts_toward_the_criterion():
    # 0 clay on hand, but Freemason (clay house, exactly 2 rooms) grants +2
    # clay at the same window. Museum Caretaker's auto is ordered after it, so
    # the point is banked. This would fail if the autos fired in registration
    # order with Museum Caretaker first.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _own_occ(s, 0, "freemason")
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 2)
    s = with_resources(s, 0, **{**_SIX, "clay": 0})
    out = _enter_round(s)
    assert out.players[0].resources.clay == 2   # Freemason landed
    assert _banked(out) == 1                    # ... and Museum Caretaker saw it
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# The trigger — same-window grants completing the criterion on a live frame
# ---------------------------------------------------------------------------

def test_cob_exchange_cannot_complete_the_criterion():
    # Criterion missing stone (a good Cob does not grant); Cob eligible
    # (clay 1, grain 2). The window pauses on Cob's frame; Museum Caretaker's
    # trigger is not offered (criterion false), and firing Cob (+2 clay
    # +1 food) still leaves it false — Cob's grants can never complete the
    # criterion, since the only criterion good it grants (clay) is gated by
    # its own "at least 1 clay" precondition.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _own_minor(s, 0, "cob")
    s = with_resources(s, 0, **{**_SIX, "stone": 0, "grain": 2})
    out = _enter_round(s)
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_work" and top.player_idx == 0
    assert _banked(out) == 0                          # the auto did not fire
    la = legal_actions(out)
    assert FireTrigger(card_id="cob") in la
    assert FireTrigger(card_id=CARD_ID) not in la     # criterion false

    out = step(out, FireTrigger(card_id="cob"))
    assert out.players[0].resources == s.players[0].resources + Resources(
        grain=-1, clay=2, food=1)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(out)  # still false
    out = step(out, Proceed())
    assert out.phase is Phase.WORK
    assert _banked(out) == 0


def test_trigger_collects_when_the_criterion_completes_mid_window():
    # A real Cob-opened start_of_work frame with the criterion missing stone;
    # a mid-frame grant of the missing good (standing in for a same-window
    # trigger grant — no implemented start_of_work trigger grants stone today)
    # makes Museum Caretaker's FireTrigger appear on the SAME frame, and firing
    # it banks the point.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _own_minor(s, 0, "cob")
    s = with_resources(s, 0, **{**_SIX, "stone": 0})
    out = _enter_round(s)
    assert isinstance(out.pending_stack[-1], PendingHarvestWindow)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(out)

    out = add_resources(out, 0, stone=1)              # the criterion completes
    assert FireTrigger(card_id=CARD_ID) in legal_actions(out)
    out = step(out, FireTrigger(card_id=CARD_ID))
    assert _banked(out) == 1
    # Latched: not re-offered on the same frame.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(out)
    out = step(out, Proceed())                        # decline Cob, resume the walk
    assert out.phase is Phase.WORK and out.pending_stack == ()
    assert _scorer()(out, 0) == 1


# ---------------------------------------------------------------------------
# Max 1 point per round — the auto's bank latches the trigger off
# ---------------------------------------------------------------------------

def test_trigger_not_offered_after_the_auto_banked():
    # All six goods held: the auto banks at window-open. Cob (clay 1, grain 2)
    # still opens a frame — Museum Caretaker's trigger must NOT be offered on
    # it (used_this_round), before or after Cob fires.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _own_minor(s, 0, "cob")
    s = with_resources(s, 0, **{**_SIX, "grain": 2})
    out = _enter_round(s)
    assert _banked(out) == 1                          # the auto banked
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "start_of_work"
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(out)
    out = step(out, FireTrigger(card_id="cob"))       # criterion still true
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(out)
    out = step(out, Proceed())
    assert _banked(out) == 1                          # never double-banked
    assert _scorer()(out, 0) == 1


# ---------------------------------------------------------------------------
# The bank accumulates across rounds
# ---------------------------------------------------------------------------

def test_accumulates_across_rounds():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = with_resources(s, 0, **_SIX)
    out = _enter_round(s, from_round=1)               # round 2
    assert out.round_number == 2 and _banked(out) == 1
    # The next round's entry clears the latch and banks again (goods intact —
    # the card consumes nothing).
    out = _complete_preparation(fast_replace(out, phase=Phase.PREPARATION))
    assert out.round_number == 3 and _banked(out) == 2
    assert _scorer()(out, 0) == 2


# ---------------------------------------------------------------------------
# Owner-gating
# ---------------------------------------------------------------------------

def test_non_owner_banks_nothing():
    s = setup(0)                                      # nobody owns the card
    s = with_resources(s, 0, **_SIX)
    s = with_resources(s, 1, **_SIX)
    out = _enter_round(s)
    assert out.pending_stack == ()
    assert _banked(out, 0) == 0 and _banked(out, 1) == 0
    assert _scorer()(out, 0) == 0
