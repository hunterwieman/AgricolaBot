"""Barrow Pusher (occupation, A105; Artifex Expansion; players 1+).

Card text: "For each new field tile you get, you also get 1 clay and 1 food."

Category 3 (sub-action hook, automatic income). A mandatory, choice-free reward
per field tile acquired → an automatic effect (register_auto), not a FireTrigger.

It rides the `after_plow` event, which `_enter_after_phase` fires once per
PendingPlow commit, for the plowing player. `_execute_plow` is the only site that
creates a `CellType.FIELD` cell, so `after_plow` catches every field-tile
acquisition exactly once — a multi-field plow action (Cultivation, Mole Plow, …)
pushes one PendingPlow per field and so fires `after_plow` once per field, exactly
matching the card's per-field-tile reward. Eligibility is unconditional: the event
firing already means a field tile was just created, so there is nothing to gate.

Played via Lessons; its on-play is a no-op. See CARD_BATCH_TRIAGE.md (A105).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "barrow_pusher"


def _always(state: GameState, idx: int) -> bool:
    # The after_plow event firing already means a field tile was just created;
    # there is nothing to gate.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    # PER-TILE payout: the after_plow flip fires ONCE per PendingPlow frame, but a
    # multi-shot granted plow (Swing/Turnwrest/Wheel Plow, "plow up to N fields")
    # commits several tiles under one frame. The frame is on top at the flip;
    # its num_plowed counts card-grant commits (0 = the base single-shot plow,
    # which is always exactly one tile). Fixed 2026-07-14 — the flat +1 underpaid
    # a multi-tile grant.
    top = state.pending_stack[-1]
    tiles = max(getattr(top, "num_plowed", 0), 1)
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=tiles, food=tiles))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_plow", CARD_ID, _always, _apply)
