"""Tests for Field Cultivator (occupation, D126; Dulcinaria Expansion).

Card text (verbatim): "Pile 1 wood, 1 clay, 1 reed, 1 stone, 1 reed, 1 clay,
and 1 wood on this card. Each time you harvest a field tile, you can also take
the top good from the pile."

An UNSCOPED per-occasion AUTO (user ruling 12, 2026-07-04 — no harvest-event
anchor in the wording, so it reacts to ANY harvesting occasion) with per-TILE
counting (user ruling 2026-07-06: count the occasion's manifest ENTRIES,
ignoring amounts). Per user ruling 41 (2026-07-06) the take is AUTOMATIC
maximum — the owner takes min(tiles harvested, pile remaining) goods with no
FireTrigger, no host frame, and no per-occasion choice (the Scythe Worker
mandatory-max precedent; the optional trigger form is in git history). The
pile is the fixed module constant ``PILE``; the only state is the taken
counter (a CardStore int, absent = 0). The harvest tests drive the REAL walk
(`_advance_until_decision` over a `Phase.HARVEST_FIELD` entry state) through
the inline take — the auto fires with no decision step; the card-driven test
plays Bumper Crop through a real `PendingPlayMinor` / `CommitPlayMinor` flow
mid-WORK; the Grain Thief interaction drives the `PendingFieldPhase` take
commit (a replaced field is not harvested and emits no manifest entry —
ruling 22, user ruling 2026-07-06).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.bumper_crop       # noqa: F401  (card-driven occasion source)
import agricola.cards.field_cultivator  # noqa: F401  (registers the card)
import agricola.cards.grain_thief       # noqa: F401  (replaced-field interaction)

from agricola.actions import CommitFieldTake, CommitPlayMinor, FireTrigger
from agricola.cards.field_cultivator import PILE
from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    HARVEST_OCCASION_TRIGGERS,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFieldPhase,
    PendingHarvestOccasion,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_resources, with_sown_fields

CARD_ID = "field_cultivator"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, *card_ids):
    ids = card_ids or (CARD_ID,)
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | set(ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_taken(state, idx, n):
    """Pre-advance the pile counter (goods already taken in earlier harvests)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _staged(grain_fields, *, own=True, taken=0, veg_fields=(), also_own=()):
    """A HARVEST_FIELD entry state (P0 the starting player, both players fed),
    P0's fields sown per `grain_fields` ({(r, c): grain_amount}) and
    `veg_fields` (1 veg each), the card owned unless `own=False`, the pile
    counter pre-set to `taken`. NOT yet advanced."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    overrides = {cell: Cell(cell_type=CellType.FIELD, grain=n)
                 for cell, n in grain_fields.items()}
    for cell in veg_fields:
        overrides[cell] = Cell(cell_type=CellType.FIELD, veg=1)
    state = with_grid(state, 0, overrides)
    if own:
        state = _own_occ(state, 0, CARD_ID, *also_own)
    if taken:
        state = _set_taken(state, 0, taken)
    return state


def _harvest_entry(grain_fields, **kwargs):
    """Stage and advance the real walk. The inline take fires the auto with
    no pause: the returned state has already received the pile goods."""
    return _advance_until_decision(_staged(grain_fields, **kwargs))


def _walk_to_field_frame(state):
    """Advance until a PendingFieldPhase host surfaces (Grain Thief owned)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingFieldPhase):
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _no_host(state):
    return not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


def _no_fire_offered(state):
    """No FireTrigger for this card anywhere in the legal set — the automatic
    form never surfaces a choice (user ruling 41, 2026-07-06)."""
    return not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state))


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # An occasion AUTO (user ruling 41, 2026-07-06) — never an optional trigger.
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    assert all(e.card_id != CARD_ID for e in HARVEST_OCCASION_TRIGGERS)


def test_on_play_is_noop():
    """The pile is notional: no goods move at play, no CardStore write —
    the taken counter reads absent-as-0."""
    state = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state


def test_json_row_matches():
    """The catalog row (revised_occupations.json) matches what the module
    implements and quotes: D126, Occupation, 1+ players, verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_occupations.json").read_text())
    row = next(r for r in data if r.get("name") == "Field Cultivator")
    assert row["type"] == "Occupation"
    assert row["deck"] == "D"
    assert row["number"] == 126
    assert row["players"] == "1+"
    assert row["expansion"] == "Dulcinaria Expansion"
    # Verbatim text in the docstring (whitespace-normalized: the quote is
    # line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.field_cultivator.__doc__.split())
    assert " ".join(row["text"].split()) in doc


def test_pile_constant_matches_printed_order():
    """The printed setup sentence, top-down: 1 wood, 1 clay, 1 reed, 1 stone,
    1 reed, 1 clay, 1 wood."""
    assert PILE == ("wood", "clay", "reed", "stone", "reed", "clay", "wood")


# ---------------------------------------------------------------------------
# The automatic maximum take (user ruling 41, 2026-07-06) — no choice, ever
# ---------------------------------------------------------------------------

def test_two_tile_harvest_takes_top_two_automatically():
    """A 2-tile harvest fires the auto during the walk's inline take: the top
    two pile goods (+1 wood, +1 clay) arrive with NO decision step — no host
    frame is pushed, no FireTrigger is offered — and the counter advances to
    2 before the walk pauses (at the feed decision)."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1})
    p = state.players[0]
    assert p.resources.wood == 1
    assert p.resources.clay == 1
    assert p.resources.reed == 0 and p.resources.stone == 0
    assert p.card_state.get(CARD_ID, 0) == 2
    assert p.resources.grain == 2                    # the harvest itself
    assert _no_host(state)
    assert _no_fire_offered(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_later_harvest_continues_down_the_pile():
    """With 2 goods already taken, the next automatic takes are the 3rd and
    4th pile entries: a 2-tile harvest grants +1 reed, +1 stone (counter -> 4)."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1}, taken=2)
    p = state.players[0]
    assert p.resources.reed == 1
    assert p.resources.stone == 1
    assert p.resources.wood == 0 and p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 4


# ---------------------------------------------------------------------------
# Per-TILE counting (user ruling 2026-07-06) — entries, not units
# ---------------------------------------------------------------------------

def test_one_multi_grain_field_is_one_tile():
    """One 3-grain field harvested (for 1 grain) is ONE tile: the auto takes
    exactly 1 good (the pile-top wood) regardless of the crop left behind."""
    state = _harvest_entry({(0, 2): 3})
    p = state.players[0]
    assert p.resources.wood == 1                     # the pile top
    assert p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 1


def test_two_one_grain_fields_are_two_tiles():
    """Two 1-crop fields = 2 tiles = 2 automatic takes — same total crop as
    one 2-grain field, but per-TILE counting sees two entries."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1})
    p = state.players[0]
    assert p.resources.wood == 1 and p.resources.clay == 1
    assert p.card_state.get(CARD_ID, 0) == 2


def test_veg_tiles_count_alike():
    """'A field tile' names no crop: a veg field is a tile too (one grain +
    one veg field = 2 tiles = 2 takes)."""
    state = _harvest_entry({(0, 1): 1}, veg_fields=((0, 4),))
    p = state.players[0]
    assert p.resources.wood == 1 and p.resources.clay == 1
    assert p.card_state.get(CARD_ID, 0) == 2


# ---------------------------------------------------------------------------
# The pile remainder caps the take; an empty pile never fires
# ---------------------------------------------------------------------------

def test_pile_remainder_caps_the_take():
    """With 6 of 7 goods taken, a 3-tile harvest takes only the 1 remaining
    good — the last pile entry (wood) — exhausting the pile."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1, (0, 3): 1}, taken=6)
    p = state.players[0]
    assert p.resources.wood == 1                     # PILE[6] is the bottom wood
    assert p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 7


def test_exhausted_pile_never_fires():
    """Counter at 7: no goods remain, so the auto is ineligible — no goods
    move, the counter stays put, and the harvest itself proceeds normally."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1, (0, 3): 1}, taken=7)
    p = state.players[0]
    assert p.resources.wood == 0 and p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 7
    assert p.resources.grain == 3                    # the take still happened
    assert _no_host(state)


def test_no_fields_no_take():
    """Nothing harvested = zero tiles = ineligible (no goods, no counter)."""
    state = _harvest_entry({})
    p = state.players[0]
    assert p.resources.wood == 0
    assert p.card_state.get(CARD_ID, 0) == 0
    assert _no_host(state)


# ---------------------------------------------------------------------------
# Negative case — unowned never fires
# ---------------------------------------------------------------------------

def test_unowned_never_fires():
    """The registration is global but ownership-gated: the same harvest
    without the card in the tableau moves no goods."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1}, own=False)
    p = state.players[0]
    assert p.resources.wood == 0 and p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 0
    assert p.resources.grain == 2                    # normal harvest
    assert _no_host(state)


# ---------------------------------------------------------------------------
# Interaction — Grain Thief (a replaced field contributes NO tile; ruling 22)
# ---------------------------------------------------------------------------

def test_grain_thief_replaced_field_is_no_tile():
    """Ruling 22 (user ruling 2026-07-06): a Grain-Thief-replaced field is not
    harvested and emits no manifest entry, so of two grain fields with one
    replaced only 1 tile remains — the auto takes 1 good. The bare take
    (control) keeps both tiles (2 takes); replacing both leaves zero tiles
    and no take at all."""
    state = _staged({}, also_own=("grain_thief",))
    state = with_sown_fields(state, 0, grain_fields=[(0, 1), (0, 2)])
    at_frame = _walk_to_field_frame(state)
    assert isinstance(at_frame.pending_stack[-1], PendingFieldPhase)

    replaced = step(at_frame, CommitFieldTake(
        modifiers=(("grain_thief", "grain3:1"),)))
    p = replaced.players[0]
    assert p.resources.wood == 1 and p.resources.clay == 0   # 1 tile -> 1 take
    assert p.card_state.get(CARD_ID, 0) == 1

    control = step(at_frame, CommitFieldTake())
    p = control.players[0]
    assert p.resources.wood == 1 and p.resources.clay == 1   # both tiles
    assert p.card_state.get(CARD_ID, 0) == 2

    both = step(at_frame, CommitFieldTake(
        modifiers=(("grain_thief", "grain3:2"),)))
    p = both.players[0]
    assert p.resources.wood == 0 and p.resources.clay == 0   # zero tiles
    assert p.card_state.get(CARD_ID, 0) == 0


# ---------------------------------------------------------------------------
# Unscoped wording (ruling 12) — the card-driven occasion
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop",) + tuple(f"m{i}" for i in range(20)),
)


def test_fires_off_bumper_crop_card_driven_occasion():
    """Ruling 12: 'each time you harvest a field tile' is unscoped, so Bumper
    Crop's mid-WORK field-phase effect (occasion source 'card:bumper_crop')
    fires the auto too — the maximum take off that occasion's manifest
    (2 tiles -> the top two pile goods), inline, with no host frame."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     occupations=cs.players[cp].occupations | {CARD_ID})
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_sown_fields(cs, cp, grain_fields=((0, 1), (0, 2)))
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1                           # free -> one payment option
    w0 = cs.players[cp].resources.wood
    c0 = cs.players[cp].resources.clay
    cs = step(cs, plays[0])

    assert cs.phase == Phase.WORK                    # mid-round, not a harvest
    p = cs.players[cp]
    assert p.resources.wood == w0 + 1                # the automatic maximum:
    assert p.resources.clay == c0 + 1                # 2 tiles -> top two goods
    assert p.card_state.get(CARD_ID, 0) == 2
    assert _no_host(cs)


# --- Ruling 32 (2026-07-06): a card-field is NOT a "field tile" ---------------

def test_card_field_entries_are_not_tiles():
    """A future card-field's manifest entry (source="card:<id>") contributes no
    tile: an occasion of one board field + one card-field caps the automatic
    take at 1, and an occasion of card-field entries alone is ineligible
    (user ruling 32)."""
    from agricola.cards.field_cultivator import _eligible, _max_take
    from agricola.pending import HarvestEntry, HarvestOccasion

    state = _own_occ(setup(0), 0, CARD_ID)
    mixed = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,1", crop="grain", amount=1, emptied=False),
        HarvestEntry(source="card:beanfield", crop="grain", amount=1, emptied=True),
    ))
    assert _max_take(state, 0, mixed) == 1
    card_only = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="card:beanfield", crop="grain", amount=1, emptied=True),
    ))
    assert not _eligible(state, 0, card_only)
