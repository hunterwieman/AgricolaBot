"""Stablehand (occupation, D89; Dulcinaria Expansion; players 1+).

Card text: "Each time you build at least 1 fence, you can also build a stable
without paying wood for the stable."

Category 5 (granted sub-action) on the build-fences hook. Structurally this is
the build-fences twin of Mining Hammer (which grants the same free stable on each
*renovate*):

- **on_play** → no effect. Like every occupation it is played via Lessons, but its
  on-play effect is a no-op (`register_occupation` requires a Callable — see
  Stable Architect).
- **each build-fences action** → an OPTIONAL trigger (`register`, not
  `register_auto` — a granted sub-action is the player's choice and pushes a
  primitive) on `after_build_fences` whose apply_fn pushes the existing
  `PendingBuildStables` primitive with a FREE cost (`Resources()`) and a cap of 1
  build.

"Each time you build at least 1 fence" is satisfied **by construction** at the
after-build-fences flip: that after-phase is only reached via `Proceed`, which
itself requires `pastures_built >= 1` (≥1 fence built), so no extra fence-count
guard is needed — see Loppers, which hooks the same event for the same reason.
The grant is **once per build-fences action**, not once per individual fence
piece: `_apply_fire_trigger` stamps `triggers_resolved | {card_id}` before
applying and `_eligible` reads it, so the card fires at most once per action.

Eligibility gates on a free stable actually being buildable (`_can_build_stable`
with the zero cost), so it never grants a dead-end (CARD_AUTHORING_GUIDE §2).

See mining_hammer.py (the renovate twin) and loppers.py (the other
`after_build_fences` optional trigger).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stablehand"
_FREE = Resources()


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the free stable only when one can actually be built and the grant
    hasn't already fired this build-fences action. Never a dead-end."""
    return (CARD_ID not in triggers_resolved
            and _can_build_stable(state, state.players[idx], _FREE))


def _apply(state: GameState, idx: int) -> GameState:
    """Grant one free (no-wood) stable build via the shared primitive."""
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id="card:stablehand",
        build_stables_action=False,  # user ruling 75, 2026-07-21: a card-effect build, not the named action (§9.6)
        cost=_FREE, max_builds=1,
    ))


# Pure granted-sub-action occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register("after_build_fences", CARD_ID, _eligible, _apply)
