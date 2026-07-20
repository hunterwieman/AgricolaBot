"""Facades Carving (minor improvement, A36; Artifex Expansion; Points Provider).

Card text (verbatim): "When you play this card, you can exchange any number of
food for 1 bonus point each, up to the number of completed harvests."
Cost: 2 Clay, 1 Reed. Prerequisite: Wood in Your Supply >= Current Round.
VPs: none printed. Not passing.

A one-shot, on-play food-to-points exchange: at the moment this card is played
the player may pay any number of food (their choice, including zero — "you can")
and bank 1 bonus point per food paid, capped at the number of harvests that
have already happened.

Timing/mechanism — "When you play this card, you can ..." is an OPTIONAL
on-play choice, and per the user ruling of 2026-07-06 such on-play choices
surface WIDE: one play action per food amount ("play paying 0 food", "play
paying 1 food", ...), the minor-improvement analog of Baker's occupation
pattern (user ruling 17, 2026-07-05 — the choice is part of the single play
action, never an after-play trigger that could interleave with other cards).
The card registers a `variants_fn` on the `PLAY_MINOR_VARIANTS` seam
(specs.register_play_minor_variant): each variant "f<k>" carries a
`Resources(food=k)` SURCHARGE on top of the card's printed cost. The
play-minor enumerator folds the surcharge into the commit's `payment` and
offers only the affordable variants (liquidation-aware via `_payable`, so
convertible goods count toward the food); `_execute_play_minor` debits the
folded payment and threads the chosen variant into the 3-arg on-play, which
grants the BENEFIT only (the food was already paid). The zero-surcharge "f0"
variant is always in the list, so the card stays playable whenever its base
cost is — declining the exchange entirely is a legal play.

"the number of completed harvests": harvests happen at the end of rounds 4, 7,
9, 11, 13, 14 (`constants.HARVEST_ROUNDS`). A minor is played during the WORK
phase of some round r, at which point the completed harvests are exactly the
harvest rounds STRICTLY below r — derived from `state.round_number` on demand,
never stored. Round 1 -> 0 (the sole variant is "f0"); round 8 -> 2 (rounds 4
and 7); round 14 -> 5.

Bonus points cannot be granted immediately (there is no immediate-VP
mechanism), so the on-play banks the paid amount in the player's `CardStore`
and a `register_scoring` term reads it back at end-game (the banked-VP idiom —
Elephantgrass Plant). Do NOT set vps= (that scores a printed keep-VP, which
this card does not have — the points are earned).

The prerequisite "Wood in Your Supply >= Current Round" is a play-time
HAVE-check (never spent): `p.resources.wood >= state.round_number`, encoded as
a custom `prereq` predicate exactly as the other round-comparison prereqs
(Digging Spade, Growing Farm).

Family-inertness: minors exist only under GameMode.CARDS; the
PLAY_MINOR_VARIANTS registry and the CardStore entry are card-only, so the
Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "facades_carving"


def _completed_harvests(state: GameState) -> int:
    """Harvests already completed at this point of the game: harvests happen at
    the END of the rounds in HARVEST_ROUNDS, and a minor is played during a
    round's WORK phase, so exactly the harvest rounds strictly below the
    current round have completed. Derived, never stored."""
    return sum(1 for h in HARVEST_ROUNDS if h < state.round_number)


def _variants(state: GameState, idx: int) -> list:
    """One play route per food amount f in 0..completed_harvests: variant
    "f<k>" surcharges k food on top of the printed cost. All amounts up to the
    harvest cap are enumerated here; filtering to what the player can PAY is
    the seam's job (the enumerator's liquidation-aware `_payable` gate). "f0"
    (no exchange — "you can") is always present, so the card is playable
    whenever its base cost is."""
    return [(f"f{f}", Resources(food=f))
            for f in range(_completed_harvests(state) + 1)]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Bank 1 bonus point per food paid. The chosen variant's food surcharge
    was already debited (folded into the commit's payment at enumeration), so
    this grants only the benefit: the banked-VP CardStore entry the scoring
    term reads back."""
    f = int(variant[1:])            # "f2" -> 2
    if f == 0:
        return state                # played without the exchange; no entry
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, f))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _prereq(state: GameState, idx: int) -> bool:
    """"Wood in Your Supply >= Current Round" — a play-time HAVE-check on the
    wood supply against the round number (never spent)."""
    return state.players[idx].resources.wood >= state.round_number


def _score(state: GameState, idx: int) -> int:
    """The bonus points banked at play (0..completed harvests). The
    SCORING_TERMS application is ownership-gated, so an unplayed card scores
    nothing."""
    return state.players[idx].card_state.get(CARD_ID, 0)


def _action_label(variant: str) -> str | None:
    """Web-UI label for a food-exchange variant (mechanical, terse — the web
    layer prepends the card name): "f2" -> "Facades Carving [exchange 2 food
    → 2 bonus points]". "f0" is the no-exchange play. Otherwise None."""
    if not (variant.startswith("f") and variant[1:].isdigit()):
        return None
    n = int(variant[1:])
    if n == 0:
        return "no exchange"
    return f"exchange {n} food → {n} bonus point{'' if n == 1 else 's'}"


# Cost 2 clay + 1 reed; prereq wood >= current round; no printed VP (points
# are earned at play and banked).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2, reed=1)),
    prereq=_prereq,
    vps=0,
    on_play=_on_play,
)

# The wide on-play choice (user ruling 2026-07-06): one play variant per food
# amount, surcharge folded into the play payment by the enumerator.
register_play_minor_variant(CARD_ID, _variants)

register_scoring(CARD_ID, _score)

# Web-UI labels so the wide play variants read as their exchange, not "[f1]".
register_action_labeler(CARD_ID, _action_label)
