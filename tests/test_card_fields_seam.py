"""Seam tests for the card-field machinery (`agricola/cards/card_fields.py`
+ its engine integration), driven through SYNTHETIC card-field registrations
(the ids below exist in no card pool, so real deals never see them; every
consumer is ownership-gated, so the registrations are inert elsewhere).

Covers the machinery the nine real card-fields ride (user rulings 43-48,
2026-07-12; CARD_DEFERRED_PLANS.md):

- the CardStore stack shape: canonical sorting, the all-empty-removes-entry
  rule (a harvested-out card-field hashes like a never-sown one)
- sow: enumeration (bundles, supply bounds, ruling 48's crops_only and the
  card-counts-once cap accounting), execution, the _can_sow gate
- the take: per-stack `card:<id>` entries in the ONE event, take-precedence
  within a stack, store write-back, replace-kind skips
- ruling 46: the three take-modifier folds (Scythe Worker, Stable Manure,
  Grain Thief) reaching card-fields
- ruling 45: scoring's Fields category + grain/veg totals
- the Family wire/canonical invariance of the new fields
"""
from agricola.actions import CommitSow
from agricola.canonical import to_canonical
from agricola.agents.nn.trace_replay import action_from_params, action_to_params
from agricola.cards.card_fields import (
    can_sow_card_fields,
    card_field_stacks,
    enumerate_card_sows,
    iter_card_field_units,
    register_card_field,
    stacks_to_store,
)
from agricola.cards.harvest_windows import fold_chosen_modifiers
from agricola.constants import CellType
from agricola.legality import _can_sow, legal_actions
from agricola.pending import PendingSow
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.scoring import score
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    with_pending_stack,
    with_resources,
    with_sown_fields,
)

# Synthetic card-fields: a 1-stack crop field (Beanfield/Crop Rotation Field
# shape), a 2-stack wood-as-grain field (Wood Field shape), a 3-stack
# stone-as-vegetables field (Rock Garden shape).
register_card_field("cf_test_crop", stacks=1,
                    sow_amounts=(("grain", 3), ("veg", 2)))
register_card_field("cf_test_wood", stacks=2, sow_amounts=(("wood", 3),))
register_card_field("cf_test_stone", stacks=3, sow_amounts=(("stone", 2),))


def _own(state, idx, card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, cid, stacks):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _base(seed=7):
    return setup(seed)


# ---------------------------------------------------------------------------
# Store shape
# ---------------------------------------------------------------------------

def test_stacks_canonical_and_empty_removed():
    state = _own(_base(), 0, ["cf_test_wood"])
    before_store = state.players[0].card_state
    # Out-of-order stacks are stored sorted descending.
    state = _set_stacks(state, 0, "cf_test_wood",
                        [(0, 0, 0, 0), (0, 0, 3, 0)])
    assert card_field_stacks(state.players[0], "cf_test_wood") == (
        (0, 0, 3, 0), (0, 0, 0, 0))
    # Writing all-empty stacks REMOVES the entry: identical to never-sown.
    state = _set_stacks(state, 0, "cf_test_wood",
                        [(0, 0, 0, 0), (0, 0, 0, 0)])
    assert state.players[0].card_state == before_store


# ---------------------------------------------------------------------------
# Sow — enumeration
# ---------------------------------------------------------------------------

def test_enumerate_card_sows_bundles_and_crops_only():
    state = _own(_base(), 0, ["cf_test_crop", "cf_test_wood"])
    p = state.players[0]
    bundles = enumerate_card_sows(p)
    assert () in bundles
    assert (("cf_test_crop", "grain"),) in bundles
    assert (("cf_test_crop", "veg"),) in bundles
    assert (("cf_test_wood", "wood"),) in bundles
    assert (("cf_test_wood", "wood"), ("cf_test_wood", "wood")) in bundles
    # crops_only (ruling 48): wood sows vanish, crop sows stay.
    crop_bundles = enumerate_card_sows(p, crops_only=True)
    assert (("cf_test_crop", "grain"),) in crop_bundles
    assert all(good != "wood" for b in crop_bundles for _cid, good in b)


def test_sow_enumeration_supply_cap_and_card_unit_accounting():
    state = _base()
    state = _own(state, 0, ["cf_test_wood"])
    state = with_resources(state, 0, wood=2, grain=0, veg=0)
    frame = PendingSow(player_idx=0, initiated_by_id="test", max_fields=1)
    state = with_pending_stack(state, [frame])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    # No board crops in supply -> every option is a card sow.
    assert sows and all(a.grain == 0 and a.veg == 0 for a in sows)
    # Ruling 48: the whole card is ONE field-unit of the max_fields=1 cap, so
    # sowing BOTH stacks in the one commit is legal (Chief Forester's "You
    # may plant 2 wood at once with 1 trigger") — as is sowing just one.
    doubles = [a for a in sows if len(a.card_sows) == 2]
    singles = [a for a in sows if len(a.card_sows) == 1]
    assert len(doubles) == 1 and len(singles) == 1
    # Supply-bounded: with 1 wood, the double sow disappears.
    state1 = with_resources(state, 0, wood=1)
    sows1 = [a for a in legal_actions(state1) if isinstance(a, CommitSow)]
    assert all(len(a.card_sows) <= 1 for a in sows1)


def test_sow_enumeration_crops_only_excludes_wood_cards():
    state = _base()
    state = _own(state, 0, ["cf_test_wood"])
    state = with_resources(state, 0, wood=5, grain=0, veg=0)
    frame = PendingSow(player_idx=0, initiated_by_id="test",
                       max_fields=1, crops_only=True)
    state = with_pending_stack(state, [frame])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert sows == []   # nothing sowable: wood card excluded, no board play


def test_can_sow_gates_see_card_fields():
    state = _base()
    # Strip the board of empty fields (setup has none anyway) and give wood.
    state = _own(state, 0, ["cf_test_wood"])
    state = with_resources(state, 0, wood=1, grain=0, veg=0)
    p = state.players[0]
    assert _can_sow(p)                                  # generic: wood sow
    assert can_sow_card_fields(p)
    assert not can_sow_card_fields(p, crops_only=True)  # ruling 48


# ---------------------------------------------------------------------------
# Sow — execution
# ---------------------------------------------------------------------------

def test_sow_execution_fills_stacks_and_spends_supply():
    from agricola.engine import step
    state = _base()
    state = _own(state, 0, ["cf_test_crop", "cf_test_wood"])
    state = with_resources(state, 0, wood=2, grain=1, veg=0)
    frame = PendingSow(player_idx=0, initiated_by_id="test")
    state = with_pending_stack(state, [frame])
    commit = CommitSow(grain=0, veg=0, card_sows=(
        ("cf_test_crop", "grain"),
        ("cf_test_wood", "wood"), ("cf_test_wood", "wood")))
    assert commit in legal_actions(state)
    nxt = step(state, commit)
    p = nxt.players[0]
    assert card_field_stacks(p, "cf_test_crop") == ((3, 0, 0, 0),)
    assert card_field_stacks(p, "cf_test_wood") == (
        (0, 0, 3, 0), (0, 0, 3, 0))
    assert p.resources.wood == 0 and p.resources.grain == 0


# ---------------------------------------------------------------------------
# The take
# ---------------------------------------------------------------------------

def test_field_take_harvests_each_stack_and_writes_back():
    state = _base()
    state = _own(state, 0, ["cf_test_crop", "cf_test_wood"])
    state = with_sown_fields(state, 0, grain_fields=[(2, 0)], veg_fields=[])
    state = _set_stacks(state, 0, "cf_test_crop", [(0, 2, 0, 0)])
    state = _set_stacks(state, 0, "cf_test_wood", [(0, 0, 3, 0), (0, 0, 1, 0)])
    g0 = state.players[0].resources
    nxt, occasion = field_take(state, 0)
    p = nxt.players[0]
    # Board entry first, then card entries sorted by card id.
    sources = [e.source for e in occasion.entries]
    assert sources == ["cell:2,0", "card:cf_test_crop",
                       "card:cf_test_wood", "card:cf_test_wood"]
    by_src = {}
    for e in occasion.entries:
        by_src.setdefault(e.source, []).append(e)
    crop_e = by_src["card:cf_test_crop"][0]
    assert (crop_e.crop, crop_e.amount, crop_e.emptied) == ("veg", 1, False)
    wood_es = by_src["card:cf_test_wood"]
    assert sorted((e.amount, e.emptied) for e in wood_es) == [(1, False), (1, True)]
    # Gains: 1 grain (board) + 1 veg + 2 wood.
    assert p.resources.grain - g0.grain == 1
    assert p.resources.veg - g0.veg == 1
    assert p.resources.wood - g0.wood == 2
    # Store write-back, canonical: (3,1)-wood became (2,0) -> sorted desc.
    assert card_field_stacks(p, "cf_test_crop") == ((0, 1, 0, 0),)
    assert card_field_stacks(p, "cf_test_wood") == ((0, 0, 2, 0), (0, 0, 0, 0))


def test_field_take_empties_card_and_removes_store_entry():
    state = _base()
    state = _own(state, 0, ["cf_test_crop"])
    pristine = state.players[0].card_state
    state = _set_stacks(state, 0, "cf_test_crop", [(1, 0, 0, 0)])
    nxt, occasion = field_take(state, 0)
    e = [e for e in occasion.entries if e.source == "card:cf_test_crop"][0]
    assert e.emptied and e.crop == "grain"
    # Harvested-out card == never-sown card (the store entry is gone).
    assert nxt.players[0].card_state == pristine


def test_mixed_stack_takes_grain_before_veg():
    # A Heresy-Teacher-shaped stack (veg below the grain): the take removes
    # grain first, exactly like a grid cell.
    state = _base()
    state = _own(state, 0, ["cf_test_crop"])
    state = _set_stacks(state, 0, "cf_test_crop", [(1, 1, 0, 0)])
    nxt, occasion = field_take(state, 0)
    e = [e for e in occasion.entries if e.source == "card:cf_test_crop"][0]
    assert (e.crop, e.amount, e.emptied) == ("grain", 1, True)
    assert card_field_stacks(nxt.players[0], "cf_test_crop") == ((0, 1, 0, 0),)


# ---------------------------------------------------------------------------
# Ruling 46 — the take-modifier folds reach card-fields
# ---------------------------------------------------------------------------

def test_scythe_worker_fold_reaches_card_grain():
    state = _base()
    state = _own(state, 0, ["cf_test_crop"])
    state = _set_stacks(state, 0, "cf_test_crop", [(3, 0, 0, 0)])
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {"scythe_worker"})
        if i == 0 else state.players[i] for i in range(2)))
    plan = fold_chosen_modifiers(state, 0, ())
    assert plan.extras.get(("card", "cf_test_crop", 0)) == 1
    nxt, occasion = field_take(state, 0, extra_takes=plan.extras)
    e = [e for e in occasion.entries if e.source == "card:cf_test_crop"][0]
    assert (e.crop, e.amount) == ("grain", 2)
    assert card_field_stacks(nxt.players[0], "cf_test_crop") == ((1, 0, 0, 0),)


def test_stable_manure_donates_from_card_field():
    from agricola.cards.stable_manure import _variants
    state = _base()
    state = _own(state, 0, ["stable_manure", "cf_test_wood"])
    state = _set_stacks(state, 0, "cf_test_wood", [(0, 0, 3, 0), (0, 0, 1, 0)])
    # One unfenced stable -> cap 1.
    p = state.players[0]
    grid = [list(row) for row in p.farmyard.grid]
    grid[2][4] = fast_replace(grid[2][4], cell_type=CellType.STABLE)
    p = fast_replace(p, farmyard=fast_replace(
        p.farmyard, grid=tuple(tuple(r) for r in grid)))
    state = fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))
    assert "cf_cf_test_wood:1" in _variants(state, 0)
    plan = fold_chosen_modifiers(
        state, 0, (("stable_manure", "cf_cf_test_wood:1"),))
    # The max-spare stack (3 wood) donates the +1; the 1-wood stack cannot.
    assert plan.extras == {("card", "cf_test_wood", 0): 1}
    nxt, occasion = field_take(state, 0, extra_takes=plan.extras)
    assert nxt.players[0].resources.wood - state.players[0].resources.wood == 3
    assert card_field_stacks(nxt.players[0], "cf_test_wood") == (
        (0, 0, 1, 0), (0, 0, 0, 0))


def test_grain_thief_replaces_card_field():
    from agricola.cards.grain_thief import _variants
    state = _base()
    state = _own(state, 0, ["cf_test_crop"])
    state = _set_stacks(state, 0, "cf_test_crop", [(2, 0, 0, 0)])
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {"grain_thief"})
        if i == 0 else state.players[i] for i in range(2)))
    assert "cf_cf_test_crop:1" in _variants(state, 0)
    plan = fold_chosen_modifiers(
        state, 0, (("grain_thief", "cf_cf_test_crop:1"),))
    assert ("card", "cf_test_crop", 0) in plan.skipped
    g0 = state.players[0].resources.grain
    nxt, occasion = field_take(state, 0, skip_cells=plan.skipped,
                               bonus=plan.bonus)
    # Replaced: no manifest entry, grain stays on the card, +1 supply grain.
    assert all(e.source != "card:cf_test_crop" for e in occasion.entries)
    assert card_field_stacks(nxt.players[0], "cf_test_crop") == ((2, 0, 0, 0),)
    assert nxt.players[0].resources.grain - g0 == 1


# ---------------------------------------------------------------------------
# Ruling 45 — scoring
# ---------------------------------------------------------------------------

def test_scoring_counts_card_fields_and_their_crops():
    state = _base()
    _, base_bd = score(state, 0)
    owned = _own(state, 0, ["cf_test_crop", "cf_test_wood"])
    owned = _set_stacks(owned, 0, "cf_test_crop", [(3, 0, 0, 0)])
    owned = _set_stacks(owned, 0, "cf_test_wood", [(0, 0, 3, 0), (0, 0, 0, 0)])
    _, bd = score(owned, 0)
    # 0 fields -> 2 fields: -1 becomes 1 point (each card = 1 field, ruling
    # 47 — the 2-stack wood card counts once). 3 planted grain: 0 -> 3 grain
    # is 1 point vs -1. Wood on the card scores nothing.
    assert bd.field_tiles == 1 and base_bd.field_tiles == -1
    assert bd.grain == 1 and base_bd.grain == -1


# ---------------------------------------------------------------------------
# Family invariance — wire + canonical
# ---------------------------------------------------------------------------

def test_family_wire_and_canonical_unchanged():
    # The action wire: default card_sows is omitted; non-default round-trips.
    params = action_to_params(CommitSow(grain=1, veg=0))
    assert params == {"grain": 1, "veg": 0}
    rich = CommitSow(grain=0, veg=1, card_sows=(("cf_test_crop", "grain"),))
    rt = action_from_params("CommitSow", action_to_params(rich))
    assert rt == rich
    # The frame canonical: crops_only/max_fields omitted at default.
    js = to_canonical(PendingSow(player_idx=0, initiated_by_id="x"))
    assert "crops_only" not in js and "max_fields" not in js
