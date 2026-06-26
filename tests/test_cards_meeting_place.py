"""Tests for the card-game Meeting Place (CARD_IMPLEMENTATION_PLAN.md I.3).

The card Meeting Place reuses the family `meeting_place` slot (no new SPACE_IDS
id), mode-branched in the resolver: family = food accumulation + become SP
(atomic); cards = become SP (immediate, no food) then OPTIONALLY play one minor
(a PendingMeetingPlace single-optional Proceed-host, ALWAYS pushed in card mode —
uniform with the Major Improvement always-wrap; SPACE_HOST_REFACTOR.md §7). When
no minor is playable the before-phase is just [before-triggers, Proceed]. Proceed
is always the decline (legal from the start). Card mode also skips the per-round
food refill on that slot, so it never accumulates.
"""
from agricola.actions import (
    ChooseSubAction, CommitPlayMinor, PlaceWorker, Proceed, Stop,
)
from agricola.agents.base import RandomAgent, play_game
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.pending import PendingMeetingPlace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, minors, grain=1, sp_other=False):
    cs, env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    if sp_other:
        cs = fast_replace(cs, starting_player=1 - cp)   # so become-SP visibly flips it
    p = fast_replace(cs.players[cp], hand_minors=minors, resources=Resources(grain=grain))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, env, cp


def test_meeting_place_placeable_in_cards():
    cs, _env, _cp = _card_state(minors=frozenset())
    assert "meeting_place" in {a.space for a in legal_placements(cs)}


def test_become_sp_then_play_minor():
    cs, _env, cp = _card_state(minors=frozenset({"market_stall"}), sp_other=True)
    opp = 1 - cp
    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert cs.starting_player == cp                       # became SP immediately
    acts = legal_actions(cs)
    # before-phase: the optional minor + Proceed (the decline, legal from start).
    assert ChooseSubAction(name="play_minor") in acts and Proceed() in acts

    cs = step(cs, ChooseSubAction(name="play_minor"))
    assert legal_actions(cs) == [CommitPlayMinor(card_id="market_stall")]
    cs = step(cs, CommitPlayMinor(card_id="market_stall"))
    assert cs.players[cp].resources.veg == 1
    assert "market_stall" in cs.players[opp].hand_minors  # passing -> circulated
    assert legal_actions(cs) == [Stop()]                  # PendingPlayMinor after-phase
    cs = step(cs, Stop())                                 # pop the play-minor after-phase
    # back at the parent before-phase: minor played -> only Proceed remains.
    assert legal_actions(cs) == [Proceed()]
    cs = step(cs, Proceed())                              # flip the parent to after
    assert legal_actions(cs) == [Stop()]                  # parent after-phase singleton
    cs = step(cs, Stop())                                 # pop the parent
    assert cs.pending_stack == ()


def test_decline_minor_keeps_sp():
    cs, _env, cp = _card_state(minors=frozenset({"market_stall"}), sp_other=True)
    cs = step(cs, PlaceWorker(space="meeting_place"))
    # Proceed is the decline (legal from the start) -> flip to after-phase.
    assert Proceed() in legal_actions(cs)
    cs = step(cs, Proceed())                              # decline the optional minor
    assert legal_actions(cs) == [Stop()]                  # parent after-phase singleton
    cs = step(cs, Stop())                                 # pop the parent
    assert cs.pending_stack == ()
    assert cs.starting_player == cp                       # SP kept
    assert "market_stall" in cs.players[cp].hand_minors   # not played


def test_no_playable_minor_always_wraps():
    """Even with no playable minor, card mode always pushes PendingMeetingPlace
    (uniform with the Major Improvement always-wrap). The before-phase contains
    only Proceed (no ChooseSubAction), so the walk is:
        PlaceWorker → [Proceed] → Proceed → [Stop] → Stop.
    become-SP still fires immediately at the push."""
    cs, _env, cp = _card_state(minors=frozenset(), grain=0, sp_other=True)
    cs = step(cs, PlaceWorker(space="meeting_place"))
    # Always-wrapped: a PendingMeetingPlace frame is on the stack.
    assert len(cs.pending_stack) == 1
    assert isinstance(cs.pending_stack[-1], PendingMeetingPlace)
    assert cs.starting_player == cp                       # become-SP fired at push
    # Before-phase: no minor available -> only Proceed (the decline).
    acts = legal_actions(cs)
    assert acts == [Proceed()]
    cs = step(cs, Proceed())                              # flip to after-phase
    assert legal_actions(cs) == [Stop()]                  # after-phase singleton
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_card_hook_fires_with_no_playable_minor():
    """Cards hooking the Meeting Place space via after_action_space must fire even
    when the player has no playable minor. This test registers a synthetic auto
    effect on after_action_space and verifies it fires when the stack's top is
    PendingMeetingPlace in card mode — the gap closed by always-wrapping."""
    from agricola.cards.triggers import AUTO_EFFECTS, register_auto

    card_id = "_test_mp_hook_no_minor"

    def _elig(state, idx):
        # Fire only when the top frame is a Meeting Place host.
        return (
            bool(state.pending_stack)
            and isinstance(state.pending_stack[-1], PendingMeetingPlace)
        )

    def _apply(state, idx):
        # Give the owner one stone as a sentinel that the hook fired.
        p = state.players[idx]
        return fast_replace(
            state,
            players=tuple(
                fast_replace(p, resources=p.resources + Resources(stone=1))
                if i == idx else state.players[i]
                for i in range(2)
            ),
        )

    register_auto("after_action_space", card_id, _elig, _apply)
    try:
        cs, _env, cp = _card_state(minors=frozenset(), grain=0)
        # Give the player ownership of the synthetic card (minor_improvements).
        p = cs.players[cp]
        p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
        cs = fast_replace(cs, players=tuple(
            p if i == cp else cs.players[i] for i in range(2)
        ))
        pre_stone = cs.players[cp].resources.stone

        cs = step(cs, PlaceWorker(space="meeting_place"))
        # before-phase: just [Proceed] (no minor playable).
        assert legal_actions(cs) == [Proceed()]
        cs = step(cs, Proceed())   # flip to after-phase; after_action_space fires here

        # The hook must have fired: stone is +1 while the frame is still on the
        # stack in its after-phase (before the trailing Stop).
        assert isinstance(cs.pending_stack[-1], PendingMeetingPlace)
        assert cs.pending_stack[-1].phase == "after"
        assert cs.players[cp].resources.stone == pre_stone + 1

        cs = step(cs, Stop())
        assert cs.pending_stack == ()
    finally:
        AUTO_EFFECTS["after_action_space"] = [
            e for e in AUTO_EFFECTS.get("after_action_space", [])
            if e.card_id != card_id
        ]


def test_card_meeting_place_never_accumulates_food():
    # In card mode the slot is not refilled, and the resolver gives no food, so
    # its accumulated_amount stays 0 throughout a whole game.
    cs, env, _cp = _card_state(minors=frozenset())
    final, _trace = play_game(cs, (RandomAgent(seed=1), RandomAgent(seed=2)),
                              dealer=env.resolve)
    assert get_space(final.board, "meeting_place").accumulated_amount == 0
    assert final.mode is GameMode.CARDS
