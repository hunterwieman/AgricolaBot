"""Stone Clearing (minor improvement, C6; Consul Dirigens; cost 1 Food, traveling).

Card text (verbatim): "Immediately place 1 stone on each of your empty fields.
Harvest them during the next field phase. These fields are considered planted
until then."
ERRATA (verbatim): "ERRATA: harvest the fields with stone normally, and the
fields are considered planted until the stone is gone."
Cost: 1 Food. No prerequisite. No VPs. A TRAVELING (passing) card — executed
then passed to the opponent, never kept. Category: Building Resource Provider.

Governing user rulings (both 2026-07-20, verbatim):

- The go-ahead: "make sure that the code does not perceive these fields as
  empty (for the purposes of sowing or for card prerequisites or effects)".
- The scope question — does "place 1 stone on each of your empty fields" cover
  empty card-fields too? — "it does. Stone Clearing should place 1 stone on
  all fields, including cards like beanfield and wood field that have
  restrictions on what can be sowed on them (wood field would get 1 stone
  not 2)".

So the on-play placement is: 1 stone on every empty board FIELD tile, AND
exactly 1 stone per fully-empty card-field CARD (one stone into one stack —
Wood Field's two stacks receive 1 stone total, per the ruling's "1 stone not
2"); a card's sow whitelist does NOT restrict this placement (the veg-only
Beanfield still receives stone). A card-field holding anything in any stack is
not empty and receives nothing (the `unplanted_card_field_count` semantics —
every stack all-zero). A play with zero empty fields anywhere is a legal
null-effect play (the Garden Claw "legal +0" precedent — no invented
prerequisite).

Everything downstream of the placement lives in the ENGINE layer, already
built and pinned by tests/test_stone_fields.py: `Cell.stone` with the
`Cell.field_empty` / `Cell.field_planted` predicates (a stone-holding board
field is planted, not empty, for sowing and for every card prerequisite /
effect / reader), and `resolution.field_take` harvesting the stone normally —
1 per field phase, to supply, with a `crop="stone"` manifest entry — from
board fields and card stacks alike (`stack_take_good` covers stone). This
module is ONLY the registration + the on-play placement.

DRIVER-ADOPTED READING, FLAGGED FOR USER CONFIRMATION (not a dated ruling):
stone in one of Wood Field's stacks leaves its OTHER stack sowable exactly as
a half-wood-planted Wood Field's is — the machinery's established per-stack
sowability (empty stacks enumerate, non-empty don't). The errata's
"considered planted" is read as the field-LEVEL reader status, which
`planted_card_field_count` already grants to any card holding anything — not
a new per-stack sow block.
"""
from __future__ import annotations

from agricola.cards.card_fields import (
    EMPTY_STACK,
    card_field_stacks,
    owned_card_fields,
    stack_with,
    stacks_to_store,
)
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stone_clearing"


def _on_play(state: GameState, idx: int) -> GameState:
    """Place 1 stone on each of the player's empty fields — every empty board
    FIELD tile, and 1 per fully-empty card-field card (user ruling
    2026-07-20)."""
    p = state.players[idx]

    # (a) Board: 1 stone on each empty FIELD tile. `Cell.field_empty` is the
    # single emptiness predicate (no grain, no veg, no stone), so an
    # already-stoned or crop-holding field is untouched. Fences are untouched,
    # so the Farmyard pasture cache carries over unchanged.
    fy = p.farmyard
    grid = [list(row) for row in fy.grid]
    changed = False
    for r in range(3):
        for c in range(5):
            if grid[r][c].field_empty:
                grid[r][c] = fast_replace(grid[r][c], stone=1)
                changed = True
    if changed:
        fy = fast_replace(fy, grid=tuple(tuple(row) for row in grid))

    # (b) Card-fields: 1 stone per CARD whose stacks are ALL empty — one stone
    # into one stack, however many stacks the card has ("wood field would get
    # 1 stone not 2"). The sow whitelist does not gate this (Beanfield's
    # veg-only restriction is a SOW restriction; this placement is not a sow).
    store = p.card_state
    for cid in owned_card_fields(p):
        stacks = card_field_stacks(p, cid)
        if all(s == EMPTY_STACK for s in stacks):
            new_stacks = (stack_with(EMPTY_STACK, "stone", 1),) + stacks[1:]
            store = stacks_to_store(store, cid, new_stacks)

    p = fast_replace(p, farmyard=fy, card_state=store)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    passing_left=True,
    on_play=_on_play,
)
