"""Excursion to the Quarry (minor improvement, B6; Bubulcus).

Card text: "You immediately get a number of stone equal to the number of people
you have." Clarification: "A newborn is a person." Cost 2 food, prereq 1 occupation,
traveling (passing), vps 0.

Drives the effect through the real improvement-space minor-play flow (PlaceWorker
-> ChooseSubAction("improvement") -> ChooseSubAction("play_minor") -> commit),
mirroring tests/test_cards_scoring_and_onplay.py.
"""
import agricola.cards.excursion_to_the_quarry  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.test_utils import sole_play_minor

CARD_ID = "excursion_to_the_quarry"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _replace_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration + spec
# ---------------------------------------------------------------------------

def test_registered_with_correct_spec():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=2))
    assert spec.min_occupations == 1
    assert spec.passing_left is True         # B6 is a traveling minor
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Prerequisite boundary — needs at least 1 occupation
# ---------------------------------------------------------------------------

def test_prereq_needs_one_occupation():
    s = setup(0)
    spec = MINORS[CARD_ID]
    assert not prereq_met(spec, _replace_player(s, 0, occupations=frozenset()), 0)
    assert prereq_met(spec, _replace_player(s, 0, occupations=frozenset({"o0"})), 0)
    assert prereq_met(spec, _replace_player(s, 0, occupations=frozenset({"o0", "o1"})), 0)


# ---------------------------------------------------------------------------
# Effect via a real play flow — stone == people_total
# ---------------------------------------------------------------------------

def _play(seed, *, people_total, newborns, start_stone=0, occupations=frozenset({"o0"})):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = _replace_player(
        cs, cp,
        resources=Resources(food=2, stone=start_stone),
        people_total=people_total,
        newborns=newborns,
        occupations=occupations,
        hand_minors=frozenset({CARD_ID}),
    )
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    return cs, cp


def test_gain_stone_equal_to_people():
    cs, cp = _play(5, people_total=2, newborns=0)
    assert cs.players[cp].resources.stone == 2       # base 2 people
    assert cs.players[cp].resources.food == 0        # 2 food cost paid
    # traveling: passes to the opponent's hand, not kept in the tableau.
    assert CARD_ID not in cs.players[cp].minor_improvements
    assert CARD_ID in cs.players[1 - cp].hand_minors


def test_stone_adds_to_existing_and_scales_with_people():
    cs, cp = _play(5, people_total=4, newborns=0, start_stone=3)
    assert cs.players[cp].resources.stone == 3 + 4   # added, not replaced


def test_newborn_counts_as_a_person():
    # people_total already INCLUDES newborns (state.py field doc + the card's
    # clarification), so a player with 3 placed + 1 newborn = people_total 4
    # gains 4 stone — the newborn is counted with no special handling.
    cs, cp = _play(5, people_total=4, newborns=1)
    assert cs.players[cp].resources.stone == 4


# ---------------------------------------------------------------------------
# Eligibility — card is unplayable (not offered) with zero occupations
# ---------------------------------------------------------------------------

def test_not_offered_without_occupation():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = _replace_player(
        cs, cp,
        resources=Resources(food=2),
        occupations=frozenset(),                     # prereq not met
        hand_minors=frozenset({CARD_ID}),
    )
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    from agricola.actions import CommitPlayMinor
    offered = [a for a in legal_actions(cs)
               if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert offered == []                             # prereq gates it out
