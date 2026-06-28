"""Tests for the action-space "each time you use [space]" before-trigger hook.

  - Threshing Board (minor): before-TRIGGER granting a Bake Bread on Cultivation.
    "Each time you use [space]" fires before the space's own effect (the Trigger-
    Timing ruling), so the grant surfaces in the space's *before-phase* alongside
    the base plow/sow, takeable in either order. Firing it pushes the granted
    PendingBakeBread on top of PendingCultivation. (The companion Farmland path — a
    delegating host where the engine must hold its post-plow auto-advance so the
    grant isn't dropped — is covered by the Moldboard Plow tests in
    test_cards_cardstore_cards.py.)

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
# Threshing Board — before-trigger granting a bake in Cultivation's before-phase
# ---------------------------------------------------------------------------

def test_threshing_board_grants_bake_in_before_phase():
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_majors(s, owner_by_idx={0: 0})         # Fireplace (grain -> 2 food on bake)
    s = with_resources(s, 0, grain=3)
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="cultivation"))
    # Before-phase: the bake grant is offered alongside the base plow ("each time
    # you use" fires before the space effect). (Sow isn't legal yet — no plowed
    # field to sow.) No Proceed yet — Cultivation requires a base sub-action.
    la = legal_actions(s)
    assert FireTrigger(card_id="threshing_board") in la
    assert ChooseSubAction(name="plow") in la
    assert Proceed() not in la

    # Do a base plow first; the grant must still be available afterwards (free
    # ordering — the grant is not consumed by using the space).
    s = step(s, ChooseSubAction(name="plow"))
    s = _commit_plow(s)
    s = step(s, Stop())                                   # pop PendingPlow's after-phase
    la = legal_actions(s)
    assert FireTrigger(card_id="threshing_board") in la
    assert Proceed() in la                                # base sub-action done → can advance

    s = step(s, FireTrigger(card_id="threshing_board"))   # grant the bake
    s = step(s, CommitBake(grain=1))                      # Fireplace: 1 grain -> 2 food
    s = step(s, Stop())                                   # pop the granted PendingBakeBread's after-phase
    assert s.players[0].resources.food == food0 + 2
    # Threshing Board already fired -> no longer offered.
    assert FireTrigger(card_id="threshing_board") not in legal_actions(s)
    assert Proceed() in legal_actions(s)
    s = step(s, Proceed())                                # flip Cultivation to after
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())                                   # pop PendingCultivation
    assert not s.pending_stack


def test_threshing_board_grants_bake_before_any_base_subaction():
    # The grant can also be taken BEFORE the base plow/sow (the other order).
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_majors(s, owner_by_idx={0: 0})
    s = with_resources(s, 0, grain=3)
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, FireTrigger(card_id="threshing_board"))   # bake first, before plowing
    s = step(s, CommitBake(grain=1))
    s = step(s, Stop())                                   # pop granted PendingBakeBread's after
    assert s.players[0].resources.food == food0 + 2
    # Still in the before-phase; the base sub-action is still required.
    la = legal_actions(s)
    assert ChooseSubAction(name="plow") in la
    assert Proceed() not in la                            # no base sub-action taken yet


def test_threshing_board_not_eligible_without_bake():
    # Owns Threshing Board but has no baker/grain -> not surfaced even in before.
    s = _state(minors=("threshing_board",))
    s = _reveal(s, "cultivation")
    s = with_resources(s, 0, grain=0)
    s = step(s, PlaceWorker(space="cultivation"))
    assert FireTrigger(card_id="threshing_board") not in legal_actions(s)
