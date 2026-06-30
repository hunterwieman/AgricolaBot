"""Tests for Sheep Provider (occupation C141; Corbarius): an any-player Sheep
Market hook that grants the OWNER 1 grain each time ANY player uses the
"Sheep Market" accumulation space.

Mirrors test_card_corf.py (the any-player opponent goods hook) but on the
NON-ATOMIC, self-hosting Sheep Market (Claw Knife's precedent) — so unlike Corf
there is NO `register_action_space_hook`: `_initiate_sheep_market` itself pushes
the host frame and fires `before_action_space` on every use (including the
opponent's). The +1 grain is a pure goods grant (no threshold), so it fires
unconditionally on any Sheep Market use, on either player's turn.
"""
import agricola.cards.sheep_provider  # noqa: F401  (registers the card before cards/__init__)

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    apply_auto_effects,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingSheepMarket, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

CARD_ID = "sheep_provider"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occupation(state, idx, card_id=CARD_ID):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _state(owner, sheep=0):
    """Card-mode state with `owner` owning Sheep Provider, P0 active, and the
    Sheep Market stocked with `sheep` sheep so the underlying take is benign."""
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    from agricola.state import get_space, with_space
    sp = get_space(s.board, "sheep_market")
    s = fast_replace(s, board=with_space(
        s.board, "sheep_market",
        fast_replace(sp, revealed=True, accumulated_amount=sheep)))
    return _own_occupation(s, owner)


def _run_turn(s):
    steps = 0
    while s.pending_stack and steps < 30:
        s = step(s, legal_actions(s)[0])
        steps += 1
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_sheep_provider_registered():
    assert CARD_ID in OCCUPATIONS
    # The any-player before-action-space auto is registered.
    entry = next(e for e in AUTO_EFFECTS.get("before_action_space", ())
                 if e.card_id == CARD_ID)
    assert entry.any_player                       # "each time ANY player ... uses"
    # Sheep Market is non-atomic + self-hosting, so NO action-space hook is registered.
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("sheep_market", set())
    assert CARD_ID not in ANY_PLAYER_HOOK_CARDS.get("sheep_market", set())


def test_sheep_provider_on_play_is_a_noop():
    spec = OCCUPATIONS[CARD_ID]
    s, _env = setup_env(5, card_pool=_POOL)
    s2 = spec.on_play(s, 0)
    assert s2.players[0].resources == s.players[0].resources
    assert s2.players[1].resources == s.players[1].resources


def test_sheep_provider_does_not_host_sheep_market():
    # No hook registered -> the non-atomic space's OWN self-host is unaffected, and
    # `should_host_space` (the atomic-space gate) returns False for it.
    s = _state(owner=0, sheep=2)
    assert not should_host_space(s, "sheep_market", 0)


# ---------------------------------------------------------------------------
# The hook — owner gains 1 grain on a real Sheep Market placement (own turn)
# ---------------------------------------------------------------------------

def test_grain_on_own_sheep_market_use():
    # P0 owns Sheep Provider and uses Sheep Market itself ("including you").
    s = _state(owner=0, sheep=4)
    g0, g1 = s.players[0].resources.grain, s.players[1].resources.grain

    # The before-auto fires at PlaceWorker (the host-frame push), immediately.
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.grain == g0 + 1   # owner gained 1 grain
    assert s.players[1].resources.grain == g1       # opponent unchanged

    # Finishing the turn does not grant a second grain (fires once per use).
    s = _run_turn(s)
    assert s.players[0].resources.grain == g0 + 1
    assert s.players[1].resources.grain == g1


def test_grain_on_opponent_sheep_market_use():
    # P1 owns Sheep Provider; P0 (active) uses Sheep Market — the owner still gains.
    s = _state(owner=1, sheep=3)
    g0, g1 = s.players[0].resources.grain, s.players[1].resources.grain

    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[1].resources.grain == g1 + 1   # owner gained 1 grain
    assert s.players[0].resources.grain == g0       # active player gains no grain

    s = _run_turn(s)
    assert s.players[1].resources.grain == g1 + 1   # still only +1


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_unowned_no_payout():
    # Neither player owns it -> no grain granted on a Sheep Market use.
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    from agricola.state import get_space, with_space
    sp = get_space(s.board, "sheep_market")
    s = fast_replace(s, board=with_space(
        s.board, "sheep_market", fast_replace(sp, revealed=True, accumulated_amount=3)))
    g0, g1 = s.players[0].resources.grain, s.players[1].resources.grain
    s = step(s, PlaceWorker(space="sheep_market"))
    s = _run_turn(s)
    assert s.players[0].resources.grain == g0
    assert s.players[1].resources.grain == g1


def test_does_not_fire_on_a_different_market():
    # The hook is gated on space_id == "sheep_market": a Pig Market use must NOT fire.
    s = _state(owner=0)
    from agricola.state import get_space, with_space
    sp = get_space(s.board, "pig_market")
    s = fast_replace(s, board=with_space(
        s.board, "pig_market", fast_replace(sp, revealed=True, accumulated_amount=0)))
    g0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="pig_market"))
    s = _run_turn(s)
    assert s.players[0].resources.grain == g0       # no grain on a non-sheep market


# ---------------------------------------------------------------------------
# Eligibility / scoping driven directly via apply_auto_effects
# ---------------------------------------------------------------------------

def test_eligibility_scoped_to_sheep_market_host_frame():
    # With a non-sheep-market host frame on top, the auto must NOT fire.
    s = _state(owner=0)
    s = push(s, PendingSheepMarket(
        player_idx=0, initiated_by_id="space:pig_market", gained=0))
    g0 = s.players[0].resources.grain
    out = apply_auto_effects(s, "before_action_space", 0)
    assert out.players[0].resources.grain == g0     # space_id != sheep_market


def test_apply_auto_grants_each_owner_once():
    # Both players own it: a single Sheep Market host push grants EACH owner 1 grain
    # (any_player iterates over both owners), regardless of which seat is "acting".
    s = _state(owner=0)
    s = _own_occupation(s, 1)
    s = push(s, PendingSheepMarket(
        player_idx=0, initiated_by_id="space:sheep_market", gained=0))
    g0, g1 = s.players[0].resources.grain, s.players[1].resources.grain
    out = apply_auto_effects(s, "before_action_space", 0)
    assert out.players[0].resources.grain == g0 + 1
    assert out.players[1].resources.grain == g1 + 1
