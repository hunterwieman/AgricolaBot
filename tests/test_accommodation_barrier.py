"""The animal-accommodation barrier (engine._reconcile_accommodation).

A DECISION-FREE animal grant (round-start collection, an on-play card gain) can push a
player over their farm's housing capacity. helpers.grant_animals adds the animals and
flags the player; the barrier — run at every decision boundary in
_advance_until_decision — surfaces a PendingAccommodate so the PLAYER chooses which to
keep (excess cooked to food) rather than the engine silently picking. This is the fix for
the seed-24592 bug: Animal Tamer fills the house (2 slots), 2 sheep are held, then an
Acorns Basket boar arrives — the two housable configs (keep 2 sheep, or trade one for the
boar) tie on total count, and the old code auto-picked (1 sheep, 1 boar). Now the player
decides.
"""
import dataclasses

import agricola.cards.acorns_basket  # noqa: F401  (registers the MinorSpec)
import agricola.cards.game_trade      # noqa: F401
import agricola.cards.young_animal_market  # noqa: F401
from agricola.canonical import from_canonical, to_canonical
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import (
    _advance_until_decision,
    _assert_animals_accommodated,
    _reconcile_accommodation,
    step,
)
from agricola.helpers import grant_animals
from agricola.actions import CommitAccommodate
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup


def _animal_tamer_two_sheep(seed=0):
    """A player with Animal Tamer (2 rooms → 2 flexible house slots) holding 2 sheep."""
    s = setup(seed)
    p0 = fast_replace(
        s.players[0],
        occupations=frozenset({"animal_tamer"}),
        animals=Animals(sheep=2),
    )
    return fast_replace(s, players=(p0, s.players[1]))


# ---------------------------------------------------------------------------
# grant_animals: the single choke point
# ---------------------------------------------------------------------------

def test_grant_animals_adds_and_flags():
    s = setup(0)
    s = grant_animals(s, 0, Animals(boar=1, cattle=1))
    assert s.players[0].animals == Animals(boar=1, cattle=1)
    assert s.players[0].animals_need_accommodation
    assert not s.players[1].animals_need_accommodation


def test_grant_animals_batches_same_moment_grants():
    # Two grants before any barrier accumulate into one over-capacity total.
    s = _animal_tamer_two_sheep()
    s = grant_animals(s, 0, Animals(boar=1))
    s = grant_animals(s, 0, Animals(cattle=1))
    assert s.players[0].animals == Animals(sheep=2, boar=1, cattle=1)  # 4 animals, 2 slots
    s, pushed = _reconcile_accommodation(s)
    assert pushed
    # One frame, over the COMBINED total — not two separate decisions.
    assert sum(isinstance(f, PendingAccommodate) for f in s.pending_stack) == 1


# ---------------------------------------------------------------------------
# The reported bug: an overflowing grant surfaces the tied choice
# ---------------------------------------------------------------------------

def test_overflow_surfaces_the_tied_choice():
    s = _animal_tamer_two_sheep()
    s = grant_animals(s, 0, Animals(boar=1))          # 2 sheep + 1 boar, 2 slots
    assert s.players[0].animals_need_accommodation

    s, pushed = _reconcile_accommodation(s)
    assert pushed
    top = s.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0
    # The flag is cleared as the player is handled (no re-push while pending).
    assert not s.players[0].animals_need_accommodation

    kept = {(a.sheep, a.boar, a.cattle) for a in legal_actions(s)}
    assert kept == {(2, 0, 0), (1, 1, 0)}             # BOTH options offered, not auto-picked


def test_commit_keep_sheep_drops_boar():
    s = _animal_tamer_two_sheep()
    s = grant_animals(s, 0, Animals(boar=1))
    s, _ = _reconcile_accommodation(s)
    food0 = s.players[0].resources.food

    s = step(s, CommitAccommodate(sheep=2, boar=0, cattle=0))
    p0 = s.players[0]
    assert p0.animals == Animals(sheep=2, boar=0, cattle=0)
    assert p0.resources.food == food0                 # no cooking improvement → boar lost, 0 food
    assert not p0.animals_need_accommodation
    assert not any(isinstance(f, PendingAccommodate) for f in s.pending_stack)


def test_commit_keep_boar_drops_sheep():
    s = _animal_tamer_two_sheep()
    s = grant_animals(s, 0, Animals(boar=1))
    s, _ = _reconcile_accommodation(s)
    s = step(s, CommitAccommodate(sheep=1, boar=1, cattle=0))
    assert s.players[0].animals == Animals(sheep=1, boar=1, cattle=0)


# ---------------------------------------------------------------------------
# The fit case: a grant that fits raises no decision
# ---------------------------------------------------------------------------

def test_fitting_grant_no_frame():
    s = setup(0)                                       # default farm: 1 empty house slot
    s = grant_animals(s, 0, Animals(boar=1))
    s, pushed = _reconcile_accommodation(s)
    assert not pushed
    assert not any(isinstance(f, PendingAccommodate) for f in s.pending_stack)
    assert not s.players[0].animals_need_accommodation  # flag cleared even with no frame
    assert s.players[0].animals.boar == 1


def test_reconcile_noop_without_any_grant():
    s = setup(0)
    out, pushed = _reconcile_accommodation(s)
    assert not pushed and out is s                      # hot-path early-out: object-identical


# ---------------------------------------------------------------------------
# Barrier wiring: it fires at the real decision boundary
# ---------------------------------------------------------------------------

def test_barrier_fires_at_work_handover():
    # _advance_until_decision must reconcile before returning the worker-placement.
    s = _animal_tamer_two_sheep()
    s = grant_animals(s, 0, Animals(boar=1))
    s = _advance_until_decision(s)
    assert isinstance(s.pending_stack[-1], PendingAccommodate)


def test_both_players_overflow_starting_player_resolves_first():
    s = _animal_tamer_two_sheep()
    p1 = fast_replace(
        s.players[1], occupations=frozenset({"animal_tamer"}), animals=Animals(sheep=2),
    )
    s = fast_replace(s, players=(s.players[0], p1))
    s = grant_animals(s, 0, Animals(boar=1))
    s = grant_animals(s, 1, Animals(boar=1))
    s, pushed = _reconcile_accommodation(s)
    assert pushed
    # Two frames; the starting player's is on TOP (resolves first), harvest convention.
    accs = [f for f in s.pending_stack if isinstance(f, PendingAccommodate)]
    assert len(accs) == 2
    assert accs[-1].player_idx == s.starting_player


# ---------------------------------------------------------------------------
# Real round-boundary path + on-play cards route through the barrier
# ---------------------------------------------------------------------------

def test_acorns_basket_overflow_at_round_start_surfaces_choice():
    # Animal Tamer + 2 sheep, Acorns Basket boar scheduled into round 2. Entering round 2
    # via the real preparation path leaves the player flagged; the barrier then asks.
    s = _animal_tamer_two_sheep()
    R = s.round_number
    s = MINORS["acorns_basket"].on_play(s, 0)          # boar onto rounds R+1, R+2
    from agricola.engine import _complete_preparation
    s = fast_replace(s, round_number=R, phase=Phase.PREPARATION)  # entering round R+1
    s = _complete_preparation(s)                        # grants + flags the boar
    assert s.players[0].animals == Animals(sheep=2, boar=1, cattle=0)
    assert s.players[0].animals_need_accommodation
    s, pushed = _reconcile_accommodation(s)
    assert pushed
    kept = {(a.sheep, a.boar, a.cattle) for a in legal_actions(s)}
    assert kept == {(2, 0, 0), (1, 1, 0)}


def test_game_trade_on_play_flags():
    s = setup(0)
    s2 = MINORS["game_trade"].on_play(s, 0)
    assert s2.players[0].animals == Animals(boar=1, cattle=1)
    assert s2.players[0].animals_need_accommodation


def test_young_animal_market_on_play_flags():
    s = setup(0)
    s2 = MINORS["young_animal_market"].on_play(s, 0)
    assert s2.players[0].animals == Animals(cattle=1)
    assert s2.players[0].animals_need_accommodation


# ---------------------------------------------------------------------------
# Backstop + serialization
# ---------------------------------------------------------------------------

def test_scoring_backstop_catches_unreconciled_overflow():
    import pytest
    s = _animal_tamer_two_sheep()
    s = grant_animals(s, 0, Animals(boar=1))           # over capacity, never reconciled
    with pytest.raises(AssertionError):
        _assert_animals_accommodated(s)


def test_backstop_passes_on_accommodatable_state():
    _assert_animals_accommodated(setup(0))             # a fresh farm is fine


def test_flag_is_default_skipped_in_canonical():
    # Family byte-identity: the default-False flag must be omitted from the JSON.
    s = setup(0)
    js = to_canonical(s.players[0])
    assert "animals_need_accommodation" not in js
    # And a set flag survives a round-trip.
    p = fast_replace(s.players[0], animals_need_accommodation=True)
    assert from_canonical(to_canonical(p)).animals_need_accommodation
