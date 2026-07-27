"""Tests for Job Contract (minor improvement, C23).

Card text (verbatim): "If both are unoccupied, you can use the "Day Laborer" and the
adjacent "Lessons" action space with a single person (in that order). Afterward, both
spaces are considered occupied."

The same-worker jump (ruling 81, 2026-07-26) whose source does NOT re-open: the person
uses Day Laborer, the after-window trigger moves it to Lessons for a full Lessons use
(play an occupation), and afterward BOTH spaces are occupied for legality — the person
standing on Lessons, a marker (this card's CardStore round stamp, via the
SPACE_BLOCK_EXTENSIONS seam) on Day Laborer. One physical worker: nothing that counts or
returns people can see a phantom, and a mid-round return of the chained person from
Lessons frees BOTH spaces (the marker clears through the worker-returned convention).
"""
import agricola.cards  # noqa: F401  -- registers the card (and everything else)

from agricola.actions import (
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.job_contract import CARD_ID
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions, legal_placements
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_resources

_POOL = CardPool(
    occupations=("second_spouse", "sheep_inspector", "henpecked_husband")
    + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

# The hand occupation for the Lessons play: registered (playable_occupations filters
# to registered specs) but inert here — Second Spouse's only effect is an
# occupancy override on Urgent Wish, untouched by these flows.
_HAND_OCC = "second_spouse"


def _p0(state):
    return state.players[0]


def _setup(*, own=True, hand_occ=(_HAND_OCC,), extra_occupations=frozenset(), seed=11):
    """Card-mode WORK state, P0 to move, owning Job Contract (already in the tableau),
    holding `hand_occ` occupations in hand."""
    s, _env = setup_env(seed, card_pool=_POOL)
    s = with_current_player(s, 0)
    p0 = fast_replace(
        s.players[0],
        hand_occupations=frozenset(hand_occ),
        hand_minors=frozenset(),
        occupations=frozenset(extra_occupations),
        minor_improvements=frozenset({CARD_ID}) if own else frozenset(),
    )
    p1 = fast_replace(s.players[1], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    return fast_replace(s, players=(p0, p1))


def _fires(state) -> bool:
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state))


def _drain(state):
    """End the turn WITHOUT firing anything optional: prefer Stop over triggers
    (a blind actions[0] drain can accidentally fire Sheep Inspector's return and
    exercise the whole marker-clearing path early)."""
    while state.pending_stack:
        acts = legal_actions(state)
        state = step(state, Stop() if Stop() in acts else acts[0])
    return state


def _day_laborer_after_window(state):
    state = step(state, PlaceWorker(space="day_laborer"))
    return step(state, Proceed())      # the +2 food take runs; after window opens


def _drive_chain(state):
    """Fire the chain and resolve the Lessons occupation play, back to the source's
    after-window."""
    state = step(state, FireTrigger(card_id=CARD_ID))
    # The Lessons host is up; play the sole hand occupation (first play is free).
    for _ in range(6):
        acts = legal_actions(state)
        plays = [a for a in acts if isinstance(a, CommitPlayOccupation)]
        if plays:
            state = step(state, plays[0])
            break
        assert acts, "no legal action while resolving the Lessons use"
        state = step(state, acts[0])
    return state


# ---------------------------------------------------------------------------
# Registration + static facts
# ---------------------------------------------------------------------------

def test_registered_with_no_occupations_prereq():
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].max_occupations == 0    # "No Occupations"
    assert MINORS[CARD_ID].vps == 0


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

def test_chain_moves_the_person_and_plays_an_occupation():
    s = _day_laborer_after_window(_setup())
    assert _fires(s)
    food_after_take = _p0(s).resources.food
    s = _drive_chain(s)
    p = _p0(s)
    # The person ended on Lessons; Day Laborer holds no worker (a marker, not a person).
    assert get_space(s.board, "day_laborer").workers[0] == 0
    assert get_space(s.board, "lessons").workers[0] == 1
    assert _HAND_OCC in p.occupations                    # the Lessons play happened
    assert p.resources.food == food_after_take           # 1st occupation is free
    assert p.card_state.get(CARD_ID) == s.round_number   # the marker is set
    # One placement act only — the jump mints no number (ruling 79).
    assert placements_this_round(p) == 1
    # Back at the source's after-window: the turn can end normally.
    s = _drain(s)


def test_both_spaces_blocked_afterward():
    s = _drain(_drive_chain(_day_laborer_after_window(_setup())))
    # The opponent is to move: neither Day Laborer (marker) nor Lessons (person) is
    # placeable.
    assert s.current_player == 1
    spaces = {a.space for a in legal_placements(s)}
    assert "day_laborer" not in spaces
    assert "lessons" not in spaces


def test_marker_dies_with_the_round():
    """The marker stores the chain's round; a stale stamp never blocks."""
    s = _setup()
    p = _p0(s)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, s.round_number - 1))
    s = fast_replace(s, players=(p, s.players[1]))
    spaces = {a.space for a in legal_placements(s)}
    assert "day_laborer" in spaces


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_lessons_is_occupied():
    s = _setup()
    sp = get_space(s.board, "lessons")
    s = fast_replace(s, board=fast_replace(
        s.board, action_spaces=tuple(
            fast_replace(x, workers=(0, 1)) if x is sp else x
            for x in s.board.action_spaces)))
    s = _day_laborer_after_window(s)
    assert not _fires(s)


def test_not_offered_with_no_playable_occupation():
    s = _day_laborer_after_window(_setup(hand_occ=()))
    assert not _fires(s)


def test_not_offered_without_ownership():
    s = _setup(own=False)
    s = step(s, PlaceWorker(space="day_laborer"))
    # Without the card, day_laborer is not hooked: it resolves atomically — no host,
    # no after-window, no trigger.
    assert not s.pending_stack
    assert not _fires(s)


def test_declinable():
    s = _day_laborer_after_window(_setup())
    assert _fires(s)
    s = step(s, Stop())                     # decline: just end the Day Laborer turn
    assert get_space(s.board, "lessons").workers[0] == 0
    assert _p0(s).card_state.get(CARD_ID) is None


# ---------------------------------------------------------------------------
# The return frees BOTH spaces (ruling 81 item 3)
# ---------------------------------------------------------------------------

def test_sheep_inspector_return_frees_both_spaces():
    """The chained person is returned home from Lessons -> the marker clears, and
    both Day Laborer and Lessons are open again."""
    s = _setup(extra_occupations=frozenset({"sheep_inspector"}))
    s = with_resources(s, 0, food=6)
    p = _p0(s)
    p = fast_replace(p, animals=fast_replace(p.animals, sheep=1))
    s = fast_replace(s, players=(p, s.players[1]))

    s = _drain(_drive_chain(_day_laborer_after_window(s)))   # end the chain turn
    assert s.current_player == 1
    s = step(s, PlaceWorker(space="forest"))      # opponent's turn
    assert s.current_player == 0

    # P0's second worker acts; after its action Sheep Inspector may return the
    # chained person from Lessons.
    s = step(s, PlaceWorker(space="clay_pit"))
    for _ in range(8):
        ret = [a for a in legal_actions(s)
               if isinstance(a, FireTrigger) and a.card_id == "sheep_inspector"
               and getattr(a, "variant", None) == "lessons"]
        if ret:
            s = step(s, ret[0])
            break
        acts = legal_actions(s)
        assert acts, "never reached Sheep Inspector's return window"
        s = step(s, acts[0])
    else:
        raise AssertionError("Sheep Inspector's lessons return was never offered")

    p = _p0(s)
    assert p.card_state.get(CARD_ID) is None          # marker cleared
    assert get_space(s.board, "lessons").workers[0] == 0
    s = _drain(s)
    # Both spaces are open again (ruling 81 item 3: the return frees BOTH) — assert
    # the occupancy fact directly; whose turn comes next is ordinary alternation
    # (the opponent still has a worker), and Lessons' PLACEABILITY also depends on
    # the placer's hand, which is not what this test pins.
    from agricola.legality import _is_available
    assert _is_available(s, "day_laborer")
    assert _is_available(s, "lessons")
    # And the freed spaces are genuinely usable: the opponent may take Day Laborer.
    assert s.current_player == 1
    assert PlaceWorker(space="day_laborer") in legal_placements(s)


# ---------------------------------------------------------------------------
# Henpecked Husband's record follows the chained person (the relocated hook)
# ---------------------------------------------------------------------------

def test_henpecked_husband_record_follows_the_jump():
    s = _setup(extra_occupations=frozenset({"henpecked_husband"}))
    s = _day_laborer_after_window(s)
    p = _p0(s)
    assert p.card_state.get("henpecked_husband") == (s.round_number, "day_laborer")
    s = _drive_chain(s)
    p = _p0(s)
    assert p.card_state.get("henpecked_husband") == (s.round_number, "lessons")


# ---------------------------------------------------------------------------
# The marker activates occupancy-READING cards (ruled 2026-07-26)
# ---------------------------------------------------------------------------

def test_marker_counts_for_turnip_farmer():
    """Turnip Farmer (3+): "at the start of the returning home phase, if both the
    'Day Laborer' and 'Grain Seeds' action spaces are occupied, you get 1 veg."
    Ruled 2026-07-26: Job Contract's "considered occupied" Day Laborer marker
    activates occupancy-reading cards exactly as a worker would — so a chain
    (marker on Day Laborer, person on Lessons) plus a worker on Grain Seeds pays
    the veg, though no worker stands on Day Laborer."""
    s = _setup(extra_occupations=frozenset({"turnip_farmer"}))
    s = _drain(_drive_chain(_day_laborer_after_window(s)))
    assert get_space(s.board, "day_laborer").workers == (0, 0)   # marker, no worker
    assert s.current_player == 1
    s = step(s, PlaceWorker(space="grain_seeds"))                # opponent occupies GS
    veg_before = _p0(s).resources.veg
    # P0's second worker; then the round runs out into returning home.
    s = step(s, PlaceWorker(space="forest"))
    s = _drain(s)
    guard = 0
    while s.round_number == 1 and guard < 60:
        acts = legal_actions(s)
        assert acts
        s = step(s, Stop() if Stop() in acts else acts[0])
        guard += 1
    assert _p0(s).resources.veg == veg_before + 1
