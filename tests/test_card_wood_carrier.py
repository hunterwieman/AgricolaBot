"""Wood Carrier (occupation, A117): on play, gain 1 wood per improvement
(minor improvements + owned majors) in front of you; occupations don't count.

Card text: "When you play this card, you immediately get 1 wood for each
improvement in front of you."
"""
import agricola.cards.wood_carrier  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors

_POOL = CardPool(
    occupations=("wood_carrier",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, occupations=frozenset(), minors=frozenset(),
                hand=frozenset({"wood_carrier"})):
    """A card-mode round-1 state with the current player's hand/tableau set
    deterministically so plays are reproducible."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(
        p,
        hand_occupations=hand,
        occupations=occupations,
        minor_improvements=minors,
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _play_wood_carrier(cs):
    """Drive the real Lessons play flow for the current player's wood_carrier."""
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="wood_carrier"))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_wood_carrier_registered():
    assert "wood_carrier" in OCCUPATIONS


# ---------------------------------------------------------------------------
# The on-play effect via the real Lessons flow
# ---------------------------------------------------------------------------

def test_no_improvements_grants_zero_wood():
    cs, cp = _card_state()
    before = cs.players[cp].resources.wood
    cs = _play_wood_carrier(cs)
    assert cs.players[cp].resources.wood == before          # +0, harmless
    assert "wood_carrier" in cs.players[cp].occupations


def test_one_wood_per_minor_improvement():
    cs, cp = _card_state(minors=frozenset({"m1", "m2", "m3"}))
    before = cs.players[cp].resources.wood
    cs = _play_wood_carrier(cs)
    assert cs.players[cp].resources.wood == before + 3


def test_counts_owned_majors():
    cs, cp = _card_state()
    # Own two majors (Fireplace idx 0 + Cooking Hearth idx 2).
    cs = with_majors(cs, owner_by_idx={0: cp, 2: cp})
    before = cs.players[cp].resources.wood
    cs = _play_wood_carrier(cs)
    assert cs.players[cp].resources.wood == before + 2


def test_counts_minors_plus_majors_together():
    cs, cp = _card_state(minors=frozenset({"m1", "m2"}))
    cs = with_majors(cs, owner_by_idx={0: cp, 2: cp, 5: cp})  # 3 majors
    before = cs.players[cp].resources.wood
    cs = _play_wood_carrier(cs)
    assert cs.players[cp].resources.wood == before + 5        # 2 minors + 3 majors


# ---------------------------------------------------------------------------
# Eligibility boundaries: occupations and the opponent's tableau don't count
# ---------------------------------------------------------------------------

def test_occupations_do_not_count():
    # Already played some occupations; they are NOT improvements.
    cs, cp = _card_state(occupations=frozenset({"o1", "o2"}))
    before = cs.players[cp].resources.wood
    cs = _play_wood_carrier(cs)
    assert cs.players[cp].resources.wood == before           # +0 (occupations excluded)


def test_opponents_improvements_do_not_count():
    cs, cp = _card_state(minors=frozenset({"m1"}))
    opp = 1 - cp
    # Give the opponent minors + a major; only the player's own improvements count.
    op = fast_replace(cs.players[opp], minor_improvements=frozenset({"x1", "x2", "x3"}))
    cs = fast_replace(cs, players=tuple(op if i == opp else cs.players[i] for i in range(2)))
    cs = with_majors(cs, owner_by_idx={1: opp})
    before = cs.players[cp].resources.wood
    cs = _play_wood_carrier(cs)
    assert cs.players[cp].resources.wood == before + 1        # only the player's 1 minor


# ---------------------------------------------------------------------------
# The card is genuinely played (lands in the tableau) and the turn closes out.
# ---------------------------------------------------------------------------

def test_card_lands_in_tableau_and_turn_completes():
    cs, cp = _card_state(minors=frozenset({"m1"}))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    assert legal_actions(cs) == [CommitPlayOccupation(card_id="wood_carrier")]
    cs = step(cs, CommitPlayOccupation(card_id="wood_carrier"))
    assert "wood_carrier" in cs.players[cp].occupations
    assert "wood_carrier" not in cs.players[cp].hand_occupations
    cs = step(cs, Stop())   # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())   # pop the Lessons host frame
    assert cs.pending_stack == ()
