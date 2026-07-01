"""Tests for Game Trade (minor improvement, D9; Consul Dirigens Expansion; traveling).

Card text: "You immediately get 1 wild boar and 1 cattle. (Effectively, you are
exchanging 2 sheep for 1 wild boar and 1 cattle.)" Cost: 2 Sheep. No prerequisite,
no printed VPs; a TRAVELING (passing) card.

Category 2 (on-play one-shot) + passing, the animal-cost shape (cf. Young Animal
Market). The cost (2 sheep) is debited by the play-minor machinery via
`Cost.animals`; the on-play effect is +1 wild boar +1 cattle. Tests cover:
registration, the on_play gain in isolation (and that the opponent is untouched),
and the REAL play-minor flow (cost paid, gain applied, card circulates to the
opponent's hand because it is traveling).
"""
import agricola.cards.game_trade  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_animals, with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "game_trade"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _animals(state: GameState, idx: int) -> Animals:
    return state.players[idx].animals


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_game_trade_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    # Cost is 2 sheep (an animal cost), nothing else.
    assert spec.cost == Cost(animals=Animals(sheep=2))
    assert spec.cost.resources == Resources()
    assert spec.cost.animals == Animals(sheep=2)
    assert spec.vps == 0
    assert spec.passing_left is True          # traveling card
    assert spec.on_play is not None


def test_game_trade_no_prerequisite():
    spec = MINORS[CARD_ID]
    # No prerequisite: any state (either player) satisfies it.
    assert spec.prereq is None
    assert prereq_met(spec, setup(0), 0)
    assert prereq_met(spec, setup(0), 1)


# ---------------------------------------------------------------------------
# on_play effect in isolation — +1 boar +1 cattle (the cost is NOT applied here)
# ---------------------------------------------------------------------------

def test_on_play_grants_one_boar_and_one_cattle():
    s = setup(0)
    before = _animals(s, 0)
    out = MINORS[CARD_ID].on_play(s, 0)
    after = _animals(out, 0)
    assert after.boar == before.boar + 1
    assert after.cattle == before.cattle + 1
    # The cost (2 sheep) is debited by the play-minor machinery, NOT by on_play,
    # so on_play leaves sheep unchanged.
    assert after.sheep == before.sheep


def test_on_play_adds_onto_existing_animals():
    # The gain is additive on top of whatever the player already owns.
    s = with_animals(setup(0), 0, boar=2, cattle=1, sheep=3)
    out = MINORS[CARD_ID].on_play(s, 0)
    after = _animals(out, 0)
    assert after.boar == 3
    assert after.cattle == 2
    assert after.sheep == 3   # untouched by on_play


def test_on_play_leaves_opponent_untouched():
    s = with_animals(setup(0), 1, boar=1, cattle=1, sheep=1)
    out = MINORS[CARD_ID].on_play(s, 0)
    # Player 1 (the non-actor) is completely unchanged.
    assert _animals(out, 1) == _animals(s, 1)


# ---------------------------------------------------------------------------
# Real play flow — through the Major Improvement space (cost paid + gain applied)
# ---------------------------------------------------------------------------

def test_played_via_engine_pays_cost_and_grants_animals():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    # Give the active player the card in hand + exactly the 2-sheep cost.
    cs = with_animals(cs, cp, sheep=2)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    after = _animals(cs, cp)
    # Cost paid: the 2 sheep are gone. Gain applied: +1 boar, +1 cattle.
    assert after.sheep == 0
    assert after.boar == 1
    assert after.cattle == 1


# ---------------------------------------------------------------------------
# Passing circulation — traveling card lands in the opponent's hand
# ---------------------------------------------------------------------------

def test_traveling_card_passes_to_opponent():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    # Active player holds the card + the 2-sheep cost; opponent's hand is empty.
    cs = with_animals(cs, cp, sheep=2)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    # Drive PendingPlayMinor directly (the established minor-play factory pattern).
    cs = with_pending_stack(
        cs,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),),
    )

    out = step(cs, sole_play_minor(cs, CARD_ID))

    # Effect applied to the active player.
    assert _animals(out, cp).boar == 1
    assert _animals(out, cp).cattle == 1
    # Passing card: NOT kept in the player's tableau...
    assert CARD_ID not in out.players[cp].minor_improvements
    # ...and circulates to the opponent's hand.
    assert CARD_ID in out.players[1 - cp].hand_minors
