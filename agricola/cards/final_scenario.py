"""Final Scenario (minor improvement, B23; Bubulcus Expansion; no cost,
prereq "Round 13 or Before", no printed VPs).

Card text: "Place the action space card for round 14 face up in front of you.
Only you can use it until it is placed on the game board."

Stage 6 is a ONE-round stage, so the round-14 card is always Farm
Redevelopment, publicly, from setup — no hidden information or chance is
involved (user, 2026-07-28). The banked design (CARD_DEFERRED_PLANS.md —
"Final Scenario B23"):

- **Use-while-unrevealed, keyed on the SPACE.** The space stays UNREVEALED;
  this card registers an `UNREVEALED_ACCESS_EXTENSIONS` grant — the owner may
  place on `farm_redevelopment` while it is unrevealed — at the predicate
  level, so `can_renovate` (the space's own carryability) still gates, the
  occupancy checks still apply, and the relocation movers (Straw Hat, Archway)
  inherit the destination for the owner automatically. The opponent's
  exclusion is free: unrevealed already blocks them.
- **Nothing is mutated.** `revealed` stays false until round 14's completely
  ordinary `RevealCard` — "until it is placed on the game board" is literal,
  and the grant simply goes moot at the flip. Every reveal reader (refill,
  the nature step, "newly revealed" cards, the future card-order GEOMETRY
  table for Legworker/Sweep-class readers) sees the truth — which is exactly
  what makes the ruled "place it in front of you strips the board geometry
  until round 14" fall out naturally (the space never enters the reveal-
  derived position record early).
- **Rulings:** the owner may use the space in the very round this card is
  played (user, 2026-07-28); the round-≤13 play prereq is printed (a later
  play would be moot anyway).
- Space-keyed on purpose (never a round-order read); assumes stage 6 stays a
  one-round stage — a future board shape re-derives this card.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.legality import register_unrevealed_access
from agricola.state import GameState

CARD_ID = "final_scenario"


def _prereq(state: GameState, idx: int) -> bool:
    return state.round_number <= 13            # "Round 13 or Before"


def _access(state: GameState, placer_idx: int, space_id: str) -> bool:
    """Only you can use it until it is placed on the game board."""
    return (space_id == "farm_redevelopment"
            and CARD_ID in state.players[placer_idx].minor_improvements)


register_minor(CARD_ID, prereq=_prereq)
register_unrevealed_access(_access)
