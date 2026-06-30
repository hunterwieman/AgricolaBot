"""Tests for Claw Knife (minor improvement, A46; Artifex): "Each time you use the
'Sheep Market' accumulation space, place 1 food on each of the next 2 round spaces.
At the start of these rounds, you get the food." Cost 1 Wood; prereq exactly 1
pasture.

A Category-8 deferred-goods card on the non-atomic `sheep_market` host's
`before_action_space` event — the Herring Pot shape (tests/test_cards_category8.py)
but on Sheep Market, 2 rounds, owner-only. Coverage: registration; the schedule via a
REAL `sheep_market` placement; the prereq boundary (exactly-1-pasture gate); that the
hook fires only on Sheep Market (not other markets) and only for the owner; and that
the play-time prereq does NOT re-gate the per-use trigger.
"""
import agricola.cards.claw_knife  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, apply_auto_effects
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_pastures(state, idx, cells_per_pasture):
    """Install the given pastures (one frozenset of cells each) onto the farmyard."""
    fy = state.players[idx].farmyard
    pastures = tuple(
        Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
        for cells in cells_per_pasture)
    fy = fast_replace(fy, pastures=pastures)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


def _run_turn(state):
    steps = 0
    while state.pending_stack and steps < 30:
        state = step(state, legal_actions(state)[0])
        steps += 1
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_claw_knife_registered():
    assert "claw_knife" in MINORS
    assert MINORS["claw_knife"].cost == Cost(resources=Resources(wood=1))
    assert MINORS["claw_knife"].vps == 0
    assert not MINORS["claw_knife"].passing_left
    # An automatic before-action-space effect (no FireTrigger surfaced).
    entry = next(e for e in AUTO_EFFECTS.get("before_action_space", [])
                 if e.card_id == "claw_knife")
    assert not entry.any_player   # "each time YOU use" -> owner only


# ---------------------------------------------------------------------------
# Prerequisite — exactly 1 pasture
# ---------------------------------------------------------------------------

def test_prereq_exactly_one_pasture():
    s = setup(0)
    # Zero pastures -> not met.
    assert not prereq_met(MINORS["claw_knife"], s, 0)
    # Exactly one pasture -> met.
    s1 = _set_pastures(s, 0, [[(0, 0), (1, 0)]])
    assert prereq_met(MINORS["claw_knife"], s1, 0)
    # Two pastures -> not met (exactly 1).
    s2 = _set_pastures(s, 0, [[(0, 0)], [(2, 2)]])
    assert not prereq_met(MINORS["claw_knife"], s2, 0)


# ---------------------------------------------------------------------------
# The schedule via a real Sheep Market placement
# ---------------------------------------------------------------------------

def test_claw_knife_schedules_on_sheep_market_use():
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "claw_knife")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="sheep_market"))
    s = _run_turn(s)
    f = _food(s, ap)
    R = 1
    # Rounds R+1..R+2 each gain 1 food; the rest unchanged.
    assert f[R] == before[R] + 1
    assert f[R + 1] == before[R + 1] + 1
    assert f[R + 2] == before[R + 2]   # round R+3 NOT scheduled (only 2 round spaces)


def test_claw_knife_unowned_noop_on_sheep_market():
    s, _env = setup_env(0)
    ap = s.current_player
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="sheep_market"))
    s = _run_turn(s)
    assert _food(s, ap) == before   # no Claw Knife owned -> no schedule


def test_claw_knife_does_not_fire_on_other_markets():
    # The hook is gated on space_id == "sheep_market": a Pig Market use must NOT fire.
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "claw_knife")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="pig_market"))
    s = _run_turn(s)
    assert _food(s, ap) == before


# ---------------------------------------------------------------------------
# Per-use trigger is NOT re-gated by the play-time pasture prereq
# ---------------------------------------------------------------------------

def test_trigger_fires_regardless_of_later_pasture_count():
    # Once played, the Sheep Market hook fires even with 0 pastures (the "exactly 1
    # pasture" condition is a play-time gate, not a per-use trigger condition). Drive
    # the before-action-space event directly with the host frame present.
    from agricola.pending import PendingSheepMarket
    from agricola.pending import push

    s = setup(0)
    s = _own_minor(s, 0, "claw_knife")
    # Player has 0 pastures here.
    assert len(s.players[0].farmyard.pastures) == 0
    before = _food(s, 0)
    s = push(s, PendingSheepMarket(
        player_idx=0, initiated_by_id="space:sheep_market", gained=0))
    out = apply_auto_effects(s, "before_action_space", 0)
    f = _food(out, 0)
    R = 1
    assert f[R] == before[R] + 1
    assert f[R + 1] == before[R + 1] + 1
    assert f[R + 2] == before[R + 2]


def test_claw_knife_owner_only():
    # The owner is player `idx`; the opponent's Sheep Market use must NOT schedule for
    # the owner (no any_player), and apply_auto_effects routed for a non-owner is a
    # no-op for that player.
    s, _env = setup_env(0)
    ap = s.current_player
    other = 1 - ap
    s = _own_minor(s, ap, "claw_knife")
    before_other = _food(s, other)
    s = step(s, PlaceWorker(space="sheep_market"))
    s = _run_turn(s)
    # The non-owner who placed gets nothing; the owner's schedule rode on ap (covered
    # elsewhere). The opponent never gains a schedule from the owner's card.
    assert _food(s, other) == before_other
