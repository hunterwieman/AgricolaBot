"""Tests for Field Cultivator (occupation, D126; Dulcinaria Expansion).

Card text (verbatim): "Pile 1 wood, 1 clay, 1 reed, 1 stone, 1 reed, 1 clay,
and 1 wood on this card. Each time you harvest a field tile, you can also take
the top good from the pile."

An UNSCOPED per-occasion optional trigger (user ruling 12, 2026-07-04 — no
harvest-event anchor in the wording, so it reacts to ANY harvesting occasion)
with per-TILE counting (user ruling 2026-07-06: count the occasion's manifest
ENTRIES, ignoring amounts; k tiles in one occasion = up to k takes AT ONCE, the
count j chosen at the fire, Proceed declining). The pile is the fixed module
constant ``PILE``; the only state is the taken counter (a CardStore int,
absent = 0). The harvest tests drive the REAL walk (`_advance_until_decision`
over a `Phase.HARVEST_FIELD` entry state) to the `PendingHarvestOccasion`
host; the card-driven test plays Bumper Crop through a real `PendingPlayMinor`
/ `CommitPlayMinor` flow mid-WORK; the Grain Thief interaction drives the
`PendingFieldPhase` take commit (a replaced field is not harvested and emits
no manifest entry — ruling 22, user ruling 2026-07-06).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.bumper_crop       # noqa: F401  (card-driven occasion source)
import agricola.cards.field_cultivator  # noqa: F401  (registers the card)
import agricola.cards.grain_thief       # noqa: F401  (replaced-field interaction)

from agricola.actions import CommitFieldTake, CommitPlayMinor, FireTrigger, Proceed
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
    """Stage and advance the real walk. With the card owned and eligible, the
    walk's inline take pushes P0's PendingHarvestOccasion host and pauses."""
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


def _fire(j=1):
    return FireTrigger(card_id=CARD_ID, variant=str(j))


def _offered_js(state):
    """The take counts j currently offered as this card's variants."""
    return sorted(int(a.variant) for a in legal_actions(state)
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


def _no_host(state):
    return not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    entry = next(e for e in HARVEST_OCCASION_TRIGGERS if e.card_id == CARD_ID)
    assert entry.variants_fn is not None            # a play-variant trigger
    # Optional ("you can") — never an occasion AUTO.
    assert all(e.card_id != CARD_ID for e in HARVEST_OCCASION_AUTOS)


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
# The pile order — takes come off the top, the counter advances
# ---------------------------------------------------------------------------

def test_first_two_takes_are_wood_then_clay():
    """A 2-tile harvest offers j in {1, 2}; firing j=2 grants the top two pile
    goods (+1 wood, +1 clay) and advances the counter to 2. The card is then
    resolved for this occasion."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1})
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    assert _offered_js(state) == [1, 2]
    assert Proceed() in legal_actions(state)

    state = step(state, _fire(j=2))
    p = state.players[0]
    assert p.resources.wood == 1
    assert p.resources.clay == 1
    assert p.resources.reed == 0 and p.resources.stone == 0
    assert p.card_state.get(CARD_ID, 0) == 2
    # Once per occasion: the host's triggers_resolved bars a re-fire.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_later_harvest_continues_down_the_pile():
    """With 2 goods already taken, the next takes are the 3rd and 4th pile
    entries: firing j=2 grants +1 reed, +1 stone (counter -> 4)."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1}, taken=2)
    assert _offered_js(state) == [1, 2]
    state = step(state, _fire(j=2))
    p = state.players[0]
    assert p.resources.reed == 1
    assert p.resources.stone == 1
    assert p.resources.wood == 0 and p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 4


# ---------------------------------------------------------------------------
# Per-TILE counting (user ruling 2026-07-06) — entries, not units
# ---------------------------------------------------------------------------

def test_one_multi_grain_field_is_one_tile():
    """One 3-grain field harvested (for 1 grain) is ONE tile: j caps at 1
    regardless of the crop left behind."""
    state = _harvest_entry({(0, 2): 3})
    assert _offered_js(state) == [1]
    state = step(state, _fire(j=1))
    p = state.players[0]
    assert p.resources.wood == 1                     # the pile top
    assert p.card_state.get(CARD_ID, 0) == 1


def test_two_one_grain_fields_are_two_tiles():
    """Two 1-crop fields = 2 tiles = j up to 2 — same total crop as one
    2-grain field, but per-TILE counting sees two entries."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1})
    assert _offered_js(state) == [1, 2]


def test_veg_tiles_count_alike():
    """'A field tile' names no crop: a veg field is a tile too (one grain +
    one veg field = 2 tiles)."""
    state = _harvest_entry({(0, 1): 1}, veg_fields=((0, 4),))
    assert _offered_js(state) == [1, 2]


# ---------------------------------------------------------------------------
# The pile remainder caps j; an empty pile never hosts
# ---------------------------------------------------------------------------

def test_pile_remainder_caps_j():
    """With 6 of 7 goods taken, a 3-tile harvest still offers only j=1, and
    that take grants the last pile entry (wood), exhausting the pile."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1, (0, 3): 1}, taken=6)
    assert _offered_js(state) == [1]
    state = step(state, _fire(j=1))
    p = state.players[0]
    assert p.resources.wood == 1                     # PILE[6] is the bottom wood
    assert p.card_state.get(CARD_ID, 0) == 7


def test_exhausted_pile_never_hosts():
    """Counter at 7: no goods remain, so the trigger is ineligible and no
    occasion host is pushed at all (the harvest itself proceeds normally)."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1, (0, 3): 1}, taken=7)
    assert _no_host(state)
    assert state.players[0].resources.grain == 3     # the take still happened


def test_no_fields_no_host():
    """Nothing harvested = zero tiles = ineligible (no host)."""
    state = _harvest_entry({})
    assert _no_host(state)


# ---------------------------------------------------------------------------
# Optionality — Proceed declines; forgone takes are not recoverable
# ---------------------------------------------------------------------------

def test_decline_via_proceed_counter_unchanged():
    """Proceed declines every offered take: no goods, no counter movement.
    Forgone takes are NOT recoverable — a later 1-tile occasion at the same
    counter caps at j=1 (its own tile count) and still starts from the
    untouched pile top."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1})
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    state = step(state, Proceed())
    p = state.players[0]
    assert p.resources.wood == 0 and p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 0
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)

    later = _harvest_entry({(0, 1): 1})              # same counter (0), 1 tile
    assert _offered_js(later) == [1]                 # no make-up for the 2 declined
    later = step(later, _fire(j=1))
    assert later.players[0].resources.wood == 1      # the pile top, unmoved


def test_partial_take_leaves_the_rest_on_the_pile():
    """Firing j=1 on a 2-tile occasion takes only the top good; the second
    opportunity lapses with the occasion (once per occasion)."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1})
    state = step(state, _fire(j=1))
    p = state.players[0]
    assert p.resources.wood == 1 and p.resources.clay == 0
    assert p.card_state.get(CARD_ID, 0) == 1
    assert legal_actions(state) == [Proceed()]


# ---------------------------------------------------------------------------
# Negative case — unowned never hosts
# ---------------------------------------------------------------------------

def test_unowned_never_hosts():
    """The registration is global but ownership-gated: the same harvest
    without the card in the tableau pushes no occasion host."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 1}, own=False)
    assert _no_host(state)
    assert state.players[0].resources.grain == 2     # normal harvest


# ---------------------------------------------------------------------------
# Interaction — Grain Thief (a replaced field contributes NO tile; ruling 22)
# ---------------------------------------------------------------------------

def test_grain_thief_replaced_field_is_no_tile():
    """Ruling 22 (user ruling 2026-07-06): a Grain-Thief-replaced field is not
    harvested and emits no manifest entry, so of two grain fields with one
    replaced only 1 tile remains — j caps at 1. The bare take (control) keeps
    both tiles; replacing both leaves zero tiles and no host."""
    state = _staged({}, also_own=("grain_thief",))
    state = with_sown_fields(state, 0, grain_fields=[(0, 1), (0, 2)])
    at_frame = _walk_to_field_frame(state)
    assert isinstance(at_frame.pending_stack[-1], PendingFieldPhase)

    replaced = step(at_frame, CommitFieldTake(
        modifiers=(("grain_thief", "grain3:1"),)))
    top = replaced.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert len(top.occasion.entries) == 1            # the replaced field: no entry
    assert _offered_js(replaced) == [1]

    control = step(at_frame, CommitFieldTake())
    assert _offered_js(control) == [1, 2]            # both tiles harvested

    both = step(at_frame, CommitFieldTake(
        modifiers=(("grain_thief", "grain3:2"),)))
    assert _no_host(both)                            # zero tiles harvested


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
    hosts the takes too — same per-tile cap off that occasion's manifest."""
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
    cs = step(cs, plays[0])

    assert cs.phase == Phase.WORK                    # mid-round, not a harvest
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == cp
    assert top.occasion.source == "card:bumper_crop"
    assert _offered_js(cs) == [1, 2]                 # 2 tiles here too

    cs = step(cs, _fire(j=1))
    assert cs.players[cp].resources.wood == w0 + 1   # the pile top
    assert cs.players[cp].card_state.get(CARD_ID, 0) == 1
    assert legal_actions(cs) == [Proceed()]          # once per occasion
    cs = step(cs, Proceed())
    assert cs.phase == Phase.WORK
