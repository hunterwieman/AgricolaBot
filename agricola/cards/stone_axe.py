"""Stone Axe (minor improvement, Ephipparius E75; cost 1 wood + 1 clay; prereq
2 occupations; 1 VP).

Card text (verbatim): "Each time you use a wood accumulation space, you can return
1 stone to the general supply to get an additional 3 wood."

An OPTIONAL exchange offered each time you use a wood accumulation space — the
Forest Trader idiom, but with a single fixed route (return 1 stone -> get 3 wood)
rather than a menu, so a plain declinable ``FireTrigger`` (``register``), not a
play-variant. "Each time you use [space]" has no "after" qualifier → the
``before_action_space`` window (the standing trigger-timing ruling). At 2 players
the only wood accumulation space is Forest (``forest``), which is ATOMIC and so
hosted via ``register_action_space_hook``.

Eligibility gates on owning >=1 stone (the exchange must be doable) and on the
``triggers_resolved`` guard so it fires at most once per use of the space
(matching Flail's plain-trigger idiom). Firing debits 1 stone and grants 3 wood;
declining is simply not firing — the host's Proceed is the decline path. No
stranding concern: Forest's mandatory work (taking accumulated wood) needs no
resources, so spending stone first cannot strand it. Played via an improvement
space; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stone_axe"

# 2-player wood accumulation space set: Forest only (Copse / Grove are 3–4-player
# board extensions, never on the 2-player board).
_WOOD_SPACES = frozenset({"forest"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    top = state.pending_stack[-1]
    return (CARD_ID not in triggers_resolved
            and getattr(top, "space_id", None) in _WOOD_SPACES
            and state.players[idx].resources.stone >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    # Return 1 stone to the general supply, get 3 wood. Instant edit — no push.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(stone=-1, wood=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, clay=1)),
               min_occupations=2, vps=1)
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _WOOD_SPACES)
