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
    "ale_benches",
    "beer_tent_operator", "champion_breeder", "estate_master", "nutrition_expert",
    "pig_owner", "wealthy_man",
    "asparagus_knife",
    "baking_sheet", "beaver_colony", "beer_keg", "beer_stein", "beer_table", "bellfounder",
    "big_country",
    "blighter", "clutterer", "cookery_lesson", "curator",
    "bucksaw", "clay_deposit", "craft_brewery", "cube_cutter", "elephantgrass_plant",
    "facades_carving",
    "furniture_carpenter", "home_brewer", "hook_knife", "loppers", "mantlepiece",
    "museum_caretaker", "paintbrush", "prodigy", "rod_collection", "rustic",
    "sugar_baker", "swimming_class",
    "truffle_slicer", "tutor", "uncaring_parents", "upholstery", "wood_rake",
})

# History-derived scoring cards that DON'T take the emblem, because the live
# points-if-scored-now would leak a hidden fact. Butler is the sole case: it scores
# 4 iff (played by round 11) AND (rooms > people now); a "+4/+0" emblem would reveal
# the play-round gate to the OPPONENT in any state where rooms currently exceed
# people. Instead the owner alone sees whether the bonus is still available (the
# play-round gate) — see `_PRIVATE_STATE_FORMATTERS`. Earthenware Potter (D99,
# implemented 2026-07-06) is the same shape: its bonus is gated on having been
# played by round 4, a hidden fact only the owner should see.
PRIVATE_HISTORY_CARDS: frozenset[str] = frozenset({"butler", "earthenware_potter"})

# Scoring cards whose points ARE derivable from the current public board (animals,
# rooms, fields, resources, majors) — the player reads them straight off the board,
# so NO emblem. Listed explicitly only so the partition test can catch an
# unclassified new card; nothing consumes this set at runtime.
PUBLIC_VP_CARDS: frozenset[str] = frozenset({
    "braggart", "chimney_sweep", "housemaster",
    "artisan_district", "cookery_outfitter", "debt_security", "fellow_grazer",
    "fodder_chamber", "greening_plan", "land_register", "lantern_house", "loom",
    "lord_of_the_manor", "manger", "mayor_candidate", "milking_stool", "misanthropy",
    "nave", "ox_skull",
    "pottery_yard", "schnapps_distillery", "soldier", "stable_architect", "storeroom",
    "summer_house", "wool_blankets",
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


def _material_hub(ps) -> str | None:
    from agricola.cards.material_hub import CARD_ID

    stock = ps.card_state.get(CARD_ID)
    if not stock:  # None, or an empty Resources() (fully paid out)
        return None
    return "Holding: " + _fmt_resources(stock)


# --- Per-card action-variant labelers (the web-UI label pass, 2026-07-12) ---
# The user's style directive: MECHANICAL and terse — "the player can interpret
# meaning from the card description" — with the card name prepended by the web
# layer and zero counts omitted (e.g. "Shepherd's Whistle: activate, keep
# sheep=2, boar=1"). A labeler maps ONE card's variant encoding to that style;
# unregistered cards keep the web layer's generic fallbacks (the static route
# labels, the count-vector prettifier, raw).

ACTION_LABELERS: dict = {}


def register_action_labeler(card_id: str, fn) -> None:
    """Register `card_id`'s variant labeler — `fn(variant: str) -> str | None`
    (None = fall through to the generic paths). Pure string→string: every
    variant encoding carries its own numbers."""
    ACTION_LABELERS[card_id] = fn


def variant_label(card_id: str, variant: str):
    """The card-aware variant label, or None when no labeler claims it."""
    fn = ACTION_LABELERS.get(card_id)
    return fn(variant) if fn is not None else None


def _card_field_badge(card_id: str, ps) -> str | None:
    """The planted contents of a card-field (rulings 45-47, 2026-07-12), one
    " | "-separated part per non-empty stack ("3 wood | 1 wood"; a mixed
    Heresy-Teacher stack reads "3 grain + 1 veg"). None when nothing is
    planted — crops on a card are public, like crops on a board field."""
    from agricola.cards.card_fields import GOODS, card_field_stacks

    parts = []
    for stack in card_field_stacks(ps, card_id):
        bits = [f"{n} {g}" for g, n in zip(GOODS, stack) if n]
        if bits:
            parts.append(" + ".join(bits))
    return ("Planted: " + " | ".join(parts)) if parts else None


_STATE_FORMATTERS = {
    "interim_storage": _interim_storage,
    "material_hub": _material_hub,
    "moldboard_plow": _moldboard_plow,
}


def state_text(card_id: str, player_state) -> str | None:
    """A PUBLIC live-state badge for a resource/counter card, or None. Shown to both
    seats (goods on a card / field tiles on a card are visible to everyone).
    Registered card-fields get the generic planted-contents badge."""
    fn = _STATE_FORMATTERS.get(card_id)
    if fn is not None:
        return fn(player_state)
    from agricola.cards.card_fields import CARD_FIELDS

    if card_id in CARD_FIELDS:
        return _card_field_badge(card_id, player_state)
    return None


# --- Owner-only badges (a hidden fact the owner may have forgotten) ---------------


def _butler(ps) -> str | None:
    n = ps.card_state.get("butler")
    if not n:  # not yet played
        return None
    # The play-round gate: eligible iff played by round 11, else the 4-point bonus
    # can never trigger. (The other condition — rooms > people — is on the board.)
    return "Bonus available" if n <= 11 else "Bonus forfeited"


def _earthenware_potter(ps) -> str | None:
    n = ps.card_state.get("earthenware_potter")
    if not n:  # not yet played
        return None
    # The play-round gate: the after-the-final-harvest clay-for-points buy is
    # eligible iff the card was played in round 4 or before (ruling 26,
    # 2026-07-06). The banked points live under a separate key and score
    # normally either way.
    return "Bonus available" if n <= 4 else "Bonus forfeited"


_PRIVATE_STATE_FORMATTERS = {
    "butler": _butler,
    "earthenware_potter": _earthenware_potter,
}


def private_state_text(card_id: str, player_state) -> str | None:
    """A PRIVATE live-state badge shown ONLY on the owner's own view (same reveal
    rule as a hand). Used where the live value is a hidden fact that a "+X vp" emblem
    would leak to the opponent — Butler's play-round. Or None."""
    fn = _PRIVATE_STATE_FORMATTERS.get(card_id)
    return fn(player_state) if fn is not None else None
