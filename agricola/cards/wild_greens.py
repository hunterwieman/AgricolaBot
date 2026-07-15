"""Wild Greens (minor improvement, E50; Ephipparius Expansion; players -).

Card text: "Each time you sow, you get 1 food for every different type of good
that you sow."
No cost. VPs: 0. Not passing.

The reward is OUTCOME-dependent: it counts the DISTINCT good-types planted by a
single Sow action. "type of GOOD" (user ruling, 2026-07-15) is deliberate and
BROADER than "crop": every kind of good you sow counts, across ALL fields --
grain and vegetables on grid FIELD tiles AND on card-fields, plus wood (Wood
Field) and stone (Rock Garden) sown onto card-fields. So grain-only -> +1 food,
grain + veg in one action -> +2, a Wood Field wood sow -> +1 (wood), a Beanfield
veg sow -> +1 (veg). Two fields of the same good is still ONE type.

`register_auto`'s apply_fn receives only (state, idx) -- the CommitSow's planted
amounts are invisible (the garden_hoe / gritter constraint) -- so the good-types
sown are detected by a before/after SNAPSHOT across the Sow sub-action host, the
same before/after CardStore shape as Garden Hoe and Gritter, but keyed on per-good
field TOTALS rather than field COUNTS:

  - `before_sow` (fires when PendingSow is pushed, before any CommitSow):
    snapshot the (grain, veg, wood, stone) totals summed over the player's fields
    (grid FIELD tiles + every card-field stack) into the per-card CardStore.
  - `after_sow` (fires at the CommitSow before->after flip, after the fields are
    filled): a good was sown this action iff its field TOTAL rose (a sow only ever
    ADDS to a field, so each good sown strictly increases its own total). Grant
    1 food per good-component whose total grew. Then reset the snapshot to the
    canonical "no entry" state so different commit orders converge (transposition
    safety).

Why per-good TOTALS, not per-good field COUNTS: a count of card-fields holding a
good has a blind spot on the multi-stack card-fields (Wood Field 2 stacks, Rock
Garden 3 stacks) -- sowing a good into one stack while another already holds it
leaves the card-level count unchanged. A total has no blind spot: the sow adds to
some stack, so the good's total always rises. And no over-count: between
before_sow and after_sow the only field mutation is this sow (field totals are
monotonic across it), so a good's total rises iff THIS sow planted it. The DELTA
(vs the raw total) is what isolates this sow from crops planted in prior rounds;
distinctness ("different type") is why each good contributes at most +1.

Card-only state (the CardStore snapshot) defaults to no entry, so the Family game
is byte-identical and the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md
Sec.4 (deferred snapshot / CardStore).
"""
from __future__ import annotations

from agricola.cards.card_fields import card_field_stacks, owned_card_fields
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wild_greens"


def _field_good_totals(state: GameState, idx: int) -> tuple:
    """(grain, veg, wood, stone) summed over this player's fields: grid FIELD
    tiles (grain/veg) + every card-field stack (each a (grain, veg, wood, stone)
    4-tuple). A sow only ever adds to a field, so a good was sown this action iff
    its component of this tuple rose across the sow."""
    p = state.players[idx]
    grain = veg = wood = stone = 0
    for row in p.farmyard.grid:
        for cell in row:
            if cell.cell_type is CellType.FIELD:
                grain += cell.grain
                veg += cell.veg
    for cid in owned_card_fields(p):
        for (g, v, w, s) in card_field_stacks(p, cid):
            grain += g
            veg += v
            wood += w
            stone += s
    return (grain, veg, wood, stone)


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_sow: record the pre-sow (grain, veg, wood, stone) field totals so
    the after-hook can tell which goods THIS sow planted."""
    totals = _field_good_totals(state, idx)
    p = fast_replace(state.players[idx],
                     card_state=state.players[idx].card_state.set(CARD_ID, totals))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_sow: +1 food for EACH good-component whose field total grew this sow
    (grain / veg / wood / stone -> 0..4 food). Always reset the snapshot to the
    canonical "no entry" state."""
    before = state.players[idx].card_state.get(CARD_ID, (0, 0, 0, 0))
    now = _field_good_totals(state, idx)
    types = sum(1 for b, n in zip(before, now) if n > b)
    p = fast_replace(
        state.players[idx],
        resources=state.players[idx].resources + Resources(food=types),
        card_state=state.players[idx].card_state.remove(CARD_ID),  # reset -> no entry
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), vps=0)
register_auto("before_sow", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_sow", CARD_ID, lambda state, idx: True, _grant_after)
