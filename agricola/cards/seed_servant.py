"""Seed Servant (occupation, E115; Ephipparius Expansion; players 1+).

Card text (verbatim): "Each time after you use the \"Grain Seeds\" or
\"Vegetable Seeds\" action space, you can take a \"Bake bread\" or \"Sow\"
action, respectively."

TIMING — the text says "each time AFTER you use" (an explicit "after"
exception to the default "each time you use" = before ruling), so the grant
rides `after_action_space`, NOT `before_action_space`. Both Grain Seeds and
Vegetable Seeds are ATOMIC spaces, so each must be explicitly hosted
(`register_action_space_hook`) or the after-window would never exist. The
after-timing is load-bearing: by the after-phase the space's own pickup has
resolved (Grain Seeds +1 grain, Vegetable Seeds +1 vegetable), so the
just-taken seed counts toward the grant's eligibility — using Grain Seeds
with 0 grain and a Fireplace makes the bake offerable.

CORRELATION — "respectively" is the strict slash-correlation rule: Grain
Seeds grants a "Bake bread" action, Vegetable Seeds grants a "Sow" action,
never crosswise. One trigger registration serves both spaces by dispatching
on the host frame's `space_id` in both eligibility and apply.

OPTIONALITY — "you can" grants a sub-action, and a granted sub-action must
have a decline path (CARD_AUTHORING_GUIDE.md — granted sub-actions are
optional): declining is Stop on the host's after-phase without firing the
trigger. Once per use comes from the host frame's `triggers_resolved`.

ELIGIBILITY — never push a dead frame (a before-phase PendingBakeBread /
PendingSow offers no Stop), so the trigger is offered only when the granted
action is doable right now, via the engine's own predicates: Grain Seeds
gates on `_can_bake_bread` (a baking improvement or card extension + grain),
Vegetable Seeds on `_can_sow` (>= 1 empty field cell AND a crop in supply,
or a card-field sow).

THE GRANT — firing pushes the existing primitive with this card's
provenance. The granted "Sow" is the full standard sow action (an uncapped,
generic `PendingSow` — any number of empty fields, grain and/or veg; the
Slurry Spreader C71 precedent for a bare granted "Sow" action); the granted
"Bake bread" is the standard `PendingBakeBread` (its own before/after card
windows, e.g. Potter, work unchanged inside it). On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _can_bake_bread, _can_sow
from agricola.pending import PendingBakeBread, PendingSow, push
from agricola.state import GameState

CARD_ID = "seed_servant"

# The two atomic seed spaces; both must be hosted (see module docstring).
SEED_SPACES = frozenset({"grain_seeds", "vegetable_seeds"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:            # at most once per space use
        return False
    space_id = state.pending_stack[-1].space_id
    p = state.players[idx]
    if space_id == "grain_seeds":               # -> a "Bake bread" action
        return _can_bake_bread(state, p)
    if space_id == "vegetable_seeds":           # -> a "Sow" action
        return _can_sow(p)
    return False


def _apply(state: GameState, idx: int) -> GameState:
    # The fire is recorded on the host before this runs, so the top frame is
    # still the after-phase host; dispatch on its space_id (strict
    # slash-correlation — never a bake off Vegetable Seeds or vice versa).
    space_id = state.pending_stack[-1].space_id
    if space_id == "grain_seeds":
        return push(state, PendingBakeBread(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))
    return push(state, PendingSow(                      # vegetable_seeds
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_occupation(CARD_ID, lambda state, idx: state)   # on-play: no effect
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SEED_SPACES)          # both atomic
