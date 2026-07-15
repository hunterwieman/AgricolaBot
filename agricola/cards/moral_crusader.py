"""Moral Crusader (occupation, B106; Bubulcus Expansion; players 1+).

Card text: "Immediately before the start of each round, if there are goods on
the remaining round space that are promised to you, you get 1 food."
Printed VPs: none. No cost / prerequisite / passing.

Timing (user ruling 2026-07-15): "immediately before the start of each round"
names the SAME instant as the preparation ladder's `before_round` window
("before the start of each round" -- Small Animal Breeder / Civic Facade's
rung); no distinct earlier instant. So this is the ladder's FIRST rung: before
the reveal, before round-space collection, before `start_of_round`. A
MANDATORY, choice-free income -> an automatic effect (`register_auto`), fired
mechanically by the walk for the owner.

Round-number semantics: `before_round` fires BEFORE `__round_setup__`
increments, so `state.round_number` still names the JUST-COMPLETED round and
the round being entered is `round_number + 1`. "The remaining round space" is
the round space about to be entered; with the 1-indexed-round-N -> slot-N-1
convention, that round's schedule slot index is exactly `round_number`.

"Goods ... promised to you": the owner's schedule for the entering round --
`future_resources[round_number]` non-empty (the Well, the Category-8 goods
schedulers) OR the card-only `future_rewards[round_number]` carrying ANIMALS
(animals are goods -- Acorns Basket-style schedules). A scheduled EFFECT id
alone (`effect_card_ids`, e.g. Handplow's deferred plow) is not goods and
grants nothing. Because the window precedes `__collect__`, the promised goods
are still ON the round space when the check runs -- exactly what the printed
text asks -- and both the 1 food and the scheduled goods have landed by the
time the WORK phase begins.

Re-checked each round, so the income fires on every round whose space holds
goods promised to the owner and stays silent otherwise. Only the OWNER's
schedule qualifies ("promised to you") and only the owner is paid.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "moral_crusader"


def _on_play(state: GameState, idx: int) -> GameState:
    """No on-play effect — the card's income is the before_round auto."""
    return state


def _eligible(state: GameState, idx: int) -> bool:
    # Pre-increment window: the round being entered is round_number + 1, whose
    # 0-based schedule slot is round_number itself.
    slot = state.round_number
    p = state.players[idx]
    if slot >= len(p.future_resources):
        return False  # no remaining round space (defensive; the ladder ends at round 14)
    if p.future_resources[slot]:      # goods/food promised on the entering round's space
        return True
    a = p.future_rewards[slot].animals  # scheduled animals are goods too
    return bool(a.sheep or a.boar or a.cattle)
    # (a scheduled EFFECT id alone -- future_rewards.effect_card_ids -- is not goods)


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
# "Immediately before the start of each round" — the before_round window (user
# ruling 2026-07-15: the same instant as Small Animal Breeder / Civic Facade's
# "before the start of each round"; no distinct earlier instant).
register_auto("before_round", CARD_ID, _eligible, _apply)
