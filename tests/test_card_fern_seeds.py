import agricola.cards.fern_seeds  # noqa: F401  (registers the card)

# Card-field modules imported for their `register_card_field` side effects (the
# card-field tests own these): Field Caretaker (occupation, grain+veg field),
# Beanfield (minor, veg-only field), Wood Field (minor, wood field).
import agricola.cards.beanfield        # noqa: F401
import agricola.cards.field_caretaker  # noqa: F401
import agricola.cards.wood_field       # noqa: F401

"""Tests for Fern Seeds (minor improvement, D8; Dulcinaria; traveling).

Card text (verbatim): "You get 2 food and 1 grain, which you must sow
immediately." No cost; prereq "1 Empty and 2 Planted Fields"; traveling.

on_play grants 2 food + 1 grain then pushes a mandatory grain sow of exactly one
field (``PendingSow(required_crop="grain", max_fields=1)``). Coverage:
registration + passing; the +2 food/+1 grain grant; the forced sow offering ONLY
grain commits (veg and wood/stone card-sows excluded); completion on a board
field and on a grain-capable card field; the prereq boundaries (card-fields
counting); and the no-dead-end guard (prereq refuses when the only empty field
cannot receive grain).
"""
import json
import os

import agricola.cards

from agricola.actions import CommitPlayMinor, CommitSow, Stop
from agricola.cards.card_fields import card_holds, stacks_to_store
from agricola.cards.fern_seeds import CARD_ID
from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _play_state(*, cells=None, res=None, minors=frozenset(), occs=frozenset()):
    """A 2-player CARDS state with the current player holding Fern Seeds in hand,
    the given grid cells / resources / owned card-fields, and the opponent's hand
    cleared (so passing lands somewhere observable)."""
    cs, _env = setup_env(7, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(p, hand_minors=frozenset({CARD_ID}),
                     minor_improvements=frozenset(minors),
                     occupations=frozenset(occs))
    if res is not None:
        p = fast_replace(p, resources=res)
    if cells:
        grid = tuple(
            tuple(cells.get((r, c), p.farmyard.grid[r][c]) for c in range(5))
            for r in range(3))
        p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.passing_left is True
    assert spec.cost == Cost()          # no cost
    assert spec.vps == 0
    assert spec.prereq is not None


def test_registration_spec_matches_json():
    path = os.path.join(os.path.dirname(agricola.cards.__file__),
                        "data", "revised_minor_improvements.json")
    with open(path) as f:
        row = next(r for r in json.load(f) if r["name"] == "Fern Seeds")
    assert row["type"] == "Minor Improvement"
    assert row["deck"] == "D" and row["number"] == 8
    assert row["passing_left"] == "X"          # traveling
    # The module docstring quotes the printed text verbatim (whitespace-normalized).
    doc = " ".join(agricola.cards.fern_seeds.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# Prerequisite: "1 Empty and 2 Planted Fields" (at-least; card-fields count)
# ---------------------------------------------------------------------------

def test_prereq_board_fields_boundaries():
    spec = MINORS[CARD_ID]
    # 2 planted + 1 empty board field -> met.
    s = with_grid(setup(0), 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    assert spec.prereq(s, 0) is True
    # Only 1 planted -> fails the "2 planted" bound.
    s = with_grid(setup(0), 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    assert spec.prereq(s, 0) is False
    # 2 planted but no empty field -> fails the "1 empty" bound.
    s = with_grid(setup(0), 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
    })
    assert spec.prereq(s, 0) is False


def test_prereq_card_fields_count_as_planted():
    spec = MINORS[CARD_ID]
    # 1 planted board + 1 planted card-field (Beanfield holding 2 veg) + 1 empty
    # board field -> 2 planted, 1 empty -> met (a card-field is a field, ruling 45).
    s = with_grid(setup(0), 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    store = stacks_to_store(s.players[0].card_state, "beanfield", [(0, 2, 0, 0)])
    s = _edit(s, 0, minor_improvements=frozenset({"beanfield"}), card_state=store)
    assert spec.prereq(s, 0) is True
    # Drop the planted card-field: only 1 planted board field remains -> unmet.
    s2 = with_grid(setup(0), 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    assert spec.prereq(s2, 0) is False


# ---------------------------------------------------------------------------
# The no-dead-end guard (user ruling 2026-07-20)
# ---------------------------------------------------------------------------

def test_dead_end_guard_refuses_veg_only_empty_field():
    """Printed prereq satisfied (2 planted board fields + 1 empty veg-only
    Beanfield card-field) but no grain-sowable empty field exists -> the guard
    withholds the card, so the mandatory grain sow can never dead-end."""
    spec = MINORS[CARD_ID]
    base = {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
    }
    # Only empty field is an empty veg-only Beanfield -> guard fails.
    s = _edit(with_grid(setup(0), 0, base), 0,
              minor_improvements=frozenset({"beanfield"}))
    assert spec.prereq(s, 0) is False
    # A grain-capable empty card-field (Field Caretaker) restores playability.
    s2 = _edit(with_grid(setup(0), 0, base), 0,
               occupations=frozenset({"field_caretaker"}))
    assert spec.prereq(s2, 0) is True
    # An empty BOARD field likewise satisfies the guard (still with the empty
    # Beanfield around).
    s3 = _edit(with_grid(setup(0), 0, {**base, (0, 2): Cell(cell_type=CellType.FIELD)}),
               0, minor_improvements=frozenset({"beanfield"}))
    assert spec.prereq(s3, 0) is True


# ---------------------------------------------------------------------------
# On-play: +2 food +1 grain, forced grain sow, passing
# ---------------------------------------------------------------------------

def test_play_grants_food_grain_forced_grain_sow_and_passes():
    cs, cp = _play_state(
        cells={
            (0, 0): Cell(cell_type=CellType.FIELD, grain=3),   # planted
            (0, 1): Cell(cell_type=CellType.FIELD, veg=2),     # planted
            (0, 2): Cell(cell_type=CellType.FIELD),            # empty (grain target)
        },
        res=Resources(veg=2),   # holds veg to prove veg is NOT a legal sow
    )
    opp = 1 - cp
    assert legal_actions(cs) == [sole_play_minor(cs, CARD_ID)]
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p = cs.players[cp]
    assert p.resources.food == 2                 # +2 food
    assert p.resources.grain == 1                # +1 grain (about to be sown)
    assert p.resources.veg == 2                  # untouched
    # Traveling: left our hand/tableau, circulated to the opponent's hand.
    assert CARD_ID not in p.minor_improvements
    assert CARD_ID not in p.hand_minors
    assert CARD_ID in cs.players[opp].hand_minors

    # The mandatory grain sow is on top.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.player_idx == cp
    assert top.max_fields == 1
    assert top.required_crop == "grain"
    assert top.initiated_by_id == f"card:{CARD_ID}"

    # Only grain commits — no veg despite 2 veg in supply, no Stop (can't decline).
    acts = legal_actions(cs)
    commits = [a for a in acts if isinstance(a, CommitSow)]
    assert commits
    assert all(a.grain == 1 and a.veg == 0 and a.card_sows == () for a in commits)
    assert Stop() not in acts                     # "you must sow immediately"

    cs = step(cs, CommitSow(grain=1, veg=0))
    p = cs.players[cp]
    assert p.farmyard.grid[0][2].grain == 3       # the granted grain sown on the board
    assert p.resources.grain == 0                 # spent
    # The sow flipped to its after-phase: Stop pops it, no re-offer of a sow.
    assert Stop() in legal_actions(cs)
    assert not any(isinstance(a, CommitSow) for a in legal_actions(cs))
    cs = step(cs, Stop())                          # pop the sow
    cs = step(cs, Stop())                          # pop the play-minor host


def test_grain_capable_card_field_is_a_legal_target():
    """With no empty board field, the granted grain may be sown onto a
    grain-capable empty CARD field (Field Caretaker); veg-only (Beanfield) and
    wood (Wood Field) card-fields are excluded by the required_crop filter."""
    cs, cp = _play_state(
        cells={
            (0, 0): Cell(cell_type=CellType.FIELD, grain=3),   # planted
            (0, 1): Cell(cell_type=CellType.FIELD, veg=2),     # planted
        },
        res=Resources(),                          # only the granted grain will exist
        minors=frozenset({"beanfield", "wood_field"}),
        occs=frozenset({"field_caretaker"}),
    )
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingSow) and top.required_crop == "grain"

    commits = [a for a in legal_actions(cs) if isinstance(a, CommitSow)]
    # The only legal sow is the granted grain onto Field Caretaker's stack.
    assert commits == [CommitSow(
        grain=0, veg=0, card_sows=(("field_caretaker", "grain"),))]

    cs = step(cs, commits[0])
    p = cs.players[cp]
    assert card_holds(p, "field_caretaker", "grain") == 3   # 1 grain -> 3 on the card
    assert p.resources.grain == 0                           # spent
    cs = step(cs, Stop())                                    # pop the sow
    cs = step(cs, Stop())                                    # pop the play-minor host
