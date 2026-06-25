"""Tests for the card-game foundation: the GameMode field, private hands on
PlayerState, mode-aware setup / placement legality, and the canonical
default-skip that keeps Family states byte-identical.

This is the Part I scaffolding from CARD_IMPLEMENTATION_PLAN.md (I.1, I.5, I.6).
The card-playing spaces (lessons, meeting_place_cards) and the play-card pendings
are NOT here yet — they land with the play-card foundation (II.4) — so a CARDS
game so far plays as the Family board minus Side Job / Meeting Place.
"""
import pytest

from agricola import canonical
from agricola.agents.base import RandomAgent, play_game
from agricola.constants import GameMode
from agricola.legality import (
    CARD_GAME_LEGALITY,
    FAMILY_GAME_LEGALITY,
    legal_placements,
)
from agricola.replace import fast_replace
from agricola.scoring import score
from agricola.setup import CardPool, _deal_hands, setup, setup_env


def _pool(n: int = 20) -> CardPool:
    """A synthetic card pool large enough to deal from (real card-spec loading
    lands with the play-card foundation; dealing only needs ids)."""
    return CardPool(
        occupations=tuple(f"occ{i}" for i in range(n)),
        minors=tuple(f"min{i}" for i in range(n)),
    )


# ---------------------------------------------------------------------------
# Family game is unchanged (default mode, empty hands)
# ---------------------------------------------------------------------------

def test_family_setup_defaults_to_family_mode_with_empty_hands():
    s = setup(7)
    assert s.mode is GameMode.FAMILY
    for p in s.players:
        assert p.hand_occupations == frozenset()
        assert p.hand_minors == frozenset()


def test_family_setup_is_deterministic_and_stable_across_seed():
    # Two builds from the same seed are identical; the family RNG path is unchanged.
    assert canonical.dumps(setup(42)) == canonical.dumps(setup(42))


# ---------------------------------------------------------------------------
# Card-game setup: mode + dealt hands
# ---------------------------------------------------------------------------

def test_card_setup_sets_mode_and_deals_disjoint_hands():
    state, _env = setup_env(123, card_pool=_pool())
    assert state.mode is GameMode.CARDS
    p0, p1 = state.players
    assert len(p0.hand_occupations) == 7 and len(p0.hand_minors) == 7
    assert len(p1.hand_occupations) == 7 and len(p1.hand_minors) == 7
    # Dealt without replacement → the two players' hands never overlap.
    assert p0.hand_occupations.isdisjoint(p1.hand_occupations)
    assert p0.hand_minors.isdisjoint(p1.hand_minors)


def test_card_setup_is_deterministic():
    a, _ = setup_env(123, card_pool=_pool())
    b, _ = setup_env(123, card_pool=_pool())
    assert canonical.dumps(a) == canonical.dumps(b)


def test_deal_hands_rejects_too_small_pool():
    # Needs >= 2 * HAND_SIZE = 14 of each type.
    with pytest.raises(ValueError):
        setup_env(1, card_pool=_pool(n=13))


# ---------------------------------------------------------------------------
# Mode-aware placement legality
# ---------------------------------------------------------------------------

def test_card_legality_drops_family_only_spaces():
    # Side Job and the food-accumulation Meeting Place are Family-only.
    assert "side_job" in FAMILY_GAME_LEGALITY
    assert "meeting_place" in FAMILY_GAME_LEGALITY
    assert "side_job" not in CARD_GAME_LEGALITY
    assert "meeting_place" not in CARD_GAME_LEGALITY
    # Everything else carries over.
    assert "farmland" in CARD_GAME_LEGALITY
    assert "forest" in CARD_GAME_LEGALITY


def test_legal_placements_dispatches_on_mode():
    cs, _ = setup_env(123, card_pool=_pool())
    card_spaces = {p.space for p in legal_placements(cs)}
    assert "side_job" not in card_spaces
    assert "meeting_place" not in card_spaces
    assert "farmland" in card_spaces

    # The same state relabeled FAMILY surfaces the family-only spaces again.
    fam = fast_replace(cs, mode=GameMode.FAMILY)
    fam_spaces = {p.space for p in legal_placements(fam)}
    assert "meeting_place" in fam_spaces


# ---------------------------------------------------------------------------
# Canonical default-skip (keeps Family JSON byte-identical, emits for cards)
# ---------------------------------------------------------------------------

def test_family_json_omits_card_fields():
    d = canonical.dumps(setup(7))
    assert '"mode"' not in d
    assert "hand_occupations" not in d
    assert "hand_minors" not in d


def test_card_json_emits_card_fields_and_round_trips():
    cs, _ = setup_env(123, card_pool=_pool())
    d = canonical.dumps(cs)
    assert '"mode"' in d
    assert "hand_occupations" in d
    restored = canonical.loads(d)
    assert restored == cs
    assert hash(restored) == hash(cs)
    assert canonical.dumps(restored) == d  # dumps stable


def test_family_round_trip_unchanged():
    s = setup(7)
    d = canonical.dumps(s)
    assert canonical.loads(d) == s
    assert hash(canonical.loads(d)) == hash(s)
    assert canonical.dumps(canonical.loads(d)) == d


# ---------------------------------------------------------------------------
# Hash distinguishes states that differ only in the new card fields
# (the transposition table keys on the GameState object, so == must imply hash==,
#  and states differing in a card field must be distinguishable).
# ---------------------------------------------------------------------------

def test_hash_distinguishes_mode():
    s = setup(7)
    assert fast_replace(s, mode=GameMode.CARDS) != s
    assert hash(fast_replace(s, mode=GameMode.CARDS)) != hash(s)


def test_hash_distinguishes_hands():
    s = setup(7)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset({"tutor"}))
    s2 = fast_replace(s, players=(p0, s.players[1]))
    assert s2 != s
    assert hash(s2) != hash(s)


# ---------------------------------------------------------------------------
# A full random CARDS game plays end-to-end with the mode preserved
# ---------------------------------------------------------------------------

def test_card_game_plays_to_scoring():
    cs, env = setup_env(123, card_pool=_pool())
    final, _trace = play_game(cs, (RandomAgent(seed=1), RandomAgent(seed=2)),
                              dealer=env.resolve)
    assert final.mode is GameMode.CARDS
    # Scoring runs without error for both seats.
    score(final, 0)
    score(final, 1)
    # No card-playing space is wired yet, so hands are untouched by play.
    for p in final.players:
        assert len(p.hand_occupations) == 7 and len(p.hand_minors) == 7
