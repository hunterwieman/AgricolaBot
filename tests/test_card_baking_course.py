import agricola.cards.baking_course  # noqa: F401  (registers the card; not in __init__ yet)
# Tests for Baking Course (minor improvement, D64; Dulcinaria Expansion).
#
# Card text (verbatim): "At the end of each round that does not end with a
# harvest, you can take a "Bake Bread" action. "Bake Bread" action: Grain →
# 2 Food" Free; prerequisite 1 Occupation; no printed VP.
#
# USER RULING 51 (2026-07-12): the second sentence is a STANDING baking source
# — an unlimited grain→2-food rate during ALL Bake Bread actions, "just like
# the fireplace does" (the BAKING_SPEC_EXTENSIONS seam) — not a rate scoped to
# the end-of-round grant. The grant itself is an optional end_of_round bake on
# non-harvest rounds (ruling 49's rung, 2026-07-12).
#
# Covers: registration (free, min_occupations=1, the end_of_round trigger, the
# two legality-seam registrations); the GLOBAL rate through a real Grain
# Utilization bake for an oven-less owner (reachability + 2/grain, uncapped);
# composition with a better oven rate (Clay Oven first, the rest at 2 — the
# greedy allocator); the end-of-round grant through the real ladder walk
# (fire → PendingBakeBread → CommitBake at 2/grain → Stop → Proceed → round
# completes); once per round; suppression on harvest rounds; no offer with 0
# grain; decline via Proceed; and the unowned negatives (no rate, no
# reachability, no trigger).
#
# Drivers mirror tests/test_card_sculpture_course.py (the end_of_round
# precedent): a drained WORK state advanced through the real round-end walk.

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.baking_course import (
    CARD_ID,
    WINDOW_ID,
    _baking_spec,
    _can_bake_bread_extension,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import (
    BAKE_BREAD_ELIGIBILITY_EXTENSIONS,
    BAKING_SPEC_EXTENSIONS,
    _can_bake_bread,
    baking_specs_for_player,
    legal_actions,
)
from agricola.pending import PendingBakeBread, PendingHarvestWindow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_majors,
    with_resources,
    with_space,
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx=0):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _drained_work_state(*, round_number=1, owned=True, owner=0, **resources):
    """A WORK state with every person placed (people_home=0), `owner`
    (optionally) owning Baking Course, and their resources set exactly to
    `resources` (the other player gets ample food so a harvest round's
    feeding never begs)."""
    state = setup(seed=0)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    if owned:
        state = _own(state, owner)
    state = _edit_player(state, owner, resources=Resources(**resources))
    state = _edit_player(state, 1 - owner, resources=Resources(food=99))
    return state


def _at_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestWindow)
            and top.window_id == WINDOW_ID)


def _bake_amounts(state):
    """Sorted CommitBake grain amounts currently legal."""
    return sorted(a.grain for a in legal_actions(state)
                  if isinstance(a, CommitBake))


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()          # free
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 1    # prerequisite: 1 occupation
    assert spec.max_occupations is None and spec.prereq is None
    assert spec.vps == 0                # no printed VP
    assert not spec.passing_left

    entry = CARDS[CARD_ID]
    assert entry.event == WINDOW_ID == "end_of_round"
    assert not entry.mandatory          # optional ("you can")

    # Both legality-seam registrations are live (ruling 51's standing source).
    assert _baking_spec in BAKING_SPEC_EXTENSIONS
    assert _can_bake_bread_extension in BAKE_BREAD_ELIGIBILITY_EXTENSIONS


# --- The GLOBAL rate: a real Grain Utilization bake, oven-less ---------------

def test_ovenless_owner_bakes_at_grain_utilization():
    """Ruling 51: the card is a standing baking source during ALL Bake Bread
    actions — an owner with grain but NO major improvement can choose the
    bake at Grain Utilization and converts at 2/grain, uncapped."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _own(s, 0)
    s = with_resources(s, 0, grain=3)
    s = with_space(s, "grain_utilization", revealed=True)

    place = PlaceWorker(space="grain_utilization")
    assert place in legal_actions(s)
    s = step(s, place)
    # Reachability: the bake branch is choosable with no oven owned.
    choose = ChooseSubAction(name="bake_bread")
    assert choose in legal_actions(s)
    s = step(s, choose)
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    # Uncapped: every amount up to the full grain supply is offered.
    assert _bake_amounts(s) == [1, 2, 3]

    s = step(s, CommitBake(grain=3))
    r = s.players[0].resources
    assert r.grain == 0 and r.food == 6         # 3 grain -> 6 food (2/grain)


def test_composes_with_better_oven_rate():
    """With Clay Oven (cap 1, rate 5) also owned, the greedy allocator spends
    the oven's grain first and the rest at this card's rate 2 — and the
    card's uncapped source lifts the per-action cap to the grain supply."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _own(s, 0)
    s = with_majors(s, owner_by_idx={5: 0})     # Clay Oven
    s = with_resources(s, 0, grain=3)
    s = push(s, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization"))

    # Clay Oven alone caps the action at 1 grain; the card lifts it to 3.
    assert _bake_amounts(s) == [1, 2, 3]

    one = step(s, CommitBake(grain=1))
    assert one.players[0].resources.food == 5   # the oven (rate 5) fires first

    three = step(s, CommitBake(grain=3))
    r = three.players[0].resources
    assert r.food == 9 and r.grain == 0         # 5 (oven) + 2 + 2 (this card)


# --- The end-of-round grant through the real ladder walk ---------------------

def test_grant_fires_at_end_of_round():
    state = _drained_work_state(grain=2)
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == WINDOW_ID and top.player_idx == 0
    fire = FireTrigger(card_id=CARD_ID)
    assert fire in legal_actions(state)

    state = step(state, fire)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBakeBread)
    assert top.initiated_by_id == "card:baking_course"
    assert top.player_idx == 0
    assert _bake_amounts(state) == [1, 2]       # the card's own source

    state = step(state, CommitBake(grain=2))
    r = state.players[0].resources
    assert r.grain == 0 and r.food == 4         # 2 grain -> 4 food

    # After-phase: Stop pops back to the window host; the fire is resolved.
    assert any(isinstance(a, Stop) for a in legal_actions(state))
    state = step(state, Stop())
    assert _at_window(state)
    assert CARD_ID in state.pending_stack[-1].triggers_resolved
    # Once per round: no second bake this round — only the exit remains.
    assert [type(a) for a in legal_actions(state)] == [Proceed]

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION     # round 1: no harvest
    assert state.round_end_cursor is None


def test_decline_via_proceed():
    state = _drained_work_state(grain=2, food=1)
    state = _advance_until_decision(state)
    assert _at_window(state)
    assert any(isinstance(a, Proceed) for a in legal_actions(state))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert state.players[0].resources == Resources(grain=2, food=1)


# --- The printed harvest-round condition -------------------------------------

def test_suppressed_on_harvest_rounds():
    # Round 4 ends with a harvest: the ladder still runs (before the harvest),
    # but the card's eligibility gate withholds the trigger — the first pause
    # is inside the harvest, never an end_of_round window.
    state = _drained_work_state(round_number=4, grain=3, food=9)
    state = _advance_until_decision(state)
    assert not _at_window(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                           Phase.HARVEST_BREED)
    assert state.players[0].resources.grain == 3    # nothing baked


# --- No grain, no offer -------------------------------------------------------

def test_not_offered_with_zero_grain():
    # No grain on hand: the trigger is ineligible, so the ladder pushes no
    # frame at all and the round completes unpaused.
    state = _drained_work_state(food=7, wood=2)
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert state.players[0].resources == Resources(food=7, wood=2)


# --- Unowned negatives ---------------------------------------------------------

def test_unowned_no_rate_no_reachability():
    s = setup(seed=0)
    s = with_resources(s, 0, grain=3)
    # No baking source and no Bake Bread reachability without the card.
    assert baking_specs_for_player(s, 0) == []
    assert not _can_bake_bread(s, s.players[0])


def test_unowned_no_trigger():
    state = _drained_work_state(owned=False, grain=3)
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION     # no pause anywhere
    assert state.players[0].resources.grain == 3
