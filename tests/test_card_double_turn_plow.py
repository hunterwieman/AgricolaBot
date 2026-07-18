"""Tests for Double-Turn Plow (minor improvement, A20; Artifex Expansion).

Card text: "When you play this card, you can immediately plow up to 2 fields."
Clarification: "The cost is 1 extra food if played in Round 4 or 5."
Cost "1 Grain,(+1 Food)"; prereq "Play in Round 3 (5) or Before" (round <= 5).

The optional plow grant surfaces WIDE (CARD_ENGINE_IMPLEMENTATION.md §6): playing
the card offers a "plow" route (a multi-shot PendingPlow of up to 2 fields, only
when a plow target exists) and an always-present "skip" route (plow 0 fields).
User rulings 2026-07-17: the on-play "immediately" adds nothing (ruling 66), and
the player may stop after plowing 1 field (the multi-shot enumerator's Proceed at
num_plowed >= 1). Tests drive the real PendingPlayMinor -> PendingPlow flow:
registration, the state-scaling cost + round-<=5 prereq boundaries, plowing 2
fields, the user-ruled early stop after 1, declining via "skip", the "plow" route
being withheld with no plowable cell, and second-plow adjacency.
"""
import agricola.cards.double_turn_plow  # noqa: F401  -- registers the card
import agricola.cards.social_benefits  # noqa: F401  -- ordinary-minor control

import json
from pathlib import Path

from agricola.actions import CommitPlayMinor, CommitPlow, Proceed, Stop
from agricola.cards.double_turn_plow import CARD_ID, _cost
from agricola.cards.social_benefits import CARD_ID as SOCIAL_BENEFITS
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env

from tests.factories import (
    with_fields, with_pending_stack, with_resources, with_round)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, SOCIAL_BENEFITS) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Double-Turn Plow")

# Starting rooms are at (1, 0) and (2, 0); every other cell is EMPTY.
_ROOMS = {(1, 0), (2, 0)}
_EMPTY_CELLS = [(r, c) for r in range(3) for c in range(5) if (r, c) not in _ROOMS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _at_play_minor_frame(round_number=1, hand=(CARD_ID,), **res):
    """A prefabricated state at a PendingPlayMinor frame for the current player,
    holding `hand` and exactly the given resources (others zero)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_round(state, round_number)
    state = with_resources(state, cp, **res)
    state = with_pending_stack(
        state,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state, cid=CARD_ID):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == cid]


def _variants_offered(state, cid=CARD_ID):
    return {a.variant for a in _plays(state, cid)}


def _field_cells(state, idx):
    return {(r, c)
            for r in range(3) for c in range(5)
            if state.players[idx].farmyard.grid[r][c].cell_type is CellType.FIELD}


def _fill_all_empty_with_fields(state, idx):
    """Plow every EMPTY cell, so no plow target remains and `_can_plow` is False."""
    return with_fields(state, idx, _EMPTY_CELLS)


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the catalog row this module encodes (text / cost / prereq /
    clarification verbatim)."""
    assert _ROW["cost"] == "1 Grain,(+1 Food)"
    assert _ROW["prerequisites"] == "Play in Round 3 (5) or Before"
    assert _ROW["text"] == (
        "When you play this card, you can immediately plow up to 2 fields.")
    assert _ROW["clarifications"] == (
        "The cost is 1 extra food if played in Round 4 or 5.")
    assert _ROW["vps"] is None
    assert _ROW["passing_left"] is None
    # The module docstring quotes both the printed text and the clarification.
    import agricola.cards.double_turn_plow as mod
    doc = " ".join(mod.__doc__.split())
    assert _ROW["text"] in doc
    assert _ROW["clarifications"] in doc


def test_registered_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                 # cost is state-scaling (cost_fn)
    assert spec.cost_fn is not None
    assert spec.alt_costs == ()
    assert spec.min_occupations == 0           # no occupation prereq
    assert spec.max_occupations is None
    assert spec.prereq is not None             # the round-<=5 check
    assert spec.vps == 0                        # no printed VP
    assert spec.passing_left is False           # not a traveling minor
    assert CARD_ID in PLAY_MINOR_VARIANTS       # the wide plow/skip choice


# ---------------------------------------------------------------------------
# Cost boundaries (the clarification) + prereq (round <= 5)
# ---------------------------------------------------------------------------

def test_cost_scales_with_round():
    """Rounds 1-3: 1 grain. Rounds 4-5: 1 grain + 1 food (the clarification)."""
    for rnd in (1, 2, 3):
        state, cp = _at_play_minor_frame(round_number=rnd)
        assert _cost(state, cp) == Cost(resources=Resources(grain=1))
    for rnd in (4, 5):
        state, cp = _at_play_minor_frame(round_number=rnd)
        assert _cost(state, cp) == Cost(resources=Resources(grain=1, food=1))


def test_cost_boundary_shows_in_commit_payment():
    """The state-scaling cost flows through the enumerator's payment: round 3
    pays 1 grain; round 4 pays 1 grain + 1 food (food routed through the normal
    food-payment layer, given here so no shortfall frame is needed)."""
    state, _cp = _at_play_minor_frame(round_number=3, grain=1)
    (skip3,) = [a for a in _plays(state) if a.variant == "skip"]
    assert skip3.payment == Resources(grain=1)
    state, _cp = _at_play_minor_frame(round_number=4, grain=1, food=1)
    (skip4,) = [a for a in _plays(state) if a.variant == "skip"]
    assert skip4.payment == Resources(grain=1, food=1)


def test_prereq_round_boundaries():
    spec = MINORS[CARD_ID]
    for rnd in (1, 3, 5):
        state, cp = _at_play_minor_frame(round_number=rnd, grain=1, food=1)
        assert prereq_met(spec, state, cp)
    for rnd in (6, 8, 14):
        state, cp = _at_play_minor_frame(round_number=rnd, grain=1, food=1)
        assert not prereq_met(spec, state, cp)


def test_prereq_gates_the_real_frame():
    """Round 5 -> the card is offered; round 6 -> not offered at all."""
    state, cp = _at_play_minor_frame(round_number=5, grain=1, food=1)
    assert CARD_ID in playable_minors(state, cp)
    assert _plays(state)
    state, cp = _at_play_minor_frame(round_number=6, grain=1, food=1)
    assert CARD_ID not in playable_minors(state, cp)
    assert not _plays(state)


# ---------------------------------------------------------------------------
# The wide plow/skip choice
# ---------------------------------------------------------------------------

def test_both_variants_offered_when_plowable():
    """A fresh farm has plow targets, so both routes are offered, zero surcharge."""
    state, cp = _at_play_minor_frame(round_number=1, grain=1)
    assert _variants_offered(state) == {"plow", "skip"}
    for a in _plays(state):                       # zero-surcharge: payment == cost
        assert a.payment == Resources(grain=1)


def test_plow_variant_withheld_when_no_plowable_cell():
    """With every cell filled (no EMPTY), `_can_plow` is False, so only "skip"
    is offered — the card stays playable (plow 0)."""
    state, cp = _at_play_minor_frame(round_number=1, grain=1)
    state = _fill_all_empty_with_fields(state, cp)
    assert _variants_offered(state) == {"skip"}
    assert _plays(state)                          # still playable via skip


# ---------------------------------------------------------------------------
# End-to-end: plow 2, plow 1 (early stop), skip
# ---------------------------------------------------------------------------

def test_play_and_plow_two_fields():
    state, cp = _at_play_minor_frame(round_number=1, grain=1)
    before = _field_cells(state, cp)
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    # Card moved to tableau, grain paid, now at the pushed PendingPlow (before-phase).
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements and CARD_ID not in p.hand_minors
    assert p.resources.grain == 0
    assert isinstance(state.pending_stack[-1], PendingPlow)
    # First plow: CommitPlow options, NO Proceed yet (num_plowed == 0).
    acts = legal_actions(state)
    assert any(isinstance(a, CommitPlow) for a in acts)
    assert not any(isinstance(a, Proceed) for a in acts)
    (first,) = [a for a in acts if isinstance(a, CommitPlow) and (a.row, a.col) == (0, 4)]
    state = step(state, first)
    # Second plow available (budget not spent) + Proceed now offered.
    acts = legal_actions(state)
    assert any(isinstance(a, Proceed) for a in acts)
    (second,) = [a for a in acts if isinstance(a, CommitPlow) and (a.row, a.col) == (0, 3)]
    state = step(state, second)
    # Budget spent -> host flips; Stop pops it and ends the turn.
    state = step(state, Stop())
    assert _field_cells(state, cp) - before == {(0, 4), (0, 3)}


def test_play_and_plow_one_then_proceed():
    """The user-ruled early stop: plow 1 field, then Proceed (not forced to 2)."""
    state, cp = _at_play_minor_frame(round_number=1, grain=1)
    before = _field_cells(state, cp)
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    (first,) = [a for a in legal_actions(state)
                if isinstance(a, CommitPlow) and (a.row, a.col) == (0, 4)]
    state = step(state, first)
    (proceed,) = [a for a in legal_actions(state) if isinstance(a, Proceed)]
    state = step(state, proceed)
    state = step(state, Stop())
    assert _field_cells(state, cp) - before == {(0, 4)}   # exactly one field plowed


def test_play_skip_declines_the_plow():
    state, cp = _at_play_minor_frame(round_number=1, grain=1)
    before = _field_cells(state, cp)
    (skip,) = [a for a in _plays(state) if a.variant == "skip"]
    state = step(state, skip)
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements        # played
    assert p.resources.grain == 0                 # cost paid
    # No PendingPlow was pushed; the host is in its after-phase offering Stop.
    assert not any(isinstance(f, PendingPlow) for f in state.pending_stack)
    assert Stop() in legal_actions(state)
    state = step(state, Stop())
    assert _field_cells(state, cp) == before      # no field plowed


# ---------------------------------------------------------------------------
# Second-plow adjacency (no exemption on this card)
# ---------------------------------------------------------------------------

def test_second_plow_respects_adjacency():
    """After the first plow at (0, 4), the second plow's legal cells are exactly
    the empty orthogonal neighbors of (0, 4) — {(0, 3), (1, 4)} — plus the
    early-stop Proceed. Normal adjacency, no exemption."""
    state, cp = _at_play_minor_frame(round_number=1, grain=1)
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    (first,) = [a for a in legal_actions(state)
                if isinstance(a, CommitPlow) and (a.row, a.col) == (0, 4)]
    state = step(state, first)
    acts = legal_actions(state)
    second_cells = {(a.row, a.col) for a in acts if isinstance(a, CommitPlow)}
    assert second_cells == {(0, 3), (1, 4)}
    assert any(isinstance(a, Proceed) for a in acts)
