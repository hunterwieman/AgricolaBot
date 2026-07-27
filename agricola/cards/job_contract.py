"""Job Contract (minor improvement, C23; Corbarius).

Card text (verbatim): "If both are unoccupied, you can use the "Day Laborer" and the
adjacent "Lessons" action space with a single person (in that order). Afterward, both
spaces are considered occupied."
Clarification: "Recommendation: occupy Day Laborer with a suggestion marker and Lessons
with your person."
Prerequisite: No Occupations. No cost, no printed VP.

A same-worker JUMP card (ruling 81, 2026-07-26), and the one member whose source does
NOT re-open:

- **The chain** (ruling 81 item 1): the jump is an optional trigger in Day Laborer's
  `after_action_space` window — the person uses Day Laborer normally (its placement
  consumed Day Laborer's unoccupancy; Lessons' unoccupancy is read at the trigger time,
  the ruled check-point), then firing moves the person to Lessons and runs the full
  Lessons action (`worker_moves.relocate_and_use` → the Lessons host plays an occupation
  at the normal Lessons price). The walk returns to Day Laborer's after-window for any
  remaining triggers. No placement number is minted (ruling 79 — the person keeps its
  number, which is ambient in the same turn).
- **"Afterward, both spaces are considered occupied"** (ruling 81 item 3): legality
  treats BOTH spaces as occupied, but physically there is ONE worker — the person stands
  on Lessons (a real board worker); Day Laborer holds a suggestion MARKER, not a worker.
  The marker is this card's CardStore entry (the round number of the chain), consulted
  by the `SPACE_BLOCK_EXTENSIONS` legality seam — it never enters the worker tuples, so
  nothing that counts or returns PEOPLE can see a phantom (the double-credit hazard the
  ruling names: a Sheep Inspector could otherwise "return" a person that doesn't exist,
  and worker-count readers would over-read).
- **A return frees BOTH spaces** (ruling 81 item 3): if the chained person is returned
  home from Lessons (Sheep Inspector; Henpecked Husband's return), the marker clears via
  the `WORKER_RETURNED_HOOKS` convention — Day Laborer and Lessons are then both open,
  exactly as ruled. The marker also dies with the round on its own (it stores the chain's
  round number; a stale round never blocks), so no round-end sweep is needed.

Re-chaining: the text prints no once-per-round cap. Structurally the chain locks itself
out (Day Laborer is marker-blocked, Lessons person-occupied) — but after a mid-round
return frees both, a re-placed person could chain again. Nothing forbids it; allowed.

Flagged OPEN for the 3+ pass (not decided here): whether "considered occupied" extends
beyond placement LEGALITY to occupancy-READING cards (Turnip Farmer's "Day Laborer and
Grain Seeds occupied", Pub Owner's all-occupied checks — all 3+/4+). Ruling 81 item 3
scoped the marker to legality; the marker is invisible to worker-tuple readers today.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.cards.worker_moves import register_worker_returned, relocate_and_use
from agricola.legality import _legal_lessons_cards, register_space_block
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "job_contract"


def _update(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """At the owner's Day Laborer after-window: the chain is offered iff the full
    Lessons action is legal right now — `_legal_lessons_cards` bundles exactly the
    ruled conditions: Lessons unoccupied (ruling 81 item 2's trigger-time read, via
    `_is_available`), a playable occupation in hand, and the occupation cost payable.
    Never a dead-end."""
    top = state.pending_stack[-1] if state.pending_stack else None
    if getattr(top, "space_id", None) != "day_laborer":
        return False
    if getattr(top, "player_idx", None) != idx:
        return False
    if CARD_ID not in state.players[idx].minor_improvements:
        return False
    return _legal_lessons_cards(state)


def _apply(state: GameState, idx: int) -> GameState:
    """Set the Day-Laborer marker (BEFORE the jump, so legality reads mid-Lessons see
    it), then move the person to Lessons and run the full Lessons action."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, state.round_number))
    state = _update(state, idx, p)
    return relocate_and_use(state, idx, "day_laborer", "lessons")


def _day_laborer_blocked(state: GameState, space_id: str) -> bool:
    """The suggestion marker: Day Laborer is "considered occupied" for the rest of the
    round of either player's chain. Cheap miss path first — this runs on the common
    unoccupied branch of `_is_available`."""
    if space_id != "day_laborer":
        return False
    return any(p.card_state.get(CARD_ID) == state.round_number
               for p in state.players)


def _clear_marker_on_return(state: GameState, idx: int, space_id: str) -> GameState:
    """The chained person came home from Lessons -> both spaces open (ruling 81
    item 3): drop the marker. (The owner holds at most one worker on Lessons, so any
    own return from Lessons while the marker is live IS the chained person.)"""
    if space_id != "lessons":
        return state
    p = state.players[idx]
    if p.card_state.get(CARD_ID) != state.round_number:
        return state
    return _update(state, idx, fast_replace(
        p, card_state=p.card_state.remove(CARD_ID)))


register_minor(CARD_ID, max_occupations=0)      # "No Occupations"; no cost, no VP
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, {"day_laborer"})    # atomic source: host when owned
register_space_block(_day_laborer_blocked)
register_worker_returned(CARD_ID, _clear_marker_on_return)
