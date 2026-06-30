"""Tests for Stew (minor improvement, C45; Corbarius): "Each time you use the
'Day Laborer' action space, also place 1 food on each of the next 4 round spaces.
At the start of these rounds, you get the food." Cost 1 Clay; no prereq; 0 VP;
not passing.

A Category-8 deferred-goods card on the single atomic `day_laborer` host's
`before_action_space` event — the Chophouse / Herring Pot shape with a fixed
schedule length of 4. Coverage: registration; the schedule via a REAL `day_laborer`
placement (4 rounds); the space's own food pickup is unaffected; the hook fires only
on day_laborer (not other spaces) and only for the owner; the scheduled food is
actually collected at the start of the target rounds; and that the effect is
automatic (no FireTrigger surfaced).
"""
import agricola.cards.stew  # noqa: F401  (registers the card)

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

def test_stew_registered():
    assert "stew" in MINORS
    spec = MINORS["stew"]
    assert spec.cost == Cost(resources=Resources(clay=1))
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is None
    # An automatic before-action-space effect (no FireTrigger surfaced).
    entry = next(e for e in AUTO_EFFECTS.get("before_action_space", [])
                 if e.card_id == "stew")
    assert not entry.any_player   # "each time YOU use" -> owner only


# ---------------------------------------------------------------------------
# The schedule via a real day_laborer placement (fixed N=4)
# ---------------------------------------------------------------------------

def test_stew_schedules_4_on_day_laborer():
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "stew")
    before = _food(s, ap)
    food_before = s.players[ap].resources.food
    s = step(s, PlaceWorker(space="day_laborer"))
    s = _run_turn(s)
    f = _food(s, ap)
    R = 1
    # Rounds R+1..R+4 each gain 1 food; round R+5 NOT scheduled.
    assert f[R] == before[R] + 1
    assert f[R + 1] == before[R + 1] + 1
    assert f[R + 2] == before[R + 2] + 1
    assert f[R + 3] == before[R + 3] + 1
    assert f[R + 4] == before[R + 4]
    # The space's own day-laborer food (+2) still happens (the schedule is independent
    # of the immediate +2 the space pays out this turn).
    assert s.players[ap].resources.food == food_before + 2


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_stew_unowned_noop_on_day_laborer():
    s, _env = setup_env(0)
    ap = s.current_player
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="day_laborer"))
    s = _run_turn(s)
    assert _food(s, ap) == before   # no Stew owned -> no schedule


def test_stew_does_not_fire_on_other_spaces():
    # The hook is gated on day_laborer: a forest use must NOT fire.
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "stew")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="forest"))
    s = _run_turn(s)
    assert _food(s, ap) == before


def test_stew_owner_only():
    # No any_player: when the owner places (and is the only owner), nothing schedules
    # for the opponent.
    s, _env = setup_env(0)
    ap = s.current_player
    other = 1 - ap
    s = _own_minor(s, ap, "stew")
    before_other = _food(s, other)
    s = step(s, PlaceWorker(space="day_laborer"))
    s = _run_turn(s)
    assert _food(s, other) == before_other


# ---------------------------------------------------------------------------
# Late-game clamping: out-of-range round spaces are silently dropped
# ---------------------------------------------------------------------------

def test_stew_clamps_out_of_range_rounds():
    # In round 14 (the last round) all of R+1..R+4 are past round 14, so nothing is
    # scheduled — "each REMAINING round space".
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "stew")
    s = fast_replace(s, round_number=14)
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="day_laborer"))
    s = _run_turn(s)
    assert _food(s, ap) == before


# ---------------------------------------------------------------------------
# The scheduled food is actually collected at the start of the target rounds
# ---------------------------------------------------------------------------

def test_stew_food_collected_at_round_start():
    # The scheduled food rides on `future_resources`, which the engine pays out at the
    # start of the scheduled round. Use Day Laborer in round 1 (schedules 1 food onto
    # rounds 2..5), then drive the PREPARATION->WORK transition into round 2 via the
    # engine's own `_complete_preparation` and confirm the food is credited.
    from agricola.constants import Phase
    from agricola.engine import _complete_preparation

    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "stew")
    s = step(s, PlaceWorker(space="day_laborer"))
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
