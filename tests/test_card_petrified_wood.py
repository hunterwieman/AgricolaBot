"""Tests for Petrified Wood (minor improvement, D6; Dulcinaria Expansion).

Card text: "Immediately exchange up to 3 wood for 1 stone each." Cost: none;
prereq "2 Occupations"; PASSING (traveling minor). On play it offers an amount choice (0..3,
capped at wood on hand) and trades that many wood for the same number of stone
(strict 1:1); 0 is a valid choice (the player may decline entirely).
"""
import agricola.cards.petrified_wood  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitCardChoice, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARD_CHOICE_RESOLVERS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingCardChoice, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("petrified_wood",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5, *, cp_minors=frozenset(), cp_res=None, cp_occ=frozenset()):
    """A 2-player card state with the current player's hand/occupations/resources set."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_minors": cp_minors, "occupations": cp_occ}
    if cp_res is not None:
        changes["resources"] = cp_res
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


def _play(cs, cp):
    """Play Petrified Wood; return the state paused at its PendingCardChoice."""
    cs = _push_minor(cs, cp)
    return step(cs, sole_play_minor(cs, "petrified_wood"))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "petrified_wood" in MINORS
    spec = MINORS["petrified_wood"]
    assert spec.min_occupations == 2
    assert spec.max_occupations is None
    assert spec.cost.resources == Resources()        # no cost
    assert spec.cost.animals == Animals()             # no animal cost
    assert spec.passing_left is True   # traveling minor (passing_left='X')
    assert spec.vps == 0
    assert "petrified_wood" in CARD_CHOICE_RESOLVERS


# ---------------------------------------------------------------------------
# Prerequisite: 2 occupations
# ---------------------------------------------------------------------------

def test_prereq_needs_two_occupations():
    spec = MINORS["petrified_wood"]
    cs, cp = _state(cp_occ=frozenset({"a"}))            # only 1 occupation
    assert not prereq_met(spec, cs, cp)
    cs, cp = _state(cp_occ=frozenset({"a", "b"}))       # 2 occupations
    assert prereq_met(spec, cs, cp)
    cs, cp = _state(cp_occ=frozenset({"a", "b", "c"}))  # more than 2 still fine
    assert prereq_met(spec, cs, cp)


def test_playable_gates_on_prereq_only():
    # Holds the card, 2 occupations, no cost -> playable regardless of wood.
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=0),
    )
    assert playable_minors(cs, cp) == ["petrified_wood"]
    # Prereq unmet (1 occupation) -> not playable.
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a"}),
        cp_res=Resources(wood=3),
    )
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play: the amount choice frame + the 1:1 exchange
# ---------------------------------------------------------------------------

def test_play_offers_full_choice_when_wood_at_least_three():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=5),
    )
    cs = _play(cs, cp)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.player_idx == cp
    assert top.options == (0, 1, 2, 3)                  # "up to 3"
    # Exactly one CommitCardChoice per option, NO Stop/decline action.
    assert legal_actions(cs) == [CommitCardChoice(index=i) for i in range(4)]


def test_exchange_two_wood_for_two_stone():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=5),
    )
    cs = _play(cs, cp)
    cs = step(cs, CommitCardChoice(index=2))            # options[2] == 2 wood
    p = cs.players[cp]
    assert p.resources.wood == 3                        # 5 - 2
    assert p.resources.stone == 2                        # +2 (1:1)
    # Choice frame popped; back at the PendingPlayMinor host (only Stop remains).
    assert [type(f).__name__ for f in cs.pending_stack] == ["PendingPlayMinor"]
    assert legal_actions(cs) == [Stop()]


def test_passes_to_opponent():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=3),
    )
    opp = 1 - cp
    cs = _play(cs, cp)
    cs = step(cs, CommitCardChoice(index=1))
    p = cs.players[cp]
    assert "petrified_wood" not in p.minor_improvements  # passing -> not kept
    assert "petrified_wood" not in p.hand_minors         # left the hand
    assert "petrified_wood" in cs.players[opp].hand_minors  # circulated to opponent
    # The choice frame resolved for the PLAYER (the hand-transfer precedes on_play).


# ---------------------------------------------------------------------------
# Eligibility boundaries: the option set is capped at wood on hand
# ---------------------------------------------------------------------------

def test_options_capped_at_wood_on_hand():
    # 2 wood -> can only choose 0, 1 or 2 (never an illegal over-spend to 3).
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=2),
    )
    cs = _play(cs, cp)
    assert cs.pending_stack[-1].options == (0, 1, 2)
    cs = step(cs, CommitCardChoice(index=2))            # exchange both wood
    p = cs.players[cp]
    assert p.resources.wood == 0
    assert p.resources.stone == 2


def test_zero_wood_is_a_singleton_noop():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=0),
    )
    cs = _play(cs, cp)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.options == (0,)                          # only the no-op
    assert legal_actions(cs) == [CommitCardChoice(index=0)]
    cs = step(cs, CommitCardChoice(index=0))
    p = cs.players[cp]
    assert p.resources.wood == 0 and p.resources.stone == 0


# ---------------------------------------------------------------------------
# Optionality: choosing 0 declines the exchange entirely
# ---------------------------------------------------------------------------

def test_choosing_zero_declines():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=5),
    )
    wood0 = cs.players[cp].resources.wood
    stone0 = cs.players[cp].resources.stone
    cs = _play(cs, cp)
    cs = step(cs, CommitCardChoice(index=0))            # options[0] == 0 -> decline
    p = cs.players[cp]
    assert p.resources.wood == wood0                    # unchanged
    assert p.resources.stone == stone0                  # unchanged
    assert "petrified_wood" not in p.minor_improvements  # passing -> not kept (still played)


def test_exchange_full_three():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=4, stone=1),
    )
    cs = _play(cs, cp)
    cs = step(cs, CommitCardChoice(index=3))            # exchange the max 3
    p = cs.players[cp]
    assert p.resources.wood == 1                        # 4 - 3
    assert p.resources.stone == 4                        # 1 + 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
