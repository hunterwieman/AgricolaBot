"""Tests for Category 4 (action-space hook, granted sub-action) on ATOMIC spaces:
Assistant Tiller (grant a Plow on Day Laborer) and Oven Firing Boy (grant a Bake
Bread on a wood space). These are optional FireTriggers whose apply_fn PUSHES an
existing primitive pending on top of the action-space host — exercising the
_apply_fire_trigger "record-the-fire-before-applying" fix that keeps the pushed
sub-decision on top.
"""
from agricola.actions import CommitBake, FireTrigger, PlaceWorker, Proceed, Stop
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state():
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own_occ(state, idx, card_id):
    p = fast_replace(state.players[idx], occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5) if g[r][c].cell_type == CellType.FIELD)


# ---------------------------------------------------------------------------
# Assistant Tiller — grant a plow on Day Laborer
# ---------------------------------------------------------------------------

def test_assistant_tiller_grants_a_plow():
    s = _own_occ(_card_state(), 0, "assistant_tiller")
    food0 = s.players[0].resources.food
    fields0 = _num_fields(s, 0)

    s = step(s, PlaceWorker(space="day_laborer"))
    s = step(s, Proceed())                       # Day Laborer: +2 food, flip to after
    assert s.players[0].resources.food == food0 + 2
    la = legal_actions(s)
    assert FireTrigger(card_id="assistant_tiller") in la
    assert Stop() in la

    s = step(s, FireTrigger(card_id="assistant_tiller"))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    plows = legal_actions(s)
    s = step(s, plows[0])                         # commit one plow (auto-pops PendingPlow)
    assert _num_fields(s, 0) == fields0 + 1
    # Back at the host (after-phase); the grant is spent → only Stop remains.
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack


def test_assistant_tiller_decline():
    s = _own_occ(_card_state(), 0, "assistant_tiller")
    fields0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="day_laborer"))
    s = step(s, Proceed())
    s = step(s, Stop())                          # decline the plow
    assert not s.pending_stack
    assert _num_fields(s, 0) == fields0


# ---------------------------------------------------------------------------
# Oven Firing Boy — grant a Bake Bread on a wood space
# ---------------------------------------------------------------------------

def test_oven_firing_boy_grants_a_bake():
    s = _own_occ(_card_state(), 0, "oven_firing_boy")
    s = with_majors(s, owner_by_idx={0: 0})      # Fireplace (index 0): grain->2 food on bake
    s = with_resources(s, 0, grain=2)
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())                       # take the accumulated wood, flip to after
    assert FireTrigger(card_id="oven_firing_boy") in legal_actions(s)

    s = step(s, FireTrigger(card_id="oven_firing_boy"))
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    s = step(s, CommitBake(grain=1))             # Fireplace: 1 grain -> 2 food (auto-pops)
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].resources.grain == 1
    assert legal_actions(s) == [Stop()]          # grant spent
    s = step(s, Stop())
    assert not s.pending_stack


def test_oven_firing_boy_not_offered_without_a_usable_bake():
    # Owns the card + a baker, but has no grain -> _can_bake_bread is False.
    s = _own_occ(_card_state(), 0, "oven_firing_boy")
    s = with_majors(s, owner_by_idx={0: 0})
    s = with_resources(s, 0, grain=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert legal_actions(s) == [Stop()]          # no bake possible -> grant not offered
