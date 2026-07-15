"""Lawn Fertilizer (minor improvement, D11; Dulcinaria Expansion; players -).

Card text: "Your pastures of size 1 can hold up to 3 animals of the same type.
(With a stable, they can hold up to 6 animals of the same type.)"

No cost, no prerequisite, no printed VPs; kept (not traveling). A standing
CAPACITY modifier, no on-play effect.

One effect: raise the capacity of every size-1 (single-cell) pasture. Registered
on the per-pasture-conditioned capacity registry (`register_pasture_capacity_per`
— Tinsmith Master's conditional sibling of Drinking Trough's flat fold): the bonus
fn inspects each pasture and adds to THAT pasture's already-computed capacity
(applied by `helpers.extract_slots` AFTER the stable doubling — the FINAL
capacity). Only size-1 pastures qualify; larger pastures get nothing.

The numbers follow the base capacity `2 * num_cells * (2 ** num_stables)`:
  - size 1, no stable: base 2 -> "up to 3"  => bonus +1
  - size 1, 1 stable : base 4 -> "up to 6"  => bonus +2
A size-1 pasture can hold at most one stable, so num_stables is 0 or 1 there.
"of the same type" is the standard one-type-per-pasture rule (each pasture cap
already holds a single animal type), not an added constraint.

Card-only state (empty registry in the Family game -> byte-identical; the
accommodation caches key on `extract_slots`' outputs, so a conditioned bonus
changes the key itself and staleness is impossible — §5.4's projection-key
contract).
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_pasture_capacity_per
from agricola.cards.specs import _noop_on_play, register_minor

CARD_ID = "lawn_fertilizer"


def _size1_pasture_bonus(pasture) -> int:
    """+2 for a size-1 pasture WITH a stable (4 -> 6), +1 for one without (2 -> 3);
    0 for any pasture larger than a single cell."""
    if len(pasture.cells) != 1:
        return 0
    return 2 if pasture.num_stables >= 1 else 1


register_minor(CARD_ID, on_play=_noop_on_play)
register_pasture_capacity_per(CARD_ID, _size1_pasture_bonus)
