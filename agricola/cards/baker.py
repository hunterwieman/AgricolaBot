"""Baker (occupation, C107; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "When you play this card and at the start of each feeding
phase, you can take a "Bake Bread" action."

Both grants are "you can" — optional — and each declines at a WIDE decision
point per the standing invariant (optionality lives at the parent choice,
never inside the granted frame; the pushed PendingBakeBread itself is
committed once chosen):

1. **On play — the decline is the PLAY VARIANT (user ruling 17, 2026-07-05):**
   "play Baker and bake" and "play Baker, decline the bake" are two distinct
   play actions (`CommitPlayOccupation(card_id="baker", variant=…)`, the Roof
   Ballaster mechanism). The user rejected an after-play trigger home because
   it would let this bake interleave with OTHER after-play triggers in
   player-chosen order, which "when you play this card" does not license.
   The "bake" variant is offered only when a bake is currently usable
   (`_can_bake_bread`: a baking improvement + grain, or a card extension) —
   otherwise the sole variant is the plain declined play.
2. **At the start of each feeding phase** — an optional trigger on the
   `start_of_feeding` window: firing is the opt-in (it pushes the bake frame),
   `Proceed` declines. Positioned before the feeding payment, so the baked
   food is payable. Once per feeding phase via the frame's `triggers_resolved`
   ("a Bake Bread action", singular).

The granted bake is the REAL Bake Bread action — before/after-bake card hooks
(Potter Ceramics, Dutch Windmill, …) fire normally, unlike Winnowing Fan's
expressly not-a-bake conversion.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import (
    register_occupation,
    register_play_occupation_variant,
)
from agricola.cards.triggers import register
from agricola.legality import _can_bake_bread
from agricola.pending import PendingBakeBread, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "baker"
WINDOW_ID = "start_of_feeding"


def _variants(state: GameState, idx: int) -> list:
    """The two play routes — bake now (only when a bake is currently usable)
    or decline. No surcharge on either (the bake's grain cost is spent inside
    the bake itself)."""
    out = [("decline_bake", Resources())]
    if _can_bake_bread(state, state.players[idx]):
        out.insert(0, ("bake", Resources()))
    return out


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    if variant != "bake":
        return state                       # declined at the wide play choice
    return push(state, PendingBakeBread(
        player_idx=idx, initiated_by_id="card:baker"))


def _feed_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    return _can_bake_bread(state, state.players[idx])


def _feed_apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBakeBread(
        player_idx=idx, initiated_by_id="card:baker"))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
register(WINDOW_ID, CARD_ID, _feed_eligible, _feed_apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
