import agricola.cards.tea_time  # noqa: F401  (registers the card)

"""Tests for Tea Time (minor improvement, E3; Ephipparius Expansion).

Card text: "Immediately return your person on the "Grain Utilization" action
space home; you can place it again later this round."
Cost: 1 Food. Prereq: Own Person on "Grain Utilization". Passing (traveling).

USER RULING (2026-07-20): the vacated space is OPEN — space illegality is
solely the presence of a worker; there is no residual "used this round"
block, so after the return EITHER player may place on Grain Utilization
again this round.

Tests drive the REAL flows: place a person on Grain Utilization and sow,
then play Tea Time through the card-mode Meeting Place's play-minor branch.
"""
import json
from pathlib import Path

from agricola.actions import ChooseSubAction, CommitPlayMinor, CommitSow, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import (
    with_fields,
    with_pending_stack,
    with_resources,
    with_space,
)
from tests.test_utils import sole_play_minor

CARD_ID = "tea_time"
GU = "grain_utilization"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Tea Time")


# ---------------------------------------------------------------------------
# State helpers — drive the REAL flows
# ---------------------------------------------------------------------------

def _base(seed=5):
    """Card-mode round-1 WORK state: Grain Utilization revealed, Tea Time
    (only) in the current player's hand, opponent's hand emptied, and BOTH
    players sow-capable (grain + empty fields) so either may legally place on
    Grain Utilization."""
    state, _env = setup_env(seed, card_pool=_POOL)
    cp = state.current_player
    state = with_space(state, GU, revealed=True)
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(
        state, players=tuple(p if i == cp else opp for i in range(2)))
    for i in (cp, 1 - cp):
        state = with_resources(state, i, food=3, grain=2)
        state = with_fields(state, i, [(0, 0), (0, 1)])
    return state, cp


def _sole_sow(state, grain):
    """The unique legal CommitSow sowing exactly `grain` grain (0 veg)."""
    opts = [a for a in legal_actions(state)
            if isinstance(a, CommitSow) and a.grain == grain and a.veg == 0]
    assert len(opts) == 1, f"expected one CommitSow(grain={grain}), got {opts!r}"
    return opts[0]


def _drain_turn(state):
    """Step through the trailing forced close-out (Proceed/Stop singletons)
    until the pending stack empties — the turn ends."""
    while state.pending_stack:
        acts = legal_actions(state)
        assert len(acts) == 1, f"expected a forced close-out, got {acts!r}"
        state = step(state, acts[0])
    return state


def _use_grain_utilization(state, *, sow_grain=1):
    """Place the current player's person on Grain Utilization, sow, and end
    the turn — the real non-atomic flow."""
    state = step(state, PlaceWorker(space=GU))
    state = step(state, ChooseSubAction(name="sow"))
    state = step(state, _sole_sow(state, sow_grain))
    return _drain_turn(state)


def _commit_tea_time_at_meeting_place(state):
    """Place on the card-mode Meeting Place and play Tea Time — stops right
    AFTER the CommitPlayMinor so its immediate effects can be observed."""
    state = step(state, PlaceWorker(space="meeting_place"))
    state = step(state, ChooseSubAction(name="play_minor"))
    return step(state, sole_play_minor(state, CARD_ID))


def _to_tea_time_moment(state, cp):
    """Round-1 script up to (and including) the Tea Time play: owner sows at
    Grain Utilization, opponent goes to the Forest, owner plays Tea Time via
    Meeting Place. Returns the state parked just after the CommitPlayMinor."""
    state = _use_grain_utilization(state)             # owner's person A on GU
    assert state.current_player == 1 - cp
    state = step(state, PlaceWorker(space="forest"))  # opponent elsewhere
    assert state.current_player == cp
    return _commit_tea_time_at_meeting_place(state)


# ---------------------------------------------------------------------------
# Registration & static facts (subset checks, never exact-set)
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] == "1 Food"
    assert _ROW["prerequisites"] == 'Own Person on "Grain Utilization"'
    assert _ROW["passing_left"] == "X"       # the JSON passing marker
    assert _ROW["text"] == (
        'Immediately return your person on the "Grain Utilization" action '
        "space home; you can place it again later this round.")
    import agricola.cards.tea_time as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.passing_left is True         # traveling
    assert spec.vps == 0
    assert spec.prereq is not None


# ---------------------------------------------------------------------------
# Prereq: Own Person on "Grain Utilization"
# ---------------------------------------------------------------------------

def _parked_at_play_minor(seed=5):
    """A state parked at a bare PendingPlayMinor frame with Tea Time (only)
    in the current player's hand and 1 food to pay the cost."""
    state, cp = _base(seed)
    state = with_pending_stack(
        state,
        (PendingPlayMinor(player_idx=cp,
                          initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _tea_plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def test_prereq_blocks_with_no_person_on_the_space():
    state, cp = _parked_at_play_minor()
    assert get_space(state.board, GU).workers == (0, 0)
    assert not prereq_met(MINORS[CARD_ID], state, cp)
    assert CARD_ID not in playable_minors(state, cp)
    assert _tea_plays(state) == []


def test_prereq_blocks_when_only_the_opponent_is_there():
    state, cp = _parked_at_play_minor()
    w = [0, 0]
    w[1 - cp] = 1                            # only the OPPONENT's person
    state = with_space(state, GU, workers=tuple(w))
    assert not prereq_met(MINORS[CARD_ID], state, cp)
    assert CARD_ID not in playable_minors(state, cp)
    assert _tea_plays(state) == []


def test_prereq_met_with_own_person():
    state, cp = _parked_at_play_minor()
    w = [0, 0]
    w[cp] = 1                                # the owner's person
    state = with_space(state, GU, workers=tuple(w))
    assert prereq_met(MINORS[CARD_ID], state, cp)
    assert CARD_ID in playable_minors(state, cp)
    assert len(_tea_plays(state)) == 1


# ---------------------------------------------------------------------------
# The play — real flow: sow at Grain Utilization, then Tea Time via
# the Meeting Place's play-minor branch
# ---------------------------------------------------------------------------

def test_play_returns_person_pays_food_and_passes():
    state, cp = _base()
    state = _use_grain_utilization(state)
    state = step(state, PlaceWorker(space="forest"))     # opponent's turn
    assert get_space(state.board, GU).workers[cp] == 1
    food_before = state.players[cp].resources.food
    home_before = state.players[cp].people_home          # 1 (person B unplaced)
    state = _commit_tea_time_at_meeting_place(state)
    p = state.players[cp]
    # Person off Grain Utilization, back home. Net home change is 0: -1 for
    # the Meeting Place placement itself, +1 for the returned person.
    assert get_space(state.board, GU).workers == (0, 0)
    assert p.people_home == home_before
    # 1 food paid.
    assert p.resources.food == food_before - 1
    # Traveling: left the owner's hand, never kept, in the OPPONENT's hand.
    assert CARD_ID not in p.hand_minors
    assert CARD_ID not in p.minor_improvements
    assert CARD_ID in state.players[1 - cp].hand_minors


def test_space_open_for_owner_again_this_round():
    """Ruling 2026-07-20: after the return the vacated space is OPEN — the
    owner may place on Grain Utilization again THIS round (driving the
    placement and a second sow)."""
    state, cp = _base()
    state = _drain_turn(_to_tea_time_moment(state, cp))  # end the MP turn
    assert state.current_player == 1 - cp
    state = step(state, PlaceWorker(space="fishing"))    # opponent's last person
    # Back to the owner — the returned person re-enters the alternation.
    assert state.phase is Phase.WORK
    assert state.current_player == cp
    assert PlaceWorker(space=GU) in legal_actions(state)
    state = _use_grain_utilization(state)                # second sow (1 grain left)
    assert state.players[cp].resources.grain == 0        # both grain sown


def test_space_open_for_opponent_this_round():
    """The ruling explicitly opens the vacated space to BOTH players: after
    Tea Time, the OPPONENT may place on Grain Utilization this round."""
    state, cp = _base()
    state = _drain_turn(_to_tea_time_moment(state, cp))  # end the MP turn
    assert state.current_player == 1 - cp
    assert PlaceWorker(space=GU) in legal_actions(state)
    state = step(state, PlaceWorker(space=GU))
    assert get_space(state.board, GU).workers[1 - cp] == 1
    state = step(state, ChooseSubAction(name="sow"))
    state = step(state, _sole_sow(state, 1))
    state = _drain_turn(state)
    assert state.players[1 - cp].resources.grain == 1    # sowed one of two


def test_last_person_edge_work_phase_continues():
    """The Grain Utilization worker was the owner's LAST unplaced person at
    the moment Tea Time resolves (people_home was 0 after the Meeting Place
    placement): the return leaves them 1 home and the work phase continues
    for them rather than ending."""
    state, cp = _base()
    state = _use_grain_utilization(state)                # person A on GU
    state = step(state, PlaceWorker(space="forest"))     # opponent
    # Place person B on Meeting Place: people_home hits 0 BEFORE the play.
    state = step(state, PlaceWorker(space="meeting_place"))
    assert state.players[cp].people_home == 0
    state = step(state, ChooseSubAction(name="play_minor"))
    state = step(state, sole_play_minor(state, CARD_ID))
    assert state.players[cp].people_home == 1            # the returned person
    state = _drain_turn(state)
    # The opponent places their last person; the round is NOT over — the
    # owner's returned person still gets a placement.
    state = step(state, PlaceWorker(space="fishing"))
    assert state.phase is Phase.WORK
    assert state.current_player == cp
    assert state.players[cp].people_home == 1
    # Place the returned person again (on the vacated space, no less) and sow —
    # stopping before the turn's close-out so the round boundary (which resets
    # people_home) is never crossed.
    state = step(state, PlaceWorker(space=GU))
    assert get_space(state.board, GU).workers[cp] == 1
    assert state.players[cp].people_home == 0
    state = step(state, ChooseSubAction(name="sow"))
    state = step(state, _sole_sow(state, 1))
    assert state.players[cp].resources.grain == 0        # both grain sown
