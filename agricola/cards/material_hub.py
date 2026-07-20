"""Material Hub (minor improvement, Corbarius C81; deck C #81; players -).

Card text (verbatim): "Immediately place 2 of each building resource on this
card. Each time any player (including you) takes at least 5 wood, 4 clay, 3 reed,
or 3 stone, you get 1 of that building resource from this card."

Cost: 1 Wood, 1 Clay. Prerequisite: "1 Reed and 1 Stone in Your Supply" — a
HAVE-check (hold >=1 reed and >=1 stone), NOT a spendable cost (the reed/stone are
never debited; only the 1 wood + 1 clay are paid). VPs: none. Not passing.

USER RULINGS (2026-07-20) — the load-bearing scope questions:

1. "Takes at least N X" scope = ACCUMULATION-SPACE acquisitions only (a player
   sweeping a building-resource accumulation space by placing a worker there). No
   other gain occasion (card grants, bonus income, on-play goods, harvest) counts.
2. Count ONLY the resources of the space's NATIVE accumulation type swept off the
   space. A FOREIGN-type resource a card deposited onto the space (e.g. Nail
   Basket's stone placed on a wood space) does NOT count toward any threshold, and
   card-trigger bonus income earned alongside the use does not count either.
   CLARIFIED (user, 2026-07-20, second ruling the same day): a NATIVE-type good a
   card returned onto the space (Forest Plow B17's wood back onto Forest, when
   built) DOES count for the next visitor — once on the space, native-type goods
   are simply "wood taken from the space," origin irrelevant. The native-type
   filter is therefore the complete, final semantics — no deposit provenance is
   ever needed.
3. "You get 1 of that building resource" is MANDATORY -> an automatic effect, and
   it fires for its owner on EVERY player's qualifying take ("each time any player
   (including you)"), so `any_player=True`.

HOW THIS MAPS TO THE MACHINERY

The five building-resource accumulation spaces are ATOMIC (Forest, Clay Pit, Reed
Bank, the two quarries), so each is hosted via `register_action_space_hook(...,
any_player=True)` — the host frame must exist on BOTH players' uses so the reactor
can fire on the opponent's take too. The payout is an `after_action_space`
automatic effect (`any_player=True`): it must read WHAT THE SPACE PRODUCED, so it
fires in the after window, reading the host frame's `taken` Resources delta (the
goods the acting player swept across the take, stamped at Proceed).

Ruling 2 is implemented by filtering `taken` to the space's NATIVE building type
(forest->wood, clay pit->clay, reed bank->reed, quarries->stone) and comparing
against that type's threshold (wood 5 / clay 4 / reed 3 / stone 3). `taken` never
includes card-trigger bonus income (that income is granted in the before/after
windows OUTSIDE the atomic take, so it is not part of the measured delta), and the
type filter drops any foreign-type deposit. Native-type goods in the sweep count
regardless of how they reached the space (the 2026-07-20 clarification above) —
`taken`'s value is exactly the intended quantity, so this filter is complete and
final, not an approximation. Each space has exactly one native type, so at most
one threshold fires per take. (A depositing card that fires in the AFTER window —
Forest Plow's ruled timing — also cannot disturb the depositing player's own
`taken`: the stamp happens at the atomic take, before after-triggers run.)

STOCK: the "2 of each building resource on this card" come from the GENERAL SUPPLY,
not the player's goods — the on-play only sets the card's CardStore stock, never
debits the owner. Payout moves 1 of the qualifying native type from the card's
stock to the OWNER's supply; eligibility requires the stock still holding >=1 of
that type (once exhausted, further qualifying takes pay nothing). Each player's own
Material Hub pays its own owner. Goods on the card are NOT the player's supply, so
there is no scoring registration (they never count toward supply or the tiebreaker
until paid out).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    BUILDING_RESOURCE_ACCUMULATION_SPACES,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "material_hub"

# The "at least N" threshold per native building-resource type (user ruling
# 2026-07-20 / printed text): wood 5, clay 4, reed 3, stone 3.
_THRESHOLDS = {"wood": 5, "clay": 4, "reed": 3, "stone": 3}

# The 2-of-each stock placed on the card at play, from the GENERAL SUPPLY.
_INITIAL_STOCK = Resources(wood=2, clay=2, reed=2, stone=2)


def _native_good(space_id: str) -> str:
    """The building-resource type a building accumulation space natively yields —
    read from BUILDING_ACCUMULATION_RATES so it is correct at 2p and for any future
    4p building space. Only called for spaces in BUILDING_RESOURCE_ACCUMULATION_SPACES."""
    rate = BUILDING_ACCUMULATION_RATES[space_id]
    if rate.wood:
        return "wood"
    if rate.clay:
        return "clay"
    if rate.reed:
        return "reed"
    return "stone"


def _prereq(state: GameState, idx: int) -> bool:
    # HAVE-check (not debited): hold >=1 reed and >=1 stone in supply.
    r = state.players[idx].resources
    return r.reed >= 1 and r.stone >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    # Place 2 of each building resource on the card FROM THE SUPPLY — set the
    # CardStore stock only; the owner's own goods are untouched.
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _INITIAL_STOCK))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the OWNER (any_player). The host frame on top belongs to the ACTING
    # player's use of a building accumulation space; its `taken` is that player's
    # swept delta. Fire iff the sweep of the space's NATIVE type met the threshold
    # AND this owner's stock still holds >=1 of that type.
    top = state.pending_stack[-1]
    space_id = getattr(top, "space_id", None)
    if space_id not in BUILDING_RESOURCE_ACCUMULATION_SPACES:
        return False
    native = _native_good(space_id)
    taken = getattr(top, "taken", Resources())
    if getattr(taken, native) < _THRESHOLDS[native]:
        return False
    stock = state.players[idx].card_state.get(CARD_ID, Resources())
    return getattr(stock, native) >= 1


def _apply(state: GameState, idx: int) -> GameState:
    native = _native_good(state.pending_stack[-1].space_id)
    one = Resources(**{native: 1})
    p = state.players[idx]
    stock = p.card_state.get(CARD_ID, Resources())
    p = fast_replace(
        p,
        resources=p.resources + one,               # 1 native good to the OWNER
        card_state=p.card_state.set(CARD_ID, stock - one),  # ...from the card's stock
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=1)),
    prereq=_prereq,                # "1 Reed and 1 Stone in Your Supply" — a HAVE-check
    on_play=_on_play,
)
# Mandatory payout, any player's qualifying take (user ruling 2026-07-20 #3). AFTER
# window because it must read what the space produced (`taken`).
register_auto("after_action_space", CARD_ID, _eligible, _apply, any_player=True)
# Host the five (2p) building accumulation spaces on EITHER player's use.
register_action_space_hook(
    CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES, any_player=True)
