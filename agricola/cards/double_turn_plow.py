"""Double-Turn Plow (minor improvement, A20; Artifex Expansion; Farm Planner).

Card text (verbatim): "When you play this card, you can immediately plow up to 2
fields."
Clarification (verbatim): "The cost is 1 extra food if played in Round 4 or 5."
Cost: "1 Grain,(+1 Food)". Prerequisite: "Play in Round 3 (5) or Before". No
printed VPs. Not passing.

USER RULINGS (2026-07-17):
- Ruling 66: the on-play "immediately" adds/changes nothing — this is a plain
  on-play grant with no separate earlier instant.
- The player may STOP after plowing 1 field (never forced to plow 2). The
  multi-shot `PendingPlow` already supports this: its before-phase enumerator
  offers `Proceed` once `num_plowed >= 1` (the Swing/Turnwrest/Wheel Plow shape),
  so "up to 2" means plow 1 (then Proceed) or 2 (budget spent). No engine change.

COST (a state-scaling cost via `cost_fn`, the Bottles template): the printed
"1 Grain,(+1 Food)" plus the clarification means rounds 1-3 cost 1 grain, and
rounds 4-5 cost 1 grain + 1 food. The +1 food is a normal cost component that
flows through the standard food-payment layer (PendingFoodPayment on a
shortfall) with no extra code — the enumerator/executor debit whatever `cost_fn`
returns.

PREREQUISITE (a custom predicate): "Play in Round 3 (5) or Before" bounds play
to `state.round_number <= 5` (the "(5)" is the higher-player-count round; the
governing bound here is 5, matching the clarification's rounds-4-and-5 cost
bump — a card that could only be played through round 5 is exactly one whose
cost can differ in rounds 4 and 5). In round >= 6 the card is unplayable.

THE OPTIONAL PLOW GRANT — declines WIDE (CARD_ENGINE_IMPLEMENTATION.md §6). This
card creates no capability of its own (it grants the ordinary plow primitive),
so the play-variant seam is preferred over the FireTrigger/PendingGrantedSubAction
wrapper: playing the card surfaces distinct CommitPlayMinor routes, one per
choice, exactly like Facades Carving / Plant Fertilizer. `register_play_minor_variant`
registers two zero-surcharge variants:
  - "plow" — offered ONLY when a legal plow target exists (`_can_plow`), because
    pushing `PendingPlow` with no legal cell would leave an empty legal-action set
    (its before-phase offers a CommitPlow per cell and no Proceed until the first
    plow); and
  - "skip" — ALWAYS offered (plow 0 fields; "you can" is optional).
The "skip" route guarantees the variant list is never empty, so the card is
playable whenever its base cost is. `_can_plow` is unchanged by playing the card
(playing a minor only debits goods + moves the card; the farmyard grid is
untouched), so a "plow" route offered at enumeration always has a target at
on_play time.

The 3-arg `on_play(state, idx, variant)`:
  - "plow" -> push a MULTI-SHOT `PendingPlow(max_plows=2)` (initiated_by_id
    "card:double_turn_plow"). Normal plow adjacency applies — no
    `must_preserve_base` (there is no mandatory base plow to strand; the whole
    plow is this card's optional grant), so the enumerator uses the ordinary
    `_legal_plow_cells`. The second plow is re-checked against the board the first
    produced, so adjacency is enforced per commit.
  - "skip" -> no-op (played without plowing).

Sequencing (mirrors Shifting Cultivation): PendingPlayMinor is a non-auto-pop
host under the deferred after-flip (ruling 2026-07-14). `_execute_play_minor`
marks the host's work applied, then runs this on_play, so the pushed PendingPlow
lands on top of the still-before-phase host; when the plow resolves and pops, the
host flips (firing after_play_minor autos only then) and its Stop pops cleanly.

Family-inertness: minors exist only under GameMode.CARDS, and PendingPlow's
`max_plows`/`num_plowed` fields are Family-constant defaults (canonical-skip), so
the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "double_turn_plow"


def _cost(state: GameState, idx: int) -> Cost:
    """"1 Grain,(+1 Food)" + the clarification "The cost is 1 extra food if
    played in Round 4 or 5": rounds 1-3 -> 1 grain; rounds 4-5 -> 1 grain +
    1 food. (The card is unplayable past round 5 — the prereq — so no later
    round is reachable.)"""
    food = 1 if state.round_number >= 4 else 0
    return Cost(resources=Resources(grain=1, food=food))


def _prereq(state: GameState, idx: int) -> bool:
    """"Play in Round 3 (5) or Before": playable only through round 5."""
    return state.round_number <= 5


def _variants(state: GameState, idx: int) -> list:
    """The wide on-play choice (zero surcharge on both routes): "plow" is offered
    only when a legal plow target exists (else pushing PendingPlow would
    dead-end); "skip" (plow 0 fields — "you can") is always offered, so the list
    is never empty and the card is always playable when its base cost is."""
    routes = [("skip", Resources())]
    if _can_plow(state.players[idx]):
        routes.insert(0, ("plow", Resources()))
    return routes


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """"plow" pushes a multi-shot PendingPlow (up to 2 fields, early-stoppable via
    Proceed once one field is plowed); "skip" plays the card without plowing."""
    if variant == "plow":
        return push(state, PendingPlow(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}", max_plows=2))
    assert variant == "skip", variant
    return state


register_minor(CARD_ID, cost_fn=_cost, prereq=_prereq, on_play=_on_play)

# The optional plow grant surfaces WIDE (CARD_ENGINE_IMPLEMENTATION.md §6): one
# play route per choice, "skip" always present so the list is never empty.
register_play_minor_variant(CARD_ID, _variants)


def _action_label(variant: str) -> str | None:
    """Web-UI label for the two play routes (terse/mechanical, matching the
    Plant Fertilizer labeler style)."""
    return {"plow": "plow up to 2 fields", "skip": "no plow"}.get(variant)


register_action_labeler(CARD_ID, _action_label)
