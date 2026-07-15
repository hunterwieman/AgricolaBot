"""Chief Forester (occupation, A115; Artifex Expansion; players 1+).

Card text (verbatim): "Each time you use a wood accumulation space, you also get
a "Sow" action for exactly 1 field."
Clarifications: "You may sow 2 wood onto the Wood Field D075."

Category: action-space hook granting a sub-action — the Assistant Tiller shape
(an OPTIONAL `before_action_space` trigger whose apply pushes a primitive), with
PendingPlow swapped for PendingSow.

- **Timing — BEFORE.** "Each time you use [space]" fires in the space's before
  phase (the standing Trigger-Timing ruling), so it registers on
  `before_action_space`. No stranding concern: the wood accumulation space's
  mandatory work is *taking the accumulated wood*, which needs no goods, so the
  sow (which spends grain/veg) cannot strand it (the Forest Trader argument).

- **Which spaces.** "A wood accumulation space" — at 2 players that is only Forest
  (`forest`; the sole entry of `BUILDING_ACCUMULATION_RATES` producing wood). Forest
  is ATOMIC, so it must be hosted for the trigger to attach
  (`register_action_space_hook`), exactly as Forest Trader hosts it. (3–4 players
  add Copse/Grove; the space set extends with the 4-player work.)

- **The grant is OPTIONAL** (a granted sub-action, declinable even though worded as
  a plain "you also get") — a `register` trigger, declined by the host's Proceed
  (using Forest without firing). Eligibility gates on `_can_sow` so firing is never a
  dead-end.

- **"a 'Sow' action for exactly 1 field"** → `PendingSow(max_fields=1)` — the sow is
  capped at one field-unit (the Fodder Planter partial-sow cap). `crops_only` stays
  its default False: the clarification explicitly permits sowing wood onto a Wood
  Field, so this is a generic bare "Sow" grant (the PendingSow docstring names this
  card as the crops_only=False, wood-permitting case).

Played via Lessons; on-play is a no-op. Card-only registries — the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _can_sow
from agricola.pending import PendingSow, push
from agricola.state import GameState

CARD_ID = "chief_forester"

# The only wood accumulation space at 2 players is Forest (the sole wood entry of
# BUILDING_ACCUMULATION_RATES). Atomic -> hosted via register_action_space_hook.
SPACES = frozenset({"forest"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and _can_sow(state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    # "a Sow action for exactly 1 field" -> a one-field-capped sow. crops_only
    # default False permits the Wood Field wood-sow (the clarification).
    return push(state, PendingSow(
        player_idx=idx, initiated_by_id="card:chief_forester", max_fields=1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)   # host atomic Forest when owned
