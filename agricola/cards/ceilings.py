"""Ceilings (minor improvement, B76; Bubulcus Expansion; cost 1 clay, prereq
1 occupation).

Card text: "Place 1 wood on the next 5 round spaces. At the start of these rounds,
you get the wood. Remove the wood promised by this card from future round spaces
the next time you renovate."

Two clauses:

- **Deferred goods (on_play).** Category 8 (the Pond Hut shape): schedule 1 wood
  onto the next 5 round spaces (rounds R+1..R+5) of `future_resources` via
  `schedule_resources`; the wood is collected automatically at the start of each of
  those rounds by `engine._complete_preparation`. Out-of-game rounds (> 14) are
  dropped by the schedule convention, so a late play seeds fewer than 5 slots. The
  slots ACTUALLY seeded are recorded (sorted `tuple[int]`) in the per-card CardStore
  under key "ceilings", so the removal clause below knows precisely what this card
  promised (and touches nothing else).

- **Removal on renovate (after_renovate).** "Remove … the next time you renovate"
  is MANDATORY ("Remove …", no "you can") and parameter-free → an automatic effect
  (`register_auto`, default `any_player=False` — the OWNER's own renovate). User
  ruling 2026-07-20: "the next time you renovate" means the owner's own next
  renovate from ANY source — an action-space renovate or a card-granted renovate —
  since every renovate flows through the `PendingRenovate` frame and fires
  `after_renovate` uniformly. Eligibility = the CardStore record is non-empty. Apply
  = subtract exactly 1 wood from `future_resources` at each recorded slot that is
  STILL UNCOLLECTED, then clear the record entirely (the cleared record is the
  once-only latch, so a second renovate does nothing). Wood from rounds already
  collected stays in the player's supply, untouched.

The slot convention (matching `engine._complete_preparation` /
`cards/schedules.py`): slot `s` (0-indexed) holds the goods for round `s+1`,
collected when round `s+1` is entered (i.e. once `round_number` reaches `s+1`).
So during the work phase of round M (`round_number == M`), slot `s` has been
collected iff `s < M`, and is still uncollected iff `s >= M`. The removal therefore
subtracts only from recorded slots with `s >= state.round_number` (user ruling
2026-07-20). It subtracts EXACTLY 1 wood per such slot — never clamped against, and
never disturbing, wood other cards scheduled onto the same slots: `future_resources`
is additive across schedulers, so removing 1 removes only what this card added.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "ceilings"
_NUM_ROUNDS = 5   # "the next 5 round spaces"


def _update_player(state: GameState, idx: int, new_player) -> GameState:
    return fast_replace(state, players=tuple(
        new_player if i == idx else state.players[i]
        for i in range(len(state.players))))


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    rounds = range(R + 1, R + 1 + _NUM_ROUNDS)   # the next 5 round spaces
    n_slots = len(state.players[idx].future_resources)
    # Record exactly the slots schedule_resources will actually seed (it drops any
    # slot outside 0..n_slots-1 — the out-of-game-round convention). Sorted tuple.
    seeded = tuple(sorted(
        rnd - 1 for rnd in rounds if 0 <= rnd - 1 < n_slots))
    state = schedule_resources(state, idx, rounds, Resources(wood=1))
    if seeded:   # nothing placed (e.g. played in round 14) → nothing to remember
        p = state.players[idx]
        state = _update_player(state, idx,
                               fast_replace(p, card_state=p.card_state.set(CARD_ID, seeded)))
    return state


def _eligible_renovate(state: GameState, idx: int) -> bool:
    # Fire iff this card still has promised wood on the books (non-empty record).
    return bool(state.players[idx].card_state.get(CARD_ID, ()))


def _remove_promised_wood(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    recorded = p.card_state.get(CARD_ID, ())
    slots = list(p.future_resources)
    for s in recorded:
        if s >= state.round_number:   # still uncollected (round s+1 not yet entered)
            slots[s] = slots[s] - Resources(wood=1)   # remove exactly what this card added
    # Clear the record entirely — the once-only latch (a later renovate does nothing).
    p = fast_replace(p, future_resources=tuple(slots),
                     card_state=p.card_state.remove(CARD_ID))
    return _update_player(state, idx, p)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=1)),
    min_occupations=1,   # prereq: 1 Occupation
    on_play=_on_play,
)
register_auto("after_renovate", CARD_ID, _eligible_renovate, _remove_promised_wood)
