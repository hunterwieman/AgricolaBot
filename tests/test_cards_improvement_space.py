"""Tests for the minor-play branch of the Major/Minor Improvement space
(CARD_IMPLEMENTATION_PLAN.md II.4, first in-game minor entry point).

In the card game this space is "build a major OR play a minor" (exclusive): its
placement is legal if either is possible, and once you pick the minor branch you
must play one (the OR-alternative — no decline). The Family game is unchanged
(no hand cards -> the play_minor branch is never offered).
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBuildMajor,
    CommitPlayMinor,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, minors=frozenset(), res=None):
    """Card-mode state with major_improvement forced revealed + the current
    player's hand/resources set."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "major_improvement"), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(p, hand_minors=minors,
                     resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _spaces(state):
    return {a.space for a in legal_placements(state)}


# ---------------------------------------------------------------------------
# Placement legality: major OR minor
# ---------------------------------------------------------------------------

def test_placeable_with_minor_only():
    # Playable minor, but no resources to afford any major -> still placeable.
    cs, _ = _card_state(minors=frozenset({"market_stall"}), res=Resources(grain=1))
    assert "major_improvement" in _spaces(cs)


def test_not_placeable_with_neither():
    # No playable minor and no affordable major -> not placeable.
    cs, _ = _card_state(minors=frozenset(), res=Resources())
    assert "major_improvement" not in _spaces(cs)


def test_placeable_with_major_only():
    # Affordable major, no minor in hand -> placeable (the Family-like path).
    cs, _ = _card_state(minors=frozenset(), res=Resources(clay=5))
    assert "major_improvement" in _spaces(cs)


# ---------------------------------------------------------------------------
# The exclusive OR at the parent frame
# ---------------------------------------------------------------------------

def test_both_options_offered_when_both_available():
    cs, _ = _card_state(minors=frozenset({"market_stall"}), res=Resources(clay=5, grain=1))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    acts = legal_actions(cs)
    assert ChooseSubAction(name="build_major") in acts
    assert ChooseSubAction(name="play_minor") in acts


def test_play_minor_branch_is_mandatory_and_plays():
    cs, cp = _card_state(minors=frozenset({"market_stall"}), res=Resources(grain=1))
    opp = 1 - cp
    cs = step(cs, PlaceWorker(space="major_improvement"))
    assert ChooseSubAction(name="build_major") not in legal_actions(cs)  # can't afford one

    cs = step(cs, ChooseSubAction(name="play_minor"))
    # Mandatory: only the play, no Stop.
    assert legal_actions(cs) == [CommitPlayMinor(card_id="market_stall")]

    cs = step(cs, CommitPlayMinor(card_id="market_stall"))
    assert cs.players[cp].resources.veg == 1                       # 1 grain -> 1 veg
    assert "market_stall" in cs.players[opp].hand_minors           # passing -> circulated
    # PendingPlayMinor's after-phase: only Stop to pop it.
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())                                          # pop after-phase
    # Back at the parent: minor done -> only Stop (no second action).
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())                                          # pop the parent
    assert cs.pending_stack == ()


def test_choosing_major_excludes_minor():
    cs, cp = _card_state(minors=frozenset({"market_stall"}), res=Resources(clay=5, grain=1))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, CommitBuildMajor(major_idx=0))   # Fireplace (2 clay)
    # Back at the parent: major done -> only Stop, no play_minor.
    assert legal_actions(cs) == [Stop()]


# ---------------------------------------------------------------------------
# Family game is unaffected
# ---------------------------------------------------------------------------

def test_family_major_improvement_never_offers_play_minor():
    s = setup(5)
    sp = fast_replace(get_space(s.board, "major_improvement"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "major_improvement", sp))
    cp = s.current_player
    # Even if we (illegally for family) put a minor in hand, mode gates it off.
    p = fast_replace(s.players[cp], hand_minors=frozenset({"market_stall"}),
                     resources=Resources(clay=5, grain=1))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    assert s.mode is GameMode.FAMILY
    s = step(s, PlaceWorker(space="major_improvement"))
    acts = legal_actions(s)
    assert ChooseSubAction(name="play_minor") not in acts
    assert ChooseSubAction(name="build_major") in acts


# ---------------------------------------------------------------------------
# House Redevelopment: renovate THEN optionally improvement (major OR minor).
# Its "improvement" choose delegates to PendingMajorMinorImprovement, so the
# minor branch comes through that frame; only the "can improve" gate is new.
# ---------------------------------------------------------------------------

def _house_redev_state(seed=5):
    """Card-mode state: house_redevelopment revealed; current player can renovate
    (wood, 2 rooms -> 2 clay + 1 reed) + has a playable minor (1 grain), but NO
    resources left over for a major."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "house_redevelopment"), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "house_redevelopment", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"market_stall"}),
                     resources=Resources(clay=2, reed=1, grain=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def test_house_redev_renovate_then_play_minor():
    cs, cp = _house_redev_state()
    opp = 1 - cp
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, CommitRenovate())
    cs = step(cs, Stop())   # pop PendingRenovate's after-phase -> back at parent
    # Post-renovate: the improvement option is offered (a minor is playable),
    # plus Proceed (the parent's before-phase turn-ending boundary).
    acts = legal_actions(cs)
    assert ChooseSubAction(name="improvement") in acts
    assert Proceed() in acts

    cs = step(cs, ChooseSubAction(name="improvement"))
    # Delegated to PendingMajorMinorImprovement: only play_minor (no major affordable).
    assert legal_actions(cs) == [ChooseSubAction(name="play_minor")]
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, CommitPlayMinor(card_id="market_stall"))
    assert cs.players[cp].resources.veg == 1
    assert "market_stall" in cs.players[opp].hand_minors


def test_house_redev_improvement_is_optional():
    # The minor (improvement) is an optional follow-up: Stop after renovate is legal.
    cs, cp = _house_redev_state()
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, CommitRenovate())
    # After CommitRenovate, top is PendingRenovate(after) → Stop pops it.
    assert Stop() in legal_actions(cs)
    cs = step(cs, Stop())                       # pop PendingRenovate's after-phase
    # Now at the parent frame; Proceed declines the improvement (flips to after-phase).
    assert Proceed() in legal_actions(cs)
    cs = step(cs, Proceed())                    # decline the improvement -> after-phase
    cs = step(cs, Stop())                       # pop the parent
    assert cs.pending_stack == ()               # turn ends, no minor played
    assert "market_stall" in cs.players[cp].hand_minors
