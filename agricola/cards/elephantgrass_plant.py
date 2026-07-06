"""Elephantgrass Plant (minor improvement, C34; Corbarius Expansion; Points Provider).

Card text (verbatim): "Immediately after each harvest, you can use this card to
exchange exactly 1 reed for 1 bonus point."
Cost: 2 Clay, 1 Stone. Prerequisite: 2 Occupations. VPs: 0 (printed). Not passing.

A recurring, optional, once-per-harvest goods-to-point swap: spend exactly 1 reed,
bank 1 bonus point (no food produced).

Timing — "immediately after each harvest" → the ``after_harvest`` window. Per the
user ruling of 2026-07-05, "immediately after each harvest" and "after each harvest"
name the SAME instant — the ladder (``agricola/cards/harvest_windows.py``) carries
one window for it, OUTSIDE the harvest, strictly after ``end_of_harvest`` (the last
in-harvest moment; post-breeding-timeline ruling 2026-07-03, ``CARD_DEFERRED_PLANS.md``
→ Harvest-window redesign rulings). The swap is registered as an OPTIONAL TRIGGER
there (a ``PendingHarvestWindow`` ``FireTrigger``; declining is the frame's
``Proceed``).

"exchange EXACTLY 1 reed": the once-per-window frame gives this for free — its
``triggers_resolved`` records the fire, so after swapping, the trigger is no longer
offered for the rest of that window (and the window fires once per harvest). No
quantity/target choice is needed (exactly 1 reed for 1 point), so this is a plain
trigger, not a play-variant. The 1-reed cost is debited and the point banked by
``_award`` itself — the window machinery carries no cost layer — and affordability
(>= 1 reed) is checked in ``_eligible`` so the swap is offered only when the player
holds a reed to spend.

Mis-timing history: this card was previously registered on the
``HARVEST_CONVERSIONS`` seam (surfaced during the FEED sub-phase), which the old
docstring justified as "behaviorally inert." That home was a mis-timing — the FEED
phase is not after the harvest — and it has been migrated to the after-harvest
window per the printed text and the 2026-07-03 ruling. Because reed is never a feeding or
cooking input, the observable outcome (spend 1 reed, bank +1 point, once per
harvest) is unchanged by the move.

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each fire increments a per-card ``CardStore`` counter (banked across all six
harvests), and the scoring term reads the count back at end-game. Do NOT set vps=
(that scores the printed keep VP, which is 0 here) — the point is earned, not
printed.

Registrations are global and the window's trigger enumerator checks ownership via
``_owns``, but the affordability/ownership shape still lives in ``_eligible`` (the
eligibility gate); ownership additionally short-circuits there so the swap is never
surfaced to a non-owner.

Card-only state (the CardStore int) is empty in the Family game, so it stays
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "elephantgrass_plant"


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the swap iff this player owns Elephantgrass Plant AND holds >= 1 reed.

    Ownership: registrations are global, so the minor-ownership check lives here
    (the trigger enumerator also gates on ownership, but keeping it here is
    explicit and matches the surrounding card idioms). Affordability: the window
    machinery has no cost layer, so the 1-reed check that the old HARVEST_FEED
    enumerator performed must live here. The once-per-window limit is handled by
    the frame's ``triggers_resolved`` (checked by the enumerator, not here).
    """
    p = state.players[idx]
    return CARD_ID in p.minor_improvements and p.resources.reed >= 1


def _award(state: GameState, idx: int) -> GameState:
    """Spend 1 reed, bank one bonus point (incremented per harvest, up to 6). The
    window trigger carries no cost layer, so this debits the reed and banks the
    point in one step."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources + Resources(reed=-1),
        card_state=p.card_state.set(CARD_ID, banked + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Cost 2 clay + 1 stone; prereq 2 occupations; printed VP 0 (points are earned).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2, stone=1)),
    min_occupations=2,
    vps=0,
)

# The recurring reed->point swap after the harvest (the after_harvest window —
# "immediately after" = "after", ruling 2026-07-05): an optional trigger — spend
# 1 reed, bank +1 point.
register("after_harvest", CARD_ID, _eligible, _award)
register_harvest_window_hook(CARD_ID, "after_harvest")

register_scoring(CARD_ID, _score)
