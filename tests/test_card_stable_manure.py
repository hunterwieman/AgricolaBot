import agricola.cards.stable_manure  # noqa: F401
"""Tests for Stable Manure (minor improvement, D72; Dulcinaria Expansion;
Crop Provider).

Card text: "In the field phase of each harvest, you can harvest 1 additional good
from a number of fields equal to the number of unfenced stables you have."

A Category-6 harvest-field hook: take 1 additional good (grain or veg) FROM each
of up to N fields, where N = the number of unfenced stables; only a field with
>= 2 of its crop can spare the extra (its single crop otherwise belongs to the
normal take). Fires BEFORE the mechanical take (`_resolve_harvest_field`) while
fields are still fully sown, so a benefited field is depleted by 2 total. Modeled
mandatory-take-the-maximum (Scythe Worker convention). Prereq "At Most 1
Occupation" → max_occupations=1.
"""
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import HARVEST_FIELD_CARDS, should_host_harvest_field
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_sown_fields

CARD_ID = "stable_manure"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _own_occupations(state, idx, occ_ids):
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(occ_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _with_stables(state, idx, cells):
    """Place unfenced STABLE cells at the given (row, col) positions."""
    return with_grid(state, idx, {(r, c): Cell(cell_type=CellType.STABLE) for (r, c) in cells})


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_and_harvest_field_card():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_FIELD_CARDS
    spec = MINORS[CARD_ID]
    # Free, no printed VPs, no custom prereq predicate, not a passing card.
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.cost == Resources() or spec.cost.__class__.__name__ == "Cost"


def test_prereq_at_most_one_occupation():
    spec = MINORS[CARD_ID]
    assert spec.max_occupations == 1
    state = setup(0)
    # 0 occupations -> ok; 1 occupation -> ok; 2 occupations -> blocked.
    assert prereq_met(spec, _own_occupations(state, 0, []), 0) is True
    assert prereq_met(spec, _own_occupations(state, 0, ["consultant"]), 0) is True
    assert prereq_met(
        spec, _own_occupations(state, 0, ["consultant", "priest"]), 0
    ) is False


# ---------------------------------------------------------------------------
# Hosting gate — card-dependent push
# ---------------------------------------------------------------------------

def test_no_host_without_card():
    assert should_host_harvest_field(setup(0)) is False


def test_host_when_owned():
    assert should_host_harvest_field(_own_minor(setup(0), 0, CARD_ID)) is True
    # Owned by the OTHER player still hosts (autos fire per-owner).
    assert should_host_harvest_field(_own_minor(setup(0), 1, CARD_ID)) is True


def test_no_host_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_minors=p.hand_minors | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]))
    assert should_host_harvest_field(state) is False


# ---------------------------------------------------------------------------
# The bonus: 1 extra good per field, capped by unfenced stables
# ---------------------------------------------------------------------------

# NOTE: `_resolve_harvest_field` fires the hook AND does the mechanical take.
# So a benefited 3-grain field: supply gains 1 (extra) + 1 (take) = 2, field
# 3 -> 1. A non-benefited sown field: supply +1 (take only), field 3 -> 2.

def test_no_stable_no_bonus():
    """With no unfenced stable (cap 0), the eligible >=2 fields get no extra —
    only the mechanical take fires (supply +1, field 3 -> 2)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])  # 3 grain, but cap 0
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == g0 + 1   # take only, no extra
    assert after.players[0].farmyard.grid[0][0].grain == 2  # 3 - 1(take)


def test_one_stable_one_extra_grain():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])             # 1 unfenced stable -> cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])  # 3 grain
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    # +1 extra (hook) +1 take = +2 grain to supply; field 3 -> 1.
    assert after.players[0].resources.grain == g0 + 2
    assert after.players[0].farmyard.grid[0][0].grain == 1  # 3 - 1(extra) - 1(take)


def test_cap_limits_number_of_fields():
    """One stable (cap 1) but two eligible fields -> only ONE extra good total.
    Both fields still get the mechanical take, so supply = 1(extra) + 2(takes)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == g0 + 3  # 1 extra (capped) + 2 takes
    # Exactly one field got the extra (depleted to 1); the other only the take (2).
    fields = sorted(
        after.players[0].farmyard.grid[r][c].grain
        for (r, c) in [(0, 0), (1, 1)]
    )
    assert fields == [1, 2]


def test_two_stables_two_extras():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])    # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == g0 + 4  # 2 extras + 2 takes
    assert after.players[0].farmyard.grid[0][0].grain == 1
    assert after.players[0].farmyard.grid[1][1].grain == 1


def test_extra_applies_to_veg_too():
    """The 'additional good' is the field's crop — a >=2-veg field spares veg."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, veg_fields=[(0, 0)])  # 2 veg
    v0 = state.players[0].resources.veg
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.veg == v0 + 2   # 1 extra + 1 take
    assert after.players[0].farmyard.grid[0][0].veg == 0  # 2 - 1(extra) - 1(take)


def test_one_count_field_cannot_spare():
    """A field with a single good gives it to the normal take, not the bonus —
    supply +1 (take only), field 1 -> 0, no extra even though cap is 1."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == g0 + 1  # take only, no extra
    assert after.players[0].farmyard.grid[0][0].grain == 0  # only the take


def test_cap_exceeds_eligible_fields():
    """Cap larger than the eligible fields takes only what is available."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4), (2, 4)])  # cap 3
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])  # only 1 eligible
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == g0 + 2  # 1 extra + 1 take


def test_no_eligible_field_no_bonus():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])  # cap 1, but no sown field
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == g0  # no fields at all -> nothing


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_eligible_requires_stable_and_field():
    from agricola.cards.stable_manure import _eligible
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Field but no stable -> ineligible.
    s1 = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert _eligible(s1, 0) is False
    # Stable but no >=2 field -> ineligible.
    s2 = _with_stables(state, 0, [(0, 4)])
    assert _eligible(s2, 0) is False
    # Both -> eligible.
    s3 = with_sown_fields(s2, 0, grain_fields=[(0, 0)])
    assert _eligible(s3, 0) is True


def test_fenced_stable_does_not_count():
    """count_unfenced_stables: a stable in a pasture doesn't raise the cap.

    We don't build a pasture here (geometry is heavy); instead we confirm the cap
    comes from `count_unfenced_stables`, which excludes pasture-enclosed stables.
    A bare stable on an open grid is unfenced, so it counts (cap 1)."""
    from agricola.cards.stable_architect import count_unfenced_stables
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    assert count_unfenced_stables(state.players[0].farmyard) == 1


# ---------------------------------------------------------------------------
# Scoping: fires only for its owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Both players have a stable and an eligible field, but only P0 owns the card.
    state = _with_stables(state, 0, [(0, 4)])
    state = _with_stables(state, 1, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    # Owner: extra + take -> supply +2, field 3 -> 1.
    assert after.players[0].resources.grain == g0 + 2
    assert after.players[0].farmyard.grid[0][0].grain == 1
    # Non-owner: only the mechanical take (no extra) -> field 3 -> 2.
    assert after.players[1].farmyard.grid[0][0].grain == 2


def test_fires_for_owner_in_seat_one():
    state = _own_minor(_field_state(), 1, CARD_ID)
    state = _with_stables(state, 1, [(0, 4), (1, 4)])      # cap 2
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    g1 = state.players[1].resources.grain
    v1 = state.players[1].resources.veg
    after = _resolve_harvest_field(state)
    # One grain field + one veg field, cap 2 -> both get the extra. Each crop:
    # extra + take = +2 grain and +2 veg.
    assert after.players[1].resources.grain == g1 + 2
    assert after.players[1].resources.veg == v1 + 2
