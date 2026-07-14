"""Tests for Prodigy (occupation, E98; Ephipparius Expansion).

Card text: "If this is your 1st occupation, you immediately get 1 bonus point
for each improvement you have. (This will not apply to improvements played
after this card.)"
User rulings 2026-07-14: "improvement" = minor improvements + owned majors;
"1st occupation" = literally the first occupation played all game; the count
FREEZES at play time (later improvements never raise it).

The plays drive the real Lessons -> play-occupation flow.
"""
import agricola.cards  # noqa: F401  (registers every implemented card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_majors

CARD_ID = "prodigy"

_POOL = CardPool(
    occupations=(CARD_ID, "bricklayer") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _scorer():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    """Round-1 card state, P0 to move, hands dropped; P0 gets food (Lessons
    charges 1 food per occupation after the first)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(
        cs.players[0],
        hand_occupations=frozenset({CARD_ID}),
        hand_minors=frozenset(),
        resources=fast_replace(cs.players[0].resources, food=10),
    )
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _replace_player(state, idx, p):
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _with_minors(state, idx, *card_ids):
    p = state.players[idx]
    return _replace_player(state, idx,
                           fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids)))


def _with_occs(state, idx, *card_ids):
    p = state.players[idx]
    return _replace_player(state, idx,
                           fast_replace(p, occupations=p.occupations | set(card_ids)))


def _play_prodigy(state):
    """The real Lessons -> play-occupation flow for P0, finished (both Stops)."""
    state = step(state, PlaceWorker(space="lessons"))
    state = step(state, ChooseSubAction(name="play_occupation"))
    state = step(state, CommitPlayOccupation(card_id=CARD_ID))
    state = step(state, Stop())   # pop the play-occupation host's after-phase
    state = step(state, Stop())   # pop the Lessons host frame
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_prodigy_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}
    # Pure on-play banking: no trigger and no automatic effect on ANY event.
    for event, entries in TRIGGERS.items():
        assert CARD_ID not in {e.card_id for e in entries}, event
    for event, entries in AUTO_EFFECTS.items():
        assert CARD_ID not in {e.card_id for e in entries}, event


# ---------------------------------------------------------------------------
# 1st occupation: banks 1 point per improvement (minors + majors)
# ---------------------------------------------------------------------------

def test_first_occupation_banks_minors_plus_majors():
    cs = _card_state()
    cs = _with_minors(cs, 0, "m1", "m2")          # 2 played minors
    cs = with_majors(cs, owner_by_idx={0: 0})     # + 1 owned major
    assert cs.players[0].occupations == frozenset()

    cs = _play_prodigy(cs)                        # the 1st occupation all game
    assert CARD_ID in cs.players[0].occupations
    assert cs.players[0].card_state.get(CARD_ID) == 3
    assert _scorer()(cs, 0) == 3


def test_first_occupation_no_improvements_scores_zero():
    cs = _card_state()
    assert cs.players[0].minor_improvements == frozenset()
    cs = _play_prodigy(cs)
    assert _scorer()(cs, 0) == 0


# ---------------------------------------------------------------------------
# 2nd occupation: banks nothing, whatever the improvement count
# ---------------------------------------------------------------------------

def test_second_occupation_banks_nothing():
    cs = _card_state()
    cs = _with_occs(cs, 0, "x0")                  # one occupation already down
    cs = _with_minors(cs, 0, "m1", "m2")          # 3 improvements in total
    cs = with_majors(cs, owner_by_idx={0: 0})

    cs = _play_prodigy(cs)                        # the 2nd occupation
    assert CARD_ID in cs.players[0].occupations
    assert cs.players[0].card_state.get(CARD_ID) is None
    assert _scorer()(cs, 0) == 0


# ---------------------------------------------------------------------------
# The count is FROZEN at play: later improvements never raise it
# ---------------------------------------------------------------------------

def test_count_frozen_at_play():
    cs = _card_state()
    cs = _with_minors(cs, 0, "m1")                # 1 minor + 1 major = 2 at play
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _play_prodigy(cs)
    assert _scorer()(cs, 0) == 2

    # Acquire another minor AND another major afterwards ("This will not apply
    # to improvements played after this card."): still 2.
    cs = _with_minors(cs, 0, "m2")
    cs = with_majors(cs, owner_by_idx={1: 0})
    assert _scorer()(cs, 0) == 2
