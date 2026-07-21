"""Tests for Dolly's Mother (minor improvement, E84; Ephipparius Expansion).

Card text (verbatim): "You only require 1 sheep to breed sheep during the
breeding phase of a harvest. This card can hold 1 sheep."
Free; prereq 1 Sheep; printed 1 VP.

Two effects, both ruled 2026-07-06 with the user's greedy-strip plan:
- single-parent sheep breeding (the parent threshold, threaded as an argument
  through the memoized breeding frontier + food formula + the newborn report);
- a sheep-only capacity slot (the greedy strip at the ownership-aware
  accommodation entry points: the owner's problem = the standard problem with
  one sheep parked on the card).

The cross-level tests pin that the optimized frontier caches
(PARETO_OPT_LEVEL >= 1) agree with the level-0 oracle under both effects —
the FRONTIER_OPT cross-level pattern for the new arguments.
"""
import dataclasses

import agricola.cards.dollys_mother  # noqa: F401  (register the card)

from agricola import opt_config
from agricola.actions import CommitBreed, FireTrigger, Stop
from agricola.cards.dollys_mother import CARD_ID
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import (
    accommodates,
    breeding_food_gained,
    breeding_frontier,
    grant_animals,
    pareto_frontier,
)
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingHarvestBreed
from agricola.resources import Animals
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **kw):
    import agricola.replace as rep
    p = rep.fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _animals(state, idx, **kw):
    return _edit_player(state, idx, animals=Animals(**kw))


def _set_pasture_1x1(state, player_idx, row=0, col=0):
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    return _edit_player(state, player_idx, farmyard=Farmyard(
        grid=p.farmyard.grid,
        horizontal_fences=tuple(tuple(r) for r in h),
        vertical_fences=tuple(tuple(r) for r in v),
        pastures=compute_pastures_from_arrays(
            p.farmyard.grid, tuple(tuple(r) for r in h),
            tuple(tuple(r) for r in v))))


def _to_p0_breed_frame(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestBreed) and top.player_idx == 0
                and not top.breed_chosen):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("no P0 breed frame surfaced")


def _harvest_state():
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    return state


# ---------------------------------------------------------------------------
# Registration / prereq
# ---------------------------------------------------------------------------

def test_registration():
    import json
    from agricola.cards.capacity_mods import (
        SINGLE_PARENT_SHEEP_CARDS, TYPED_SLOT_CARDS)
    from agricola.cards.specs import MINORS, prereq_met
    from agricola.resources import Animals

    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.prereq is not None
    entry = next(fn for cid, fn in TYPED_SLOT_CARDS if cid == CARD_ID)
    assert entry(None) == Animals(sheep=1)   # a static count; ignores the player
    assert CARD_ID in SINGLE_PARENT_SHEEP_CARDS
    rows = json.load(open("agricola/cards/data/revised_minor_improvements.json"))
    row = next(r for r in rows if r["name"] == "Dolly's Mother")
    assert row["deck"] == "E" and row["number"] == 84
    assert row["vps"] == 1 and row["cost"] is None
    assert row["prerequisites"] == "1 Sheep"

    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)          # 0 sheep
    assert prereq_met(spec, _animals(state, 0, sheep=1), 0)


# ---------------------------------------------------------------------------
# The sheep-only slot (capacity)
# ---------------------------------------------------------------------------

def test_slot_holds_one_sheep_only():
    """Starting farm (1 flexible house slot): the owner fits 2 sheep (pet +
    card) and 1 sheep + 1 boar (boar pet, sheep card) — but NOT 2 boar (the
    slot is sheep-only) and not 3 sheep (one slot each, nothing left)."""
    state = _own(setup(seed=0), 0)
    p = state.players[0]
    assert accommodates(p, 2, 0, 0)
    assert accommodates(p, 1, 1, 0)
    assert not accommodates(p, 0, 2, 0)
    assert not accommodates(p, 3, 0, 0)
    # Non-owner control: 2 sheep do NOT fit the bare farm.
    q = setup(seed=0).players[0]
    assert not accommodates(q, 2, 0, 0)


def test_barrier_uses_the_slot():
    """A decision-free second sheep FITS an owner's bare farm (no keep-or-cook
    frame); the same grant to a non-owner surfaces the frame."""
    for owned in (True, False):
        state = setup(seed=0)
        if owned:
            state = _own(state, 0)
        state = _animals(state, 0, sheep=1)
        state = grant_animals(state, 0, Animals(sheep=1))
        state = _advance_until_decision(state)
        frame = any(isinstance(f, PendingAccommodate) and f.player_idx == 0
                    for f in state.pending_stack)
        assert frame == (not owned)
        if owned:
            assert state.players[0].animals.sheep == 2


def test_pareto_frontier_shifts_by_the_slot():
    """The owner's keep-sets are the bare-farm keep-sets plus one sheep, food
    unchanged — and cooking the carded sheep remains available (the frontier
    never forces keeping it)."""
    base = setup(seed=0)
    owner = _own(base, 0)
    plain = pareto_frontier(_animals(base, 0, sheep=1).players[0],
                            Animals(sheep=1), rates=(2, 0, 0))
    carded = pareto_frontier(_animals(owner, 0, sheep=1).players[0],
                             Animals(sheep=1), rates=(2, 0, 0))
    # Bare farm: keep at most 1 (cook the other -> 2 food). Owner: keep both.
    assert max(a.sheep for a, _ in plain) == 1
    assert max(a.sheep for a, _ in carded) == 2
    assert (Animals(sheep=2, boar=0, cattle=0), 0) in carded


def test_cross_level_equivalence():
    """The optimized frontier paths agree with the level-0 oracle under both
    of the card's effects (the FRONTIER_OPT cross-level pattern)."""
    state = _own(setup(seed=0), 0)
    state = _set_pasture_1x1(state, 0)
    state = _animals(state, 0, sheep=1, boar=2)
    p = state.players[0]
    saved = opt_config.PARETO_OPT_LEVEL
    try:
        opt_config.PARETO_OPT_LEVEL = 0
        slow_p = sorted((a.sheep, a.boar, a.cattle, f)
                        for a, f in pareto_frontier(p, Animals(sheep=1), (2, 2, 3)))
        slow_b = sorted((a.sheep, a.boar, a.cattle, f)
                        for a, f in breeding_frontier(p, (2, 2, 3)))
        opt_config.PARETO_OPT_LEVEL = saved if saved >= 1 else 1
        fast_p = sorted((a.sheep, a.boar, a.cattle, f)
                        for a, f in pareto_frontier(p, Animals(sheep=1), (2, 2, 3)))
        fast_b = sorted((a.sheep, a.boar, a.cattle, f)
                        for a, f in breeding_frontier(p, (2, 2, 3)))
    finally:
        opt_config.PARETO_OPT_LEVEL = saved
    assert slow_p == fast_p
    assert slow_b == fast_b


# ---------------------------------------------------------------------------
# Single-parent breeding
# ---------------------------------------------------------------------------

def test_breeds_from_one_sheep():
    """Owner with exactly 1 sheep (house pet): the newborn takes the card slot
    — CommitBreed(sheep=2) is offered on the bare farm and resolves."""
    state = _own(_harvest_state(), 0)
    state = _animals(state, 0, sheep=1)
    state = _to_p0_breed_frame(state)
    acts = legal_actions(state)
    breed2 = [a for a in acts if isinstance(a, CommitBreed) and a.sheep == 2]
    assert breed2, f"no from-one-sheep breed offered: {acts}"
    state = step(state, breed2[0])
    assert state.players[0].animals.sheep == 2


def test_nonowner_does_not_breed_from_one():
    state = _harvest_state()
    state = _animals(state, 0, sheep=1)
    state = _to_p0_breed_frame(state)
    assert all(a.sheep <= 1 for a in legal_actions(state)
               if isinstance(a, CommitBreed))


def test_food_formula_single_parent():
    """The generalized fired-and-kept indicator at m=1."""
    r = (2, 0, 0)
    # pre 1 -> post 2: bred, nothing cooked.
    assert breeding_food_gained(Animals(sheep=1), Animals(sheep=2), r, 1) == 0
    # pre 1 -> post 0: no breed (post < 2), the one sheep cooked.
    assert breeding_food_gained(Animals(sheep=1), Animals(sheep=0), r, 1) == 2
    # pre 3 -> post 2: cooked down to 1, bred back to 2 -> 2 cooked.
    assert breeding_food_gained(Animals(sheep=3), Animals(sheep=2), r, 1) == 4
    # m=2 default unchanged: pre 1 -> post 0 cooks 1.
    assert breeding_food_gained(Animals(sheep=1), Animals(sheep=0), r) == 2


def test_outcome_report_sees_the_single_parent_newborn():
    """THE trap the user's plan would have missed: Fodder Planter's sow must
    fire on a from-one-sheep newborn (the breeding-outcome report uses the
    card-aware threshold)."""
    import agricola.cards.fodder_planter  # noqa: F401
    from agricola.cards.fodder_planter import CARD_ID as FODDER

    state = _own(_harvest_state(), 0)
    p = state.players[0]
    state = _edit_player(state, 0, occupations=p.occupations | {FODDER})
    state = _animals(state, 0, sheep=1)
    # An empty field + a grain so the granted sow is committable.
    state = with_resources(state, 0, food=20, grain=1)
    from agricola.constants import CellType
    from agricola.replace import fast_replace
    p = state.players[0]
    grid = tuple(
        tuple(fast_replace(cell, cell_type=CellType.FIELD)
              if (r, c) == (2, 4) else cell
              for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    state = _edit_player(state, 0, farmyard=fast_replace(p.farmyard, grid=grid))

    state = _to_p0_breed_frame(state)
    breed2 = next(a for a in legal_actions(state)
                  if isinstance(a, CommitBreed) and a.sheep == 2)
    state = step(state, breed2)
    acts = legal_actions(state)
    assert FireTrigger(card_id=FODDER) in acts, (
        f"Fodder Planter's sow not offered on the single-parent newborn: {acts}")
    assert Stop() in acts


def test_two_sheep_still_breed_normally():
    state = _own(_harvest_state(), 0)
    state = _set_pasture_1x1(state, 0)
    state = _animals(state, 0, sheep=2)
    state = _to_p0_breed_frame(state)
    assert any(isinstance(a, CommitBreed) and a.sheep == 3
               for a in legal_actions(state))


# ---------------------------------------------------------------------------
# Shepherd's Whistle composition
# ---------------------------------------------------------------------------

def test_composes_with_shepherds_whistle_free_stable_test():
    """SW's free-stable test on a Dolly's-Mother owner sees the card slot:
    2 sheep + pet + 1 unfenced stable + the card -> removing the stable still
    fits (pet + card), so SW's sheep is granted automatically."""
    import agricola.cards.shepherds_whistle  # noqa: F401
    from agricola.cards.shepherds_whistle import _stable_is_free

    from agricola.constants import CellType
    from agricola.replace import fast_replace

    state = _own(setup(seed=0), 0)
    p = state.players[0]
    grid = tuple(
        tuple(fast_replace(cell, cell_type=CellType.STABLE)
              if (r, c) == (2, 4) else cell
              for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    state = _edit_player(state, 0, farmyard=fast_replace(p.farmyard, grid=grid))
    state = _animals(state, 0, sheep=2)
    assert _stable_is_free(state, 0)          # pet + card hold the 2 sheep
    # Non-owner control: without the card slot the stable is NOT free.
    q = setup(seed=0)
    qp = q.players[0]
    qgrid = tuple(
        tuple(fast_replace(cell, cell_type=CellType.STABLE)
              if (r, c) == (2, 4) else cell
              for c, cell in enumerate(row))
        for r, row in enumerate(qp.farmyard.grid))
    q = _edit_player(q, 0, farmyard=fast_replace(qp.farmyard, grid=qgrid))
    q = _animals(q, 0, sheep=2)
    assert not _stable_is_free(q, 0)
