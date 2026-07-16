"""Forest Stone (minor improvement, B48; Bubulcus Expansion; Food Provider).

Card text: "Place 2 food on this card. Each time you use a wood accumulation
space, move 1 of these food to your supply. Each time you use a stone
accumulation space, add 2 food to this card."

Cost 2 Wood OR 1 Stone (a printed "/"-alternative cost). Prerequisite: 1
occupation. Worth 1 VP.

Three parts, all driven off the food this card holds in its CardStore slot (an
int, the food count sitting on the card):

ON PLAY — "Place 2 food on this card": `on_play` seeds the CardStore to 2.

WOOD USE — "Each time you use a wood accumulation space, move 1 of these food to
your supply": a `before_action_space` automatic effect hooking the game's wood
accumulation space (`forest` is the only one). "Each time you use [a space]" is
the BEFORE-phase hook (the Geologist / Interim Storage precedent), and the
timing relative to the space's own wood take is irrelevant here since the food
merely moves from the card to the player's supply. Gated on the card holding at
least 1 food — with an empty card there is nothing to move, so the auto simply
does not fire.

STONE USE — "Each time you use a stone accumulation space, add 2 food to this
card": a second `before_action_space` automatic effect hooking the two stone
accumulation spaces (`western_quarry`, `eastern_quarry` — the only ones). Always
adds 2 food (from the general supply) onto the card; nothing gates it.

Both halves are MANDATORY, choice-free flat effects (`register_auto`, never a
declinable trigger). They branch by space id, so they are registered as two
separate autos on `before_action_space` — the wood auto's eligibility naturally
carries the "food on the card" gate, the stone auto's the space membership.
`register_action_space_hook` indexes all three spaces so the atomic accumulation
placement is hosted (a PendingActionSpace frame pushed) for the owner, which is
what lets the before-phase autos fire. See CARD_IMPLEMENTATION_PLAN.md Category 3
(action-space hook); interim_storage.py is the closest template.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import STONE_ACCUMULATION_SPACES, WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "forest_stone"


def _on_play(state: GameState, idx: int) -> GameState:
    """Place 2 food on the card (seed the CardStore food count to 2)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, 2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible_wood(state: GameState, idx: int) -> bool:
    # A wood accumulation space, and there is at least 1 food on the card to move.
    return (
        state.pending_stack[-1].space_id in WOOD_ACCUMULATION_SPACES
        and state.players[idx].card_state.get(CARD_ID, 0) > 0
    )


def _apply_wood(state: GameState, idx: int) -> GameState:
    # Move 1 food from the card to the player's supply.
    p = state.players[idx]
    held = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=1),
        card_state=p.card_state.set(CARD_ID, held - 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible_stone(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in STONE_ACCUMULATION_SPACES


def _apply_stone(state: GameState, idx: int) -> GameState:
    # Add 2 food (from the general supply) onto the card.
    p = state.players[idx]
    held = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, held + 2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    alt_costs=(Cost(resources=Resources(stone=1)),),
    min_occupations=1,
    vps=1,
    on_play=_on_play,
)
# Host the wood + stone accumulation spaces so the before-phase autos can fire.
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES | STONE_ACCUMULATION_SPACES)
register_auto("before_action_space", CARD_ID, _eligible_wood, _apply_wood)
register_auto("before_action_space", CARD_ID, _eligible_stone, _apply_stone)
