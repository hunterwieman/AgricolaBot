"""Tests for Cooperative Plower (occupation, B90; Bubulcus Expansion).

"Each time you use the 'Farmland' action space while the 'Grain Seeds' action space
is occupied, you can plow 1 additional field."

This is an optional `before_action_space` FireTrigger on the (non-atomic) Farmland
host whose apply_fn pushes a free PendingPlow — gated on (1) Grain Seeds being
occupied, (2) a plowable cell, and (3) once-per-use. Mirrors
test_cards_granted_subaction.py (Assistant Tiller).
"""
import agricola.cards.cooperative_plower  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, FireTrigger, PlaceWorker, Stop
from agricola.cards.triggers import CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "cooperative_plower"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state():
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own_occ(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _occupy_grain_seeds(state, worker_player=1):
    """Put a worker of `worker_player` on the Grain Seeds space."""
    sp = get_space(state.board, "grain_seeds")
    workers = tuple(1 if p == worker_player else 0 for p in range(2))
    sp = fast_replace(sp, workers=workers)
    return fast_replace(state, board=with_space(state.board, "grain_seeds", sp))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
              if g[r][c].cell_type == CellType.FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in CARDS
    assert any(e.card_id == CARD_ID for e in TRIGGERS["before_action_space"])


# ---------------------------------------------------------------------------
# Grants an extra plow when Grain Seeds is occupied
# ---------------------------------------------------------------------------

def test_grants_extra_plow_when_grain_seeds_occupied():
    s = _own_occ(_card_state(), 0, CARD_ID)
    s = _occupy_grain_seeds(s)
    fields0 = _num_fields(s, 0)

    s = step(s, PlaceWorker(space="farmland"))
    # Before-phase: the grant is offered alongside Farmland's own plow.
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert ChooseSubAction(name="plow") in la

    # Fire the grant -> pushes a free PendingPlow.
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    s = step(s, legal_actions(s)[0])     # commit the granted plow (flips to after)
    assert _num_fields(s, 0) == fields0 + 1
    s = step(s, Stop())                  # pop PendingPlow's after-phase

    # Grant spent (once per use) -> only Farmland's own plow remains.
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert ChooseSubAction(name="plow") in la

    # Take Farmland's own plow -> a second field.
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, legal_actions(s)[0])     # commit the space's plow
    s = step(s, Stop())                  # pop the space PendingPlow after-phase
    s = step(s, Stop())                  # pop the host frame
    assert not s.pending_stack
    assert _num_fields(s, 0) == fields0 + 2


# ---------------------------------------------------------------------------
# Declinable (optional trigger)
# ---------------------------------------------------------------------------

def test_grant_is_declinable():
    s = _own_occ(_card_state(), 0, CARD_ID)
    s = _occupy_grain_seeds(s)
    fields0 = _num_fields(s, 0)

    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    # Decline by going straight to Farmland's own plow (the only mandatory sub-action).
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, legal_actions(s)[0])     # commit the space's own plow
    s = step(s, Stop())                  # pop the space PendingPlow after-phase
    s = step(s, Stop())                  # pop the host frame
    assert not s.pending_stack
    assert _num_fields(s, 0) == fields0 + 1   # only the one printed plow, not the grant


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered when Grain Seeds is unoccupied
# ---------------------------------------------------------------------------

def test_not_offered_when_grain_seeds_empty():
    s = _own_occ(_card_state(), 0, CARD_ID)
    # grain_seeds left empty (workers == (0, 0))
    assert get_space(s.board, "grain_seeds").workers == (0, 0)

    s = step(s, PlaceWorker(space="farmland"))
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert ChooseSubAction(name="plow") in la


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered to a non-owner
# ---------------------------------------------------------------------------

def test_not_offered_to_non_owner():
    s = _card_state()                    # nobody owns the card
    s = _occupy_grain_seeds(s)
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Eligibility boundary: NOT offered when no plowable cell remains
# ---------------------------------------------------------------------------

def test_not_offered_when_no_plowable_cell():
    s = _own_occ(_card_state(), 0, CARD_ID)
    s = _occupy_grain_seeds(s)
    # Fill the entire grid with FIELD tiles so _can_plow is False.
    g = s.players[0].farmyard.grid
    new_rows = tuple(
        tuple(fast_replace(g[r][c], cell_type=CellType.FIELD) for c in range(5))
        for r in range(3)
    )
    fy = fast_replace(s.players[0].farmyard, grid=new_rows)
    p = fast_replace(s.players[0], farmyard=fy)
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))

    s = step(s, PlaceWorker(space="farmland"))
    # The grant is gated on a plowable cell, so it is not offered.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
