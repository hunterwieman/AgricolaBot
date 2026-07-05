import agricola.cards.beer_table  # noqa: F401
# Tests for Beer Table (minor improvement, C29; Corbarius Expansion).
#
# Card text (verbatim): "At the end of the field phase of each harvest, you can
# pay 1 grain from your supply to get 2 bonus points. If you do, all other
# players get 1 food each."
# Cost: 2 Wood. VPs: none printed. Prerequisite: "No Grain in Your Supply".
#
# TIMING: harvest window #6 `end_of_field_phase` — an optional plain trigger on
# the per-player PendingHarvestWindow host AFTER that player's crop take
# (window #5) and BEFORE window #7, inside the per-player FIELD segment
# (ruling 3, 2026-07-03: the starting player's whole FIELD segment resolves
# before the other player's begins). Pays 1 grain, banks 2 bonus points in
# CardStore (read back by the scoring term), and gives every other player 1
# food — only when fired ("If you do"). Once per harvest; Proceed declines.
#
# Drivers mirror tests/test_card_home_brewer.py / tests/test_harvest_windows.py.

import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.beer_table import CARD_ID, WINDOW_ID
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import Cell, GameState

from tests.factories import with_grid, with_phase, with_resources


# --- Helpers ----------------------------------------------------------------

def _own_minor(state, player_idx, card_id):
    p = state.players[player_idx]
    p = dataclasses.replace(p, minor_improvements=p.minor_improvements | {card_id})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, grain=0, owned=True, owner=0) -> GameState:
    """A HARVEST_FIELD-phase state with `owner` (optionally) owning Beer Table
    and holding `grain`. Both players get plenty of food so feeding is painless
    (and never converts the goods under test)."""
    state = setup(seed=0)
    state = fast_replace(state, starting_player=owner)
    if owned:
        state = _own_minor(state, owner, CARD_ID)
    state = with_resources(state, owner, food=10, grain=grain)
    state = with_resources(state, 1 - owner, food=10)
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


def _bt_offered(state):
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state))


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration / spec ------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))   # "2 Wood"
    assert spec.vps == 0                                    # vps=null -> 0
    assert spec.passing_left is False
    assert spec.prereq is not None                          # "No Grain in Your Supply"
    # A plain trigger (fixed cost, fixed output — no variants) on window #6.
    assert CARD_ID not in PLAY_VARIANT_TRIGGERS
    assert WINDOW_ID == "end_of_field_phase"
    assert CARD_ID in HARVEST_WINDOW_CARDS[WINDOW_ID]
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_prereq_no_grain_in_supply():
    s = setup(0)
    s = with_resources(s, 0, food=3)                        # 0 grain
    assert prereq_met(MINORS[CARD_ID], s, 0)
    s = with_resources(s, 0, food=3, grain=1)               # any grain blocks
    assert not prereq_met(MINORS[CARD_ID], s, 0)


# --- Real-flow effect ---------------------------------------------------------

def test_fire_pays_grain_banks_points_feeds_opponent():
    state = _walk_to_window(_harvest_state(grain=1))
    opp_food_before = state.players[1].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))

    assert state.players[0].resources.grain == 0            # 1 grain paid
    assert state.players[0].card_state.get(CARD_ID, 0) == 2  # 2 points banked
    # "If you do, all other players get 1 food each" — the opponent, in 2p.
    assert state.players[1].resources.food == opp_food_before + 1


def test_take_harvested_grain_can_pay():
    """Window #6 follows window #5's crop take: grain harvested moments earlier
    in the same field phase is in the supply and can pay the card — the printed
    "end of the field phase" instant."""
    state = _harvest_state(grain=0)                         # no grain in supply
    state = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD, grain=3)})
    state = _walk_to_window(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == WINDOW_ID
    assert state.players[0].resources.grain == 1            # the take's harvest
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.grain == 0
    assert state.players[0].card_state.get(CARD_ID, 0) == 2


def test_owner_segment_resolves_before_opponents_take():
    """Ruling 3's whole-segment-per-player ordering: the starting player's
    window #6 fires while the other player's FIELD segment has not begun — the
    food handed over arrives before the opponent's own take."""
    state = _harvest_state(grain=1, owner=0)                # owner 0 is SP
    state = with_grid(state, 1, {(0, 1): Cell(cell_type=CellType.FIELD, grain=3)})
    state = _walk_to_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # The opponent has the food already, but their take has NOT run yet.
    assert state.players[1].resources.food == 11
    assert state.players[1].farmyard.grid[0][1].grain == 3
    assert state.players[1].resources.grain == 0
    # Walk on: the opponent's band then runs their take.
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    while state.phase == Phase.HARVEST_FIELD:
        state = step(state, legal_actions(state)[0])
    assert state.players[1].farmyard.grid[0][1].grain == 2
    assert state.players[1].resources.grain == 1


# --- Eligibility boundaries ---------------------------------------------------

def test_not_offered_without_grain():
    state = _walk_to_window(_harvest_state(grain=0))
    assert not (state.pending_stack
                and isinstance(state.pending_stack[-1], PendingHarvestWindow))


def test_not_offered_when_unowned():
    state = _walk_to_window(_harvest_state(grain=2, owned=False))
    assert not (state.pending_stack
                and isinstance(state.pending_stack[-1], PendingHarvestWindow))


def test_exactly_one_grain_suffices():
    state = _walk_to_window(_harvest_state(grain=1))
    assert _bt_offered(state)


# --- Once per window / optionality ---------------------------------------------

def test_once_per_harvest():
    """One fire spends the use for this harvest, grain to spare or not."""
    state = _walk_to_window(_harvest_state(grain=3))
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert not _bt_offered(state)
    assert legal_actions(state) == [Proceed()]
    assert state.players[0].card_state.get(CARD_ID, 0) == 2  # fired exactly once


def test_decline_via_proceed_spends_nothing():
    """Declining pays no grain, banks no points, and — "If you do" — gives the
    opponent no food."""
    state = _walk_to_window(_harvest_state(grain=2))
    opp_food_before = state.players[1].resources.food
    state = step(state, Proceed())
    assert state.players[0].resources.grain == 2
    assert state.players[0].card_state.get(CARD_ID, 0) == 0
    assert state.players[1].resources.food == opp_food_before


def test_not_offered_during_feeding_or_later():
    """Declined at window #6, the card is never re-offered later in the harvest
    (it is not a feeding-seam conversion)."""
    state = _walk_to_window(_harvest_state(grain=2))
    state = step(state, Proceed())
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        assert not _bt_offered(state)
        state = step(state, legal_actions(state)[0])
    assert state.players[0].resources.grain == 2
    assert state.players[0].card_state.get(CARD_ID, 0) == 0


# --- Bank accumulation & scoring ------------------------------------------------

def test_bank_accumulates_across_harvests():
    state = _walk_to_window(_harvest_state(grain=1))
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].card_state.get(CARD_ID, 0) == 2

    # A later harvest, bank carried forward: firing again banks 2 more.
    banked = state.players[0].card_state.get(CARD_ID, 0)
    fresh = _harvest_state(grain=1)
    p = fresh.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, banked))
    fresh = dataclasses.replace(
        fresh, players=tuple(p if i == 0 else fresh.players[i] for i in range(2)))
    fresh = _walk_to_window(fresh)
    assert _bt_offered(fresh)
    fresh = step(fresh, FireTrigger(card_id=CARD_ID))
    assert fresh.players[0].card_state.get(CARD_ID, 0) == 4


def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    assert score_fn(state, 0) == 0                          # no bank -> 0
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 4))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    assert score_fn(state, 0) == 4
    assert score_fn(state, 1) == 0                          # opponent: no bank
