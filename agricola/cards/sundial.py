"""Sundial (minor improvement, E26; Ephipparius Expansion; Actions Booster).

Card text (verbatim): "At the end of the work phases in rounds 7 and 9, you can
take a "Sow" action without placing a person."
Cost: 1 Wood. No prerequisite. No printed VPs.

TIMING — "at the end of the work phases in rounds 7 and 9" is the round-end
ladder's ``end_of_work`` rung (user ruling 2026-07-14,
``agricola/cards/round_end.py``: position 0 — still during the work phase, once
every worker is placed), latched to rounds 7 and 9 by the bearer's own
eligibility (``round_number in {7, 9}``; at the ladder, ``round_number`` still
names the round just completing). Rounds 7 and 9 are harvest rounds — the
round-end ladder runs BEFORE the harvest, so the grant precedes that harvest.

THE GRANT — "you can take a 'Sow' action without placing a person" is an
OPTIONAL trigger ("you can"). Firing pushes a FULL ``PendingSow`` (Master
Renovator's exact grant shape — a bare ``PendingSow`` with the default
``max_fields=0``, i.e. UNCAPPED: a complete Sow action, every empty field
sowable), carrying this card's provenance. "Without placing a person" is
inherent — the window trigger involves no worker. Declining is the window's
``Proceed`` (no SkipTrigger); once-per-window is the frame's
``triggers_resolved``, and rounds 7 and 9 are separate window frames so the
card fires in each. Eligibility requires a legal sow (``_can_sow``) so the
grant is never a dead-end.

Cost "1 Wood" → ``cost=Cost(resources=Resources(wood=1))``.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_sow
from agricola.pending import PendingSow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "sundial"
_ROUNDS = frozenset({7, 9})


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"...in rounds 7 and 9" + a legal sow exists (never a dead-end).
    Ownership is the window machinery's gate; once-per-window is the frame's
    ``triggers_resolved``."""
    return state.round_number in _ROUNDS and _can_sow(state.players[idx])


def _apply(state: GameState, idx: int) -> GameState:
    """Push the granted full Sow action (uncapped ``PendingSow``, the Master
    Renovator grant shape)."""
    return push(state, PendingSow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))

# The optional full Sow on the round-end ladder's end_of_work rung, latched to
# rounds 7 and 9.
register("end_of_work", CARD_ID, _eligible, _apply)
