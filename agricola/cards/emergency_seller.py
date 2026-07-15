"""Emergency Seller (occupation, E106; Ephipparius Expansion; players 1+).

Card text: "When you play this card, you can immediately turn as many building
resources into food as you have people: Each wood or clay is worth 2 food; each
reed or stone is worth 3 food."

An on-play OPTIONAL conversion, modeled as a PLAY-VARIANT occupation (the Roof
Ballaster mechanism — specs.PLAY_OCCUPATION_VARIANTS): playing Emergency Seller
surfaces one CommitPlayOccupation per convertible multiset (w, c, r, s) with
w + c + r + s <= people_total and each component capped by the resources on
hand — INCLUDING the all-zero multiset, which is the decline (ruling 17: on-play
optional choices decline WIDE; the zero variant keeps the card always playable
when its base play cost is). The converted resources are the variant's SURCHARGE
(folded into the play cost by the enumerator/executor, so affordability is
automatic); the food is granted by the variant-aware on_play.

User decision (2026-07-14): "surfaced WIDE with FULL enumeration — every
convertible multiset is its own play variant"; the user explicitly approved the
worst case (~126 variants at 5 people with abundant resources).

Variant encoding: "w{w}c{c}r{r}s{s}" (e.g. "w1c0r2s0"). Food granted:
2*(w + c) + 3*(r + s). Played via Lessons (or any occupation-play route).
"""
from __future__ import annotations

import re

from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "emergency_seller"

_VARIANT_RE = re.compile(r"w(\d+)c(\d+)r(\d+)s(\d+)")


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """Every convertible multiset (w, c, r, s): total capped by people_total, each
    component capped by the matching resource on hand. Each variant's SURCHARGE is
    the converted resources themselves — the play-occupation enumerator folds it
    into the base play cost, so a variant the player cannot pay for is filtered
    there. The all-zero variant (no conversion) is always present, so the list is
    never empty and the card is always playable when its base cost is."""
    p = state.players[idx]
    res = p.resources
    cap = p.people_total
    out: list[tuple[str, Resources]] = []
    for w in range(min(cap, res.wood) + 1):
        for c in range(min(cap - w, res.clay) + 1):
            for r in range(min(cap - w - c, res.reed) + 1):
                for s in range(min(cap - w - c - r, res.stone) + 1):
                    out.append((
                        f"w{w}c{c}r{r}s{s}",
                        Resources(wood=w, clay=c, reed=r, stone=s),
                    ))
    return out


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the food for the chosen conversion: 2 food per wood/clay, 3 per
    reed/stone. The converted resources are NOT debited here — they ride as the
    variant's surcharge, folded into the play cost and debited by
    `_execute_play_occupation` before this on_play runs. The zero variant (the
    decline) grants nothing."""
    if variant is None:
        return state
    m = _VARIANT_RE.fullmatch(variant)
    w, c, r, s = (int(g) for g in m.groups())
    food = 2 * (w + c) + 3 * (r + s)
    if food == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
