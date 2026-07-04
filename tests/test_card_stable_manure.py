import agricola.cards.stable_manure  # noqa: F401
"""Tests for Stable Manure (minor improvement, D72; Dulcinaria Expansion;
Crop Provider).

Card text: "In the field phase of each harvest, you can harvest 1 additional good
from a number of fields equal to the number of unfenced stables you have."

A during-window ("field_phase", harvest window #5) class-(a) FREE-ORDERED
independent trigger (HARVEST_WINDOWS_DESIGN.md §4a, user ruling 2026-07-03):
surfaced on the per-player `PendingFieldPhase` host as one FireTrigger per legal
count vector over the donor-field groups (fields grouped by crop kind + crops
remaining, counts summing 1..N where N = unfenced stables), freely orderable
BEFORE or AFTER the mandatory crop take (`CommitFieldTake`). Declining is
take + Proceed. Its extra goods are their OWN harvesting occasion
(`source="card:stable_manure"`, ruling 5), recorded on the frame's `occasions`
manifest. A field benefited while still planted is depleted by the extra plus the
take; only a field with >= 2 of its crop can spare the extra. Prereq "At Most 1
Occupation" → max_occupations=1.
"""
from agricola.actions import CommitFieldTake, FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS, owns_window_card
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingFieldPhase
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


def _with_food(state, idx, food=10):
    p = state.players[idx]
    p = fast_replace(p, resources=fast_replace(p.resources, food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _with_stables(state, idx, cells):
    """Place unfenced STABLE cells at the given (row, col) positions."""
    return with_grid(state, idx, {(r, c): Cell(cell_type=CellType.STABLE) for (r, c) in cells})


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet), both players fed so the
    feeding phase never blocks the walk."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    return _with_food(_with_food(state, 0), 1)


def _walk_to_field_frame(state):
    """Advance until a PendingFieldPhase host surfaces (or the harvest ends when
    no field-phase trigger is eligible — the take runs inline)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingFieldPhase):
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _variants_offered(state):
    """The stable_manure variant strings offered at the current field-phase host."""
    return sorted(a.variant for a in legal_actions(state)
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


def _own_occasions(state):
    """The occasions recorded on the current PendingFieldPhase host (frame log)."""
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase)
    return top.occasions


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_and_field_phase_trigger():
    assert CARD_ID in MINORS
    # New during-window ("field_phase") hosting index; the legacy harvest_field
    # registration is gone.
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("field_phase", set())
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
# Hosting gate — card-dependent field-phase host (new machinery)
# ---------------------------------------------------------------------------

def test_no_host_without_card():
    assert owns_window_card(setup(0).players[0], "field_phase") is False


def test_host_when_owned():
    s0 = _own_minor(setup(0), 0, CARD_ID)
    assert owns_window_card(s0.players[0], "field_phase") is True
    # Owned by the OTHER player hosts that player's window (fires per-owner).
    s1 = _own_minor(setup(0), 1, CARD_ID)
    assert owns_window_card(s1.players[1], "field_phase") is True


def test_no_host_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_minors=p.hand_minors | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]))
    assert owns_window_card(state.players[0], "field_phase") is False


def test_no_frame_when_ineligible():
    """Owned but ineligible (no stable): the field phase runs the take inline —
    no PendingFieldPhase frame surfaces from this card, and the take still runs
    (field 3 -> 2, supply +1)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])   # field, but cap 0
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD                  # past the field phase
    assert not any(isinstance(f, PendingFieldPhase) for f in after.pending_stack)
    assert after.players[0].resources.grain == g0 + 1          # take only
    assert after.players[0].farmyard.grid[0][0].grain == 2


# ---------------------------------------------------------------------------
# The field-phase host: frame push, option enumeration, free order
# ---------------------------------------------------------------------------

def test_frame_pushed_when_eligible():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    assert not top.take_fired                    # take is still owed
    assert top.occasions == ()
    assert after.phase == Phase.HARVEST_FIELD


def test_variant_enumeration_groups_and_cap():
    """Two 3-grain fields + one 2-veg field, cap 2: every count vector over the
    groups {grain3: 2 fields, veg2: 1 field} with total 1..2 — offered pre-take."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)],
                             veg_fields=[(2, 2)])
    after = _walk_to_field_frame(state)
    assert _variants_offered(after) == sorted(
        ["grain3:1", "grain3:2", "veg2:1", "grain3:1|veg2:1"])
    # The take is offered alongside the trigger variants (free order); Proceed is
    # withheld until the (mandatory) take fires.
    assert CommitFieldTake() in legal_actions(after)
    assert Proceed() not in legal_actions(after)


def test_variant_cap_one_restricts_totals():
    """Same fields, cap 1: only the single-take vectors."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)],
                             veg_fields=[(2, 2)])
    after = _walk_to_field_frame(state)
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
    after = _walk_to_field_frame(state)
    assert _variants_offered(after) == sorted(["grain2:1", "grain3:1"])


def test_once_per_field_phase_then_take_and_proceed():
    """Fired once, the trigger is spent (frame's triggers_resolved); only the
    still-owed take, then Proceed, remain."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    # Fired once: no more stable_manure variants; the take is still owed.
    assert _variants_offered(after) == []
    assert legal_actions(after) == [CommitFieldTake()]


# ---------------------------------------------------------------------------
# Fire BEFORE the take (preserves the old pre-take outcomes)
# ---------------------------------------------------------------------------

# NOTE: firing the extra pre-take then running the take: a benefited 3-grain
# field loses 1 (extra) + 1 (take) = 2, ending at 1. A non-benefited sown field
# loses 1 (take only). This mirrors the outcomes of the retired pre-take host.

def test_fire_before_take_one_stable_one_extra_grain():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[0].resources.grain == g0 + 2            # extra + take
    assert after.players[0].farmyard.grid[0][0].grain == 1       # 3 - 1 - 1


def test_fire_before_take_partial_take_is_a_real_option():
    """Cap 2 with two eligible fields — taking only ONE extra pre-take leaves the
    other field at full yield (minus the mechanical take)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[0].resources.grain == g0 + 3            # 1 extra + 2 takes
    fields = sorted(after.players[0].farmyard.grid[r][c].grain
                    for (r, c) in [(0, 0), (1, 1)])
    assert fields == [1, 2]                                      # one -2, one -1


def test_fire_before_take_extra_applies_to_veg_too():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, veg_fields=[(0, 0)])      # 2 veg
    v0 = state.players[0].resources.veg
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="veg2:1"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[0].resources.veg == v0 + 2             # extra + take
    assert after.players[0].farmyard.grid[0][0].veg == 0        # 2 - 1 - 1


def test_fire_before_take_depletes_three_count_field_to_one():
    """The brief's headline pre-take outcome: extra + take depletes a 3-count
    field to 1 (a benefited field loses 2 total)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])           # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (1, 1)])
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:2"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[0].resources.grain == g0 + 4          # 2 extras + 2 takes
    assert after.players[0].farmyard.grid[0][0].grain == 1
    assert after.players[0].farmyard.grid[1][1].grain == 1


# ---------------------------------------------------------------------------
# Fire AFTER the take (the new free-order semantics)
# ---------------------------------------------------------------------------

def test_fire_after_take_field_emptied_by_take_is_no_longer_a_variant():
    """A 1-count field, emptied by the take, can no longer spare an extra — after
    the take it drops out of the donor groups. So a lone 1-grain field with no
    other donor leaves NO variant, and the frame exits with the take only."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    # A 2-grain field (donor pre-take) — the take will drop it to 1.
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    # Pre-take: the 2-grain field is a donor.
    assert _variants_offered(after) == ["grain2:1"]
    after = step(after, CommitFieldTake())                       # 2 -> 1
    # Post-take: the field now holds 1 grain — no donor group survives, so no
    # variant is offered; only Proceed remains.
    assert _variants_offered(after) == []
    assert legal_actions(after) == [Proceed()]
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[0].resources.grain == g0 + 1           # take only
    assert after.players[0].farmyard.grid[0][0].grain == 1      # extra was unavailable


def test_fire_after_take_still_available_on_a_surviving_donor():
    """Free order: a field with 3 crops is still a donor AFTER the take dropped it
    to 2, so the extra can be taken post-take (ending the field at 1)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    after = step(after, CommitFieldTake())                       # 3 -> 2
    assert _variants_offered(after) == ["grain2:1"]             # post-take grouping
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain2:1"))
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[0].resources.grain == g0 + 2           # take + extra
    assert after.players[0].farmyard.grid[0][0].grain == 1      # 3 - 1 - 1


# ---------------------------------------------------------------------------
# Decline via take + Proceed
# ---------------------------------------------------------------------------

def test_decline_via_take_then_proceed_takes_nothing_extra():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    after = step(after, CommitFieldTake())                       # take, no extra
    after = step(after, Proceed())                               # decline the trigger
    after = _advance_until_decision(after)
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[0].resources.grain == g0 + 1            # take only
    assert after.players[0].farmyard.grid[0][0].grain == 2       # 3 - 1(take)


# ---------------------------------------------------------------------------
# The emitted occasion (ruling 5): the extras are their own harvesting occasion
# ---------------------------------------------------------------------------

def test_extra_emits_its_own_occasion():
    """Firing the extra records a HarvestOccasion on the frame with source
    "card:stable_manure", separate from the take occasion — pre-take here, so the
    take occasion follows it."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                    # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain at (0,0)
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    occ = _own_occasions(after)
    # Exactly the card's own occasion so far (take not yet fired).
    assert [o.source for o in occ] == [f"card:{CARD_ID}"]
    card_occ = occ[0]
    assert len(card_occ.entries) == 1
    e = card_occ.entries[0]
    assert e.source == "cell:0,0" and e.crop == "grain" and e.amount == 1
    assert e.emptied is False                                   # 3 - 1 = 2 left
    # After the take, both occasions are on the frame (card occasion, then take).
    after = step(after, CommitFieldTake())
    occ = _own_occasions(after)
    assert [o.source for o in occ] == [f"card:{CARD_ID}", "take"]


def test_extra_occasion_entry_is_never_emptied():
    """The extra can never take a field's LAST crop: a donor needs >= 2 of its
    crop at fire time and the extra removes exactly 1, so the field is left with
    >= 1 — the card occasion's entry is therefore never `emptied`. Pinned for
    both crops and both fire orders (pre-take here; the post-take donor path is
    covered by test_fire_after_take_still_available_on_a_surviving_donor)."""
    # grain donor at 3 -> 2 (not emptied)
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # 3 grain
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    card_occ = [o for o in _own_occasions(after) if o.source == f"card:{CARD_ID}"][0]
    assert card_occ.entries[0].crop == "grain"
    assert card_occ.entries[0].emptied is False                 # 3 - 1 = 2 left
    # veg donor at 2 -> 1 (not emptied)
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, veg_fields=[(0, 0)])      # 2 veg
    after = _walk_to_field_frame(state)
    after = step(after, FireTrigger(card_id=CARD_ID, variant="veg2:1"))
    card_occ = [o for o in _own_occasions(after) if o.source == f"card:{CARD_ID}"][0]
    assert card_occ.entries[0].crop == "veg" and card_occ.entries[0].amount == 1
    assert card_occ.entries[0].emptied is False                 # 2 - 1 = 1 left


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
    """count_unfenced_stables: a stable in a pasture doesn't raise the cap. A bare
    stable on an open grid is unfenced, so it counts (cap 1)."""
    from agricola.cards.stable_architect import count_unfenced_stables
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    assert count_unfenced_stables(state.players[0].farmyard) == 1


def test_cap_exceeds_eligible_fields():
    """Cap larger than the eligible fields offers only what is available."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4), (2, 4)])    # cap 3
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])    # only 1 eligible
    after = _walk_to_field_frame(state)
    assert _variants_offered(after) == ["grain3:1"]


def test_no_eligible_field_no_frame():
    """A stable but no donor field: no field-phase trigger fires; the field phase
    passes with no extra taken and no host frame."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])   # cap 1, but no sown field
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD
    assert not any(isinstance(f, PendingFieldPhase) for f in after.pending_stack)
    assert after.players[0].resources.grain == g0               # nothing


# ---------------------------------------------------------------------------
# Scoping: fires only for its owner; two-owner ordering (per-player FIELD band)
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Both players have a stable and an eligible field, but only P0 owns the card.
    state = _with_stables(state, 0, [(0, 4)])
    state = _with_stables(state, 1, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    g_owner = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    # The host that surfaces is the owner's (P0) — the non-owner's field phase
    # runs the take inline (no field_phase trigger to host).
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    # Owner: extra + take -> supply +2, field 3 -> 1.
    assert after.players[0].resources.grain == g_owner + 2
    assert after.players[0].farmyard.grid[0][0].grain == 1
    # Non-owner: only the mechanical take (no extra) -> field 3 -> 2.
    assert after.players[1].farmyard.grid[0][0].grain == 2


def test_fires_for_owner_in_seat_one():
    state = _own_minor(_field_state(), 1, CARD_ID)
    state = _with_stables(state, 1, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    g1 = state.players[1].resources.grain
    v1 = state.players[1].resources.veg
    after = _walk_to_field_frame(state)
    assert after.pending_stack[-1].player_idx == 1
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1|veg2:1"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.players[1].resources.grain == g1 + 2           # extra + take
    assert after.players[1].resources.veg == v1 + 2             # extra + take


def test_both_owners_starting_player_resolves_first():
    """The FIELD band is per-player (user ruling 3, HARVEST_WINDOWS_DESIGN.md §3):
    the starting player resolves their WHOLE field phase — frame (trigger + take)
    — before the other player's begins, so only one PendingFieldPhase frame is
    ever out at a time."""
    state = _field_state()
    sp = state.starting_player
    for i in (0, 1):
        state = _own_minor(state, i, CARD_ID)
        state = _with_stables(state, i, [(0, 4)])
        state = with_sown_fields(state, i, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    frames = [f.player_idx for f in after.pending_stack
              if isinstance(f, PendingFieldPhase)]
    # Only the starting player's frame is out; the other player's field phase has
    # not started yet (their field untaken).
    assert frames == [sp]
    assert after.players[1 - sp].farmyard.grid[0][0].grain == 3  # untaken
    # SP fires + takes + proceeds; then the other player's frame surfaces.
    after = step(after, FireTrigger(card_id=CARD_ID, variant="grain3:1"))
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 1 - sp
    assert after.players[sp].farmyard.grid[0][0].grain == 1      # extra + take
    # The other player declines (take + Proceed).
    after = step(after, CommitFieldTake())
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[1 - sp].farmyard.grid[0][0].grain == 2  # take only
