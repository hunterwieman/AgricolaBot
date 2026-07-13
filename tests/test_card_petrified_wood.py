"""Tests for Petrified Wood (minor improvement, D6; Dulcinaria Expansion).

Card text: "Immediately exchange up to 3 wood for 1 stone each." Cost: none;
prereq "2 Occupations"; PASSING (traveling minor). Surfaced WIDE via the minor
play-variant seam (migrated from the deep PendingCardChoice shape 2026-07-13):
one CommitPlayMinor per amount 0..min(3, wood on hand), the wood riding the
variant surcharge, the stone granted by the variant-aware on_play. 0 is the
zero-surcharge decline variant.
"""
import agricola.cards.petrified_wood  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitPlayMinor, Stop
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

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


def _commits(cs):
    return [a for a in legal_actions(cs)
            if isinstance(a, CommitPlayMinor) and a.card_id == "petrified_wood"]


def _commit(cs, variant):
    return next(a for a in _commits(cs) if a.variant == variant)


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
    assert "petrified_wood" in PLAY_MINOR_VARIANTS


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
# The wide variants: one commit per amount, capped at wood on hand
# ---------------------------------------------------------------------------

def test_play_offers_full_variant_range_when_wood_at_least_three():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=5),
    )
    cs = _push_minor(cs, cp)
    commits = _commits(cs)
    assert sorted(c.variant for c in commits) == ["0", "1", "2", "3"]
    # Each variant's wood surcharge is folded into its payment.
    assert sorted(c.payment.wood for c in commits) == [0, 1, 2, 3]


def test_options_capped_at_wood_on_hand():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=2),
    )
    cs = _push_minor(cs, cp)
    assert sorted(c.variant for c in _commits(cs)) == ["0", "1", "2"]


def test_zero_wood_offers_only_the_noop():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=0),
    )
    cs = _push_minor(cs, cp)
    (commit,) = _commits(cs)
    assert commit.variant == "0"
    cs = step(cs, commit)
    p = cs.players[cp]
    assert p.resources.wood == 0 and p.resources.stone == 0


# ---------------------------------------------------------------------------
# The exchange itself
# ---------------------------------------------------------------------------

def test_exchange_two_wood_for_two_stone():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=5),
    )
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "2"))
    p = cs.players[cp]
    assert p.resources.wood == 3                        # 5 - 2
    assert p.resources.stone == 2                        # +2 (1:1)
    # No choice frame: the play resolved in one step, back at the host.
    assert [type(f).__name__ for f in cs.pending_stack] == ["PendingPlayMinor"]
    assert legal_actions(cs) == [Stop()]


def test_exchange_full_three():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=4, stone=1),
    )
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "3"))
    p = cs.players[cp]
    assert p.resources.wood == 1                        # 4 - 3
    assert p.resources.stone == 4                        # 1 + 3


def test_choosing_zero_declines():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=5),
    )
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "0"))
    p = cs.players[cp]
    assert p.resources.wood == 5                        # unchanged
    assert p.resources.stone == 0                       # unchanged
    assert "petrified_wood" not in p.minor_improvements  # passing -> not kept (still played)


def test_passes_to_opponent():
    cs, cp = _state(
        cp_minors=frozenset({"petrified_wood"}),
        cp_occ=frozenset({"a", "b"}),
        cp_res=Resources(wood=3),
    )
    opp = 1 - cp
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "1"))
    p = cs.players[cp]
    assert p.resources.wood == 2 and p.resources.stone == 1
    assert "petrified_wood" not in p.minor_improvements  # passing -> not kept
    assert "petrified_wood" not in p.hand_minors         # left the hand
    assert "petrified_wood" in cs.players[opp].hand_minors  # circulated to opponent


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
