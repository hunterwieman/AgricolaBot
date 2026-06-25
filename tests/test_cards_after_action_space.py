"""Tests for the multi-sub-action after_action_space hook (step 4b, the unified
"surface after-triggers wherever Stop is legal; fire after-auto at Stop" model):

  - Firewood Collector (occ): after-AUTO +1 wood at the end of a Farmland /
    Grain Seeds / Grain Util / Cultivation turn (fires at the host's Stop).
  - Threshing Board (minor): after-TRIGGER granting a Bake Bread on Farmland /
    Cultivation, which also closes the base sub-actions (after_started derived
    from triggers_resolved — no stored flag).
"""
from agricola.actions import (
    ChooseSubAction, CommitBake, FireTrigger, PlaceWorker, Proceed, Stop,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_majors, with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, occ=(), minors=()):
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    p = fast_replace(s.players[0],
                     occupations=s.players[0].occupations | set(occ),
                     minor_improvements=s.players[0].minor_improvements | set(minors))
    return fast_replace(s, players=(p, s.players[1]))


def _reveal(s, space_id, **kwargs):
    sp = fast_replace(get_space(s.board, space_id), revealed=True, **kwargs)
    return fast_replace(s, board=with_space(s.board, space_id, sp))


def _commit_plow(s):
    plow = next(a for a in legal_actions(s) if type(a).__name__ == "CommitPlow")
    return step(s, plow)


# ---------------------------------------------------------------------------
# Firewood Collector — after-auto +1 wood at Stop
# ---------------------------------------------------------------------------

def test_firewood_collector_on_farmland():
    s = _state(occ=("firewood_collector",))
    w0 = s.players[0].resources.wood
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, ChooseSubAction(name="plow"))
    s = _commit_plow(s)
    assert legal_actions(s) == [Stop()]            # plow done, no after-triggers owned
    s = step(s, Stop())
    assert s.players[0].resources.wood == w0 + 1   # Firewood fired at Stop
    assert not s.pending_stack


def test_firewood_collector_on_atomic_grain_seeds():
    s = _state(occ=("firewood_collector",))
    w0 = s.players[0].resources.wood
    g0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="grain_seeds"))   # atomic -> hosted (owns firewood)
    s = step(s, Proceed())                          # +1 grain, flip to after
    s = step(s, Stop())                             # after-auto fires here
    assert s.players[0].resources.grain == g0 + 1   # Grain Seeds primary
    assert s.players[0].resources.wood == w0 + 1    # Firewood


def test_firewood_collector_not_on_other_spaces():
    # Day Laborer isn't in Firewood's space set -> no hosting, no +1 wood.
    s = _state(occ=("firewood_collector",))
    w0 = s.players[0].resources.wood
    s = step(s, PlaceWorker(space="day_laborer"))
    from agricola.pending import PendingActionSpace
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[0].resources.wood == w0


# ---------------------------------------------------------------------------
# Threshing Board — after-trigger granting a bake, closing the base sub-actions
# ---------------------------------------------------------------------------

def test_threshing_board_grants_bake_and_closes_subactions():
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_majors(s, owner_by_idx={0: 0})         # Fireplace (grain -> 2 food on bake)
    s = with_resources(s, 0, grain=3)
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, ChooseSubAction(name="plow"))
    s = _commit_plow(s)
    # Stop-gate met: sow is still available AND the after-trigger is surfaced.
    la = legal_actions(s)
    assert ChooseSubAction(name="sow") in la
    assert FireTrigger(card_id="threshing_board") in la
    assert Stop() in la

    s = step(s, FireTrigger(card_id="threshing_board"))   # grant the bake
    s = step(s, CommitBake(grain=1))                      # Fireplace: 1 grain -> 2 food
    assert s.players[0].resources.food == food0 + 2
    # after_started (derived) -> base sub-actions are now closed; only Stop.
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert not s.pending_stack


def test_threshing_board_not_eligible_without_bake():
    # Owns Threshing Board but has no baker/grain -> not surfaced.
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_resources(s, 0, grain=0)
    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, ChooseSubAction(name="plow"))
    s = _commit_plow(s)
    assert FireTrigger(card_id="threshing_board") not in legal_actions(s)
