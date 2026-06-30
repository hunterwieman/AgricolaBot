"""Tests for Abort Oriel (minor improvement, Corbarius C #32).

Card text: "You can no longer play this card when any player (including you) has 5
or more cards in front of them." Clarification: "may be played as one's fifth
card." Cost 2 Clay; 3 printed VPs; no on-play effect.

Coverage: registration, the play-time prerequisite (own/opponent boundaries at
4 vs 5 cards-in-front; majors NOT counted; the "fifth card" boundary), the
real-flow play (clay paid, card kept, no on_play side effect), and the 3 VPs
scoring automatically from the kept card.
"""
import agricola.cards.abort_oriel  # noqa: F401

from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_pending_stack, with_resources
from tests.test_utils import sole_play_minor

CARD_ID = "abort_oriel"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_cards(state, idx, *, occupations=frozenset(), minors=frozenset()):
    """Set player `idx`'s played occupations + minor improvements (cards in front)."""
    p = fast_replace(state.players[idx],
                     occupations=frozenset(occupations),
                     minor_improvements=frozenset(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_with_cost_and_vps():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(clay=2)
    assert spec.vps == 3
    assert spec.passing_left is False          # kept in tableau, not passing
    assert spec.on_play is MINORS[CARD_ID].on_play  # no custom on_play needed
    assert spec.prereq is not None


# ---------------------------------------------------------------------------
# Prerequisite — own-player boundary (the "fifth card" clarification)
# ---------------------------------------------------------------------------

def test_prereq_owner_below_five_ok():
    s = setup(0)
    # Owner has 4 cards in front (2 occ + 2 minors); opponent empty -> playable
    # (this would be the 5th card — exactly the clarification).
    s = _set_cards(s, 0, occupations={"a", "b"}, minors={"x", "y"})
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_owner_at_five_blocked():
    s = setup(0)
    # Owner already at 5 cards in front -> can no longer play.
    s = _set_cards(s, 0, occupations={"a", "b", "c"}, minors={"x", "y"})
    assert not prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# Prerequisite — opponent boundary ("any player, including you")
# ---------------------------------------------------------------------------

def test_prereq_opponent_at_five_blocks_play():
    s = setup(0)
    # Owner has 0 cards, but the OPPONENT has 5 -> still blocked.
    s = _set_cards(s, 1, occupations={"a", "b", "c"}, minors={"x", "y"})
    assert not prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_opponent_at_four_ok():
    s = setup(0)
    s = _set_cards(s, 1, occupations={"a", "b"}, minors={"x", "y"})  # opp at 4
    assert prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# Majors are NOT "cards in front of you"
# ---------------------------------------------------------------------------

def test_majors_do_not_count_toward_five():
    s = setup(0)
    # 4 cards in front + every major owned: majors are tiles, not cards -> still
    # playable.
    s = _set_cards(s, 0, occupations={"a", "b"}, minors={"x", "y"})
    n_majors = len(s.board.major_improvement_owners)
    owners = tuple(0 for _ in range(n_majors))
    s = fast_replace(s, board=fast_replace(s.board, major_improvement_owners=owners))
    assert prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# Real-flow play — clay paid, card kept, no on_play side effect
# ---------------------------------------------------------------------------

def test_play_keeps_card_and_pays_clay():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    cs = with_resources(cs, cp, clay=3, wood=2)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p = cs.players[cp]
    assert CARD_ID in p.minor_improvements          # kept (non-passing)
    assert CARD_ID not in p.hand_minors             # left hand
    assert p.resources.clay == 1                    # paid 2 clay (3 -> 1)
    assert p.resources.wood == 2                    # untouched (no other cost / effect)


# ---------------------------------------------------------------------------
# Scoring — 3 VPs from the kept card
# ---------------------------------------------------------------------------

def test_kept_card_scores_three_vps():
    s = setup(0)
    base, _ = score(s, 0)
    s1 = _set_cards(s, 0, minors={CARD_ID})
    t1, bd1 = score(s1, 0)
    assert bd1.card_points == 3
    assert t1 == base + 3
