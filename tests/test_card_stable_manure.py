import agricola.cards.stable_manure  # noqa: F401
"""Tests for Stable Manure (minor improvement, D72; Dulcinaria Expansion;
Crop Provider).

Card text: "In the field phase of each harvest, you can harvest 1 additional good
from a number of fields equal to the number of unfenced stables you have."

A Category-6 harvest-field TRIGGER — the field phase's first surfaced choice
(user ruling 2026-07): at the per-player PendingHarvestField choice host (pushed
by `_resolve_harvest_field` before the mechanical take), the card offers one
FireTrigger per legal count vector over the donor-field groups (fields grouped by
crop kind + crops remaining, counts summing 1..N where N = unfenced stables);
declining is the host's Proceed. A benefited field is depleted by 2 this harvest
(1 extra + 1 mechanical take); only a field with >= 2 of its crop can spare the
extra. Prereq "At Most 1 Occupation" → max_occupations=1.
"""
from agricola.actions import FireTrigger, Proceed
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    CARDS,
    HARVEST_FIELD_CARDS,
    PLAY_VARIANT_TRIGGERS,
    should_host_harvest_field,
)
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestField
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


def _enter_field(state):
    """Walk into the field phase — pushes the choice frame(s) when a field-phase
    trigger is eligible, else runs straight through to HARVEST_FEED."""
    return _advance_until_decision(state)


def _variants_offered(state):
    """The stable_manure variant strings offered at the current choice host."""
    return sorted(a.variant for a in legal_actions(state)
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


def _fire(state, variant):
    """Fire the chosen variant, then Proceed past the (now trigger-less) host."""
    state = step(state, FireTrigger(card_id=CARD_ID, variant=variant))
    return step(state, Proceed())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_and_field_phase_trigger():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_FIELD_CARDS
    assert CARD_ID in CARDS                    # an optional trigger, not an auto
    assert CARD_ID in PLAY_VARIANT_TRIGGERS    # variant-expanded (count vectors)
    spec = MINORS[CARD_ID]
    # Free, no printed VPs, no custom prereq predicate, not a passing card.
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.passing_left is False


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
    # Owned by the OTHER player still hosts (fires per-owner).
    assert should_host_harvest_field(_own_minor(setup(0), 1, CARD_ID)) is True


def test_no_host_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_minors=p.hand_minors | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]))
    assert should_host_harvest_field(state) is False


def test_no_choice_frame_when_ineligible():
    """Owned but ineligible (no stable): the field phase runs straight through
    to FEED — no choice frame, flag untouched."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])   # field, but cap 0
    after = _enter_field(state)
    assert after.phase == Phase.HARVEST_FEED
    assert after.field_triggers_offered is False


# ---------------------------------------------------------------------------
# The choice host: frame push, option enumeration, decline
# ---------------------------------------------------------------------------

def test_choice_frame_pushed_when_eligible():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    after = _enter_field(state)
    top = after.pending_stack[-1]
    assert isinstance(top, PendingHarvestField) and top.player_idx == 0
    assert after.field_triggers_offered is True
    assert after.phase == Phase.HARVEST_FIELD    # take not yet run


def test_variant_enumeration_groups_and_cap():
    """Two 3-grain fields + one 2-veg field, cap 2: every count vector over the
    groups {grain3: 2 fields, veg2: 1 field} with total 1..2."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)],
                             veg_fields=[(2, 2)])
    after = _enter_field(state)
    assert _variants_offered(after) == sorted(
        ["grain3:1", "grain3:2", "veg2:1", "grain3:1|veg2:1"])
    # Proceed (decline) is always available alongside the options.
    assert Proceed() in legal_actions(after)


def test_variant_cap_one_restricts_totals():
    """Same fields, cap 1: only the single-take vectors."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)],
                             veg_fields=[(2, 2)])
    after = _enter_field(state)
    assert _variants_offered(after) == sorted(["grain3:1", "veg2:1"])


def test_fields_group_by_crops_remaining():
    """A 3-grain field and a 2-grain field are DIFFERENT groups — choosing which
    to deplete is the strategic choice the enumeration preserves."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (1, 1): Cell(cell_type=CellType.FIELD, grain=2),
    })
    after = _enter_field(state)
    assert _variants_offered(after) == sorted(["grain2:1", "grain3:1"])


def test_decline_via_proceed_takes_nothing_extra():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain
    g0 = state.players[0].resources.grain
    after = _enter_field(state)
    after = step(after, Proceed())                               # decline
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[0].resources.grain == g0 + 1            # take only
    assert after.players[0].farmyard.grid[0][0].grain == 2       # 3 - 1(take)
    assert after.field_triggers_offered is False                 # flag reset


def test_once_per_harvest_then_proceed_only():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    after = _enter_field(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    # Fired once: recorded in triggers_resolved, only Proceed remains.
    assert legal_actions(after) == [Proceed()]


# ---------------------------------------------------------------------------
# The bonus through the real flow: extra + mechanical take
# ---------------------------------------------------------------------------

# NOTE: after the choice resolves, the mechanical take runs. So a benefited
# 3-grain field: supply gains 1 (extra) + 1 (take) = 2, field 3 -> 1. A
# non-benefited sown field: supply +1 (take only), field 3 -> 2.

def test_one_stable_one_extra_grain():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain
    g0 = state.players[0].resources.grain
    after = _fire(_enter_field(state), "grain3:1")
    assert after.players[0].resources.grain == g0 + 2            # extra + take
    assert after.players[0].farmyard.grid[0][0].grain == 1       # 3 - 1 - 1


def test_partial_take_is_a_real_option():
    """Cap 2 with two eligible fields — taking only ONE extra is offered and
    leaves the other field at full yield (the choice the auto model destroyed)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    g0 = state.players[0].resources.grain
    after = _fire(_enter_field(state), "grain3:1")               # 1 of the 2 allowed
    assert after.players[0].resources.grain == g0 + 3            # 1 extra + 2 takes
    fields = sorted(after.players[0].farmyard.grid[r][c].grain
                    for (r, c) in [(0, 0), (1, 1)])
    assert fields == [1, 2]                                      # one depleted by 2, one by 1


def test_two_stables_two_extras():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    g0 = state.players[0].resources.grain
    after = _fire(_enter_field(state), "grain3:2")
    assert after.players[0].resources.grain == g0 + 4            # 2 extras + 2 takes
    assert after.players[0].farmyard.grid[0][0].grain == 1
    assert after.players[0].farmyard.grid[1][1].grain == 1


def test_extra_applies_to_veg_too():
    """The 'additional good' is the field's crop — a >=2-veg field spares veg."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, veg_fields=[(0, 0)])      # 2 veg
    v0 = state.players[0].resources.veg
    after = _fire(_enter_field(state), "veg2:1")
    assert after.players[0].resources.veg == v0 + 2              # extra + take
    assert after.players[0].farmyard.grid[0][0].veg == 0         # 2 - 1 - 1


def test_mixed_crop_vector():
    """A single fired vector can span groups: one grain extra + one veg extra."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    g0 = state.players[0].resources.grain
    v0 = state.players[0].resources.veg
    after = _fire(_enter_field(state), "grain3:1|veg2:1")
    assert after.players[0].resources.grain == g0 + 2            # extra + take
    assert after.players[0].resources.veg == v0 + 2              # extra + take


def test_one_count_field_cannot_spare():
    """A field with a single good gives it to the normal take, not the bonus —
    no donor group exists, so no choice frame is pushed at all."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    g0 = state.players[0].resources.grain
    after = _enter_field(state)
    assert after.phase == Phase.HARVEST_FEED                     # no decision
    assert after.players[0].resources.grain == g0 + 1            # take only
    assert after.players[0].farmyard.grid[0][0].grain == 0


def test_cap_exceeds_eligible_fields():
    """Cap larger than the eligible fields offers only what is available."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4), (2, 4)])    # cap 3
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # only 1 eligible
    after = _enter_field(state)
    assert _variants_offered(after) == ["grain3:1"]
    g0 = state.players[0].resources.grain
    after = _fire(after, "grain3:1")
    assert after.players[0].resources.grain == g0 + 2            # 1 extra + 1 take


def test_no_eligible_field_no_bonus():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])   # cap 1, but no sown field
    g0 = state.players[0].resources.grain
    after = _enter_field(state)
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[0].resources.grain == g0                # nothing


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_eligible_requires_stable_and_field():
    from agricola.cards.stable_manure import _eligible
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Field but no stable -> ineligible.
    s1 = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert _eligible(s1, 0, frozenset()) is False
    # Stable but no >=2 field -> ineligible.
    s2 = _with_stables(state, 0, [(0, 4)])
    assert _eligible(s2, 0, frozenset()) is False
    # Both -> eligible.
    s3 = with_sown_fields(s2, 0, grain_fields=[(0, 0)])
    assert _eligible(s3, 0, frozenset()) is True


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
# Scoping: fires only for its owner; two-owner ordering
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Both players have a stable and an eligible field, but only P0 owns the card.
    state = _with_stables(state, 0, [(0, 4)])
    state = _with_stables(state, 1, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    g0 = state.players[0].resources.grain
    after = _enter_field(state)
    # Exactly one choice frame — the owner's.
    frames = [f for f in after.pending_stack if isinstance(f, PendingHarvestField)]
    assert [f.player_idx for f in frames] == [0]
    after = _fire(after, "grain3:1")
    # Owner: extra + take -> supply +2, field 3 -> 1.
    assert after.players[0].resources.grain == g0 + 2
    assert after.players[0].farmyard.grid[0][0].grain == 1
    # Non-owner: only the mechanical take (no extra) -> field 3 -> 2.
    assert after.players[1].farmyard.grid[0][0].grain == 2


def test_fires_for_owner_in_seat_one():
    state = _own_minor(_field_state(), 1, CARD_ID)
    state = _with_stables(state, 1, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    g1 = state.players[1].resources.grain
    v1 = state.players[1].resources.veg
    after = _enter_field(state)
    assert after.pending_stack[-1].player_idx == 1
    after = _fire(after, "grain3:1|veg2:1")
    assert after.players[1].resources.grain == g1 + 2
    assert after.players[1].resources.veg == v1 + 2


def test_both_owners_starting_player_resolves_first():
    state = _field_state()
    sp = state.starting_player
    for i in (0, 1):
        state = _own_minor(state, i, CARD_ID)
        state = _with_stables(state, i, [(0, 4)])
        state = with_sown_fields(state, i, grain_fields=[(0, 0)])
    after = _enter_field(state)
    frames = [f.player_idx for f in after.pending_stack
              if isinstance(f, PendingHarvestField)]
    # One frame per player; SP on TOP (resolves first), mirroring FEED/BREED.
    assert sorted(frames) == [0, 1]
    assert after.pending_stack[-1].player_idx == sp
    # Resolve both (SP fires, other declines) and reach FEED with the flag reset.
    after = _fire(after, "grain3:1")                             # SP's frame
    assert after.pending_stack[-1].player_idx == 1 - sp
    after = step(after, Proceed())                               # other declines
    assert after.phase == Phase.HARVEST_FEED
    assert after.field_triggers_offered is False
