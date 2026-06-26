"""Tests for the card-game Meeting Place (CARD_IMPLEMENTATION_PLAN.md I.3).

The card Meeting Place reuses the family `meeting_place` slot (no new SPACE_IDS
id), mode-branched in the resolver: family = food accumulation + become SP
(atomic); cards = become SP (immediate, no food) then OPTIONALLY play one minor
(a PendingMeetingPlace single-optional Proceed-host, pushed only when a minor is
playable; SPACE_HOST_REFACTOR.md §7). Proceed is the decline (legal from the
start). Card mode also skips the per-round food refill on that slot, so it never
accumulates.
"""
from agricola.actions import (
    ChooseSubAction, CommitPlayMinor, PlaceWorker, Proceed, Stop,
)
from agricola.agents.base import RandomAgent, play_game
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
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


def test_no_playable_minor_is_atomic():
    cs, _env, cp = _card_state(minors=frozenset(), grain=0, sp_other=True)
    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert cs.pending_stack == ()                         # become-SP only, no frame
    assert cs.starting_player == cp


def test_card_meeting_place_never_accumulates_food():
    # In card mode the slot is not refilled, and the resolver gives no food, so
    # its accumulated_amount stays 0 throughout a whole game.
    cs, env, _cp = _card_state(minors=frozenset())
    final, _trace = play_game(cs, (RandomAgent(seed=1), RandomAgent(seed=2)),
                              dealer=env.resolve)
    assert get_space(final.board, "meeting_place").accumulated_amount == 0
    assert final.mode is GameMode.CARDS
