"""Tests for Corf (minor B79): an any-player quarry hook that grants the OWNER
1 stone each time any player takes at least 3 stone from a quarry (the only stone
accumulation spaces).

Mirrors test_card_hod.py (any-player opponent hook) + test_cards_action_space_hook.py
(the Stone Tongs atomic-quarry case) — the two closest same-shape precedents. The
quarries are ATOMIC, so the host frame is only pushed because Corf registers an
action-space hook with any_player=True; the >=3 threshold is read off the stone the
acting player took (the host frame's `taken`, stamped at Proceed), so Corf's grant
fires in the after-window — after the take, not at the host-frame push.
"""
import agricola.cards.corf  # noqa: F401  (registers the card before cards/__init__)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _quarry_state(owner_of_corf, space_id="western_quarry", stone=3):
    """Card-mode state with `space_id` revealed + stocked with `stone` stone, and
    `owner_of_corf` owning Corf. P0 is the active player."""
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, space_id)
    s = fast_replace(s, board=with_space(s.board, space_id,
                                         fast_replace(sp, revealed=True,
                                                      accumulated=Resources(stone=stone))))
    p = fast_replace(s.players[owner_of_corf],
                     minor_improvements=s.players[owner_of_corf].minor_improvements | {"corf"})
    s = fast_replace(s, players=tuple(
        p if i == owner_of_corf else s.players[i] for i in range(2)))
    return s


def _finish_quarry_turn(s):
    """Drive the hosted atomic-quarry lifecycle to completion (Proceed then Stop)."""
    # before-phase: automatic-only, so a singleton Proceed.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert legal_actions(s) == [Proceed()]
    s = step(s, Proceed())            # the quarry's own stone take
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_corf_registered():
    assert "corf" in MINORS
    spec = MINORS["corf"]
    assert spec.cost.resources == Resources(reed=1)
    assert spec.vps == 0
    assert not spec.passing_left
    # The any-player after-hook is registered, and it hooks BOTH quarries.
    assert any(e.card_id == "corf" and e.any_player
               for e in AUTO_EFFECTS.get("after_action_space", ()))
    assert "corf" in ANY_PLAYER_HOOK_CARDS["western_quarry"]
    assert "corf" in ANY_PLAYER_HOOK_CARDS["eastern_quarry"]


def test_corf_on_play_is_a_noop():
    spec = MINORS["corf"]
    s, _env = setup_env(5, card_pool=_POOL)
    s2 = spec.on_play(s, 0)
    assert s2.players[0].resources == s.players[0].resources
    assert s2.players[1].resources == s.players[1].resources


# ---------------------------------------------------------------------------
# Quarry hook — fires on the OWNER, only the owner gains, on either turn
# ---------------------------------------------------------------------------

def test_corf_fires_for_self_when_owner_takes_3_stone():
    # P0 owns Corf and uses Western Quarry itself ("including you"), 3 stone on it.
    s = _quarry_state(owner_of_corf=0, stone=3)
    s0, s1 = s.players[0].resources.stone, s.players[1].resources.stone

    # After-auto: nothing fires at the host-frame push (the take hasn't happened yet).
    s = step(s, PlaceWorker(space="western_quarry"))
    assert s.players[0].resources.stone == s0       # not yet — Corf fires after the take
    assert s.players[1].resources.stone == s1

    # At Proceed the active player takes the quarry's 3 stone, THEN Corf grants +1.
    s = _finish_quarry_turn(s)
    assert s.players[0].resources.stone == s0 + 3 + 1
    assert s.players[1].resources.stone == s1


def test_corf_fires_on_opponent_quarry_use():
    # P1 owns Corf; P0 (active) takes 4 stone from Eastern Quarry.
    s = _quarry_state(owner_of_corf=1, space_id="eastern_quarry", stone=4)
    s0, s1 = s.players[0].resources.stone, s.players[1].resources.stone

    # After-auto: nothing fires at the host-frame push.
    s = step(s, PlaceWorker(space="eastern_quarry"))
    assert s.players[1].resources.stone == s1       # owner not paid until the take
    assert s.players[0].resources.stone == s0       # active player gains nothing yet

    # At Proceed P0 takes the 4 stone, THEN Corf pays its owner (P1) +1.
    s = _finish_quarry_turn(s)
    assert s.players[0].resources.stone == s0 + 4   # active player took the 4 stone
    assert s.players[1].resources.stone == s1 + 1   # owner +1 from Corf


# ---------------------------------------------------------------------------
# Threshold boundary — fires at >= 3, not at 2
# ---------------------------------------------------------------------------

def test_corf_fires_at_exactly_three():
    s = _quarry_state(owner_of_corf=0, stone=3)
    s0 = s.players[0].resources.stone
    s = step(s, PlaceWorker(space="western_quarry"))
    s = _finish_quarry_turn(s)                          # take 3 stone, then Corf fires
    assert s.players[0].resources.stone == s0 + 3 + 1   # threshold met (>= 3): +1 from Corf


def test_corf_does_not_fire_below_three():
    # Only 2 stone on the quarry -> threshold not met -> no Corf stone.
    s = _quarry_state(owner_of_corf=0, stone=2)
    s0 = s.players[0].resources.stone
    s = step(s, PlaceWorker(space="western_quarry"))
    # Host frame pushed (Corf hooks the space); the after-auto has not run yet.
    assert s.players[0].resources.stone == s0       # nothing before the take
    s = _finish_quarry_turn(s)                       # take 2 stone; 2 < 3 → Corf inert
    assert s.players[0].resources.stone == s0 + 2   # only the quarry's 2 stone


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_no_corf_no_payout_and_no_host():
    # Neither player owns it -> no host frame, atomic fast path, no extra stone.
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "western_quarry")
    s = fast_replace(s, board=with_space(s.board, "western_quarry",
                                         fast_replace(sp, revealed=True,
                                                      accumulated=Resources(stone=3))))
    assert not should_host_space(s, "western_quarry", 0)
    s0, s1 = s.players[0].resources.stone, s.players[1].resources.stone
    out = step(s, PlaceWorker(space="western_quarry"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.stone == s0 + 3   # just the quarry take
    assert out.players[1].resources.stone == s1


def test_corf_does_not_fire_on_a_non_stone_space():
    # Owner uses the Forest (a wood space, not a quarry) -> no Corf stone, and
    # Corf does not host the Forest.
    s = _quarry_state(owner_of_corf=0)
    assert not should_host_space(s, "forest", 0)
    s0 = s.players[0].resources.stone
    out = step(s, PlaceWorker(space="forest"))
    assert out.players[0].resources.stone == s0       # Corf did not fire
