"""Tests for Bed in the Grain Field (minor improvement, C24).

Card text (verbatim): "At the start of the next harvest, you get a "Family
Growth" action if you have room for the newborn."
Clarification: "Only works in the next harvest after it is played. The newborn
must be fed."
Free, 0 VPs, prerequisite 1 Grain Field, kept.

An optional trigger (granted sub-actions are optional even when worded as
commands) on harvest window #2 ``start_of_harvest``, firing ONLY in the first
harvest at-or-after the recorded play round (the round key can match one
harvest, so the card is one-shot by construction — a decline consumes the
opportunity). Firing pushes the card-granted family-growth primitive
(``PendingFamilyGrowth(place_on_space=False)``, Group A1 ruling 2026-07-03: the
newborn occupies NO action space). Eligibility gates on the printed room
condition (people_total < 5 and a free room).

These tests drive REAL harvests through the walk, and the on-play through a
real ``PendingPlayMinor`` flow (the play records the round in CardStore).
"""
from __future__ import annotations

import agricola.cards.bed_in_the_grain_field  # noqa: F401  (register the card)

from agricola.actions import (
    CommitFamilyGrowth,
    CommitPlayMinor,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFamilyGrowth,
    PendingHarvestFeed,
    PendingHarvestWindow,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import (
    with_grid,
    with_pending_stack,
    with_phase,
    with_resources,
    with_sown_fields,
)

CARD_ID = "bed_in_the_grain_field"
WINDOW_ID = "start_of_harvest"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_played(state, idx, play_round):
    """Put the card in idx's tableau with the play round recorded — the state
    ``_on_play`` leaves behind."""
    p = state.players[idx]
    return _edit_player(
        state, idx,
        minor_improvements=p.minor_improvements | {CARD_ID},
        card_state=p.card_state.set(CARD_ID, play_round),
    )


def _harvest_state(*, round_number=4, play_round=2, owner=0, food=10,
                   extra_room=True, own=True):
    """A HARVEST_FIELD-phase state at ``round_number``, P0 the starting player,
    the card played in ``play_round``. Setup gives 2 people in 2 rooms — the
    room gate FAILS by default — so ``extra_room`` adds a third ROOM."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = fast_replace(state, starting_player=0, round_number=round_number)
    if own:
        state = _own_played(state, owner, play_round)
    if extra_room:
        state = with_grid(state, owner, {(0, 0): Cell(cell_type=CellType.ROOM)})
    for idx in (0, 1):
        state = with_resources(state, idx, food=food)
    return state


def _walk_to_window(state, player_idx=0):
    """Advance until the player's start_of_harvest window frame is on top,
    stepping the first legal action everywhere else (never firing OUR card).
    Returns (state, frame_seen, fire_seen_during_feeding)."""
    fire_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                fire_in_feeding = True
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == WINDOW_ID and top.player_idx == player_idx):
            return state, True, fire_in_feeding
        acts = legal_actions(state)
        picked = next((a for a in acts
                       if not (isinstance(a, FireTrigger) and a.card_id == CARD_ID)),
                      acts[0])
        state = step(state, picked)
    return state, False, fire_in_feeding


def _finish_harvest(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        acts = legal_actions(state)
        picked = next((a for a in acts
                       if not (isinstance(a, FireTrigger) and a.card_id == CARD_ID)),
                      acts[0])
        state = step(state, picked)
    return state


# --- Registration / spec (vs the JSON: free, no VPs, prereq 1 Grain Field) ---

def test_registered_minor_spec_and_window_trigger():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                       # cost: null -> free
    assert spec.vps == 0                             # vps: null -> 0
    assert spec.passing_left is False                # kept
    assert spec.prereq is not None                   # "1 Grain Field"
    assert CARD_ID in HARVEST_WINDOW_CARDS.get(WINDOW_ID, set())
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get(WINDOW_ID, ()))


def test_prereq_one_grain_field():
    """'1 Grain Field' = a FIELD cell currently holding grain (the settled
    reading — Straw-Thatched Roof / Sleeping Corner). An empty or veg field
    does not qualify."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)            # no fields at all
    grain = with_sown_fields(state, 0, grain_fields=((0, 1),))
    assert prereq_met(spec, grain, 0)
    veg = with_sown_fields(state, 0, veg_fields=((0, 1),))
    assert not prereq_met(spec, veg, 0)


def test_prereq_met_only_via_grain_card_field():
    """Ruling 45 (2026-07-12): a grain-holding card-field IS a grain field, so
    it alone satisfies "1 Grain Field" with zero grid fields (the old
    grid-only read failed this). A veg-holding card-field is not a grain
    field and does not."""
    from agricola.cards.card_fields import stacks_to_store
    spec = MINORS[CARD_ID]

    def _with_card_field(cid, stacks):
        state = setup(seed=0)
        p = state.players[0]
        p = fast_replace(
            p,
            minor_improvements=p.minor_improvements | {cid},
            card_state=stacks_to_store(p.card_state, cid, stacks),
        )
        return fast_replace(state, players=tuple(
            p if i == 0 else state.players[i] for i in range(2)))

    grain_cf = _with_card_field("artichoke_field", ((3, 0, 0, 0),))
    assert prereq_met(spec, grain_cf, 0)
    veg_cf = _with_card_field("beanfield", ((0, 2, 0, 0),))
    assert not prereq_met(spec, veg_cf, 0)


# --- On-play through a real play-minor flow ----------------------------------

def _at_play_minor_frame(with_prereq=True):
    """A CARDS-mode state at a PendingPlayMinor host, the current player holding
    the card in hand (and a grain field for the prerequisite)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    if with_prereq:
        cs = with_sown_fields(cs, cp, grain_fields=((0, 1),))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def test_real_play_records_the_round():
    cs, cp = _at_play_minor_frame()
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert len(plays) == 1                           # free -> one payment option
    cs = step(cs, plays[0])
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors
    # The on-play recorded the play round (round 1 -> next harvest is round 4).
    assert cs.players[cp].card_state.get(CARD_ID) == 1


def test_prereq_gates_the_play():
    cs, _cp = _at_play_minor_frame(with_prereq=False)
    assert not any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                   for a in legal_actions(cs))


# --- The growth at the start of the NEXT harvest ------------------------------

def test_growth_fires_at_start_of_next_harvest():
    state = _harvest_state(round_number=4, play_round=2)
    before_workers = tuple(sp.workers for sp in state.board.action_spaces)

    state, seen, _ = _walk_to_window(state)
    assert seen
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts and Proceed() in acts

    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth)
    assert top.place_on_space is False
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert top.player_idx == 0

    assert legal_actions(state) == [CommitFamilyGrowth()]
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == 3
    assert state.players[0].newborns == 1
    # The newborn occupies NO action space (Group A1 ruling 2026-07-03).
    assert tuple(sp.workers for sp in state.board.action_spaces) == before_workers

    state = step(state, Stop())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == WINDOW_ID
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())

    # "The newborn must be fed": 10 - 5 (2 adults x2 + newborn x1) = 5.
    # (The synthetic round-4 state has only round 1's stage card revealed, so
    # PREPARATION completes straight into WORK — assert the harvest is over.)
    state = _finish_harvest(state)
    assert state.phase not in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                               Phase.HARVEST_BREED)
    assert state.players[0].resources.food == 5
    assert state.players[1].people_total == 2


def test_played_on_a_harvest_round_works_in_that_rounds_harvest():
    """A WORK-phase play precedes its own round's harvest, so play_round == 4
    fires in round 4's harvest — the next to start."""
    state = _harvest_state(round_number=4, play_round=4)
    state, seen, _ = _walk_to_window(state)
    assert seen


# --- "Only works in the NEXT harvest" ----------------------------------------

def test_silent_in_a_later_harvest():
    """Played round 2: the next harvest was round 4 — round 7's is too late."""
    state = _harvest_state(round_number=7, play_round=2)
    state, seen, _ = _walk_to_window(state)
    assert not seen
    assert state.players[0].people_total == 2


def test_decline_consumes_the_one_shot():
    """Declining in the next harvest spends the opportunity: the card never
    fires in any later harvest."""
    state = _harvest_state(round_number=4, play_round=2)
    state, seen, _ = _walk_to_window(state)
    assert seen
    state = step(state, Proceed())                   # decline
    state = _finish_harvest(state)
    assert state.phase not in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                               Phase.HARVEST_BREED)
    assert state.players[0].people_total == 2

    # The round-7 harvest, same tableau/CardStore: never offered again.
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = fast_replace(state, round_number=7, harvest_cursor=None)
    for idx in (0, 1):
        state = with_resources(state, idx, food=10)
    state, seen, _ = _walk_to_window(state)
    assert not seen
    assert state.players[0].people_total == 2


# --- Eligibility boundaries ---------------------------------------------------

def test_not_offered_without_room_for_the_newborn():
    state = _harvest_state(extra_room=False)
    state, seen, _ = _walk_to_window(state)
    assert not seen


def test_not_offered_at_the_family_cap():
    state = _harvest_state(food=20)
    state = with_grid(state, 0, {(0, c): Cell(cell_type=CellType.ROOM)
                                 for c in range(5)})   # 7 rooms total
    state = _edit_player(state, 0, people_total=5, workers_in_supply=0)
    state, seen, _ = _walk_to_window(state)
    assert not seen


def test_not_offered_to_a_non_owner():
    state = _harvest_state(own=False)
    state, seen, _ = _walk_to_window(state)
    assert not seen


def test_never_surfaces_during_feeding():
    state = _harvest_state(round_number=4, play_round=2)
    state, seen, fire_in_feeding = _walk_to_window(state)
    assert seen
    state = step(state, Proceed())
    # Finish the harvest scanning the FEED frames for a stray offer.
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                fire_in_feeding = True
        state = step(state, legal_actions(state)[0])
    assert not fire_in_feeding
