"""Forestry Studies (minor improvement, B28; Bubulcus Expansion).

Card text: "Each time after you use the 'Forest' accumulation space, you can return
2 wood to that space to play 1 occupation without paying an occupation cost."
Cost: 2 Food. No prerequisite. No VPs. Not passing.

An OPTIONAL `after_action_space` trigger on the Forest wood accumulation space (the
only wood accumulation space on the 2-player board). The text's "after you use" is
the explicit "immediately after" exception to the default "each time you use [space]"
= before ruling — the same wording Carpenter's Axe / Mushroom Collector ride — so it
rides `after_action_space`, firing only once Forest's own pickup (+wood into the
player's supply) has already happened. The "return 2 wood to that space" is therefore
a HAVE-check on the POST-pickup supply: the engine runs ATOMIC_HANDLERS["forest"]
first (sweeping the wood into the player's supply), then `_enter_after_phase` flips to
the after-phase where eligibility is evaluated, so a player who picked the wood up now
reads it and can give 2 of it back.

Forest is an ATOMIC space, so it must be explicitly hosted (`register_action_space_hook`)
to push a PendingActionSpace frame whose Proceed flips to the after-phase and surfaces
this trigger — the same wiring Carpenter's Axe / Mushroom Collector use for the atomic
Forest space.

OPTIONALITY: "you can return ... to play" → an OPTIONAL FireTrigger (`register`, not
`register_auto`). The decline path IS not firing the trigger — the host's Proceed/Stop
exits without playing. Because firing pushes a PendingPlayOccupation whose own
enumerator offers a CommitPlayOccupation per playable hand occupation (no decline once
pushed — the Scholar precedent), eligibility gates on a playable hand occupation
actually existing, to never offer a dead-end fire.

EFFECT (`_apply`): debit 2 wood from the player and place that wood back on the Forest
accumulation space (the "return 2 wood to that space" clause — like Mushroom Collector,
the wood goes onto the space, not the general supply, so it is there for whoever uses
Forest next; by the after-phase Proceed has already swept the space, so this leaves 2
wood on it). Then push PendingPlayOccupation(cost=Resources()) — `cost=Resources()` is
the empty (zero-food) cost, so `_execute_play_occupation` debits nothing: the
occupation plays free, honoring "without paying an occupation cost" (the Scholar
precedent for a non-Lessons free occupation play).

"Each time" = once per use, enforced by `CARD_ID not in triggers_resolved` (NOT
used_this_round — it may fire on every Forest use), exactly as Carpenter's Axe /
Mushroom Collector. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "forestry_studies"

# Wood accumulation spaces this card fires on. 2-player: Forest only (Copse /
# Grove are 3–4-player board-extension spaces, never on the 2-player board).
WOOD_SPACES = frozenset({"forest"})

_WOOD_RETURNED = 2


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per Forest use
        return False
    if state.pending_stack[-1].space_id not in WOOD_SPACES:
        return False
    p = state.players[idx]
    # Must be able to return 2 wood (post-pickup HAVE-check) AND have a playable hand
    # occupation to spend the free play on — never a dead-end fire.
    return p.resources.wood >= _WOOD_RETURNED and bool(playable_occupations(state, idx))


def _apply(state: GameState, idx: int) -> GameState:
    """Return 2 wood to the Forest space, then push a FREE occupation play."""
    space_id = state.pending_stack[-1].space_id
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=-_WOOD_RETURNED))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    # "return 2 wood to that space" — onto the accumulation space, not general supply.
    sp = get_space(state.board, space_id)
    sp = fast_replace(sp, accumulated=sp.accumulated + Resources(wood=_WOOD_RETURNED))
    state = fast_replace(state, board=with_space(state.board, space_id, sp))
    # Play 1 occupation for free (cost=Resources() → zero food debited).
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", cost=Resources()))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)))
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_SPACES)
