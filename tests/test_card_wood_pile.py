"""Tests for Wood Pile (minor improvement, B4; Bubulcus; traveling).

Card text: "You immediately get a number of wood equal to the number of people
you have on accumulation spaces." No cost, no prereq, no VPs; traveling (passed
to the opponent after the on-play effect).
"""
import agricola.cards.wood_pile  # noqa: F401  (registers the card)

from agricola.constants import ACCUMULATION_SPACES
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_space
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("wood_pile",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5, *, cp_minors=frozenset(), workers_on=()):
    """A 2-player card state with the current player holding ``cp_minors`` and
    one of its own people placed on each space id in ``workers_on``."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=cp_minors)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    for sid in workers_on:
        w = [0, 0]
        w[cp] = 1
        cs = with_space(cs, sid, revealed=True, workers=tuple(w))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "wood_pile" in MINORS
    spec = MINORS["wood_pile"]
    assert spec.passing_left is True
    assert spec.vps == 0
    assert spec.min_occupations == 0
    assert spec.cost.resources == Resources()  # no cost


# ---------------------------------------------------------------------------
# Free, no-prereq -> always playable when held
# ---------------------------------------------------------------------------

def test_playable_when_held():
    cs, cp = _state(cp_minors=frozenset({"wood_pile"}))
    assert playable_minors(cs, cp) == ["wood_pile"]
    # Not in hand -> not offered.
    cs, cp = _state(cp_minors=frozenset())
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play effect via a real engine flow + passing circulation
# ---------------------------------------------------------------------------

def test_grants_wood_per_worker_on_accumulation_spaces():
    # Own people on 3 accumulation spaces -> +3 wood.
    cs, cp = _state(
        cp_minors=frozenset({"wood_pile"}),
        workers_on=("forest", "clay_pit", "fishing"),
    )
    opp = 1 - cp
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, "wood_pile")]
    cs = step(cs, sole_play_minor(cs, "wood_pile"))

    p = cs.players[cp]
    assert p.resources.wood == wood0 + 3
    # Traveling: not kept, circulated to the opponent.
    assert "wood_pile" not in p.minor_improvements
    assert "wood_pile" not in p.hand_minors
    assert "wood_pile" in cs.players[opp].hand_minors


def test_zero_workers_grants_no_wood():
    cs, cp = _state(cp_minors=frozenset({"wood_pile"}), workers_on=())
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "wood_pile"))
    assert cs.players[cp].resources.wood == wood0  # +0


def test_counts_all_accumulation_spaces_not_others():
    # Every accumulation space occupied -> +len(ACCUMULATION_SPACES) wood.
    cs, cp = _state(
        cp_minors=frozenset({"wood_pile"}),
        workers_on=tuple(ACCUMULATION_SPACES),
    )
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "wood_pile"))
    assert cs.players[cp].resources.wood == wood0 + len(ACCUMULATION_SPACES)


def test_ignores_non_accumulation_spaces():
    # A worker on grain_seeds / vegetable_seeds / day_laborer / farmland is NOT
    # counted (fixed-yield, non-accumulating).
    cs, cp = _state(
        cp_minors=frozenset({"wood_pile"}),
        workers_on=("grain_seeds", "vegetable_seeds", "day_laborer", "farmland"),
    )
    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "wood_pile"))
    assert cs.players[cp].resources.wood == wood0  # none counted


def test_ignores_opponent_workers():
    # Opponent people on accumulation spaces must NOT be counted.
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"wood_pile"}))
    op = fast_replace(cs.players[opp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else op for i in range(2)))
    # Put OPPONENT workers on two accumulation spaces (and one own worker on one).
    w = [0, 0]
    w[opp] = 1
    cs = with_space(cs, "forest", revealed=True, workers=tuple(w))
    cs = with_space(cs, "clay_pit", revealed=True, workers=tuple(w))
    w2 = [0, 0]
    w2[cp] = 1
    cs = with_space(cs, "reed_bank", revealed=True, workers=tuple(w2))

    wood0 = cs.players[cp].resources.wood
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "wood_pile"))
    assert cs.players[cp].resources.wood == wood0 + 1  # only the own reed_bank worker
