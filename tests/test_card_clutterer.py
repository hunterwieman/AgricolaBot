"""Tests for Clutterer (occupation, B100; Bubulcus Expansion).

Card text: "During scoring, you get 1 bonus point for each card played after
this on[e] that has "accumulation space(s)" in its text."
Clarification: only cards played by the OWNER count.
User ruling 2026-07-14: a qualifying traveling (passing) minor played after
Clutterer counts even though it leaves the tableau.

These tests drive the real play flows (Lessons for occupations, the
PendingPlayMinor host for minors) so the after_play_* firing points are
exercised end-to-end.
"""
import agricola.cards  # noqa: F401  (registers every implemented card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.clutterer import QUALIFYING_IDS
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_pending_stack, with_space
from tests.test_utils import sole_play_minor

CARD_ID = "clutterer"

# A qualifying implemented occupation (no-op on_play; its own auto rides
# before_action_space on Forest, which no play flow here touches) and a
# qualifying implemented minor (1 clay, no prereq, no-op on_play). Both picks
# are re-validated against the computed catalog intersection in
# test_qualifying_set_sanity / the flow test below.
QUAL_OCC = "wood_cutter"
QUAL_MINOR = "milk_jug"
# A NON-qualifying occupation with a no-op on_play (the Education Bonus filler).
NONQUAL_OCC = "bricklayer"

_POOL = CardPool(
    occupations=(CARD_ID, QUAL_OCC, NONQUAL_OCC) + tuple(f"o{i}" for i in range(20)),
    minors=(QUAL_MINOR, "wood_pile") + tuple(f"m{i}" for i in range(20)),
)


def _scorer():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _bank(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    """Round-1 card state, P0 to move, both hands dropped; P0 gets food (Lessons
    charges 1 food per occupation after the first) and clay (milk_jug's cost)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(
        cs.players[0],
        hand_occupations=frozenset(),
        hand_minors=frozenset(),
        resources=fast_replace(cs.players[0].resources, food=10, clay=5),
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


def _give_hand_minor(state, idx, card_id):
    p = state.players[idx]
    return _replace_player(state, idx,
                           fast_replace(p, hand_minors=p.hand_minors | {card_id}))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return _replace_player(state, idx,
                           fast_replace(p, occupations=p.occupations | {card_id}))


def _fresh_turn(state, idx):
    """Reset the Lessons space + player `idx`'s per-turn latch so a new placement
    is legal again (test-only state surgery, the cardstore-test idiom)."""
    state = with_space(state, "lessons", workers=(0, 0))
    p = fast_replace(state.players[idx], used_this_turn=frozenset(),
                     people_home=max(1, state.players[idx].people_home))
    state = _replace_player(state, idx, p)
    return with_current_player(state, idx)


def _play_occupation(state, idx, card_id):
    """The real Lessons -> play-occupation flow, stopping right after the commit
    (the after_play_occupation autos have fired; the bank is readable)."""
    state = with_current_player(state, idx)
    state = step(state, PlaceWorker(space="lessons"))
    state = step(state, ChooseSubAction(name="play_occupation"))
    return step(state, CommitPlayOccupation(card_id=card_id))


def _play_and_finish(state, idx, card_id):
    state = _play_occupation(state, idx, card_id)
    state = step(state, Stop())   # pop the play-occupation host's after-phase
    state = step(state, Stop())   # pop the Lessons host frame
    return state


def _play_minor(state, idx, card_id):
    """Play a minor through a real PendingPlayMinor host (the Wood Pile idiom):
    the CommitPlayMinor executor stamps played_card_id and fires the
    after_play_minor autos. Leaves the host's after-phase open."""
    state = with_current_player(state, idx)
    state = with_pending_stack(state, (
        PendingPlayMinor(player_idx=idx, initiated_by_id="space:meeting_place_cards"),
    ))
    return step(state, sole_play_minor(state, card_id))


# ---------------------------------------------------------------------------
# Registration + the qualifying set
# ---------------------------------------------------------------------------

def test_clutterer_registered():
    assert CARD_ID in OCCUPATIONS
    # Counts AT PLAY TIME: automatic effects on BOTH play events.
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("after_play_occupation", ())}
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("after_play_minor", ())}
    # The banked count is read at scoring.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}


def test_qualifying_set_sanity():
    # Cards whose text names "accumulation space(s)" qualify...
    assert "wood_pile" in QUALIFYING_IDS
    assert "milk_jug" in QUALIFYING_IDS
    assert "hand_truck" in QUALIFYING_IDS
    assert CARD_ID in QUALIFYING_IDS          # Clutterer's own text qualifies
    # ...and cards whose text doesn't, don't.
    assert "tutor" not in QUALIFYING_IDS
    assert "big_country" not in QUALIFYING_IDS
    # The picks used by the flow tests really are qualifying + implemented
    # (computed from the catalog intersection, not hard-coded trust).
    impl_qual_occs = sorted(QUALIFYING_IDS & set(OCCUPATIONS))
    impl_qual_minors = sorted(QUALIFYING_IDS & set(MINORS))
    assert QUAL_OCC in impl_qual_occs
    assert QUAL_MINOR in impl_qual_minors
    assert NONQUAL_OCC not in QUALIFYING_IDS


# ---------------------------------------------------------------------------
# The real flow: qualifying plays after Clutterer each bank 1 point
# ---------------------------------------------------------------------------

def test_qualifying_plays_after_clutterer_bank_points():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, QUAL_OCC)
    cs = _give_hand_minor(cs, 0, QUAL_MINOR)

    # Play Clutterer itself (1st occupation, free). Its own play never counts.
    cs = _play_and_finish(cs, 0, CARD_ID)
    assert CARD_ID in cs.players[0].occupations
    assert _bank(cs, 0) == 0

    # A qualifying occupation played after it -> bank 1.
    cs = _fresh_turn(cs, 0)
    cs = _play_and_finish(cs, 0, QUAL_OCC)
    assert _bank(cs, 0) == 1

    # A qualifying minor played after it -> bank 2.
    cs = _play_minor(cs, 0, QUAL_MINOR)
    assert _bank(cs, 0) == 2
    cs = step(cs, Stop())                     # pop the play-minor host

    # The scoring term returns the banked 2; the full score() path agrees
    # (Clutterer is the only card-points source in this tableau — wood_cutter
    # has no scoring term and milk_jug's printed VPs are 0).
    assert _scorer()(cs, 0) == 2
    _t, bd = score(cs, 0)
    assert bd.card_points == 2


def test_non_qualifying_play_adds_nothing():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 0, NONQUAL_OCC)
    cs = _play_and_finish(cs, 0, CARD_ID)
    cs = _fresh_turn(cs, 0)
    cs = _play_and_finish(cs, 0, NONQUAL_OCC)
    assert NONQUAL_OCC in cs.players[0].occupations
    assert _bank(cs, 0) == 0
    assert _scorer()(cs, 0) == 0


def test_cards_played_before_clutterer_do_not_count():
    # "played after this one": a qualifying card already down when Clutterer
    # lands adds nothing.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, QUAL_OCC)
    cs = _give_hand_occ(cs, 0, CARD_ID)
    cs = _play_and_finish(cs, 0, QUAL_OCC)    # qualifying card FIRST
    cs = _fresh_turn(cs, 0)
    cs = _play_and_finish(cs, 0, CARD_ID)     # then Clutterer
    assert _bank(cs, 0) == 0
    assert _scorer()(cs, 0) == 0


def test_own_play_never_counts_itself():
    # Clutterer's own text contains the phrase (pinned above), but it is not a
    # card played AFTER itself: the bank is 0 right after its own commit.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, CARD_ID)
    cs = _play_occupation(cs, 0, CARD_ID)     # bank readable at the commit
    assert CARD_ID in cs.players[0].occupations
    assert _bank(cs, 0) == 0


def test_opponents_qualifying_play_does_not_count():
    # Owner-only: P0 owns Clutterer; P1 plays a qualifying occupation.
    cs = _card_state()
    cs = _own_occ(cs, 0, CARD_ID)
    cs = _give_hand_occ(cs, 1, QUAL_OCC)
    cs = _play_and_finish(cs, 1, QUAL_OCC)
    assert QUAL_OCC in cs.players[1].occupations
    assert _bank(cs, 0) == 0
    assert _scorer()(cs, 0) == 0


def test_traveling_minor_counts_despite_leaving_tableau():
    # User ruling 2026-07-14: Wood Pile (qualifying AND passing) counts for its
    # player even though it is passed to the opponent, never kept.
    cs = _card_state()
    cs = _own_occ(cs, 0, CARD_ID)
    cs = _give_hand_minor(cs, 0, "wood_pile")
    cs = _play_minor(cs, 0, "wood_pile")
    assert _bank(cs, 0) == 1
    # The traveler really left: not in P0's tableau or hand, now in P1's hand.
    assert "wood_pile" not in cs.players[0].minor_improvements
    assert "wood_pile" not in cs.players[0].hand_minors
    assert "wood_pile" in cs.players[1].hand_minors
    assert _scorer()(cs, 0) == 1


def test_unplayed_clutterer_counts_nothing():
    # A Clutterer still in HAND is not owned: qualifying plays bank nothing.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, CARD_ID)       # in hand, never played
    cs = _give_hand_occ(cs, 0, QUAL_OCC)
    cs = _play_and_finish(cs, 0, QUAL_OCC)
    assert cs.players[0].card_state.get(CARD_ID) is None
    _t, bd = score(cs, 0)
    assert bd.card_points == 0
