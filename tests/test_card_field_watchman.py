"""Tests for Field Watchman (occupation, C90; Consul Dirigens Expansion).

Card text: "Each time you use the 'Grain Seeds' action space, you can also plow
1 field."

An OPTIONAL `before_action_space` FireTrigger on the ATOMIC-hosted Grain Seeds
space whose apply_fn pushes a free PendingPlow — gated on (1) a plowable cell and
(2) once-per-use. Grain Seeds is atomic, so register_action_space_hook is required
to host the before-phase. The space's own +1-grain effect is applied by the host's
Proceed (the decline path). Mirrors test_card_cooperative_plower.py / Assistant
Tiller.
"""
import agricola.cards.field_watchman  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    CARDS,
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingPlow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import GameState

CARD_ID = "field_watchman"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state() -> GameState:
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own_occ(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
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
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in CARDS
    assert any(e.card_id == CARD_ID for e in TRIGGERS["before_action_space"])
    # The atomic Grain Seeds space must be claimed as a host or the event never fires.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("grain_seeds", set())


def test_on_play_is_noop():
    s = _card_state()
    before = s.players[0]
    after = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert after.players[0] == before


# ---------------------------------------------------------------------------
# Grants an extra plow on the Grain Seeds before-phase
# ---------------------------------------------------------------------------

def test_grants_plow_on_grain_seeds():
    s = _own_occ(_card_state(), 0, CARD_ID)
    fields0 = _num_fields(s, 0)

    s = step(s, PlaceWorker(space="grain_seeds"))
    host = s.pending_stack[-1]
    assert isinstance(host, PendingActionSpace)
    assert host.phase == "before"

    # Before-phase: the grant is offered, with the host's Proceed as the decline.
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la

    # Fire the grant -> pushes a free PendingPlow.
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    s = step(s, legal_actions(s)[0])     # commit the granted plow (flips to after)
    assert _num_fields(s, 0) == fields0 + 1
    s = step(s, Stop())                  # pop PendingPlow's after-phase

    # Grant spent (once per use) -> only the host's Proceed remains.
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la

    # Proceed applies Grain Seeds' own +1 grain and completes the space.
    grain0 = s.players[0].resources.grain
    s = step(s, Proceed())               # +1 grain, flip host to after
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert s.players[0].resources.grain == grain0 + 1
    assert _num_fields(s, 0) == fields0 + 1


# ---------------------------------------------------------------------------
# Declinable (optional trigger)
# ---------------------------------------------------------------------------

def test_grant_is_declinable():
    s = _own_occ(_card_state(), 0, CARD_ID)
    fields0 = _num_fields(s, 0)
    grain0 = s.players[0].resources.grain

    s = step(s, PlaceWorker(space="grain_seeds"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    # Decline the grant via the host's Proceed; still get the +1 grain.
    s = step(s, Proceed())
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert _num_fields(s, 0) == fields0          # no plow taken
    assert s.players[0].resources.grain == grain0 + 1


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered to a non-owner
# ---------------------------------------------------------------------------

def test_not_offered_to_non_owner():
    s = _card_state()                    # nobody owns the card
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered when no plowable cell remains
# ---------------------------------------------------------------------------

def test_not_offered_when_no_plowable_cell():
    s = _own_occ(_card_state(), 0, CARD_ID)
    s = _fill_grid_with_fields(s, 0)

    s = step(s, PlaceWorker(space="grain_seeds"))
    # The grant is gated on a plowable cell, so it is not offered.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Proceed() in legal_actions(s)


# ---------------------------------------------------------------------------
# Scoping: the grant is only on Grain Seeds, not other spaces
# ---------------------------------------------------------------------------

def test_not_offered_on_other_space():
    s = _own_occ(_card_state(), 0, CARD_ID)
    # Farmland is a different (non-atomic) plow space; Field Watchman must not hook it.
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
