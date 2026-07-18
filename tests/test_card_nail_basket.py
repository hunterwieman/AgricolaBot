"""Nail Basket (minor E15): after you use a wood accumulation space, you can place 1 stone
on that space (for the next visitor) and take a literal "Build Fences" action.

Text: "Each time after you use a wood accumulation space, you can place 1 stone from your
supply on that space (for the next visitor) to take a "Build Fences" action." Cost 1 Reed, 1 VP.

The trigger is an OPTIONAL `after_action_space` trigger (the wood spaces are ATOMIC, so a
`register_action_space_hook` gives them a host). Firing debits 1 stone, adds it to the space's
`accumulated` Resources (swept whole by the next visitor), and pushes the real PendingBuildFences.
"""
import agricola.cards.nail_basket  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitBuildPasture,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.nail_basket import CARD_ID, FRAME_ID, _eligible
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingBuildFences
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import get_space

from tests.factories import (
    with_current_player,
    with_pending_stack,
    with_resources,
    with_space,
)

_1x1_03 = frozenset({(0, 3)})   # a fresh-farmyard 1x1 pasture: 4 new edges = 4 wood


def _own(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, wood=10, stone=1, forest_wood=3, own=True, current_player=0):
    """A CARDS-mode state (so the fence deferred-tally is exercised), P0 to move, Forest
    revealed with `forest_wood` on it, P0 holding `wood`/`stone` and (by default) Nail Basket."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, wood=wood, stone=stone)
    state = with_space(state, "forest", revealed=True,
                       accumulated=Resources(wood=forest_wood))
    if own:
        state = _own(state, current_player, CARD_ID)
    return state


def _has_fire(opts):
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID for a in opts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.specs import MINORS
    from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
    from agricola.constants import WOOD_ACCUMULATION_SPACES
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(reed=1))
    assert MINORS[CARD_ID].vps == 1
    # optional trigger on the AFTER window of an action space
    assert any(e.card_id == CARD_ID and not e.mandatory
               for e in TRIGGERS.get("after_action_space", []))
    # hook registered over the WHOLE wood-accumulation-space set (4-player forward-compat)
    assert WOOD_ACCUMULATION_SPACES  # non-empty
    for space_id in WOOD_ACCUMULATION_SPACES:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(space_id, set())


# ---------------------------------------------------------------------------
# The real flow on Forest: use → fire → place stone → build a pasture
# ---------------------------------------------------------------------------

def test_full_flow_on_forest():
    s = _state(wood=10, stone=2, forest_wood=3)
    s = step(s, PlaceWorker(space="forest"))
    # before-phase of the hosted Forest: no before-trigger, just Proceed (the take).
    assert [type(a).__name__ for a in legal_actions(s)] == ["Proceed"]
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 13          # swept 3 wood from Forest
    # after-phase: the optional grant is offered, alongside Stop (the decline).
    opts = legal_actions(s)
    assert _has_fire(opts)
    assert any(isinstance(a, Stop) for a in opts)

    s = step(s, FireTrigger(card_id=CARD_ID))
    # stone debited, stone placed on Forest, the real Build Fences host pushed.
    assert s.players[0].resources.stone == 1          # 2 -> 1
    assert get_space(s.board, "forest").accumulated == Resources(stone=1)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.initiated_by_id == FRAME_ID
    assert top.build_fences_action is True

    # Build a 1x1 pasture, paying wood normally (4 edges = 4 wood, settled at Proceed).
    s = step(s, CommitBuildPasture(cells=_1x1_03))
    assert s.pending_stack[-1].accrued_cost.wood == 4
    s = step(s, Proceed())                            # settle: pay 4 wood
    assert s.players[0].resources.wood == 9           # 13 - 4
    assert len(s.players[0].farmyard.pastures) == 1   # the pasture exists

    # Fence host after-phase -> Stop pops it, returning to the Forest host after-phase.
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())                               # pop the fence host
    # Back at the Forest host: once-per-use, the grant is NOT re-offered.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert not _has_fire(legal_actions(s))
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())                               # pop the Forest host -> turn ends
    assert not any(isinstance(f, (PendingBuildFences, PendingActionSpace))
                   for f in s.pending_stack)


def test_next_visitor_sweeps_wood_and_stone():
    """The load-bearing claim: the next visitor to the space sweeps the WHOLE accumulated
    vector (a round's fresh wood AND the Nail-Basket stone)."""
    s = fast_replace(setup(seed=0), mode=GameMode.CARDS)
    s = with_current_player(s, 0)
    s = with_resources(s, 0)                          # zero everything
    # Forest carries a fresh +3 wood on top of the stone a prior Nail Basket left behind.
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3, stone=1))
    # P0 does NOT own Nail Basket -> Forest is atomic (a one-step take, no host).
    s = step(s, PlaceWorker(space="forest"))
    assert s.players[0].resources.wood == 3
    assert s.players[0].resources.stone == 1          # the leftover stone came along
    assert get_space(s.board, "forest").accumulated == Resources()


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_with_zero_stone():
    s = _state(wood=10, stone=0, forest_wood=3)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    opts = legal_actions(s)
    assert not _has_fire(opts)
    assert any(isinstance(a, Stop) for a in opts)


def test_not_offered_when_no_legal_pasture():
    # 0 wood after sweeping an empty Forest, 1 stone, no free-fence budget -> no pasture is
    # buildable (a 1x1 costs 4 wood), so the grant would dead-end and is not offered.
    s = _state(wood=0, stone=1, forest_wood=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[0].resources.wood == 0
    assert not _has_fire(legal_actions(s))


def test_eligibility_space_filter():
    # The eligibility fn filters by space_id: a wood space qualifies, a non-wood one (clay_pit)
    # does not. (Nail Basket only HOOKS wood spaces, so a hosted clay_pit is unreachable through
    # its own play; this asserts the predicate directly for the non-wood case.)
    base = _state(wood=10, stone=1)
    forest_host = PendingActionSpace(
        player_idx=0, initiated_by_id="space:forest", phase="after")
    assert _eligible(with_pending_stack(base, [forest_host]), 0, frozenset()) is True
    clay_host = PendingActionSpace(
        player_idx=0, initiated_by_id="space:clay_pit", phase="after")
    assert _eligible(with_pending_stack(base, [clay_host]), 0, frozenset()) is False


def test_opponent_use_not_hosted():
    # "you use" is own-use only: the wood space is hosted for the OWNER's placement, atomic
    # for the opponent's (so the opponent's Forest use never offers the grant).
    from agricola.cards.triggers import should_host_space
    s = _state(own=True)                              # P0 owns Nail Basket
    assert should_host_space(s, "forest", 0) is True
    assert should_host_space(s, "forest", 1) is False


# ---------------------------------------------------------------------------
# Optionality
# ---------------------------------------------------------------------------

def test_decline_via_stop():
    s = _state(wood=10, stone=1, forest_wood=3)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert _has_fire(legal_actions(s))               # the grant is available
    stone_before = s.players[0].resources.stone
    s = step(s, Stop())                              # decline: the host's after-phase Stop
    # nothing spent, nothing placed on the space, no fence host, turn ended.
    assert s.players[0].resources.stone == stone_before
    assert get_space(s.board, "forest").accumulated == Resources()
    assert not any(isinstance(f, (PendingBuildFences, PendingActionSpace))
                   for f in s.pending_stack)
