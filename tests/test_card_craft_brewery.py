"""Tests for Craft Brewery (minor improvement, C63; Corbarius Expansion).

Card text (verbatim): "In the feeding phase of each harvest, you can use this
card to exchange 1 grain from your supply plus 1 grain from a field for 2 bonus
points and 4 food."
Cost 2 wood, 1 clay. No prerequisite. VPs: none printed (points are earned).

The exchange rides the HARVEST_CONVERSIONS seam (the printed "in the feeding
phase of each harvest" timing — Beer Keg precedent). The which-field choice
surfaces WIDE, encoded by field height (user ruling 2026-07-06): one
``CommitHarvestConversion(conversion_id, variant="h<X>")`` per grain-count group
present among the player's fields; the canonical field of the chosen group is
the first in row-major scan order. Firing debits 1 supply grain (the spec's
input_cost) + 1 grain off the chosen-height field (the side effect), grants
4 food (food_out, arriving BEFORE the feeding payment — conversions fire
pre-CommitConvert), and banks 2 bonus points in the CardStore for the scoring
term. NOT a harvest (ruling 12's lexicon, 2026-07-03): no harvesting occasion is
emitted, so harvest-consequence cards (Grain Sieve) get nothing from it.

These tests drive the REAL harvest walk from Phase.HARVEST_FIELD (the field-
phase take removes 1 grain from each planted field before FEED — the sown
amounts below account for that), plus ``_initiate_harvest_feed`` for the one
state the walk cannot produce (planted fields with an empty grain supply).
"""
from __future__ import annotations

import dataclasses

import agricola.cards.craft_brewery  # noqa: F401  (register the card)
import agricola.cards.grain_sieve    # noqa: F401  (the NOT-a-harvest witness)

from agricola.actions import CommitConvert, CommitHarvestConversion, Stop
from agricola.cards.craft_brewery import CARD_ID, _variants
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestOccasion
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import add_resources, with_minors, with_phase, with_resources


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_fields(state, idx, fields, veg_fields=None):
    """Set cells to FIELD: `fields` maps (r, c) -> grain held; `veg_fields`
    maps (r, c) -> veg held. Cells not named are untouched."""
    veg_fields = veg_fields or {}
    p = state.players[idx]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD, grain=fields[(r, c)])
            if (r, c) in fields else
            fast_replace(cell, cell_type=CellType.FIELD, veg=veg_fields[(r, c)])
            if (r, c) in veg_fields else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


def _field_grain(state, idx, r, c):
    return state.players[idx].farmyard.grid[r][c].grain


def _harvest_state(*, fields=None, grain=0, food=10, owners=(0,)):
    """A HARVEST_FIELD-phase state: P0 holds `grain`/`food` and the SOWN
    `fields` ({(r,c): grain} — the field-phase take removes 1 from each before
    FEED); the seats in `owners` own Craft Brewery; P1 food-rich."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in owners:
        state = with_minors(state, i, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, grain=grain)
    state = with_resources(state, 1, food=99)
    if fields:
        state = _set_fields(state, 0, fields)
    return state


def _walk_to_p0_feed(state):
    """Drive the harvest walk until P0's still-undecided feed frame is on top."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestFeed) and top.player_idx == 0
                and not top.conversion_done):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("no P0 feed frame surfaced")


def _brewery_actions(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion)
            and a.conversion_id == CARD_ID]


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=2, clay=1)   # "2 Wood,1 Clay"
    assert spec.min_occupations == 0                          # no prerequisite
    assert spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 0                                      # none printed
    conv = HARVEST_CONVERSIONS[CARD_ID]
    assert conv.input_cost == Resources(grain=1)              # the supply grain
    assert conv.food_out == 4
    assert conv.variants_fn is not None                       # which-field choice
    assert conv.side_effect_fn is not None                    # field grain + points
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- The variants encoding (unit) --------------------------------------------

def test_variants_one_tag_per_height_sorted():
    """One "h<X>" per grain-height group present, ascending; same-height
    fields collapse into one tag (ruling 2026-07-06)."""
    state = setup(seed=0)
    state = _set_fields(state, 0, {(0, 1): 3, (0, 2): 1, (0, 3): 1})
    assert _variants(state, 0) == ["h1", "h3"]
    state = setup(seed=0)
    state = _set_fields(state, 0, {(0, 1): 1, (0, 2): 2, (0, 3): 3})
    assert _variants(state, 0) == ["h1", "h2", "h3"]


def test_variants_empty_without_planted_grain():
    """No fields, empty fields, and veg-only fields all yield no variants."""
    state = setup(seed=0)
    assert _variants(state, 0) == []
    state = _set_fields(state, 0, {(0, 1): 0}, veg_fields={(0, 2): 2})
    assert _variants(state, 0) == []


# --- The exchange, end-to-end through the walk --------------------------------

def test_fire_h2_full_accounting():
    """Sown {3, 2} -> post-take heights {2, 1}, supply grain 0 -> 2. Firing
    "h2" debits 1 supply grain, decrements the 2-grain field to 1, grants
    4 food and 2 banked points, marks the conversion used (no re-offer) —
    and the 4 food arrives in time to pay the feeding cost (food starts 0)."""
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 3, (0, 2): 2}, grain=0, food=0))
    p = state.players[0]
    assert p.resources.grain == 2                 # +1 per field-phase take
    assert _field_grain(state, 0, 0, 1) == 2
    assert _field_grain(state, 0, 0, 2) == 1
    # The offers match the POST-take heights, one per group, ascending.
    assert _brewery_actions(state) == [
        CommitHarvestConversion(conversion_id=CARD_ID, variant="h1"),
        CommitHarvestConversion(conversion_id=CARD_ID, variant="h2"),
    ]

    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID, variant="h2"))
    p = state.players[0]
    assert p.resources.grain == 1                 # 1 supply grain spent
    assert p.resources.food == 4                  # +4, BEFORE the feeding payment
    assert _field_grain(state, 0, 0, 1) == 1      # the 2-grain field, decremented
    assert _field_grain(state, 0, 0, 2) == 1      # the other field untouched
    assert p.card_state.get(CARD_ID, 0) == 2      # 2 bonus points banked
    assert CARD_ID in p.harvest_conversions_used
    # Once per harvest: no re-offer (even though heights are still present).
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)
    assert _brewery_actions(state) == []

    # The brewed food pays this harvest's feeding: need 4, no begging.
    assert CommitConvert(0, 0, 0, 0, 0) in legal_actions(state)
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 0


def test_canonical_field_is_first_in_row_major_order():
    """Two same-height fields: the debit lands on the row-major-first one."""
    state = _walk_to_p0_feed(_harvest_state(
        fields={(1, 2): 3, (0, 3): 3}, grain=0, food=10))
    assert _brewery_actions(state) == [
        CommitHarvestConversion(conversion_id=CARD_ID, variant="h2")]
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID, variant="h2"))
    assert _field_grain(state, 0, 0, 3) == 1      # (0,3) scans before (1,2)
    assert _field_grain(state, 0, 1, 2) == 2


def test_single_height_single_variant():
    state = _walk_to_p0_feed(_harvest_state(fields={(0, 1): 2}, grain=0))
    assert _brewery_actions(state) == [
        CommitHarvestConversion(conversion_id=CARD_ID, variant="h1")]


# --- Withholding boundaries ---------------------------------------------------

def test_no_planted_grain_field_not_offered():
    """Supply grain alone is not enough — the field half must exist."""
    state = _walk_to_p0_feed(_harvest_state(fields=None, grain=3))
    assert _brewery_actions(state) == []


def test_no_supply_grain_not_offered():
    """Planted fields alone are not enough — the input_cost gate withholds the
    conversion when the supply grain cannot be paid. (Direct FEED init: the
    walk's field-phase take would put grain in supply.)"""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=10, grain=0)
    state = with_resources(state, 1, food=99)
    state = _set_fields(state, 0, {(0, 1): 2})
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    assert _variants(state, 0) == ["h2"]          # the field half IS present
    assert _brewery_actions(state) == []          # but 1 supply grain is not


def test_unowned_never_offered():
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 2}, grain=2, owners=()))
    assert _brewery_actions(state) == []


def test_opponent_ownership_not_offered_to_p0():
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 2}, grain=2, owners=(1,)))
    assert _brewery_actions(state) == []


# --- Declining ---------------------------------------------------------------

def test_decline_leaves_everything_unchanged():
    """CommitConvert without firing forfeits the exchange: fields, supply
    grain, and the point bank are untouched."""
    state = _walk_to_p0_feed(_harvest_state(fields={(0, 1): 3}, grain=1, food=10))
    assert _brewery_actions(state) != []          # it was on offer
    assert CommitConvert(0, 0, 0, 0, 0) in legal_actions(state)
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.grain == 2                 # 1 + the take, unspent
    assert p.resources.food == 6                  # 10 - need 4; no +4
    assert _field_grain(state, 0, 0, 1) == 2      # post-take height, untouched
    assert p.card_state.get(CARD_ID, 0) == 0
    assert CARD_ID not in p.harvest_conversions_used
    assert Stop() in legal_actions(state)


# --- NOT a harvest (ruling 12's lexicon) ---------------------------------------

def test_not_a_harvest_grain_sieve_gets_nothing():
    """Own Grain Sieve too: firing Craft Brewery emits NO harvesting occasion,
    so the sieve neither fires nor hosts — the grain delta is exactly the
    exchange's own. (One planted field, so the FIELD-phase take is 1 grain and
    the sieve stays silent there as well.)"""
    state = _harvest_state(fields={(0, 1): 3}, grain=1, food=10)
    state = with_minors(state, 0, frozenset({CARD_ID, "grain_sieve"}))
    state = _walk_to_p0_feed(state)
    p = state.players[0]
    assert p.resources.grain == 2                 # 1 + 1 take, no sieve grant
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID, variant="h2"))
    p = state.players[0]
    assert p.resources.grain == 1                 # exactly -1: no sieve grain
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)  # no occasion host pushed
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)


# --- The Family builtins are untouched -----------------------------------------

def test_builtin_conversions_still_variantless():
    """Joinery still enumerates as the plain variant-less commit."""
    from tests.factories import with_majors
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=10, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    assert CommitHarvestConversion(conversion_id="joinery") in legal_actions(state)


# --- Scoring -------------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    assert score_fn(state, 0) == 0
    # Two fires across harvests -> 4 banked points.
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 4))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    assert score_fn(state, 0) == 4
    assert score_fn(state, 1) == 0


# --- Card-fields (rulings 45/46, 2026-07-12) ---------------------------------
# A grain-holding card-field is "a field" and may supply the field grain, as
# its own per-card variant "cf_<card_id>" (never merged into a height group).
# The card path routes through card_fields.remove_card_crop — the
# NON-TAKE-removal chokepoint — so emptying a Crop Rotation Field this way
# offers its re-sow RIGHT HERE, mid-feeding (ruling 44, 2026-07-12).

import agricola.cards.artichoke_field       # noqa: F401,E402
import agricola.cards.crop_rotation_field   # noqa: F401,E402

from agricola.actions import CommitCardChoice          # noqa: E402
from agricola.cards.card_fields import (               # noqa: E402
    card_field_stacks,
    stacks_to_store,
)
from agricola.pending import PendingCardChoice         # noqa: E402


def _own_card_field(state, idx, cid, stacks):
    """Give player `idx` card-field `cid` holding `stacks` (post-walk edit —
    the card contents are set AT the feed frame, so the field-phase take has
    not touched them)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {cid},
        card_state=stacks_to_store(p.card_state, cid, stacks),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def test_card_field_variant_offered_and_fires():
    """An artichoke_field holding 2 grain offers "cf_artichoke_field"; firing
    it debits 1 supply grain + 1 card grain, grants 4 food, banks 2 points —
    and pushes NO frame (the card kept grain: no removal reaction)."""
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 2}, grain=0, food=0))
    state = _own_card_field(state, 0, "artichoke_field", [(2, 0, 0, 0)])
    offers = _brewery_actions(state)
    assert CommitHarvestConversion(
        conversion_id=CARD_ID, variant="cf_artichoke_field") in offers

    state = step(state, CommitHarvestConversion(
        conversion_id=CARD_ID, variant="cf_artichoke_field"))
    p = state.players[0]
    assert p.resources.food == 4
    assert card_field_stacks(p, "artichoke_field") == ((1, 0, 0, 0),)
    assert _field_grain(state, 0, 0, 1) == 1      # the grid field untouched
    assert p.card_state.get(CARD_ID, 0) == 2
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)


def test_emptying_crop_rotation_field_offers_resow_mid_feed():
    """Ruling 44: Craft Brewery removing Crop Rotation Field's LAST grain is
    a non-take removal — the sow-or-decline choice surfaces at THIS instant
    (a PendingCardChoice on top of the feed frame); sowing swaps in 2 veg."""
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 2}, grain=0, food=0))
    state = _own_card_field(state, 0, "crop_rotation_field", [(1, 0, 0, 0)])
    state = add_resources(state, 0, veg=1)

    state = step(state, CommitHarvestConversion(
        conversion_id=CARD_ID, variant="cf_crop_rotation_field"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.initiated_by_id == "card:crop_rotation_field"
    assert top.options == ("sow_veg", "decline")
    # The exchange itself already applied (banked before the push).
    assert state.players[0].resources.food == 4
    assert state.players[0].card_state.get(CARD_ID, 0) == 2

    state = step(state, CommitCardChoice(0))      # sow_veg
    p = state.players[0]
    assert card_field_stacks(p, "crop_rotation_field") == ((0, 2, 0, 0),)
    assert p.resources.veg == 0                   # the sow cost the supply veg
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)


def test_emptying_crop_rotation_field_decline():
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 2}, grain=0, food=0))
    state = _own_card_field(state, 0, "crop_rotation_field", [(1, 0, 0, 0)])
    state = add_resources(state, 0, veg=1)
    state = step(state, CommitHarvestConversion(
        conversion_id=CARD_ID, variant="cf_crop_rotation_field"))
    state = step(state, CommitCardChoice(1))      # decline
    p = state.players[0]
    assert "crop_rotation_field" not in dict(p.card_state.items)  # empty card
    assert p.resources.veg == 1
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)


def test_emptying_crop_rotation_field_no_offer_without_opposite_crop():
    """No supply veg -> the re-sow is impossible, so NO choice frame appears
    (the reactor declines silently) and play stays at the feed frame."""
    state = _walk_to_p0_feed(_harvest_state(
        fields={(0, 1): 2}, grain=0, food=0))
    state = _own_card_field(state, 0, "crop_rotation_field", [(1, 0, 0, 0)])
    assert state.players[0].resources.veg == 0
    state = step(state, CommitHarvestConversion(
        conversion_id=CARD_ID, variant="cf_crop_rotation_field"))
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)
    assert "crop_rotation_field" not in dict(state.players[0].card_state.items)
