"""Tests for Straw Hat (minor improvement, E10; Ephipparius Expansion).

Card text (verbatim): "At the end of the work phases of rounds 3 and 6, you can
move your person from the "Farmland" action space to an unoccupied action space
and take that action, or get 1 food."

Ruling 83 pins (user, 2026-07-27):
- the 1-food branch is UNCONDITIONAL (no person on Farmland needed);
- the relocation inherits the jump-family readings — strict unoccupancy,
  destination legal per its own placement predicate, destination resolves as a
  FULL use (its card windows fire, the ordinal readers see the moved worker's
  PRESERVED number);
- Steam Machine both ways: a prior fire (`last_use_committed`) FORECLOSES the
  relocation (food only), and an un-fired Steam Machine surfaces at an
  accumulation-space destination as a new last use.

Harness: the Sundial idiom (a drained WORK state walks the round-end ladder to
the `end_of_work` window) on a CARDS-mode state (the standing-worker ledger and
the destination predicates are card-game machinery).
"""
from __future__ import annotations

import agricola.cards  # noqa: F401  -- populate the registries

import pytest

from agricola.actions import FireTrigger, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingBakeBread, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_majors, with_resources, with_space

CARD_ID = "straw_hat"

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {card_id})


def _fabricate_placed(state, idx, space_id):
    """Mirror the placement chokepoint's bookkeeping (counts + mint + ledger)."""
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


def _sh_state(*, round_number=3, owned=True, on_farmland=True, seed=11):
    """A drained round-3/6 CARDS WORK state: every worker placed, P0's first
    worker on Farmland (unless on_farmland=False), the rest spread out."""
    s, _env = setup_env(seed, card_pool=POOL)
    s = fast_replace(s, phase=Phase.WORK, round_number=round_number,
                     starting_player=0, current_player=1)
    for idx in (0, 1):
        s = _edit_player(s, idx, hand_occupations=frozenset(),
                         hand_minors=frozenset())
    if owned:
        s = _own_minor(s, 0, CARD_ID)
    if on_farmland:
        s = _fabricate_placed(s, 0, "farmland")        # person 1
    s = _fabricate_placed(s, 0, "day_laborer")         # person 2 (or 1)
    if not on_farmland:
        s = _fabricate_placed(s, 0, "grain_seeds")
    s = _fabricate_placed(s, 1, "clay_pit")
    s = _fabricate_placed(s, 1, "reed_bank")
    assert all(p.people_home == 0 for p in s.players)
    return s


def _walk_to_window(state):
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no end_of_work window (top={top!r}, phase={state.phase})")
    assert top.window_id == "end_of_work" and top.player_idx == 0
    return state


def _sh_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.vps == 0 or spec.vps is None


# --- Round gating and the unconditional food branch --------------------------

def test_no_window_outside_rounds_3_and_6():
    s = _sh_state(round_number=4)
    s = _advance_until_decision(s)
    assert not any(isinstance(f, PendingHarvestWindow) and f.window_id == "end_of_work"
                   for f in s.pending_stack)


def test_unowned_never_hosts():
    s = _sh_state(owned=False)
    s = _advance_until_decision(s)
    assert not any(isinstance(f, PendingHarvestWindow) and f.window_id == "end_of_work"
                   for f in s.pending_stack)


@pytest.mark.parametrize("rnd", [3, 6])
def test_food_offered_unconditionally_without_a_farmland_person(rnd):
    s = _walk_to_window(_sh_state(round_number=rnd, on_farmland=False))
    fires = _sh_fires(s)
    assert [f.variant for f in fires] == ["food"]       # ruling 83 item 1
    food_before = s.players[0].resources.food
    s = step(s, fires[0])
    assert s.players[0].resources.food == food_before + 1
    s = step(s, Proceed())                              # the window closes cleanly
    _advance_until_decision(s)


def test_declinable():
    s = _walk_to_window(_sh_state())
    food_before = s.players[0].resources.food
    farmland_before = get_space(s.board, "farmland").workers[0]
    s = step(s, Proceed())
    s = _advance_until_decision(s)
    assert s.players[0].resources.food == food_before
    assert farmland_before == 1                        # nothing moved


# --- The relocation branch ---------------------------------------------------

def test_relocation_variants_are_strictly_unoccupied_and_legal():
    s = _walk_to_window(_sh_state())
    variants = {f.variant for f in _sh_fires(s)}
    assert "food" in variants
    assert "forest" in variants                        # unoccupied, goods present
    assert "clay_pit" not in variants                  # occupied by P1
    assert "day_laborer" not in variants               # occupied by P0 themselves
    assert "farmland" not in variants                  # the mover stands on it


def test_relocate_and_take_collects_and_preserves_the_number():
    s = _walk_to_window(_sh_state())
    wood_on_forest = get_space(s.board, "forest").accumulated.wood
    assert wood_on_forest > 0
    wood_before = s.players[0].resources.wood

    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest"))
    # The destination resolves as a full use above the window host; drive it out
    # (prefer the window's Proceed / a host's Stop over anything exotic).
    for _ in range(12):
        top = s.pending_stack[-1] if s.pending_stack else None
        if isinstance(top, PendingHarvestWindow):
            break
        acts = legal_actions(s)
        nxt = next((a for a in acts if isinstance(a, (Proceed, Stop))), acts[0])
        s = step(s, nxt)

    p = s.players[0]
    assert p.resources.wood == wood_before + wood_on_forest
    assert get_space(s.board, "farmland").workers[0] == 0   # vacated
    assert get_space(s.board, "forest").workers[0] == 1     # arrived
    assert (1, "forest") in p.standing_workers              # number PRESERVED
    assert p.placements_this_round == 2                     # nothing minted
    assert not _sh_fires(s)                                 # once per window

    s = step(s, Proceed())                                  # close the window
    s = _advance_until_decision(s)
    assert all(pl.standing_workers == () for pl in s.players)  # reset cleared


def test_foreclosed_by_a_committed_last_use():
    s = _sh_state()
    s = _edit_player(s, 0, last_use_committed=True)        # Steam Machine fired
    s = _walk_to_window(s)
    assert [f.variant for f in _sh_fires(s)] == ["food"]   # ruling 83 item 3


# --- Steam Machine reopens at an accumulation destination --------------------

def test_steam_machine_offered_after_relocating_onto_an_accumulation_space():
    s = _sh_state()
    s = _own_minor(s, 0, "steam_machine")
    s = with_majors(s, owner_by_idx={0: 0})                # a Fireplace: can bake
    s = with_resources(s, 0, grain=1)
    s = _walk_to_window(s)

    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest"))
    # Steam Machine hooks the atomic accumulation spaces, so the destination is
    # HOSTED: before-phase -> Proceed applies the take -> after-phase surfaces
    # the Steam Machine trigger (people_home == 0, latch unset, can bake).
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.space_id == "forest"
    s = step(s, Proceed())
    fires = [a for a in legal_actions(s)
             if isinstance(a, FireTrigger) and a.card_id == "steam_machine"]
    assert fires, "Steam Machine not offered at the relocated last use"

    s = step(s, fires[0])
    assert s.players[0].last_use_committed                 # the fire commits
    assert isinstance(s.pending_stack[-1], PendingBakeBread)


def test_steam_machine_not_reoffered_when_already_committed():
    s = _sh_state()
    s = _own_minor(s, 0, "steam_machine")
    s = with_majors(s, owner_by_idx={0: 0})
    s = with_resources(s, 0, grain=1)
    s = _edit_player(s, 0, last_use_committed=True)
    s = _walk_to_window(s)
    # Foreclosed: no relocation at all, so no second "last use" can arise.
    assert [f.variant for f in _sh_fires(s)] == ["food"]


# --- Card-space destinations (ruling 86 item 5) ------------------------------

def test_tree_inspector_card_space_is_a_destination():
    """An owned, stocked, un-occupied card space is a relocation destination;
    the use resolves hosted (Proceed takes the stack), the ledger entry follows
    the person, and the card is occupied for the round."""
    s = _sh_state()
    p = s.players[0]
    s = _edit_player(s, 0, occupations=p.occupations | {"tree_inspector"},
                     card_state=p.card_state.set("tree_inspector", 3))
    s = _walk_to_window(s)
    assert any(f.variant == "card:tree_inspector" for f in _sh_fires(s))

    wood_before = s.players[0].resources.wood
    s = step(s, FireTrigger(card_id=CARD_ID, variant="card:tree_inspector"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace)
    assert top.space_id == "card:tree_inspector"
    s = step(s, Proceed())
    p = s.players[0]
    assert p.resources.wood == wood_before + 3         # the whole stack taken
    assert (1, "card:tree_inspector") in p.standing_workers   # number preserved
    assert get_space(s.board, "farmland").workers[0] == 0     # vacated
    from agricola.cards.card_spaces import card_space_occupied
    assert card_space_occupied(s, "tree_inspector")
    s = step(s, Stop())
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)


def test_collector_card_space_offers_wide_picks_destinations():
    """A picks-bearing card space surfaces one FireTrigger per goods
    combination (mirroring its own placements); firing one resolves the full
    Collector use for the mover."""
    s = _sh_state()
    p = s.players[0]
    s = _edit_player(s, 0, occupations=p.occupations | {"collector"})
    s = _walk_to_window(s)
    coll = [f for f in _sh_fires(s) if f.variant == "card:collector"]
    assert len(coll) == 210                    # C(10, 6) — one fire per combo

    target = ("wood", "clay", "reed", "stone", "grain", "veg")
    fire = next(f for f in coll if f.picks == target)
    res_before = s.players[0].resources
    s = step(s, fire)
    s = step(s, Proceed())
    p = s.players[0]
    assert p.resources.wood == res_before.wood + 1
    assert p.resources.veg == res_before.veg + 1
    assert p.begging_markers == 1              # part of the action
    assert p.card_state.get("collector") == 1  # the use counter advanced
    assert (1, "card:collector") in p.standing_workers


def test_occupied_card_space_not_a_destination():
    s = _sh_state()
    p = s.players[0]
    s = _edit_player(s, 0, occupations=p.occupations | {"tree_inspector"},
                     card_state=(p.card_state.set("tree_inspector", 2)
                                 .set("card_space_worker:tree_inspector", 1)))
    s = _walk_to_window(s)
    assert not any(f.variant == "card:tree_inspector" for f in _sh_fires(s))


# --- The ordinal divergence pin (ruling 79 item 4) ---------------------------

def test_catcher_reads_the_moved_workers_preserved_number():
    """Person 1 stands on Farmland, person 2 placed after (counter == 2). The
    end-of-work move onto a Catcher space with exactly 5 building resources is
    "placing your 1st person" — Catcher must fire on the PRESERVED number 1
    (required pile 5), not the counter 2 (required pile 4)."""
    s = _sh_state()
    p = s.players[0]
    s = _edit_player(s, 0, occupations=p.occupations | {"catcher"})
    s = with_space(s, "forest", accumulated=Resources(wood=5))
    s = _walk_to_window(s)
    food_before = s.players[0].resources.food

    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest"))
    # Catcher's +1 food is a before_action_space AUTO at the hosted destination.
    assert s.players[0].resources.food == food_before + 1
