"""Mountain Plowman (occupation, E164; Ephipparius Expansion; players 4+; Livestock
Provider).

Card text (verbatim): "Each time you plow at least 1 field tile, you get 1 sheep
for each field tile that you just plowed."
No clarifications / errata printed.

A per-field-tile animal grant on the plow sub-action. The reward reads WHAT was
plowed (the number of tiles), so it fires in the AFTER phase of the plow —
`after_plow`, which `_enter_after_phase` fires once per PendingPlow commit for the
plowing player. This is the Barrow Pusher shape: `_execute_plow` is the only site
that creates a field tile, so `after_plow` catches every acquisition exactly once,
and a multi-tile granted plow (Swing/Turnwrest/Wheel Plow, "plow up to N fields")
commits several tiles under ONE PendingPlow frame and fires `after_plow` once with
the frame's `num_plowed` counting the extra commits. The reward is MANDATORY and
choice-free (1 sheep per tile) → an automatic effect (`register_auto`), not a
FireTrigger.

Per-tile count — `max(top.num_plowed, 1)`: `num_plowed == 0` is the base
single-shot plow (exactly one tile); a granted multi-plow carries the extra tiles
in `num_plowed`. The sheep are granted through `helpers.grant_animals` in ONE
synchronous shot (never per-tile prompts), so an over-capacity farm is reconciled
by the accommodation barrier at the next decision boundary.

Played via Lessons; no on-play effect. The registry is empty in the Family game,
so it stays byte-identical and the C++ gates are untouched. See barrow_pusher.py
(the identical `after_plow` per-tile shape) and shepherds_crook.py (grant_animals).
"""
from __future__ import annotations

from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "mountain_plowman"


def _eligible(state: GameState, idx: int) -> bool:
    # The after_plow event firing already means a field tile was just created;
    # there is nothing to gate.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    """+1 sheep PER field tile plowed. The PendingPlow frame is on top at the
    after-flip; `num_plowed` counts card-grant commits (0 = the base single plow =
    one tile), so the reward is `max(num_plowed, 1)` sheep."""
    top = state.pending_stack[-1]
    tiles = max(getattr(top, "num_plowed", 0), 1)
    return grant_animals(state, idx, Animals(sheep=tiles))


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
register_auto("after_plow", CARD_ID, _eligible, _apply)
