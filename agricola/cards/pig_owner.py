"""Pig Owner (occupation, A153; Artifex Expansion; players 4+).

Card text (verbatim): "The first time after you play this card that you have 5 wild
boars on your farm, you immediately get 3 bonus points."

A once-per-game reward keyed to an ANIMAL COUNT — the direct analog of Hook Knife
(B35), differing only in the animal (boar, not sheep), the threshold (5), and the
payout (3 points). The first time the owner has at least 5 wild boars ACCOMMODATED
on their farm, they bank 3 bonus points.

Because the trigger is a resource count (not a house-material condition), the
ordinary conditional-one-shot sweep never sees it; instead it registers on the
decision-BOUNDARY one-shot sweep (`register_boundary_one_shot`), which
`engine._fire_boundary_one_shots` runs at every agent-decision boundary right AFTER
the accommodation barrier settles. That ordering is load-bearing: `animals.boar`
then reflects the boar the farm can actually HOUSE, so a transient over-capacity
grant (which the barrier trims below the threshold) never triggers the award — the
`accommodates` guard makes "5 wild boars ON YOUR FARM" literal (mirrors Hook Knife).
Latched in `fired_once` (fires once per game); the 3 points are banked in the
per-card CardStore and read by the scoring term.

Card-only state (the CardStore int + the `fired_once` latch) is empty in the Family
game -> byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_boundary_one_shot
from agricola.helpers import accommodates
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "pig_owner"
_BOAR_THRESHOLD = 5
_BONUS = 3


def _condition(state: GameState, idx: int) -> bool:
    """>= 5 boar, all animals actually HOUSED. The `accommodates` check is
    load-bearing (as in Hook Knife): the boundary sweep also runs while a
    `PendingAccommodate` is still up, where `animals.boar` transiently exceeds what
    the farm holds — the card must not fire on those un-housed boar."""
    p = state.players[idx]
    if p.animals.boar < _BOAR_THRESHOLD:
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


# Pure boundary-one-shot occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_boundary_one_shot(CARD_ID, _condition, _apply)
register_scoring(CARD_ID, _score)
