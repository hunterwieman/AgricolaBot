import agricola.cards.bookcase  # noqa: F401
"""Bookcase (minor improvement, C68; cost 2 wood; prereq 1 occupation).

Card text: "Each time after you play an occupation, you get 1 vegetable."

A Category-5 unconditional automatic income on `after_play_occupation`: each
occupation the OWNER plays grants exactly 1 vegetable, fired choicelessly
(`register_auto`) in the play-occupation host's after-window. These tests drive
the real Lessons -> play-occupation flow (no direct frame pokes) so the firing
point is exercised end-to-end, and cover: registration, the real-flow +1 veg,
owner/own-action scoping (no fire on the opponent's play, no fire when unowned),
multiple plays each granting a veg, and the play-time prerequisite.
"""
from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_space

_POOL = CardPool(
    occupations=("consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=("bookcase",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so deterministic plays come only from what a test grants.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _play_occupation(cs, idx, card_id):
    """Drive the real Lessons -> play-occupation flow for player `idx`."""
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_bookcase_registered():
    assert "bookcase" in MINORS
    spec = MINORS["bookcase"]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 1     # prereq: 1 occupation
    assert spec.vps == 0
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Real-flow effect: +1 veg after playing an occupation
# ---------------------------------------------------------------------------

def test_bookcase_grants_veg_after_occupation():
    cs = _card_state()
    cs = _own_minor(cs, 0, "bookcase")
    cs = _give_hand_occ(cs, 0, "consultant")
    veg0 = cs.players[0].resources.veg
    cs = _play_occupation(cs, 0, "consultant")
    assert "consultant" in cs.players[0].occupations
    assert cs.players[0].resources.veg == veg0 + 1   # Bookcase fired (choiceless)


def test_bookcase_fires_choicelessly_no_firetrigger():
    # Bookcase is automatic income — no optional FireTrigger is ever surfaced.
    cs = _card_state()
    cs = _own_minor(cs, 0, "bookcase")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = _play_occupation(cs, 0, "consultant")
    from agricola.actions import FireTrigger
    assert FireTrigger(card_id="bookcase") not in legal_actions(cs)


def test_bookcase_fires_on_each_occupation_play():
    # Two separate occupation plays -> two vegetables (no once-per-game limit).
    cs = _card_state()
    cs = _own_minor(cs, 0, "bookcase")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = _give_hand_occ(cs, 0, "priest")
    veg0 = cs.players[0].resources.veg

    from agricola.actions import Stop
    cs = _play_occupation(cs, 0, "consultant")
    cs = step(cs, Stop())                      # pop the play-occupation host
    assert cs.players[0].resources.veg == veg0 + 1

    cs = _play_occupation(cs, 0, "priest")
    assert cs.players[0].resources.veg == veg0 + 2


# ---------------------------------------------------------------------------
# Scoping: owner + own-action only
# ---------------------------------------------------------------------------

def test_bookcase_does_not_fire_when_unowned():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "consultant")   # owns no Bookcase
    veg0 = cs.players[0].resources.veg
    cs = _play_occupation(cs, 0, "consultant")
    assert cs.players[0].resources.veg == veg0   # no fire


def test_bookcase_does_not_fire_on_opponents_play():
    # Player 0 owns Bookcase; player 1 plays an occupation -> 0 gets no veg.
    cs = _card_state()
    cs = _own_minor(cs, 0, "bookcase")
    cs = _give_hand_occ(cs, 1, "consultant")
    veg0_p0 = cs.players[0].resources.veg
    veg0_p1 = cs.players[1].resources.veg
    cs = _play_occupation(cs, 1, "consultant")
    assert "consultant" in cs.players[1].occupations
    assert cs.players[0].resources.veg == veg0_p0   # owner got nothing
    assert cs.players[1].resources.veg == veg0_p1   # non-owner got nothing


# ---------------------------------------------------------------------------
# Prerequisite: 1 occupation to play
# ---------------------------------------------------------------------------

def test_bookcase_prereq_needs_one_occupation():
    cs = _card_state()
    spec = MINORS["bookcase"]
    # No occupations -> prereq unmet.
    assert not prereq_met(spec, cs, 0)
    # With one occupation in the tableau -> prereq met.
    p = fast_replace(cs.players[0], occupations=frozenset({"consultant"}))
    cs2 = fast_replace(cs, players=tuple(p if i == 0 else cs.players[i] for i in range(2)))
    assert prereq_met(spec, cs2, 0)
