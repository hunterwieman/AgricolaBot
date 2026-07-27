"""Delayed Wayfarer (occupation, E125; Ephipparius; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 building resource
of your choice and, once all people have been placed this round, you can place a person
from your supply."

The fourth (and final buildable) card of the **supply-loaner** family — a meeple from the
player's SUPPLY works for one round without joining the family (`TEMP_WORKER_DESIGN.md`;
CARD_ENGINE_IMPLEMENTATION.md §1's 2026-07-24 entry). Motivator's loaner comes on the
owner's FIRST turn; Telegram's and Work Permit's once the OWNER's workers are exhausted;
Delayed Wayfarer's instant is later still — "once all people have been placed" means
**every player's** workers, the shared boundary at which the work phase would otherwise
end.

Rulings (user, 2026-07-26):

- **One-shot.** "This round" is the round the card is PLAYED — the loaner clause never
  recurs (contrast Motivator's explicit "each round"). The play round is recorded in
  CardStore; a later round can never match it.
- **The loaner's placement happens INSIDE the work phase**, before the `end_of_work`
  rung — so it is visible to the end-of-work occupancy readers (Iron Hoe's "occupy both
  'Grain Seeds' and 'Vegetable Seeds'", Pub Owner's three-space check): the bonus worker
  can complete their conditions. This falls out structurally: an unanswered offer keeps
  the phase open (`engine._can_act`), and the granted placement resolves through the
  ordinary pipeline before the phase-end gate passes.

How it is built (both effects ride the shared `PendingCardChoice` resolver, dispatched on
the chosen option — the option sets are disjoint):

1. **On play**: record the play round in CardStore, then push a `PendingCardChoice` over
   ("wood", "clay", "reed", "stone") — "1 building resource of your choice" is mandatory
   with a choice, so there is no decline option.
2. **The loaner offer** (`cards/turn_offers.py`): eligible when the card was played THIS
   round ∧ every player's `people_home == 0` ∧ the owner has a supply meeple ∧ not yet
   answered. The all-players-placed condition is exactly the moment the work phase would
   end; `engine._can_act` counts the outstanding offer as "this player may yet place",
   so the phase stays open and the alternation routes the turn to the owner. Taking
   calls `helpers.activate_temp_worker` (supply → hand; the meeple then places through
   the untouched normal pipeline, minting the next placement ordinal per ruling 79);
   declining changes nothing. **Both answers set the `used_this_round` latch — a
   LIVENESS requirement**: the outstanding offer is what holds the work phase open, and
   eligibility is re-tested at every boundary, so an offer that survived its own decline
   would re-push forever and the round could never end.

The growth tradeoff is the family's usual one, enforced with no card code: the loaner
occupies a physical supply meeple, so a player at 5 family (supply 0) simply cannot use
the effect, and taking it with the last meeple closes Family Growth for the round.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_card_choice_resolver
from agricola.cards.turn_offers import register_turn_start_offer
from agricola.helpers import activate_temp_worker
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "delayed_wayfarer"

TAKE = "take"
DECLINE = "decline"
_OFFER_OPTIONS = (TAKE, DECLINE)
_RESOURCE_OPTIONS = ("wood", "clay", "reed", "stone")


def _update(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _on_play(state: GameState, idx: int) -> GameState:
    """Record the play round (the loaner clause's one-shot anchor), then surface the
    mandatory building-resource choice."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, state.round_number))
    state = _update(state, idx, p)
    return push(state, PendingCardChoice(
        player_idx=idx,
        initiated_by_id=f"card:{CARD_ID}",
        options=_RESOURCE_OPTIONS,
    ))


def _offer_eligible(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    if CARD_ID not in p.occupations:
        return False
    if CARD_ID in p.used_this_round:            # answered already (liveness)
        return False
    if p.card_state.get(CARD_ID) != state.round_number:   # one-shot: the play round only
        return False
    if p.workers_in_supply <= 0:                # no meeple to loan (e.g. 5 family)
        return False
    # "Once all people have been placed this round" — EVERY player's, the shared
    # boundary (contrast Telegram, whose instant is the OWNER's workers exhausted).
    return all(pl.people_home == 0 for pl in state.players)


def _resolve(state: GameState, idx: int, chosen) -> GameState:
    """One resolver for both of this card's choices, dispatched on the option — the
    on-play resource pick and the loaner offer have disjoint option sets."""
    p = state.players[idx]
    if chosen in _RESOURCE_OPTIONS:
        p = fast_replace(p, resources=p.resources + Resources(**{chosen: 1}))
        return pop(_update(state, idx, p))
    # The loaner offer. Latch on BOTH answers (liveness — see the module docstring).
    state = _update(state, idx, fast_replace(
        p, used_this_round=p.used_this_round | {CARD_ID}))
    if chosen == TAKE:
        state = activate_temp_worker(state, idx)
    return pop(state)


register_occupation(CARD_ID, _on_play)
register_turn_start_offer(CARD_ID, _offer_eligible, _OFFER_OPTIONS)
register_card_choice_resolver(CARD_ID, _resolve)
