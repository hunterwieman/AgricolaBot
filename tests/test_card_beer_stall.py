"""Tests for Beer Stall (minor improvement, C49; Corbarius Expansion).

Card text (verbatim): "In the feeding phase of each harvest, for each empty
unfenced stable you have, you can exchange 1 grain for 5 food."
Cost 1 Wood; no prereq, no VPs.

User ruling 30 (2026-07-06): options are (kept animals, k conversions TAKEN)
pairs — the kept animals must fit with k unfenced stables left empty, the
cooking bundled into the option — Pareto over animals within each k, options
across k never compared; declining is the implicit (current animals, 0).
The exchange fires in the feed frame's craft window, before the final
CommitConvert payment (the user's timing clarification), so the food pays the
same feeding.
"""
import dataclasses

import agricola.cards.beer_stall  # noqa: F401  (register the card)

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.beer_stall import CARD_ID, _options
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import setup

from tests.factories import with_phase, with_resources


def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _with_stables(state, idx, cells):
    p = state.players[idx]
    grid = tuple(
        tuple(fast_replace(cell, cell_type=CellType.STABLE)
              if (r, c) in cells else cell
              for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


def _feed_state(*, grain=3, boar=0, food=10):
    """A HARVEST_FIELD state: P0 owns Beer Stall, two unfenced stables at
    (2,3)/(2,4), the given animals/goods; P1 food-rich."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = _own(state, 0)
    state = _with_stables(state, 0, {(2, 3), (2, 4)})
    if boar:
        state = _edit_player(state, 0, animals=Animals(boar=boar))
    state = with_resources(state, 0, food=food, grain=grain)
    state = with_resources(state, 1, food=99)
    return state


def _to_p0_feed_frame(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestFeed) and top.player_idx == 0
                and not top.conversion_done):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("no P0 feed frame surfaced")


# ---------------------------------------------------------------------------
# Registration + the option set
# ---------------------------------------------------------------------------

def test_registration():
    import json
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    from agricola.cards.specs import MINORS

    assert MINORS[CARD_ID].cost == Cost(resources=Resources(wood=1))
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.variants_fn is not None
    assert spec.input_cost == Resources() and spec.food_out == 0
    row = next(r for r in json.load(
        open("agricola/cards/data/revised_minor_improvements.json"))
        if r["name"] == "Beer Stall")
    assert (row["deck"], row["number"], row["cost"]) == ("C", 49, "1 Wood")


def test_option_set_two_stables_two_boar():
    """2 unfenced stables housing 2 boar (pet free): k=1 needs one stable
    empty — the boars fit stable+pet, rearrange-only; k=2 needs both empty —
    only 1 boar fits the pet, cook the other."""
    state = _feed_state(boar=2)
    opts = {(a.sheep, a.boar, a.cattle, k) for a, k, _f in _options(state, 0)}
    assert opts == {(0, 2, 0, 1), (0, 1, 0, 2)}


def test_option_gates():
    # No grain -> no options; no unfenced stable -> no options.
    assert _options(_feed_state(grain=0, boar=0), 0) == []
    no_stables = _own(with_phase(setup(seed=0), Phase.HARVEST_FIELD), 0)
    no_stables = with_resources(no_stables, 0, grain=3)
    assert _options(no_stables, 0) == []
    # k capped by grain: 2 stables but 1 grain -> only k=1.
    assert {k for _a, k, _f in _options(_feed_state(grain=1, boar=0), 0)} == {1}


# ---------------------------------------------------------------------------
# End-to-end at the real feed frame
# ---------------------------------------------------------------------------

def test_fire_rearrange_only_and_food_pays_the_feeding():
    """Fire (2 boar kept, k=1): -1 grain +5 food with animals untouched, in
    the craft window BEFORE CommitConvert — the food covers this feeding."""
    state = _to_p0_feed_frame(_feed_state(boar=2, food=0))
    fires = [a for a in legal_actions(state)
             if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID]
    assert {a.variant for a in fires} == {"k1s0b2c0", "k2s0b1c0"}
    state = step(state, next(a for a in fires if a.variant == "k1s0b2c0"))
    p = state.players[0]
    assert p.animals == Animals(boar=2)
    assert p.resources.grain == 2 and p.resources.food == 5
    # Once per feeding: no re-offer.
    assert not any(isinstance(a, CommitHarvestConversion)
                   and a.conversion_id == CARD_ID for a in legal_actions(state))
    # The final payment sees the 5 food: 2 people owe 4 -> no begging.
    convert = next(a for a in legal_actions(state) if isinstance(a, CommitConvert))
    state = step(state, convert)
    assert state.players[0].begging_markers == 0
    assert state.players[0].resources.food == 1


def test_fire_cook_to_free_both_stables():
    """Fire (1 boar kept, k=2): the released boar cooks (rate 0 here), 2 grain
    pay, +10 food."""
    state = _to_p0_feed_frame(_feed_state(boar=2, food=0))
    fires = [a for a in legal_actions(state)
             if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID]
    state = step(state, next(a for a in fires if a.variant == "k2s0b1c0"))
    p = state.players[0]
    assert p.animals == Animals(boar=1)
    assert p.resources.grain == 1 and p.resources.food == 10


def test_decline_is_implicit():
    """Committing the payment without firing forfeits the exchange — the
    (current animals, 0 conversions) point."""
    state = _to_p0_feed_frame(_feed_state(boar=2, food=10))
    convert = next(a for a in legal_actions(state) if isinstance(a, CommitConvert))
    state = step(state, convert)
    p = state.players[0]
    assert p.animals == Animals(boar=2) and p.resources.grain == 3


def test_unowned_never_offered():
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = _with_stables(state, 0, {(2, 3), (2, 4)})
    state = with_resources(state, 0, food=10, grain=3)
    state = with_resources(state, 1, food=99)
    state = _to_p0_feed_frame(state)
    assert not any(isinstance(a, CommitHarvestConversion)
                   and a.conversion_id == CARD_ID for a in legal_actions(state))
