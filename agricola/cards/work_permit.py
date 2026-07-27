"""Work Permit (minor improvement, D22; Dulcinaria).

Card text (verbatim): "Add 1 to the current round for each building resource you have and
place 1 person from your supply on the corresponding round space. In that round, you can
use the person."
Cost: 1 Food. Prerequisite: At Least 1 Building Resource in Your Supply.

A **supply-loaner** card (the mechanism: `TEMP_WORKER_DESIGN.md`,
CARD_ENGINE_IMPLEMENTATION.md §1's 2026-07-24 entry), and Telegram's near-twin — same
"schedule a loaner for a future round" shape, differing in exactly one respect that is the
whole point of the card:

**The meeple leaves supply when the card is PLAYED, not when the loaner is used.** Telegram
merely marks a round space; Work Permit puts a real person on it. So from the moment it is
played until its round has passed, that meeple is out of play — and Family Growth to a 5th
person is blocked for that whole stretch, not just for the round the loaner works. Taking
the loaner in the target round therefore does NOT debit supply a second time
(`activate_temp_worker(debit_supply=False)`), and if the player never uses it, the parked
meeple returns to supply at that round's returning-home phase.

The rest mirrors Telegram: the target round is `current round + building resources in
supply` (wood + clay + reed + stone), the prerequisite guarantees at least one so the
target is always a later round, a target past round 14 never arrives, and the offer is
surfaced at the **last usable moment** in its round — once every household worker is placed
— because taking a loaner never yields a placement any sooner, so an earlier offer would be
a dominated choice. `engine._can_act` grants the turn.

**"On the corresponding round space" is a timing indicator, not a placement** (user ruling
2026-07-24, stated as a general principle): goods and other rewards put on the round space of
a round **not yet reached** are a reminder that they arrive at the start of that round, and
this is *completely unrelated* to the action space that round reveals or to that round's
dynamics. The object being a meeple rather than a good changes nothing — the placement is
about WHEN, not WHERE. So the round space stays a normal, unoccupied action space that either
player may use, and the effect "would be identical if the player set the worker aside and then
used it in a specified future round". That is why the parked meeple is a CardStore record here
and not a board worker marker: the record is exactly the rule, not a convenient approximation
of it. (Distinct from goods on an ALREADY-REVEALED round space, which are a live accumulation
space's stock — CARD_ENGINE_IMPLEMENTATION.md §6.)
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_card_choice_resolver
from agricola.cards.turn_offers import register_turn_start_offer
from agricola.helpers import activate_temp_worker
from agricola.pending import pop
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "work_permit"

TAKE = "take"
DECLINE = "decline"
_OPTIONS = (TAKE, DECLINE)


def _building_resources(p) -> int:
    """"Building resource" is the game's collective term for wood / clay / reed / stone
    (RULES.md); the prerequisite scopes it to the player's supply."""
    r = p.resources
    return r.wood + r.clay + r.reed + r.stone


def _update(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _prereq(state: GameState, idx: int) -> bool:
    """"At Least 1 Building Resource in Your Supply" — a have-check, not a cost. It also
    guarantees the target round is a LATER one, and that a meeple exists to park only in
    so far as the supply pile is checked separately below."""
    p = state.players[idx]
    return _building_resources(p) >= 1 and p.workers_in_supply >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Park a supply meeple on the target round space: record the round and take the
    meeple out of the supply pile NOW (which is what blocks growth in the meantime)."""
    p = state.players[idx]
    target = state.round_number + _building_resources(p)
    p = fast_replace(p,
                     workers_in_supply=p.workers_in_supply - 1,
                     card_state=p.card_state.set(CARD_ID, target))
    return _update(state, idx, p)


def _offer_eligible(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    if CARD_ID not in p.minor_improvements:
        return False
    if CARD_ID in p.used_this_round:        # answered already (liveness — see _resolve)
        return False
    if p.card_state.get(CARD_ID) != state.round_number:   # "in that round"
        return False
    return p.people_home == 0               # the last usable moment (see the docstring)
    # NOTE: no `workers_in_supply` check — unlike Telegram, this meeple left supply when
    # the card was played, so it is available regardless of the current supply pile.


def _resolve(state: GameState, idx: int, chosen) -> GameState:
    """Apply the choice and latch the offer closed.

    The latch is set on BOTH options — a LIVENESS requirement, not a "once per round"
    nicety: an outstanding offer holds the work phase open (`engine._can_act`) and
    eligibility is re-tested at every decision boundary, so an offer that survived being
    declined would be re-pushed forever.
    """
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    if chosen == TAKE:
        # The parked meeple leaves the round space for the board; drop the record so the
        # unused-return auto below does not also credit it back.
        p = fast_replace(p, card_state=p.card_state.remove(CARD_ID))
        state = activate_temp_worker(_update(state, idx, p), idx, debit_supply=False)
    else:
        state = _update(state, idx, p)
    return pop(state)   # resolver owns the PendingCardChoice frame


def _unused_return_eligible(state: GameState, idx: int) -> bool:
    """The parked meeple is still on the round space at the end of its round — the player
    never used it, so it goes back to supply now rather than being stranded there."""
    return state.players[idx].card_state.get(CARD_ID) == state.round_number


def _unused_return(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p,
                     workers_in_supply=p.workers_in_supply + 1,
                     card_state=p.card_state.remove(CARD_ID))
    return _update(state, idx, p)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    prereq=_prereq,
    on_play=_on_play,
)
register_turn_start_offer(CARD_ID, _offer_eligible, _OPTIONS)
register_card_choice_resolver(CARD_ID, _resolve)
# Fires BEFORE the returning-home reset, so an unused parked meeple is credited back to
# supply in the same phase a used one is (the reset's temp_workers_active restore).
register_auto("returning_home", CARD_ID, _unused_return_eligible, _unused_return)
