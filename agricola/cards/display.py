"""UI-facing live per-card state for played cards (web UI only).

Some cards carry per-player `CardStore` state that a human needs to see but cannot
read off the visible board. Two kinds get surfaced:

  - **History-derived victory points** — bonus points banked at play time or
    accumulated across harvests, so their value depends on *when/how* the card was
    used, not on final board state: Big Country, Mantelpiece, Tutor, Beer Keg,
    Furniture Carpenter. These show a "+X vp" emblem (the live points-if-the-game-
    ended-now). Cards whose bonus points ARE derivable from public state — Loom
    (sheep owned), Half-Timbered House (stone rooms) — are deliberately EXCLUDED:
    the player can read those straight off the board, so no emblem is needed.
    The emblem value reuses the card's own registered scoring term, so it can never
    drift from what is actually scored.

  - **Accumulated resources / remaining-use counters** — Interim Storage (goods
    held on the card), Moldboard Plow (plows left). These show a plain state badge.

All of this is public information (played cards are a face-up tableau, and the
history both players observed), so it is shown for both seats. The engine never
reads any of this — it is consumed only by `play_web.py`'s card serialization.
"""
from __future__ import annotations

from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS

# Card ids whose end-game bonus points are knowable ONLY from game history (the
# stored CardStore snapshot). See the module docstring for why public-info scoring
# cards (Loom, Half-Timbered House) are excluded.
HISTORY_VP_CARDS: frozenset[str] = frozenset(
    {"big_country", "mantlepiece", "tutor", "beer_keg", "furniture_carpenter"}
)

_SCORING_BY_ID: dict[str, "callable"] | None = None


def _scoring_fn(card_id: str):
    """The card's registered end-game scoring term, or None. Built lazily so this
    module doesn't depend on card-import order."""
    global _SCORING_BY_ID
    if _SCORING_BY_ID is None:
        _SCORING_BY_ID = {cid: fn for cid, fn in SCORING_TERMS}
    return _SCORING_BY_ID.get(card_id)


def bonus_vps(card_id: str, state, idx: int) -> int | None:
    """Live bonus VP for a history-derived card (points if the game ended now), or
    None if the card isn't one of them."""
    if card_id not in HISTORY_VP_CARDS:
        return None
    fn = _scoring_fn(card_id)
    return fn(state, idx) if fn is not None else None


# --- Resource / counter state badges --------------------------------------------

_RESOURCE_ORDER = ("wood", "clay", "reed", "stone", "food", "grain", "veg")


def _fmt_resources(r: Resources) -> str:
    return ", ".join(f"{getattr(r, f)} {f}" for f in _RESOURCE_ORDER if getattr(r, f))


def _interim_storage(ps) -> str | None:
    from agricola.cards.interim_storage import CARD_ID

    held = ps.card_state.get(CARD_ID)
    if not held:  # None, or an empty Resources()
        return None
    return "Holding: " + _fmt_resources(held)


def _moldboard_plow(ps) -> str | None:
    from agricola.cards.moldboard_plow import CARD_ID, _INITIAL_USES

    uses = ps.card_state.get(CARD_ID, _INITIAL_USES)
    return f"{uses} field-plow{'' if uses == 1 else 's'} left"


_STATE_FORMATTERS = {
    "interim_storage": _interim_storage,
    "moldboard_plow": _moldboard_plow,
}


def state_text(card_id: str, player_state) -> str | None:
    """A plain-text live-state badge for a resource/counter card, or None."""
    fn = _STATE_FORMATTERS.get(card_id)
    return fn(player_state) if fn is not None else None
