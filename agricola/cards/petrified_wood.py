"""Petrified Wood (minor improvement, D6; Dulcinaria Expansion; players -).

Card text: "Immediately exchange up to 3 wood for 1 stone each."

Prerequisite: "2 Occupations". Cost: none. PASSING (traveling minor —
`passing_left='X'` in the catalog: the card moves to the opponent's hand; the
hand-transfer happens in `_execute_play_minor` BEFORE `on_play` runs, so the
exchange resolves for the player who played it).

Category 2 (on-play one-shot) with an OPTIONAL amount choice. "up to 3 ... for
1 stone each" is a strict 1:1 trade of wood for stone, the player choosing how
many to convert — 0 (a full decline) through min(3, wood on hand).

Surfaced WIDE via the minor play-variant seam (`register_play_minor_variant`),
per the standing "on-play optional choices surface wide" ruling: one
`CommitPlayMinor(variant="<n>")` per amount, the n wood riding the variant
SURCHARGE (folded into the play payment at enumeration, so the debit and its
affordability are the enumerator's standard machinery), and the variant-aware
`on_play` granting the n stone. The "0" variant is the zero-surcharge decline
the seam requires; with 0 wood it is the sole variant (a no-op play the agent
auto-resolves via singleton-skip). The amounts are capped at the wood actually
on hand so no dead-end variant is ever offered (the card itself is cost-free,
so enumeration-time wood equals resolution-time wood).

History: originally implemented DEEP (an on-play `PendingCardChoice` amount
frame) because it predated the seam (built 2026-07-06 for Facades Carving);
migrated wide 2026-07-13 at the user's direction — the 2026-07-13 session's
audit found it was the seam's intended shape verbatim. No event hooks, no
scoring, no card state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "petrified_wood"
MAX_EXCHANGE = 3


def _variants(state: GameState, idx: int):
    """One variant per exchange amount 0..min(3, wood on hand); the n wood is
    the variant surcharge, the n stone its on_play benefit."""
    n_max = min(MAX_EXCHANGE, state.players[idx].resources.wood)
    return [(str(n), Resources(wood=n)) for n in range(0, n_max + 1)]


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """Grant the chosen amount of stone (the wood was already debited as the
    variant surcharge folded into the play payment)."""
    n = int(variant)
    if n == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(stone=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, min_occupations=2, passing_left=True, on_play=_on_play)
register_play_minor_variant(CARD_ID, _variants)
