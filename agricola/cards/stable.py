"""Stable (minor improvement, C2; Consul Dirigens Expansion; players -).

Card text: "Immediately build 1 stable. (The stable costs you nothing, but you must pay
the cost shown on this card.)"
Cost: 1 Wood. PASSING (traveling minor — `passing_left='X'` in the catalog: the card
moves to the opponent's hand; the hand-transfer in `_execute_play_minor` precedes
`on_play`, so the pushed build resolves for the player who played it).

A free, MANDATORY granted Build-Stable on play (mirrors Mini Pasture's restricted granted
build, with the build-stable push itself mirroring Groom's `PendingBuildStables(cost, cap=1)`):

- on_play pushes the reusable `PendingBuildStables` primitive with `cost=Resources()` (the
  stable itself is FREE — "the stable costs you nothing"), `max_builds=1`, and
  `build_stables_action=False`. The 1-wood card cost is paid by the play-minor path, NOT by
  this build (`cost=Resources()`). The primitive's enumerator handles cell selection and only
  offers `Proceed` once `num_built >= 1`, so with `max_builds=1` the build is effectively
  forced — there is no decline path at `num_built=0` — exactly matching "Immediately build 1
  stable".
- `build_stables_action=False` — this is a card effect, not the literal "Build Stables" action,
  so future action-scoped stable-build triggers (e.g. Stable Tree) do NOT fire on it. Mirrors
  Mini Pasture's `build_fences_action=False`. (Today this skip-field has no trigger consumer; it
  is the correct forward-compat choice.)
- Because the grant offers ONLY `CommitBuildStable` cells (no Proceed) while `num_built=0`, an
  empty action set would deadlock if no stable could be built when the card is played.
  Therefore the playability prereq — a legal empty cell AND >= 1 stable in supply, checked via
  `_can_build_stable` with a FREE cost — is load-bearing and anticipates the grant exactly,
  exactly as Mini Pasture's prereq does for its fence grant.

Cards-only (`build_stables_action` is an unrestricted-default skip-field). Family byte-identical,
C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stable"
FRAME_ID = "card:stable"


def _can_build_free_stable(state: GameState, idx: int) -> bool:
    """Playability: a FREE stable is buildable (>= 1 stable in supply AND a legal empty cell;
    the free cost is trivially payable). Anticipates the grant exactly."""
    return _can_build_stable(state, state.players[idx], Resources())


def _on_play(state: GameState, idx: int) -> GameState:
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id=FRAME_ID,
        cost=Resources(), max_builds=1, build_stables_action=False))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               prereq=_can_build_free_stable, passing_left=True, on_play=_on_play)
