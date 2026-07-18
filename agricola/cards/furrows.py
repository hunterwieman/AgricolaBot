"""Furrows (minor improvement, D3; Dulcinaria Expansion; traveling/passing).

Card text (verbatim): "You can immediately sow in exactly 1 field."
Cost: none. Prerequisite: none. VPs: none. PASSING (traveling minor —
``passing_left`` is "X" in the data): after its on-play effect the card is
passed to the OPPONENT's hand, never kept in the tableau.

Timing / firing kind — an on-play OPTIONAL granted sub-action (a "Sow"
action). "You can" makes it declinable; a granted sub-action is optional even
when worded as a command (CARD_AUTHORING_GUIDE §1 step 4). It composes the
engine's existing sow primitive; it invents nothing.

USER RULINGS (quoted verbatim from the governing rulings):
- Ruling 66 (2026-07-17): the on-play "immediately" adds/changes nothing here
  — the sow happens as the card's ordinary on-play effect.
- Ruling 48 (2026-07-12, standing): "a GENERIC 'Sow' grant — even limited ('for
  exactly 1 field': Chief Forester A115, Furrows D3, Changeover D71) — may
  target wood/stone card-fields" (Furrows is named in the ruling's own list).
  So the sow is pushed with ``crops_only=False`` (the default), and the
  "exactly 1 field" cap "consumes exactly ONE field-unit of any capped sow's
  budget regardless of stacks".

SHAPE — WIDE (play-variant), not the wrapper. Per the wide-vs-wrapper guideline
(CARD_ENGINE_IMPLEMENTATION.md §6): the grant's eligibility is exact BEFORE the
card is owned — Furrows creates no sowing capability, no cell, and no discount,
so a sow is possible iff the player already has a seed + an empty board field or
a sowable card-field. And any grant on a PASSING card cannot use an
ownership-gated ``after_play_minor`` trigger: the card leaves the tableau (into
the opponent's hand) before the after-phase, so the trigger's ``_owns`` gate
would fail and it would never fire (the Dwelling Plan passing bug). So the
take-or-decline is fused into the play commit via the minor play-variant seam
(``register_play_minor_variant``): a zero-surcharge "sow" variant, offered only
when a sow is possible NOW, and a zero-surcharge "skip" variant, always present
(so ``variants_fn`` is never empty, the card is always playable, and declining
the sow is itself a legal play).

The play path (`_execute_play_minor`) debits the (empty) cost, passes the card
to the opponent's hand, THEN runs ``on_play(state, idx, variant)`` — so the sow
resolves for the player who played it while the card already sits in the
opponent's hand.
  - "sow"  -> push ``PendingSow(max_fields=1)``: "exactly 1 field" is the
             one-field cap (the sow enumerator enforces
             ``grain + veg + cards_touched <= max_fields``).
  - "skip" -> no-op (the declined sow).

Family-inertness: minors exist only under GameMode.CARDS; the
PLAY_MINOR_VARIANTS registry entry is card-only, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.legality import _can_sow
from agricola.pending import PendingSow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "furrows"


def _variants(state: GameState, idx: int):
    """A zero-surcharge "skip" (ALWAYS — so the list is never empty and the card
    is always playable) + a zero-surcharge "sow" offered ONLY when a sow is
    possible right now. ``_can_sow(p)`` is the engine's own sow-availability
    predicate: a seed in supply + an empty board field, OR a sowable card-field
    (rulings 45-48). Both surcharges are ``Resources()`` — Furrows has no cost
    and the grant is free."""
    out = [("skip", Resources())]
    if _can_sow(state.players[idx]):
        out.append(("sow", Resources()))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """The chosen route. "sow" grants a one-field-capped "Sow" action
    (``PendingSow(max_fields=1)``; ``crops_only`` stays its default False per
    ruling 48 — wood/stone card-fields are legal targets for a generic sow
    grant); "skip" declines (no-op). The card has already been passed to the
    opponent's hand by ``_execute_play_minor`` before this runs."""
    if variant == "sow":
        return push(state, PendingSow(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}", max_fields=1))
    return state


# Cost: none; no prerequisite; no printed VP; PASSING (travels to the opponent).
register_minor(
    CARD_ID,
    cost=Cost(),
    passing_left=True,
    on_play=_on_play,
)

# The wide on-play optional grant (play-variant seam): "sow" (when sowable) or
# "skip" (always), each a zero-surcharge route folded into the play commit.
register_play_minor_variant(CARD_ID, _variants)
