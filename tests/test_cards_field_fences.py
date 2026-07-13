"""Field Fences (minor C16): grants a Build Fences action whose new edges NEXT TO A FIELD
tile cost no wood, scoped to that grant (COST_MODIFIER_DESIGN.md §9).

Geometry used throughout: a fresh 1x1 pasture at (0,3) has 4 new edges; with a FIELD plowed
at (0,2), its LEFT vertical edge borders that field, so under a Field-Fences-initiated build
it costs 3 wood (4 - 1 field-adjacent), but 4 wood under any other build (the discount is
gated on the frame's provenance).
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.field_fences import CARD_ID, FRAME_ID
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildFences, PendingGrantedSubAction, push
from agricola.replace import fast_replace

from tests.factories import with_fields, with_resources
from tests.test_fencing import _fencing_setup

_1x1_03 = frozenset({(0, 3)})       # left edge borders a field at (0,2)
_FIELD_02 = [(0, 2)]


def _own(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _cards_fencing(*, wood, field=True, own=True):
    """CARDS-mode fencing state, optionally with a field at (0,2) and owning Field Fences."""
    state = fast_replace(_fencing_setup(wood=wood), mode=GameMode.CARDS)
    if field:
        state = with_fields(state, 0, _FIELD_02)
    if own:
        state = _own(state, 0, CARD_ID)
    return state


def _grant_frame(state, initiated_by_id=FRAME_ID):
    """Push a Build Fences host with the given provenance (no scalar budget)."""
    return push(state, PendingBuildFences(player_idx=0, initiated_by_id=initiated_by_id))


def _wood(state, idx=0):
    return state.players[idx].resources.wood


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.specs import MINORS
    from agricola.resources import Resources
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost.resources == Resources(food=2)


# ---------------------------------------------------------------------------
# The positional discount, scoped to the grant
# ---------------------------------------------------------------------------

def test_field_adjacent_edge_free_under_grant():
    state = _grant_frame(_cards_fencing(wood=20))
    assert state.pending_stack[-1].initiated_by_id == FRAME_ID
    state = step(state, CommitBuildPasture(cells=_1x1_03))
    # 4 edges; the left edge borders the field at (0,2) -> 1 free -> accrued 3.
    assert state.pending_stack[-1].accrued_cost.wood == 3
    state = step(state, Proceed())                 # singleton settle pays 3
    assert _wood(state) == 17


def test_discount_scoped_to_field_fences_provenance():
    # Same owner + field, but a FENCING-space build (initiated_by_id "fencing") gets NO
    # discount — the edge fn is gated on initiated_by_id == "card:field_fences".
    state = _cards_fencing(wood=20)
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    assert state.pending_stack[-1].initiated_by_id == "fencing"
    state = step(state, CommitBuildPasture(cells=_1x1_03))
    assert state.pending_stack[-1].accrued_cost.wood == 4   # full price, wrong provenance


def test_no_discount_without_a_field():
    # Field Fences grant but NO field on the board -> nothing is field-adjacent -> full price.
    state = _grant_frame(_cards_fencing(wood=20, field=False))
    state = step(state, CommitBuildPasture(cells=_1x1_03))
    assert state.pending_stack[-1].accrued_cost.wood == 4


# ---------------------------------------------------------------------------
# The grant's legal set is possibly LARGER (the user's point)
# ---------------------------------------------------------------------------

def test_grant_legal_set_larger_than_normal_build():
    # 3 wood: the field-adjacent 1x1 costs 4 normally but 3 under the grant, so it is OFFERED
    # during the Field Fences grant and NOT in a normal Fencing build at the same wood.
    grant = _grant_frame(_cards_fencing(wood=3))
    grant_commits = {a.cells for a in legal_actions(grant)
                     if isinstance(a, CommitBuildPasture)}
    assert _1x1_03 in grant_commits, "field-adjacent 1x1 affordable at 3 wood under the grant"

    normal = _cards_fencing(wood=3)
    normal = step(normal, PlaceWorker(space="fencing"))
    normal = step(normal, ChooseSubAction(name="build_fences"))
    normal_commits = {a.cells for a in legal_actions(normal)
                      if isinstance(a, CommitBuildPasture)}
    assert _1x1_03 not in normal_commits, "same 1x1 needs the full 4 wood without the grant"


# ---------------------------------------------------------------------------
# Integration: playing the card grants the action (forfeit when nothing is buildable)
# ---------------------------------------------------------------------------

def _play_field_fences_via_improvement(state, cp):
    from agricola.state import get_space, with_space
    from tests.test_utils import sole_play_minor
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    state = fast_replace(state, board=with_space(state.board, "major_improvement", sp))
    p = fast_replace(state.players[cp], hand_minors=state.players[cp].hand_minors | {CARD_ID})
    state = fast_replace(state, players=tuple(
        p if i == cp else state.players[i] for i in range(2)))
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="play_minor"))
    return step(state, sole_play_minor(state, CARD_ID))


def _setup_play(seed=7, **player_changes):
    from agricola.setup import CardPool, setup_env
    pool = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)))
    cs, _env = setup_env(seed, card_pool=pool)
    cp = cs.current_player
    cs = with_resources(cs, cp, **player_changes)
    return cs, cp


def test_play_grants_optional_build_fences_then_build():
    cs, cp = _setup_play(food=2, wood=20)
    cs = with_fields(cs, cp, [(0, 2)])
    cs = _play_field_fences_via_improvement(cs, cp)
    # The OPTIONAL grant wrapper is on top of the after-flipped play host — NOT the build host.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction) and top.initiated_by_id == FRAME_ID
    assert top.subaction == "build_fences"
    assert cs.players[cp].resources.food == 0       # the 2-food cost was paid at play
    # Opt in: choose Build Fences -> the real build host (with the grant provenance).
    cs = step(cs, ChooseSubAction(name="build_fences"))
    inner = cs.pending_stack[-1]
    assert isinstance(inner, PendingBuildFences) and inner.initiated_by_id == FRAME_ID
    # Build the field-adjacent 1x1 -> 3 wood accrued (the discount applied through the grant).
    cs = step(cs, CommitBuildPasture(cells=_1x1_03))
    assert cs.pending_stack[-1].accrued_cost.wood == 3


def test_play_grant_can_be_declined_even_when_buildable():
    # "You CAN take a Build Fences action" — optional. Even with a buildable pasture + wood,
    # the player may decline (Stop the wrapper) and play the card without building.
    cs, cp = _setup_play(food=2, wood=20)
    cs = with_fields(cs, cp, [(0, 2)])
    cs = _play_field_fences_via_improvement(cs, cp)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    options = legal_actions(cs)
    assert any(isinstance(a, ChooseSubAction) and a.name == "build_fences" for a in options)
    assert any(isinstance(a, Stop) for a in options)     # decline is offered
    cs = step(cs, Stop())                                # decline
    assert not any(isinstance(f, (PendingGrantedSubAction, PendingBuildFences))
                   for f in cs.pending_stack)            # wrapper popped, no build host
    assert CARD_ID in cs.players[cp].minor_improvements  # card kept, cost paid


def test_play_grant_only_decline_when_nothing_buildable():
    # 0 wood, no field, no free fences -> nothing is buildable, so the wrapper offers ONLY
    # Stop (the decline is the sole option), and the card is still played.
    cs, cp = _setup_play(food=2, wood=0)
    cs = _play_field_fences_via_improvement(cs, cp)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert [type(a).__name__ for a in legal_actions(cs)] == ["Stop"]
    cs = step(cs, Stop())
    assert cs.players[cp].resources.food == 0        # cost still paid; card kept
