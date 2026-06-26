"""Tests for the card-game Basic Wish for Children (CARD_IMPLEMENTATION_PLAN.md).

Basic Wish is *atomic* in the Family game (family growth only). In the card game
it becomes a non-atomic space modeled exactly like House Redevelopment: a
PendingBasicWishForChildren parent whose mandatory first sub-action is the family
growth (a PendingFamilyGrowth primitive), then an *optional* minor improvement.
Optionality lives at the parent's Stop, not on any frame. The Family game keeps
the atomic resolver and is byte-identical.

In a real game the growth steps (family_growth choose + CommitFamilyGrowth) are
mandatory singletons the agent auto-applies; these tests drive them explicitly.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitFamilyGrowth,
    CommitPlayMinor,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType, GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_grid

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def _prep(cs, cp, *, minors):
    """Reveal Basic Wish, give the current player a 3rd room (so family growth is
    legal: people_total < num_rooms) + the given hand and 1 grain."""
    sp = fast_replace(get_space(cs.board, "basic_wish_for_children"), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "basic_wish_for_children", sp))
    cs = with_grid(cs, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})
    p = fast_replace(cs.players[cp], hand_minors=minors, resources=Resources(grain=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    return fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))


def _card_state(seed=5, *, minors):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    return _prep(cs, cp, minors=minors), cp


def _do_growth(cs):
    """Drive the mandatory family-growth sub-action and pop its after-phase."""
    assert legal_actions(cs) == [ChooseSubAction(name="family_growth")]
    cs = step(cs, ChooseSubAction(name="family_growth"))
    assert legal_actions(cs) == [CommitFamilyGrowth()]
    cs = step(cs, CommitFamilyGrowth())
    cs = step(cs, Stop())   # pop PendingFamilyGrowth's after-phase
    return cs


def test_family_growth_is_the_mandatory_first_subaction():
    cs, cp = _card_state(minors=frozenset({"market_stall"}))
    pt0 = cs.players[cp].people_total
    cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
    # Before growth: the only option is the growth sub-action (no Stop, no minor).
    assert legal_actions(cs) == [ChooseSubAction(name="family_growth")]
    cs = step(cs, ChooseSubAction(name="family_growth"))
    assert cs.players[cp].people_total == pt0      # not yet — growth runs at commit
    assert legal_actions(cs) == [CommitFamilyGrowth()]
    cs = step(cs, CommitFamilyGrowth())
    assert cs.players[cp].people_total == pt0 + 1   # newborn added


def test_growth_then_play_minor():
    cs, cp = _card_state(minors=frozenset({"market_stall"}))
    opp = 1 - cp
    cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
    cs = _do_growth(cs)
    # Post-growth: optional minor + Stop.
    acts = legal_actions(cs)
    assert ChooseSubAction(name="play_minor") in acts and Stop() in acts

    cs = step(cs, ChooseSubAction(name="play_minor"))
    assert legal_actions(cs) == [CommitPlayMinor(card_id="market_stall")]  # mandatory once chosen
    cs = step(cs, CommitPlayMinor(card_id="market_stall"))
    assert cs.players[cp].resources.veg == 1
    assert "market_stall" in cs.players[opp].hand_minors    # passing -> circulated
    assert legal_actions(cs) == [Stop()]                    # minor done -> only Stop (after-phase)
    cs = step(cs, Stop())                                   # pop PendingPlayMinor's after-phase
    cs = step(cs, Stop())                                   # pop the parent
    assert cs.pending_stack == ()


def test_minor_is_optional_decline_with_stop():
    cs, cp = _card_state(minors=frozenset({"market_stall"}))
    cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
    cs = _do_growth(cs)
    cs = step(cs, Stop())                                    # decline the minor -> pop parent
    assert cs.pending_stack == ()
    assert "market_stall" in cs.players[cp].hand_minors      # not played


def test_no_playable_minor_only_stop_after_growth():
    # Card mode is still non-atomic (growth via sub-action), but post-growth the
    # only option is Stop when no minor is playable.
    cs, cp = _card_state(minors=frozenset())
    cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
    cs = _do_growth(cs)
    assert legal_actions(cs) == [Stop()]


def test_family_basic_wish_is_atomic():
    s = setup(5)
    cp = s.current_player
    sp = fast_replace(get_space(s.board, "basic_wish_for_children"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "basic_wish_for_children", sp))
    s = with_grid(s, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})
    # Even (illegally for family) holding a minor, mode keeps Basic Wish atomic.
    p = fast_replace(s.players[cp], hand_minors=frozenset({"market_stall"}),
                     resources=Resources(grain=1))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    assert s.mode is GameMode.FAMILY
    pt0 = s.players[cp].people_total
    s = step(s, PlaceWorker(space="basic_wish_for_children"))
    assert s.pending_stack == ()                            # atomic — no frames
    assert s.players[cp].people_total == pt0 + 1            # growth happened immediately
