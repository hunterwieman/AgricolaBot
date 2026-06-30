"""Tests for Second Spouse (occupation C129):

  - registration as an occupation with a no-op on-play and an occupancy override;
  - the LEGALITY RELAXATION: the owner may place on an "Urgent Wish for Children" space
    occupied by one opponent, exercised through `legal_placements`;
  - "count players, not workers" tolerates an opponent's parent+newborn pair;
  - SCOPING to the urgent space ONLY: the override does NOT relax basic_wish_for_children
    (distinct from Sleeping Corner) nor any non-wish space;
  - the boundaries: not offered without ownership, not when the owner already holds it,
    and (4-player shape) not when 2+ other players hold it;
  - Family byte-identity (no card owned -> occupied wish space stays illegal).
"""
import agricola.cards.second_spouse  # noqa: F401

import dataclasses

import pytest

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.second_spouse import CARD_ID, TARGET_SPACE, _occupancy_override
from agricola.legality import OCCUPANCY_OVERRIDE_EXTENSIONS, legal_placements
from agricola.setup import setup_env

import tests.factories as f

WISH = "urgent_wish_for_children"
BASIC = "basic_wish_for_children"


def _with_occupations(state, player_idx, card_ids):
    p = state.players[player_idx]
    new_p = dataclasses.replace(p, occupations=frozenset(card_ids))
    new_players = list(state.players)
    new_players[player_idx] = new_p
    return dataclasses.replace(state, players=tuple(new_players))


def _state(seed=5, *, owner=None, space=WISH):
    """Card-mode state with `space` revealed, p0 to move. `owner` set -> that player owns
    Second Spouse."""
    cs, _env = setup_env(seed, card_pool=None)
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, space, revealed=True)
    if owner is not None:
        cs = _with_occupations(cs, owner, {CARD_ID})
    return cs


def _set_workers(cs, w, space=WISH):
    return f.with_space(cs, space, workers=w)


def _placeable(cs, space=WISH):
    return PlaceWorker(space=space) in legal_placements(cs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert _occupancy_override in OCCUPANCY_OVERRIDE_EXTENSIONS


def test_on_play_is_noop():
    cs = _state()
    spec = OCCUPATIONS[CARD_ID]
    assert spec.on_play(cs, 0) == cs


# ---------------------------------------------------------------------------
# The relaxation
# ---------------------------------------------------------------------------

def test_owner_may_use_urgent_wish_occupied_by_opponent():
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 1))   # opponent (p1) holds the urgent-wish space
    assert _placeable(cs)


def test_owner_may_use_urgent_wish_with_opponent_parent_and_newborn():
    # A normally-used wish space holds the opponent's parent + newborn = 2 workers, ONE
    # player. "Count players, not workers" must still permit the owner to use it.
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 2))
    assert _placeable(cs)


# ---------------------------------------------------------------------------
# Scoping — urgent space ONLY (distinct from Sleeping Corner)
# ---------------------------------------------------------------------------

def test_override_does_not_relax_basic_wish():
    # Card names only the Urgent space; the basic wish space stays under normal occupancy.
    cs = _state(owner=0, space=BASIC)
    cs = _set_workers(cs, (0, 1), space=BASIC)
    assert _occupancy_override(cs, BASIC) is False
    assert not _placeable(cs, space=BASIC)


def test_override_does_not_apply_to_non_wish_spaces():
    cs = _state(owner=0)
    cs = f.with_space(cs, "forest", revealed=True, workers=(0, 1))
    assert _occupancy_override(cs, "forest") is False
    assert PlaceWorker(space="forest") not in legal_placements(cs)


def test_target_space_constant():
    assert TARGET_SPACE == WISH


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_ownership():
    cs = _state(owner=None)
    cs = _set_workers(cs, (0, 1))
    assert not _placeable(cs)


def test_not_offered_when_owner_already_holds_the_space():
    cs = _state(owner=0)
    cs = _set_workers(cs, (1, 0))   # the owner (p0) is the sole occupant
    assert not _placeable(cs)
    assert _occupancy_override(cs, WISH) is False


def test_two_other_players_blocks_override():
    # 4-player shape: 2+ OTHER players holding the space -> override declines (== 1 only).
    cs = _state(owner=0)
    cs1 = _set_workers(cs, (0, 1))
    # Forge a 3-slot worker tuple so two *other* players hold the space.
    cs3 = f.with_space(cs, WISH, workers=(0, 1, 1))
    assert _occupancy_override(cs3, WISH) is False
    assert _occupancy_override(cs1, WISH) is True


# ---------------------------------------------------------------------------
# Unoccupied space — the override is irrelevant; normal legality applies
# ---------------------------------------------------------------------------

def test_unoccupied_urgent_wish_placeable_regardless():
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 0))
    assert _placeable(cs)


# ---------------------------------------------------------------------------
# Family byte-identity: without the card, an occupied wish space stays illegal
# ---------------------------------------------------------------------------

def test_family_occupied_wish_stays_illegal_without_card():
    cs = _state(owner=None)
    cs = _set_workers(cs, (0, 1))
    assert _occupancy_override(cs, WISH) is False
    assert not _placeable(cs)
