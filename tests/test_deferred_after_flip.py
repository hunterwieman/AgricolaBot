"""The deferred after-flip (user ruling 2026-07-14).

"After you [do X]" card effects fire after X's FULL effect — everything the
effect pushed included — never between the commit and the effect. The commit
executors set `effect_initiated` on their host instead of flipping inline, and
`_advance_until_decision` flips the host (firing the after-autos) once it is
back on top. The accommodation barrier runs FIRST at that boundary: a
keep-which-animals choice raised by the effect is part of the effect settling,
so the after-autos wait for it too.

These tests pin the ruled ORDERING with real cards (the structural mid-states
are pinned in test_subaction_hook_lifecycle / test_card_host_enforce_first /
test_major_improvement / test_cards_cardstore_cards):

- Junk Room's "+1 food after any improvement" payout must NOT be available
  while Shifting Cultivation's granted plow (the played card's own effect) is
  being resolved — the motivating Bonehead x Established Person shape.
- The same payout must wait for the accommodation barrier raised by Game
  Trade's animal grant (barrier-before-flip).
- Farm Building's after_build_major schedule must land only after an oven's
  free-bake wrapper resolves.
"""
import agricola.cards.farm_building  # noqa: F401
import agricola.cards.game_trade  # noqa: F401
import agricola.cards.junk_room  # noqa: F401
import agricola.cards.shifting_cultivation  # noqa: F401

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitPlow,
    Stop,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingAccommodate,
    PendingBuildMajor,
    PendingClayOven,
    PendingPlayMinor,
    PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_animals, with_pending_stack, with_resources
from tests.test_utils import sole_build_major, sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("shifting_cultivation", "game_trade", "junk_room", "farm_building")
    + tuple(f"m{i}" for i in range(20)),
)


def _cards_state(seed=0):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return cs, cs.current_player


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _hand_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_minors=p.hand_minors | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _at_play_minor(state, idx):
    return with_pending_stack(
        state, (PendingPlayMinor(player_idx=idx, initiated_by_id="space:meeting_place_cards"),))


# ---------------------------------------------------------------------------
# The motivating ordering: an after-improvement payout cannot fund the
# improvement's own effect.
# ---------------------------------------------------------------------------

def test_after_improvement_payout_waits_for_the_played_cards_effect():
    cs, cp = _cards_state()
    cs = _own_minor(cs, cp, "junk_room")
    cs = _hand_minor(cs, cp, "shifting_cultivation")
    cs = with_resources(cs, cp, food=2)       # exactly the play cost — no slack
    cs = _at_play_minor(cs, cp)

    cs = step(cs, sole_play_minor(cs, "shifting_cultivation"))

    # Mid-effect: the granted plow is up, the play host is unflipped, and Junk
    # Room's food has NOT been paid out (2 food went to the cost -> 0 on hand).
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    host = cs.pending_stack[-2]
    assert host.phase == "before" and host.effect_initiated
    assert cs.players[cp].resources.food == 0

    plows = [a for a in legal_actions(cs) if isinstance(a, CommitPlow)]
    cs = step(cs, plows[0])                    # the granted plow
    cs = step(cs, Stop())                      # pop the plow; the deferred flip fires

    host = cs.pending_stack[-1]
    assert isinstance(host, PendingPlayMinor)
    assert host.phase == "after" and not host.effect_initiated
    assert cs.players[cp].resources.food == 1  # Junk Room's +1, only now


# ---------------------------------------------------------------------------
# Barrier-before-flip: the payout also waits for the keep-which-animals choice.
# ---------------------------------------------------------------------------

def test_after_improvement_payout_waits_for_the_accommodation_barrier():
    cs, cp = _cards_state()
    cs = _own_minor(cs, cp, "junk_room")
    cs = _hand_minor(cs, cp, "game_trade")
    # 2 sheep pay Game Trade's cost; the granted boar+cattle exceed the fresh
    # farm's single house-pet slot, so the barrier must raise an accommodation.
    cs = with_animals(cs, cp, sheep=2)
    cs = with_resources(cs, cp, food=0)
    cs = _at_play_minor(cs, cp)

    cs = step(cs, sole_play_minor(cs, "game_trade"))

    # The barrier ran BEFORE the deferred flip: the accommodate frame is up and
    # Junk Room's food has NOT been paid out.
    assert isinstance(cs.pending_stack[-1], PendingAccommodate)
    host = cs.pending_stack[-2]
    assert host.phase == "before" and host.effect_initiated
    assert cs.players[cp].resources.food == 0

    keeps = [a for a in legal_actions(cs) if isinstance(a, CommitAccommodate)]
    assert keeps
    cs = step(cs, keeps[0])                    # settle the keep-which choice

    host = cs.pending_stack[-1]
    assert isinstance(host, PendingPlayMinor)
    assert host.phase == "after" and not host.effect_initiated
    # Junk Room's +1 food arrived only after the accommodation settled (any
    # cooked excess adds on top of it — a fresh farm has zero cooking rates,
    # so the excess yields no food and the +1 is exact).
    assert cs.players[cp].resources.food == 1


# ---------------------------------------------------------------------------
# Build-major: the after_build_major schedule waits for the oven's free bake.
# ---------------------------------------------------------------------------

def test_after_build_major_auto_waits_for_the_oven_free_bake():
    cs, cp = _cards_state()
    cs = _own_minor(cs, cp, "farm_building")   # schedules food on build-major
    cs = with_resources(cs, cp, clay=3, stone=1, grain=1)
    cs = with_pending_stack(
        cs, (PendingBuildMajor(player_idx=cp, initiated_by_id="space:major_improvement"),))
    future0 = cs.players[cp].future_resources

    cs = step(cs, sole_build_major(cs, 5))     # Clay Oven

    # Mid-effect: the oven wrapper is up, the host unflipped, and Farm
    # Building's schedule has NOT landed.
    assert isinstance(cs.pending_stack[-1], PendingClayOven)
    host = cs.pending_stack[-2]
    assert host.phase == "before" and host.effect_initiated
    assert cs.players[cp].future_resources == future0

    cs = step(cs, ChooseSubAction(name="bake_bread"))
    cs = step(cs, CommitBake(grain=1))
    cs = step(cs, Stop())                      # pop the bake
    cs = step(cs, Stop())                      # pop the wrapper; the deferred flip fires

    host = cs.pending_stack[-1]
    assert isinstance(host, PendingBuildMajor)
    assert host.phase == "after" and not host.effect_initiated
    assert cs.players[cp].future_resources != future0   # the schedule landed
