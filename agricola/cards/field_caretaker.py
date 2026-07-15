"""Field Caretaker (occupation, deck B #141; Bubulcus Expansion; players 3+).

Card text (verbatim): "When you play this card, you can immediately exchange
0/1/3 clay for 1/2/3 grain. This card is a field."
Category: Crop Provider. No printed VPs.

Two independent pieces, each an existing mechanism:

- **"This card is a field."** A plain card-field registration
  (`register_card_field`) — the shared machinery (`cards/card_fields.py`) does
  everything once the spec row exists. No restriction is printed, so it is a
  general field: sowable with grain (1 supply grain -> 3) OR vegetables (1 -> 2),
  exactly like a plowed board field, harvested by the field-phase take and
  counted as exactly 1 field by every field-count reader (ruling 45). Same shape
  as Artichoke Field / Patch Caregiver.

- **"you can immediately exchange 0/1/3 clay for 1/2/3 grain."** An OPTIONAL,
  tiered on-play exchange — the Roof Ballaster / Petrified Wood play-variant
  shape (`register_play_occupation_variant`). The printed slash-lists correlate:
  pay 0 clay -> 1 grain, 1 clay -> 2 grain, 3 clay -> 3 grain. Each tier's clay
  is the variant SURCHARGE (folded into the play payment and debited by the
  executor, liquidation-aware); the variant-aware `on_play` grants the matching
  grain. "you CAN exchange" is optional, so a zero-surcharge "decline" (grants
  nothing) is always offered alongside the tiers — the 0-clay tier gives a free
  grain and so dominates declining, but the decline honors the printed optionality
  (a granted exchange is never forced). The enumerator drops a tier the player
  cannot afford, so no dead-end is offered.

"immediately" is the ordinary on-play instant (the card-play moment), the same
reading Roof Ballaster / Petrified Wood use. Played via Lessons; card-only (the
card-field content lives in the default-empty CardStore) — the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "field_caretaker"

# (variant name, clay surcharge, grain granted) — the correlated slashes.
_TIERS = (("1", 0, 1), ("2", 1, 2), ("3", 3, 3))
_GRAIN_OF = {name: grain for name, _clay, grain in _TIERS}


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """A zero-surcharge decline (always) plus one route per exchange tier, its
    clay as the surcharge (affordability filtered by the play-occupation
    enumerator)."""
    out = [("decline", Resources())]
    for name, clay, _grain in _TIERS:
        out.append((name, Resources(clay=clay)))
    return out


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the tier's grain (the clay surcharge was already debited by the
    executor). `decline` grants nothing."""
    grain = _GRAIN_OF.get(variant, 0)
    if grain == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=grain))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_card_field(CARD_ID, stacks=1, sow_amounts=(("grain", 3), ("veg", 2)))
register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
