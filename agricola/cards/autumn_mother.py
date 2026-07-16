"""Autumn Mother (occupation, C92; Corbarius Expansion; players 1+).

Card text (verbatim): "Immediately before each harvest, if you have room in your
house, you can take a "Family Growth" action for 3 food."
No clarifications printed. Occupation — no cost / prerequisite / VPs.

TIMING — window #1 ``immediately_before_harvest``: the printed "immediately
before each harvest" is that window's defining phrase (the harvest-ladder census,
HARVEST_WINDOWS_DESIGN.md §1, lists Autumn Mother there). An OPTIONAL trigger —
"you can" — surfaced as a ``FireTrigger`` on the per-player
``PendingHarvestWindow`` frame; declining is the frame's ``Proceed``. Singular "a
'Family Growth' action" = once per harvest, given by the frame's
``triggers_resolved`` (once-per-window is automatic).

THE GROWTH — the card-granted family-growth primitive (Group A1, built
2026-07-03 with the user's ruling recorded in CARD_DEFERRED_PLANS.md §A1 /
the ``PendingFamilyGrowth`` docstring): firing pushes
``PendingFamilyGrowth(place_on_space=False)``, so the newborn occupies NO action
space — the commit increments the owner's people_total/newborns only. Once
fired, the payment and the growth are mandatory (the Ox Goad shape); the
optionality lives at the FireTrigger itself, per the granted-sub-actions-are-
optional rule (CARD_AUTHORING_GUIDE.md "A granted sub-action is optional").

"IF YOU HAVE ROOM IN YOUR HOUSE" — the printed condition, checked in
``_eligible`` (the primitive does not self-check; CARD_DEFERRED_PLANS.md §A1
names the predicate): ``workers_in_supply > 0`` (the family cap — a meeple left
in supply, a game rule the card does not waive) AND ``people_total < _num_rooms(p)``
(a free room). This is
the same gate as the Basic Wish for Children space (``legality._legal_basic_
wish_for_children``); the card does NOT waive the room requirement (contrast
Urgent Wish, which drops only the room clause, never the 5-cap).

"FOR 3 FOOD" — paid through the shared food-payment path (FOOD_PAYMENT_DESIGN.md
§8/§9, the Ox Goad pattern): with 3 food on hand ``_apply`` debits directly and
pushes the growth; short, it pushes a raise-only ``PendingFoodPayment`` whose
``resume_kind`` is this card id, so the player may raise the shortfall via the
game-wide anytime conversions (grain 1:1, veg/animals at ``cooking_rates``) and
``_pay_and_grow`` — the registered resume — debits the full 3 and pushes the
growth. That frontier offers exactly the anytime conversions and never the
harvest-scoped converter cards, matching the window-#1 cost prescription in
HARVEST_WINDOWS_DESIGN.md ("A window-#1 food cost (Autumn Mother's 3-food
growth) may use the game-wide anytime cooking conversions but NOT [the
once-per-harvest converter cards]"). Eligibility gates on BOTH the room AND the
3 food being payable-with-liquidation (``_liquidatable_to``), so a fired trigger
is never a dead end (CARD_AUTHORING_GUIDE.md §2).

The newborn is a normal newborn: it feeds at THIS harvest's FEED (1 food, the
engine's uniform newborn rule) and grows up at RETURN_HOME like any other.

Played via Lessons; on-play is a no-op (the effect is purely recurring).
Card-only registries are empty in the Family game, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to, _num_rooms
from agricola.pending import PendingFamilyGrowth, PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "autumn_mother"
WINDOW_ID = "immediately_before_harvest"
_FOOD_COST = 3


def _pay_and_grow(state: GameState, idx: int) -> GameState:
    """Debit the 3 food, then grant the growth. Reached directly (food on hand)
    and as the post-food-payment continuation (the raise-only frame leaves the
    food in supply for this to debit). Reads the food from supply either way."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the growth iff the printed room condition holds AND the 3 food is
    payable (with liquidation) — never a dead end. Ownership is the window
    enumerator's ``_owns`` gate; once-per-window is the frame's
    ``triggers_resolved`` (checked by the enumerator, not here)."""
    p = state.players[idx]
    if not (p.workers_in_supply > 0 and p.people_total < _num_rooms(p)):
        return False
    return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 3 food and grant the growth. With enough food on hand, do it
    directly; otherwise push a raise-only PendingFoodPayment and defer the
    pay-and-grow to its resume (which debits the raised food). The 3 food is
    the card's only cost, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_grow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


# Pure recurring-window occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Optional trigger on window #1 (immediately_before_harvest): pay 3 food (via
# the shared food-payment path), take a card-granted Family Growth.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
register_food_payment_resume(CARD_ID, _pay_and_grow)
