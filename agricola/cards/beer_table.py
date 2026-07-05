"""Beer Table (minor improvement, C29; Corbarius Expansion; Points Provider).

Card text (verbatim): "At the end of the field phase of each harvest, you can pay
1 grain from your supply to get 2 bonus points. If you do, all other players get 1
food each."

Cost: 2 Wood. Printed VPs: 0 (vps=null — the points come from the recurring
effect, not a static value). Prerequisite: "No Grain in Your Supply". Not passing.

TIMING — window #6 ``end_of_field_phase`` (HARVEST_WINDOWS_DESIGN.md §1 ladder
lists Beer Table as the sole census member of window #6). The printed "At the end
of the field phase of each harvest" is the last moment INSIDE the field phase —
after window #5's crop take, before window #7 ``after_field_phase``. This window
sits inside the per-player FIELD segment: under ruling 3 (2026-07-03,
CARD_DEFERRED_PLANS.md → Harvest-window redesign) the starting player resolves
their WHOLE FIELD segment (windows #3..#7) before the other player's begins, so
the two players' #6 frames never coexist and firing order is fixed SP-first.

INTERACTION SURFACE (owner-flagged): because the effect PAYS 1 grain (consuming a
crop just harvested during the same field segment) and its "If you do, all other
players get 1 food each" clause HANDS FOOD to the opponent, its exact instant is
high-stakes relative to other during-phase cards. Under ruling 3's
whole-segment-per-player ordering the starting player's Beer Table fires while the
other player has NOT yet started their FIELD segment, so the food it hands over is
available to the other player's later during-phase / feeding effects (e.g. a
non-starter's Cube Cutter, which spends food at window #5). See
HARVEST_WINDOWS_DESIGN.md §11 "Player interleaving" — Beer Table × Cube Cutter is
the named worked example of the funding line ruling 3 creates. Nothing in this
card's own resolution depends on that ordering; the food it grants and the grain
it spends are applied at exactly the ``end_of_field_phase`` instant printed.

DECLINABLE ("you can") — an optional trigger on the per-player
``PendingHarvestWindow`` frame; ``Proceed`` declines. Once per window is automatic
(the frame's ``triggers_resolved`` records the fire, so it cannot fire twice in one
harvest's window #6). There is no quantity/target choice — a fixed 1 grain for a
fixed 2 bonus points and the fixed opponent-food side-effect — so this is a plain
trigger, not a play-variant.

THE COST — the window machinery carries no cost layer, so ``_apply`` debits the 1
grain itself, and affordability (>= 1 grain) is checked in ``_eligible`` so the
trigger is offered only when it can be paid.

BONUS POINTS — "get 2 bonus points" cannot be granted as an immediate score (no
immediate-VP mechanism exists), so each fire banks +2 in a per-card CardStore
counter (accumulated across all six harvests) and the scoring term reads it back at
end-game — the same mechanism Home Brewer's "vp" variant uses.

"If you do, all other players get 1 food each" — the food grant is CONDITIONAL on
paying, so it is applied inside ``_apply`` (which only runs when the player fires,
i.e. chooses to pay) and NOT on decline. In the 2-player game "all other players"
is the single opponent (``1 - idx``), who gains 1 food — the same shape as
Christianity's on-play gift. (Weighted for [3+]/[4] per CLAUDE.md Phase 3: the
grant loops over every other seat, so a wider table would each get 1 food; only 2
seats exist today.)

Prerequisite "No Grain in Your Supply" — a play-time HAVE-check that the player
holds zero grain (``resources.grain == 0``) at the moment of playing the card. It
is NOT re-checked afterward: the card may hold grain later (that is what it spends
each harvest); the prerequisite only gates the initial play.

Card-only state (the CardStore int) is empty in the Family game, so it stays
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "beer_table"
WINDOW_ID = "end_of_field_phase"

_GRAIN_COST = 1
_BONUS_POINTS = 2
_OTHER_FOOD = 1


def _prereq_no_grain(state: GameState, idx: int) -> bool:
    """Prerequisite "No Grain in Your Supply": zero grain at play time (a
    have-check, never re-evaluated after the card is in play)."""
    return state.players[idx].resources.grain == 0


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff the player owns Beer Table AND holds >= 1 grain to pay.

    Ownership is also gated by the host enumerator; keeping the check here is
    explicit and matches the surrounding card idioms. Affordability lives here
    because the window machinery has no cost layer. The once-per-window limit is
    the frame's ``triggers_resolved`` (checked by the enumerator, not here)."""
    p = state.players[idx]
    return CARD_ID in p.minor_improvements and p.resources.grain >= _GRAIN_COST


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 grain; bank 2 bonus points; and (because you paid) give every other
    player 1 food. The window trigger carries no cost layer, so this debits the
    grain and grants the effects in one step."""
    p = state.players[idx]
    card_state = p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + _BONUS_POINTS)
    p = fast_replace(
        p, resources=p.resources - Resources(grain=_GRAIN_COST), card_state=card_state
    )
    players = [p if i == idx else state.players[i] for i in range(len(state.players))]
    # "all other players get 1 food each" — every seat except the payer.
    for other in range(len(players)):
        if other != idx:
            players[other] = fast_replace(
                players[other],
                resources=players[other].resources + Resources(food=_OTHER_FOOD),
            )
    return fast_replace(state, players=tuple(players))


def _score(state: GameState, idx: int) -> int:
    """Bonus points banked across all harvests (2 per fire)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), prereq=_prereq_no_grain)
# Recurring once-per-harvest optional trigger at the end of the field phase
# (window #6): pay 1 grain -> bank 2 bonus points + give each opponent 1 food.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
register_scoring(CARD_ID, _score)
