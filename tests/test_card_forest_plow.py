"""Forest Plow (minor B17): after you use a wood accumulation space, you can pay 2 wood
to plow 1 field, placing the paid wood on the space (for the next visitor).

Text: "Each time you use a wood accumulation space, you can pay 2 wood to plow 1 field.
Place the paid wood on the accumulation space (for the next visitor)." Cost 1 Wood.
Clarification: "You may take less than 2 wood from the space and still use this card's
effect."

USER RULING (2026-07-20): the trigger fires AFTER the take (per-card override of the
default before-window reading of "each time you use [space]") — so the deposit can't be
scooped back by the player's own sweep, and the just-taken wood can fund the payment.

The trigger is an OPTIONAL `after_action_space` trigger (wood spaces are ATOMIC, so a
`register_action_space_hook` gives them a host). Firing debits 2 wood, adds it to the
space's `accumulated` Resources (swept whole by the next visitor), and pushes PendingPlow.
"""
import agricola.cards.forest_plow  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    RevealCard,
    Stop,
)
from agricola.cards.forest_plow import CARD_ID, FRAME_ID, _eligible
from agricola.constants import CellType, GameMode, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import get_space

from tests.factories import (
    with_current_player,
    with_fields,
    with_pending_stack,
    with_resources,
    with_space,
)


def _own(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, wood=10, forest_wood=3, own=True, current_player=0):
    """A CARDS-mode state, P0 to move, Forest revealed with `forest_wood` on it, P0
    holding `wood` and (by default) Forest Plow."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, wood=wood)
    state = with_space(state, "forest", revealed=True,
                       accumulated=Resources(wood=forest_wood))
    if own:
        state = _own(state, current_player, CARD_ID)
    return state


def _has_fire(opts):
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID for a in opts)


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.FIELD)


# ---------------------------------------------------------------------------
# Registration (SUBSET checks, never exact-set)
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.specs import MINORS
    from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
    from agricola.constants import WOOD_ACCUMULATION_SPACES
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(wood=1))
    # optional trigger on the AFTER window of an action space (the 2026-07-20 ruling)
    assert any(e.card_id == CARD_ID and not e.mandatory
               for e in TRIGGERS.get("after_action_space", []))
    # hook registered over the WHOLE wood-accumulation-space set (4-player forward-compat)
    assert WOOD_ACCUMULATION_SPACES  # non-empty
    for space_id in WOOD_ACCUMULATION_SPACES:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(space_id, set())


# ---------------------------------------------------------------------------
# The real flow on Forest: use -> sweep -> fire -> pay/deposit -> plow
# ---------------------------------------------------------------------------

def test_full_flow_on_forest():
    s = _state(wood=10, forest_wood=3)
    s = step(s, PlaceWorker(space="forest"))
    # before-phase of the hosted Forest: no before-trigger (the AFTER ruling), just
    # Proceed (the take).
    assert [type(a).__name__ for a in legal_actions(s)] == ["Proceed"]
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 13          # swept 3 wood from Forest
    assert get_space(s.board, "forest").accumulated == Resources()
    # after-phase: the optional trigger is offered, alongside Stop (the decline).
    opts = legal_actions(s)
    assert _has_fire(opts)
    assert any(isinstance(a, Stop) for a in opts)

    fields_before = _num_fields(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID))
    # 2 wood debited, 2 wood deposited on Forest, the plow primitive pushed.
    assert s.players[0].resources.wood == 11          # 13 - 2
    assert get_space(s.board, "forest").accumulated == Resources(wood=2)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.initiated_by_id == FRAME_ID

    # The paid-for plow is committed once fired: every option is a CommitPlow.
    plow_opts = legal_actions(s)
    assert plow_opts and all(isinstance(a, CommitPlow) for a in plow_opts)
    s = step(s, plow_opts[0])
    assert _num_fields(s, 0) == fields_before + 1     # a real cell was plowed
    cell = s.players[0].farmyard.grid[plow_opts[0].row][plow_opts[0].col]
    assert cell.cell_type == CellType.FIELD

    # The plow frame's after-phase -> Stop pops it, back to the Forest host.
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())
    # Back at the Forest host: once-per-use, the trigger is NOT re-offered.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert not _has_fire(legal_actions(s))
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())                               # pop the Forest host -> turn ends
    assert not any(isinstance(f, (PendingPlow, PendingActionSpace))
                   for f in s.pending_stack)


def test_deposit_goes_to_next_visitor_next_round():
    """The deposited wood is 'for the next visitor': play the round out, cross into
    round 2, and the OPPONENT's Forest visit sweeps refill (+3) + deposit (+2) = 5."""
    s = _state(wood=10, forest_wood=3)
    # P0's turn: use Forest, fire, plow, end the turn.
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, legal_actions(s)[0])                  # CommitPlow
    s = step(s, Stop())                               # pop the plow frame
    s = step(s, Stop())                               # pop the Forest host -> turn ends
    assert get_space(s.board, "forest").accumulated == Resources(wood=2)
    # Place out the round's remaining workers on atomic spaces (P1, P0, P1).
    assert s.current_player == 1
    s = step(s, PlaceWorker(space="clay_pit"))
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, PlaceWorker(space="reed_bank"))
    # RETURN_HOME -> PREPARATION pauses at the round-2 reveal (a nature step).
    acts = legal_actions(s)
    while acts and isinstance(acts[0], RevealCard):
        s = step(s, acts[0])
        acts = legal_actions(s)
    assert s.round_number == 2 and s.phase == Phase.WORK
    # The refill landed ON TOP of the deposit.
    assert get_space(s.board, "forest").accumulated == Resources(wood=5)
    # The next visitor is the OPPONENT (no card, so Forest is atomic for them).
    if s.current_player == 0:
        s = step(s, PlaceWorker(space="grain_seeds"))
    assert s.current_player == 1
    wood_before = s.players[1].resources.wood
    s = step(s, PlaceWorker(space="forest"))
    assert s.players[1].resources.wood == wood_before + 5
    assert get_space(s.board, "forest").accumulated == Resources()


def test_just_taken_wood_funds_payment():
    """Clarification-consistent, after-timing: 0 wood in supply, sweep a 3-wood Forest,
    and the trigger is offered — the payment is made from the post-take supply."""
    s = _state(wood=0, forest_wood=3)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 3
    assert _has_fire(legal_actions(s))
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].resources.wood == 1           # 3 - 2
    assert get_space(s.board, "forest").accumulated == Resources(wood=2)
    assert isinstance(s.pending_stack[-1], PendingPlow)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_below_two_wood_after_take():
    # 1 wood in supply after sweeping an empty Forest -> can't pay 2 -> not offered.
    s = _state(wood=1, forest_wood=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 1
    opts = legal_actions(s)
    assert not _has_fire(opts)
    assert any(isinstance(a, Stop) for a in opts)


def test_not_offered_with_no_plowable_cell():
    # Fill every empty farmyard cell with a field -> no plow target -> the paid-for
    # plow would dead-end, so the trigger is not offered.
    s = _state(wood=10, forest_wood=3)
    empties = [(r, c) for r in range(3) for c in range(5)
               if s.players[0].farmyard.grid[r][c].cell_type == CellType.EMPTY]
    s = with_fields(s, 0, empties)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 13          # plenty of wood; plow is the gate
    assert not _has_fire(legal_actions(s))


def test_eligibility_space_filter():
    # The eligibility fn filters by space_id: a wood space qualifies, a non-wood one
    # (clay_pit) does not — asserted on the predicate directly for the non-wood case.
    base = _state(wood=10)
    forest_host = PendingActionSpace(
        player_idx=0, initiated_by_id="space:forest", phase="after")
    assert _eligible(with_pending_stack(base, [forest_host]), 0, frozenset()) is True
    clay_host = PendingActionSpace(
        player_idx=0, initiated_by_id="space:clay_pit", phase="after")
    assert _eligible(with_pending_stack(base, [clay_host]), 0, frozenset()) is False


def test_non_wood_space_stays_unhosted():
    # Forest Plow only hooks wood accumulation spaces: the owner's Clay Pit use is
    # ATOMIC — no host frame, no fire, the turn just passes.
    s = _state(wood=10)
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.current_player == 1                      # turn passed


def test_once_per_use_via_triggers_resolved():
    # The predicate itself refuses a resolved fire (belt-and-braces with the firing
    # machinery's own filter, exercised in the full-flow test).
    base = _state(wood=10)
    forest_host = PendingActionSpace(
        player_idx=0, initiated_by_id="space:forest", phase="after")
    s = with_pending_stack(base, [forest_host])
    assert _eligible(s, 0, frozenset()) is True
    assert _eligible(s, 0, frozenset({CARD_ID})) is False


def test_opponent_use_not_hosted():
    # "you use" is own-use only: the wood space is hosted for the OWNER's placement,
    # atomic for the opponent's (so the opponent's Forest use never offers the trigger).
    from agricola.cards.triggers import should_host_space
    s = _state(own=True)                              # P0 owns Forest Plow
    assert should_host_space(s, "forest", 0) is True
    assert should_host_space(s, "forest", 1) is False


# ---------------------------------------------------------------------------
# Optionality
# ---------------------------------------------------------------------------

def test_decline_via_stop():
    s = _state(wood=10, forest_wood=3)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert _has_fire(legal_actions(s))                # the trigger is available
    s = step(s, Stop())                               # decline: the host's after-phase Stop
    # nothing spent, nothing placed on the space, no plow frame, turn ended.
    assert s.players[0].resources.wood == 13          # the sweep only
    assert get_space(s.board, "forest").accumulated == Resources()
    assert not any(isinstance(f, (PendingPlow, PendingActionSpace))
                   for f in s.pending_stack)
