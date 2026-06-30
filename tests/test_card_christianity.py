"""Christianity (minor improvement, C38; Corbarius Expansion).

Card text: "When you play this card, all other players get 1 food each."
Cost: none. Prerequisite: Exactly 1 Sheep. VPs: 2. Not passing.

Covers: registration/spec, the exact-1-sheep prerequisite boundary, the
real-flow on-play effect (the OPPONENT gains 1 food; the player gains nothing
but keeps the card), and end-game scoring of the 2 printed VPs.
"""
import agricola.cards.christianity  # noqa: F401

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_animals
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("christianity",) + tuple(f"m{i}" for i in range(20)),
)


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_registered_spec():
    spec = MINORS["christianity"]
    assert spec.vps == 2
    assert spec.cost == Cost()              # no printed cost
    assert spec.passing_left is False       # kept, not traveling
    assert spec.prereq is not None
    assert spec.on_play is not None


# ---------------------------------------------------------------------------
# Prerequisite — EXACTLY 1 sheep (a have-check, not >= 1)
# ---------------------------------------------------------------------------

def test_prereq_requires_exactly_one_sheep():
    s = setup(0)
    assert not prereq_met(MINORS["christianity"], with_animals(s, 0, sheep=0), 0)
    assert prereq_met(MINORS["christianity"], with_animals(s, 0, sheep=1), 0)
    # Exactly 1 — two sheep does NOT satisfy it.
    assert not prereq_met(MINORS["christianity"], with_animals(s, 0, sheep=2), 0)


# ---------------------------------------------------------------------------
# On-play — the OPPONENT gets 1 food; the player gains nothing but keeps the card
# ---------------------------------------------------------------------------

def test_on_play_gives_opponent_food():
    cs, env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    opp = 1 - cp
    # Christianity's prereq is "exactly 1 sheep" — required for it to be playable.
    cs = with_animals(cs, cp, sheep=1)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"christianity"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    before_self = cs.players[cp].resources.food
    before_opp = cs.players[opp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))     # play-minor entry point
    cs = step(cs, ChooseSubAction(name="improvement"))        # singleton: push PendingMajorMinorImprovement
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "christianity"))

    # The opponent (all OTHER players) gains 1 food.
    assert cs.players[opp].resources.food == before_opp + 1
    # The player who played it gains nothing from the effect (no cost, no gain).
    assert cs.players[cp].resources.food == before_self
    # It is kept in the tableau (not passing).
    assert "christianity" in cs.players[cp].minor_improvements
    assert "christianity" not in cs.players[opp].minor_improvements


# ---------------------------------------------------------------------------
# Scoring — 2 printed VPs when kept
# ---------------------------------------------------------------------------

def test_scores_two_vps():
    s = setup(0)
    base, _ = score(s, 0)
    s1 = _own_minor(s, 0, "christianity")
    total, bd = score(s1, 0)
    assert bd.card_points == 2
    assert total == base + 2
