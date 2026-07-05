"""Haydryer (occupation, A166; Artifex Expansion; players 4+).

Card text (verbatim): "Immediately before each harvest, you can buy 1 cattle for
4 food minus 1 food for each pasture you have. (The minimum cost is 0)."

Category: Livestock Provider. Occupation. No cost / prerequisite / VPs (the JSON
carries only name / category / text — no cost, prereq, or VP fields).

PLAYERS 4+ — this card is not dealt in the 2-player pool, but it is implemented
per the project directive to give real design weight to [3+]/[4] cards
(CLAUDE.md Phase 3): its shape is a plain window trigger with no 4-player-only
machinery, so it registers and works for any player who owns it.

TIMING — window #1 ``immediately_before_harvest``. The printed "Immediately
before each harvest" maps directly to the harvest ladder's first window
(``agricola/cards/harvest_windows.py``), before start_of_harvest and the field
phase. It fires at EVERY harvest (rounds 4, 7, 9, 11, 13, 14) — the census's
"round-14-gated" annotation on this window belongs to its co-member Transactor
("the final harvest at the end of round 14"), not to Haydryer, whose text says
"each harvest" with no round gate.

OPTIONAL TRIGGER — "you can buy 1 cattle" is a declinable offer of exactly one
buy, so it is registered as an optional trigger (``register`` on the
``immediately_before_harvest`` event). It surfaces as a ``FireTrigger`` on the
per-player ``PendingHarvestWindow`` frame; ``Proceed`` declines. "1 cattle" is a
single buy per harvest — enforced by the frame's ``triggers_resolved``
(once-per-window is automatic; the window fires once per harvest). No
quantity/target choice exists (exactly 1 cattle at a state-determined price), so
this is a plain trigger, not a play-variant.

THE PRICE — "4 food minus 1 food for each pasture you have. (The minimum cost is
0)": ``max(0, 4 - #pastures)`` food. Pastures are the farmyard's fenced
enclosures — ``player.farmyard.pastures`` (the engine's pasture decomposition);
the count is its length. The window machinery carries no cost layer, so ``_buy``
debits the food itself, and affordability (``food >= price``) is checked in
``_eligible`` so the buy is offered only when payable (a 0-price buy is always
payable).

THE CATTLE — granted via ``helpers.grant_animals`` (the single choke point for
decision-free card animal gains — Game Trade, Young Animal Market, Shepherd's
Crook): the cattle is added even if it exceeds housing capacity, and the engine's
accommodation barrier (``engine._reconcile_accommodation``, run at every decision
boundary) surfaces the keep-or-cook choice if it does not fit.

Card-only state is empty (no CardStore use), so the Family game is byte-identical
and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "haydryer"
WINDOW_ID = "immediately_before_harvest"

_BASE_PRICE = 4


def _price(state: GameState, idx: int) -> int:
    """4 food minus 1 per pasture, floored at 0 ("The minimum cost is 0")."""
    return max(0, _BASE_PRICE - len(state.players[idx].farmyard.pastures))


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff the player can pay the current price. Ownership and the
    once-per-window guard are enforced by the host enumerator (``_owns`` / the
    frame's ``triggers_resolved``); the affordability check lives here because
    the window machinery carries no cost layer. No round gate — the text says
    "each harvest"."""
    return state.players[idx].resources.food >= _price(state, idx)


def _buy(state: GameState, idx: int) -> GameState:
    """Pay max(0, 4 - #pastures) food; gain 1 cattle (via grant_animals, so the
    accommodation barrier handles a cattle that doesn't fit)."""
    price = _price(state, idx)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=price))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return grant_animals(state, idx, Animals(cattle=1))


# Pure recurring-window occupation: no on-play effect (the effect is the
# recurring pre-harvest cattle buy only), so the on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Optional trigger on window #1 (immediately_before_harvest), every harvest.
register(WINDOW_ID, CARD_ID, _eligible, _buy)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
