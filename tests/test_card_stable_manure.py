"""Tests for Stable Manure (minor improvement, D72; Dulcinaria Expansion;
Crop Provider).

Card text: "In the field phase of each harvest, you can harvest 1 additional good
from a number of fields equal to the number of unfenced stables you have."

A CHOICE-BEARING TAKE-MODIFIER (user ruling 11, 2026-07-05: all field-phase
harvesting is ONE simultaneous event): its extras fold into the mechanical take
rather than forming a separate occasion. The which-fields choice surfaces as
variants of the take commit itself — `CommitFieldTake(modifiers=(("stable_manure",
"<count vector>"),))` — at the per-player `PendingFieldPhase` host, which is
pushed precisely because the player owns this card with a legal use. Declining is
the bare `CommitFieldTake()`. A benefited field is depleted by 2 in the one event
(1 base + 1 extra), so only fields with >= 2 of their crop are donors; the take
occasion's manifest entry carries the combined amount and the NET emptied flag.
Prereq "At Most 1 Occupation" → max_occupations=1.
"""
from agricola.actions import CommitFieldTake, FireTrigger, Proceed
from agricola.cards.harvest_windows import (
    HARVEST_WINDOW_CARDS,
    TAKE_MODIFIERS,
    choice_take_modifiers,
)
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.stable_manure import _fold, _variants
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingFieldPhase
from agricola.replace import fast_replace
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
    the player has no field-phase decision — the take runs inline)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingFieldPhase):
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _take_variants_offered(state):
    """The stable_manure count vectors offered as take-commit variants at the
    current field-phase host (the bare take excluded)."""
    out = []
    for a in legal_actions(state):
        if isinstance(a, CommitFieldTake):
            for cid, variant in a.modifiers:
                if cid == CARD_ID:
                    out.append(variant)
    return sorted(out)


def _commit(variant):
    return CommitFieldTake(modifiers=((CARD_ID, variant),))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_and_take_modifier():
    assert CARD_ID in MINORS
    # A choice-bearing take-modifier (ruling 11) — NOT a trigger of any kind.
    entry = next(e for e in TAKE_MODIFIERS if e.card_id == CARD_ID)
    assert entry.variants_fn is not None
    assert CARD_ID not in CARDS
    assert CARD_ID not in PLAY_VARIANT_TRIGGERS
    # Window-membership index (census/hosting documentation).
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("field_phase", set())
    spec = MINORS[CARD_ID]
    # Free, no printed VPs, no custom prereq predicate, not a passing card.
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.passing_left is False


def test_prereq_at_most_one_occupation():
    spec = MINORS[CARD_ID]
    assert spec.max_occupations == 1
    state = setup(0)
    assert prereq_met(spec, _own_occupations(state, 0, []), 0) is True
    assert prereq_met(spec, _own_occupations(state, 0, ["consultant"]), 0) is True
    assert prereq_met(
        spec, _own_occupations(state, 0, ["consultant", "priest"]), 0
    ) is False


# ---------------------------------------------------------------------------
# Hosting — the frame exists exactly when the card gives a live choice
# ---------------------------------------------------------------------------

def test_no_choice_without_card():
    state = with_sown_fields(_field_state(), 0, grain_fields=[(0, 0)])
    assert choice_take_modifiers(state, 0) == []


def test_choice_when_owned_and_eligible():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    mods = choice_take_modifiers(state, 0)
    assert [cid for cid, _ in mods] == [CARD_ID]


def test_no_frame_when_ineligible():
    """Owned but ineligible (no stable): no live choice, so the field phase runs
    the take inline (field 3 -> 2, supply +1) with no frame."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])   # field, but cap 0
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD                  # past the field phase
    assert not any(isinstance(f, PendingFieldPhase) for f in after.pending_stack)
    assert after.players[0].resources.grain == g0 + 1          # base take only
    assert after.players[0].farmyard.grid[0][0].grain == 2


def test_frame_pushed_when_eligible():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0


# ---------------------------------------------------------------------------
# Enumeration at the host: take-commit variants, no triggers, no early Proceed
# ---------------------------------------------------------------------------

def test_take_commit_variants_offered():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    acts = legal_actions(state)
    # The bare decline-take plus one variant-carrying take; nothing else — the
    # card is NOT a FireTrigger, and Proceed waits for the take.
    assert CommitFieldTake() in acts
    assert _commit("grain3:1") in acts
    assert not any(isinstance(a, FireTrigger) for a in acts)
    assert Proceed() not in acts


def test_variant_enumeration_groups_and_cap():
    """Two 3-grain fields + one 2-veg field, cap 2: every count vector over the
    (crop, remaining) groups with 1 <= total <= 2."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])           # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = with_grid(state, 0, {(1, 1): Cell(cell_type=CellType.FIELD, veg=2)})
    state = _walk_to_field_frame(state)
    assert _take_variants_offered(state) == sorted([
        "grain3:1", "grain3:2", "veg2:1", "grain3:1|veg2:1",
    ])


def test_variant_cap_one_restricts_totals():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])                   # cap 1
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    assert _take_variants_offered(state) == ["grain3:1"]


def test_fields_group_by_crops_remaining():
    """A 3-grain and a 2-grain field are DISTINCT groups (different remaining)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD, grain=2)})
    state = _walk_to_field_frame(state)
    assert _take_variants_offered(state) == ["grain2:1", "grain3:1"]


# ---------------------------------------------------------------------------
# Outcomes — the extras fold into the ONE take event (ruling 11)
# ---------------------------------------------------------------------------

def test_extra_plus_take_deplete_field_by_two_in_one_event():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3:1"))
    # One event: 1 base + 1 extra -> supply +2, field 3 -> 1.
    assert state.players[0].resources.grain == g0 + 2
    assert state.players[0].farmyard.grid[0][0].grain == 1
    # ONE take occasion carrying the combined amount; no separate card occasion.
    top = state.pending_stack[-1]
    assert [o.source for o in top.occasions] == ["take"]
    (entry,) = top.occasions[0].entries
    assert entry.source == "cell:0,0" and entry.amount == 2 and not entry.emptied


def test_extra_empties_a_two_count_field_net():
    """A 2-grain donor: base + extra take BOTH crops -> the one entry is
    amount 2, emptied True (the net result — what Slurry Spreader reads)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    state = _walk_to_field_frame(state)
    state = step(state, _commit("grain2:1"))
    assert state.players[0].farmyard.grid[0][0].grain == 0
    (entry,) = state.pending_stack[-1].occasions[0].entries
    assert entry.amount == 2 and entry.emptied


def test_extra_applies_to_veg_too():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_grid(state, 0, {(1, 1): Cell(cell_type=CellType.FIELD, veg=2)})
    state = _walk_to_field_frame(state)
    v0 = state.players[0].resources.veg
    state = step(state, _commit("veg2:1"))
    assert state.players[0].resources.veg == v0 + 2
    assert state.players[0].farmyard.grid[1][1].veg == 0


def test_mixed_crop_vector():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])           # cap 2
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_grid(state, 0, {(1, 1): Cell(cell_type=CellType.FIELD, veg=2)})
    state = _walk_to_field_frame(state)
    g0, v0 = state.players[0].resources.grain, state.players[0].resources.veg
    state = step(state, _commit("grain3:1|veg2:1"))
    assert state.players[0].resources.grain == g0 + 2
    assert state.players[0].resources.veg == v0 + 2
    assert state.players[0].farmyard.grid[0][0].grain == 1
    assert state.players[0].farmyard.grid[1][1].veg == 0


def test_partial_use_is_a_real_option():
    """Cap 2 with two donors: using only 1 is offered and takes only 1 extra."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3:1"))
    assert state.players[0].resources.grain == g0 + 3   # 2 base + 1 extra
    grid = state.players[0].farmyard.grid
    assert sorted((grid[0][0].grain, grid[0][1].grain)) == [1, 2]


def test_decline_via_bare_take():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, CommitFieldTake())
    assert state.players[0].resources.grain == g0 + 1   # base take only
    assert state.players[0].farmyard.grid[0][0].grain == 2
    # The take consumed the window's decision: only Proceed remains — the
    # unchosen modifier is implicitly declined (the §4b one-way gate).
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED


def test_no_second_chance_after_the_take():
    """Once the take fired (with or without the modifier), no further use of the
    card exists this harvest — the event it modifies has happened."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    state = step(state, _commit("grain3:1"))
    acts = legal_actions(state)
    assert acts == [Proceed()]
    assert not any(isinstance(a, CommitFieldTake) for a in acts)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_one_count_field_cannot_donate():
    """A field holding exactly 1 of its crop can spare nothing beyond the base
    take — it forms no donor group."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    assert _variants(state, 0) == []
    assert choice_take_modifiers(state, 0) == []


def test_cap_exceeds_eligible_fields():
    """Cap 3 but only one donor: totals are bounded by the donor count."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4), (1, 4), (2, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert _variants(state, 0) == ["grain3:1"]


def test_no_stable_no_variants():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert _variants(state, 0) == []


def test_unfenced_stable_counts_toward_cap():
    """count_unfenced_stables drives the cap: a bare stable on an open grid is
    unfenced, so it counts (cap 1) — the boundary the card's N is read from."""
    from agricola.cards.stable_architect import count_unfenced_stables
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    assert count_unfenced_stables(state.players[0].farmyard) == 1


def test_fold_maps_vector_to_cells():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _with_stables(state, 0, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert _fold(state, 0, "grain3:1", {}) == {(0, 0): 1}


# ---------------------------------------------------------------------------
# Owner-gating and the per-player FIELD band
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Both players have a stable and an eligible field, but only P0 owns the card.
    state = _with_stables(state, 0, [(0, 4)])
    state = _with_stables(state, 1, [(0, 4)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    after = step(after, _commit("grain3:1"))
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    # Owner: extra + take -> supply +2, field 3 -> 1. Non-owner: take only.
    assert after.players[0].resources.grain == 2
    assert after.players[0].farmyard.grid[0][0].grain == 1
    assert after.players[1].farmyard.grid[0][0].grain == 2


def test_owner_in_seat_one():
    state = _own_minor(_field_state(), 1, CARD_ID)
    state = _with_stables(state, 1, [(0, 4), (1, 4)])            # cap 2
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    after = _walk_to_field_frame(state)
    assert after.pending_stack[-1].player_idx == 1
    g1, v1 = after.players[1].resources.grain, after.players[1].resources.veg
    after = step(after, _commit("grain3:1|veg2:1"))
    assert after.players[1].resources.grain == g1 + 2
    assert after.players[1].resources.veg == v1 + 2


def test_both_owners_starting_player_resolves_first():
    """The FIELD segment is per-player (user ruling 3): the starting player's
    whole field phase — frame and take — completes before the other player's
    begins, so only one PendingFieldPhase is ever out at a time."""
    state = _field_state()
    sp = state.starting_player
    for i in (0, 1):
        state = _own_minor(state, i, CARD_ID)
        state = _with_stables(state, i, [(0, 4)])
        state = with_sown_fields(state, i, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    frames = [f.player_idx for f in after.pending_stack
              if isinstance(f, PendingFieldPhase)]
    assert frames == [sp]
    assert after.players[1 - sp].farmyard.grid[0][0].grain == 3  # untaken
    after = step(after, _commit("grain3:1"))                     # SP folds the extra in
    after = step(after, Proceed())
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 1 - sp
    assert after.players[sp].farmyard.grid[0][0].grain == 1      # extra + take
    after = step(after, CommitFieldTake())                       # other declines
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[1 - sp].farmyard.grid[0][0].grain == 2  # take only


# ---------------------------------------------------------------------------
# Claim-aware allocation (the over-harvest collision fix)
# ---------------------------------------------------------------------------

def test_scythe_worker_collision_on_a_two_count_field():
    """Scythe Worker's auto (+1 per >=2-grain field) and Stable Manure's chosen
    extra both want a lone 2-grain field's single spare unit. The rigid chosen
    modifier allocates first; the auto degrades gracefully (nothing additional
    remains) — the take is base 1 + 1 extra, never an over-harvest crash."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {"scythe_worker"})
        if i == 0 else state.players[i] for i in range(2)))
    state = _with_stables(state, 0, [(0, 4)])
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain2:1"))
    assert state.players[0].resources.grain == g0 + 2      # base + SM's 1 (SW: none)
    assert state.players[0].farmyard.grid[0][0].grain == 0
