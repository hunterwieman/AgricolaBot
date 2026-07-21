"""Tests for Tinsmith Master (occupation, deck B #115): "You can hold 1 additional
animal in each pasture without a stable. Each time you sow in a field, you can place
1 additional crop of the respective type in that field."

Clarifications: one extra crop on top of the usual stack (not a second stack); only
grain or vegetable may be added; this does not add a condition to sowing.
User ruling (2026-07-15): the "+1 crop, you can" is meaningfully declinable per field,
so the sow enumeration counts boosted grain/veg fields separately (CommitSow.boost_*).

Covers: registration; the +1 capacity on stable-less pastures only (stabled pastures,
house pet, and standalone-stable flexible slots unchanged; non-owner unchanged; stacks
with Drinking Trough's flat +2); cross-level frontier equivalence with the conditioned
capacities (the §5.4 projection-key contract, exercised like test_frontier_opt's
Drinking Trough red-team item); the sow-boost expansion (offered only when owned;
bounded by the sown counts; the bare 0,0 decline is today's sow); the executor (a
boosted grain field holds 4 while an unboosted one in the same commit holds 3; a
boosted veg field holds 3; mixed partial boosts; supply debit unchanged); the
after-sow harvest (one field-phase take still pays 1 crop regardless of stack height);
card-field boosts (a boosted Beanfield veg stack holds 3, a boosted Artichoke Field
grain stack holds 4, Wood Field's wood stacks are never boostable); and the wire
encoding (zero boosts skipped — Family byte-identity — nonzero boosts round-trip).
"""
from __future__ import annotations

import agricola.cards.tinsmith_master  # noqa: F401  (registers the card; not in __init__ yet)

from agricola import helpers, opt_config
from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.agents.nn.trace_replay import action_from_params, action_to_params
from agricola.cards.capacity_mods import (
    PASTURE_CAPACITY_PER_MODS,
    pasture_capacity_per_list,
)
from agricola.cards.card_fields import card_holds, stacks_to_store
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import SOW_BOOST_CARDS, legal_actions
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Animals
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

from scripts.profile_states import STATES, _add_pasture

CARD = "tinsmith_master"

_POOL = CardPool(
    occupations=(CARD,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_occ(state, idx, card_id=CARD):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _with_empty_fields(state, idx, cells):
    """Place empty FIELD tiles at the given (row, col) cells, ready to sow into."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _to_before_sow(s, space="grain_utilization"):
    """Place at `space`, choose sow -> PendingSow in its before-phase."""
    s = _reveal(s, space)
    s = step(s, PlaceWorker(space=space))
    s = step(s, ChooseSubAction(name="sow"))
    return s


def _sows(state):
    return [a for a in legal_actions(state) if isinstance(a, CommitSow)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD in OCCUPATIONS
    assert any(cid == CARD for cid, _fn in PASTURE_CAPACITY_PER_MODS)
    assert CARD in SOW_BOOST_CARDS


def test_on_play_is_a_no_op():
    s = setup(0)
    assert OCCUPATIONS[CARD].on_play(s, 0) == s


# ---------------------------------------------------------------------------
# Capacity: +1 per pasture WITHOUT a stable
# ---------------------------------------------------------------------------

def test_capacity_fold_none_by_default():
    s = setup(0)
    assert pasture_capacity_per_list(
        s.players[0], s.players[0].farmyard.pastures) is None


def test_stableless_pasture_holds_one_more():
    # A single 1x1 stable-less pasture (cap 2) + the default house pet (1 flexible).
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0)])                    # 1x1, 0 stables -> capacity 2
    caps0, flex0 = helpers.extract_slots(s, s.players[0])
    assert caps0 == [2]
    assert helpers.can_accommodate(caps0, flex0, 3, 0, 0)       # 2 in pasture + 1 pet
    assert not helpers.can_accommodate(caps0, flex0, 4, 0, 0)

    s2 = _own_occ(s, 0)
    caps1, flex1 = helpers.extract_slots(s2, s2.players[0])
    assert caps1 == [3]                                  # 2 -> 3
    assert flex1 == flex0                                # house pet / stables unchanged
    assert helpers.can_accommodate(caps1, flex1, 4, 0, 0)        # 3 in pasture + 1 pet
    assert not helpers.can_accommodate(caps1, flex1, 5, 0, 0)


def test_stabled_pasture_unchanged_stableless_boosted():
    # mid_round_6_basic: p0 has a 1x1 + 1 stable pasture (cap 4) and a stable-less
    # 2x1 (cap 4). Tinsmith boosts ONLY the stable-less one: [4, 4] -> {4, 5}.
    state = STATES["mid_round_6_basic"]()
    pastures = state.players[0].farmyard.pastures
    assert sorted(p.num_stables for p in pastures) == [0, 1]
    base_caps, base_flex = helpers.extract_slots(state, state.players[0])

    state2 = _own_occ(state, 0)
    caps, flex = helpers.extract_slots(state2, state2.players[0])
    assert flex == base_flex
    # Parallel to `pastures`: +1 exactly where num_stables == 0.
    expected = [c + (1 if p.num_stables == 0 else 0)
                for c, p in zip(base_caps, pastures)]
    assert caps == expected
    # The other (non-owner) player is unaffected.
    assert (helpers.extract_slots(state2, state2.players[1])
            == helpers.extract_slots(state, state.players[1]))


def test_pasture_that_gains_a_stable_loses_the_bonus():
    # The same 1x1 pasture WITH a stable gets no bonus (cap 2*1*2 = 4, stays 4).
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0)], num_stables=1)
    s = _own_occ(s, 0)
    caps, _flex = helpers.extract_slots(s, s.players[0])
    assert caps == [4]


def test_unowned_unchanged():
    s = setup(0)
    s = _add_pasture(s, 0, [(0, 0)])
    caps, flex = helpers.extract_slots(s, s.players[0])
    assert caps == [2]                                   # no card -> no bonus


def test_stacks_with_drinking_trough():
    # Drinking Trough's flat +2 applies to EVERY pasture; Tinsmith adds +1 only to
    # the stable-less one: stabled 4 -> 6, stable-less 4 -> 7.
    state = STATES["mid_round_6_basic"]()
    state = _own_occ(state, 0)
    state = _own_minor(state, 0, "drinking_trough")
    pastures = state.players[0].farmyard.pastures
    caps, _flex = helpers.extract_slots(state, state.players[0])
    expected = [4 + 2 + (1 if p.num_stables == 0 else 0) for p in pastures]
    assert caps == expected
    assert sorted(caps) == [6, 7]


def test_cross_level_frontier_equivalence_with_tinsmith():
    """The §5.4 projection-key contract, exercised: Tinsmith's conditioned (mixed
    +1) capacities flow into the level-2/3 accommodation caches keyed on
    extract_slots' outputs — every opt level must agree with the level-0 oracle
    (the test_frontier_opt idiom, on the Tinsmith-owning farm)."""
    state = STATES["mid_round_6_basic"]()
    state = _own_occ(state, 0)
    p = state.players[0]
    p = fast_replace(p, animals=Animals(sheep=8, boar=6, cattle=6))  # capacity binds
    norms = {}
    for lvl in (0, 1, 2, 3):
        opt_config.PARETO_OPT_LEVEL = lvl
        norms[lvl] = sorted(
            ((a.sheep, a.boar, a.cattle), f)
            for a, f in helpers.pareto_frontier(state, p, Animals(), (2, 2, 3)))
    assert norms[1] == norms[2] == norms[3]              # optimized levels: identical
    assert set(norms[0]) == set(norms[1])                # level 0: set-identical


# ---------------------------------------------------------------------------
# Sow boost: the expansion is offered only when owned
# ---------------------------------------------------------------------------

def test_unowned_sow_enumeration_is_todays():
    s, cp = _card_state()
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=1, veg=1)
    s = _to_before_sow(s)
    sows = _sows(s)
    assert set(sows) == {
        CommitSow(grain=1, veg=0), CommitSow(grain=0, veg=1),
        CommitSow(grain=1, veg=1),
    }
    assert all(a.boost_grain == 0 and a.boost_veg == 0
               and a.boost_card_sows == () for a in sows)


def test_owned_sow_enumeration_expands_over_boosts():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=1, veg=1)
    s = _to_before_sow(s)
    sows = _sows(s)
    # Each (g, v) option expands over boost_grain in 0..g x boost_veg in 0..v.
    expected = set()
    for g, v in ((1, 0), (0, 1), (1, 1)):
        for bg in range(g + 1):
            for bv in range(v + 1):
                expected.add(CommitSow(grain=g, veg=v,
                                       boost_grain=bg, boost_veg=bv))
    assert set(sows) == expected
    assert len(sows) == len(expected)                    # no duplicates


# ---------------------------------------------------------------------------
# Executor: the boosted stack heights
# ---------------------------------------------------------------------------

def test_boosted_grain_field_holds_4_unboosted_3_same_commit():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=2)
    grain0 = s.players[cp].resources.grain
    s = _to_before_sow(s)
    s = step(s, CommitSow(grain=2, veg=0, boost_grain=1))
    grid = s.players[cp].farmyard.grid
    # Fields fill in canonical order; the first boost_grain of them take the +1.
    assert grid[1][0].grain == 4
    assert grid[1][1].grain == 3
    # Supply debit unchanged: the extra crop is general-supply, not the player's.
    assert s.players[cp].resources.grain == grain0 - 2


def test_boosted_veg_field_holds_3():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1)
    veg0 = s.players[cp].resources.veg
    s = _to_before_sow(s)
    s = step(s, CommitSow(grain=0, veg=1, boost_veg=1))
    assert s.players[cp].farmyard.grid[1][0].veg == 3
    assert s.players[cp].resources.veg == veg0 - 1


def test_decline_is_todays_sow():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=1, veg=1)
    s = _to_before_sow(s)
    s = step(s, CommitSow(grain=1, veg=1))               # the bare 0,0 decline
    grid = s.players[cp].farmyard.grid
    assert grid[1][0].grain == 3                          # standard stacks
    assert grid[1][1].veg == 2


def test_mixed_partial_boosts():
    # grain=1 (boosted) + veg=2 (one boosted): fields fill grain-first in canonical
    # order -> [4 grain, 3 veg, 2 veg].
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1), (1, 2)])
    s = with_resources(s, cp, grain=1, veg=2)
    s = _to_before_sow(s)
    s = step(s, CommitSow(grain=1, veg=2, boost_grain=1, boost_veg=1))
    grid = s.players[cp].farmyard.grid
    assert grid[1][0].grain == 4
    assert grid[1][1].veg == 3
    assert grid[1][2].veg == 2


def test_boosted_field_harvests_normally():
    # One field-phase take pays 1 crop regardless of stack height: 4 -> 3, +1 grain.
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, grain=1)
    s = _to_before_sow(s)
    s = step(s, CommitSow(grain=1, veg=0, boost_grain=1))
    assert s.players[cp].farmyard.grid[1][0].grain == 4
    s = fast_replace(s, pending_stack=())                # bare take, outside the turn
    grain0 = s.players[cp].resources.grain
    s, occ = field_take(s, cp)
    assert s.players[cp].farmyard.grid[1][0].grain == 3
    assert s.players[cp].resources.grain == grain0 + 1
    [entry] = occ.entries
    assert entry.amount == 1 and not entry.emptied


# ---------------------------------------------------------------------------
# Card-fields (ruling 45, 2026-07-12: card-fields are fields): grain/veg stacks
# boostable, wood/stone never (the card's clarification).
# ---------------------------------------------------------------------------

def _own_card_field(s, idx, cid, stacks=None):
    p = s.players[idx]
    store = (stacks_to_store(p.card_state, cid, stacks)
             if stacks is not None else p.card_state)
    p = fast_replace(p, minor_improvements=p.minor_improvements | {cid},
                     card_state=store)
    return fast_replace(
        s, players=tuple(p if i == idx else s.players[i] for i in range(2)))


def test_boosted_beanfield_veg_stack_holds_3():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _own_card_field(s, cp, "beanfield")
    s = with_resources(s, cp, veg=1)
    s = _to_before_sow(s)
    sow = next(a for a in _sows(s)
               if a.grain == 0 and a.veg == 0
               and a.card_sows == (("beanfield", "veg"),)
               and a.boost_card_sows == (("beanfield", "veg"),))
    s = step(s, sow)
    assert card_holds(s.players[cp], "beanfield", "veg") == 3     # 2 + 1


def test_unboosted_beanfield_veg_stack_holds_2():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _own_card_field(s, cp, "beanfield")
    s = with_resources(s, cp, veg=1)
    s = _to_before_sow(s)
    sow = next(a for a in _sows(s)
               if a.grain == 0 and a.veg == 0
               and a.card_sows == (("beanfield", "veg"),)
               and a.boost_card_sows == ())
    s = step(s, sow)
    assert card_holds(s.players[cp], "beanfield", "veg") == 2


def test_boosted_artichoke_grain_stack_holds_4():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _own_card_field(s, cp, "artichoke_field")
    s = with_resources(s, cp, grain=1)
    s = _to_before_sow(s)
    sow = next(a for a in _sows(s)
               if a.card_sows == (("artichoke_field", "grain"),)
               and a.boost_card_sows == (("artichoke_field", "grain"),))
    s = step(s, sow)
    assert card_holds(s.players[cp], "artichoke_field", "grain") == 4   # 3 + 1


def test_wood_field_stacks_never_boostable():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = _own_card_field(s, cp, "wood_field")
    s = with_resources(s, cp, wood=2)
    s = _to_before_sow(s)
    wood_sows = [a for a in _sows(s)
                 if any(good == "wood" for _cid, good in a.card_sows)]
    assert wood_sows                                     # wood sows ARE offered...
    assert all(a.boost_card_sows == () for a in wood_sows)   # ...never boosted


# ---------------------------------------------------------------------------
# Wire encoding: zero boosts skipped (Family byte-identity), nonzero round-trip
# ---------------------------------------------------------------------------

def test_wire_encoding_skips_default_boosts():
    params = action_to_params(CommitSow(grain=1, veg=0))
    assert set(params) == {"grain", "veg"}               # the pre-boost Family shape


def test_wire_encoding_round_trips_boosts():
    a = CommitSow(grain=2, veg=1, boost_grain=1, boost_veg=1,
                  card_sows=(("beanfield", "veg"),),
                  boost_card_sows=(("beanfield", "veg"),))
    params = action_to_params(a)
    assert params["boost_grain"] == 1 and params["boost_veg"] == 1
    # Simulate the JSON round-trip's tuple->list conversion.
    params["card_sows"] = [list(p) for p in params["card_sows"]]
    params["boost_card_sows"] = [list(p) for p in params["boost_card_sows"]]
    assert action_from_params("CommitSow", params) == a
