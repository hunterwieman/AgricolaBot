"""Tests for Steam Machine (minor improvement, C25; Consul Dirigens Expansion).

Card text: "Each work phase, if the last action space you use is an accumulation
space, you can immediately afterward take a 'Bake Bread' action."
Cost: 2 Wood. No prerequisite. VPs: 1. Not passing.

Shape: an OPTIONAL `after_action_space` FireTrigger that grants a Bake Bread action,
gated on BOTH (a) this being the player's LAST worker placement of the work phase
(`people_home == 0` at the after-phase) and (b) the space being a goods-accumulating
space — the 6 atomic building/food spaces (atomic-hosted via the card's hook) plus the
3 animal markets (non-atomic, self-hosting). `meeting_place` is in
`constants.ACCUMULATION_SPACES` but is EXCLUDED here: in the card game it gives no goods,
so it is not functioning as an accumulation space. Firing pushes the PendingBakeBread
primitive; declining is not firing (the host's Stop exits without baking).
"""
from __future__ import annotations

import agricola.cards.steam_machine  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitBake,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingBakeBread
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import (
    with_majors,
    with_minors,
    with_people,
    with_resources,
)

CARD_ID = "steam_machine"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(seed=7, *, home0=1, can_bake=True):
    """A card-mode state where P0 owns Steam Machine, has `home0` workers at home
    (so home0 placements remain), and — when `can_bake` — owns a Fireplace + grain so
    `_can_bake_bread` is true. P1 is given 2 home workers so the work phase does not
    end when P0 places its last worker."""
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    s = with_minors(s, 0, frozenset({CARD_ID}))
    if can_bake:
        s = with_majors(s, owner_by_idx={0: 0})        # Fireplace (index 0)
        s = with_resources(s, 0, grain=2, wood=0, food=0)
    else:
        s = with_resources(s, 0, grain=0, wood=0, food=0)
    s = with_people(s, 0, total=2, home=home0)
    s = with_people(s, 1, total=2, home=2)
    return s, 0


def _reveal_empty(state, space_id, **extra):
    sp = fast_replace(get_space(state.board, space_id),
                      revealed=True, workers=(0, 0), **extra)
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _place_atomic_to_after(state, space_id):
    """Place P0 on an atomic accumulation space and Proceed past its pickup so its
    host frame is in the after-phase (where this trigger is surfaced)."""
    state = _reveal_empty(state, space_id)
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                     # pickup, flip to after-phase
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_steam_machine_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.prereq is None
    assert spec.vps == 1
    assert not spec.passing_left
    # Optional after_action_space trigger.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    # Hosts ONLY the 6 atomic accumulation spaces; the 3 markets self-host.
    expected_hooked = {
        "forest", "clay_pit", "reed_bank",
        "western_quarry", "eastern_quarry", "fishing",
    }
    for sp in expected_hooked:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(sp, set()), sp
    # Markets are NOT hooked (they self-host).
    for sp in ("sheep_market", "pig_market", "cattle_market"):
        assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get(sp, set()), sp
    # meeting_place is NOT hooked (no goods in the card game → not an accumulation space).
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("meeting_place", set())


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_offered_on_last_placement_atomic_accumulation():
    s, cp = _base_state(home0=1)               # this placement is the last (home -> 0)
    s = _place_atomic_to_after(s, "forest")
    assert s.players[cp].people_home == 0      # last placement signal
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_fire_grants_bake_bread():
    s, cp = _base_state(home0=1)
    s = _place_atomic_to_after(s, "forest")
    grain0 = s.players[cp].resources.grain
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The granted, optional Bake Bread primitive is now on the stack.
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    assert bakes
    s = step(s, bakes[-1])                      # bake all grain
    # Fireplace bakes grain at 2 food / grain.
    assert s.players[cp].resources.grain == 0
    assert s.players[cp].resources.food == grain0 * 2
    # The bake leaf flips to its after-phase (only Stop remains).
    assert legal_actions(s) == [Stop()]


def test_offered_on_market_last_placement():
    # The 3 animal markets are accumulation spaces too; they self-host (non-atomic)
    # and still surface the after_action_space trigger — no hook needed.
    from agricola.actions import CommitAccommodate

    s, cp = _base_state(home0=1)
    s = _reveal_empty(s, "sheep_market", accumulated_amount=2)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.pending_stack[-1].phase == "before"
    acc = [a for a in legal_actions(s) if isinstance(a, CommitAccommodate)]
    s = step(s, acc[0])                         # flip the market host to after-phase
    assert s.pending_stack[-1].phase == "after"
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_not_last_placement():
    # Two workers at home → after placing one, people_home == 1 (not the last).
    s, cp = _base_state(home0=2)
    s = _place_atomic_to_after(s, "forest")
    assert s.players[cp].people_home == 1
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert legal_actions(s) == [Stop()]        # the host exits with no bake granted


def test_not_offered_on_meeting_place():
    # meeting_place is in constants.ACCUMULATION_SPACES but gives no goods in the card
    # game, so it is NOT an accumulation space for Steam Machine.
    s, cp = _base_state(home0=1)
    s = _reveal_empty(s, "meeting_place")
    s = step(s, PlaceWorker(space="meeting_place"))
    s = step(s, Proceed())                      # become SP, decline minor, flip to after
    assert s.pending_stack[-1].phase == "after"
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_when_cannot_bake():
    # Last placement on an accumulation space, but no baker / no grain → the grant
    # would be a dead-end, so it is not offered.
    s, cp = _base_state(home0=1, can_bake=False)
    s = _place_atomic_to_after(s, "forest")
    assert s.players[cp].people_home == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_card():
    # Without owning the card, the atomic space is not hosted → resolves immediately,
    # no host frame, no trigger anywhere.
    s, cp = _base_state(home0=1)
    s = with_minors(s, cp, frozenset())         # un-own the card
    s = _reveal_empty(s, "forest")
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                   # resolved atomically


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _base_state(home0=1)
    food0 = s.players[cp].resources.food
    grain0 = s.players[cp].resources.grain
    s = _place_atomic_to_after(s, "forest")
    la = legal_actions(s)
    # Both firing AND declining (the host's Stop) are available — optionality lives at
    # the FireTrigger.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                          # decline → host exits, work done
    assert not s.pending_stack
    # No bread baked: grain/food unchanged (Forest gave wood only).
    assert s.players[cp].resources.grain == grain0
    assert s.players[cp].resources.food == food0


# ---------------------------------------------------------------------------
# Scoping — once per use, and not on a non-accumulation atomic space
# ---------------------------------------------------------------------------

def test_fires_once_per_use():
    s, cp = _base_state(home0=1)
    s = _place_atomic_to_after(s, "forest")
    s = step(s, FireTrigger(card_id=CARD_ID))
    bakes = [a for a in legal_actions(s) if isinstance(a, CommitBake)]
    s = step(s, bakes[0])                        # bake
    s = step(s, Stop())                          # pop PendingBakeBread (after-phase)
    # Back at the Forest host's after-phase; already fired → not re-offered.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_on_non_accumulation_space():
    # grain_seeds is an atomic space but NOT an accumulation space → not hooked, so it
    # resolves atomically (no host) and never offers the trigger.
    s, cp = _base_state(home0=1)
    s = _reveal_empty(s, "grain_seeds")
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not s.pending_stack                   # not hosted → atomic resolution
