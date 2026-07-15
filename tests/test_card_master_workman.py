import agricola.cards.master_workman  # noqa: F401  (registers the card)

"""Tests for Master Workman (occupation, Artifex A126).

Card text: "Each time before you use an action space card on round spaces
1/2/3/4, you get 1 wood/clay/reed/stone."

A ``before_action_space`` automatic effect keyed on the used space's
``revealed_round``: round 1 -> wood, 2 -> clay, 3 -> reed, 4 -> stone; no gain on
any other round space or a permanent. No hook (the stage-1 spaces are all
non-atomic hosts). Covers the four-round mapping, the out-of-range boundary, and
the not-owned no-op.
"""
import pytest

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_space

_POOL = CardPool(
    occupations=("master_workman",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return with_current_player(s, 0)


def _own(state, idx=0):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {"master_workman"})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_for(state, space_id, round_number):
    """Reveal `space_id` as the given round space, stocked so it is placeable."""
    return with_space(state, space_id, revealed=True,
                      revealed_round=round_number, accumulated_amount=1)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "master_workman" in OCCUPATIONS
    autos = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert "master_workman" in autos


# ---------------------------------------------------------------------------
# The round -> resource mapping (fired via a real Sheep Market placement)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("round_number,resource", [
    (1, "wood"), (2, "clay"), (3, "reed"), (4, "stone"),
])
def test_round_space_grants_matched_resource(round_number, resource):
    # Sheep Market is a stage-1 non-atomic host; put it on round space N and use it.
    s = _own(_reveal_for(_state(), "sheep_market", round_number))
    before = s.players[0].resources
    s = step(s, PlaceWorker(space="sheep_market"))
    after = s.players[0].resources
    # The before_action_space auto fired at the host push: +1 of the matched
    # resource, and no OTHER building resource moved.
    assert getattr(after, resource) == getattr(before, resource) + 1
    for other in ("wood", "clay", "reed", "stone"):
        if other != resource:
            assert getattr(after, other) == getattr(before, other)


def test_no_gain_outside_rounds_1_to_4():
    # A round-8 stage space (revealed_round 8) is outside {1,2,3,4} -> no gain,
    # even though it is hosted and the auto is consulted.
    s = _own(_reveal_for(_state(), "sheep_market", 8))
    before = s.players[0].resources
    s = step(s, PlaceWorker(space="sheep_market"))
    got = s.players[0].resources
    for r in ("wood", "clay", "reed", "stone"):
        assert getattr(got, r) == getattr(before, r)


def test_not_owned_no_gain():
    # Nobody owns Master Workman -> Sheep Market resolves with no building-resource
    # gain (round space 1 would otherwise give wood).
    s = _reveal_for(_state(), "sheep_market", 1)
    before = s.players[0].resources.wood
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.players[0].resources.wood == before
