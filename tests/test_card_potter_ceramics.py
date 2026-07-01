"""Tests for Potter Ceramics (minor D66): "Each time before you take a
'Bake Bread' action, you can exchange 1 clay for 1 grain." Clarification:
"You must bake if you make this exchange." Free, no prerequisite, no printed
VPs, not a passing card.

Modeled as an OPTIONAL, declinable `before_bake_bread` FireTrigger ("you can")
that swaps 1 clay for 1 grain, plus a `register_bake_bread_extension` so a
Potter+baker owner can take a Bake Bread action even at 0 grain (the swap then
supplies the grain). The trigger machinery has long existed (this card was the
original worked example for it); this test file focuses on the playable-minor
wiring (`register_minor`) added to make the card dealable, while re-covering the
real-flow effect, the eligibility boundaries, the optionality (no SkipTrigger —
declined by committing the bake directly), and the per-action `triggers_resolved`
scoping that gives "each time" its meaning.

The sibling `tests/test_potter_ceramics.py` is the original trigger-machinery
suite (prefab states); this file additionally asserts the card registers as a
real minor and re-exercises the headline flows.
"""
from __future__ import annotations

import agricola.cards.potter_ceramics  # noqa: F401

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import _can_bake_bread, legal_actions
from agricola.pending import PendingBakeBread, PendingGrainUtilization
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_majors,
    with_minors,
    with_pending_stack,
    with_resources,
)
from tests.test_utils import run_actions

CARD_ID = "potter_ceramics"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _potter_setup(*, grain=0, clay=1, with_fireplace=True, with_card=True,
                  seed=0, current_player=0):
    """Prefab state where the active player optionally owns Potter Ceramics
    with the given clay/grain and (optionally) a Fireplace baker."""
    state = setup(seed=seed)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, grain=grain, clay=clay)
    if with_card:
        state = with_minors(state, current_player, frozenset({CARD_ID}))
    if with_fireplace:
        state = with_majors(state, owner_by_idx={0: current_player})
    return state


def _to_before_bake(state):
    """Place at Grain Utilization and choose bake_bread → PendingBakeBread."""
    state = step(state, PlaceWorker(space="grain_utilization"))
    state = step(state, ChooseSubAction(name="bake_bread"))
    return state


# ---------------------------------------------------------------------------
# Registration — the gap this card needed closed
# ---------------------------------------------------------------------------

def test_potter_registered_as_minor():
    """Potter Ceramics is now a dealable/playable minor with free, no-prereq,
    non-passing, 0-VP defaults (the card data has cost/prereq/vps/passing null)."""
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()           # free
    assert spec.cost_fn is None
    assert spec.prereq is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.passing_left is False
    assert spec.vps == 0


def test_potter_trigger_is_optional_not_auto():
    """The effect is a declinable FireTrigger on before_bake_bread (NOT a
    mandatory register_auto), because the card says 'you can' exchange."""
    before = {e.card_id for e in TRIGGERS.get("before_bake_bread", [])}
    assert CARD_ID in before
    entry = CARDS[CARD_ID]
    assert entry.event == "before_bake_bread"
    assert entry.mandatory is False
    # Not registered as an automatic (mandatory) effect.
    auto = {e.card_id for e in AUTO_EFFECTS.get("before_bake_bread", [])}
    assert CARD_ID not in auto


# ---------------------------------------------------------------------------
# The bake-bread legality extension (0-grain bake enabled by the swap)
# ---------------------------------------------------------------------------

def test_can_bake_bread_zero_grain_with_clay():
    """0 grain + 1 clay + Potter + baker → bakeable via the extension."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=True)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is True


def test_can_bake_bread_zero_grain_no_clay():
    """0 grain + 0 clay → not bakeable (the swap needs a clay to spend)."""
    state = _potter_setup(grain=0, clay=0, with_fireplace=True)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is False


def test_can_bake_bread_requires_baker():
    """No baking improvement → not bakeable even with Potter and clay."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=False)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is False


def test_can_bake_bread_extension_needs_ownership():
    """Without Potter played, the 0-grain bake is not enabled."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=True, with_card=False)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is False


# ---------------------------------------------------------------------------
# Real-flow effect: fire the swap, then bake the grain it produced
# ---------------------------------------------------------------------------

def test_real_flow_swap_then_bake_at_zero_grain():
    """0 grain, 1 clay, Potter, Fireplace: only FireTrigger is legal at the bake,
    firing it swaps clay→grain, and that grain bakes to +2 food."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=True)
    ap = state.current_player
    pre_food = state.players[ap].resources.food

    state = _to_before_bake(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBakeBread)
    assert top.triggers_resolved == frozenset()

    # 0 grain → no CommitBake; only the swap is legal.
    assert legal_actions(state) == [FireTrigger(card_id=CARD_ID)]

    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[ap].resources.clay == 0
    assert state.players[ap].resources.grain == 1
    assert state.pending_stack[-1].triggers_resolved == frozenset({CARD_ID})

    # Now exactly one commit (the swap already fired).
    assert legal_actions(state) == [CommitBake(grain=1)]
    state = step(state, CommitBake(grain=1))
    assert state.players[ap].resources.grain == 0
    assert state.players[ap].resources.food == pre_food + 2


def test_does_not_fire_when_not_owned():
    """No Potter played → no swap is offered at a Bake Bread action."""
    state = _potter_setup(grain=1, clay=1, with_fireplace=True, with_card=False)
    state = _to_before_bake(state)
    assert isinstance(state.pending_stack[-1], PendingBakeBread)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(state)


# ---------------------------------------------------------------------------
# Optionality — declined by committing the bake directly (no SkipTrigger)
# ---------------------------------------------------------------------------

def test_optional_declined_by_committing():
    """1 grain + 1 clay: both Fire and Commit are legal; declining = commit, and
    the clay is left untouched."""
    state = _potter_setup(grain=1, clay=1, with_fireplace=True)
    ap = state.current_player
    pre_clay = state.players[ap].resources.clay
    pre_food = state.players[ap].resources.food

    state = _to_before_bake(state)
    actions = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in actions
    assert CommitBake(grain=1) in actions

    state = step(state, CommitBake(grain=1))   # decline the swap, bake the grain
    assert state.players[ap].resources.clay == pre_clay
    assert state.players[ap].resources.food == pre_food + 2


# ---------------------------------------------------------------------------
# Scoping — at most once per action, re-eligible on a fresh action ("each time")
# ---------------------------------------------------------------------------

def test_fires_at_most_once_per_action():
    """With 2 clay, the swap is offered only once per Bake Bread action."""
    state = _potter_setup(grain=0, clay=2, with_fireplace=True)
    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        FireTrigger(card_id=CARD_ID),
    ])
    actions = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in actions   # no second swap
    assert actions == [CommitBake(grain=1)]


def test_re_eligible_in_fresh_pending_bake_bread():
    """A new PendingBakeBread has empty triggers_resolved → the swap is offered
    again ('each time' = before each action, scoped per frame)."""
    state = _potter_setup(grain=0, clay=2, with_fireplace=True)
    ap = state.current_player

    # Run a full Grain Utilization bake (swap once, bake, end the turn).
    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        FireTrigger(card_id=CARD_ID),
        CommitBake(grain=1),
        Stop(),      # pop PendingBakeBread's after-phase
        Proceed(),   # flip the parent to its after-phase
        Stop(),      # pop the parent — turn ends
    ])
    assert state.players[ap].resources.clay == 1
    assert state.players[ap].resources.grain == 0
    assert state.pending_stack == ()

    # Construct a fresh PendingBakeBread directly — the swap re-becomes eligible.
    state = with_current_player(state, ap)
    state = with_pending_stack(state, [
        PendingGrainUtilization(player_idx=ap, initiated_by_id="space:grain_utilization"),
        PendingBakeBread(player_idx=ap, initiated_by_id="grain_utilization"),
    ])
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
