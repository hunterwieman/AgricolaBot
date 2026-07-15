"""Tests for Seed Servant (occupation, E115; Ephipparius): "Each time after you
use the 'Grain Seeds' or 'Vegetable Seeds' action space, you can take a 'Bake
bread' or 'Sow' action, respectively."

An OPTIONAL trigger on the two atomic seed spaces' `after_action_space` window
(explicit "after" in the text) with strict slash-correlation ("respectively"):
Grain Seeds -> a granted Bake Bread, Vegetable Seeds -> a granted Sow, never
crosswise. Coverage: registration (trigger on the after window + both space
hooks); the bake grant end-to-end off a real Grain Seeds use, with the
just-taken grain counting toward bakeability; the sow grant end-to-end off a
real Vegetable Seeds use, with the just-taken vegetable counting toward
sowability; eligibility boundaries (no baker -> no offer at Grain Seeds even
when sowable; nothing sowable -> no offer at Vegetable Seeds even when
bakeable — the strict correlation); decline (Stop without firing); once per
use; opponent use offers nothing; hand-only inert.
"""
import agricola.cards.seed_servant  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitBake, CommitSow, FireTrigger, PlaceWorker, Proceed, Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread, PendingSow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid, with_majors, with_resources, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id="seed_servant")


def _card_state():
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own(state, idx=0):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {"seed_servant"})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_veg(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(g[r][c].veg for r in range(3) for c in range(5))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_seed_servant_registered():
    assert "seed_servant" in OCCUPATIONS
    # The trigger lives on the AFTER window (explicit "after" in the text) and
    # is optional (not mandatory). Subset checks, never exact-set.
    entry = next(e for e in TRIGGERS.get("after_action_space", [])
                 if e.card_id == "seed_servant")
    assert not entry.mandatory
    assert not any(e.card_id == "seed_servant"
                   for e in TRIGGERS.get("before_action_space", []))
    # Both atomic seed spaces are hooked (owner-only).
    assert "seed_servant" in OWN_ACTION_HOOK_CARDS.get("grain_seeds", set())
    assert "seed_servant" in OWN_ACTION_HOOK_CARDS.get("vegetable_seeds", set())


# ---------------------------------------------------------------------------
# Grain Seeds -> a granted Bake Bread (end-to-end; just-taken grain counts)
# ---------------------------------------------------------------------------

def test_bake_granted_after_grain_seeds_with_just_taken_grain():
    # 0 grain + a Fireplace: only the grain the space itself provides makes a
    # bake possible — the after-timing means it counts.
    s = _own(_card_state())
    s = with_majors(s, owner_by_idx={0: 0})       # Fireplace: grain -> 2 food
    s = with_resources(s, 0, grain=0)
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="grain_seeds"))
    # Before-phase: the grant is NOT offered (after-window card; and no grain yet).
    assert legal_actions(s) == [Proceed()]
    s = step(s, Proceed())                        # +1 grain, flip to after
    assert s.players[0].resources.grain == 1
    la = legal_actions(s)
    assert _FIRE in la
    assert Stop() in la

    s = step(s, _FIRE)
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    assert s.pending_stack[-1].initiated_by_id == "card:seed_servant"
    s = step(s, CommitBake(grain=1))              # Fireplace: 1 grain -> 2 food
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].resources.grain == 0
    assert legal_actions(s) == [Stop()]           # bake after-phase
    s = step(s, Stop())                           # pop the bake frame
    # Back at the host's after-phase; the grant is spent (once per use).
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack


def test_bake_not_offered_without_a_baker_even_when_sowable():
    # Strict correlation: at Grain Seeds only a BAKE is granted. A player who
    # could sow (empty field + the just-taken grain) but owns no baking
    # improvement gets nothing.
    s = _own(_card_state())
    s = with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    s = with_resources(s, 0, grain=0)
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = step(s, Proceed())
    assert s.players[0].resources.grain == 1      # sowable, but not bakeable
    assert legal_actions(s) == [Stop()]           # no sow grant here


# ---------------------------------------------------------------------------
# Vegetable Seeds -> a granted Sow (end-to-end; just-taken veg counts)
# ---------------------------------------------------------------------------

def _veg_seeds_state():
    """Owner with one empty field and no crops; Vegetable Seeds revealed
    (it is a Stage-3 space)."""
    s = _own(_card_state())
    s = with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    s = with_resources(s, 0, grain=0, veg=0)
    return with_space(s, "vegetable_seeds", revealed=True)


def test_sow_granted_after_vegetable_seeds_with_just_taken_veg():
    s = _veg_seeds_state()
    s = step(s, PlaceWorker(space="vegetable_seeds"))
    assert legal_actions(s) == [Proceed()]        # nothing in the before-window
    s = step(s, Proceed())                        # +1 veg, flip to after
    assert s.players[0].resources.veg == 1
    la = legal_actions(s)
    assert _FIRE in la
    assert Stop() in la

    s = step(s, _FIRE)
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.pending_stack[-1].initiated_by_id == "card:seed_servant"
    assert s.pending_stack[-1].max_fields == 0    # the full, uncapped Sow action
    s = step(s, CommitSow(grain=0, veg=1))
    assert s.players[0].resources.veg == 0
    assert _field_veg(s, 0) > 0                   # the vegetable is in the field
    assert legal_actions(s) == [Stop()]           # sow after-phase
    s = step(s, Stop())                           # pop the sow frame
    assert legal_actions(s) == [Stop()]           # grant spent (once per use)
    s = step(s, Stop())
    assert not s.pending_stack


def test_sow_not_offered_when_nothing_sowable_even_when_bakeable():
    # Strict correlation: at Vegetable Seeds only a SOW is granted. A player
    # who could bake (Fireplace + grain) but has no empty field gets nothing.
    s = _own(_card_state())
    s = with_majors(s, owner_by_idx={0: 0})       # Fireplace
    s = with_resources(s, 0, grain=2, veg=0)      # bakeable; no field at all
    s = with_space(s, "vegetable_seeds", revealed=True)
    s = step(s, PlaceWorker(space="vegetable_seeds"))
    s = step(s, Proceed())
    assert legal_actions(s) == [Stop()]           # no bake grant here


# ---------------------------------------------------------------------------
# Decline / opponent / hand-only
# ---------------------------------------------------------------------------

def test_grant_is_declinable():
    s = _own(_card_state())
    s = with_majors(s, owner_by_idx={0: 0})
    s = with_resources(s, 0, grain=0)
    food0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = step(s, Proceed())
    assert _FIRE in legal_actions(s)
    s = step(s, Stop())                           # decline: Stop without firing
    assert not s.pending_stack
    assert s.players[0].resources.grain == 1      # the pickup stays
    assert s.players[0].resources.food == food0   # no bake happened


def test_opponent_use_offers_nothing():
    # Player 0 owns the card; player 1 uses Grain Seeds. The hook is
    # owner-only, so the space stays on the atomic fast path — no host frame,
    # no trigger.
    s = _own(_card_state())                       # player 0 owns
    s = fast_replace(s, current_player=1)
    s = with_majors(s, owner_by_idx={0: 1})       # even a bakeable opponent
    s = with_resources(s, 1, grain=0)
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not s.pending_stack                    # resolved atomically
    assert s.players[1].resources.grain == 1


def test_hand_only_is_inert():
    # In hand but not played: no hosting, no trigger.
    s = _card_state()
    p = s.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"seed_servant"})
    s = fast_replace(s, players=(p, s.players[1]))
    s = with_majors(s, owner_by_idx={0: 0})
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not s.pending_stack                    # atomic fast path
    assert s.players[0].resources.grain == 1
