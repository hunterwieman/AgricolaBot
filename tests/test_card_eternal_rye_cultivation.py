"""Tests for Eternal Rye Cultivation (minor improvement, C66; Corbarius Expansion).

Card text (verbatim): "After each harvest in which you have 2 or 3+ grain in
your supply, you get 1 food and 1 additional grain, respectively."
ERRATA (verbatim from the JSON row): 'ERRATA: last "and" should be "or"'.
Free, 0 VPs, prerequisite "1 Grain Field", kept.

Governing tier ruling (user ruling 2026-07-06): the tiers are EXCLUSIVE —
exactly 2 grain in supply -> 1 food; 3 or more grain -> 1 additional grain
INSTEAD; never both; 0-1 grain -> nothing.

The payout is a choice-free tiered AUTO on the ``after_harvest`` window (the
merged after-harvest instant, user ruling 2026-07-05), so these tests drive the
REAL harvest walk end-to-end and assert the final resource totals — the supply
read happens AT the window, i.e. after the field-phase take, after the FEED
payment (grain converted to feed the family no longer counts), and after
breeding. The window also fires after the FINAL harvest (round 14), where the
3+ tier's grain joins the supply before end-game grain scoring counts it.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

import agricola.cards.eternal_rye_cultivation  # noqa: F401  (register the card)

from agricola.actions import CommitConvert, CommitPlayMinor
from agricola.cards.eternal_rye_cultivation import _apply, _eligible
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, GameState

from tests.factories import (
    with_grid,
    with_minors,
    with_phase,
    with_resources,
    with_round,
    with_sown_fields,
)

CARD_ID = "eternal_rye_cultivation"

_JSON = pathlib.Path(__file__).resolve().parent.parent / (
    "agricola/cards/data/revised_minor_improvements.json")

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)


# --- Helpers ----------------------------------------------------------------

def _harvest_state(*, grain=0, food=10, owned=True, round_number=None) -> GameState:
    """A HARVEST_FIELD-phase state, P0 the starting player, P0 owning Eternal
    Rye Cultivation (unless owned=False) with the given supply grain/food and
    NO planted fields (so the field-phase take adds nothing and the supply
    lands at the window exactly where we put it). P1 food-rich so only P0's
    feeding is interesting. Both players: 2 adults -> the FEED payment is 4
    food."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, grain=grain)
    state = with_resources(state, 1, food=99)
    if round_number is not None:
        state = with_round(state, round_number)
    return state


def _run_harvest(state, *, pick=None, probe=None):
    """Drive the harvest walk to completion. At each decision, `pick(state,
    actions)` may choose the action (None -> take the first legal action —
    the singleton path everywhere in these states except where a pick is
    supplied). `probe(state)` is called at every decision point."""
    state = _advance_until_decision(state)
    for _ in range(200):
        if state.phase not in _HARVEST_PHASES:
            return state
        if probe is not None:
            probe(state)
        actions = legal_actions(state)
        chosen = pick(state, actions) if pick is not None else None
        state = step(state, chosen if chosen is not None else actions[0])
    raise AssertionError("harvest walk did not complete")


def _own(state, idx, grain=0, food=10):
    state = with_minors(state, idx, frozenset({CARD_ID}))
    return with_resources(state, idx, food=food, grain=grain)


# --- Registration / spec vs the JSON row ------------------------------------

def test_spec_matches_json_row():
    row = next(r for r in json.loads(_JSON.read_text())
               if r["name"] == "Eternal Rye Cultivation")
    # The verbatim text + errata the module implements.
    assert row["text"] == ("After each harvest in which you have 2 or 3+ grain "
                           "in your supply, you get 1 food and 1 additional "
                           "grain, respectively.")
    assert row["errata"] == "ERRATA: last “and” should be “or”"
    spec = MINORS[CARD_ID]
    assert row["cost"] is None and spec.cost == Cost()      # free
    assert row["vps"] is None and spec.vps == 0
    assert row["prerequisites"] == "1 Grain Field" and spec.prereq is not None
    assert spec.passing_left is False                       # kept


def test_registered_as_after_harvest_auto_not_trigger():
    """Choice-free tiered income -> an AUTO on the after_harvest window; the
    card is never an optional trigger (no decision to offer)."""
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("after_harvest", ()))
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("after_harvest", ()))
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_harvest", set())


# --- Prerequisite: "1 Grain Field" -------------------------------------------

def test_prereq_one_grain_field_boundaries():
    """At least one FIELD cell currently holding grain. Zero fields, an EMPTY
    field, and a veg field all fail; one grain field passes."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)                   # no fields at all
    empty = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD)})
    assert not prereq_met(spec, empty, 0)                   # unsown field
    veg = with_sown_fields(state, 0, veg_fields=((0, 1),))
    assert not prereq_met(spec, veg, 0)                     # veg is not grain
    one = with_sown_fields(state, 0, grain_fields=((0, 1),))
    assert prereq_met(spec, one, 0)                         # exactly one: yes
    two = with_sown_fields(state, 0, grain_fields=((0, 1), (0, 2)))
    assert prereq_met(spec, two, 0)


def _at_play_minor_frame(*, grain_fields=()):
    """A CARDS-mode state at a real PendingPlayMinor host, the current player
    holding the card in hand with the given sown grain fields."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_sown_fields(cs, cp, grain_fields=grain_fields)
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def test_prereq_gates_a_real_play():
    """At a real play-minor frame: no grain field -> the play is not offered;
    one grain field -> offered (free: exactly one payment option) and playable."""
    cs, _cp = _at_play_minor_frame(grain_fields=())
    assert not any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                   for a in legal_actions(cs))
    cs, cp = _at_play_minor_frame(grain_fields=((0, 1),))
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert len(plays) == 1                                  # free -> one option
    cs = step(cs, plays[0])
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors


# --- Eligibility / tier units -------------------------------------------------

def test_eligibility_units():
    state = _harvest_state(grain=2)
    assert _eligible(state, 0) is True
    assert _eligible(state, 1) is False                     # unowned seat
    assert _eligible(with_resources(state, 0, grain=1, food=10), 0) is False
    assert _eligible(with_resources(state, 0, grain=0, food=10), 0) is False
    assert _eligible(with_resources(state, 0, grain=3, food=10), 0) is True


def test_apply_tiers_unit():
    """Exclusive tiers (user ruling 2026-07-06): exactly 2 -> +1 food, never
    grain; 3+ -> +1 grain, never food."""
    state = _harvest_state(grain=2, food=5)
    out = _apply(state, 0)
    assert out.players[0].resources.food == 6               # +1 food
    assert out.players[0].resources.grain == 2              # NOT +1 grain
    state = _harvest_state(grain=3, food=5)
    out = _apply(state, 0)
    assert out.players[0].resources.grain == 4              # +1 grain
    assert out.players[0].resources.food == 5               # NOT +1 food
    state = _harvest_state(grain=7, food=5)
    out = _apply(state, 0)
    assert out.players[0].resources.grain == 8
    assert out.players[0].resources.food == 5


# --- The tier table through a REAL harvest walk -------------------------------
# 2 adults -> feeding pays 4 food; no planted fields, so the supply lands at
# the window exactly at the starting grain. Asserting BOTH resources in every
# tier is the never-both check.

def test_harvest_exactly_two_grain_gives_one_food():
    end = _run_harvest(_harvest_state(grain=2, food=10))
    p0 = end.players[0].resources
    assert p0.grain == 2                                    # no grain gained
    assert p0.food == 10 - 4 + 1                            # fed 4, +1 food
    # The non-owner is untouched by the window.
    assert end.players[1].resources.food == 99 - 4
    assert end.players[1].resources.grain == 0


def test_harvest_three_grain_gives_one_grain_not_food():
    end = _run_harvest(_harvest_state(grain=3, food=10))
    p0 = end.players[0].resources
    assert p0.grain == 4                                    # +1 grain
    assert p0.food == 10 - 4                                # no food gained


def test_harvest_five_grain_gives_one_grain():
    end = _run_harvest(_harvest_state(grain=5, food=10))
    p0 = end.players[0].resources
    assert p0.grain == 6
    assert p0.food == 10 - 4


def test_harvest_one_grain_gives_nothing():
    end = _run_harvest(_harvest_state(grain=1, food=10))
    p0 = end.players[0].resources
    assert p0.grain == 1
    assert p0.food == 10 - 4


def test_harvest_zero_grain_gives_nothing():
    end = _run_harvest(_harvest_state(grain=0, food=10))
    p0 = end.players[0].resources
    assert p0.grain == 0
    assert p0.food == 10 - 4


def test_payout_not_granted_before_the_after_harvest_window():
    """At P0's FEED frame the payout has not happened yet — the supply read
    and the grant live at the after_harvest window, outside the harvest."""
    seen = []

    def probe(state):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed) and top.player_idx == 0:
            seen.append((state.players[0].resources.food,
                         state.players[0].resources.grain))

    end = _run_harvest(_harvest_state(grain=3, food=10), probe=probe)
    # The frame is observed both before the payment commit (food 10) and after
    # it (food 6, the frame still hosts Stop) — at NO observation has the +1
    # grain landed, and no food was ever granted (3+ tier).
    assert seen and all(g == 3 for _, g in seen)            # not granted at FEED
    assert all(f <= 10 for f, _ in seen)                    # no +1 food either
    assert end.players[0].resources.grain == 4              # granted after


def test_supply_read_after_feeding_conversion():
    """Grain spent feeding no longer counts: P0 enters with 3 grain (the +1
    grain tier if read early) but 3 food against a 4-food bill — converting 1
    grain to feed drops the supply to 2 at the window, so the card pays the
    FOOD tier instead."""
    def pick(state, actions):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed) and top.player_idx == 0:
            for a in actions:
                if isinstance(a, CommitConvert) and a.grain == 1:
                    return a
        return None

    end = _run_harvest(_harvest_state(grain=3, food=3), pick=pick)
    p0 = end.players[0]
    assert p0.begging_markers == 0                          # bill fully paid
    assert p0.resources.grain == 2                          # 3 - 1 fed, +0
    assert p0.resources.food == 3 + 1 - 4 + 1               # exactly-2 tier: +1


def test_final_harvest_round_14_banks_grain_before_scoring():
    """The after_harvest window fires after the FINAL harvest too: the round-14
    walk ends in BEFORE_SCORING with the 3+ tier's grain already in supply,
    where the end-game grain scoring category counts it."""
    end = _run_harvest(_harvest_state(grain=5, food=10, round_number=14))
    assert end.phase == Phase.BEFORE_SCORING
    assert end.players[0].resources.grain == 6              # banked pre-scoring


def test_unowned_never_fires():
    end = _run_harvest(_harvest_state(grain=3, food=10, owned=False))
    p0 = end.players[0].resources
    assert p0.grain == 3
    assert p0.food == 10 - 4


def test_fires_for_its_owner_only():
    """P1 owning the card gets the payout off their own supply; P0 (unowned,
    same grain) gets nothing."""
    state = _harvest_state(grain=3, food=10, owned=False)
    state = _own(state, 1, grain=3, food=99)
    end = _run_harvest(state)
    assert end.players[0].resources.grain == 3              # unowned: nothing
    assert end.players[1].resources.grain == 4              # owner: +1 grain
    assert end.players[1].resources.food == 99 - 4          # and no food
