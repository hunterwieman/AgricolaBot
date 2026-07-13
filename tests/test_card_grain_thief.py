"""Tests for Grain Thief (occupation, E112; Ephipparius Expansion; Crop
Provider).

Card text (verbatim): "Each time you would harvest a grain field, you can leave
the grain on the field and take 1 grain from the general supply instead."

A REPLACE-kind CHOICE-BEARING TAKE-MODIFIER: registered at ``order=0`` (folds
first — later folds see the replaced cells pre-claimed at full count) with
``harvest_scoped=False`` (user ruling 12, 2026-07-04, the harvest-verb lexicon:
unscoped harvest-verb wording applies wherever the field-phase effect runs — a
real harvest's take AND Bumper Crop's card-played field phase). The per-field
choice surfaces as ``CommitFieldTake(modifiers=(("grain_thief", "<count
vector>"),))`` variants at the ``PendingFieldPhase`` host, and at Bumper Crop as
a ``PendingCardChoice`` over the feasible combinations.

Per the user ruling of 2026-07-06 (proposed 2026-07-05)
a replaced field is NOT harvested: it emits no manifest entry (invisible to
Grain Sieve), can donate nothing to Scythe Worker, and the replacement's 1
supply grain is likewise never in the manifest.
"""
import json
from pathlib import Path

import agricola.cards.bumper_crop    # noqa: F401  (interaction test)
import agricola.cards.grain_sieve    # noqa: F401  (interaction test)
import agricola.cards.grain_thief    # noqa: F401  (register the card)
import agricola.cards.scythe_worker  # noqa: F401  (interaction test)

from agricola.actions import (
    CommitCardChoice,
    CommitFieldTake,
    CommitPlayMinor,
    FireTrigger,
    Proceed,
)
from agricola.cards.grain_thief import _fold, _variants
from agricola.cards.harvest_windows import (
    HARVEST_WINDOW_CARDS,
    TAKE_MODIFIERS,
    TakeFold,
    choice_take_modifiers,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice, PendingFieldPhase, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_sown_fields

CARD_ID = "grain_thief"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, *card_ids):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _own_minor(state, idx, *card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
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
    """The grain_thief count vectors offered as take-commit variants at the
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
# Registration — the JSON row, the spec, and the modifier registration shape
# ---------------------------------------------------------------------------

def test_registered_as_occupation_and_replace_kind_take_modifier():
    assert CARD_ID in OCCUPATIONS
    # A choice-bearing take-modifier — NOT a trigger of any kind.
    entry = next(e for e in TAKE_MODIFIERS if e.card_id == CARD_ID)
    assert entry.variants_fn is not None
    assert entry.order == 0                    # replace-kind: folds FIRST
    assert entry.harvest_scoped is False       # ruling 12: unscoped wording
    assert CARD_ID not in CARDS
    assert CARD_ID not in PLAY_VARIANT_TRIGGERS
    # Window-membership index (census/hosting documentation).
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("field_phase", set())
    # Order 0 sorts ahead of the rigid/flexible modifiers (load-bearing:
    # later folds must see the replaced cells pre-claimed).
    ids = [e.card_id for e in TAKE_MODIFIERS]
    assert ids.index(CARD_ID) < ids.index("scythe_worker")


def test_on_play_is_a_noop():
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state


def test_json_row_and_verbatim_docstring():
    data = json.loads(
        (Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
         / "revised_occupations.json").read_text())
    rows = data if isinstance(data, list) else data["cards"]
    row = next(r for r in rows if r["name"] == "Grain Thief")
    assert row["type"] == "Occupation"
    assert row["deck"] == "E" and row["number"] == 112
    assert row["players"] == "1+"
    import agricola.cards.grain_thief as mod
    # The docstring quotes the text verbatim (modulo line wrapping).
    assert row["text"] in " ".join(mod.__doc__.split())


# ---------------------------------------------------------------------------
# Variant enumeration — per-field choice, grouped by remaining grain count
# ---------------------------------------------------------------------------

def test_variants_group_by_remaining_grain_count():
    """Two 3-grain fields + one 1-grain field: every count vector over the
    (remaining-count) groups with >= 1 replacement."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD, grain=1)})
    assert sorted(_variants(state, 0)) == sorted([
        "grain1:1", "grain3:1", "grain3:2",
        "grain1:1|grain3:1", "grain1:1|grain3:2",
    ])


def test_one_grain_field_is_replaceable():
    """Unlike Stable Manure's >= 2 donor floor, a 1-grain field IS a valid
    replacement target — its single grain is what gets left behind."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    assert _variants(state, 0) == ["grain1:1"]


def test_veg_fields_are_not_grain_fields():
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, veg_fields=[(1, 1)])
    assert _variants(state, 0) == []
    # Mixed: only the grain field forms a group.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert _variants(state, 0) == ["grain3:1"]


def test_no_planted_grain_field_no_choice():
    state = _own_occ(_field_state(), 0, CARD_ID)
    assert _variants(state, 0) == []
    assert choice_take_modifiers(state, 0) == []
    # An empty (harvested-out) field is not a grain field either.
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})
    assert _variants(state, 0) == []


# ---------------------------------------------------------------------------
# The fold — cells, bonus, claim-awareness, infeasibility
# ---------------------------------------------------------------------------

def test_fold_maps_vector_to_skips_and_bonus():
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    fold = _fold(state, 0, "grain3:2", {})
    assert isinstance(fold, TakeFold)
    assert fold.skipped == frozenset({(0, 0), (0, 1)})
    assert fold.bonus == Resources(grain=2)    # 1 per replaced field
    assert fold.extras == {}


def test_fold_skips_claimed_cells_and_fails_unmeetable():
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    # The only grain3 field already claimed: the demand cannot be met.
    assert _fold(state, 0, "grain3:1", {(0, 0): 1}) is None
    # With a second grain3 field, the fold redirects to the unclaimed one.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    fold = _fold(state, 0, "grain3:1", {(0, 0): 1})
    assert fold.skipped == frozenset({(0, 1)})
    assert fold.bonus == Resources(grain=1)


# ---------------------------------------------------------------------------
# The real harvest walk — hosting, replacement, decline
# ---------------------------------------------------------------------------

def test_frame_hosts_when_usable():
    """Owning the card with a planted grain field is a live take-choice, so the
    FIELD during-frame hosts and the commit variants carry the card."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    acts = legal_actions(state)
    assert CommitFieldTake() in acts           # the bare decline-take
    assert _commit("grain3:1") in acts
    assert not any(isinstance(a, FireTrigger) for a in acts)
    assert Proceed() not in acts               # the take is mandatory first


def test_replace_one_of_two_grain_fields():
    """The replaced field keeps ALL its grain, the other is harvested normally,
    the supply gains 1 (bonus) + 1 (harvest), and the manifest has exactly one
    entry (the replaced field was not harvested — user ruling 2026-07-06)."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3:1"))
    grid = state.players[0].farmyard.grid
    assert grid[0][0].grain == 3               # replaced (scan order): untouched
    assert grid[0][1].grain == 2               # harvested normally
    assert state.players[0].resources.grain == g0 + 2   # 1 harvest + 1 supply
    top = state.pending_stack[-1]
    assert [o.source for o in top.occasions] == ["take"]
    (entry,) = top.occasions[0].entries        # exactly ONE manifest entry
    assert entry.source == "cell:0,1" and entry.amount == 1 and not entry.emptied


def test_replace_both_fields_empties_the_manifest():
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3:2"))
    grid = state.players[0].farmyard.grid
    assert grid[0][0].grain == 3 and grid[0][1].grain == 3   # both untouched
    assert state.players[0].resources.grain == g0 + 2        # both from supply
    top = state.pending_stack[-1]
    assert top.occasions[0].entries == ()      # nothing was harvested


def test_decline_via_bare_take():
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, CommitFieldTake())
    grid = state.players[0].farmyard.grid
    assert grid[0][0].grain == 2 and grid[0][1].grain == 2   # normal take
    assert state.players[0].resources.grain == g0 + 2
    assert len(state.pending_stack[-1].occasions[0].entries) == 2
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.HARVEST_FEED


def test_replaced_one_grain_field_is_not_emptied():
    """A replaced 1-grain field keeps its grain (NOT emptied) and emits no
    manifest entry; the control bare take empties it (emptied=True)."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    at_frame = _walk_to_field_frame(state)

    replaced = step(at_frame, _commit("grain1:1"))
    assert replaced.players[0].farmyard.grid[0][0].grain == 1   # grain stays
    assert replaced.pending_stack[-1].occasions[0].entries == ()
    assert replaced.players[0].resources.grain == \
        at_frame.players[0].resources.grain + 1                 # supply bonus

    control = step(at_frame, CommitFieldTake())
    assert control.players[0].farmyard.grid[0][0].grain == 0
    (entry,) = control.pending_stack[-1].occasions[0].entries
    assert entry.emptied


def test_unowned_never_surfaces():
    """Without the card, a planted grain field gives no take choice: the walk
    takes inline (no PendingFieldPhase) and harvests normally."""
    state = _field_state()
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    assert choice_take_modifiers(state, 0) == []
    after = _walk_to_field_frame(state)
    assert after.phase != Phase.HARVEST_FIELD
    assert not any(isinstance(f, PendingFieldPhase) for f in after.pending_stack)
    assert after.players[0].farmyard.grid[0][0].grain == 2      # base take only


# ---------------------------------------------------------------------------
# Interaction — Grain Sieve ("at least 2 grain" reads the manifest)
# ---------------------------------------------------------------------------

def test_grain_sieve_trips_on_the_normal_take():
    """Harvesting 2 grain fields normally takes 2 grain -> Grain Sieve's bonus
    fires (+1 grain from the supply): +3 total."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = _own_minor(state, 0, "grain_sieve")
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, CommitFieldTake())
    assert state.players[0].resources.grain == g0 + 3   # 2 harvest + 1 sieve


def test_grain_sieve_not_tripped_when_one_field_replaced():
    """Replacing one of the two fields harvests only 1 grain (the replaced
    field is not in the manifest — user ruling 2026-07-06), so Grain Sieve
    stays silent: +2 total (1 harvest + 1 supply), not +3."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = _own_minor(state, 0, "grain_sieve")
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _walk_to_field_frame(state)
    g0 = state.players[0].resources.grain
    state = step(state, _commit("grain3:1"))
    assert state.players[0].resources.grain == g0 + 2


# ---------------------------------------------------------------------------
# Interaction — Scythe Worker (a replaced field donates nothing)
# ---------------------------------------------------------------------------

def test_scythe_worker_takes_nothing_from_a_replaced_field():
    """A replaced 2-grain field yields Scythe Worker no additional grain (its
    auto fold degrades — the cell arrives pre-claimed at full count); the other
    grain field still gives its extra."""
    state = _own_occ(_field_state(), 0, CARD_ID, "scythe_worker")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    state = with_sown_fields(state, 0, grain_fields=[(0, 1)])   # 3 grain
    at_frame = _walk_to_field_frame(state)
    g0 = at_frame.players[0].resources.grain

    state = step(at_frame, _commit("grain2:1"))
    grid = state.players[0].farmyard.grid
    assert grid[0][0].grain == 2               # replaced: SW took nothing
    assert grid[0][1].grain == 1               # base 1 + SW's extra 1
    # +1 supply bonus + 2 harvested from (0,1) = +3.
    assert state.players[0].resources.grain == g0 + 3
    (entry,) = state.pending_stack[-1].occasions[0].entries
    assert entry.source == "cell:0,1" and entry.amount == 2

    # Control (decline): SW takes its extra from BOTH fields -> +4.
    control = step(at_frame, CommitFieldTake())
    grid = control.players[0].farmyard.grid
    assert grid[0][0].grain == 0 and grid[0][1].grain == 1
    assert control.players[0].resources.grain == g0 + 4


# ---------------------------------------------------------------------------
# Interaction — Bumper Crop (the card-played field phase; harvest_scoped=False)
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop",) + tuple(f"m{i}" for i in range(20)),
)


def _at_play_minor_frame(seed=5, *, own_thief=True):
    """A CARDS-mode WORK-phase state at a PendingPlayMinor host, the current
    player holding Bumper Crop in hand with two 3-grain fields (its prereq),
    and Grain Thief already in the tableau when ``own_thief``."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     occupations=(cs.players[cp].occupations | {CARD_ID}
                                  if own_thief else cs.players[cp].occupations))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_sown_fields(cs, cp, grain_fields=((0, 1), (0, 2)))
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _play_bumper_crop(cs):
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1
    return step(cs, plays[0])


def _pick(cs, option):
    top = cs.pending_stack[-1]
    return step(cs, CommitCardChoice(index=top.options.index(option)))


def test_bumper_crop_surfaces_the_choice():
    """Playing Bumper Crop with a planted grain field and Grain Thief owned
    surfaces a PendingCardChoice carrying the plain take AND the replace
    options (harvest_scoped=False — ruling 12)."""
    cs, cp = _at_play_minor_frame()
    cs = _play_bumper_crop(cs)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.player_idx == cp
    assert top.initiated_by_id == "card:bumper_crop"
    assert () in top.options                               # the plain take
    assert ((CARD_ID, "grain3:1"),) in top.options
    assert ((CARD_ID, "grain3:2"),) in top.options


def test_bumper_crop_plain_option_takes_normally():
    cs, cp = _at_play_minor_frame()
    g0 = cs.players[cp].resources.grain
    cs = _play_bumper_crop(cs)
    cs = _pick(cs, ())
    grid = cs.players[cp].farmyard.grid
    assert grid[0][1].grain == 2 and grid[0][2].grain == 2   # both harvested
    assert cs.players[cp].resources.grain == g0 + 2
    assert cs.phase == Phase.WORK                            # no harvest detour
    assert not any(isinstance(f, PendingCardChoice) for f in cs.pending_stack)


def test_bumper_crop_replace_option_leaves_the_grain():
    cs, cp = _at_play_minor_frame()
    g0 = cs.players[cp].resources.grain
    cs = _play_bumper_crop(cs)
    cs = _pick(cs, ((CARD_ID, "grain3:1"),))
    grid = cs.players[cp].farmyard.grid
    assert grid[0][1].grain == 3               # replaced (scan order): untouched
    assert grid[0][2].grain == 2               # harvested normally
    assert cs.players[cp].resources.grain == g0 + 2   # 1 harvest + 1 supply
    assert cs.phase == Phase.WORK


def test_bumper_crop_without_grain_thief_no_choice():
    """Unowned never surfaces: without Grain Thief the on-play takes directly
    (the existing Bumper Crop behavior), no PendingCardChoice."""
    cs, cp = _at_play_minor_frame(own_thief=False)
    g0 = cs.players[cp].resources.grain
    cs = _play_bumper_crop(cs)
    assert not any(isinstance(f, PendingCardChoice) for f in cs.pending_stack)
    grid = cs.players[cp].farmyard.grid
    assert grid[0][1].grain == 2 and grid[0][2].grain == 2
    assert cs.players[cp].resources.grain == g0 + 2


def test_action_labels():
    """The web-UI labeler (display.register_action_labeler) says what happens
    — leave the grain, take supply grain — never the generic count-vector
    prettifier's "+N grain (from ...)" misread."""
    from agricola.cards.display import variant_label

    assert (variant_label("grain_thief", "grain1:2|grain2:1")
            == "leave 2 1-grain fields + 1 2-grain field, +3 grain from supply")
    assert (variant_label("grain_thief", "cf_crop_rotation_field:1")
            == "leave Crop Rotation Field, +1 grain from supply")
