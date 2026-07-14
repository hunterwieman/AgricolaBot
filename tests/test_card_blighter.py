"""Tests for Blighter (occupation, E101; Ephipparius Expansion).

Card text: "When you play this card, you get 1 bonus point for each complete
stage left to play. You may not play any more occupations."
User ruling 2026-07-14: "complete stages left" = 6 - stage_of_round(current
round) — played in round 5 (stage 2) banks 4 points; round 14 (stage 6) banks 0.

The plays drive the real Lessons -> play-occupation flow; the occupation lock
is checked at the `playable_occupations` chokepoint AND at the legal-placement
surface (Lessons must stop being a legal placement for the blocked player).
"""
import agricola.cards  # noqa: F401  (registers every implemented card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATION_PLAY_BLOCKERS, OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions, playable_occupations
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_round, with_space

CARD_ID = "blighter"

_POOL = CardPool(
    occupations=(CARD_ID, "bricklayer", "carpenter") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _scorer():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    """Round-1 card state, P0 to move, hands dropped; both players get food
    (Lessons charges 1 food per occupation after the first)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(
        cs.players[0],
        hand_occupations=frozenset({CARD_ID}),
        hand_minors=frozenset(),
        resources=fast_replace(cs.players[0].resources, food=10),
    )
    p1 = fast_replace(
        cs.players[1],
        hand_occupations=frozenset(),
        hand_minors=frozenset(),
        resources=fast_replace(cs.players[1].resources, food=10),
    )
    return fast_replace(cs, players=(p0, p1))


def _replace_player(state, idx, p):
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    return _replace_player(state, idx,
                           fast_replace(p, hand_occupations=p.hand_occupations | {card_id}))


def _fresh_turn(state, idx):
    """Reset the Lessons space + player `idx`'s per-turn latch so a new placement
    is legal again (test-only state surgery, the cardstore-test idiom)."""
    state = with_space(state, "lessons", workers=(0, 0))
    p = fast_replace(state.players[idx], used_this_turn=frozenset(),
                     people_home=max(1, state.players[idx].people_home))
    state = _replace_player(state, idx, p)
    return with_current_player(state, idx)


def _play_blighter(state):
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

def test_blighter_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}
    # "You may not play any more occupations" = an occupation-play blocker.
    assert CARD_ID in OCCUPATION_PLAY_BLOCKERS


# ---------------------------------------------------------------------------
# The banked points: 1 per complete stage left to play
# ---------------------------------------------------------------------------

def test_banks_four_when_played_in_stage_two():
    # Round 5 is a stage-2 round: stages 3-6 are still entirely ahead -> 4.
    cs = with_round(_card_state(), 5)
    cs = _play_blighter(cs)
    assert cs.players[0].card_state.get(CARD_ID) == 4
    assert _scorer()(cs, 0) == 4


def test_banks_five_in_round_one():
    # Round 1 (stage 1): stages 2-6 remain -> 5.
    cs = _card_state()
    assert cs.round_number == 1
    cs = _play_blighter(cs)
    assert cs.players[0].card_state.get(CARD_ID) == 5
    assert _scorer()(cs, 0) == 5


def test_banks_zero_in_round_fourteen():
    # Round 14 (stage 6, the last): no complete stage is left -> 0.
    cs = with_round(_card_state(), 14)
    cs = _play_blighter(cs)
    assert cs.players[0].card_state.get(CARD_ID) == 0
    assert _scorer()(cs, 0) == 0


# ---------------------------------------------------------------------------
# The occupation lock
# ---------------------------------------------------------------------------

def test_playing_blighter_itself_succeeds_then_locks():
    cs = _card_state()
    # Before the play the block does not exist: Lessons is a legal placement
    # and Blighter itself is offered.
    assert PlaceWorker(space="lessons") in legal_actions(cs)
    assert playable_occupations(cs, 0) == [CARD_ID]

    cs = _play_blighter(cs)                       # the very play succeeds
    assert CARD_ID in cs.players[0].occupations

    # ... and only AFTER it lands does the lock apply.
    cs = _give_hand_occ(cs, 0, "bricklayer")      # a playable occupation in hand
    assert cs.players[0].resources.food > 0       # affordability is not the gate
    assert playable_occupations(cs, 0) == []

    # Lessons is no longer a legal placement for P0 on a fresh worker turn.
    cs = _fresh_turn(cs, 0)
    assert cs.pending_stack == ()
    assert PlaceWorker(space="lessons") not in legal_actions(cs)


def test_opponent_can_still_play_occupations():
    cs = _card_state()
    cs = _play_blighter(cs)                       # P0 is locked
    cs = _give_hand_occ(cs, 1, "carpenter")
    assert playable_occupations(cs, 1) == ["carpenter"]

    # On P1's worker turn (Lessons freed) the placement is legal for them.
    cs = _fresh_turn(cs, 1)
    assert PlaceWorker(space="lessons") in legal_actions(cs)


def test_blighter_in_hand_blocks_nothing():
    # Unplayed (hand) Blighter is not owned: no lock.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "bricklayer")      # hand = {blighter, bricklayer}
    assert playable_occupations(cs, 0) == [CARD_ID, "bricklayer"]
    assert PlaceWorker(space="lessons") in legal_actions(cs)


def test_lock_persists_in_later_rounds():
    cs = _card_state()
    cs = _play_blighter(cs)                       # played in round 1
    cs = _give_hand_occ(cs, 0, "bricklayer")
    cs = with_round(cs, 10)                       # rounds later, still locked
    assert playable_occupations(cs, 0) == []
    cs = _fresh_turn(cs, 0)
    assert PlaceWorker(space="lessons") not in legal_actions(cs)
