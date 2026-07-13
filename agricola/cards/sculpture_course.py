"""Sculpture Course (minor improvement, B53; Bubulcus Expansion; Food Provider).

Card text (verbatim): "At the end of each round that does not end with a
harvest, you can use this card to exchange your choice of 1 wood for 2 food,
or 1 stone for 4 food."
Cost: 1 Grain. No prerequisite. No printed VP. Not passing.

TIMING — the round-end ladder's ``end_of_round`` rung (user ruling 49,
2026-07-12: the returning-home phase is the round's LAST phase, and "the end
of the round" is a DISTINCT, LATER instant — the final window of
``agricola/cards/round_end.py``'s step table, resolved after the return-home
reset). The card is an ordinary optional trigger registered on that event; the
walk (``engine._advance_round_end``) pushes the per-player
``PendingHarvestWindow`` choice host (window_id ``"end_of_round"``) whenever
the owner's trigger is eligible, exactly as on the harvest ladder's simple
windows.

"THAT DOES NOT END WITH A HARVEST" — the ladder itself runs on EVERY round
(including harvest rounds, where the round end precedes the harvest — the
round_end.py module note: the harvest condition is each bearer's own
eligibility clause, not a ladder concern). This card's printed condition is
therefore its eligibility gate: ``state.round_number not in HARVEST_ROUNDS``
(the round-end walk runs before the next round's preparation increments
``round_number``, so during round N's ladder it still reads N).

THE CHOICE — "your choice of 1 wood for 2 food, or 1 stone for 4 food" is a
per-fire route choice, modeled as a play-variant optional trigger (the
Scholar / Home Brewer mechanism): the host enumerator expands the one trigger
into ``FireTrigger(card_id, variant)`` per currently-affordable variant —
``"wood"`` (pay 1 wood -> +2 food) and ``"stone"`` (pay 1 stone -> +4 food) —
and declining entirely is the frame's ``Proceed``. The window trigger
machinery carries no cost layer, so ``_apply`` debits the input itself;
affordability is checked in ``_eligible`` / ``_variants`` so no unpayable
variant is ever surfaced.

ONCE PER ROUND — "you can use this card" once per round end is structural:
firing the trigger marks it in the host frame's ``triggers_resolved``, so it
cannot fire again in the same window, and the frame exists once per round.

Card-only state is nil (no CardStore use); unowned, the trigger never
surfaces, so the Family game stays byte-identical and the C++ gates are
untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "sculpture_course"
WINDOW_ID = "end_of_round"

# variant -> (input debited, food granted)
_EXCHANGES: dict[str, tuple[Resources, Resources]] = {
    "wood":  (Resources(wood=1),  Resources(food=2)),
    "stone": (Resources(stone=1), Resources(food=4)),
}


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Usable iff this round does not end with a harvest (the printed
    condition — HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}) and at least one
    exchange is affordable. Ownership and the once-per-round guard are the
    host enumerator's (``_owns`` / the frame's ``triggers_resolved``)."""
    if state.round_number in HARVEST_ROUNDS:
        return False
    r = state.players[idx].resources
    return r.wood >= 1 or r.stone >= 1


def _variants(state: GameState, idx: int) -> list[str]:
    """The currently-affordable exchange routes, in printed order. Mirrors
    ``_eligible``'s round gate so the enumerator never surfaces a mis-timed
    variant."""
    if state.round_number in HARVEST_ROUNDS:
        return []
    r = state.players[idx].resources
    out = []
    if r.wood >= 1:
        out.append("wood")
    if r.stone >= 1:
        out.append("stone")
    return out


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """The chosen exchange: debit the input, grant the food (the window
    trigger machinery carries no cost layer, so the debit lives here)."""
    cost, gain = _EXCHANGES[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - cost + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


_ACTION_LABELS = {"wood": "1 wood → 2 food", "stone": "1 stone → 4 food"}


def _action_label(variant: str) -> str | None:
    """Web-UI label for the per-fire choice (mechanical, terse): the full
    exchange each variant performs."""
    return _ACTION_LABELS.get(variant)


# Cost 1 grain; no prerequisite; no printed VP; the on-play is a no-op (the
# effect is the recurring end-of-round exchange only).
register_minor(CARD_ID, cost=Cost(resources=Resources(grain=1)))

# The end-of-round exchange: an optional play-variant trigger on the round-end
# ladder's last rung (ruling 49, 2026-07-12); once per round via the host
# frame's triggers_resolved.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)

register_action_labeler(CARD_ID, _action_label)
