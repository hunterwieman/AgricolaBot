"""Tests for Growing Farm (minor improvement, B52; Bubulcus Expansion).

Card text: "You can only play this card if you have at least as many pasture
spaces as the number of completed rounds. If you do, you get a number of food
equal to the current round."

The two off-by-one / terminology traps this card turns on (verified against the
verbatim text + the triage ordering_note):
  - "Pasture spaces" = the number of CELLS enclosed in pastures (a 2-cell pasture
    counts as 2), i.e. len(enclosed_cells(fy)) — NOT the number of distinct
    Pasture objects.
  - "Completed rounds" = round_number - 1 (the current round is in progress), so
    the prereq is pasture_cells >= round_number - 1.
  - The food grant is the CURRENT round = round_number (one more than the prereq
    threshold), so the two amounts must not be conflated.
"""
import agricola.cards.growing_farm  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pasture import Pasture
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_round
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("growing_farm",) + tuple(f"m{i}" for i in range(20)),
)

_AFFORD = Resources(clay=2, reed=1)  # the printed cost: 2 clay, 1 reed


def _state(*, round_number=1, pasture_cells=0, resources=_AFFORD, in_hand=True):
    """Set up a card-mode state with the active player holding Growing Farm, owning
    a single pasture of `pasture_cells` cells, at `round_number`."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = with_round(cs, round_number)
    cp = cs.current_player
    # A single pasture covering `pasture_cells` cells (the cells themselves don't
    # matter for the count; enclosed_cells just unions the pasture cells).
    cells = frozenset((0, c) for c in range(pasture_cells))
    pastures = (
        (Pasture(cells=cells, num_stables=0, capacity=2 * len(cells)),)
        if pasture_cells
        else ()
    )
    fy = fast_replace(cs.players[cp].farmyard, pastures=pastures)
    hand = frozenset({"growing_farm"}) if in_hand else frozenset()
    p = fast_replace(cs.players[cp], farmyard=fy, hand_minors=hand, resources=resources)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "growing_farm" in MINORS
    spec = MINORS["growing_farm"]
    assert spec.vps == 2
    assert spec.cost.resources == Resources(clay=2, reed=1)
    assert spec.prereq is not None
    assert spec.passing_left is False  # kept in tableau, scores its 2 VPs


# ---------------------------------------------------------------------------
# Prerequisite: pasture_cells >= round_number - 1
# ---------------------------------------------------------------------------

def test_prereq_uses_completed_rounds_minus_one():
    spec = MINORS["growing_farm"]
    # Round 1: 0 completed rounds -> 0 pasture cells suffices.
    cs, cp = _state(round_number=1, pasture_cells=0)
    assert prereq_met(spec, cs, cp)
    # Round 5: 4 completed rounds -> need >= 4 pasture cells.
    cs, cp = _state(round_number=5, pasture_cells=3)
    assert not prereq_met(spec, cs, cp)        # 3 < 4 -> blocked
    cs, cp = _state(round_number=5, pasture_cells=4)
    assert prereq_met(spec, cs, cp)            # 4 >= 4 -> at threshold, ok
    cs, cp = _state(round_number=5, pasture_cells=5)
    assert prereq_met(spec, cs, cp)            # surplus ok


def test_prereq_counts_cells_not_pasture_objects():
    spec = MINORS["growing_farm"]
    # Round 3 needs >= 2 completed-round pasture cells. A SINGLE 2-cell pasture
    # has 1 pasture object but 2 cells -> should satisfy the "pasture spaces" read.
    cs, cp = _state(round_number=3, pasture_cells=2)
    assert prereq_met(spec, cs, cp)
    # A single 1-cell pasture (1 object, 1 cell) is NOT enough at round 3.
    cs, cp = _state(round_number=3, pasture_cells=1)
    assert not prereq_met(spec, cs, cp)


def test_playable_minors_respects_prereq_and_cost():
    # Eligible: round 1, 0 cells, can afford -> offered.
    cs, cp = _state(round_number=1, pasture_cells=0)
    assert playable_minors(cs, cp) == ["growing_farm"]
    # Prereq fails: round 4 needs >= 3 cells, has 0 -> not offered.
    cs, cp = _state(round_number=4, pasture_cells=0)
    assert playable_minors(cs, cp) == []
    # Prereq met but cost unaffordable -> not offered.
    cs, cp = _state(round_number=1, pasture_cells=0, resources=Resources(clay=2))  # no reed
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play: food == current round, card kept, cost paid
# ---------------------------------------------------------------------------

def test_play_grants_current_round_food_and_keeps_card():
    # Round 5, 4 pasture cells (at threshold). Food gained = current round = 5.
    cs, cp = _state(round_number=5, pasture_cells=4)
    before_food = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, "growing_farm")]
    cs = step(cs, sole_play_minor(cs, "growing_farm"))
    p = cs.players[cp]
    # Food: +5 (the current round), not +4 (the completed-round threshold).
    assert p.resources.food == before_food + 5
    # Cost paid: 2 clay, 1 reed spent.
    assert p.resources.clay == 0 and p.resources.reed == 0
    # Kept in the tableau (non-passing), left the hand.
    assert "growing_farm" in p.minor_improvements
    assert "growing_farm" not in p.hand_minors


def test_play_food_equals_round_one_at_round_one():
    cs, cp = _state(round_number=1, pasture_cells=0)
    before_food = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "growing_farm"))
    assert cs.players[cp].resources.food == before_food + 1
