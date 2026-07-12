"""Tests for Crop Rotation Field (minor improvement, E70; Ephipparius Expansion).

Card text (verbatim): "This card is a field. Each time you remove the last
grain or vegetable from this card, you can immediately sow vegetable or grain
on this card, respectively."

A 1-stack grain/veg card-field (rulings 45/47, 2026-07-12) whose re-sow is an
UNSCOPED per-occasion optional trigger (ruling 44, 2026-07-12 — the
removal-occasion optional stretch, alongside Food Merchant): removing the
card's last grain offers sowing 1 supply veg (plants 2) onto the card, and
vice versa (1 supply grain plants 3). The harvest tests drive the REAL walk
(`_advance_until_decision` over a `Phase.HARVEST_FIELD` entry state) to the
`PendingHarvestOccasion` host; the remove-verb scoping test plays Bumper Crop
through a real `PendingPlayMinor` / `CommitPlayMinor` flow mid-WORK.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.bumper_crop  # noqa: F401  (the card-driven occasion source)
import agricola.cards.crop_rotation_field  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor, CommitSow, FireTrigger, Proceed
from agricola.cards.card_fields import (
    CARD_FIELDS,
    card_field_stacks,
    card_holds,
    stacks_to_store,
)
from agricola.cards.harvest_windows import HARVEST_OCCASION_TRIGGERS
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHarvestOccasion,
    PendingPlayMinor,
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

CARD_ID = "crop_rotation_field"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx=0):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, stacks, cid=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_entry(stacks=None, *, own=True, grain=0, veg=0, grid_grain=None):
    """A real-walk harvest: build a HARVEST_FIELD entry state (P0 the starting
    player, P0's supply set to exactly `grain`/`veg` + 20 food, the card owned
    with `stacks`, optional board grain fields per `grid_grain`
    ({(r, c): grain_amount})) and advance the walk. With the card owned and
    eligible, the walk's inline take pushes P0's PendingHarvestOccasion host
    and pauses there."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    state = with_resources(state, 0, food=20, grain=grain, veg=veg)
    if grid_grain:
        state = with_grid(state, 0, {
            cell: Cell(cell_type=CellType.FIELD, grain=n)
            for cell, n in grid_grain.items()})
    if own:
        state = _own(state, 0)
    if stacks is not None:
        state = _set_stacks(state, 0, stacks)
    return _advance_until_decision(state)


def _no_host(state):
    return not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


_FIRE = FireTrigger(card_id=CARD_ID)


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registration_facts():
    """Free, prerequisite 1 Occupation, no printed VP; a 1-stack grain/veg
    card-field; an occasion trigger is registered."""
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()          # no cost
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 1 and spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 0                # no printed VP
    assert spec.passing_left is False

    cf = CARD_FIELDS[CARD_ID]
    assert cf.stacks == 1
    assert cf.sow_amounts == (("grain", 3), ("veg", 2))

    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_TRIGGERS)


def test_on_play_is_noop():
    state = setup(0)
    assert MINORS[CARD_ID].on_play(state, 0) is state


def test_json_row_matches():
    """The catalog row (revised_minor_improvements.json) matches what the
    module implements and quotes: E70, Minor Improvement, no cost/VP,
    prerequisite 1 Occupation, verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_minor_improvements.json").read_text())
    row = next(r for r in data if r.get("name") == "Crop Rotation Field")
    assert row["type"] == "Minor Improvement"
    assert row["deck"] == "E"
    assert row["number"] == 70
    assert row["expansion"] == "Ephipparius Expansion"
    assert row["cost"] is None
    assert row["vps"] is None
    assert row["prerequisites"] == "1 Occupation"
    # Verbatim text in the docstring (whitespace-normalized: the quote is
    # line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.crop_rotation_field.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# The field itself — sow through the real enumerator, then the take
# ---------------------------------------------------------------------------

def test_sow_onto_card_and_field_take():
    """At a PendingSow frame the card's empty stack is offered for both crops;
    sowing grain plants 3 on the card and spends 1 supply grain; the
    field-phase take then harvests 1 back off it."""
    state = _own(setup(seed=7), 0)
    state = with_resources(state, 0, grain=1, veg=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert (CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "grain"),))
            in sows)
    assert (CommitSow(grain=0, veg=0, card_sows=((CARD_ID, "veg"),))
            in sows)
    nxt = step(state, CommitSow(grain=0, veg=0,
                                card_sows=((CARD_ID, "grain"),)))
    p = nxt.players[0]
    assert card_field_stacks(p, CARD_ID) == ((3, 0, 0, 0),)
    assert p.resources.grain == 0 and p.resources.veg == 1

    taken, occasion = field_take(nxt, 0)
    e = [e for e in occasion.entries if e.source == f"card:{CARD_ID}"][0]
    assert (e.crop, e.amount, e.emptied) == ("grain", 1, False)
    assert taken.players[0].resources.grain == 1
    assert card_field_stacks(taken.players[0], CARD_ID) == ((2, 0, 0, 0),)


# ---------------------------------------------------------------------------
# The re-sow trigger — both directions, off the real harvest walk
# ---------------------------------------------------------------------------

def test_last_grain_removed_offers_veg_sow():
    """The take empties the card of grain (with veg in supply): the occasion
    host offers the fire; firing spends 1 supply veg and plants 2 veg on the
    card — with no PendingSow frame (the fire IS the whole decision)."""
    state = _harvest_entry([(1, 0, 0, 0)], veg=1)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    # The take itself already happened: +1 grain to supply, the card emptied.
    assert state.players[0].resources.grain == 1
    assert card_holds(state.players[0], CARD_ID, "grain") == 0
    assert _FIRE in legal_actions(state)
    assert Proceed() in legal_actions(state)

    state = step(state, _FIRE)
    p = state.players[0]
    assert p.resources.veg == 0                      # 1 supply veg spent
    assert card_field_stacks(p, CARD_ID) == ((0, 2, 0, 0),)
    assert card_holds(p, CARD_ID, "veg") == 2
    # The granted sow is the card's own effect — no PendingSow frame appears.
    assert not any(isinstance(f, PendingSow) for f in state.pending_stack)
    # Once per occasion: only the decline remains.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_last_veg_removed_offers_grain_sow():
    """The other direction of "respectively": the take empties the card of
    veg; firing spends 1 supply grain and plants 3 grain on the card."""
    state = _harvest_entry([(0, 1, 0, 0)], grain=1)
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    assert state.players[0].resources.veg == 1       # the take's harvest
    assert _FIRE in legal_actions(state)

    state = step(state, _FIRE)
    p = state.players[0]
    assert p.resources.grain == 0                    # 1 supply grain spent
    assert card_field_stacks(p, CARD_ID) == ((3, 0, 0, 0),)


def test_decline_via_proceed_leaves_card_empty():
    state = _harvest_entry([(1, 0, 0, 0)], veg=1)
    assert isinstance(state.pending_stack[-1], PendingHarvestOccasion)
    state = step(state, Proceed())
    p = state.players[0]
    assert card_field_stacks(p, CARD_ID) == ((0, 0, 0, 0),)
    assert p.resources.veg == 1                      # nothing spent
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_not_offered_when_crop_remains_on_card():
    """A 2-grain stack loses 1 to the take — the last grain did NOT leave the
    card, so no host."""
    state = _harvest_entry([(2, 0, 0, 0)], veg=5)
    assert _no_host(state)
    assert card_holds(state.players[0], CARD_ID, "grain") == 1


def test_not_offered_when_no_empty_stack():
    """A Heresy-Teacher-shaped mixed stack (1 veg below 1 grain): the take
    removes the last GRAIN, but the stack still holds the veg — no room to
    sow, so no host."""
    state = _harvest_entry([(1, 1, 0, 0)], veg=5)
    assert _no_host(state)
    assert card_holds(state.players[0], CARD_ID, "grain") == 0
    assert card_holds(state.players[0], CARD_ID, "veg") == 1


def test_not_offered_without_opposite_crop_in_supply():
    """The last grain leaves the card but the player has no supply veg to sow
    — no host (normal sow semantics: the sow costs the supply crop)."""
    state = _harvest_entry([(1, 0, 0, 0)], veg=0)
    assert _no_host(state)
    assert card_holds(state.players[0], CARD_ID, "grain") == 0


def test_not_offered_for_board_field_removal():
    """Targets only THIS card: emptying a board grain field (the owned card
    never sown) is not a removal from the card — no host."""
    state = _harvest_entry(None, veg=5, grid_grain={(0, 1): 1})
    assert _no_host(state)
    assert state.players[0].resources.grain == 1     # the board take landed


def test_unowned_never_hosts():
    """The registration is global but ownership-gated: the same harvest
    without the card in the tableau pushes no occasion host."""
    state = _harvest_entry(None, own=False, veg=5, grid_grain={(0, 1): 1})
    assert _no_host(state)


# ---------------------------------------------------------------------------
# The "remove" verb (E-deck lexicon) — a Bumper-Crop bare take fires it too
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("bumper_crop", CARD_ID) + tuple(f"m{i}" for i in range(20)),
)


def test_fires_off_bumper_crop_bare_take():
    """"Remove" is any last-crop departure (ruling 44), so Bumper Crop's
    mid-WORK bare take (occasion source "card:bumper_crop") that empties the
    card of grain offers the veg re-sow at that removal's instant."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"bumper_crop"}),
                     minor_improvements=cs.players[cp].minor_improvements
                     | {CARD_ID})
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(
        p if i == cp else opp for i in range(2)))
    # Bumper Crop's prereq: 2 grain fields on the grid.
    cs = with_grid(cs, cp, {(0, 1): Cell(cell_type=CellType.FIELD, grain=1),
                            (0, 2): Cell(cell_type=CellType.FIELD, grain=3)})
    cs = with_resources(cs, cp, veg=1)
    cs = _set_stacks(cs, cp, [(1, 0, 0, 0)])
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp,
                         initiated_by_id="space:meeting_place_cards"),))

    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "bumper_crop"]
    assert len(plays) == 1                       # free -> one payment option
    cs = step(cs, plays[0])

    assert cs.phase == Phase.WORK                # mid-round, not a harvest
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == cp
    assert top.occasion.source == "card:bumper_crop"
    # The bare take harvested the board fields AND the card's last grain.
    assert card_holds(cs.players[cp], CARD_ID, "grain") == 0
    assert _FIRE in legal_actions(cs)

    cs = step(cs, _FIRE)
    p = cs.players[cp]
    assert p.resources.veg == 0
    assert card_field_stacks(p, CARD_ID) == ((0, 2, 0, 0),)
    assert legal_actions(cs) == [Proceed()]      # once per occasion
    cs = step(cs, Proceed())
    assert cs.phase == Phase.WORK
