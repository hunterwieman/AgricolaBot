"""Tests for Chophouse (minor improvement, B43; Bubulcus): "Each time you use the
'Grain/Vegetable Seed' action space, place 1 food on each of the next 3/2 round
spaces. At the start of these rounds, you get the food." Cost 2 Wood / 2 Clay;
no prereq; 1 VP; not passing.

A Category-8 deferred-goods card on the TWO atomic seed-space hosts'
`before_action_space` event — the Herring Pot / Claw Knife shape but with a
per-space schedule length (grain_seeds -> 3 rounds, vegetable_seeds -> 2). Coverage:
registration; the schedule via REAL `grain_seeds` and `vegetable_seeds` placements
(each with the correct N); the space's own grain/veg pickup is unaffected; the hook
fires only on the two seed spaces (not other spaces) and only for the owner; that the
scheduled food is actually collected at the start of the target rounds; and that the
effect is automatic (no FireTrigger surfaced).
"""
import agricola.cards.chophouse  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
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

def test_chophouse_registered():
    assert "chophouse" in MINORS
    spec = MINORS["chophouse"]
    assert spec.cost == Cost(resources=Resources(wood=2, clay=2))
    assert spec.vps == 1
    assert not spec.passing_left
    assert spec.prereq is None
    # An automatic before-action-space effect (no FireTrigger surfaced).
    entry = next(e for e in AUTO_EFFECTS.get("before_action_space", [])
                 if e.card_id == "chophouse")
    assert not entry.any_player   # "each time YOU use" -> owner only


# ---------------------------------------------------------------------------
# The schedule via real seed-space placements (per-space N)
# ---------------------------------------------------------------------------

def test_chophouse_schedules_3_on_grain_seeds():
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "chophouse")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = _run_turn(s)
    f = _food(s, ap)
    R = 1
    # Rounds R+1..R+3 each gain 1 food; round R+4 NOT scheduled.
    assert f[R] == before[R] + 1
    assert f[R + 1] == before[R + 1] + 1
    assert f[R + 2] == before[R + 2] + 1
    assert f[R + 3] == before[R + 3]
    # The space's own grain pickup still happens (the schedule is independent).
    assert s.players[ap].resources.grain == 1


def test_chophouse_schedules_2_on_vegetable_seeds():
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "chophouse")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="vegetable_seeds"))
    s = _run_turn(s)
    f = _food(s, ap)
    R = 1
    # Rounds R+1..R+2 each gain 1 food; round R+3 NOT scheduled (only 2 round spaces).
    assert f[R] == before[R] + 1
    assert f[R + 1] == before[R + 1] + 1
    assert f[R + 2] == before[R + 2]
    # The space's own veg pickup still happens.
    assert s.players[ap].resources.veg == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_chophouse_unowned_noop_on_grain_seeds():
    s, _env = setup_env(0)
    ap = s.current_player
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = _run_turn(s)
    assert _food(s, ap) == before   # no Chophouse owned -> no schedule


def test_chophouse_does_not_fire_on_other_spaces():
    # The hook is gated on the two seed spaces: a forest use must NOT fire.
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "chophouse")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="forest"))
    s = _run_turn(s)
    assert _food(s, ap) == before


def test_chophouse_owner_only():
    # No any_player: when the owner places (and is the only owner), nothing schedules
    # for the opponent.
    s, _env = setup_env(0)
    ap = s.current_player
    other = 1 - ap
    s = _own_minor(s, ap, "chophouse")
    before_other = _food(s, other)
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = _run_turn(s)
    assert _food(s, other) == before_other


# ---------------------------------------------------------------------------
# The scheduled food is actually collected at the start of the target rounds
# ---------------------------------------------------------------------------

def test_chophouse_food_collected_at_round_start():
    # The scheduled food rides on `future_resources`, which the engine pays out at the
    # start of the scheduled round. Use Grain Seeds in round 1 (schedules 1 food onto
    # rounds 2/3/4), then drive the PREPARATION→WORK transition into round 2 via the
    # engine's own `_complete_preparation` and confirm the food is credited.
    from agricola.constants import Phase
    from agricola.engine import _complete_preparation

    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "chophouse")
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = _run_turn(s)
    assert _food(s, ap)[1] >= 1   # round-2 slot scheduled

    food_before = s.players[ap].resources.food
    # Enter round 2's start.
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    s = _complete_preparation(s)
    assert s.round_number == 2
    # The scheduled 1 food for round 2 was collected; the slot is now consumed.
    assert s.players[ap].resources.food == food_before + 1
    assert _food(s, ap)[1] == 0
