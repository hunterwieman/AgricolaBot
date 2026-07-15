"""Shed Builder (occupation, E-deck #114; Ephipparius Expansion; players 1+).

Card text: "When you build your 1st and 2nd stable, you get 1 grain. When you
build your 3rd and 4th stable, you get 1 vegetable. (This does not apply to
stables you have already built.)"

Payouts keyed to the LIFETIME ordinal of each stable the owner builds: the 1st
and 2nd stables ever built pay 1 grain each, the 3rd and 4th pay 1 vegetable
each. Build Stables is ONE action (CARD_AUTHORING_GUIDE §2 — no per-piece
events exist), so the payout is computed per ACTION at the after boundary:
an `after_build_stables` automatic effect. When that event fires, the
`PendingBuildStables` host (now phase="after") is still on top of the stack
(`_enter_after_phase` flips the frame in place, then fires the autos), so the
effect reads `frame.num_built` — the stables built this action — directly off
the top frame. The lifetime after-count is `helpers.stables_built(farmyard)`
(the grid-derived built count — NEVER `4 − stables_in_supply`, which would
double-count card removals like Market Stall C54's spent stable piece); the
before-count is `after − num_built`. Each ordinal k in (before, after] pays:
k ≤ 2 → +1 grain; k ∈ {3, 4} → +1 vegetable.

The parenthetical ("This does not apply to stables you have already built.")
needs NO play-time snapshot: ordinals only increase, so stables that existed
before the card was played consumed their ordinals (1..before) and can never
be crossed again — a player who already built 2 stables and then plays this
card gets a vegetable for the next stable (their lifetime 3rd), never grain.

Source-agnostic: "when you build your Nth stable" doesn't care which action
built it. Card-granted stable builds (a `PendingBuildStables` pushed by a
card, e.g. Stallwright/Stablehand's free stable) flow through the same host
and fire the same `after_build_stables` event (`trigger_event` derives the
event from the frame's PENDING_ID), so they pay too.

Own-action only (`any_player=False`, the register_auto default): the autos
fire for the acting player, so an opponent's stable builds never pay the
owner — matching "you build".

See millwright.py (the existing `after_build_stables` auto consumer) for the
event idiom.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import stables_built
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "shed_builder"


def _payout(state: GameState, idx: int) -> GameState:
    """Pay 1 grain per lifetime-ordinal-1st/2nd stable and 1 vegetable per
    lifetime-ordinal-3rd/4th stable built by THIS action.

    Fired at the after-flip, so the (phase="after") `PendingBuildStables`
    frame is still on top: `num_built` = stables built this action; the grid
    already contains them, so `stables_built` is the lifetime after-count.
    """
    after = stables_built(state.players[idx].farmyard)
    num_built = state.pending_stack[-1].num_built
    before = after - num_built
    # Ordinals k in (before, after] with k <= 2 pay grain; k in {3, 4} pay veg.
    grain = max(0, min(after, 2) - min(before, 2))
    veg = max(0, min(after, 4) - max(before, 2))
    if grain == 0 and veg == 0:
        return state   # nothing due (e.g. 4 stables already built) — converge
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=grain, veg=veg))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# Pure passive-payout occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_auto("after_build_stables", CARD_ID, lambda state, idx: True, _payout)
