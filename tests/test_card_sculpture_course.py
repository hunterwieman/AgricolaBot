import agricola.cards.sculpture_course  # noqa: F401
# Tests for Sculpture Course (minor improvement, B53; Bubulcus Expansion).
#
# Card text (verbatim): "At the end of each round that does not end with a
# harvest, you can use this card to exchange your choice of 1 wood for 2 food,
# or 1 stone for 4 food." Cost: 1 Grain. No prerequisite. No printed VP.
#
# TIMING: the round-end ladder's "end_of_round" rung (ruling 49, 2026-07-12) —
# an optional play-variant trigger surfaced on the per-player
# PendingHarvestWindow host the ladder walk pushes at the round's last instant.
# Two variants: "wood" (1 wood -> 2 food) and "stone" (1 stone -> 4 food).
# Suppressed on harvest rounds (the printed condition, as eligibility — the
# ladder itself runs on harvest rounds too). Once per round via the frame's
# triggers_resolved.
#
# Drivers mirror tests/test_round_end_ladder.py: a drained WORK state (all
# people placed) advanced through the real ladder walk to the end_of_round
# frame, then fire / decline around it.

from agricola.actions import FireTrigger, Proceed
from agricola.cards.display import variant_label
from agricola.cards.sculpture_course import CARD_ID, WINDOW_ID
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _drained_work_state(*, round_number=1, owned=True, owner=0, **resources):
    """A WORK state with every person placed (people_home=0), `owner`
    (optionally) owning Sculpture Course, and their resources set exactly to
    `resources` (the other player gets ample food so a harvest round's feeding
    never begs)."""
    state = setup(seed=0)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    if owned:
        p = state.players[owner]
        state = _edit_player(state, owner,
                             minor_improvements=p.minor_improvements | {CARD_ID})
    state = _edit_player(state, owner, resources=Resources(**resources))
    state = _edit_player(state, 1 - owner, resources=Resources(food=99))
    return state


def _card_variants(state):
    """Sorted Sculpture Course FireTrigger variants currently legal."""
    return sorted(a.variant for a in legal_actions(state)
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


def _at_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestWindow)
            and top.window_id == WINDOW_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(grain=1))
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.prereq is None          # no prerequisite
    assert spec.vps == 0                # no printed VP
    assert not spec.passing_left

    entry = CARDS[CARD_ID]
    assert entry.event == WINDOW_ID == "end_of_round"
    assert not entry.mandatory          # optional ("you can")
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


# --- The exchange through the real round-end walk ---------------------------

def test_wood_variant_fires_at_end_of_round():
    state = _drained_work_state(wood=3, stone=2, food=1)
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == WINDOW_ID and top.player_idx == 0
    assert _card_variants(state) == ["stone", "wood"]

    state = step(state, FireTrigger(card_id=CARD_ID, variant="wood"))
    r = state.players[0].resources
    assert r.wood == 2 and r.stone == 2 and r.food == 3   # -1 wood, +2 food

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION               # round 1: no harvest
    assert state.round_end_cursor is None


def test_stone_variant_fires_at_end_of_round():
    state = _drained_work_state(wood=1, stone=1)
    state = _advance_until_decision(state)
    assert _at_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="stone"))
    r = state.players[0].resources
    assert r.stone == 0 and r.wood == 1 and r.food == 4   # -1 stone, +4 food


def test_decline_via_proceed():
    state = _drained_work_state(wood=2, stone=2, food=5)
    state = _advance_until_decision(state)
    assert _at_window(state)
    assert any(isinstance(a, Proceed) for a in legal_actions(state))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert state.players[0].resources == Resources(wood=2, stone=2, food=5)


# --- Variant affordability gating -------------------------------------------

def test_only_affordable_variants_offered():
    # Wood only -> only the wood route.
    state = _advance_until_decision(_drained_work_state(wood=1))
    assert _at_window(state)
    assert _card_variants(state) == ["wood"]
    # Stone only -> only the stone route.
    state = _advance_until_decision(_drained_work_state(stone=1))
    assert _at_window(state)
    assert _card_variants(state) == ["stone"]


def test_no_input_no_window():
    # Neither input on hand: the trigger is ineligible, so the ladder pushes
    # no frame at all and the round completes unpaused.
    state = _advance_until_decision(_drained_work_state(food=7, grain=2))
    assert state.phase == Phase.PREPARATION
    assert state.players[0].resources == Resources(food=7, grain=2)


# --- The printed harvest-round condition ------------------------------------

def test_suppressed_on_harvest_rounds():
    # Round 4 ends with a harvest: the ladder still runs (before the harvest),
    # but the card's eligibility gate withholds the trigger — the first pause
    # is inside the harvest, never an end_of_round window.
    state = _drained_work_state(round_number=4, wood=3, stone=3, food=9)
    state = _advance_until_decision(state)
    assert not _at_window(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                           Phase.HARVEST_BREED)
    r = state.players[0].resources
    assert r.wood == 3 and r.stone == 3                   # nothing exchanged


# --- Once per round ----------------------------------------------------------

def test_once_per_round():
    state = _drained_work_state(wood=2, stone=2)
    state = _advance_until_decision(state)
    assert _at_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="wood"))
    # Still at the window frame, but the fire is marked resolved: no second
    # exchange this round — only the decline/exit remains.
    assert _at_window(state)
    assert CARD_ID in state.pending_stack[-1].triggers_resolved
    assert _card_variants(state) == []
    assert [type(a) for a in legal_actions(state)] == [Proceed]
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    r = state.players[0].resources
    assert r.wood == 1 and r.stone == 2 and r.food == 2   # exactly one fire


# --- Unowned negative ---------------------------------------------------------

def test_unowned_never_surfaces():
    state = _drained_work_state(owned=False, wood=3, stone=3)
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION               # no pause anywhere
    assert state.players[0].resources == Resources(wood=3, stone=3)


# --- The labeler --------------------------------------------------------------

def test_action_labels():
    assert variant_label(CARD_ID, "wood") == "1 wood → 2 food"
    assert variant_label(CARD_ID, "stone") == "1 stone → 4 food"
    assert variant_label(CARD_ID, "bogus") is None
