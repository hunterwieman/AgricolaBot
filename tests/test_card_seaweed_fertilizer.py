import agricola.cards.seaweed_fertilizer  # noqa: F401

"""Tests for Seaweed Fertilizer (minor improvement, Corbarius C73).

Card text: "Each time after you take an unconditional \"Sow\" action, you get
1 grain from the general supply. From round 11 on, you can get 1 vegetable
instead."

USER RULING (2026-07-20): "unconditional" = a PendingSow with max_fields == 0
AND crops_only == False AND required_crop is None. Action-space sows (Grain
Utilization, Cultivation) qualify; capped / crops-only / forced-crop grants do
not.

Coverage: registration (subset checks); the after-sow Stop gate (Stop withheld
until the mandatory trigger fires, restored after it resolves); the pre-round-11
grain singleton; the round-11+ grain/veg choice (veg chosen); "each time" —
fires on a Cultivation sow too; a restricted sow (capped / crops-only /
forced-crop) does not fire it and Stop is immediate; once per sow action
(triggers_resolved); the opponent's sow does not fire it; the not-owned no-gate
(Family/no-op path).
"""
from agricola.actions import (
    ChooseSubAction,
    CommitCardChoice,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARD_CHOICE_RESOLVERS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_current_player, with_pending_stack, with_resources

CARD = "seaweed_fertilizer"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD,) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return with_current_player(s, 0)


def _own(state, idx=0):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {CARD})
        if i == idx else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _with_empty_fields(state, idx, cells):
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _sow_grain(state, space="grain_utilization"):
    """Drive the real flow: place at `space`, choose sow, commit a 1-grain sow.

    Returns the state right after CommitSow (the sow host's after-phase)."""
    state = _reveal(state, space)
    state = step(state, PlaceWorker(space=space))
    state = step(state, ChooseSubAction(name="sow"))
    sow = next(a for a in legal_actions(state)
               if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    return step(state, sow)


def _fire_here(state):
    """The Seaweed Fertilizer FireTrigger among the current legal actions (or None)."""
    return next((a for a in legal_actions(state)
                 if isinstance(a, FireTrigger) and a.card_id == CARD), None)


def _stop_here(state):
    return any(isinstance(a, Stop) for a in legal_actions(state))


# ---------------------------------------------------------------------------
# Registration (subset checks, never exact-set)
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD in MINORS
    assert MINORS[CARD].cost == Cost(resources=Resources(food=2))
    entries = {e.card_id: e for e in TRIGGERS.get("after_sow", [])}
    assert CARD in entries
    assert entries[CARD].mandatory is True
    assert CARD in CARD_CHOICE_RESOLVERS


# ---------------------------------------------------------------------------
# The Stop gate + the pre-round-11 grain singleton
# ---------------------------------------------------------------------------

def test_gate_withholds_stop_and_grants_grain_pre_round_11():
    s = _own(_state())
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1)
    s = _sow_grain(s)
    # After-phase: the mandatory trigger withholds Stop until it fires.
    fire = _fire_here(s)
    assert fire is not None
    assert not _stop_here(s)
    s = step(s, fire)
    # Pre-round-11 the choice is the grain singleton.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.options == ("grain",)
    s = step(s, CommitCardChoice(index=0))
    # Sowed the 1 supply grain, then gained 1 back from the general supply.
    assert s.players[0].resources.grain == 1
    assert s.players[0].farmyard.grid[1][0].grain > 0
    # Resolved: Stop is restored and the trigger is not re-offered (once per sow).
    assert _stop_here(s)
    assert _fire_here(s) is None


def test_round_10_still_grain_only():
    s = _own(_state())
    s = fast_replace(s, round_number=10)
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1)
    s = _sow_grain(s)
    s = step(s, _fire_here(s))
    assert s.pending_stack[-1].options == ("grain",)


def test_round_11_offers_veg_and_grants_it():
    s = _own(_state())
    s = fast_replace(s, round_number=11)
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1)
    s = _sow_grain(s)
    s = step(s, _fire_here(s))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.options == ("grain", "veg")
    s = step(s, CommitCardChoice(index=1))   # veg
    assert s.players[0].resources.veg == 1
    assert s.players[0].resources.grain == 0   # the sown grain, not replaced
    assert _stop_here(s)


def test_fires_on_cultivation_sow_too():
    # "Each time": the other action-space sow host fires it as well.
    s = _own(_state())
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1)
    s = _sow_grain(s, "cultivation")
    assert _fire_here(s) is not None
    assert not _stop_here(s)


# ---------------------------------------------------------------------------
# Restricted sows do NOT fire it (user ruling 2026-07-20)
# ---------------------------------------------------------------------------

def _restricted_sow_after_phase(pending_kwargs):
    """Push a restricted PendingSow directly (boundary case — no convenient real
    restricted-grant flow in this file), commit a real 1-grain sow through
    legal_actions + step, and return the after-phase state."""
    s = _own(_state())
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1)
    s = with_pending_stack(s, [PendingSow(
        player_idx=0, initiated_by_id="test", **pending_kwargs)])
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    return step(s, sow)


def test_capped_sow_does_not_fire():
    s = _restricted_sow_after_phase({"max_fields": 1})
    assert _fire_here(s) is None
    assert _stop_here(s)   # no gate: Stop available immediately
    assert s.players[0].resources.grain == 0   # no grain granted


def test_crops_only_sow_does_not_fire():
    s = _restricted_sow_after_phase({"crops_only": True})
    assert _fire_here(s) is None
    assert _stop_here(s)
    assert s.players[0].resources.grain == 0


def test_forced_crop_sow_does_not_fire():
    s = _restricted_sow_after_phase({"required_crop": "grain"})
    assert _fire_here(s) is None
    assert _stop_here(s)
    assert s.players[0].resources.grain == 0


def test_unrestricted_direct_push_does_fire():
    # Control for the three above: the same direct-push idiom with the default
    # (unconditional) PendingSow DOES gate — the restriction, not the idiom,
    # is what suppresses the trigger.
    s = _restricted_sow_after_phase({})
    assert _fire_here(s) is not None
    assert not _stop_here(s)


# ---------------------------------------------------------------------------
# Opponent's sow / not-owned
# ---------------------------------------------------------------------------

def test_opponents_sow_does_not_fire():
    # Player 0 owns the card; player 1 sows. No trigger, no gate.
    s = _own(_state(), 0)
    s = with_current_player(s, 1)
    s = _with_empty_fields(s, 1, [(1, 0)])
    s = with_resources(s, 1, grain=1)
    s = _sow_grain(s)
    assert _fire_here(s) is None
    assert _stop_here(s)
    assert s.players[0].resources.grain == 0   # owner gained nothing


def test_not_owned_no_gate():
    # Nobody played the card: the sow after-phase is the plain Family shape —
    # Stop immediately, no Seaweed Fertilizer trigger, no grain granted.
    s = _state()
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1)
    s = _sow_grain(s)
    assert _fire_here(s) is None
    assert _stop_here(s)
    assert s.players[0].resources.grain == 0
