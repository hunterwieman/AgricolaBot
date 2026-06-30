"""Wood Workshop (minor B75): before you play/build an improvement, +1 wood.

Card text: "Each time before you play or build an improvement, you get 1 wood."
Clarification: "You are able to pay for the improvement with just the wood given
by this card."

These tests drive the REAL Major/Minor Improvement space flow (the same harness
test_cards_improvement_space.py uses) so the before_play_minor / before_build_major
autos fire exactly where the engine fires them — at the ChooseSubAction push, before
the commit charges cost.
"""
import agricola.cards.wood_workshop  # noqa: F401  (registers the card; not in cards/__init__)

from agricola.actions import ChooseSubAction, PlaceWorker, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import sole_build_major, sole_play_minor

CARD_ID = "wood_workshop"

# A pool that lets the current player be dealt the minors we drive (market_stall is
# passing — a clean non-self minor; bread_paddle costs exactly 1 wood for the
# "fund with just the granted wood" clarification).
_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall", "bread_paddle") + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5, *, hand=frozenset(), played=frozenset(), res=None):
    """Card-mode state with major_improvement forced revealed + the current player's
    played minors / hand / resources set; opponent's hand cleared."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=hand,
                     minor_improvements=played,
                     resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(clay=1)
    assert spec.min_occupations == 1
    assert spec.vps == 0
    assert spec.passing_left is False


def test_registered_on_both_before_events():
    for event in ("before_build_major", "before_play_minor"):
        ids = {e.card_id for e in AUTO_EFFECTS.get(event, ())}
        assert CARD_ID in ids, f"{CARD_ID} not registered on {event}"
    # NOT on rooms / renovation (improvement = major or minor only).
    for event in ("before_build_rooms", "before_renovate"):
        ids = {e.card_id for e in AUTO_EFFECTS.get(event, ())}
        assert CARD_ID not in ids, f"{CARD_ID} wrongly registered on {event}"


# ---------------------------------------------------------------------------
# The effect via a real play_minor flow
# ---------------------------------------------------------------------------

def test_grants_wood_before_playing_a_minor():
    # Owner of Wood Workshop plays market_stall (cost 1 grain). The +1 wood lands
    # before the cost is charged and banks (grain pays the cost, wood is surplus).
    cs, cp = _state(played=frozenset({CARD_ID}),
                    hand=frozenset({"market_stall"}),
                    res=Resources(grain=1))
    assert cs.players[cp].resources.wood == 0

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    # The before_play_minor auto fired at the play_minor push: +1 wood is already in hand.
    assert cs.players[cp].resources.wood == 1

    cs = step(cs, sole_play_minor(cs, "market_stall"))
    # Grain paid the cost; the granted wood remains banked.
    assert cs.players[cp].resources.wood == 1
    assert cs.players[cp].resources.grain == 0
    assert cs.players[cp].resources.veg == 1   # market_stall's +1 veg


def test_grants_wood_before_building_a_major():
    # Owner builds Fireplace (major idx 0, cost 2 clay). +1 wood arrives before payment.
    cs, cp = _state(played=frozenset({CARD_ID}), res=Resources(clay=2))
    assert cs.players[cp].resources.wood == 0

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    # The before_build_major auto fired at the build_major push.
    assert cs.players[cp].resources.wood == 1

    cs = step(cs, sole_build_major(cs, 0))   # Fireplace, 2 clay
    assert cs.players[cp].resources.wood == 1   # banked (clay paid)
    assert cs.players[cp].resources.clay == 0


def test_granted_wood_can_fund_the_improvement():
    # The clarification: "you can pay for the improvement with just the wood given
    # by this card." bread_paddle costs exactly 1 wood. Start with ZERO wood; the
    # before_play_minor grant must make it affordable.
    cs, cp = _state(played=frozenset({CARD_ID}),
                    hand=frozenset({"bread_paddle"}),
                    res=Resources())
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    assert cs.players[cp].resources.wood == 1   # the grant
    # bread_paddle is now affordable (and the only thing in hand) -> playable.
    cs = step(cs, sole_play_minor(cs, "bread_paddle"))
    assert "bread_paddle" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == 0   # the granted wood paid the cost


# ---------------------------------------------------------------------------
# Eligibility boundary: only the owner gets wood
# ---------------------------------------------------------------------------

def test_non_owner_gets_no_wood():
    # Same flow but the player does NOT own Wood Workshop -> no grant.
    cs, cp = _state(played=frozenset(),
                    hand=frozenset({"market_stall"}),
                    res=Resources(grain=1))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    assert cs.players[cp].resources.wood == 0   # not owned -> nothing granted


# ---------------------------------------------------------------------------
# Self-firing avoidance: playing Wood Workshop itself does not grant its owner wood
# (it isn't in minor_improvements until CommitPlayMinor, after its own
# before_play_minor would have fired).
# ---------------------------------------------------------------------------

def test_playing_wood_workshop_itself_grants_no_wood():
    # Hand-play Wood Workshop (cost 1 clay, needs 1 occupation). No wood before/after.
    cs, cp = _state(played=frozenset(),
                    hand=frozenset({CARD_ID}),
                    res=Resources(clay=1))
    # Give the player an occupation so the min_occupations=1 prereq is met.
    p = fast_replace(cs.players[cp], occupations=frozenset({"o0"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    # before_play_minor fired, but the card isn't owned yet -> no self-grant.
    assert cs.players[cp].resources.wood == 0

    cs = step(cs, sole_play_minor(cs, CARD_ID))
    assert CARD_ID in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == 0   # still none (the clay paid the cost)


# ---------------------------------------------------------------------------
# It is choice-free (mandatory auto): no FireTrigger / decline surfaces.
# ---------------------------------------------------------------------------

def test_grant_is_automatic_not_a_firetrigger():
    from agricola.actions import FireTrigger
    cs, cp = _state(played=frozenset({CARD_ID}),
                    hand=frozenset({"market_stall"}),
                    res=Resources(grain=1))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    # The grant already applied; no FireTrigger for Wood Workshop is offered.
    acts = legal_actions(cs)
    assert not any(isinstance(a, FireTrigger) for a in acts)
    assert legal_actions(cs) == [sole_play_minor(cs, "market_stall")]
