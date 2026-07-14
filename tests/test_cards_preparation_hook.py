"""Tests for the preparation-ladder machinery (user ruling 54, 2026-07-14).

The preparation phase is a cursor-driven timing ladder
(`agricola/cards/preparation.py`, walked by `engine._advance_preparation`):
mechanical sentinels (`__collect__` — newborns/used-sets clear + round-space
collection; `__reveal__` — the nature pause; `__round_setup__` — round_number
increments; `__replenish__` — the accumulation refill) interleaved with card
WINDOWS (`round_space_collection`, `reveal`, `start_of_round`, `replenishment`,
`before_work`, `start_of_work`). Each window fires its automatic effects
mechanically per player (starting player first) with NO frame; a
`PendingHarvestWindow(window_id=<window>, player_idx=<idx>)` choice frame is
pushed ONLY for each player with an ELIGIBLE registered TRIGGER on that window
(non-SP pushed first, so the starting player decides first). Triggers surface
as `FireTrigger`; `Proceed` declines/pops; a mandatory trigger (Childless)
gates Proceed off until fired. While a window frame is up the phase is still
PREPARATION and `prep_cursor` stores the walk's resume point; the reveal pause
deliberately carries NO cursor (its resume is derived from public state, so
`prep_cursor` stays Family-constant None).

These tests exercise the machinery itself — registration mapping, the
auto-vs-trigger frame contract, frame order, mandatory gating, the two pause
kinds, the Family fast path, and the ladder's step order — with real cards
(Plow Driver, Scullery, Childless) plus two synthetic recording autos for the
order check. Per-card behavior lives in the card test files
(tests/test_cards_category7.py, tests/test_card_trout_pool.py, …).
"""
from __future__ import annotations

import numpy as np

from agricola.actions import CommitCardChoice, FireTrigger, Proceed
from agricola.agents.base import decider_of
from agricola.cards.preparation import PREP_INDEX, PREP_STEPS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS, register_auto
from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    CellType,
    HouseMaterial,
    Phase,
)
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingCardChoice,
    PendingHarvestWindow,
    PendingReveal,
    push,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup, setup_env
from agricola.state import Cell, get_space, with_space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_house(state, idx, material, extra=Resources()):
    p = state.players[idx]
    p = fast_replace(p, house_material=material, resources=p.resources + extra)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


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
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible_plow_driver(state, idx):
    """Make Plow Driver eligible for `idx`: stone house + food to pay."""
    state = _own_occ(state, idx, "plow_driver")
    return _set_house(state, idx, HouseMaterial.STONE, extra=Resources(food=2))


def _prep_boundary(state, round_number=1):
    """A PREPARATION-phase state poised at the round-`round_number` →
    `round_number+1` boundary for `_complete_preparation` (which runs the whole
    ladder with the reveal step assumed done)."""
    return fast_replace(state, phase=Phase.PREPARATION, round_number=round_number)


# ---------------------------------------------------------------------------
# Registration mapping — each card sits on its ladder window's event
# ---------------------------------------------------------------------------

def test_ladder_registration_mapping():
    # Optional / mandatory TRIGGERS on the start_of_round window.
    sor = {e.card_id for e in TRIGGERS.get("start_of_round", [])}
    for cid in ("plow_driver", "groom", "scholar", "childless", "handplow",
                "tree_farm_joiner"):
        assert cid in sor
    # Choice-free AUTOS on start_of_round.
    sor_autos = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    for cid in ("small_scale_farmer", "scullery"):
        assert cid in sor_autos
    # RE-TAGGED events (ruling 54): Nest Site's "placed on [a space] in the
    # preparation phase" is the replenishment window; "at the start of each
    # work phase" (Freemason, Cob, Trout Pool) is the start_of_work window.
    assert "nest_site" in {e.card_id for e in AUTO_EFFECTS.get("replenishment", ())}
    sow_autos = {e.card_id for e in AUTO_EFFECTS.get("start_of_work", ())}
    assert "freemason" in sow_autos and "trout_pool" in sow_autos
    assert "cob" in {e.card_id for e in TRIGGERS.get("start_of_work", [])}
    assert "nest_site" not in (sor | sor_autos)
    assert not {"freemason", "cob", "trout_pool"} & (sor | sor_autos)
    # Every window id in the ladder table is a distinct step, in the ruled order.
    for w in ("round_space_collection", "reveal", "start_of_round",
              "replenishment", "before_work", "start_of_work"):
        assert w in PREP_STEPS
    assert (PREP_INDEX["start_of_round"] < PREP_INDEX["__replenish__"]
            < PREP_INDEX["replenishment"] < PREP_INDEX["before_work"]
            < PREP_INDEX["start_of_work"])


# ---------------------------------------------------------------------------
# Family fast path — no frames, prep_cursor None throughout
# ---------------------------------------------------------------------------

def test_family_game_no_window_frames_and_no_cursor():
    """A full Family game completes with no window choice frame or
    PendingCardChoice ever produced, and prep_cursor stays None on every state
    (the ladder pauses only at the reveal — the Family fast path)."""
    rng = np.random.default_rng(11)
    s, env = setup_env(11)
    saw_frame = False
    steps = 0
    while s.phase != Phase.BEFORE_SCORING and steps < 8000:
        assert s.prep_cursor is None
        for f in s.pending_stack:
            if isinstance(f, (PendingHarvestWindow, PendingCardChoice)):
                saw_frame = True
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))
        else:
            la = legal_actions(s)
            s = step(s, la[rng.integers(len(la))])
        steps += 1
    assert s.phase == Phase.BEFORE_SCORING
    assert not saw_frame


def test_complete_preparation_no_frame_without_card():
    """_complete_preparation on a cardless state runs the whole ladder straight
    through: no frame, round incremented, phase flipped to WORK with the
    starting player active, cursor None."""
    out = _complete_preparation(_prep_boundary(setup(5)))
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert out.round_number == 2
    assert out.prep_cursor is None
    assert out.current_player == out.starting_player


# ---------------------------------------------------------------------------
# Auto-only → no frame; hand cards never fire
# ---------------------------------------------------------------------------

def test_auto_only_card_produces_no_frame():
    # Scullery (+1 food in a wooden house) is a choice-free AUTO: it fires
    # mechanically at its window with NO frame, so the returned state is
    # already in WORK with an empty stack and the effect applied.
    s = setup(0)
    p = s.players[0]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {"scullery"})
    s = fast_replace(s, players=(p, s.players[1]))     # default house is WOOD
    before = s.players[0].resources.food
    out = _complete_preparation(_prep_boundary(s))
    assert out.players[0].resources.food == before + 1
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert out.prep_cursor is None


def test_hand_card_never_fires():
    # A card only in HAND is not played: it neither fires nor surfaces a
    # trigger (the _owns filter), so the ladder completes with no frame.
    s = setup(0)
    p = s.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"plow_driver"},
                     house_material=HouseMaterial.STONE,
                     resources=p.resources + Resources(food=2))
    s = fast_replace(s, players=(p, s.players[1]))
    out = _complete_preparation(_prep_boundary(s))
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Trigger → window frame (phase PREPARATION, cursor set), decline resumes
# ---------------------------------------------------------------------------

def test_trigger_pushes_window_frame_and_cursor():
    s = _eligible_plow_driver(setup(0), 0)
    out = _complete_preparation(_prep_boundary(s))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round" and top.player_idx == 0
    # While a window frame is up the phase is still PREPARATION, and — unlike
    # the reveal pause — the card-window pause carries the resume cursor.
    assert out.phase is Phase.PREPARATION
    assert out.prep_cursor == PREP_INDEX["start_of_round"] + 1
    la = legal_actions(out)
    assert FireTrigger(card_id="plow_driver") in la
    assert Proceed() in la                     # optional → declinable
    # Proceed declines: the walk resumes from the cursor and completes to WORK.
    done = step(out, Proceed())
    assert done.phase is Phase.WORK
    assert done.pending_stack == ()
    assert done.prep_cursor is None


def test_frame_for_the_non_current_player_too():
    # Owned by the OTHER player still pushes a frame (per-player frames keyed
    # on the owner's eligibility, not on whose placement is being resolved);
    # the frame's player_idx — not current_player — names the decider.
    s = _eligible_plow_driver(setup(0), 1)
    out = _complete_preparation(_prep_boundary(s))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.player_idx == 1
    assert decider_of(out) == 1


def test_sp_decides_first_frame_order():
    # Both players own an eligible start_of_round trigger → one frame each,
    # non-SP pushed FIRST so the starting player's frame ends on top (SP
    # decides first — the FEED/BREED push order).
    s = setup(0)
    for i in (0, 1):
        s = _eligible_plow_driver(s, i)
    out = _complete_preparation(_prep_boundary(s))
    frames = [f for f in out.pending_stack if isinstance(f, PendingHarvestWindow)]
    assert len(frames) == 2
    assert all(f.window_id == "start_of_round" for f in frames)
    sp = out.starting_player
    assert frames[-1].player_idx == sp
    assert frames[-2].player_idx == (sp + 1) % 2
    assert decider_of(out) == sp


def test_used_this_round_clears_at_round_entry_before_windows():
    # The per-round used-set clears at __collect__ (step 0), BEFORE any window:
    # a start_of_round trigger latched last round is eligible again this round.
    s = _eligible_plow_driver(setup(0), 0)
    p = s.players[0]
    p = fast_replace(p, used_this_round=p.used_this_round | {"plow_driver"})
    s = fast_replace(s, players=(p, s.players[1]))
    out = _complete_preparation(_prep_boundary(s))
    assert "plow_driver" not in out.players[0].used_this_round
    assert isinstance(out.pending_stack[-1], PendingHarvestWindow)
    assert FireTrigger(card_id="plow_driver") in legal_actions(out)


# ---------------------------------------------------------------------------
# Mandatory-with-choice gating (Childless) through the real ladder
# ---------------------------------------------------------------------------

def test_mandatory_gate_childless_through_the_ladder():
    # Childless (>=3 rooms, exactly 2 people) is the mandatory-with-choice
    # kind: its window frame withholds Proceed until it fires; firing pushes
    # the PendingCardChoice (grain/veg, no decline); resolving reopens Proceed;
    # Proceed then resumes the walk to WORK.
    s = _own_occ(setup(0), 0, "childless")
    s = _set_rooms(s, 0, 3)
    out = _complete_preparation(_prep_boundary(s))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round"
    assert legal_actions(out) == [FireTrigger(card_id="childless")]  # no Proceed
    food0 = out.players[0].resources.food
    out = step(out, FireTrigger(card_id="childless"))
    assert out.players[0].resources.food == food0 + 1
    top = out.pending_stack[-1]
    assert isinstance(top, PendingCardChoice) and top.options == ("grain", "veg")
    assert legal_actions(out) == [CommitCardChoice(index=0), CommitCardChoice(index=1)]
    grain0 = out.players[0].resources.grain
    out = step(out, CommitCardChoice(index=0))   # grain
    assert out.players[0].resources.grain == grain0 + 1
    # The gate reopens; the fired trigger is not offered again.
    la = legal_actions(out)
    assert Proceed() in la
    assert FireTrigger(card_id="childless") not in la
    out = step(out, Proceed())
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()


def test_single_option_card_choice_is_singleton():
    """A 1-option PendingCardChoice offers exactly one CommitCardChoice (a
    singleton the agent auto-resolves), never a decline."""
    state = setup(0)
    state = push(state, PendingCardChoice(
        player_idx=0, initiated_by_id="card:childless", options=("grain",)))
    assert legal_actions(state) == [CommitCardChoice(index=0)]


# ---------------------------------------------------------------------------
# The reveal pause — no cursor, goods collected BEFORE the reveal
# ---------------------------------------------------------------------------

def test_reveal_pause_no_cursor_and_precollected_goods():
    """Drive a real Family game to the round-1 → round-2 boundary. The reveal
    pause: PendingReveal up, phase PREPARATION, prep_cursor None (the resume is
    derived from public state, never stored across the reveal) — and, ruling
    53's one Family-observable reordering, the round-space goods were collected
    at __collect__ BEFORE the reveal, with round_number still naming the
    just-completed round (steps 0-2 semantics)."""
    rng = np.random.default_rng(3)
    s, env = setup_env(3)
    # Promise 1 veg on the round-2 slot (index 1), Well-style. Veg is
    # unobtainable through round-1 play, so its arrival isolates the collection.
    p = s.players[0]
    fr = list(p.future_resources)
    fr[1] = fr[1] + Resources(veg=1)
    p = fast_replace(p, future_resources=tuple(fr))
    s = fast_replace(s, players=(p, s.players[1]))
    assert s.players[0].resources.veg == 0
    steps = 0
    while decider_of(s) is not None and steps < 300:
        la = legal_actions(s)
        s = step(s, la[rng.integers(len(la))])
        steps += 1
    # The nature pause.
    assert isinstance(s.pending_stack[-1], PendingReveal)
    assert s.phase is Phase.PREPARATION
    assert s.prep_cursor is None
    assert s.round_number == 1                       # pre-__round_setup__
    assert s.players[0].resources.veg == 1           # collected pre-reveal
    # Resuming through the reveal completes the Family ladder: WORK, round 2,
    # no frame, cursor still None.
    s = step(s, env.resolve(s))
    assert s.phase is Phase.WORK and s.round_number == 2
    assert s.pending_stack == ()
    assert s.prep_cursor is None


# ---------------------------------------------------------------------------
# Ladder order — start_of_round is PRE-refill, start_of_work POST-refill
# ---------------------------------------------------------------------------

# Two synthetic recording autos (registered once at import, gated on ownership
# of fake card ids no other test owns). Each logs the forest bank it observes.
_WINDOW_LOG: list[tuple[str, int]] = []


def _record(event):
    def _apply(state, idx):
        _WINDOW_LOG.append(
            (event, get_space(state.board, "forest").accumulated.wood))
        return state
    return _apply


register_auto("start_of_round", "synth_prewindow",
              lambda s, i: True, _record("start_of_round"))
register_auto("start_of_work", "synth_postwindow",
              lambda s, i: True, _record("start_of_work"))


def test_window_order_around_the_replenish_step():
    # A start_of_round auto sees the PRE-refill accumulation board; a
    # start_of_work auto sees the POST-refill board (the __replenish__ sentinel
    # sits between them), and start_of_round fires first.
    _WINDOW_LOG.clear()
    s = setup(0)
    p = s.players[0]
    p = fast_replace(
        p, occupations=p.occupations | {"synth_prewindow", "synth_postwindow"})
    s = fast_replace(s, players=(p, s.players[1]))
    forest = get_space(s.board, "forest")
    s = fast_replace(s, board=with_space(
        s.board, "forest", fast_replace(forest, accumulated=Resources(wood=5))))
    out = _complete_preparation(_prep_boundary(s))
    assert out.phase is Phase.WORK
    rate = BUILDING_ACCUMULATION_RATES["forest"].wood
    assert _WINDOW_LOG == [("start_of_round", 5), ("start_of_work", 5 + rate)]
