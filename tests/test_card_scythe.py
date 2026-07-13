"""Tests for Scythe (minor improvement, E73; Ephipparius Expansion; Crop Provider).

Card text (verbatim): "During the field phase of each harvest, you can select
exactly one of your fields and harvest all the crops planted in it."

A CHOICE-BEARING TAKE-MODIFIER (user ruling 11, 2026-07-05: all field-phase
harvesting is ONE simultaneous event) — the sibling of Stable Manure and Scythe
Worker. Its extra crops (the chosen field's `count - 1` remaining, on top of the
base take's 1) fold into the mechanical take rather than forming a separate
occasion. The which-field choice surfaces as variants of the take commit itself —
`CommitFieldTake(modifiers=(("scythe", "<group key>"),))` — at the per-player
`PendingFieldPhase` host, which is pushed precisely because the player owns this
card with a legal use. Declining is the bare `CommitFieldTake()`. "Select exactly
one of your fields" = exactly one group choice per harvest, enforced structurally
by the variant shape (a variant names one group; the enumerator offers no
multi-group combination for this card). Only fields with >= 2 of their crop form
groups: a 1-crop field's sole crop already goes to the base take, so "harvest all
the crops" reaps nothing extra there. Cost 1 Wood; no printed VPs, no prereq, not
a passing card.

Card-fields (user rulings 45/46, 2026-07-12): a card-field is one of "your
fields" and per-field harvest modifiers reach it — a card whose take-good is a
crop with >= 2 remaining is its OWN singleton group ("cf_<card_id>"), emptied at
the take-target key ("card", card_id, stack_idx). Wood/stone card-fields never
qualify ("all the CROPS planted in it" — wood/stone are not crops).
"""
import agricola.cards.crop_rotation_field  # noqa: F401  (card-field target)
import agricola.cards.grain_sieve      # noqa: F401  (interaction test)
import agricola.cards.scythe            # noqa: F401  (registration side effects)
import agricola.cards.slurry_spreader   # noqa: F401  (interaction test)
import agricola.cards.stable_manure     # noqa: F401  (interaction test)
import agricola.cards.wood_field        # noqa: F401  (non-crop card-field)
from agricola.actions import CommitFieldTake, FireTrigger, Proceed
from agricola.cards.card_fields import stacks_to_store
from agricola.cards.harvest_windows import (
    HARVEST_WINDOW_CARDS,
    TAKE_MODIFIERS,
    choice_take_modifiers,
)
from agricola.cards.scythe import _fold, _variants
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingFieldPhase
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_sown_fields

CARD_ID = "scythe"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, *card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _own_occupations(state, idx, occ_ids):
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(occ_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_stacks(state, idx, cid, stacks):
    """Write a card-field's per-stack contents (the seam-test idiom)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _with_food(state, idx, food=10):
    p = state.players[idx]
    p = fast_replace(p, resources=fast_replace(p.resources, food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


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
    """The scythe group keys offered as take-commit variants at the current
    field-phase host (the bare take excluded)."""
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
# Registration — spec fields vs the JSON, and the modifier registration shape
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


def test_spec_fields_match_json():
    """cost 1 Wood; vps null -> 0; prerequisites null -> no prereq/max-occ;
    passing_left null -> False."""
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(Resources(wood=1))
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.max_occupations is None
    assert spec.min_occupations == 0
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Hosting — the frame exists exactly when the card gives a live choice
# ---------------------------------------------------------------------------

def test_no_choice_without_card():
    state = with_sown_fields(_field_state(), 0, grain_fields=[(0, 0)])
    assert choice_take_modifiers(state, 0) == []


def test_choice_when_owned_and_eligible():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    mods = choice_take_modifiers(state, 0)
    assert [cid for cid, _ in mods] == [CARD_ID]


def test_no_frame_when_ineligible():
    """Owned but ineligible (only a 1-grain field, which cannot spare a crop
    beyond the base take): no live choice, so the field phase runs the take
    inline (field 1 -> 0, supply +1) with no frame."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    g0 = state.players[0].resources.grain
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD                  # past the field phase
    assert not any(isinstance(f, PendingFieldPhase) for f in after.pending_stack)
    assert after.players[0].resources.grain == g0 + 1          # base take only
    assert after.players[0].farmyard.grid[0][0].grain == 0


def test_frame_pushed_when_eligible():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0


# ---------------------------------------------------------------------------
# Enumeration at the host: take-commit variants, no triggers, no early Proceed
# ---------------------------------------------------------------------------

def test_take_commit_variants_offered():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    acts = legal_actions(state)
    # The bare decline-take plus one variant-carrying take; nothing else — the
    # card is NOT a FireTrigger, and Proceed waits for the take.
    assert CommitFieldTake() in acts
    assert _commit("grain3") in acts
    assert not any(isinstance(a, FireTrigger) for a in acts)
    assert Proceed() not in acts


def test_one_variant_per_group_not_a_count_vector():
    """Two 3-grain fields, one 2-veg field: ONE variant per (crop, remaining)
    group — "select exactly one field" is a single group choice, never a
    multi-field count vector (contrast Stable Manure)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = with_grid(state, 0, {(1, 1): Cell(cell_type=CellType.FIELD, veg=2)})
    state = _walk_to_field_frame(state)
    assert _take_variants_offered(state) == ["grain3", "veg2"]


def test_fields_group_by_crops_remaining():
    """A 3-grain and a 2-grain field are DISTINCT groups (different remaining) —
    emptying one yields a different amount than the other."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD, grain=2)})
    state = _walk_to_field_frame(state)
    assert _take_variants_offered(state) == ["grain2", "grain3"]


# ---------------------------------------------------------------------------
# Outcomes — the chosen field is emptied within the ONE take event (ruling 11)
# ---------------------------------------------------------------------------

def test_scythe_empties_the_chosen_field_in_one_event():
    """A 3-grain field: base 1 + scythe's remaining 2 = 3 taken, field 3 -> 0,
    ONE take occasion carrying the full amount with emptied=True (what Slurry
    Spreader reads)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3"))
    assert state.players[0].resources.grain == g0 + 3
    assert state.players[0].farmyard.grid[0][0].grain == 0
    top = state.pending_stack[-1]
    assert [o.source for o in top.occasions] == ["take"]
    (entry,) = top.occasions[0].entries
    assert entry.source == "cell:0,0" and entry.amount == 3 and entry.emptied


def test_scythe_on_a_two_count_field():
    """A 2-grain field: base 1 + remaining 1 = 2, field -> 0, entry amount 2,
    emptied (same net result the base take alone would reach on a 1-count field,
    but here reached in one event that harvested TWO)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain2"))
    assert state.players[0].resources.grain == g0 + 2
    assert state.players[0].farmyard.grid[0][0].grain == 0
    (entry,) = state.pending_stack[-1].occasions[0].entries
    assert entry.amount == 2 and entry.emptied


def test_scythe_applies_to_veg():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(1, 1): Cell(cell_type=CellType.FIELD, veg=3)})
    state = _walk_to_field_frame(state)
    v0 = state.players[0].resources.veg
    state = step(state, _commit("veg3"))
    assert state.players[0].resources.veg == v0 + 3
    assert state.players[0].farmyard.grid[1][1].veg == 0
    (entry,) = state.pending_stack[-1].occasions[0].entries
    assert entry.crop == "veg" and entry.amount == 3 and entry.emptied


def test_only_the_chosen_field_is_emptied():
    """"Exactly one field": two 3-grain fields but the chosen group empties only
    the FIRST in scan order; the second keeps its base-take-only 3 -> 2."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3"))
    # base 1 on each field (2) + scythe's remaining 2 on the first (2) = +4.
    assert state.players[0].resources.grain == g0 + 4
    grid = state.players[0].farmyard.grid
    assert grid[0][0].grain == 0    # scythe-emptied
    assert grid[0][1].grain == 2    # base take only


def test_decline_via_bare_take():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, CommitFieldTake())
    assert state.players[0].resources.grain == g0 + 1   # base take only
    assert state.players[0].farmyard.grid[0][0].grain == 2
    # The take consumed the window's decision: only Proceed remains — the
    # unchosen modifier is implicitly declined (the one-way gate).
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED


def test_no_second_chance_after_the_take():
    """Once the take fired (with or without the modifier), no further use of the
    card exists this harvest — the event it modifies has happened."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    state = step(state, _commit("grain3"))
    acts = legal_actions(state)
    assert acts == [Proceed()]
    assert not any(isinstance(a, CommitFieldTake) for a in acts)


# ---------------------------------------------------------------------------
# NOT firing elsewhere — a real harvest, not feeding/breeding; harvest-scoped
# ---------------------------------------------------------------------------

def test_not_offered_during_feeding_or_breeding():
    """After the field phase resolves, no scythe variant/frame survives into the
    feeding phase — the modifier lives only in the field phase."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    state = step(state, CommitFieldTake())      # decline
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED
    assert not any(isinstance(f, PendingFieldPhase) for f in state.pending_stack)
    assert not any(
        isinstance(a, CommitFieldTake) for a in legal_actions(state))


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_one_count_field_forms_no_group():
    """A field holding exactly 1 of its crop can spare nothing beyond the base
    take — "harvest all the crops" reaps only that 1, identical to the base
    take — so it forms no donor group and is not a meaningful selection."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    assert _variants(state, 0) == []
    assert choice_take_modifiers(state, 0) == []


def test_no_fields_no_variants():
    state = _own_minor(_field_state(), 0, CARD_ID)
    assert _variants(state, 0) == []


def test_fold_maps_group_to_first_field():
    """The fold empties the FIRST field of the chosen group in scan order,
    contributing count-1 extra there (base take reaps the other 1)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    assert _fold(state, 0, "grain3", {}) == {(0, 0): 2}


# ---------------------------------------------------------------------------
# Owner-gating and the per-player FIELD band
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Both players have an eligible field, but only P0 owns the card.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    after = step(after, _commit("grain3"))
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    # Owner: scythe empties the field (3 -> 0). Non-owner: base take only (3 -> 2).
    assert after.players[0].farmyard.grid[0][0].grain == 0
    assert after.players[1].farmyard.grid[0][0].grain == 2


def test_owner_in_seat_one():
    state = _own_minor(_field_state(), 1, CARD_ID)
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    assert after.pending_stack[-1].player_idx == 1
    g1 = after.players[1].resources.grain
    after = step(after, _commit("grain3"))
    assert after.players[1].resources.grain == g1 + 3
    assert after.players[1].farmyard.grid[0][0].grain == 0


def test_both_owners_starting_player_resolves_first():
    """The FIELD segment is per-player (user ruling 3): the starting player's
    whole field phase — frame and take — completes before the other player's
    begins, so only one PendingFieldPhase is ever out at a time."""
    state = _field_state()
    sp = state.starting_player
    for i in (0, 1):
        state = _own_minor(state, i, CARD_ID)
        state = with_sown_fields(state, i, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    frames = [f.player_idx for f in after.pending_stack
              if isinstance(f, PendingFieldPhase)]
    assert frames == [sp]
    assert after.players[1 - sp].farmyard.grid[0][0].grain == 3  # untaken
    after = step(after, _commit("grain3"))                       # SP empties the field
    after = step(after, Proceed())
    top = after.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 1 - sp
    assert after.players[sp].farmyard.grid[0][0].grain == 0      # scythe-emptied
    after = step(after, CommitFieldTake())                       # other declines
    after = step(after, Proceed())
    after = _advance_until_decision(after)
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[1 - sp].farmyard.grid[0][0].grain == 2  # take only


# ---------------------------------------------------------------------------
# Not a real harvest — harvest-event scope (ruling 12) via the frame test above
# is the positive; here the modifier stays silent when the card isn't owned.
# ---------------------------------------------------------------------------

def test_bare_take_when_unowned_even_with_eligible_fields():
    """No owner: the field phase runs inline with no frame — a 3-grain field is
    reduced only by the base take."""
    state = with_sown_fields(_field_state(), 0, grain_fields=[(0, 0)])
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD
    assert after.players[0].farmyard.grid[0][0].grain == 2


# ---------------------------------------------------------------------------
# Interaction with take-occasion consumers (ruling 11: extras fold into the take)
# ---------------------------------------------------------------------------

def test_grain_sieve_counts_scythes_folded_in_grain():
    """Grain Sieve fires "if you harvest at least 2 grain" summing the take
    occasion's grain UNITS. A single 3-grain field harvests only 1 grain under
    the bare take (below threshold), but Scythe folds the field's other 2 grain
    into the SAME take (amount 3) — so the threshold is met and Grain Sieve pays
    its +1 grain from supply (ruling 11: it counts the folded-in extras)."""
    state = _own_minor(_field_state(), 0, CARD_ID, "grain_sieve")
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    # Sanity: without Scythe this lone field would harvest only 1 grain (< 2),
    # so any surplus above +3 is Grain Sieve reacting to the folded-in extra.
    state = step(state, _commit("grain3"))
    # base 1 + scythe 2 = 3 taken, PLUS Grain Sieve's +1 = +4.
    assert state.players[0].resources.grain == g0 + 4


def test_grain_sieve_silent_when_scythe_declined():
    """Declining Scythe leaves a lone 3-grain field harvesting only 1 grain —
    below Grain Sieve's threshold — so no supply grain is added."""
    state = _own_minor(_field_state(), 0, CARD_ID, "grain_sieve")
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, CommitFieldTake())      # decline scythe
    assert state.players[0].resources.grain == g0 + 1   # base take only, no sieve


def test_slurry_spreader_pays_once_on_the_scythe_emptied_field():
    """Slurry Spreader pays "each time you take the last grain from a field" —
    per FIELD-emptying, NOT per unit. Scythe empties a 3-grain field in the one
    take (amount 3, emptied), so Slurry Spreader pays +2 food ONCE, not +6."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _own_occupations(state, 0, ["slurry_spreader"])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    f0 = state.players[0].resources.food
    state = step(state, _commit("grain3"))
    assert state.players[0].farmyard.grid[0][0].grain == 0
    assert state.players[0].resources.food == f0 + 2    # one last-grain-taking


def test_slurry_spreader_silent_when_field_not_emptied():
    """A base take on a 3-grain field (Scythe declined) leaves 2 grain — the
    field is NOT emptied, so Slurry Spreader pays nothing."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = _own_occupations(state, 0, ["slurry_spreader"])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    f0 = state.players[0].resources.food
    state = step(state, CommitFieldTake())      # decline scythe
    assert state.players[0].resources.food == f0   # field not emptied


# ---------------------------------------------------------------------------
# Interaction with Stable Manure — both choice-bearing modifiers on one commit
# ---------------------------------------------------------------------------

def test_scythe_and_stable_manure_offered_as_combinations():
    """Owning both choice-bearing modifiers, the enumerator offers the CROSS
    PRODUCT of their uses on one CommitFieldTake — each modifier declinable, or
    combined."""
    state = _own_minor(_field_state(), 0, CARD_ID, "stable_manure")
    # One unfenced stable -> stable_manure cap 1; distinct crop groups so the two
    # modifiers pick DIFFERENT fields and their extras never collide.
    state = with_grid(state, 0, {
        (2, 4): Cell(cell_type=CellType.STABLE),
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=3),
    })
    state = _walk_to_field_frame(state)
    combos = {a.modifiers for a in legal_actions(state)
              if isinstance(a, CommitFieldTake)}
    assert () in combos                                        # decline both
    assert ((CARD_ID, "grain3"),) in combos                   # scythe only
    assert (("stable_manure", "veg3:1"),) in combos           # stable only
    # Both together (order as the enumerator emits: stable_manure then scythe).
    assert (("stable_manure", "veg3:1"), (CARD_ID, "grain3")) in combos


def test_scythe_and_stable_manure_both_fold_into_one_take():
    """Both modifiers on one commit, targeting DISTINCT fields: Scythe empties
    the grain field (amount 3, emptied), Stable Manure adds +1 to the veg field
    (amount 2, not emptied) — all in the SAME take occasion. The merged extras
    do not over-harvest (the engine would assert otherwise)."""
    state = _own_minor(_field_state(), 0, CARD_ID, "stable_manure")
    state = with_grid(state, 0, {
        (2, 4): Cell(cell_type=CellType.STABLE),
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=3),
    })
    state = _walk_to_field_frame(state)
    g0, v0 = state.players[0].resources.grain, state.players[0].resources.veg
    combo = CommitFieldTake(
        modifiers=(("stable_manure", "veg3:1"), (CARD_ID, "grain3")))
    state = step(state, combo)
    assert state.players[0].resources.grain == g0 + 3   # base 1 + scythe 2
    assert state.players[0].resources.veg == v0 + 2     # base 1 + stable 1
    grid = state.players[0].farmyard.grid
    assert grid[0][0].grain == 0                        # scythe-emptied
    assert grid[0][1].veg == 1                          # 3 - (base 1 + stable 1)
    # ONE take occasion carrying both fields' entries.
    (occasion,) = state.pending_stack[-1].occasions
    assert occasion.source == "take"
    entries = {(e.crop, e.amount, e.emptied) for e in occasion.entries}
    assert entries == {("grain", 3, True), ("veg", 2, False)}


# ---------------------------------------------------------------------------
# Claim-aware allocation (the over-harvest collision fix)
# ---------------------------------------------------------------------------

def test_same_group_combo_on_one_field_is_feasible_and_exact():
    """Scythe + Stable Manure both targeting the ONLY grain3 field: the rigid
    Stable Manure claim (+1) allocates first, Scythe then empties the remaining
    spare — one event, total exactly 3, no over-harvest."""
    state = _own_minor(_field_state(), 0, "scythe", "stable_manure")
    state = with_grid(state, 0, {(0, 4): Cell(cell_type=CellType.STABLE)})
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])   # one grain3 field
    state = _walk_to_field_frame(state)
    combo = next(a for a in legal_actions(state)
                 if isinstance(a, CommitFieldTake) and len(a.modifiers) == 2)
    g0 = state.players[0].resources.grain
    state = step(state, combo)
    assert state.players[0].resources.grain == g0 + 3
    assert state.players[0].farmyard.grid[0][0].grain == 0


def test_same_group_combo_prefers_distinct_fields():
    """With TWO grain3 fields, the combined commit routes Stable Manure and
    Scythe to different fields: Scythe empties an unclaimed one (max spare),
    Stable Manure's +1 rides the other — total base 2 + 1 + 2 = 5."""
    state = _own_minor(_field_state(), 0, "scythe", "stable_manure")
    state = with_grid(state, 0, {(0, 4): Cell(cell_type=CellType.STABLE)})
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    combo = next(a for a in legal_actions(state)
                 if isinstance(a, CommitFieldTake)
                 and len(a.modifiers) == 2
                 and ("stable_manure", "grain3:1") in a.modifiers)
    g0 = state.players[0].resources.grain
    state = step(state, combo)
    assert state.players[0].resources.grain == g0 + 5
    grid = state.players[0].farmyard.grid
    assert sorted((grid[0][0].grain, grid[0][1].grain)) == [0, 1]


# ---------------------------------------------------------------------------
# Card-fields — a card-field is one of "your fields" (rulings 45/46, 2026-07-12)
# ---------------------------------------------------------------------------

def test_card_field_variant_offered_and_empties_the_card():
    """A crop_rotation_field holding 3 grain — and NO grid fields — is a
    Scythe target on its own (the boundary the grid-only code failed): the
    frame is hosted, the "cf_crop_rotation_field" variant is offered, and
    committing it empties the card in the one event — +3 grain (base 1 +
    scythe 2), a "card:" manifest entry of amount 3 with emptied=True, and
    the CardStore entry REMOVED (a harvested-out card-field stores nothing)."""
    state = _own_minor(_field_state(), 0, CARD_ID, "crop_rotation_field")
    state = _set_stacks(state, 0, "crop_rotation_field", [(3, 0, 0, 0)])
    state = _walk_to_field_frame(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    assert _take_variants_offered(state) == ["cf_crop_rotation_field"]
    g0 = state.players[0].resources.grain
    state = step(state, _commit("cf_crop_rotation_field"))
    assert state.players[0].resources.grain == g0 + 3
    assert state.players[0].card_state.get("crop_rotation_field") is None
    (occasion,) = state.pending_stack[-1].occasions
    assert occasion.source == "take"
    (entry,) = occasion.entries
    assert entry.source == "card:crop_rotation_field"
    assert (entry.crop, entry.amount, entry.emptied) == ("grain", 3, True)


def test_card_and_grid_groups_are_distinct_variants():
    """A 3-grain card-field and a 3-grain grid field are DIFFERENT groups —
    a card is never interchangeable with a same-count grid field (harvesting
    it moves card state and fires card-level readers), so both variants are
    offered side by side."""
    state = _own_minor(_field_state(), 0, CARD_ID, "crop_rotation_field")
    state = _set_stacks(state, 0, "crop_rotation_field", [(3, 0, 0, 0)])
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    assert _take_variants_offered(state) == ["cf_crop_rotation_field", "grain3"]


def test_wood_field_never_a_scythe_target():
    """Wood/stone card-fields never qualify: the card harvests "all the CROPS
    planted in it", and wood is not a crop — a wood-planted Wood Field forms
    no group even with >= 2 wood per stack, so the field phase runs inline."""
    state = _own_minor(_field_state(), 0, CARD_ID, "wood_field")
    state = _set_stacks(state, 0, "wood_field", [(0, 0, 3, 0), (0, 0, 3, 0)])
    assert _variants(state, 0) == []
    assert choice_take_modifiers(state, 0) == []
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD
    assert not any(isinstance(f, PendingFieldPhase) for f in after.pending_stack)


def test_one_crop_card_field_forms_no_group():
    """The grid floor, mirrored: a card-field holding exactly 1 of its crop
    can spare nothing beyond the base take, so it forms no group."""
    state = _own_minor(_field_state(), 0, CARD_ID, "crop_rotation_field")
    state = _set_stacks(state, 0, "crop_rotation_field", [(1, 0, 0, 0)])
    assert _variants(state, 0) == []
    assert choice_take_modifiers(state, 0) == []


def test_fold_card_group_respects_claims_and_is_rigid():
    """The card group's fold takes the stack's remaining spare (count − 1 −
    claimed) at the take-target key, and is RIGID: fully-claimed leaves
    nothing to empty and returns None (the combination is dropped — contrast
    the grid groups' flexible 0-extra fold)."""
    state = _own_minor(_field_state(), 0, CARD_ID, "crop_rotation_field")
    state = _set_stacks(state, 0, "crop_rotation_field", [(3, 0, 0, 0)])
    key = ("card", "crop_rotation_field", 0)
    assert _fold(state, 0, "cf_crop_rotation_field", {}) == {key: 2}
    assert _fold(state, 0, "cf_crop_rotation_field", {key: 1}) == {key: 1}
    assert _fold(state, 0, "cf_crop_rotation_field", {key: 2}) is None


def test_card_group_composes_with_stable_manure_claims():
    """Scythe + Stable Manure both targeting the ONLY donor — a 3-grain
    crop_rotation_field: Stable Manure's rigid +1 claims first, Scythe then
    empties the remaining spare — one event, total exactly 3, card emptied,
    no over-harvest."""
    state = _own_minor(
        _field_state(), 0, CARD_ID, "stable_manure", "crop_rotation_field")
    state = with_grid(state, 0, {(2, 4): Cell(cell_type=CellType.STABLE)})
    state = _set_stacks(state, 0, "crop_rotation_field", [(3, 0, 0, 0)])
    state = _walk_to_field_frame(state)
    combo = CommitFieldTake(modifiers=(
        ("stable_manure", "cf_crop_rotation_field:1"),
        (CARD_ID, "cf_crop_rotation_field")))
    assert combo in legal_actions(state)
    g0 = state.players[0].resources.grain
    state = step(state, combo)
    assert state.players[0].resources.grain == g0 + 3
    assert state.players[0].card_state.get("crop_rotation_field") is None
    (entry,) = state.pending_stack[-1].occasions[0].entries
    assert (entry.crop, entry.amount, entry.emptied) == ("grain", 3, True)


def test_fully_claimed_card_group_combo_is_dropped():
    """A 2-grain card: Stable Manure's +1 leaves Scythe nothing to empty, so
    the COMBINED commit is infeasible (the rigid card group returns None) and
    never offered — each modifier alone still is, and either alone already
    empties the card, so nothing is lost."""
    state = _own_minor(
        _field_state(), 0, CARD_ID, "stable_manure", "crop_rotation_field")
    state = with_grid(state, 0, {(2, 4): Cell(cell_type=CellType.STABLE)})
    state = _set_stacks(state, 0, "crop_rotation_field", [(2, 0, 0, 0)])
    state = _walk_to_field_frame(state)
    combos = {a.modifiers for a in legal_actions(state)
              if isinstance(a, CommitFieldTake)}
    assert ((CARD_ID, "cf_crop_rotation_field"),) in combos
    assert (("stable_manure", "cf_crop_rotation_field:1"),) in combos
    assert (("stable_manure", "cf_crop_rotation_field:1"),
            (CARD_ID, "cf_crop_rotation_field")) not in combos


def test_action_labels():
    """The web-UI labeler (display.register_action_labeler): the group's full
    yield for a grid group, the title-cased card name for a "cf_" group."""
    from agricola.cards.display import variant_label

    assert variant_label(CARD_ID, "grain3") == "empty a 3-grain field (+3 grain)"
    assert (variant_label(CARD_ID, "cf_crop_rotation_field")
            == "empty Crop Rotation Field")
