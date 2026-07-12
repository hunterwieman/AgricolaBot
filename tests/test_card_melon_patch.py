"""Tests for Melon Patch (minor improvement, E69; Ephipparius Expansion).

Card text (verbatim): "This card is a field that can only grow vegetables. Each
time you harvest the last vegetable from this card, you can plow 1 field."

A card-field (veg-only sow whitelist, 1 stack — rulings 45/47, 2026-07-12)
whose "harvest the last vegetable" reaction is an UNSCOPED per-occasion
optional trigger (ruling 12, 2026-07-04; rulings 43/44, 2026-07-12): the
`PendingHarvestOccasion` host offers `FireTrigger("melon_patch")`, firing
pushes the standard single-shot `PendingPlow` (cell picked via the normal
CommitPlow flow), and Proceed declines. The harvest tests drive the REAL walk
(`_advance_until_decision` over a `Phase.HARVEST_FIELD` entry state); the
scoping test plays Bumper Crop through a real `PendingPlayMinor` /
`CommitPlayMinor` flow mid-WORK.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.bumper_crop  # noqa: F401  (the card-driven occasion source)
import agricola.cards.melon_patch  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitPlayMinor,
    CommitPlow,
    CommitSow,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.card_fields import (
    CARD_FIELDS,
    card_field_stacks,
    card_holds,
    stacks_to_store,
)
from agricola.cards.harvest_windows import HARVEST_OCCASION_TRIGGERS
from agricola.cards.melon_patch import _eligible
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import _can_plow, legal_actions
from agricola.pending import (
    HarvestEntry,
    HarvestOccasion,
    PendingHarvestOccasion,
    PendingPlayMinor,
    PendingPlow,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import (
    with_grid,
    with_pending_stack,
    with_phase,
    with_resources,
)

CARD_ID = "melon_patch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, stacks):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, CARD_ID, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_entry(*, own=True, veg_on_card=1, grid_overrides=None, food=20):
    """A real-walk harvest: build a HARVEST_FIELD entry state (P0 the starting
    player, both players fed, P0 owning the card with `veg_on_card` vegetables
    on it) and advance the walk. With the card owned and the trigger eligible,
    the walk's inline take pushes P0's PendingHarvestOccasion host and pauses
    there."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=food)
    if grid_overrides:
        state = with_grid(state, 0, grid_overrides)
    if own:
        state = _own(state, 0)
        if veg_on_card:
            state = _set_stacks(state, 0, [(0, veg_on_card, 0, 0)])
    return _advance_until_decision(state)


def _my_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _no_occasion_host(state):
    return not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                    # no cost
    assert spec.min_occupations == 2              # prerequisite: 2 Occupations
    assert spec.vps == 0                          # no printed VP
    assert spec.prereq is None
    assert spec.passing_left is False
    cf = CARD_FIELDS[CARD_ID]
    assert cf.stacks == 1                         # ruling 47: no N-fields clause
    assert cf.sow_amounts == (("veg", 2),)        # can only grow vegetables
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_TRIGGERS)


def test_json_row_matches():
    """The catalog row (revised_minor_improvements.json) matches what the
    module implements and quotes: E69, Minor Improvement, Ephipparius, free,
    no VP, 2-Occupations prerequisite, verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_minor_improvements.json").read_text())
    row = next(r for r in data if r.get("name") == "Melon Patch")
    assert row["type"] == "Minor Improvement"
    assert row["deck"] == "E"
    assert row["number"] == 69
    assert row["expansion"] == "Ephipparius Expansion"
    assert row["prerequisites"] == "2 Occupations"
    assert row["cost"] is None and row["vps"] is None
    # Verbatim text in the docstring (whitespace-normalized: the quote is
    # line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.melon_patch.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# The field — sowing and the take
# ---------------------------------------------------------------------------

def test_sow_veg_only_via_legal_actions():
    """At a PendingSow frame the card's empty stack is offered — for
    vegetables ONLY (the whitelist: grain in supply never reaches the card,
    and setup has no board fields so no other sow exists)."""
    state = _own(setup(7), 0)
    state = with_resources(state, 0, veg=1, grain=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert sows == [CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "veg"),))]
    nxt = step(state, sows[0])
    p = nxt.players[0]
    assert card_field_stacks(p, CARD_ID) == ((0, 2, 0, 0),)   # 1 veg plants 2
    assert p.resources.veg == 0 and p.resources.grain == 1


def test_take_harvests_card_and_empties_store():
    """The field-phase take harvests 1 veg from the card (one card:melon_patch
    entry, emptied) and the harvested-out card's store entry is removed."""
    state = _own(setup(7), 0)
    pristine = state.players[0].card_state
    state = _set_stacks(state, 0, [(0, 1, 0, 0)])
    nxt, occasion = field_take(state, 0)
    es = [e for e in occasion.entries if e.source == f"card:{CARD_ID}"]
    assert len(es) == 1
    assert (es[0].crop, es[0].amount, es[0].emptied) == ("veg", 1, True)
    assert nxt.players[0].resources.veg - state.players[0].resources.veg == 1
    assert nxt.players[0].card_state == pristine


# ---------------------------------------------------------------------------
# The real harvest — offer, fire, plow, once-per-occasion
# ---------------------------------------------------------------------------

def test_last_veg_offers_plow_and_fires():
    """Harvesting the card's last vegetable hosts the occasion; firing pushes
    the standard single-shot PendingPlow, whose CommitPlow plows a cell, Stop
    pops back to the host, and the trigger is resolved for the occasion."""
    state = _harvest_entry()
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    # The take already happened: the veg arrived, the card emptied out.
    assert state.players[0].resources.veg == 1
    assert card_holds(state.players[0], CARD_ID, "veg") == 0
    fires = _my_fires(state)
    assert len(fires) == 1
    assert Proceed() in legal_actions(state)

    state = step(state, fires[0])
    plow = state.pending_stack[-1]
    assert isinstance(plow, PendingPlow)
    assert plow.initiated_by_id == f"card:{CARD_ID}"
    assert plow.player_idx == 0
    commits = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    assert commits
    target = commits[0]
    state = step(state, target)
    grid = state.players[0].farmyard.grid
    assert grid[target.row][target.col].cell_type == CellType.FIELD
    # Single-shot plow: the after-phase offers Stop, which pops to the host.
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    # Once per occasion: the trigger is resolved; only Proceed remains.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_decline_via_proceed():
    """'You can plow' — declining = Proceed on the host without firing: no
    PendingPlow, no new field, the walk continues."""
    state = _harvest_entry()
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    fields_before = sum(
        1 for row in state.players[0].farmyard.grid for c in row
        if c.cell_type == CellType.FIELD)
    state = step(state, Proceed())
    assert not any(isinstance(f, PendingPlow) for f in state.pending_stack)
    fields_after = sum(
        1 for row in state.players[0].farmyard.grid for c in row
        if c.cell_type == CellType.FIELD)
    assert fields_after == fields_before
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_not_offered_when_veg_remains():
    """With 2 veg on the card the take removes 1 and 1 remains — not the last
    vegetable, so no host is pushed (the veg still arrives)."""
    state = _harvest_entry(veg_on_card=2)
    assert _no_occasion_host(state)
    assert state.players[0].resources.veg == 1
    assert card_holds(state.players[0], CARD_ID, "veg") == 1


def test_unowned_never_hosts():
    """The registration is global but ownership-gated: without the card in the
    tableau, a veg harvest (board field) pushes no occasion host."""
    state = _harvest_entry(
        own=False,
        grid_overrides={(1, 1): Cell(cell_type=CellType.FIELD, veg=1)})
    assert _no_occasion_host(state)
    assert state.players[0].resources.veg == 1


def test_not_offered_without_plow_target():
    """Never offer a grant whose fired frame would have no legal commit: with
    every empty cell already a field, no legal plow target exists, so
    harvesting the last veg pushes no host (the veg still arrives)."""
    base = setup(seed=0)
    overrides = {
        (r, c): Cell(cell_type=CellType.FIELD)
        for r in range(3) for c in range(5)
        if base.players[0].farmyard.grid[r][c].cell_type == CellType.EMPTY}
    state = _harvest_entry(grid_overrides=overrides)
    assert not _can_plow(state.players[0])
    assert _no_occasion_host(state)
    assert state.players[0].resources.veg == 1
    assert card_holds(state.players[0], CARD_ID, "veg") == 0


def test_board_veg_harvest_without_card_entry_not_eligible():
    """Eligibility reads the card's OWN entry: a veg harvest that never
    touched the card (board field only; the owned card is empty, so holds==0
    and a plow target exists) does not qualify."""
    state = _own(setup(0), 0)
    assert _can_plow(state.players[0])
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:1,1", crop="veg", amount=1, emptied=True),))
    assert not _eligible(state, 0, occ)


# ---------------------------------------------------------------------------
# Unscoped wording (ruling 12) — the card-driven occasion
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop",) + tuple(f"m{i}" for i in range(20)),
)


def test_fires_off_bumper_crop_card_driven_occasion():
    """Ruling 12: 'you harvest the last vegetable' is unscoped, so Bumper
    Crop's mid-WORK field-phase effect (occasion source 'card:bumper_crop')
    empties the card and offers the plow there too."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     minor_improvements=cs.players[cp].minor_improvements
                     | {CARD_ID})
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    # Bumper Crop's prerequisite: 2 grain fields on the grid.
    cs = with_grid(cs, cp, {(0, 1): Cell(cell_type=CellType.FIELD, grain=1),
                            (0, 2): Cell(cell_type=CellType.FIELD, grain=1)})
    cs = _set_stacks(cs, cp, [(0, 1, 0, 0)])
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp,
                         initiated_by_id="space:meeting_place_cards"),))

    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1                        # free -> one payment option
    cs = step(cs, plays[0])

    assert cs.phase == Phase.WORK                 # mid-round, not a harvest
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == cp
    assert top.occasion.source == "card:bumper_crop"
    assert cs.players[cp].resources.veg == 1      # the card's veg arrived
    assert card_holds(cs.players[cp], CARD_ID, "veg") == 0

    fires = [a for a in legal_actions(cs)
             if isinstance(a, FireTrigger) and a.card_id == CARD_ID]
    assert len(fires) == 1
    cs = step(cs, fires[0])
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitPlow)]
    target = commits[0]
    cs = step(cs, target)
    assert (cs.players[cp].farmyard.grid[target.row][target.col].cell_type
            == CellType.FIELD)
    cs = step(cs, Stop())
    assert legal_actions(cs) == [Proceed()]       # once per occasion
    cs = step(cs, Proceed())
    assert cs.phase == Phase.WORK
