import agricola.cards.field_doctor  # noqa: F401

"""Tests for Field Doctor (occupation E92):

  - the ruled geometry ("surrounded by 4 field tiles" = ALL on-board orth+diag
    neighbors of the exactly-2 ROOM cells are FIELD tiles);
  - the LEGALITY RELAXATION: with the condition held and rooms == people, the
    room-gated Basic Wish placement becomes legal and the growth commits
    (Family atomic flow AND the cards-mode Proceed-host parent flow);
  - the "once this game" latch: consumed exactly when a wish growth commits
    WITHOUT a spare room (a spare-room growth does not consume; Urgent Wish —
    never room-gated — does not consume);
  - boundaries: no ownership / broken geometry / hand-only -> gate unchanged.
"""
import dataclasses

from agricola.actions import (
    ChooseSubAction,
    CommitFamilyGrowth,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.field_doctor import (
    CARD_ID,
    _growth_room_override,
    _house_surrounded_by_fields,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import (
    GROWTH_ROOM_OVERRIDE_EXTENSIONS,
    legal_actions,
    legal_placements,
)
from agricola.setup import CardPool, setup_env
from agricola.state import Cell

import tests.factories as f

BASIC = "basic_wish_for_children"
URGENT = "urgent_wish_for_children"

# The starting 2-room domino sits at (1,0)/(2,0); its on-board orth+diag
# neighbors (excluding the rooms) are exactly these 4 cells.
SURROUND = ((0, 0), (0, 1), (1, 1), (2, 1))


def _own_occ(cs, idx):
    p = cs.players[idx]
    new_p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        cs, players=tuple(new_p if i == idx else cs.players[i] for i in range(2)))


def _with_fields(cs, idx, cells, *, sown_first=False):
    overrides = {}
    for k, (r, c) in enumerate(cells):
        grain = 2 if (sown_first and k == 0) else 0
        overrides[(r, c)] = Cell(cell_type=CellType.FIELD, grain=grain)
    return f.with_grid(cs, idx, overrides)


def _family_state(seed=5, *, owner=True, fields=SURROUND, space=BASIC):
    """Family state, p0 to move, the wish space revealed. Starting farm:
    2 rooms, 2 people -> the Basic Wish room gate FAILS (rooms == people)."""
    cs, _env = setup_env(seed)
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, space, revealed=True)
    cs = _with_fields(cs, 0, fields)
    if owner:
        cs = _own_occ(cs, 0)
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # Subset check, never exact-set: our (card_id, fn) pair is in the registry.
    assert CARD_ID in {cid for cid, _fn in GROWTH_ROOM_OVERRIDE_EXTENSIONS}


# ---------------------------------------------------------------------------
# The ruled geometry
# ---------------------------------------------------------------------------

def test_geometry_holds_with_all_four_fields():
    cs = _family_state()
    assert _house_surrounded_by_fields(cs.players[0])
    assert _growth_room_override(cs, 0)


def test_sown_fields_still_count_as_field_tiles():
    cs = _family_state(fields=SURROUND)
    cs = _with_fields(cs, 0, SURROUND, sown_first=True)
    assert _house_surrounded_by_fields(cs.players[0])


def test_geometry_fails_with_three_fields_one_empty():
    cs = _family_state(fields=SURROUND[:3])   # (2,1) stays EMPTY
    assert not _house_surrounded_by_fields(cs.players[0])
    assert not _growth_room_override(cs, 0)


def test_geometry_fails_with_three_room_house():
    cs = _family_state()
    # A 3rd room breaks "exactly 2 rooms" (regardless of what surrounds it).
    cs = f.with_grid(cs, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    assert not _house_surrounded_by_fields(cs.players[0])
    assert not _growth_room_override(cs, 0)


# ---------------------------------------------------------------------------
# The relaxation + the real Family flow (Basic Wish is atomic there)
# ---------------------------------------------------------------------------

def test_placement_becomes_legal_without_spare_room():
    cs = _family_state(owner=True)
    assert cs.players[0].people_total == 2   # rooms == people: the normal gate fails
    assert PlaceWorker(space=BASIC) in legal_placements(cs)


def test_without_the_card_the_gate_is_unchanged():
    cs = _family_state(owner=False)
    assert PlaceWorker(space=BASIC) not in legal_placements(cs)


def test_broken_geometry_leaves_the_gate_unchanged():
    cs = _family_state(owner=True, fields=SURROUND[:3])
    assert PlaceWorker(space=BASIC) not in legal_placements(cs)


def test_growth_commits_and_consumes_the_latch():
    cs = _family_state(owner=True)
    cs = step(cs, PlaceWorker(space=BASIC))
    p = cs.players[0]
    assert p.people_total == 3
    assert p.newborns == 1
    assert CARD_ID in p.fired_once            # the once-per-game use is spent
    assert not _growth_room_override(cs, 0)   # ... so the override is dead


def test_second_under_room_use_is_illegal():
    cs = _family_state(owner=True)
    cs = step(cs, PlaceWorker(space=BASIC))
    # Re-stage: same player to move, the wish space free again. 3 people,
    # 2 rooms -> the room gate fails and the spent latch no longer waives it.
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, BASIC, workers=(0, 0))
    assert PlaceWorker(space=BASIC) not in legal_placements(cs)


def test_spare_room_growth_does_not_consume_the_latch():
    # 1 person, 2 rooms: the normal gate passes, so the card's permission is
    # not used — the latch must survive the growth.
    cs = _family_state(owner=True)
    cs = f.with_people(cs, 0, total=1, home=1)
    assert PlaceWorker(space=BASIC) in legal_placements(cs)
    cs = step(cs, PlaceWorker(space=BASIC))
    p = cs.players[0]
    assert p.people_total == 2
    assert CARD_ID not in p.fired_once
    assert _growth_room_override(cs, 0)       # still live


def test_urgent_wish_does_not_consume_the_latch():
    # Urgent Wish has no room gate — using it is never using the card.
    cs = _family_state(owner=True, space=URGENT)
    cs = step(cs, PlaceWorker(space=URGENT))
    p = cs.players[0]
    assert p.people_total == 3
    assert CARD_ID not in p.fired_once
    assert _growth_room_override(cs, 0)


# ---------------------------------------------------------------------------
# Cards mode — the Proceed-host Basic Wish parent
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cards_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    cs = f.with_space(cs, BASIC, revealed=True, workers=(0, 0))
    cs = _with_fields(cs, cp, SURROUND)
    # Empty hands (no minor option after the growth) + played Field Doctor.
    for i in range(2):
        p = dataclasses.replace(
            cs.players[i], hand_minors=frozenset(), hand_occupations=frozenset())
        cs = dataclasses.replace(
            cs, players=tuple(p if j == i else cs.players[j] for j in range(2)))
    cs = _own_occ(cs, cp)
    return cs, cp


def test_cards_mode_parent_flow_commits_and_consumes():
    cs, cp = _cards_state()
    assert cs.players[cp].people_total == 2   # rooms == people: gate fails
    assert PlaceWorker(space=BASIC) in legal_placements(cs)
    cs = step(cs, PlaceWorker(space=BASIC))
    assert legal_actions(cs) == [ChooseSubAction(name="family_growth")]
    cs = step(cs, ChooseSubAction(name="family_growth"))
    assert legal_actions(cs) == [CommitFamilyGrowth()]
    cs = step(cs, CommitFamilyGrowth())
    p = cs.players[cp]
    assert p.people_total == 3
    assert CARD_ID in p.fired_once            # consumed at the growth commit
    cs = step(cs, Stop())                     # pop PendingFamilyGrowth after-phase
    assert Proceed() in legal_actions(cs)     # no minors in hand -> just Proceed
    cs = step(cs, Proceed())
    cs = step(cs, Stop())                     # pop the parent's after-phase
    assert not cs.pending_stack


def test_hand_only_is_inert():
    cs, cp = _cards_state()
    # Move the card from played occupations back to the HAND.
    p = cs.players[cp]
    p = dataclasses.replace(
        p,
        occupations=p.occupations - {CARD_ID},
        hand_occupations=p.hand_occupations | {CARD_ID},
    )
    cs = dataclasses.replace(
        cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    assert not _growth_room_override(cs, cp)
    assert PlaceWorker(space=BASIC) not in legal_placements(cs)
