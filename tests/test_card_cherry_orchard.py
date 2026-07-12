"""Tests for Cherry Orchard (minor improvement, E68; Ephipparius Expansion).

Card text (verbatim): "This card is a field on which you can only sow and
harvest wood as you would grain. Each time you harvest the last wood from this
card, you also get 1 vegetable."

A card-field (1 stack, wood-as-grain: 1 supply wood plants 3) plus an UNSCOPED
occasion AUTO (user ruling 21, 2026-07-05: "you also get" is mandatory +
choice-free = automatic, never a FireTrigger button; user ruling 12,
2026-07-04: bare harvest-verb wording fires on ANY occasion, a card-driven
bare take included). Covered here: the registration facts (free minor, no
prereq, no VP; the CARD_FIELDS row; auto-not-trigger), sowing wood through
`legal_actions` + `step` at a PendingSow frame (ruling 48's crops_only
negative), the field-phase take, the vegetable grant on the LAST wood (real
walk — and NOT firing while wood remains), the unowned negative, and the
unscoped card-source bare take (the Bumper Crop idiom's frameless form:
`field_take` + `emit_harvest_occasion`).
"""
from __future__ import annotations

import json
from pathlib import Path

import agricola.cards.cherry_orchard  # noqa: F401  (registers the card)

from agricola.actions import CommitSow, FireTrigger
from agricola.cards.card_fields import (
    CARD_FIELDS,
    card_field_stacks,
    stacks_to_store,
)
from agricola.cards.cherry_orchard import CARD_ID, _eligible
from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    HARVEST_OCCASION_TRIGGERS,
    apply_harvest_occasion_autos,
)
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    HarvestEntry,
    HarvestOccasion,
    PendingHarvestOccasion,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resolution import emit_harvest_occasion, field_take
from agricola.resources import Cost
from agricola.setup import setup

from tests.factories import with_pending_stack, with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers (the card-fields seam-test idioms)
# ---------------------------------------------------------------------------

def _own(state, idx, card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, cid, stacks):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _owned(wood_on_card=0, seed=3):
    """P0 owns Cherry Orchard holding `wood_on_card`, zeroed supply."""
    state = _own(setup(seed), 0, [CARD_ID])
    if wood_on_card:
        state = _set_stacks(state, 0, CARD_ID, [(0, 0, wood_on_card, 0)])
    return with_resources(state, 0)


def _walk_harvest(state):
    """Enter a real harvest's field phase and advance the walk."""
    return _advance_until_decision(with_phase(state, Phase.HARVEST_FIELD))


def _card_occ(*, emptied, source="take"):
    """A synthetic occasion whose one entry is this card's wood take."""
    return HarvestOccasion(source=source, entries=(
        HarvestEntry(source=f"card:{CARD_ID}", crop="wood",
                     amount=1, emptied=emptied),))


# ---------------------------------------------------------------------------
# Registration facts
# ---------------------------------------------------------------------------

def test_registered_free_minor_no_prereq_no_vp():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 0


def test_card_field_row_wood_as_grain():
    cf = CARD_FIELDS[CARD_ID]
    assert cf.stacks == 1
    assert cf.sow_amounts == (("wood", 3),)


def test_occasion_registration_is_auto_not_trigger():
    # Ruling 21 (2026-07-05): mandatory + choice-free = automatic — the grant
    # lives in the AUTO registry and never in the trigger (button) one.
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    assert not any(e.card_id == CARD_ID for e in HARVEST_OCCASION_TRIGGERS)


def test_json_row_matches():
    """The catalog row matches what the module implements and quotes: E68,
    Minor Improvement, Ephipparius, no cost/prereq/VP, verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_minor_improvements.json").read_text())
    row = next(r for r in data if r.get("name") == "Cherry Orchard")
    assert row["type"] == "Minor Improvement"
    assert row["deck"] == "E" and row["number"] == 68
    assert row["expansion"] == "Ephipparius Expansion"
    assert row["cost"] is None
    assert row["vps"] is None
    assert row["prerequisites"] is None
    doc = " ".join(agricola.cards.cherry_orchard.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# Sowing (through legal_actions + step at a PendingSow frame)
# ---------------------------------------------------------------------------

def test_sow_wood_spends_one_plants_three():
    state = _owned()
    state = with_resources(state, 0, wood=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    commit = CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "wood"),))
    assert commit in legal_actions(state)
    nxt = step(state, commit)
    p = nxt.players[0]
    assert card_field_stacks(p, CARD_ID) == ((0, 0, 3, 0),)
    assert p.resources.wood == 0


def test_crops_explicit_sow_cannot_plant_wood():
    # Ruling 48 (2026-07-12): a crops-explicit grant may not sow wood here.
    state = _owned()
    state = with_resources(state, 0, wood=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test",
                           crops_only=True)])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert not any(a.card_sows for a in sows)


def test_unowned_sow_never_offered():
    state = with_resources(setup(3), 0, wood=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert not any(a.card_sows for a in sows)


# ---------------------------------------------------------------------------
# The field-phase take
# ---------------------------------------------------------------------------

def test_field_take_harvests_one_wood():
    state = _owned(wood_on_card=3)
    nxt, occ = field_take(state, 0)
    e = next(e for e in occ.entries if e.source == f"card:{CARD_ID}")
    assert (e.crop, e.amount, e.emptied) == ("wood", 1, False)
    assert card_field_stacks(nxt.players[0], CARD_ID) == ((0, 0, 2, 0),)
    assert nxt.players[0].resources.wood == 1


# ---------------------------------------------------------------------------
# The vegetable grant — the LAST wood, as an AUTO (real harvest walk)
# ---------------------------------------------------------------------------

def test_last_wood_grants_vegetable_automatically():
    state = _walk_harvest(_owned(wood_on_card=1))
    p = state.players[0]
    assert p.resources.wood == 1                      # the take's income
    assert p.resources.veg == 1                       # "you also get 1 vegetable"
    assert card_field_stacks(p, CARD_ID) == ((0, 0, 0, 0),)
    # An AUTO fires with no player input: no occasion host, no FireTrigger.
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state))
    assert state.phase == Phase.HARVEST_FEED          # ran straight through


def test_no_vegetable_while_wood_remains():
    state = _walk_harvest(_owned(wood_on_card=2))
    p = state.players[0]
    assert p.resources.wood == 1
    assert p.resources.veg == 0
    assert card_field_stacks(p, CARD_ID) == ((0, 0, 1, 0),)


# ---------------------------------------------------------------------------
# Eligibility boundaries + the unowned negative
# ---------------------------------------------------------------------------

def test_eligibility_requires_this_cards_wood_entry():
    # Card owned but empty (holds 0 wood): a board field's emptied grain take
    # is NOT "the last wood from this card" — no manifest entry of ours.
    state = _owned()
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,1", crop="grain", amount=1, emptied=True),))
    assert not _eligible(state, 0, occ)


def test_eligibility_requires_card_emptied_post_take():
    # Post-take state still holds 1 wood: the take was not the last.
    state = _owned(wood_on_card=1)
    assert not _eligible(state, 0, _card_occ(emptied=False))


def test_eligibility_positive_post_take():
    # Post-take state: the card holds nothing, our wood entry is present.
    state = _owned()
    assert _eligible(state, 0, _card_occ(emptied=True))


def test_unowned_auto_never_fires():
    # The registration is global but ownership-gated at the seam.
    state = with_resources(setup(3), 0)
    nxt, fired = apply_harvest_occasion_autos(state, 0, _card_occ(emptied=True))
    assert CARD_ID not in fired
    assert nxt.players[0].resources.veg == 0


# ---------------------------------------------------------------------------
# Unscoped wording (ruling 12) — a card-driven bare take mid-WORK
# ---------------------------------------------------------------------------

def test_unscoped_card_driven_bare_take_still_grants():
    """Ruling 12 (2026-07-04): no phase anchor, so a Bumper-Crop-shaped
    mid-WORK field-phase effect (bare `field_take` with a card source +
    `emit_harvest_occasion`) taking the last wood grants the vegetable too."""
    state = _owned(wood_on_card=1)
    assert state.phase == Phase.WORK
    state, occ = field_take(state, 0, source="card:bumper_crop")
    state = emit_harvest_occasion(state, 0, occ)
    p = state.players[0]
    assert p.resources.wood == 1
    assert p.resources.veg == 1
    assert card_field_stacks(p, CARD_ID) == ((0, 0, 0, 0),)
    assert state.phase == Phase.WORK                  # mid-round, not a harvest
