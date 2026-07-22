"""Livestock Feeder (occupation, deck C #86; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 grain. Each
grain in your supply can hold 1 animal of any type. (these animals count as
accommodated on your farm.)"

Implementation per ruling 74 (user, 2026-07-21; CARD_DEFERRED_PLANS.md):

- **Capacity**: "one FLEXIBLE slot per grain in supply — `register_flexible_slots
  ("livestock_feeder", fn)` where fn(player_state) -> the player's grain count.
  This is the Petting Zoo seam; cache safety is automatic (the frontier caches key
  on `extract_slots` outputs)." Each slot holds 1 animal of any type, mixable
  across slots — exactly the printed "1 animal of any type", and the parenthetical
  "(these animals count as accommodated on your farm)" is the flexible-slot model
  itself.
- **Eviction is STRUCTURAL, not per-seam** (user approved): grain is spent at many
  seam-less sites (sow, bake, feeding, card costs, liquidation), so rather than
  flagging every grain-spend seam, the accommodation barrier
  (`engine._reconcile_accommodation`) consults the volatile-capacity registry
  (`register_volatile_capacity`) at every agent-decision boundary; this card
  registers a re-check that reports whether its capacity input (grain) fell since
  the last boundary.

The watermark discipline (ruling 74's dropped_fn contract): `_grain_dropped(state,
idx)` (a) self-gates on ownership, returning (state, False) unchanged for a
non-owner; (b) keeps the last-boundary grain count in this card's own CardStore
entry; (c) reports dropped=True iff current grain < the stored value; (d)
refreshes the stored value to the current grain at EVERY owner boundary — writing
only when the value actually changed, so quiet boundaries return the state object
unchanged; (e) treats a missing stored value as equal to current (the first
boundary after play stores it and reports no drop).

Soundness rationale (why boundary-only re-checks suffice): capacity through this
card only drops when grain drops, and every animal INCREASE already reconciles
through its own accommodation path (grant_animals' flag, the animal-market
frames, the breeding frontier) — so "grain has not fallen since the last
boundary" implies no new violation at that boundary. The refresh in (d) is
load-bearing in BOTH directions: an upward refresh skipped after a grain gain
would leave a stale LOW watermark that masks a later drop back through it (the
player houses an animal on the new slot, the slot vanishes, and current == stale
watermark hides the eviction); the downward refresh after a reported drop is what
keeps the barrier from re-reporting the same drop at every subsequent boundary.

On play: 1 grain, a plain resources add (the immediate one-shot). No other seams.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import (
    register_flexible_slots,
    register_volatile_capacity,
)
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "livestock_feeder"


def _with_player(state: GameState, idx: int, p: PlayerState) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _on_play(state: GameState, idx: int) -> GameState:
    """On play: immediately get 1 grain."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return _with_player(state, idx, p)


def _slots(p: PlayerState) -> int:
    """One flexible (any-type, capacity-1, mixable) slot per grain in supply."""
    return p.resources.grain


def _grain_dropped(state: GameState, idx: int) -> tuple[GameState, bool]:
    """Volatile-capacity re-check, run at every decision boundary (ruling 74).

    Watermark discipline (module docstring): self-gate on ownership; store the
    last-boundary grain count in CardStore; report dropped=True iff current
    grain < stored; refresh the stored value at every owner boundary, writing
    only on change; a missing stored value counts as equal to current.
    """
    p = state.players[idx]
    if CARD_ID not in p.occupations:            # (a) non-owner: untouched
        return state, False
    grain = p.resources.grain
    stored = p.card_state.get(CARD_ID)
    if stored is None:                          # (e) first boundary after play
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, grain))
        return _with_player(state, idx, p), False
    dropped = grain < stored                    # (c)
    if grain != stored:                         # (d) refresh, write only on change
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, grain))
        state = _with_player(state, idx, p)
    return state, dropped


register_occupation(CARD_ID, _on_play)
register_flexible_slots(CARD_ID, _slots)
register_volatile_capacity(CARD_ID, _grain_dropped)
