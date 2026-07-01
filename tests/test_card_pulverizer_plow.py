"""Tests for Pulverizer Plow (minor improvement, D19; Dulcinaria Expansion).

Card text: "Immediately after each time you use a clay accumulation space, you can
pay 1 clay to plow 1 field. If you do, place that 1 clay on the accumulation space."

An OPTIONAL `after_action_space` FireTrigger on the ATOMIC-hosted Clay Pit space
whose apply_fn debits 1 clay, places that 1 clay back on the Clay Pit accumulation
space, and pushes a PendingPlow — gated on (1) ≥1 clay on hand, (2) a plowable cell,
and (3) once-per-use. Clay Pit is atomic, so register_action_space_hook is required to
host the after-phase. Mirrors test_card_field_watchman.py / test_card_clay_puncher.py.
"""
import agricola.cards.pulverizer_plow  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import GameState, get_space

CARD_ID = "pulverizer_plow"
_SPACE = "clay_pit"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state() -> GameState:
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_clay(state, idx, n):
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
              if g[r][c].cell_type == CellType.FIELD)


def _fill_grid_with_fields(state, idx):
    """Plow over the whole grid so no plowable cell remains (_can_plow False)."""
    g = state.players[idx].farmyard.grid
    new_rows = tuple(
        tuple(fast_replace(g[r][c], cell_type=CellType.FIELD) for c in range(5))
        for r in range(3)
    )
    fy = fast_replace(state.players[idx].farmyard, grid=new_rows)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=2)
    assert spec.min_occupations == 1
    assert CARD_ID in CARDS
    # OPTIONAL after_action_space trigger (the "immediately after" timing).
    assert any(e.card_id == CARD_ID for e in TRIGGERS["after_action_space"])
    # The atomic Clay Pit space must be claimed as a host or the event never fires.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(_SPACE, set())


# ---------------------------------------------------------------------------
# Pay 1 clay -> plow, clay placed back on the space (after-phase)
# ---------------------------------------------------------------------------

def test_pay_clay_grants_plow_and_returns_clay():
    s = _give_clay(_own_minor(_card_state(), 0, CARD_ID), 0, 2)
    fields0 = _num_fields(s, 0)
    space_clay0 = get_space(s.board, _SPACE).accumulated.clay

    s = step(s, PlaceWorker(space=_SPACE))
    host = s.pending_stack[-1]
    assert isinstance(host, PendingActionSpace)
    assert host.phase == "before"

    # Before the space resolves, no FireTrigger (it is an AFTER hook).
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Proceed() in legal_actions(s)

    # Proceed runs Clay Pit (player collects the accumulated clay), flips to after,
    # and offers the grant.
    clay_after_collect = s.players[0].resources.clay + space_clay0
    s = step(s, Proceed())
    assert s.pending_stack[-1].phase == "after"
    assert s.players[0].resources.clay == clay_after_collect
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    # Fire the grant -> pays 1 clay, pushes a free PendingPlow.
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    # The space resets to 0 on collect; the 1 paid clay is placed back on it.
    assert get_space(s.board, _SPACE).accumulated.clay == 1
    # Player paid 1 clay.
    assert s.players[0].resources.clay == clay_after_collect - 1

    s = step(s, legal_actions(s)[0])     # commit the granted plow (flips to after)
    assert _num_fields(s, 0) == fields0 + 1
    s = step(s, Stop())                  # pop PendingPlow's after-phase

    # Grant spent (once per use) -> only the host's Proceed remains.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert _num_fields(s, 0) == fields0 + 1


# ---------------------------------------------------------------------------
# Declinable (optional trigger): no clay spent, no plow
# ---------------------------------------------------------------------------

def test_grant_is_declinable():
    s = _give_clay(_own_minor(_card_state(), 0, CARD_ID), 0, 2)
    fields0 = _num_fields(s, 0)
    space_clay0 = get_space(s.board, _SPACE).accumulated.clay

    s = step(s, PlaceWorker(space=_SPACE))
    s = step(s, Proceed())               # collect clay, flip to after
    clay0 = s.players[0].resources.clay
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    # Decline the grant by exiting the after-phase host (Stop).
    assert Stop() in legal_actions(s)
    s = step(s, Stop())
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert _num_fields(s, 0) == fields0          # no plow taken
    assert s.players[0].resources.clay == clay0  # no clay paid
    # Space cleared on collect, nothing placed back.
    assert get_space(s.board, _SPACE).accumulated.clay == 0
    assert space_clay0 >= 0  # sanity


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered to a non-owner
# ---------------------------------------------------------------------------

def test_not_offered_to_non_owner():
    s = _give_clay(_card_state(), 0, 2)   # nobody owns the card
    s = step(s, PlaceWorker(space=_SPACE))
    # Non-owner -> the atomic space is not even hosted; no after-phase, no FireTrigger.
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered without clay on hand
# ---------------------------------------------------------------------------

def test_not_offered_without_clay():
    # Owns the card, but spend down to 0 clay so the pay is impossible.
    s = _own_minor(_card_state(), 0, CARD_ID)
    p = fast_replace(s.players[0], resources=fast_replace(s.players[0].resources, clay=0))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))

    s = step(s, PlaceWorker(space=_SPACE))
    s = step(s, Proceed())               # collect accumulated clay, flip to after
    # If the space had accumulated clay, the player now holds it -> may be eligible.
    # Force the zero-clay branch deterministically by clearing it post-collect.
    p = fast_replace(s.players[0], resources=fast_replace(s.players[0].resources, clay=0))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    # No grant offered -> the after-phase host exits via Stop.
    assert Stop() in legal_actions(s)


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered when no plowable cell remains
# ---------------------------------------------------------------------------

def test_not_offered_when_no_plowable_cell():
    s = _give_clay(_own_minor(_card_state(), 0, CARD_ID), 0, 2)
    s = _fill_grid_with_fields(s, 0)

    s = step(s, PlaceWorker(space=_SPACE))
    s = step(s, Proceed())               # collect, flip to after
    # The grant is gated on a plowable cell, so it is not offered.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Stop() in legal_actions(s)


# ---------------------------------------------------------------------------
# Scoping: the grant is only on Clay Pit, not other accumulation spaces
# ---------------------------------------------------------------------------

def test_not_offered_on_other_space():
    s = _give_clay(_own_minor(_card_state(), 0, CARD_ID), 0, 2)
    # Reed Bank is a different (atomic) accumulation space; Pulverizer Plow must not hook it.
    s = step(s, PlaceWorker(space="reed_bank"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
