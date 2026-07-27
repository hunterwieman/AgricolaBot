"""Motivator (occupation, E93; Ephipparius; players 1+).

Card text (verbatim): "On your first turn each round, if you have no unused farmyard
spaces, you can place a person from your supply."

The first card of the **supply-loaner** family: a meeple from the player's SUPPLY acts as
a worker for one round without ever becoming a family member.

Ruled semantics (user, 2026-07-21):

- **The loaner is a borrowed worker for the round.** It is placed like a worker (it takes
  a real action space, performs the whole action, and blocks the space), returns to
  SUPPLY — not home — in the returning-home phase, never becomes a family member,
  requires no food (it is back in supply before any harvest), and scores nothing.
- **The physical-meeple constraint.** A player owns 5 meeples. While the loaner is out it
  occupies one, so **Family Growth to a 5th person is illegal while no free supply meeple
  remains** — and declining the offer in order to keep growth open can be strictly
  optimal. The offer is therefore always declinable ("you can").

Ruled 2026-07-24: **the loaner is placed on the player's first turn** — it is an
additional worker beyond the household, not two placements in a row; the household
workers follow on the player's subsequent turns under normal alternation. And a loaner
placement **advances the "Nth person you place this round" ordinal** (the plain reading),
so it can be, e.g., Henpecked Husband's "second person you place".

How it is built:

- The offer is a start-of-turn choice (`cards/turn_offers.py`), surfaced as a
  `PendingCardChoice` with options ("take", "decline") at the moment the player is handed
  their first placement turn of the round — before they place, which is what the card's
  "on your first turn" pins down.
- Taking it calls `helpers.activate_temp_worker`: one meeple moves supply -> hand
  (`workers_in_supply` -1, `people_home` +1, `temp_workers_active` +1). From there the
  loaner is FUNGIBLE with a family worker — the player simply has one more meeple to
  place, and every existing path (alternation, all-placed detection, the placement
  enumerator, a mid-round "return a person home") handles it unchanged. Nothing needs to
  know which meeple is the loaner, only how many are out.
- Growth-blocking needs no code: the wish-space gate already refuses a growth at
  `workers_in_supply == 0`, so taking the loaner with one meeple left closes growth for
  the round exactly as the physical game does.
- The returning-home reset credits the meeple back to supply (`engine._return_home_reset`).

Eligibility, and why each conjunct is there:

- **"on your first turn"** — no placement made yet this round
  (`helpers.placements_this_round == 0`). Note this stays 0 after taking the offer (the
  loaner is at home, not placed), so it is the LATCH below, not this conjunct, that stops
  the offer repeating.
- **the once-per-round latch** — set by the resolver on BOTH options. Load-bearing for
  LIVENESS, not just "once per round": the engine re-checks offers at every WORK decision
  boundary, so an offer that survived a decline would be re-pushed forever. It also stops
  a mid-round return (Sheep Inspector, Tea Time) from re-opening the window by dropping
  the placement count back to 0.
- **"no unused farmyard spaces"** — every space is a room, field, stable, or a fenced
  pasture cell. Must be the fence-aware check: a pasture is not a `CellType`, so a fenced
  but empty cell still reads `EMPTY` and a naive `cell_type` test would undercount it
  (the bug that made Big Country's identical prerequisite reject a fully-fenced farm;
  `big_country._all_farmyard_spaces_used` is the shared reference).
- **a meeple in supply** — `workers_in_supply > 0`, or there is nothing to loan.

No dead-end check is needed for the placement itself: the offer is only made on a turn the
player is already taking, so a legal placement exists, and the board always has far more
unoccupied spaces than the at most ten meeples two players can place.
"""
from __future__ import annotations

from agricola.cards.big_country import _all_farmyard_spaces_used
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_card_choice_resolver
from agricola.cards.turn_offers import register_turn_start_offer
from agricola.helpers import activate_temp_worker, placements_this_round
from agricola.pending import pop
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "motivator"

TAKE = "take"
DECLINE = "decline"
_OPTIONS = (TAKE, DECLINE)


def _offer_eligible(state: GameState, idx: int) -> bool:
    """Is this player owed Motivator's offer right now? (See the module docstring for
    why each conjunct is present; the latch is what makes this go False once answered.)"""
    p = state.players[idx]
    if CARD_ID not in p.occupations:
        return False
    if CARD_ID in p.used_this_round:            # already answered this round (liveness)
        return False
    if placements_this_round(p) != 0:           # "on your first turn"
        return False
    if p.workers_in_supply <= 0:                # no meeple in supply to loan
        return False
    return _all_farmyard_spaces_used(state, idx)


def _resolve(state: GameState, idx: int, chosen) -> GameState:
    """Apply the chosen option and latch the offer closed.

    The latch is set on BOTH options — taking AND declining — because eligibility is
    re-tested at every WORK-phase decision boundary; an offer that survived a decline
    would be re-pushed immediately and the round could never end.
    """
    p = state.players[idx]
    state = fast_replace(state, players=tuple(
        fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
        if i == idx else state.players[i]
        for i in range(len(state.players))))
    if chosen == TAKE:
        state = activate_temp_worker(state, idx)
    return pop(state)   # resolver owns the PendingCardChoice frame


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_turn_start_offer(CARD_ID, _offer_eligible, _OPTIONS)
register_card_choice_resolver(CARD_ID, _resolve)
