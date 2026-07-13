"""Tests for Lettuce Patch (minor improvement, C70; Consul Dirigens Expansion).

Card text (verbatim): "This card is a field that can only grow vegetables. You
can immediately turn each vegetable you harvested from this card into 4 food."

A vegetables-only card-field (rulings 45/47, 2026-07-12: 1 field for
field-count readers; ruling 32, 2026-07-06: never a tile) whose convert is an
UNSCOPED per-occasion optional trigger (ruling 43, 2026-07-12: offered on the
take occasion's `PendingHarvestOccasion` stretch, alongside Food Merchant —
"immediately" does not jump the queue; ruling 12's lexicon, 2026-07-04: bare
harvest-verb wording, so ANY occasion, Bumper Crop's bare take included).
Variants "1".."k" per the Food Merchant per-unit precedent, k = the vegetable
units this occasion harvested from this card, variant j spending j supply
vegetables for 4*j food. The harvest tests drive the REAL walk
(`_advance_until_decision` over a `Phase.HARVEST_FIELD` entry state); the k=2
case rides Stable Manure's donated extra (ruling 46) at the unit level; the
card-driven test plays Bumper Crop through a real `PendingPlayMinor` /
`CommitPlayMinor` flow mid-WORK.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.bumper_crop  # noqa: F401  (the card-driven occasion source)
import agricola.cards.lettuce_patch  # noqa: F401  (registers the card)
import agricola.cards.stable_manure  # noqa: F401  (the k=2 donated extra)

from agricola.actions import CommitPlayMinor, CommitSow, FireTrigger, Proceed
from agricola.cards.card_fields import (
    CARD_FIELDS,
    card_field_stacks,
    stacks_to_store,
)
from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_TRIGGERS,
    fold_chosen_modifiers,
)
from agricola.cards.lettuce_patch import _apply, _eligible, _variants
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    HarvestEntry,
    HarvestOccasion,
    PendingHarvestOccasion,
    PendingPlayMinor,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resolution import emit_harvest_occasion, field_take
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import (
    with_grid,
    with_pending_stack,
    with_phase,
    with_resources,
)

CARD_ID = "lettuce_patch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx, card_ids=(CARD_ID,)):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, stacks, cid=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_entry(*, card_veg=1, own=True, food=10, veg_fields=()):
    """A real-walk harvest: build a HARVEST_FIELD entry state (P0 the starting
    player, holding `food`, the card — when owned — holding `card_veg`
    vegetables, plus any board `veg_fields`) and advance the walk. With the
    card owned and eligible, the walk's inline take pushes P0's
    PendingHarvestOccasion host and pauses there."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=food)
    if veg_fields:
        state = with_grid(state, 0, {
            cell: Cell(cell_type=CellType.FIELD, veg=1) for cell in veg_fields})
    if own:
        state = _own(state, 0)
        if card_veg:
            state = _set_stacks(state, 0, [(0, card_veg, 0, 0)])
    return _advance_until_decision(state)


def _offered_js(state):
    """The convert counts j currently offered as this card's variants."""
    return sorted(int(a.variant) for a in legal_actions(state)
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                  # free
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 3
    assert spec.prereq is None
    assert spec.vps == 1
    assert not spec.passing_left
    cf = CARD_FIELDS[CARD_ID]
    assert cf.stacks == 1
    assert cf.sow_amounts == (("veg", 2),)      # can only grow vegetables
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_TRIGGERS)


def test_json_row_matches():
    """The catalog row (revised_minor_improvements.json) matches what the
    module implements and quotes: C70, minor, free, 3 Occupations, 1 VP,
    verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_minor_improvements.json").read_text())
    row = next(r for r in data if r.get("name") == "Lettuce Patch")
    assert row["type"] == "Minor Improvement"
    assert row["deck"] == "C"
    assert row["number"] == 70
    assert row["expansion"] == "Consul Dirigens Expansion"
    assert row["cost"] is None
    assert row["prerequisites"] == "3 Occupations"
    assert row["vps"] == 1
    # Verbatim text in the docstring (whitespace-normalized: the quote is
    # line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.lettuce_patch.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# The field — sow (vegetables only) + take
# ---------------------------------------------------------------------------

def test_sow_veg_only_then_take():
    state = _own(setup(7), 0)
    state = with_resources(state, 0, grain=1, veg=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    # No board fields: the only sow is the card's — and it is veg-only ("can
    # only grow vegetables"), so no grain sow onto it despite grain in supply.
    assert sows == [CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "veg"),))]
    state = step(state, sows[0])
    p = state.players[0]
    assert card_field_stacks(p, CARD_ID) == ((0, 2, 0, 0),)   # 1 veg plants 2
    assert p.resources.veg == 0 and p.resources.grain == 1

    # The field-phase take harvests 1 from the card's stack.
    nxt, occasion = field_take(state, 0)
    e = [e for e in occasion.entries if e.source == f"card:{CARD_ID}"][0]
    assert (e.crop, e.amount, e.emptied) == ("veg", 1, False)
    assert card_field_stacks(nxt.players[0], CARD_ID) == ((0, 1, 0, 0),)
    assert nxt.players[0].resources.veg == 1


# ---------------------------------------------------------------------------
# The convert — the real harvest walk (ruling 43: the occasion host)
# ---------------------------------------------------------------------------

def test_harvest_offers_convert_and_fires():
    """The card holds 1 veg; the walk's take harvests it and pushes the
    occasion host (ruling 43 — the convert rides the PendingHarvestOccasion
    stretch). Variant "1" turns the harvested vegetable into 4 food; the card
    is then resolved for this occasion."""
    state = _harvest_entry(card_veg=1)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    assert _offered_js(state) == [1]
    assert Proceed() in legal_actions(state)
    # The take itself already happened: the veg landed in supply.
    assert state.players[0].resources.veg == 1

    state = step(state, FireTrigger(card_id=CARD_ID, variant="1"))
    assert state.players[0].resources.veg == 0
    assert state.players[0].resources.food == 10 + 4
    # Once per occasion: the host's triggers_resolved bars a re-fire.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_decline_via_proceed():
    state = _harvest_entry(card_veg=1)
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    state = step(state, Proceed())
    assert state.players[0].resources.veg == 1      # kept, not converted
    assert state.players[0].resources.food == 10
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


# ---------------------------------------------------------------------------
# k=2 — Stable Manure's donated extra (ruling 46) raises the per-unit count
# ---------------------------------------------------------------------------

def test_stable_manure_extra_gives_two_variants():
    """The card holds 2 veg and Stable Manure (one unfenced stable -> cap 1)
    donates the +1 from it: the one take harvests BOTH units in one entry, so
    the convert offers variants "1" and "2" (per-unit — the Food Merchant
    precedent); firing "2" turns both into 8 food."""
    from agricola.cards.stable_manure import _variants as sm_variants
    state = _own(setup(7), 0, [CARD_ID, "stable_manure"])
    state = _set_stacks(state, 0, [(0, 2, 0, 0)])
    p = state.players[0]
    grid = [list(row) for row in p.farmyard.grid]
    grid[2][4] = fast_replace(grid[2][4], cell_type=CellType.STABLE)
    p = fast_replace(p, farmyard=fast_replace(
        p.farmyard, grid=tuple(tuple(r) for r in grid)))
    state = fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))

    assert f"cf_{CARD_ID}:1" in sm_variants(state, 0)
    plan = fold_chosen_modifiers(state, 0, (("stable_manure", f"cf_{CARD_ID}:1"),))
    assert plan.extras == {("card", CARD_ID, 0): 1}
    food0 = state.players[0].resources.food
    nxt, occasion = field_take(state, 0, extra_takes=plan.extras)
    e = [e for e in occasion.entries if e.source == f"card:{CARD_ID}"][0]
    assert (e.crop, e.amount, e.emptied) == ("veg", 2, True)
    assert nxt.players[0].resources.veg == 2

    # Emit the occasion: the host goes up and offers both per-unit variants.
    hosted = emit_harvest_occasion(nxt, 0, occasion)
    assert isinstance(hosted.pending_stack[-1], PendingHarvestOccasion)
    assert _offered_js(hosted) == [1, 2]
    fired = step(hosted, FireTrigger(card_id=CARD_ID, variant="2"))
    assert fired.players[0].resources.veg == 0
    assert fired.players[0].resources.food == food0 + 8


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_not_offered_when_no_veg_harvested_from_card():
    """Only "from this card" counts: a board veg field harvests fine, but the
    empty card contributes nothing -> no host at all (the veg still arrives)."""
    state = _harvest_entry(card_veg=0, veg_fields=((1, 0),))
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)
    assert state.players[0].resources.veg == 1


def test_unowned_never_hosts():
    """The registration is global but ownership-gated: the same veg harvest
    without the card in the tableau pushes no occasion host."""
    state = _harvest_entry(own=False, veg_fields=((1, 0),))
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


def test_eligibility_capped_by_supply():
    """The harvested veg is spent FROM SUPPLY: if a same-occasion earlier
    consumer already spent it (supply veg 0), no variant is offered; with 1
    left, only "1" is (never an unpayable "2")."""
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source=f"card:{CARD_ID}", crop="veg", amount=2,
                     emptied=True),))
    broke = with_resources(setup(0), 0, food=5)         # 0 veg in supply
    assert not _eligible(broke, 0, occ)
    one_left = with_resources(setup(0), 0, veg=1)
    assert _variants(one_left, 0, occ) == ["1"]
    # And grain entries from the card would never count (veg filter).
    grain_occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source=f"card:{CARD_ID}", crop="grain", amount=1,
                     emptied=True),))
    assert not _eligible(one_left, 0, grain_occ)


def test_apply_moves_goods():
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source=f"card:{CARD_ID}", crop="veg", amount=1,
                     emptied=False),))
    state = with_resources(setup(0), 0, veg=1)
    nxt = _apply(state, 0, occ, "1")
    assert nxt.players[0].resources.veg == 0
    assert nxt.players[0].resources.food == 4


# ---------------------------------------------------------------------------
# Unscoped wording (ruling 12) — the card-driven occasion
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop", CARD_ID) + tuple(f"m{i}" for i in range(20)),
)


def test_fires_off_bumper_crop_card_driven_occasion():
    """Ruling 12: 'you harvested from this card' is unscoped (bare harvest
    verb, no phase anchor), so Bumper Crop's mid-WORK field-phase effect
    (occasion source 'card:bumper_crop') hosts the convert too."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     minor_improvements=cs.players[cp].minor_improvements
                     | {CARD_ID})
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    # Bumper Crop's prereq: 2 grain fields (they harvest too — grain entries
    # the veg-only convert ignores).
    cs = with_grid(cs, cp, {(0, 1): Cell(cell_type=CellType.FIELD, grain=1),
                            (0, 2): Cell(cell_type=CellType.FIELD, grain=1)})
    cs = with_resources(cs, cp, food=10)
    cs = _set_stacks(cs, cp, [(0, 1, 0, 0)])
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp,
                         initiated_by_id="space:meeting_place_cards"),))

    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1                          # free -> one payment option
    cs = step(cs, plays[0])

    assert cs.phase == Phase.WORK                   # mid-round, not a harvest
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == cp
    assert top.occasion.source == "card:bumper_crop"
    assert _offered_js(cs) == [1]

    cs = step(cs, FireTrigger(card_id=CARD_ID, variant="1"))
    assert cs.players[cp].resources.veg == 0
    assert cs.players[cp].resources.food == 10 + 4
    assert legal_actions(cs) == [Proceed()]         # once per occasion
    cs = step(cs, Proceed())
    assert cs.phase == Phase.WORK


def test_action_labels():
    """The web-UI labeler (display.register_action_labeler): the full
    exchange at 4 food per vegetable."""
    from agricola.cards.display import variant_label

    assert variant_label(CARD_ID, "2") == "2 veg → 8 food"
    assert variant_label(CARD_ID, "bogus") is None
