"""Tests for the action-space after-trigger hook on a Proceed-host space.

  - Threshing Board (minor): after-TRIGGER granting a Bake Bread on Cultivation.
    Under the space-host refactor (SPACE_HOST_REFACTOR.md) Cultivation is a
    Proceed-host: the after-trigger surfaces in the space's *after-phase* (after
    Proceed), not at the old before-phase Stop-gate. Firing it pushes the granted
    PendingBakeBread on top of the already-after PendingCultivation.

  (Firewood Collector's after-AUTO is DEFERRED — see archive/cards/; its "+1 wood
  at the END of that turn" needs an end-of-turn event the firing migration does not
  add, so its tests are removed here. It returns when that event exists.)
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
# Threshing Board — after-trigger granting a bake in Cultivation's after-phase
# ---------------------------------------------------------------------------

def test_threshing_board_grants_bake_in_after_phase():
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_majors(s, owner_by_idx={0: 0})         # Fireplace (grain -> 2 food on bake)
    s = with_resources(s, 0, grain=3)
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, ChooseSubAction(name="plow"))
    s = _commit_plow(s)
    s = step(s, Stop())                                   # pop PendingPlow's after-phase
    # Cultivation before-phase: the base sub-action (sow) + Proceed. The
    # after-trigger is NOT surfaced yet (it lives in the after-phase).
    la = legal_actions(s)
    assert ChooseSubAction(name="sow") in la
    assert Proceed() in la
    assert FireTrigger(card_id="threshing_board") not in la

    s = step(s, Proceed())                                # flip Cultivation to after
    # After-phase: the after-trigger is now surfaced alongside Stop.
    la = legal_actions(s)
    assert FireTrigger(card_id="threshing_board") in la
    assert Stop() in la
    assert ChooseSubAction(name="sow") not in la          # base sub-actions closed in after

    s = step(s, FireTrigger(card_id="threshing_board"))   # grant the bake
    s = step(s, CommitBake(grain=1))                      # Fireplace: 1 grain -> 2 food
    s = step(s, Stop())                                   # pop the granted PendingBakeBread's after-phase
    assert s.players[0].resources.food == food0 + 2
    # Threshing Board already fired -> only Stop remains in the after-phase.
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())                                   # pop PendingCultivation
    assert not s.pending_stack


def test_threshing_board_not_eligible_without_bake():
    # Owns Threshing Board but has no baker/grain -> not surfaced even in after.
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_resources(s, 0, grain=0)
    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, ChooseSubAction(name="plow"))
    s = _commit_plow(s)
    s = step(s, Stop())                                   # pop PendingPlow's after-phase
    s = step(s, Proceed())                                # flip Cultivation to after-phase
    assert FireTrigger(card_id="threshing_board") not in legal_actions(s)
