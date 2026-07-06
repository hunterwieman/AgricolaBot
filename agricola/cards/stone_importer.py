"""Stone Importer (occupation, C124; Corbarius Expansion; players 1+).

Card text (verbatim): "In the breeding phase of the 1st/2nd/3rd/4th/5th/6th
harvest, you can use this card to buy exactly 2 stone for 2/2/3/3/4/1 food."

Category: Building Resource Provider. Occupation. No cost / prerequisite / VPs
(the JSON row carries only name / category / text — no cost, prereq, or VP
fields). No on-play effect (the effect is the recurring in-harvest buy only).

What the card does: once per harvest, during that harvest's breeding phase, the
owner may pay a harvest-dependent food price and take 2 stone from the supply —
2 food at the 1st and 2nd harvests, 3 at the 3rd and 4th, 4 at the 5th, and only
1 at the 6th (final) harvest.

TIMING — the breed frame's pre-commit trigger stretch. **User ruling 20
(2026-07-05): in-breeding-phase card effects fire BEFORE the CommitBreed
decision, not after.** The breed frame (``PendingHarvestBreed``) hosts
pre-commit triggers on the event string ``"breeding"``; once CommitBreed
resolves, that event is closed (only outcome-reactive triggers + Stop remain).
The buy is therefore registered as an OPTIONAL TRIGGER (``register("breeding",
…)``) — it surfaces as a ``FireTrigger`` on the owner's breed frame before the
breed decision, and declining is simply committing the breed (or, with nothing
to breed, the do-nothing CommitBreed) without firing. The frame only exists
during ``Phase.HARVEST_BREED``, so no extra phase gate is needed.

THE HARVEST ORDINAL — "the 1st/2nd/3rd/4th/5th/6th harvest". The harvests run
on rounds {4, 7, 9, 11, 13, 14} (``constants.HARVEST_ROUNDS``); a harvest
resolves while ``state.round_number`` still equals its round (round_number is
only incremented in the NEXT round's PREPARATION — the Transactor precedent).
So the Nth harvest is the harvest whose round sits at 0-based index N-1 of the
harvest rounds in play order, and the price ladder ``(2, 2, 3, 3, 4, 1)`` is
indexed by that ordinal. ``_price`` returns None on a non-harvest round — a
purely defensive guard (the breed frame is only ever pushed by the harvest
walk, and the printed six harvests are exactly all the breeding phases there
are), under which eligibility is False.

"you can USE THIS CARD to buy EXACTLY 2 stone": optional (a declinable
trigger, never automatic), and once per breeding phase — the frame's
``triggers_resolved`` records the fire, so after buying, the trigger is not
offered again for the rest of that phase (and the frame is pushed fresh each
harvest). No quantity/target choice exists (exactly 2 stone for a fixed
price), so this is a plain trigger, not a play-variant. The food price is
debited and the stone granted by ``_buy`` itself — frame triggers carry no
cost layer — and affordability (food >= the current harvest's price) is
checked in ``_eligible`` so the buy is offered only when the player can pay
(the Winter Caretaker / Elephantgrass Plant idiom).

Registrations are global and the breed frame's trigger enumerator checks
ownership via ``_owns``, but the ownership check also lives in ``_eligible``
(explicit, matching the surrounding card idioms) so the buy is never surfaced
to a non-owner.

Card-only state is empty (no CardStore use) and the registration rides the
ownership-gated ``"breeding"`` trigger event only, so the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stone_importer"

# The printed price ladder: the 1st/2nd/3rd/4th/5th/6th harvest costs
# 2/2/3/3/4/1 food for the 2 stone.
_PRICES = (2, 2, 3, 3, 4, 1)

# HARVEST_ROUNDS is a set; the harvest ordinal needs the rounds in play order.
_ORDERED_HARVEST_ROUNDS = tuple(sorted(HARVEST_ROUNDS))


def _price(state: GameState) -> int | None:
    """The food price of the current harvest's buy, from the printed ladder.

    During a harvest, ``state.round_number`` still equals the harvest's round
    (it is incremented only in the next round's PREPARATION), so the current
    harvest's 0-based ordinal is the round's index in the ordered harvest
    rounds. Returns None on a non-harvest round (defensive — the breed frame
    only exists on harvest rounds)."""
    rn = state.round_number
    if rn not in HARVEST_ROUNDS:
        return None
    return _PRICES[_ORDERED_HARVEST_ROUNDS.index(rn)]


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff this player owns Stone Importer AND holds at least the
    current harvest's food price.

    Ownership: registrations are global, so the occupation-ownership check
    lives here (the breed-frame enumerator also gates on ownership, but keeping
    it here is explicit and matches the surrounding card idioms).
    Affordability: frame triggers carry no cost layer, so the food check lives
    here. The once-per-phase limit is handled by the frame's
    ``triggers_resolved`` (checked by the enumerator, not here)."""
    price = _price(state)
    if price is None:
        return False
    p = state.players[idx]
    return CARD_ID in p.occupations and p.resources.food >= price


def _buy(state: GameState, idx: int) -> GameState:
    """Pay the current harvest's food price, take exactly 2 stone. Frame
    triggers carry no cost layer, so this debits the food and grants the stone
    in one step."""
    price = _price(state)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=-price, stone=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# Pure recurring-trigger occupation: no on-play effect, so the on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# The once-per-harvest priced stone buy, on the breed frame's PRE-COMMIT
# trigger stretch (event "breeding"; user ruling 20, 2026-07-05: in-breeding-
# phase card effects fire BEFORE the CommitBreed decision, not after).
register("breeding", CARD_ID, _eligible, _buy)
