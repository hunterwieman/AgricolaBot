"""Bookshelf (minor improvement, D49; Consul Dirigens Expansion; Food Provider).

Card text: "Immediately before each time you play an occupation (even before paying the
occupation cost), you get 3 food."

Cost 1 wood; prerequisite 3 occupations; worth 1 VP.

A MANDATORY, unconditional `before_play_occupation` automatic effect: each time you play an
occupation (via Lessons, Scholar, or any future route), BEFORE its cost is paid, you get 3
food. "you get 3 food" is a pure-goods grant with no downside or choice, so it is an
`register_auto` (fires automatically), NOT a declinable `register` trigger. The play-occupation
host's before-phase already surfaces `before_play_occupation` autos, so no new firing machinery
is needed — the auto runs at frame-push time (`_fire_subaction_before_auto`, when
`ChooseSubAction("play_occupation")` pushes `PendingPlayOccupation`), and the cost debit happens
later in `_execute_play_occupation`, so the 3 food correctly lands BEFORE the cost is paid (the
"even before paying the occupation cost" clause).

"each time you play an occupation": Bookshelf is a minor and is already in the tableau before any
occupation play, so unlike Paper Maker (an occupation that must self-exclude on its own play)
there is no self-firing concern — it simply fires on every occupation play once owned.

Because the 3 food is usable for the occupation's food cost, Bookshelf ALSO registers an
OCCUPATION_FOOD_SOURCE: the occupation-affordability GATE (Lessons / Scholar — `_payable_occupation`)
runs BEFORE the auto fires (before the frame is pushed), so without this registration an
occupation payable only via Bookshelf's 3 food would be wrongly un-offered (the player would never
reach the frame where the auto lands the food). The source declares NO inputs — the 3 food is free
— distinguishing it from Paper Maker's 1-wood->N-food trade. There is no double-count: the source
is consulted only at the offer-gate (a hypothetical "could I pay if the food were here"), while the
auto applies the real food at frame-push (a later, distinct evaluation point); and unlike Paper
Maker NO commit-gate withholding is needed, since the auto lands the food automatically before any
`CommitPlayOccupation` is reachable. See PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_occupation_food_source
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "bookshelf"

_FOOD = 3


def _eligible(state: GameState, idx: int) -> bool:
    # Unconditional pure-goods grant: always fires for the owner before each occupation play.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=_FOOD))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _food_source(state: GameState, idx: int):
    """For the occupation-affordability gate: 3 free food, no inputs consumed. Always available
    once owned (it fires automatically), so it never returns None."""
    return (_FOOD, Resources())


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    min_occupations=3,
    vps=1,
)
register_auto("before_play_occupation", CARD_ID, _eligible, _apply)
register_occupation_food_source(CARD_ID, _food_source)
