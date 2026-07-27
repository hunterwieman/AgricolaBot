"""The standing-worker identity ledger — `PlayerState.standing_workers` (ruling 79).

The ledger records which MINTED placement number stands at which location
((number, location) pairs, ascending; locations are board space_ids or
"card:<id>"). Pins, per the ruling's semantics:

- a CARDS-mode placement appends the just-minted number (Family appends nothing);
- returning home ANONYMIZES (the entry is dropped at the notify_worker_returned
  chokepoint; the mint counter is untouched, so the next placement mints fresh);
- an on-board relocation PRESERVES (worker_moves._move_board_worker rewrites the
  entry's location, number and order untouched);
- the returning-home reset clears the ledger with the board;
- a wish space's parent+newborn is ONE numbered entry (newborns mint nothing);
- `helpers.acting_placement_number` reads the ACTING worker's number at the
  nearest space frame — equal to the mint counter at an ordinary placement,
  the preserved (lower) number after a relocation.
"""
from __future__ import annotations

import agricola.cards  # noqa: F401  -- populate the registries

from agricola.actions import PlaceWorker
from agricola.cards.worker_moves import _move_board_worker, notify_worker_returned
from agricola.engine import _return_home_reset, step
from agricola.helpers import acting_placement_number, standing_worker_number
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_space

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))


def _cards_state(seed=11):
    s, _env = setup_env(seed, card_pool=POOL)
    s = with_current_player(s, 0)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    p1 = fast_replace(s.players[1], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    return fast_replace(s, players=(p0, p1))


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _fabricate_placed(state, idx, space_id):
    """Mirror the placement chokepoint's bookkeeping for a mid-round fixture."""
    sp_workers = list(get_space(state.board, space_id).workers)
    sp_workers[idx] += 1
    state = with_space(state, space_id, workers=tuple(sp_workers))
    p = state.players[idx]
    return _edit_player(
        state, idx,
        people_home=p.people_home - 1,
        placements_this_round=p.placements_this_round + 1,
        standing_workers=p.standing_workers
        + ((p.placements_this_round + 1, space_id),))


# --- Placement appends -------------------------------------------------------

def test_cards_placement_appends_the_minted_number():
    s = _cards_state()
    placements = [a for a in legal_actions(s)
                  if isinstance(a, PlaceWorker) and a.space == "day_laborer"]
    assert placements, "day_laborer placement not legal in the fixture"
    s = step(s, placements[0])
    p = s.players[0]
    assert p.placements_this_round == 1
    assert p.standing_workers == ((1, "day_laborer"),)
    assert standing_worker_number(p, "day_laborer") == 1


def test_family_placement_appends_nothing():
    s = setup(seed=0)
    placements = [a for a in legal_actions(s)
                  if isinstance(a, PlaceWorker) and a.space == "day_laborer"]
    s = step(s, placements[0])
    ap = 1 - s.current_player if s.pending_stack == () else s.current_player
    # Whoever placed: neither player ever has ledger entries in Family.
    assert all(p.standing_workers == () for p in s.players)
    del ap


# --- Returns anonymize -------------------------------------------------------

def test_return_drops_the_entry_and_leaves_the_counter():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "fishing")
    s = notify_worker_returned(s, 0, "fishing")
    p = s.players[0]
    assert p.standing_workers == ()
    assert p.placements_this_round == 1        # anonymized, not un-minted
    # Re-placing mints FRESH: the next append carries number 2.
    s = _fabricate_placed(s, 0, "day_laborer")
    assert s.players[0].standing_workers == ((2, "day_laborer"),)


def test_return_with_no_entry_is_a_noop():
    s = setup(seed=0)                          # Family: ledger always empty
    assert notify_worker_returned(s, 0, "fishing") is s


# --- Relocation preserves ----------------------------------------------------

def test_move_rewrites_location_and_preserves_number_and_order():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "farmland")
    s = _fabricate_placed(s, 0, "fishing")
    s = _move_board_worker(s, 0, "farmland", "forest")
    p = s.players[0]
    assert p.standing_workers == ((1, "forest"), (2, "fishing"))
    assert get_space(s.board, "farmland").workers[0] == 0
    assert get_space(s.board, "forest").workers[0] == 1


# --- The reset clears --------------------------------------------------------

def test_returning_home_reset_clears_the_ledger():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "farmland")
    s = _fabricate_placed(s, 1, "fishing")
    s = _return_home_reset(s)
    assert all(p.standing_workers == () for p in s.players)
    assert all(p.placements_this_round == 0 for p in s.players)


# --- Wish-space group: one numbered entry ------------------------------------

def test_wish_space_parent_plus_newborn_is_one_entry():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "basic_wish_for_children")
    # The newborn's marker joins the space OUTSIDE the placement chokepoint —
    # count 2, still one numbered entry (newborns mint nothing).
    s = with_space(s, "basic_wish_for_children", workers=(2, 0))
    p = s.players[0]
    assert standing_worker_number(p, "basic_wish_for_children") == 1
    assert p.standing_workers == ((1, "basic_wish_for_children"),)


# --- acting_placement_number -------------------------------------------------

def test_acting_number_equals_counter_at_an_ordinary_placement():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "day_laborer")
    s = _fabricate_placed(s, 0, "forest")
    frame = PendingActionSpace(player_idx=0, initiated_by_id="space:forest")
    s = fast_replace(s, pending_stack=(frame,))
    assert acting_placement_number(s, 0) == 2 == s.players[0].placements_this_round


def test_acting_number_reads_the_preserved_number_after_a_relocation():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "farmland")    # person 1
    s = _fabricate_placed(s, 0, "fishing")     # person 2 — counter now 2
    s = _move_board_worker(s, 0, "farmland", "forest")
    frame = PendingActionSpace(player_idx=0, initiated_by_id="space:forest")
    s = fast_replace(s, pending_stack=(frame,))
    assert acting_placement_number(s, 0) == 1          # the MOVED worker's number
    assert s.players[0].placements_this_round == 2     # ...which the counter lost


def test_acting_number_falls_back_to_the_counter_off_space_frames():
    s = _cards_state()
    s = _fabricate_placed(s, 0, "day_laborer")
    assert acting_placement_number(s, 0) == 1          # empty stack -> counter
