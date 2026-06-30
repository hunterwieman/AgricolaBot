"""Tests for Hod (minor A77): on-play +1 clay and an any-player Pig Market hook
that grants the OWNER 2 clay each time any player uses Pig Market.

Mirrors test_cards_opponent_hook.py (Milk Jug) — the closest same-shape card —
plus an on-play check.
"""
import agricola.cards.hod  # noqa: F401  (registers the card before cards/__init__)

from agricola.actions import CommitAccommodate, PlaceWorker, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPigMarket
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _pig_market_state(owner_of_hod):
    """Card-mode state with Pig Market revealed + stocked with 1 boar, and
    `owner_of_hod` owning Hod. P0 is the active player."""
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "pig_market")
    s = fast_replace(s, board=with_space(s.board, "pig_market",
                                         fast_replace(sp, revealed=True, accumulated_amount=1)))
    p = fast_replace(s.players[owner_of_hod],
                     minor_improvements=s.players[owner_of_hod].minor_improvements | {"hod"})
    s = fast_replace(s, players=tuple(
        p if i == owner_of_hod else s.players[i] for i in range(2)))
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_hod_registered():
    assert "hod" in MINORS
    spec = MINORS["hod"]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert not spec.passing_left
    # the any-player before-hook is registered
    assert any(e.card_id == "hod" and e.any_player
               for e in AUTO_EFFECTS.get("before_action_space", ()))


# ---------------------------------------------------------------------------
# On-play: +1 clay
# ---------------------------------------------------------------------------

def test_hod_on_play_grants_one_clay():
    spec = MINORS["hod"]
    s, _env = setup_env(5, card_pool=_POOL)
    clay0 = s.players[0].resources.clay
    s2 = spec.on_play(s, 0)
    assert s2.players[0].resources.clay == clay0 + 1
    # opponent untouched
    assert s2.players[1].resources.clay == s.players[1].resources.clay


# ---------------------------------------------------------------------------
# Pig Market hook — fires on the OWNER, only the owner gains, on either turn
# ---------------------------------------------------------------------------

def test_hod_fires_on_opponent_pig_market_use():
    # P1 owns Hod; P0 (active) uses Pig Market.
    s = _pig_market_state(owner_of_hod=1)
    c0, c1 = s.players[0].resources.clay, s.players[1].resources.clay

    # The before-auto fires at PlaceWorker (the host-frame push).
    s = step(s, PlaceWorker(space="pig_market"))
    assert isinstance(s.pending_stack[-1], PendingPigMarket)
    assert s.players[1].resources.clay == c1 + 2   # owner gained 2 clay
    assert s.players[0].resources.clay == c0       # active player gains NO clay

    # The boar still goes to the active player via normal resolution.
    b0 = s.players[0].animals.boar
    s = step(s, CommitAccommodate(sheep=0, boar=1, cattle=0))
    s = step(s, Stop())
    assert s.players[0].animals.boar == b0 + 1
    assert not s.pending_stack
    # clay totals unchanged after the boar take
    assert s.players[1].resources.clay == c1 + 2
    assert s.players[0].resources.clay == c0


def test_hod_fires_for_self_when_owner_acts():
    # P0 owns Hod and uses Pig Market itself ("including you").
    s = _pig_market_state(owner_of_hod=0)
    c0, c1 = s.players[0].resources.clay, s.players[1].resources.clay
    s = step(s, PlaceWorker(space="pig_market"))
    assert s.players[0].resources.clay == c0 + 2   # owner gained
    assert s.players[1].resources.clay == c1       # opponent gains nothing


def test_no_hod_no_payout():
    # Neither player owns it -> no clay anywhere.
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "pig_market")
    s = fast_replace(s, board=with_space(s.board, "pig_market",
                                         fast_replace(sp, revealed=True, accumulated_amount=1)))
    c0, c1 = s.players[0].resources.clay, s.players[1].resources.clay
    s = step(s, PlaceWorker(space="pig_market"))
    assert s.players[0].resources.clay == c0
    assert s.players[1].resources.clay == c1


def test_hod_does_not_fire_on_a_different_space():
    # Owner uses Sheep Market (not Pig Market) -> no Hod clay.
    s = _pig_market_state(owner_of_hod=0)
    sp = get_space(s.board, "sheep_market")
    s = fast_replace(s, board=with_space(s.board, "sheep_market",
                                         fast_replace(sp, revealed=True, accumulated_amount=1)))
    c0 = s.players[0].resources.clay
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.clay == c0       # Hod did not fire
