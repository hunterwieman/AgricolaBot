"""UI-facing live per-card state for played cards (web UI only).

Some cards carry per-player `CardStore` state that a human needs to see but cannot
read off the visible board. Two kinds get surfaced:

  - **History-derived victory points** — bonus points banked at play time or
    accumulated across events (harvest conversions, per-use counters, play-time
    gates), so their value depends on *when / how often* the card was used and can't
    be reconstructed from the final board. The tell is structural: these cards store
    their score in `card_state`. They show a "+X vp" emblem (the live points-if-the-
    game-ended-now, reusing the card's own scoring term so it can't drift). Cards
    whose bonus points ARE derivable from public state — Loom (sheep owned),
    Stable Architect (unfenced stables) — compute from the board and are EXCLUDED:
    the player reads those straight off it. The full classification of every scoring
    card lives in HISTORY_VP_CARDS / PUBLIC_VP_CARDS below.

  - **Accumulated resources / remaining-use counters** — Interim Storage (goods
    held on the card), Moldboard Plow (plows left). These show a plain state badge.

All of this is public information (played cards are a face-up tableau, and the
history both players observed), so it is shown for both seats. The engine never
reads any of this — it is consumed only by `play_web.py`'s card serialization.
"""
from __future__ import annotations

from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS

# Every card whose end-game scoring term reads a banked / snapshot value out of
# `card_state` — i.e. its points depend on WHEN or HOW OFTEN it was used and cannot
# be reconstructed from the visible board. These show the "+X vp" emblem (the live
# points-if-the-game-ended-now, via the card's own scoring term).
#
# The distinguishing rule is structural: a card stores its score in `card_state`
# precisely because that score is NOT recomputable from public state. So this set is
# exactly {scoring cards that read card_state}, and its complement below is
# {scoring cards that compute from the board}. `test_card_display` asserts the two
# sets partition every registered scoring term, so adding a new scoring card without
# classifying it FAILS the suite rather than silently going emblem-less.
HISTORY_VP_CARDS: frozenset[str] = frozenset({
    "baking_sheet", "beer_keg", "beer_stein", "big_country", "bucksaw",
    "clay_deposit", "cube_cutter", "elephantgrass_plant", "furniture_carpenter",
    "home_brewer", "loppers", "mantlepiece", "rustic", "truffle_slicer", "tutor",
    "wood_rake",
})

# History-derived scoring cards that DON'T take the emblem, because the live
# points-if-scored-now would leak a hidden fact. Butler is the sole case: it scores
# 4 iff (played by round 11) AND (rooms > people now); a "+4/+0" emblem would reveal
# the play-round gate to the OPPONENT in any state where rooms currently exceed
# people. Instead the owner sees the round it was played (the actually-useful fact),
# owner-only — see `_PRIVATE_STATE_FORMATTERS`.
PRIVATE_HISTORY_CARDS: frozenset[str] = frozenset({"butler"})

# Scoring cards whose points ARE derivable from the current public board (animals,
# rooms, fields, resources, majors) — the player reads them straight off the board,
# so NO emblem. Listed explicitly only so the partition test can catch an
# unclassified new card; nothing consumes this set at runtime.
PUBLIC_VP_CARDS: frozenset[str] = frozenset({
    "artisan_district", "cookery_outfitter", "debt_security", "fellow_grazer",
    "fodder_chamber", "greening_plan", "lantern_house", "loom", "lord_of_the_manor",
    "manger", "milking_stool", "pottery_yard", "schnapps_distillery", "soldier",
    "stable_architect", "storeroom", "summer_house", "wool_blankets",
})

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
    """A PUBLIC live-state badge for a resource/counter card, or None. Shown to both
    seats (goods on a card / field tiles on a card are visible to everyone)."""
    fn = _STATE_FORMATTERS.get(card_id)
    return fn(player_state) if fn is not None else None


# --- Owner-only badges (a hidden fact the owner may have forgotten) ---------------


def _butler(ps) -> str | None:
    n = ps.card_state.get("butler")
    if not n:  # not yet played
        return None
    if n > 11:  # played too late — the 4-point bonus can never trigger
        return f"Played round {n} — bonus forfeited"
    return f"Played round {n}"


_PRIVATE_STATE_FORMATTERS = {
    "butler": _butler,
}


def private_state_text(card_id: str, player_state) -> str | None:
    """A PRIVATE live-state badge shown ONLY on the owner's own view (same reveal
    rule as a hand). Used where the live value is a hidden fact that a "+X vp" emblem
    would leak to the opponent — Butler's play-round. Or None."""
    fn = _PRIVATE_STATE_FORMATTERS.get(card_id)
    return fn(player_state) if fn is not None else None
