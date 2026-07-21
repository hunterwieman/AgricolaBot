"""Hook Knife (minor improvement, B35; Bubulcus Expansion; cost 1 Wood).

Card text: "Once this game, when you have 9/8/7/6/5/5 sheep on your farm in a
1-/2-3-/4-/5-/6- player game, you immediately get 2 bonus points."

A once-per-game reward keyed to an ANIMAL COUNT: the first time the owner has at least the
threshold number of sheep accommodated on their farm, they bank 2 bonus points. In the
2-player game the threshold is 8 (the "2-3 player" band). Because the trigger is a resource
count — not a house-material condition — the ordinary conditional-one-shot sweep (renovate /
card-play seams) never sees it; instead it registers on the decision-BOUNDARY one-shot
sweep (`register_boundary_one_shot`), which `engine._fire_boundary_one_shots` runs at every
agent-decision boundary right AFTER the accommodation barrier settles. That ordering is
load-bearing: it means `animals.sheep` reflects the sheep the farm can actually HOUSE, so a
transient over-capacity grant (which the barrier will trim below the threshold) never
triggers the award. Latched in `fired_once` (fires once per game); the 2 points are banked
in CardStore and read by the scoring term.

Card-only state (the CardStore int + the fired_once latch) is empty in the Family game ->
byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_boundary_one_shot
from agricola.helpers import accommodates
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "hook_knife"
_SHEEP_THRESHOLD = 8   # 2-player game (the 9/8/7/6/5/5 ladder's "2-3 player" band)
_BONUS = 2


def _condition(state: GameState, idx: int) -> bool:
    """>= 8 sheep, all animals actually HOUSED. The `accommodates` check is load-bearing:
    the boundary sweep also runs at the boundary where a `PendingAccommodate` is still up
    (a decision-free grant pushed the player over capacity but the excess hasn't been cooked
    yet), where `animals.sheep` transiently exceeds what the farm holds — the card must not
    fire on those un-housed sheep ("8 sheep ON YOUR FARM"). Once the player commits the
    accommodation, the housed count is what this reads."""
    p = state.players[idx]
    if p.animals.sheep < _SHEEP_THRESHOLD:
        return False
    return accommodates(state, p, p.animals.sheep, p.animals.boar, p.animals.cattle)


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _BONUS))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_boundary_one_shot(CARD_ID, _condition, _apply)
register_scoring(CARD_ID, _score)
