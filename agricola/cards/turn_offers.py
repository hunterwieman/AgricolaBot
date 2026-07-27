"""Start-of-turn card offers — a decision surfaced to a player at the moment they are
handed a worker-placement turn, *before* they place.

The mechanism exists for the **supply-loaner** family (Motivator E93, and the other cards
that let a player place "a person from your supply"): those cards let a player take an
extra meeple out of supply to work this round, and the choice has to be presented at the
instant the card names — Motivator's is *"on your first turn each round"* — because it is
a genuine tradeoff, not free value. While the loaner is out it occupies a physical meeple,
so a player at 4 family with 1 meeple in supply is choosing between an extra worker now
and growing to 5 (the `workers_in_supply` growth gate enforces that on its own). Declining
must therefore always be possible.

**Why a choice frame and not extra placement options.** The offer is a small binary that
is independent of *where* the resulting worker goes, so it is surfaced as its own decision
(a `PendingCardChoice` with the card's options) and the placement then happens through the
ordinary, untouched placement path — rather than doubling the placement enumeration with a
"…but from supply" variant of every legal space. That keeps branching at the placement
node unchanged and keeps the two decisions separable, per CLAUDE.md's Foundations
(sequential decomposition).

**Why the resolver must latch.** The engine consults this registry at every WORK-phase
decision boundary, so an offer whose eligibility is unchanged by *declining* would be
re-pushed forever — the player declines, nothing about the state moved, the offer returns.
Eligibility must therefore go false once the offer has been answered, whichever way it was
answered. The convention is the `used_this_round` latch, set by the card's resolver on
BOTH options (see `motivator.py`). This is a liveness requirement, not just a "once per
round" nicety.

Default-inert: an empty registry is one `if` in the engine's boundary walk, so the Family
game (and any card game with none of these cards) is byte-identical.
"""
from __future__ import annotations

from typing import Callable

from agricola.pending import PendingCardChoice
from agricola.state import GameState

# card_id -> (eligible_fn, options). `eligible_fn(state, idx) -> bool` decides whether
# THIS player is owed the offer right now; `options` are the PendingCardChoice options,
# resolved by the card's own registered card-choice resolver.
TURN_START_OFFERS: dict[str, tuple[Callable, tuple]] = {}


def register_turn_start_offer(card_id: str, eligible: Callable,
                              options: tuple) -> None:
    """Register a start-of-turn offer for `card_id` (called at card-module import).

    `eligible(state, idx) -> bool` must be False once the offer has been answered this
    round — see the module docstring on latching.
    """
    TURN_START_OFFERS[card_id] = (eligible, options)


def has_outstanding_offer(state: GameState, idx: int) -> bool:
    """Does this player have an unanswered start-of-turn offer right now?

    The turn flow consults this so a player who has run out of household workers but may
    still place a LOANER is given a turn rather than skipped: it widens
    `_advance_current_player`'s "has a worker" test and the work phase's all-placed gate.
    That is what lets a card whose loaner is available anywhere in the round (Telegram,
    Work Permit) surface its offer at the LAST usable moment — the strictly better time
    to decide, since taking a loaner never grants a placement sooner and only forecloses
    family growth earlier.

    Liveness rests on the same latch the offer itself needs: an offer that survived being
    declined would keep this True forever and the work phase could never end.
    """
    if not TURN_START_OFFERS:
        return False
    return pending_turn_start_offer(state, idx) is not None


def pending_turn_start_offer(state: GameState, idx: int):
    """The `PendingCardChoice` this player is owed at the start of their turn, or None.

    Callers gate on `TURN_START_OFFERS` being non-empty first, so the no-card path never
    reaches here. At most one offer is surfaced per boundary; if two ever became eligible
    at once, the second is surfaced at the next boundary (the first one's resolver latches
    it off), so both are still offered before the player places.

    A player who has COMMITTED their last work-phase use (`last_use_committed` — set by
    firing a last-use-conditioned effect, Steam Machine today) is owed no offer: a loaner
    placement would contradict the commitment, so every offer is implicitly declined for
    the round (the user's ruled Telegram-arc principle). The consult lives HERE, at the
    single chokepoint, so it also suppresses offers that only become eligible at a LATER
    boundary (Delayed Wayfarer's all-players-placed offer arises after Steam Machine's
    fire instant — a decline-what's-outstanding call at fire time would miss it). The
    latch clears at the returning-home reset, so it never outlives its round; whether a
    foreclosed offer exists in a later round is each card's own predicate.
    """
    if state.players[idx].last_use_committed:
        return None
    for card_id, (eligible, options) in TURN_START_OFFERS.items():
        if eligible(state, idx):
            return PendingCardChoice(
                player_idx=idx,
                initiated_by_id=f"card:{card_id}",
                options=options,
            )
    return None
