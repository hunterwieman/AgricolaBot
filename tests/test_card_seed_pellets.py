"""Tests for Seed Pellets (minor A65): "Each time before you take an unconditional
'Sow' action, you get 1 grain." Prerequisite: 3 Fields.

Modeled as a mandatory, choice-free `before_sow` automatic effect (register_auto) — the
+1 grain lands at the PendingSow push (the sub-action before-phase), with no declinable
FireTrigger. Covers: registration; the prereq boundary (3 fields yes / 2 no); the grant
firing via a real Grain Utilization sow AND a real Cultivation sow; that it fires BEFORE
the sow (grain on hand at CommitSow); once-per-sow scoping; and that it does not fire when
the card is not owned.
"""
from __future__ import annotations

import agricola.cards.seed_pellets  # noqa: F401  (registers the card; not in __init__ yet)

from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_fields, with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("seed_pellets",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


# ---------------------------------------------------------------------------
# Registration + prereq
# ---------------------------------------------------------------------------

def test_seed_pellets_registered():
    assert "seed_pellets" in MINORS
    spec = MINORS["seed_pellets"]
    assert spec.cost == Cost()           # no cost
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is not None
    bsow = {e.card_id for e in AUTO_EFFECTS.get("before_sow", [])}
    assert "seed_pellets" in bsow


def test_seed_pellets_prereq_three_fields():
    s, cp = _card_state()
    spec = MINORS["seed_pellets"]
    # 0 fields at fresh setup -> not met.
    assert not prereq_met(spec, s, cp)
    # 2 fields -> still not met.
    s2 = with_fields(s, cp, [(0, 0), (0, 1)])
    assert not prereq_met(spec, s2, cp)
    # 3 fields -> met.
    s3 = with_fields(s, cp, [(0, 0), (0, 1), (0, 2)])
    assert prereq_met(spec, s3, cp)


def test_seed_pellets_prereq_counts_card_fields():
    """Ruling 45 (2026-07-12): a card-field counts for the "3 Fields" prereq,
    planted or not — 2 grid fields + a never-sown Beanfield = 3 fields, met
    ONLY via the card (the boundary the grid-only count failed)."""
    import agricola.cards.beanfield  # noqa: F401  (registers the card-field)
    s, cp = _card_state()
    spec = MINORS["seed_pellets"]
    s2 = with_fields(s, cp, [(0, 0), (0, 1)])
    assert not prereq_met(spec, s2, cp)
    s3 = _own_minor(s2, cp, "beanfield")     # bare card-field, never sown
    assert prereq_met(spec, s3, cp)


# ---------------------------------------------------------------------------
# The grant fires via a real sow flow
# ---------------------------------------------------------------------------

def _to_before_sow(s, cp, space="grain_utilization"):
    """Place at `space`, choose sow -> PendingSow in its before-phase. Leaves one FIELD
    (row 1 col 0) to sow into and gives 1 grain to seed the sow."""
    p = s.players[cp]
    grid = [[c for c in row] for row in p.farmyard.grid]
    grid[1][0] = Cell(cell_type=CellType.FIELD)   # an empty field to sow into
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    s = fast_replace(s, players=tuple(
        fast_replace(p, farmyard=fy) if i == cp else s.players[i] for i in range(2)))
    s = with_resources(s, cp, grain=1)
    s = _reveal(s, space)
    s = step(s, PlaceWorker(space=space))
    s = step(s, ChooseSubAction(name="sow"))
    return s


def test_seed_pellets_grants_grain_before_grain_utilization_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "seed_pellets")
    grain0 = 1
    s = _to_before_sow(s, cp, "grain_utilization")
    # The auto fired at the PendingSow push: +1 grain already on hand, before any CommitSow.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert s.players[cp].resources.grain == grain0 + 1     # seed grain + the +1 grant
    # And the +1 grain is available to be sown.
    assert any(isinstance(a, CommitSow) for a in legal_actions(s))


def test_seed_pellets_grants_grain_on_cultivation_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "seed_pellets")
    s = _to_before_sow(s, cp, "cultivation")
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.players[cp].resources.grain == 2              # 1 seed + 1 grant


def test_seed_pellets_does_not_fire_when_not_owned():
    s, cp = _card_state()
    # Same flow, but the card is NOT in the player's tableau.
    s = _to_before_sow(s, cp, "grain_utilization")
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.players[cp].resources.grain == 1              # only the seed grain, no grant


def test_seed_pellets_fires_once_per_sow():
    """The grant is +1 per Sow action (one PendingSow push), not per grain sown."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "seed_pellets")
    s = _to_before_sow(s, cp, "grain_utilization")
    assert s.players[cp].resources.grain == 2              # exactly one +1, not repeated
    # Sow exactly 1 grain into the single field; the grant does not re-apply afterward.
    sow1 = next(a for a in legal_actions(s)
                if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    s = step(s, sow1)
    # 2 grain on hand, sowed 1 -> 1 left; the grant fired exactly once (no re-application).
    assert s.players[cp].resources.grain == 1
    # The field is now sown (FIELD cell holds grain), confirming a real sow ran.
    g = s.players[cp].farmyard.grid
    assert g[1][0].cell_type == CellType.FIELD and g[1][0].grain > 0


def test_seed_pellets_fires_on_a_second_independent_sow():
    """A fresh Sow action (a new PendingSow push) fires the grant again — 'each time'."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "seed_pellets")
    # First sow.
    s = _to_before_sow(s, cp, "grain_utilization")
    assert s.players[cp].resources.grain == 2
    sows = [a for a in legal_actions(s) if isinstance(a, CommitSow)]
    s = step(s, sows[0])
    # Drive to a brand-new, independent PendingSow push (Cultivation, next placement).
    grain_before = s.players[cp].resources.grain
    p = s.players[cp]
    grid = [[c for c in row] for row in p.farmyard.grid]
    grid[1][1] = Cell(cell_type=CellType.FIELD)   # another empty field
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    s = fast_replace(s, players=tuple(
        fast_replace(p, farmyard=fy) if i == cp else s.players[i] for i in range(2)))
    s = fast_replace(s, current_player=cp, pending_stack=())
    s = _reveal(s, "cultivation")
    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, ChooseSubAction(name="sow"))
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.players[cp].resources.grain == grain_before + 1   # the grant fired again
