"""Apiary (minor improvement, E23; Ephipparius Expansion; Actions Booster).

Card text (verbatim): "At the end of each work phase, you can sow exactly 1
crop on 1 field."
Cost: none (free). Prerequisite: "4 Occupations". No printed VPs.

TIMING — "at the end of each work phase" is the round-end ladder's
``end_of_work`` rung (user ruling 2026-07-14, ``agricola/cards/round_end.py``:
position 0 — still during the work phase, running once every worker is placed;
the rung Master Renovator / Iron Hoe use).

THE GRANT — "you can sow exactly 1 crop on 1 field" is an OPTIONAL trigger
("you can"). Firing pushes a ``PendingSow`` with ``max_fields=1`` — the
partial-sow cap that limits the commit to grain+veg <= 1 field (the PendingSow
"granted partial sow" contract), i.e. exactly one field is sown. It is the
generic (not ``crops_only``) sow: a bare "sow" grant, so no crop restriction
beyond the 1-field cap. Declining is the window's ``Proceed`` (no SkipTrigger);
once-per-window is the frame's ``triggers_resolved``. Eligibility requires a
legal sow (``_can_sow`` — an empty field plus a seed in supply, or a card-field
sow) so the grant is never a dead-end.

Prerequisite "4 Occupations" → ``min_occupations=4``.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_sow
from agricola.pending import PendingSow, push
from agricola.state import GameState

CARD_ID = "apiary"


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """A legal sow exists (never a dead-end). Ownership is the window
    machinery's gate; once-per-window is the frame's ``triggers_resolved``."""
    return _can_sow(state.players[idx])


def _apply(state: GameState, idx: int) -> GameState:
    """Push the granted single-field sow ("exactly 1 crop on 1 field" =
    ``max_fields=1``). "Without placing a person" is inherent — the window
    trigger involves no worker."""
    return push(state, PendingSow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", max_fields=1))


register_minor(CARD_ID, min_occupations=4)

# The optional single-field sow on the round-end ladder's end_of_work rung.
register("end_of_work", CARD_ID, _eligible, _apply)
