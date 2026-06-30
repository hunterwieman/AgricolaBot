"""Tests for Thresher (occupation, C112; Consul Dirigens Expansion).

Card text: "Immediately before each time you use the 'Grain Utilization',
'Farmland', or 'Cultivation' action space, you can buy 1 grain for 1 food."

Implemented as an OPTIONAL `before_action_space` trigger over the three named
spaces: on the before-phase of any of them the owner may FireTrigger("thresher")
to swap 1 food for 1 grain. Eligibility gates on food >= 1 and `triggers_resolved`
limits it to at most once per space use. Tests drive the real engine placement
flow (PlaceWorker → FireTrigger → the space's own sub-action), not frame poking.
"""
import agricola.cards.thresher  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction, CommitPlow, FireTrigger, PlaceWorker, Proceed, Stop,
)
from agricola.cards.triggers import TRIGGERS, CARDS
from agricola.constants import CellType
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_grid, with_resources
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    """A card-mode round-1 WORK state."""
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    return fast_replace(state, board=with_space(state.board, space_id, fast_replace(
        get_space(state.board, space_id), revealed=True)))


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registers_before_action_space_trigger():
    ids = [e.card_id for e in TRIGGERS.get("before_action_space", ())]
    assert "thresher" in ids
    entry = CARDS["thresher"]
    assert entry.event == "before_action_space"
    assert entry.mandatory is False  # optional / declinable


# --------------------------------------------------------------------------- #
# The buy is OFFERED (and optional) on a real placement flow
# --------------------------------------------------------------------------- #

def test_buy_offered_after_placing_on_farmland():
    """After placing on Farmland, an owner with >=1 food sees FireTrigger('thresher')."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=2)

    s = run_actions(s, [PlaceWorker(space="farmland")])
    actions = legal_actions(s)
    assert FireTrigger(card_id="thresher") in actions
    # It is declinable: a plow ChooseSubAction is also offered, so the player can
    # proceed without buying.
    assert ChooseSubAction(name="plow") in actions


def test_buy_swaps_one_food_for_one_grain():
    """Firing the trigger costs exactly 1 food and yields exactly 1 grain."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=2)
    before = s.players[0].resources

    s = run_actions(s, [
        PlaceWorker(space="farmland"),
        FireTrigger(card_id="thresher"),   # buy 1 grain for 1 food
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
        Stop(),   # pop PendingPlow after-phase
        Stop(),   # pop the Farmland parent
    ])

    assert s.players[0].resources.food == before.food - 1
    assert s.players[0].resources.grain == before.grain + 1
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD


def test_buy_is_optional_decline_changes_nothing():
    """Declining (never firing) leaves food/grain untouched."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=2)
    before = s.players[0].resources

    s = run_actions(s, [
        PlaceWorker(space="farmland"),
        ChooseSubAction(name="plow"),       # decline the buy, just plow
        CommitPlow(row=0, col=2),
        Stop(),       # pop PendingPlow after-phase
        # Thresher is still eligible (declined), so the delegating host holds its
        # flip and offers Proceed rather than auto-advancing.
        Proceed(),    # advance the Farmland host to its after-phase
        Stop(),       # pop the parent
    ])

    assert s.players[0].resources.food == before.food
    assert s.players[0].resources.grain == before.grain


def test_grain_bought_is_available_to_subsequent_sow():
    """The before-phase ruling: grain bought here is usable by the space's own
    effect. On Grain Utilization, buying grain tops up the supply available to the
    subsequent sow sub-action."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = _reveal(s, "grain_utilization")
    # An empty field to sow into; 1 grain + 2 food so the placement is legal now
    # (can sow), and Thresher can then buy a second grain.
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})
    s = with_resources(s, 0, food=2, grain=1)

    s = run_actions(s, [
        PlaceWorker(space="grain_utilization"),
        FireTrigger(card_id="thresher"),    # +1 grain, -1 food
    ])
    # After the buy the player has 2 grain available for the sow sub-action, and
    # the sow ChooseSubAction is offered (the bought grain is usable here).
    assert s.players[0].resources.grain == 2
    assert s.players[0].resources.food == 1
    assert ChooseSubAction(name="sow") in legal_actions(s)


# --------------------------------------------------------------------------- #
# Fires on all three named spaces (cultivation force-revealed)
# --------------------------------------------------------------------------- #

def test_offered_on_cultivation():
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=1)
    s = _reveal(s, "cultivation")

    s = run_actions(s, [PlaceWorker(space="cultivation")])
    assert FireTrigger(card_id="thresher") in legal_actions(s)


# --------------------------------------------------------------------------- #
# Eligibility boundaries
# --------------------------------------------------------------------------- #

def test_not_offered_without_food():
    """No food (< 1) → the buy is not offered (never a dead-end FireTrigger)."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=0)   # cannot pay the 1-food cost

    s = run_actions(s, [PlaceWorker(space="farmland")])
    assert FireTrigger(card_id="thresher") not in legal_actions(s)


def test_non_owner_not_offered():
    """A player who does not own Thresher is never offered the buy."""
    s = fast_replace(_card_state(), current_player=0)
    s = with_resources(s, 0, food=2)   # has food, but does NOT own the card

    s = run_actions(s, [PlaceWorker(space="farmland")])
    assert FireTrigger(card_id="thresher") not in legal_actions(s)


def test_not_offered_on_unnamed_space():
    """The trigger is scoped to its three spaces — not offered on, e.g., Forest."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=2)

    # Forest is atomic and not hooked by Thresher → no host frame, no FireTrigger.
    s = run_actions(s, [PlaceWorker(space="forest")])
    for a in legal_actions(s):
        assert not (isinstance(a, FireTrigger) and a.card_id == "thresher")


# --------------------------------------------------------------------------- #
# Scoping: at most once per space use; re-eligible on the next use
# --------------------------------------------------------------------------- #

def test_at_most_once_per_use():
    """`triggers_resolved` blocks a second buy within the same space use."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = with_resources(s, 0, food=3)

    s = run_actions(s, [
        PlaceWorker(space="farmland"),
        FireTrigger(card_id="thresher"),   # first (and only) buy this use
    ])
    # Still has food, but already fired this use → not offered again.
    assert s.players[0].resources.food == 2
    assert FireTrigger(card_id="thresher") not in legal_actions(s)


def test_re_eligible_on_a_fresh_use():
    """A new space use (a fresh parent frame) makes the buy eligible again."""
    s = fast_replace(_card_state(), current_player=0)
    s = _own(s, 0, occupations=("thresher",))
    s = _reveal(s, "cultivation")
    s = with_resources(s, 0, food=3)

    # First use: Farmland — buy once.
    s = run_actions(s, [
        PlaceWorker(space="farmland"),
        FireTrigger(card_id="thresher"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
        Stop(),
        Stop(),
    ])
    food_after_first = s.players[0].resources.food

    # Second use: Cultivation by the same player — the buy is offered again.
    s = fast_replace(s, current_player=0)
    s = run_actions(s, [PlaceWorker(space="cultivation")])
    assert FireTrigger(card_id="thresher") in legal_actions(s)
    assert food_after_first == 2  # only one buy has happened so far
