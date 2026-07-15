"""Tests for Blackberry Farmer (occupation, E108; Ephipparius).

"Each time you build fences, place 1 food on each remaining round space, up to
the number of fences just built. At the start of these rounds, you get the food."

The card is a before/after pair of automatic effects on the build_fences host
(the Shepherd's Crook / Trimmer snapshot idiom): `before_build_fences` snapshots
the board fence count, `after_build_fences` schedules 1 food on each of the next
`built` round spaces (built = board count now − snapshot; rounds past 14 are
dropped). Computed once per build-fences ACTION — per-pasture commits inside one
action are not separate events. Tests drive the REAL fencing flow (PlaceWorker
fencing → ChooseSubAction build_fences → CommitBuildPasture → Proceed → Stop),
per CARD_AUTHORING_GUIDE §5.
"""
import agricola.cards.blackberry_farmer  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.blackberry_farmer import CARD_ID, _schedule_after
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.helpers import fences_built
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from tests.factories import with_house, with_resources, with_space
from tests.test_fencing import _fencing_setup
from tests.test_utils import sole_renovate

# Two single-cell pastures on the top row, far from the rooms (column 0). A 1x1
# is the minimum pasture: 4 fences. The second, adjacent 1x1 shares an edge with
# the first, so committing both in one action builds 4 + 3 = 7 fences.
_1x1_A = frozenset({(0, 4)})
_1x1_B = frozenset({(0, 3)})


def _own(state, idx=0, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    return state


def _commit(state, cells):
    action = CommitBuildPasture(cells=cells)
    assert action in legal_actions(state)
    return step(state, action)


def _finish(state):
    """Proceed (flip PBF to after — fires the schedule) then drain the two Stops."""
    state = step(state, Proceed())   # flips PendingBuildFences -> after
    state = step(state, Stop())      # pop PendingBuildFences
    state = step(state, Stop())      # pop PendingSubActionSpace
    return state


def _food_schedule(state, idx=0):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS


# ---------------------------------------------------------------------------
# The schedule, through the real Fencing flow
# ---------------------------------------------------------------------------

def test_1x1_pasture_schedules_4_food_on_next_4_rounds():
    # A 1x1 pasture = 4 fences. Built in round 1 -> 1 food on each of rounds
    # 2, 3, 4, 5 (slot r-1 holds round r).
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _finish(state)
    assert fences_built(state.players[0].farmyard) == 4
    f = _food_schedule(state)
    assert f[0] == 0                            # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == f[4] == 1    # rounds 2-5
    assert sum(f) == 4
    # Snapshot reset to the canonical value (path-independence).
    assert state.players[0].card_state.get(CARD_ID) == 0


def test_two_pastures_one_action_is_one_payout():
    # Two adjacent 1x1s committed in the SAME action share an edge: 4 + 3 = 7
    # fences, ONE payout — exactly 1 food on each of rounds 2..8, never 2 on any
    # round (which a per-commit computation would produce).
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _commit(state, _1x1_B)
    state = _finish(state)
    assert fences_built(state.players[0].farmyard) == 7
    f = _food_schedule(state)
    assert f[0] == 0
    assert all(f[i] == 1 for i in range(1, 8))  # rounds 2..8, 1 each
    assert sum(f) == 7


def test_late_game_build_clips_at_round_14():
    # Built in round 12: 4 fences would cover rounds 13-16, but only 13 and 14
    # exist ("each REMAINING round space, up to the number built").
    state = _own(fast_replace(_fencing_setup(wood=12), round_number=12))
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _finish(state)
    f = _food_schedule(state)
    assert f[12] == 1 and f[13] == 1            # rounds 13, 14
    assert sum(f) == 2


def test_round_14_build_schedules_nothing():
    # No round spaces remain after round 14.
    state = _own(fast_replace(_fencing_setup(wood=12), round_number=14))
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _finish(state)
    assert sum(_food_schedule(state)) == 0
    assert state.players[0].card_state.get(CARD_ID) == 0


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_opponents_build_schedules_nothing():
    # P0 owns the card; P1 builds fences. Neither player gets any food scheduled.
    state = _own(_fencing_setup(wood=0, current_player=1), idx=0)
    state = with_resources(state, 1, wood=12)
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _finish(state)
    assert sum(_food_schedule(state, 0)) == 0
    assert sum(_food_schedule(state, 1)) == 0


def test_hand_only_is_inert():
    # The card in HAND (not played) does nothing.
    state = _fencing_setup(wood=12)
    p = state.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]))
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _finish(state)
    assert sum(_food_schedule(state)) == 0


def test_no_schedule_without_card():
    state = _fencing_setup(wood=12)             # does NOT own the card
    state = _enter_build_fences(state)
    state = _commit(state, _1x1_A)
    state = _finish(state)
    assert sum(_food_schedule(state)) == 0


# ---------------------------------------------------------------------------
# The other entry point: Farm Redevelopment
# ---------------------------------------------------------------------------

def _farm_redev_setup():
    state = _fencing_setup(wood=12)
    state = with_house(state, 0, material=HouseMaterial.WOOD)
    state = with_resources(state, 0, wood=12, clay=4, reed=2)
    state = _own(state)
    return with_space(state, "farm_redevelopment", revealed=True)


def test_via_farm_redevelopment():
    # Farm Redevelopment ("Overhaul") also pushes PendingBuildFences, so the
    # hook fires there too.
    state = _farm_redev_setup()
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, sole_renovate(state))
    state = step(state, Stop())                 # pop PendingRenovate
    state = step(state, ChooseSubAction(name="build_fences"))
    state = _commit(state, _1x1_A)
    state = step(state, Proceed())              # flip PBF -> after (schedule fires)
    state = step(state, Stop())                 # pop PBF
    state = step(state, Proceed())              # flip FarmRedev -> after
    state = step(state, Stop())                 # pop FarmRedev
    f = _food_schedule(state)
    assert sum(f) == 4
    assert f[1] == f[2] == f[3] == f[4] == 1    # rounds 2-5


def test_farm_redevelopment_fences_declined_no_payout():
    # Declining the optional fences never pushes PendingBuildFences, so neither
    # hook fires and nothing is scheduled.
    state = _farm_redev_setup()
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, sole_renovate(state))
    state = step(state, Stop())                 # pop PendingRenovate
    state = step(state, Proceed())              # flip FarmRedev -> after (no fences)
    state = step(state, Stop())                 # pop FarmRedev
    assert sum(_food_schedule(state)) == 0


# ---------------------------------------------------------------------------
# "At the start of these rounds, you get the food" — collection at round entry
# ---------------------------------------------------------------------------

def test_scheduled_food_collected_at_round_start():
    # The card's own after-hook schedules through the standard future_resources
    # machinery; drive _complete_preparation to enter the first scheduled round
    # and confirm the food is paid out into the supply.
    state = _own(
        fast_replace(_fencing_setup(wood=12), round_number=2, phase=Phase.PREPARATION)
    )
    # Reproduce the after-hook's inputs: snapshot 0 taken, 4 fences on the board
    # (a completed 1x1 build), then let the card's real after-effect schedule.
    from tests.test_fencing import _with_initial_pasture
    state = _with_initial_pasture(state, 0, [(0, 4)])
    p = state.players[0]
    state = fast_replace(
        state,
        players=(fast_replace(p, card_state=p.card_state.set(CARD_ID, 0)), state.players[1]),
    )
    state = _schedule_after(state, 0)           # schedules rounds 3..6
    assert _food_schedule(state)[2] == 1        # round 3 promised
    food_before = state.players[0].resources.food

    out = _complete_preparation(state)
    assert out.round_number == 3
    assert out.players[0].resources.food == food_before + 1
