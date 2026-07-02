"""Enforce-first gates on the card-only Proceed-hosts + the play-occupation flip order.

Two engine behaviors landed together (CARD_ENGINE_IMPLEMENTATION.md §2/§4):

- `PendingBasicWishForChildren` / `PendingMeetingPlace` gained the `subaction_started`
  before-window gate (SPACE_HOST_REFACTOR.md §5.1), closing the gap the five Family
  Proceed-hosts already had: a `before_action_space` trigger is offered only until a base
  sub-action is chosen — taking the space's work implicitly declines it (enforce-first).
- `_execute_play_occupation` flips its host to the after-phase BEFORE running `on_play`
  (mirroring `_execute_play_minor`), so an occupation `on_play` that PUSHES a frame lands
  it on top of the already-flipped host instead of getting mis-flipped itself.

Synthetic cards are registered with the test-scoped register + try/finally cleanup
pattern from test_space_host_hooks.py.
"""
from contextlib import contextmanager

from agricola.actions import (
    ChooseSubAction,
    CommitFamilyGrowth,
    CommitPlayOccupation,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_grid
from tests.test_utils import sole_play_minor

_TRIG = "test_enforce_first_trigger"
_OCC = "test_pushing_occupation"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


@contextmanager
def _registered_trigger(event: str, space_ids: set):
    """Test-scoped OPTIONAL trigger on `event`, eligible only when the top frame's
    `space_id` is in `space_ids`. Applies +1 food (content irrelevant here)."""
    from agricola.cards.triggers import CARDS, TRIGGERS, register

    def _elig(state, idx, resolved):
        top = state.pending_stack[-1]
        return getattr(top, "space_id", None) in space_ids

    def _apply(state, idx):
        p = state.players[idx]
        p = fast_replace(p, resources=p.resources + Resources(food=1))
        return fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))

    register(event, _TRIG, _elig, _apply)
    try:
        yield
    finally:
        TRIGGERS[event] = [e for e in TRIGGERS.get(event, []) if e.card_id != _TRIG]
        CARDS.pop(_TRIG, None)


@contextmanager
def _registered_pushing_occupation():
    """Test-scoped occupation whose ON_PLAY pushes a PendingPlow (no real occupation
    does this today — the flip-before-on_play order is what makes it safe)."""
    from agricola.cards.specs import OCCUPATIONS, register_occupation

    def _on_play(state, idx):
        return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{_OCC}"))

    register_occupation(_OCC, _on_play)
    try:
        yield
    finally:
        OCCUPATIONS.pop(_OCC, None)


def _own_trigger(cs, cp):
    """Put the synthetic trigger card in the current player's tableau (a hand card
    cannot fire)."""
    p = fast_replace(cs.players[cp], occupations=cs.players[cp].occupations | {_TRIG})
    return fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))


def test_basic_wish_before_window_closes_at_growth():
    with _registered_trigger("before_action_space", {"basic_wish_for_children"}):
        cs, _env = setup_env(5, card_pool=_POOL)
        cp = cs.current_player
        # Reveal the space + a 3rd room (growth legality: people_total < rooms).
        sp = fast_replace(get_space(cs.board, "basic_wish_for_children"),
                          revealed=True, workers=(0, 0))
        cs = fast_replace(cs, board=with_space(cs.board, "basic_wish_for_children", sp))
        cs = with_grid(cs, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})
        cs = _own_trigger(cs, cp)

        cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
        acts = legal_actions(cs)
        # Window open at push: the trigger is offered alongside the mandatory growth.
        assert FireTrigger(card_id=_TRIG) in acts
        assert ChooseSubAction(name="family_growth") in acts

        cs = step(cs, ChooseSubAction(name="family_growth"))
        cs = step(cs, CommitFamilyGrowth())
        cs = step(cs, Stop())   # pop the growth primitive's after-phase
        # Back at the parent (family_growth_done=True): the mandatory work closed the
        # before-window — the unfired trigger is implicitly declined.
        acts = legal_actions(cs)
        assert FireTrigger(card_id=_TRIG) not in acts
        assert Proceed() in acts


def test_meeting_place_before_window_closes_at_minor():
    with _registered_trigger("before_action_space", {"meeting_place"}):
        cs, _env = setup_env(5, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_trigger(cs, cp)
        # A playable minor (market_stall: 1 grain) in hand + the grain to pay it.
        p = cs.players[cp]
        p = fast_replace(p, hand_minors=frozenset({"market_stall"}),
                         resources=p.resources + Resources(grain=1))
        cs = fast_replace(cs, players=tuple(
            p if i == cp else cs.players[i] for i in range(2)))

        cs = step(cs, PlaceWorker(space="meeting_place"))
        acts = legal_actions(cs)
        # Window open at push (become-SP already happened at the resolver).
        assert FireTrigger(card_id=_TRIG) in acts
        assert ChooseSubAction(name="play_minor") in acts
        assert Proceed() in acts   # Proceed IS the decline, legal from the start

        cs = step(cs, ChooseSubAction(name="play_minor"))
        cs = step(cs, sole_play_minor(cs, "market_stall"))
        cs = step(cs, Stop())   # pop PendingPlayMinor's after-phase
        # Back at the parent (minor_chosen=True): the chosen minor closed the window.
        acts = legal_actions(cs)
        assert FireTrigger(card_id=_TRIG) not in acts
        assert acts == [Proceed()]


def test_meeting_place_trigger_still_fireable_before_minor():
    """The gate must not over-close: firing the trigger FIRST, then the minor, works."""
    with _registered_trigger("before_action_space", {"meeting_place"}):
        cs, _env = setup_env(5, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_trigger(cs, cp)
        cs = step(cs, PlaceWorker(space="meeting_place"))
        food0 = cs.players[cp].resources.food
        cs = step(cs, FireTrigger(card_id=_TRIG))
        assert cs.players[cp].resources.food == food0 + 1
        # Fired triggers don't re-offer (triggers_resolved); Proceed remains.
        acts = legal_actions(cs)
        assert FireTrigger(card_id=_TRIG) not in acts
        assert Proceed() in acts


@contextmanager
def _registered_leaf_pair():
    """Test-scoped pair on `before_play_occupation`: an AUTO granting +1 food and a
    non-pushing optional TRIGGER (+1 wood) — the Hand-Truck-plus-Potter shape. The
    seam's depth guard must fire the auto exactly once (at the leaf's push), never
    again after the non-pushing trigger fires."""
    from agricola.cards.triggers import AUTO_EFFECTS, CARDS, TRIGGERS, register, register_auto

    _AUTO = "test_leaf_before_auto"

    def _grant(res):
        def _apply(state, idx):
            p = state.players[idx]
            p = fast_replace(p, resources=p.resources + res)
            return fast_replace(state, players=tuple(
                p if i == idx else state.players[i] for i in range(2)))
        return _apply

    register_auto("before_play_occupation", _AUTO, lambda s, i: True,
                  _grant(Resources(food=1)))
    register("before_play_occupation", _TRIG, lambda s, i, r: True,
             _grant(Resources(wood=1)))
    try:
        yield _AUTO
    finally:
        AUTO_EFFECTS["before_play_occupation"] = [
            e for e in AUTO_EFFECTS.get("before_play_occupation", []) if e.card_id != _AUTO
        ]
        TRIGGERS["before_play_occupation"] = [
            e for e in TRIGGERS.get("before_play_occupation", []) if e.card_id != _TRIG
        ]
        CARDS.pop(_TRIG, None)


def test_nonpushing_trigger_does_not_refire_leaf_before_auto():
    """The seam's depth guard (the Bookshelf-double-fire regression): a before-auto
    on a leaf fires once at the leaf's push; a non-pushing trigger fired at the same
    leaf must not re-fire it."""
    with _registered_leaf_pair() as auto_id:
        cs, _env = setup_env(5, card_pool=_POOL)
        cp = cs.current_player
        sp = fast_replace(get_space(cs.board, "lessons"), revealed=True, workers=(0, 0))
        cs = fast_replace(cs, board=with_space(cs.board, "lessons", sp))
        p = fast_replace(cs.players[cp],
                         hand_occupations=frozenset({"consultant"}),
                         occupations=frozenset({auto_id, _TRIG}))
        cs = fast_replace(cs, players=tuple(
            p if i == cp else cs.players[i] for i in range(2)))
        food0 = cs.players[cp].resources.food

        cs = step(cs, PlaceWorker(space="lessons"))
        cs = step(cs, ChooseSubAction(name="play_occupation"))
        # The leaf's push fired the before-auto exactly once.
        assert cs.players[cp].resources.food == food0 + 1
        # Fire the non-pushing trigger at the same leaf: its own effect applies,
        # but the auto must NOT re-fire.
        assert FireTrigger(card_id=_TRIG) in legal_actions(cs)
        wood0 = cs.players[cp].resources.wood
        cs = step(cs, FireTrigger(card_id=_TRIG))
        assert cs.players[cp].resources.wood == wood0 + 1
        assert cs.players[cp].resources.food == food0 + 1   # still once


def test_pushing_occupation_on_play_flips_host_first():
    with _registered_pushing_occupation():
        cs, _env = setup_env(5, card_pool=_POOL)
        cp = cs.current_player
        sp = fast_replace(get_space(cs.board, "lessons"), revealed=True, workers=(0, 0))
        cs = fast_replace(cs, board=with_space(cs.board, "lessons", sp))
        p = fast_replace(cs.players[cp], hand_occupations=frozenset({_OCC}))
        cs = fast_replace(cs, players=tuple(
            p if i == cp else cs.players[i] for i in range(2)))

        cs = step(cs, PlaceWorker(space="lessons"))
        cs = step(cs, ChooseSubAction(name="play_occupation"))
        cs = step(cs, CommitPlayOccupation(card_id=_OCC))

        # The host flipped to its after-phase BEFORE on_play ran, so the pushed plow
        # sits on top of the already-"after" host (not: the plow got mis-flipped).
        plow = cs.pending_stack[-1]
        assert isinstance(plow, PendingPlow) and plow.phase == "before"
        host = cs.pending_stack[-2]
        assert isinstance(host, PendingPlayOccupation) and host.phase == "after"
        assert _OCC in cs.players[cp].occupations

        # The granted plow plays end-to-end.
        plows = [a for a in legal_actions(cs) if isinstance(a, CommitPlow)]
        assert plows
        cs = step(cs, plows[0])
        cs = step(cs, Stop())   # pop the plow's after-phase
        assert legal_actions(cs) == [Stop()]   # the host's after-phase
        cs = step(cs, Stop())   # pop the host; the Delegating space host auto-flips
        assert legal_actions(cs) == [Stop()]
        cs = step(cs, Stop())
        assert cs.pending_stack == ()
