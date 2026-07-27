"""Child Ombudsman (occupation, D92; Dulcinaria; players 1+).

Card text (verbatim): "From round 5 on, if you have room in your house, at the end of
each person action, you can take a 'Family Growth' action with that person. If you do,
you get 2 negative points."

NOT a worker-movement card, despite the "with that person" phrasing (ruling 81 item 4 —
it entered the same-worker-jump family lists as a sweep artifact): nothing moves. It is a
granted no-space Family Growth — the Stork's Nest shape at a different instant — plus a
per-use scoring penalty.

Rulings (user, 2026-07-26; ruling 81 item 4):

- **"At the end of each person action" = the `after_action_space` window** (the same
  reading as Sheep Inspector's "after you complete a person action", ruling 74). Hooked
  over the full space list so atomic spaces host while the card is owned; non-atomic
  spaces and card spaces host natively and fire the same event.
- **It can fire multiple times per turn** when a turn contains multiple person actions
  (Job Contract's chained Day Laborer → Lessons, once built). So there is NO
  per-round/per-turn latch — once-per-window is the host's `triggers_resolved`, and the
  only caps are the real ones: rooms, the meeple supply, and the −2 per use.

Mechanics:

- **"If you have room in your house"** is the standard family-growth room gate —
  `people_total < _housing_capacity(state, idx)`, the same predicate as the Basic Wish
  space's "only if you have room" (so people-capacity cards — Homekeeper, Bunk Beds,
  Reader — extend it, exactly as they extend the wish spaces). The family cap rides the
  meeple supply (`workers_in_supply > 0`), per the standard growth chokepoint.
- **Firing pushes `PendingFamilyGrowth(place_on_space=False)`** — the card-granted
  growth the user ruled occupies NO action space (Group A1); "with that person" is the
  acting person performing it in place. The newborn is a normal newborn (fed 1 food at a
  same-round harvest; matures at round entry). The growth is not a placement act, so the
  ordinal counter is untouched ("Newborns are not placed", ruling 79).
- **"You get 2 negative points"** per use: a CardStore use-counter incremented at fire,
  scored as −2 × uses via `register_scoring` (the Recount/Almsbag negative-term seam).
  The counter increments in the same apply that pushes the growth — the pushed primitive
  runs to completion (no decline on `PendingFamilyGrowth`), so "If you do" is satisfied:
  a fire IS a growth.
- Optional ("you can"): surfaced as a FireTrigger; declining is picking anything else at
  the host (Stop/Proceed) — no skip flag, per the engine invariant.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import SPACE_IDS
from agricola.legality import _housing_capacity
from agricola.pending import PendingFamilyGrowth, push
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "child_ombudsman"


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """Round 5+, room in the house (the standard growth room gate, capacity cards
    included), and a meeple in supply — never a dead-end."""
    if state.round_number < 5:
        return False
    p = state.players[idx]
    if p.workers_in_supply <= 0:
        return False
    return p.people_total < _housing_capacity(state, idx)


def _apply(state: GameState, idx: int) -> GameState:
    """Count the use (−2 points each) and grant the no-space growth."""
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


def _score(state: GameState, idx: int) -> int:
    return -2 * state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply)
# "Each person action" = every space: hook the whole canonical list (atomic spaces are
# hosted only when hooked; non-atomic ids in the hook set are harmless — the Sheep
# Inspector pattern).
register_action_space_hook(CARD_ID, SPACE_IDS)
register_scoring(CARD_ID, _score)
