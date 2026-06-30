"""Sheep Provider (occupation, C141; Corbarius Expansion; printed "players 3+").

Card text: "Each time any player (including you) uses the 'Sheep Market'
accumulation space, you get 1 grain."

Category 3 (action-space hook, automatic income) crossed with Category 9
(opponent-action hook). The +1 grain is a mandatory, choiceless effect → an
automatic effect (register_auto) on the `before_action_space` event, NOT a
FireTrigger. Per the Trigger-Timing ruling, a bare "each time ... uses [space]"
fires on the BEFORE phase (the host frame's push) — and since this is a pure
goods grant (not a threshold read off the goods still on the space, like Corf),
before- vs after-phase is immaterial here.

"Each time ANY player (including you)" → `any_player=True`: the owner gains grain
even on the OPPONENT's Sheep Market turn. `apply_auto_effects` iterates over both
owners only when `any_player` is set (triggers.py:138), running this card's
eligibility/apply with that owner as the index.

Despite `any_player=True`, NO `register_action_space_hook` is needed: Sheep Market
is NON-ATOMIC and self-hosts — `_initiate_sheep_market` (resolution.py) pushes
PendingSheepMarket and itself calls `apply_auto_effects(state,
"before_action_space", ap)` on EVERY use, including the opponent's, so the host
frame already exists. (The hook index only conditionally hosts ATOMIC spaces;
verified against Claw Knife, which uses the same Sheep Market self-host.) Grain has
no capacity limit, so the +1 grant is always safe.

The printed "players 3+" restriction (this is a Crop Provider card) is irrelevant
in the 2-player engine and has no mechanical effect. On-play is a no-op — the hook
IS the effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "sheep_provider"


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the OWNER (any player). Fire whenever the active use is Sheep Market.
    return state.pending_stack[-1].space_id == "sheep_market"


def _apply(state: GameState, idx: int) -> GameState:
    # Owner gets 1 grain from the general supply (no capacity limit on grain).
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
