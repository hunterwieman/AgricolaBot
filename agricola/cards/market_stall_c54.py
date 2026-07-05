"""Market Stall (minor improvement, C54; Corbarius Expansion; Food Provider).

Card text (verbatim): "After the field phase of each harvest, you can exchange
1 grain plus 1 fence (both from your supply) for 5 food."
Play cost: "1 Stable from Your Supply". No prerequisite, no printed VPs.

**card_id `market_stall_c54`, not the name slug** — the Base-Revised B8
"Market Stall" (an unrelated passing card, implemented first) already owns the
`market_stall` slug; the web UI's card-metadata join carries an explicit
(slug, deck) alias for this id.

**The play cost — a stable piece spent from supply, never built (user go-ahead
2026-07-05).** The stable supply is DERIVED (`helpers.stables_in_supply(player)
= 4 − built − card-removed`, the derived-not-stored default): rather than
converting it to a stored PlayerState field (a Family state-shape + C++
contract change), this card records its removal in its own card_state at play
(`_on_play`), registered through the cost-mod seam
(`register_stable_supply_removal`) that the derived read subtracts. The play
prerequisite gates on a piece actually being in supply. The removed piece is
gone for the game: build-stable legality reads the same derived supply, so the
player can build at most 3 stables afterward.

**The recurring exchange** — an `after_field_phase` (harvest window #7)
optional trigger, Winter Caretaker's shape: eligibility gates affordability
(1 grain in the resource supply AND 1 fence piece in the stored
`fences_in_supply` pile — the fence is SPENT from supply, never placed, the
Loppers debit idiom); the apply debits both and credits 5 food. "Exchange 1
grain plus 1 fence" is a single fixed-rate use — once per harvest via the
window frame's `triggers_resolved`; declining is `Proceed`.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_stable_supply_removal
from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.helpers import stables_in_supply
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "market_stall_c54"
WINDOW_ID = "after_field_phase"
_REMOVED_KEY = f"{CARD_ID}_stable_removed"


def _prereq(state: GameState, idx: int) -> bool:
    """"1 Stable from Your Supply" is payable only while a piece is in supply
    (unbuilt and not already card-removed)."""
    return stables_in_supply(state.players[idx]) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Pay the play cost: record the removal of 1 stable piece from supply in
    this card's card_state — the derived supply read subtracts it from then on
    (the piece is spent for the game, not built)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(_REMOVED_KEY, 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    # Both inputs on hand: 1 grain in the resource supply, 1 fence piece in the
    # stored supply pile.
    p = state.players[idx]
    return p.resources.grain >= 1 and p.fences_in_supply >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Exchange 1 grain + 1 fence piece (both from supply) for 5 food. The
    fence piece is spent, never placed — `fences_in_supply` drops by 1 and the
    piece is gone for the game (the Loppers idiom)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(grain=-1, food=5),
        fences_in_supply=p.fences_in_supply - 1,
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, prereq=_prereq, on_play=_on_play)
register_stable_supply_removal(CARD_ID, _REMOVED_KEY)
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
