"""Tests for Newly-Plowed Field (minor improvement, C17; Corbarius Expansion).

Card text: "When you play this card, you can immediately plow 1 field, which needs
not be adjacent to another field."

The on-play plow is an OPTIONAL grant that surfaces WIDE (user ruling 17, the
on-play optional grant declines wide): two zero-surcharge CommitPlayMinor
variants — "plow" (offered only when an empty, non-enclosed cell exists) and
"decline" (always present). The "plow" route pushes
PendingPlow(ignore_adjacency=True), which WAIVES the subsequent-field adjacency
narrowing so a non-adjacent cell becomes a legal target (adjacent cells stay
legal too — the card relaxes, never forbids). The plow is mandatory once "plow"
is chosen (the "decline" route was the take-or-leave moment).

Prerequisite "Exactly 3 Field Tiles" is grid-only (user ruling 2026-07-20; per
ruling 32 a card-field is never a field tile): exactly 3 board-grid FIELD cells.

Tests drive the real PendingPlayMinor frame through legal_actions / step, pin the
prereq boundary (2 and 4 board fields fail; a card-field does not count), the
variant-offered gate, the adjacency waiver at both the helper and engine level,
the no-op decline, and a full end-to-end play through the major_improvement space
in Cards mode.
"""
import json
from pathlib import Path

import agricola.cards.newly_plowed_field  # noqa: F401  -- registers the card
import agricola.cards.artichoke_field     # noqa: F401  -- a card-field control
import agricola.cards.social_benefits     # noqa: F401  -- ordinary-minor control

from agricola.actions import (
    ChooseSubAction,
    CommitPlayMinor,
    CommitPlow,
    PlaceWorker,
    Stop,
)
from agricola.cards.newly_plowed_field import CARD_ID
from agricola.cards.artichoke_field import CARD_ID as ARTICHOKE_FIELD
from agricola.cards.social_benefits import CARD_ID as SOCIAL_BENEFITS
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import _legal_plow_cells, legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space

from tests.factories import (
    add_resources,
    with_fields,
    with_grid,
    with_pending_stack,
    with_round,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, ARTICHOKE_FIELD, SOCIAL_BENEFITS) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Newly-Plowed Field")

# Default starting rooms sit at (1,0) and (2,0); a clustered 3-field block.
_FIELDS = ((0, 0), (0, 1), (0, 2))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(*, field_cells=_FIELDS, extra_overrides=None, hand=(CARD_ID,),
           minors=(), round_number=1):
    """A prefabricated state at a PendingPlayMinor frame for the current player,
    holding `hand`, owning `minors`, with `field_cells` plowed (plus any
    `extra_overrides` on the grid)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand),
                     minor_improvements=frozenset(minors))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_fields(state, cp, field_cells)
    if extra_overrides:
        state = with_grid(state, cp, extra_overrides)
    state = with_round(state, round_number)
    state = with_pending_stack(state, (
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state, cid=CARD_ID):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == cid]


def _variants_offered(state, cid=CARD_ID):
    return {a.variant for a in _plays(state, cid)}


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the catalog row this module encodes (cost / prereq / text verbatim)."""
    assert _ROW["cost"] is None                       # no cost
    assert _ROW["prerequisites"] == "Exactly 3 Field Tiles"
    assert _ROW["text"] == (
        "When you play this card, you can immediately plow 1 field, "
        "which needs not be adjacent to another field.")
    assert _ROW["vps"] is None
    assert _ROW["passing_left"] is None
    # The module docstring quotes the printed text verbatim (line-wrapped, so
    # compare whitespace-normalized).
    import agricola.cards.newly_plowed_field as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                        # no cost
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is not None                    # the exactly-3-fields check
    assert spec.vps == 0
    assert spec.passing_left is False
    assert CARD_ID in PLAY_MINOR_VARIANTS             # the wide on-play choice


# ---------------------------------------------------------------------------
# Prerequisite: Exactly 3 Field Tiles (grid-only; boundaries)
# ---------------------------------------------------------------------------

def test_prereq_exactly_three_boundary():
    spec = MINORS[CARD_ID]
    two, cp = _frame(field_cells=((0, 0), (0, 1)))
    assert not prereq_met(spec, two, cp)              # 2 board fields: no
    three, cp = _frame(field_cells=((0, 0), (0, 1), (0, 2)))
    assert prereq_met(spec, three, cp)               # exactly 3: yes
    four, cp = _frame(field_cells=((0, 0), (0, 1), (0, 2), (0, 3)))
    assert not prereq_met(spec, four, cp)            # 4 board fields: no


def test_prereq_card_field_does_not_count():
    spec = MINORS[CARD_ID]
    # 2 board fields + an owned card-field (Artichoke Field) → still fails: a
    # card-field is not a field TILE (ruling 32), so it does not reach the count
    # of 3.
    two_plus_card, cp = _frame(
        field_cells=((0, 0), (0, 1)), minors=(CARD_ID, ARTICHOKE_FIELD))
    from agricola.cards.card_fields import card_field_count
    assert card_field_count(two_plus_card.players[cp]) == 1   # the card-field exists
    assert not prereq_met(spec, two_plus_card, cp)            # but does not count
    # 3 board fields + an owned card-field → still passes (the card-field does not
    # push the count to 4).
    three_plus_card, cp = _frame(
        field_cells=((0, 0), (0, 1), (0, 2)), minors=(CARD_ID, ARTICHOKE_FIELD))
    assert prereq_met(spec, three_plus_card, cp)


def test_prereq_gates_the_real_frame():
    """2 board fields → not offered; exactly 3 → offered."""
    state, cp = _frame(field_cells=((0, 0), (0, 1)))
    assert CARD_ID not in playable_minors(state, cp)
    assert not _plays(state)
    state, cp = _frame(field_cells=((0, 0), (0, 1), (0, 2)))
    assert CARD_ID in playable_minors(state, cp)
    assert _plays(state)


# ---------------------------------------------------------------------------
# The wide on-play choice: "plow" (when a target exists) + always "decline"
# ---------------------------------------------------------------------------

def test_both_variants_offered_with_empty_cell():
    """With empty, non-enclosed cells available, both routes are offered."""
    state, _cp = _frame()
    assert _variants_offered(state) == {"plow", "decline"}


def test_only_decline_when_no_empty_cell():
    """No empty, non-enclosed cell → the "plow" route is withheld (no target),
    but "decline" keeps the card playable (the plow is optional)."""
    # Fill every non-field cell with ROOM so there is no empty cell, keeping
    # exactly the 3 field tiles for the prereq.
    rooms = {(r, c): Cell(cell_type=CellType.ROOM)
             for r in range(3) for c in range(5) if (r, c) not in _FIELDS}
    state, cp = _frame(extra_overrides=rooms)
    assert not _legal_plow_cells(state.players[cp], ignore_adjacency=True)
    assert prereq_met(MINORS[CARD_ID], state, cp)    # still exactly 3 fields
    assert _variants_offered(state) == {"decline"}


def test_variant_surcharges_are_zero():
    """Both routes are zero-surcharge (the plow is free, the card has no cost)."""
    state, _cp = _frame()
    for a in _plays(state):
        assert a.payment == Resources()


# ---------------------------------------------------------------------------
# The granted plow waives adjacency (non-adjacent AND adjacent both legal)
# ---------------------------------------------------------------------------

def test_helper_waiver_admits_non_adjacent_cell():
    """At the helper level: with fields at row 0, an ordinary plow excludes the
    far cell (2,4) (adjacency-required) but the adjacency-waived enumeration
    includes it — and an adjacent cell (0,3) is legal either way."""
    state, cp = _frame()
    p = state.players[cp]
    ordinary = set(_legal_plow_cells(p))
    waived = set(_legal_plow_cells(p, ignore_adjacency=True))
    assert (2, 4) not in ordinary                    # non-adjacent: not a normal target
    assert (2, 4) in waived                          # ...but legal under the waiver
    assert (0, 3) in ordinary and (0, 3) in waived   # adjacent: always legal


def test_granted_plow_offers_non_adjacent_and_adjacent():
    """Choosing "plow" pushes PendingPlow(ignore_adjacency=True); its CommitPlow
    set includes both a non-adjacent cell (2,4) and an adjacent cell (0,3)."""
    state, _cp = _frame()
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.ignore_adjacency is True
    assert top.initiated_by_id == "card:newly_plowed_field"
    cells = {(a.row, a.col) for a in legal_actions(state) if isinstance(a, CommitPlow)}
    assert (2, 4) in cells                            # non-adjacent target legal
    assert (0, 3) in cells                            # adjacent target also legal
    # The forced plow offers no Stop before a cell is committed (mandatory once chosen).
    assert not any(isinstance(a, Stop) for a in legal_actions(state))


def test_granted_plow_commits_a_non_adjacent_cell():
    """Committing the non-adjacent (2,4) plows it and flips the frame to its
    after-phase (single-shot grant)."""
    state, cp = _frame()
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    state = step(state, CommitPlow(row=2, col=4))
    assert state.players[cp].farmyard.grid[2][4].cell_type is CellType.FIELD
    assert state.pending_stack[-1].phase == "after"   # max_plows=1 → flipped


# ---------------------------------------------------------------------------
# The decline route is a no-op
# ---------------------------------------------------------------------------

def test_decline_changes_nothing_but_plays_the_card():
    state, cp = _frame()
    fields_before = sum(
        1 for r in range(3) for c in range(5)
        if state.players[cp].farmyard.grid[r][c].cell_type is CellType.FIELD)
    (decline,) = [a for a in _plays(state) if a.variant == "decline"]
    state = step(state, decline)
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements            # played (kept, not passing)
    assert CARD_ID not in p.hand_minors
    fields_after = sum(
        1 for r in range(3) for c in range(5)
        if p.farmyard.grid[r][c].cell_type is CellType.FIELD)
    assert fields_after == fields_before              # no plow happened
    # No PendingPlow was pushed by the decline route.
    assert not any(isinstance(f, PendingPlow) for f in state.pending_stack)


# ---------------------------------------------------------------------------
# End-to-end through a real engine flow (major_improvement space, Cards mode)
# ---------------------------------------------------------------------------

def test_end_to_end_via_major_improvement_space():
    """Full flow: place a worker on Major/Minor Improvement, choose play_minor,
    play with the "plow" variant, plow a NON-adjacent cell, and unwind."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    sp = fast_replace(get_space(cs.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    p = fast_replace(cs.players[cp],
                     hand_occupations=frozenset(),
                     hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_fields(cs, cp, _FIELDS)                 # exactly 3 field tiles → prereq met

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    (plow,) = [a for a in legal_actions(cs)
               if isinstance(a, CommitPlayMinor) and a.variant == "plow"]
    cs = step(cs, plow)
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    cells = {(a.row, a.col) for a in legal_actions(cs) if isinstance(a, CommitPlow)}
    assert (2, 4) in cells                            # non-adjacent target legal via waiver
    cs = step(cs, CommitPlow(row=2, col=4))
    # Unwind the nested hosts (each after-phase offers only Stop).
    while cs.pending_stack:
        stops = [a for a in legal_actions(cs) if isinstance(a, Stop)]
        assert stops, "expected a Stop to unwind the host stack"
        cs = step(cs, stops[0])

    g = cs.players[cp].farmyard.grid
    assert g[2][4].cell_type is CellType.FIELD        # the non-adjacent plow landed
    n_fields = sum(1 for r in range(3) for c in range(5)
                   if g[r][c].cell_type is CellType.FIELD)
    assert n_fields == 4                              # 3 starting + 1 plowed
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors


# ---------------------------------------------------------------------------
# The seam does not widen ordinary minors
# ---------------------------------------------------------------------------

def test_ordinary_minor_unaffected():
    """Social Benefits (no variants_fn): exactly one play, variant=None."""
    state, cp = _frame(hand=(SOCIAL_BENEFITS,))
    state = add_resources(state, cp, reed=1)          # Social Benefits costs 1 reed
    plays = _plays(state, SOCIAL_BENEFITS)
    assert len(plays) == 1
    assert plays[0].variant is None
