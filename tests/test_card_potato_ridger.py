"""Tests for Potato Ridger (minor improvement, A59; Artifex Expansion).

Card text (verbatim): "Each time after you harvest 1+ vegetables, if you then have
3+ vegetables in your supply, you can turn exactly 1 vegetable into 6 food. With
4+ vegetables, you must do so."
Official clarification: "'Harvest' is equivalent to the field phase, or any literal
effect of a card saying 'Harvest a [crop/vegetable].'"

TWO tiers (user ruling 2026-07-05: the must-tier is automatic, no player input):

- at post-income supply 4+ the exchange is a per-occasion AUTO — it fires
  mechanically, with no PendingHarvestOccasion frame and no FireTrigger;
- at exactly 3 it is a per-occasion OPTIONAL trigger (host up, FireTrigger +
  Proceed);
- the seam's ``autos_fired`` exclusivity keeps the 4 -> 3 auto from re-offering
  the optional tier for the same occasion ("exactly 1 vegetable"), while a later
  occasion checks afresh.

Both tiers are UNSCOPED per ruling 12 (2026-07-04) and the card's own
clarification: a real harvest's field-phase take and a card-driven field phase
(Bumper Crop, mid-WORK) both count. The harvest cases drive the REAL walk
(Phase.HARVEST_FIELD entry through `_advance_until_decision`); the card-driven
cases play Bumper Crop through a real PendingPlayMinor / CommitPlayMinor flow.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

import agricola.cards.potato_ridger  # noqa: F401  (register the card)
import agricola.cards.bumper_crop    # noqa: F401  (the card-driven occasion)

from agricola.actions import CommitPlayMinor, FireTrigger, Proceed, Stop
from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    HARVEST_OCCASION_TRIGGERS,
)
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestOccasion, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env

from tests.factories import with_phase, with_resources, with_sown_fields

CARD_ID = "potato_ridger"

_JSON = pathlib.Path(__file__).resolve().parent.parent / (
    "agricola/cards/data/revised_minor_improvements.json")


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {cid})


def _harvest_take_state(*, supply_veg, veg_fields=((0, 1),), grain_fields=(),
                        owner=True):
    """A HARVEST_FIELD-phase state advanced through the walk: P0 (the starting
    player) sown as given, holding `supply_veg` vegetables (+20 food so feeding
    stays trivial), owning Potato Ridger unless owner=False. Sown veg fields
    carry 2 veg / grain fields 3 grain (the factory), so the take removes
    exactly 1 crop per field."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=20, veg=supply_veg)
    state = with_resources(state, 1, food=20)
    state = with_sown_fields(state, 0, grain_fields=grain_fields,
                             veg_fields=veg_fields)
    if owner:
        state = _own_minor(state, 0)
    return _advance_until_decision(state)


def _assert_no_host(state):
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(state)


# --- Registration / spec (vs the JSON row) ----------------------------------

def test_json_row_is_what_we_implemented():
    """Pin the verbatim printed text + cost so catalog drift is caught."""
    row = next(r for r in json.loads(_JSON.read_text())
               if r["name"] == "Potato Ridger")
    assert row["text"] == (
        "Each time after you harvest 1+ vegetables, if you then have 3+ "
        "vegetables in your supply, you can turn exactly 1 vegetable into "
        "6 food. With 4+ vegetables, you must do so.")
    assert row["cost"] == "1 Wood"
    assert row["vps"] is None
    assert row["prerequisites"] is None
    assert row["passing_left"] is None


def test_registered_minor_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(Resources(wood=1))        # "1 Wood"
    assert spec.alt_costs == ()
    assert spec.vps == 0                               # vps: null
    assert spec.prereq is None                         # prerequisites: null
    assert spec.min_occupations == 0
    assert spec.passing_left is False                  # kept


def test_two_tier_registration():
    """One AUTO (the 4+ must-tier — fires with no player input) plus one plain
    TRIGGER (the at-3 can-tier), per the 2026-07-05 ruling."""
    autos = [e for e in HARVEST_OCCASION_AUTOS if e.card_id == CARD_ID]
    triggers = [e for e in HARVEST_OCCASION_TRIGGERS if e.card_id == CARD_ID]
    assert len(autos) == 1
    assert len(triggers) == 1
    assert triggers[0].variants_fn is None             # exactly 1 veg — no variants


# --- The real harvest take: optional at 3 -----------------------------------

def test_optional_at_exactly_three_supply_veg():
    """Take 1 veg leaving supply at exactly 3: host pushed, FireTrigger AND
    Proceed both offered (the can-tier); firing swaps 1 veg for 6 food."""
    state = _harvest_take_state(supply_veg=2)          # +1 from the take -> 3
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    assert top.autos_fired == frozenset()              # the auto did NOT fire
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Proceed() in acts                           # optional at 3
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.veg == 2         # 3 - 1
    assert state.players[0].resources.food == 26       # 20 + 6
    assert legal_actions(state) == [Proceed()]         # once per occasion
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_two_veg_fields_units_sum():
    """"you harvest 1+ vegetables" sums the occasion's veg UNITS: two veg
    fields harvest 2 units, landing supply at 1 + 2 = 3 -> eligible."""
    state = _harvest_take_state(supply_veg=1, veg_fields=((0, 1), (0, 2)))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts and Proceed() in acts


# --- The real harvest take: automatic at 4+ ----------------------------------

def test_auto_fires_at_four_supply_veg():
    """Supply at 4 after the take: the exchange happens AUTOMATICALLY — food
    +6, veg -1, with NO PendingHarvestOccasion frame and no FireTrigger ever
    offered. Specifically the 4 -> 3 case: the auto leaves supply at exactly 3
    (the can-tier's printed range), and NO optional offer appears for that
    same occasion (the seam's autos_fired exclusion)."""
    state = _harvest_take_state(supply_veg=3)          # +1 from the take -> 4
    assert state.players[0].resources.veg == 3         # 4 - 1, automatic
    assert state.players[0].resources.food == 26       # 20 + 6, automatic
    _assert_no_host(state)                             # no frame, no offer at 3


def test_auto_fires_exactly_once_per_occasion():
    """"exactly 1 vegetable": at 5 post-take supply the auto fires ONCE —
    4 veg remain (still in the must-tier's range) and exactly +6 food — and
    no optional offer follows for the same occasion."""
    state = _harvest_take_state(supply_veg=4)          # +1 from the take -> 5
    assert state.players[0].resources.veg == 4         # one exchange only
    assert state.players[0].resources.food == 26       # +6, not +12
    _assert_no_host(state)


# --- Negative cases ----------------------------------------------------------

def test_nothing_below_three_supply_veg():
    """Take 1 veg landing supply at only 2: neither tier reacts — the veg
    still arrives, no exchange, no host."""
    state = _harvest_take_state(supply_veg=1)          # +1 from the take -> 2
    _assert_no_host(state)
    assert state.players[0].resources.veg == 2
    assert state.players[0].resources.food == 20       # no exchange happened


def test_grain_only_take_not_eligible_despite_supply():
    """"each time after you harvest 1+ VEGETABLES" is the entry condition for
    BOTH tiers: a grain-only take triggers nothing, even with 5 vegetables in
    supply — 4+ supply alone never forces the auto."""
    state = _harvest_take_state(supply_veg=5, veg_fields=(),
                                grain_fields=((0, 1),))
    _assert_no_host(state)
    assert state.players[0].resources.veg == 5         # untouched
    assert state.players[0].resources.food == 20       # the auto did NOT fire


def test_unowned_never_fires():
    state = _harvest_take_state(supply_veg=3, owner=False)  # take lands at 4
    _assert_no_host(state)
    assert state.players[0].resources.veg == 4         # take landed, no exchange
    assert state.players[0].resources.food == 20


def test_opponents_take_does_not_fire_for_owner():
    """"YOU harvest": P0 owns the card; P1's veg take (landing P1 at 4 —
    would be the must-tier) fires nothing — the occasion belongs to the
    harvesting player."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=20)
    state = with_resources(state, 1, food=20, veg=3)
    state = with_sown_fields(state, 1, veg_fields=((0, 1),))
    state = _own_minor(state, 0)
    state = _advance_until_decision(state)
    _assert_no_host(state)
    assert state.players[1].resources.veg == 4         # P1's take landed
    assert state.players[1].resources.food == 20       # no auto fired for P1


# --- The card-driven occasion (Bumper Crop, mid-WORK) ------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop", CARD_ID) + tuple(f"m{i}" for i in range(20)),
)


def _at_bumper_crop_play(supply_veg):
    """A CARDS-mode WORK-phase state at a PendingPlayMinor host: the current
    player holds Bumper Crop in hand, owns Potato Ridger in the tableau, has
    2 grain fields (Bumper Crop's prereq) + 1 veg field sown, and `supply_veg`
    vegetables."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     minor_improvements=(cs.players[cp].minor_improvements
                                         | {CARD_ID}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_resources(cs, cp, veg=supply_veg)
    cs = with_sown_fields(cs, cp, grain_fields=((0, 1), (0, 2)),
                          veg_fields=((1, 0),))
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _play_bumper_crop(cs):
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1
    return step(cs, plays[0])


def test_bumper_crop_occasion_optional_mid_work():
    """UNSCOPED (ruling 12 + the card's clarification): Bumper Crop's played
    field phase (mid-WORK, source card:bumper_crop) harvests 1 veg landing
    supply at 3 — the host is pushed with the phase still WORK, and the
    exchange works."""
    cs, cp = _at_bumper_crop_play(supply_veg=2)        # +1 veg from the take -> 3
    cs = _play_bumper_crop(cs)
    assert cs.phase == Phase.WORK                      # no harvest detour
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == cp
    assert top.occasion.source == "card:bumper_crop"
    acts = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Proceed() in acts                           # optional at 3
    food0 = cs.players[cp].resources.food
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    assert cs.players[cp].resources.veg == 2
    assert cs.players[cp].resources.food == food0 + 6
    cs = step(cs, Proceed())                           # pop the host ...
    assert Stop() in legal_actions(cs)                 # ... back at the play frame


def test_bumper_crop_auto_at_four_mid_work():
    """The must-tier also binds on a card-driven occasion, and it is
    automatic there too: supply at 4 after Bumper Crop's take exchanges
    immediately — no frame, no FireTrigger, straight back to the play frame."""
    cs, cp = _at_bumper_crop_play(supply_veg=3)        # +1 veg from the take -> 4
    food0 = cs.players[cp].resources.food
    cs = _play_bumper_crop(cs)
    assert cs.phase == Phase.WORK
    assert cs.players[cp].resources.veg == 3           # 4 - 1, automatic
    assert cs.players[cp].resources.food == food0 + 6
    _assert_no_host(cs)
    assert Stop() in legal_actions(cs)                 # the play frame's exit


def test_exclusion_is_per_occasion_not_sticky():
    """A LATER occasion in the same game re-checks from scratch: after the
    auto fired on Bumper Crop's occasion (4 -> 3, no offer), a subsequent real
    harvest landing supply at exactly 3 hosts the optional tier normally."""
    cs, cp = _at_bumper_crop_play(supply_veg=3)        # occasion A: 4 -> auto
    cs = _play_bumper_crop(cs)
    assert cs.players[cp].resources.veg == 3           # the auto fired
    _assert_no_host(cs)                                # no offer for occasion A
    cs = step(cs, Stop())                              # close the play frame

    # Occasion B, same game: stage a real harvest whose take lands cp at
    # exactly 3. The fields keep their post-occasion-A crops — the veg field
    # (1, 0) holds 1 veg (2 sown, 1 taken by Bumper Crop) — so the take
    # harvests 1 veg: set supply to 2 and 2 + 1 = 3 (the can-tier, not the
    # auto).
    cs = with_resources(cs, cp, food=20, veg=2)
    cs = with_resources(cs, 1 - cp, food=20)
    cs = with_phase(cs, Phase.HARVEST_FIELD)
    cs = dataclasses.replace(cs, starting_player=cp, current_player=cp,
                             pending_stack=())
    cs = _advance_until_decision(cs)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)     # hosts afresh
    assert top.player_idx == cp
    acts = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) in acts        # offered normally
    assert Proceed() in acts
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    assert cs.players[cp].resources.veg == 2
    assert cs.players[cp].resources.food == 26
