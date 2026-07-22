"""Carpenter's Apprentice (occupation, Corbarius Expansion, deck C #88, players 1+;
Farm Planner).

Card text (verbatim): "Wood rooms cost you 2 woods less. Your 3rd and 4th stable
each cost you 1 wood less. Your 13th to 15th fence each cost you nothing."

A passive three-clause COST card (no on-play effect), one registration per clause:

- **Clause 1 — wood rooms** (`register_reduction("build_room", ...)`): -2 wood on a
  room build, applicable only while the player's house material is WOOD. A room is
  always built of the current house material (`ROOM_COSTS[p.house_material]` is the
  base in `_build_room_ctx`), so "wood rooms" == rooms built while the house is
  wood; a clay/stone-house room build gets no reduction. The gate is the HOUSE
  MATERIAL, never the wood content of a candidate payment — a conversion card that
  routes wood into a clay-room payment (e.g. Frame Builder's 2 clay -> 1 wood) must
  not be discounted, because that room is still a clay room.

- **Clause 2 — 3rd and 4th stable** (`register_reduction("build_stable", ...)`):
  -1 wood when the stable being priced is the player's 3rd or 4th. CURRENT-count
  semantics (user ruling 74, 2026-07-21, per the user's note on Lumber Pile): the
  ordinal is derived from the current farmyard (`helpers.stables_built`), never
  from a cumulative built-ever counter — so a stable returned to supply (Lumber
  Pile) and later rebuilt passes through counts 2 and 3 again and RE-DISCOUNTS.
  That behavior falls out of the derivation for free. The cost pipeline prices
  each stable BEFORE it is placed (`resolution._execute_build_stable` computes the
  payment frontier pre-placement; `legality._can_build_stable` likewise reads the
  pre-build farmyard), so at cost time `stables_built == N` means the priced
  stable is the (N+1)-th: discount iff N in {2, 3}. Within one multi-shot Build
  Stables action each stable commits and debits individually and the count
  advances between commits, so an action spanning the 2nd and 3rd stables prices
  them at 2 wood and 1 wood respectively (Farm Expansion base 2).

- **Clause 3 — 13th to 15th fence** (`register_free_fence_ordinals`): the ORDINAL
  free-fence source (source 1b, user ruling 74, 2026-07-21): the card frees the
  fence pieces whose cumulative build ordinals are 13, 14, 15 (1-indexed over
  pieces placed on the board, derived from the farmyard fence popcount — exact
  because fences are never demolished). Non-consuming: only the WOOD is waived —
  a free piece still draws from the player's fence-piece supply (§9.7). Consumed
  by the CARDS deferred-tally accrue (`resolution._execute_build_pasture`) and
  the placement-time anticipation (`legality._check_entry_legal`) via
  `ordinal_free_count`.

Family-inertness: all three registries are ownership-gated (`_owns`), and no
Family player owns cards, so the Family game is byte-identical and the C++
differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_free_fence_ordinals, register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.helpers import stables_built
from agricola.resources import Resources

CARD_ID = "carpenters_apprentice"


def _wood_rooms_less_2_wood(state, idx, ctx, cost: Resources) -> Resources:
    """Clause 1: -2 wood, only while the house (hence the room being built) is
    wood. Clay/stone-house rooms pass through unchanged."""
    if state.players[idx].house_material is HouseMaterial.WOOD:
        return cost - Resources(wood=2)
    return cost


def _third_fourth_stable_less_1_wood(state, idx, ctx, cost: Resources) -> Resources:
    """Clause 2: -1 wood when pricing the 3rd or 4th stable. Current-count
    semantics (ruling 74): pre-placement `stables_built == N` means this is the
    (N+1)-th stable, so the discount applies iff N is 2 or 3."""
    if stables_built(state.players[idx].farmyard) in (2, 3):
        return cost - Resources(wood=1)
    return cost


register_reduction("build_room", CARD_ID, _wood_rooms_less_2_wood)
register_reduction("build_stable", CARD_ID, _third_fourth_stable_less_1_wood)

# Clause 3: "Your 13th to 15th fence each cost you nothing" — ordinal free-fence
# source 1b (ruling 74). Free pieces still draw from the fence-piece supply.
register_free_fence_ordinals("carpenters_apprentice",
                             lambda state, idx: frozenset({13, 14, 15}))

register_occupation(CARD_ID, _noop_on_play)   # passive cost card — no on-play effect
