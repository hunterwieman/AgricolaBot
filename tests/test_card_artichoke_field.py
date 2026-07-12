"""Tests for Artichoke Field (minor improvement, E72; Ephipparius Expansion).

Card text (verbatim): "This card is a field. During the field phase of each
harvest, if you harvest at least 1 good from this card, you also get 1 food."

Two effects:
  - a registered card-field (1 stack, grain-or-veg — rulings 45/47, 2026-07-12);
  - a per-occasion harvest AUTO (`register_harvest_occasion_auto`, ruling 21
    2026-07-05: mandatory + choice-free = automatic): +1 food, flat, when a
    field-phase occasion's manifest carries an entry sourced from this card —
    gated on `state.phase == Phase.HARVEST_FIELD` (ruling 12's lexicon,
    2026-07-04 — "During the field phase of each harvest" anchors the window;
    the Crack Weeder precedent), so a mid-WORK Bumper Crop bare take (ruling 4)
    harvests the card's crop but pays nothing.

The harvest tests drive a real harvest through the walk
(`_advance_until_decision` over a `Phase.HARVEST_FIELD` state) so the auto
fires off the actual take manifest; the Bumper Crop negative drives a real
`PendingPlayMinor` -> `CommitPlayMinor` flow mid-WORK.
"""
from __future__ import annotations

import json
from pathlib import Path

import agricola.cards.artichoke_field  # noqa: F401  (registers the card)
import agricola.cards.bumper_crop  # noqa: F401  (the phase-gate negative's driver)
import agricola.cards.scythe_worker  # noqa: F401  (the take-modifier amount-2 case)

import pytest

from agricola.actions import CommitPlayMinor, CommitSow
from agricola.cards.card_fields import (
    CARD_FIELDS,
    card_field_stacks,
    stacks_to_store,
)
from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    apply_harvest_occasion_autos,
    fold_chosen_modifiers,
)
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import HarvestEntry, HarvestOccasion, PendingPlayMinor, PendingSow
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_pending_stack, with_phase, with_resources
from tests.test_utils import sole_play_minor

CARD_ID = "artichoke_field"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    """Put the (played) minor in player `idx`'s tableau."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, stacks, cid=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with both players fed (feeding painless)."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = with_resources(state, idx, food=food)
    return state


def _run_field_phase(state):
    """Advance from HARVEST_FIELD until the field phase completes. The card is
    an occasion AUTO (no choice frame) and no take-modifier is owned, so the
    take runs inline inside `_advance_until_decision`, landing at the feeding
    decision with the field-phase income applied and feeding food NOT yet
    spent."""
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FEED, Phase.HARVEST_BREED,
                           Phase.PREPARATION, Phase.WORK), state.phase
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))   # 1 Wood
    assert spec.min_occupations == 2                        # "2 Occupations"
    assert spec.max_occupations is None
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 1
    # The card-field spec: one stack, unrestricted crops (grain 3 / veg 2).
    cf = CARD_FIELDS[CARD_ID]
    assert cf.stacks == 1
    assert cf.sow_amounts == (("grain", 3), ("veg", 2))
    # The food grant is a registered per-occasion AUTO.
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)


def test_on_play_is_noop():
    state = setup(0)
    assert MINORS[CARD_ID].on_play(state, 0) is state


def test_json_row_matches():
    """The catalog row (revised_minor_improvements.json) matches what the
    module implements and quotes: E72, 1 Wood, 2 Occupations, 1 VP, verbatim
    text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_minor_improvements.json").read_text())
    row = next(r for r in data if r.get("name") == "Artichoke Field")
    assert row["type"] == "Minor Improvement"
    assert row["deck"] == "E"
    assert row["number"] == 72
    assert row["cost"] == "1 Wood"
    assert row["vps"] == 1
    assert row["prerequisites"] == "2 Occupations"
    # Verbatim text in the module docstring (whitespace-normalized: the quote
    # is line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.artichoke_field.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# Playing the card — cost + the 2-Occupations prerequisite (engine flow)
# ---------------------------------------------------------------------------

_POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                 minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)))


def _play_minor_state(n_occupations):
    """A PendingPlayMinor state: the active player holds the card + 1 wood and
    has `n_occupations` played occupations."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     occupations=cs.players[cp].occupations
                     | {f"dummy_occ_{i}" for i in range(n_occupations)},
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),)), cp


def test_play_pays_one_wood_and_keeps_card():
    cs, cp = _play_minor_state(n_occupations=2)
    f0 = cs.players[cp].resources.food
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    after = cs.players[cp]
    assert after.resources.wood == 0                # 1 wood cost paid
    assert after.resources.food == f0               # no on-play grant
    assert CARD_ID in after.minor_improvements      # kept in tableau
    # Freshly played, the card-field is empty (no CardStore entry).
    assert card_field_stacks(after, CARD_ID) == ((0, 0, 0, 0),)


def test_prereq_one_occupation_blocks_play():
    cs, _cp = _play_minor_state(n_occupations=1)
    assert not any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                   for a in legal_actions(cs))


# ---------------------------------------------------------------------------
# "This card is a field" — sowing grain AND vegetables through the engine
# ---------------------------------------------------------------------------

def _sow_state(**resources):
    state = _own_minor(setup(7), 0)
    state = with_resources(state, 0, **resources)
    return with_pending_stack(
        state, (PendingSow(player_idx=0, initiated_by_id="test"),))


def test_sow_offers_both_crops_one_stack():
    state = _sow_state(grain=1, veg=1)
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    card_sows = sorted(a.card_sows for a in sows if a.card_sows)
    # One stack: exactly one card sow at a time, grain or veg.
    assert card_sows == [((CARD_ID, "grain"),), ((CARD_ID, "veg"),)]


def test_sow_grain_plants_three():
    state = _sow_state(grain=1, veg=0)
    commit = CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "grain"),))
    assert commit in legal_actions(state)
    nxt = step(state, commit)
    assert card_field_stacks(nxt.players[0], CARD_ID) == ((3, 0, 0, 0),)
    assert nxt.players[0].resources.grain == 0      # 1 grain spent from supply


def test_sow_veg_plants_two():
    state = _sow_state(grain=0, veg=1)
    commit = CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "veg"),))
    assert commit in legal_actions(state)
    nxt = step(state, commit)
    assert card_field_stacks(nxt.players[0], CARD_ID) == ((0, 2, 0, 0),)
    assert nxt.players[0].resources.veg == 0


def test_sown_card_not_sowable_again():
    state = _sow_state(grain=1, veg=1)
    state = _set_stacks(state, 0, [(3, 0, 0, 0)])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert all(not a.card_sows for a in sows)       # no empty stack left


# ---------------------------------------------------------------------------
# The food grant — driven through a real harvest walk
# ---------------------------------------------------------------------------

def test_grain_harvest_from_card_gives_one_food():
    state = _own_minor(_harvest_state(), 0)
    state = _set_stacks(state, 0, [(3, 0, 0, 0)])
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1     # "you also get 1 food"
    assert after.players[0].resources.grain == g0 + 1    # the mechanical take
    assert card_field_stacks(after.players[0], CARD_ID) == ((2, 0, 0, 0),)


def test_veg_harvest_from_card_gives_one_food():
    """ANY good qualifies — the text says "at least 1 good", not a crop name."""
    state = _own_minor(_harvest_state(), 0)
    state = _set_stacks(state, 0, [(0, 2, 0, 0)])
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[0].resources.veg == v0 + 1
    assert card_field_stacks(after.players[0], CARD_ID) == ((0, 1, 0, 0),)


def test_board_fields_do_not_add_food():
    """Board-field entries are not "from this card": card + two sown board
    fields in the one take -> exactly +1 food."""
    state = _own_minor(_harvest_state(), 0)
    state = _set_stacks(state, 0, [(3, 0, 0, 0)])
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=2),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=1),
    })
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1


def test_take_modifier_amount_two_still_one_food():
    """"If you harvest at least 1 good" is a threshold, not a unit counter:
    Scythe Worker's fold (ruling 46 reaches card-fields) makes the card's
    manifest entry amount 2, and the grant is still exactly +1 food."""
    state = _own_minor(with_phase(setup(0), Phase.HARVEST_FIELD), 0)
    state = _own_occ(state, 0, "scythe_worker")
    state = _set_stacks(state, 0, [(3, 0, 0, 0)])
    plan = fold_chosen_modifiers(state, 0, ())
    assert plan.extras.get(("card", CARD_ID, 0)) == 1
    nxt, occasion = field_take(state, 0, extra_takes=plan.extras)
    entry = next(e for e in occasion.entries if e.source == f"card:{CARD_ID}")
    assert (entry.crop, entry.amount) == ("grain", 2)
    f0 = nxt.players[0].resources.food
    after, _fired = apply_harvest_occasion_autos(nxt, 0, occasion)
    assert after.players[0].resources.food == f0 + 1     # exactly 1, not 2


# ---------------------------------------------------------------------------
# Negatives — empty card, unowned, and the Bumper Crop phase gate
# ---------------------------------------------------------------------------

def test_empty_card_gives_no_food():
    """The take harvested a board field but nothing from this card -> no food."""
    state = _own_minor(_harvest_state(), 0)          # owned, never sown
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0     # no card entry -> nothing
    assert after.players[0].resources.grain == g0 + 1


def test_unowned_never_fires():
    """The registration is global but ownership-gated: a card-sourced entry in
    the manifest pays nothing to a player without the card in the tableau."""
    state = with_phase(setup(0), Phase.HARVEST_FIELD)   # P0 does NOT own it
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source=f"card:{CARD_ID}", crop="grain", amount=1,
                     emptied=False),))
    f0 = state.players[0].resources.food
    after, _fired = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0


def test_bumper_crop_bare_take_gives_no_food():
    """The phase gate (rulings 12 + 4): Bumper Crop's mid-WORK field-phase
    EFFECT harvests the card's crop — the crop arrives and the stack depletes
    — but the phase is WORK, not HARVEST_FIELD, so no food."""
    pool = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                    minors=("bumper_crop", CARD_ID) + tuple(f"m{i}" for i in range(20)))
    cs, _env = setup_env(5, card_pool=pool)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"bumper_crop"}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = _own_minor(cs, cp)                              # Artichoke Field in play
    cs = _set_stacks(cs, cp, [(0, 2, 0, 0)])             # sown with vegetables
    # Bumper Crop's prerequisite: 2 grain fields on the grid.
    cs = with_grid(cs, cp, {(0, 1): Cell(cell_type=CellType.FIELD, grain=1),
                            (0, 2): Cell(cell_type=CellType.FIELD, grain=1)})
    cs = with_pending_stack(cs, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    f0 = cs.players[cp].resources.food
    v0 = cs.players[cp].resources.veg
    assert cs.phase == Phase.WORK
    cs = step(cs, sole_play_minor(cs, "bumper_crop"))

    after = cs.players[cp]
    assert after.resources.veg == v0 + 1                 # the card WAS harvested
    assert card_field_stacks(after, CARD_ID) == ((0, 1, 0, 0),)
    assert after.resources.food == f0                    # ... but pays nothing


# ---------------------------------------------------------------------------
# Ruling 45 — the card counts as 1 field (never a tile) for scoring
# ---------------------------------------------------------------------------

def test_scoring_counts_card_as_one_field_and_its_crops():
    state = setup(7)
    state = with_grid(state, 0, {(2, 0): Cell(cell_type=CellType.FIELD)})
    _, base_bd = score(state, 0)
    owned = _own_minor(state, 0)
    owned = _set_stacks(owned, 0, [(3, 0, 0, 0)])
    _, bd = score(owned, 0)
    # 1 board field -> 2 fields (the card counts once): -1 becomes 1 point.
    assert base_bd.field_tiles == -1 and bd.field_tiles == 1
    # 3 planted grain on the card: -1 becomes 1 point.
    assert base_bd.grain == -1 and bd.grain == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
