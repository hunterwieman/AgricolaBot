"""Tests for Food Merchant (occupation, D113; Dulcinaria Expansion).

Card text (verbatim): "For each grain you harvest from a field, you can buy 1
vegetable for 3 food. If you harvest the last grain from a field, the vegetable
costs you only 2 food."

An UNSCOPED per-occasion optional trigger (user ruling 12, 2026-07-04 — no
harvest-event anchor in the wording, so it reacts to ANY harvesting occasion,
gated on the occasion, never on `state.phase`): N2 = emptied grain entries
(2-food buys), N3 = remaining grain units (3-food buys); one FireTrigger variant
per affordable vegetable count k with cost(k) = 2*min(k, N2) + 3*max(0, k − N2)
(discounted buys filled first — Pareto-minimal). The harvest tests drive the
REAL walk (`_advance_until_decision` over a `Phase.HARVEST_FIELD` entry state)
to the `PendingHarvestOccasion` host; the card-driven test plays Bumper Crop
through a real `PendingPlayMinor` / `CommitPlayMinor` flow mid-WORK.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.bumper_crop  # noqa: F401  (the card-driven occasion source)
import agricola.cards.food_merchant  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor, FireTrigger, Proceed
from agricola.cards.food_merchant import _buy_counts
from agricola.cards.harvest_windows import HARVEST_OCCASION_TRIGGERS
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    HarvestEntry,
    HarvestOccasion,
    PendingHarvestOccasion,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_resources

CARD_ID = "food_merchant"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_entry(grain_fields: dict, *, food=20, own=True, veg_fields=()):
    """A real-walk harvest: build a HARVEST_FIELD entry state (P0 the starting
    player, both players holding `food`, P0's fields sown per `grain_fields`
    ({(r, c): grain_amount}) and `veg_fields`) and advance the walk. With the
    card owned and eligible, the walk's inline take pushes P0's
    PendingHarvestOccasion host and pauses there."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=food)
    overrides = {cell: Cell(cell_type=CellType.FIELD, grain=n)
                 for cell, n in grain_fields.items()}
    for cell in veg_fields:
        overrides[cell] = Cell(cell_type=CellType.FIELD, veg=1)
    state = with_grid(state, 0, overrides)
    if own:
        state = _own_occ(state, 0)
    return _advance_until_decision(state)


def _fire(card_id=CARD_ID, k=1):
    return FireTrigger(card_id=card_id, variant=str(k))


def _offered_ks(state):
    """The vegetable counts k currently offered as this card's variants."""
    return sorted(int(a.variant) for a in legal_actions(state)
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_TRIGGERS)


def test_on_play_is_noop():
    state = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state


def test_json_row_matches():
    """The catalog row (revised_occupations.json) matches what the module
    implements and quotes: D113, Occupation, 1+ players, verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_occupations.json").read_text())
    row = next(r for r in data if r.get("name") == "Food Merchant")
    assert row["type"] == "Occupation"
    assert row["deck"] == "D"
    assert row["number"] == 113
    assert row["players"] == "1+"
    assert row["expansion"] == "Dulcinaria Expansion"
    # Verbatim text in the docstring (whitespace-normalized: the quote is
    # line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.food_merchant.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# The counting doctrine — N2/N3 off the manifest
# ---------------------------------------------------------------------------

def test_emptied_two_grain_entry_is_one_discount():
    """Counting doctrine: an emptied 2-grain entry (one FIELD whose take-modifier
    fold-in removed both units in the one event) unlocks ONE 2-food buy — exactly
    one of its units was the field's last grain — plus one 3-food buy."""
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,1", crop="grain", amount=2, emptied=True),))
    assert _buy_counts(occ) == (1, 1)


def test_veg_entries_never_count():
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:1,0", crop="veg", amount=1, emptied=True),))
    assert _buy_counts(occ) == (0, 0)


# ---------------------------------------------------------------------------
# The real harvest — variants, pricing, firing, once-per-occasion
# ---------------------------------------------------------------------------

def test_harvest_variants_and_fire_k2():
    """A 1-grain field (emptied by the take) + a 3-grain field: 2 grain units,
    N2=1, N3=1 -> k=1 at 2 food, k=2 at 2+3=5 food. Firing k=2 pays 5 food and
    gains 2 vegetables; the card is then resolved for this occasion."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 3})
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    assert _offered_ks(state) == [1, 2]
    assert Proceed() in legal_actions(state)

    # The take itself already happened: +2 grain, the 1-grain field emptied.
    assert state.players[0].resources.grain == 2
    assert state.players[0].farmyard.grid[0][1].grain == 0
    assert state.players[0].farmyard.grid[0][2].grain == 2

    state = step(state, _fire(k=2))
    assert state.players[0].resources.food == 20 - 5
    assert state.players[0].resources.veg == 2
    # Once per occasion: the host's triggers_resolved bars a re-fire.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_discount_ordering_k1_costs_2():
    """With an emptied grain field, the single buy uses the 2-food price (not
    3): at exactly 2 food, k=1 is offered and firing it lands on 0 food."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 3}, food=2)
    assert _offered_ks(state) == [1]                    # cost(2)=5 unaffordable
    state = step(state, _fire(k=1))
    assert state.players[0].resources.food == 0
    assert state.players[0].resources.veg == 1


def test_no_discount_without_emptied_field():
    """A single 3-grain field is not emptied by taking 1: N2=0, so the one buy
    costs 3 food — unaffordable at 2 food (no host at all), affordable at 3."""
    poor = _harvest_entry({(0, 2): 3}, food=2)
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in poor.pending_stack)

    state = _harvest_entry({(0, 2): 3}, food=3)
    assert _offered_ks(state) == [1]
    state = step(state, _fire(k=1))
    assert state.players[0].resources.food == 0
    assert state.players[0].resources.veg == 1


def test_food_limited_drops_unaffordable_k():
    """N2=1, N3=1 with 4 food: cost(2)=5 > 4, so only k=1 is offered."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 3}, food=4)
    assert _offered_ks(state) == [1]
    state = step(state, _fire(k=1))
    assert state.players[0].resources.food == 2
    assert state.players[0].resources.veg == 1


def test_two_grain_field_not_emptied_by_take():
    """One 1-grain field (emptied) + one 2-grain field (take leaves 1 — NOT
    emptied): N2=1, N3=1. The 2-grain field earns no second discount."""
    state = _harvest_entry({(0, 1): 1, (0, 3): 2})
    assert state.players[0].farmyard.grid[0][3].grain == 1
    assert _offered_ks(state) == [1, 2]
    state = step(state, _fire(k=2))
    assert state.players[0].resources.food == 20 - 5    # 2 + 3, not 2 + 2
    assert state.players[0].resources.veg == 2


def test_decline_via_proceed():
    state = _harvest_entry({(0, 1): 1, (0, 2): 3})
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    state = step(state, Proceed())
    assert state.players[0].resources.veg == 0
    assert state.players[0].resources.food == 20
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_veg_only_harvest_not_eligible():
    """A harvest that takes only vegetables unlocks nothing — no host, and the
    walk runs straight through to feeding (the veg still arrives)."""
    state = _harvest_entry({}, veg_fields=((1, 0),))
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)
    assert state.players[0].resources.veg == 1


def test_unowned_never_hosts():
    """The registration is global but ownership-gated: the same grain harvest
    without the card in the tableau pushes no occasion host."""
    state = _harvest_entry({(0, 1): 1, (0, 2): 3}, own=False)
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Unscoped wording (ruling 12) — the card-driven occasion
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop",) + tuple(f"m{i}" for i in range(20)),
)


def test_fires_off_bumper_crop_card_driven_occasion():
    """Ruling 12: 'you harvest from a field' is unscoped, so Bumper Crop's
    mid-WORK field-phase effect (occasion source 'card:bumper_crop') hosts the
    buys too — same N2/N3 pricing off that occasion's manifest."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     occupations=cs.players[cp].occupations | {CARD_ID})
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_grid(cs, cp, {(0, 1): Cell(cell_type=CellType.FIELD, grain=1),
                            (0, 2): Cell(cell_type=CellType.FIELD, grain=3)})
    cs = with_resources(cs, cp, food=10)
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1                              # free -> one payment option
    cs = step(cs, plays[0])

    assert cs.phase == Phase.WORK                       # mid-round, not a harvest
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == cp
    assert top.occasion.source == "card:bumper_crop"
    assert _offered_ks(cs) == [1, 2]                    # N2=1, N3=1 here too

    cs = step(cs, _fire(k=2))
    assert cs.players[cp].resources.food == 10 - 5
    assert cs.players[cp].resources.veg == 2
    assert legal_actions(cs) == [Proceed()]             # once per occasion
    cs = step(cs, Proceed())
    assert cs.phase == Phase.WORK


def test_action_labels():
    """The web-UI labeler (display.register_action_labeler): the buy count.
    The price is deliberately absent — cost(k) depends on the occasion's
    discounted-buy count, which is not in the variant string."""
    from agricola.cards.display import variant_label

    assert variant_label("food_merchant", "2") == "buy 2 veg"
    assert variant_label("food_merchant", "bogus") is None
