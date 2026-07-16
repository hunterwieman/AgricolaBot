"""Truffle Slicer (minor improvement, D39; Consul Dirigens Expansion; Points
Provider; cost 1 wood; prereq "Play in Round 8 or Later").

Card text: "Each time you use a wood accumulation space, if you have at least 1
wild boar, you can pay 1 food for 1 bonus point."

An OPTIONAL action-space trigger hosted on Forest — the only wood accumulation
space in the 2-player game (Copse / Grove are 3–4-player board-extension spaces,
never on the 2-player board). The trigger rides the `before_action_space` event:
the Wood Cutter ruling settles that a bare "each time you use [space]" fires
BEFORE the space's own wood pickup, not after — and the phase is immaterial here
anyway, since paying 1 food for 1 bonus point is independent of the +3 wood the
space grants. Optionality lives in the FireTrigger: declining is simply the host's
`Stop` (no SkipTrigger flag).

Firing pays 1 food for 1 BANKED bonus point:
  - The bonus point is stored in the per-card CardStore (vps=0 on the spec) and
    emitted by `register_scoring` at end-game — the same one-shot-points pattern
    Loppers / Big Country use, because the point is earned at fire time but only
    scored later. The count in the store is "how many times Truffle Slicer was
    used."

Eligibility never offers a dead-end (CARD_AUTHORING_GUIDE §2): it gates on having
>=1 wild boar AND >=1 food to pay. "Once per use" is automatic — `_apply_fire_trigger`
stamps `triggers_resolved | {card_id}` before applying, and `_eligible` reads it, so
the card fires at most once per Forest use. (It may, however, be used on every
separate Forest use over the game, hence the cumulative bank.)

The 1-food cost is gated on on-hand `food >= 1` (direct pay, Loppers-style), NOT
routed through the PendingFoodPayment liquidation path: a Tier-2 simplification
(only 1 food, late-game). A player with 0 food but spare grain/veg/animals could
technically liquidate, but won't be offered the option.

Card-only state (the CardStore int + the per-frame `triggers_resolved`) defaults
canonically, so the Family game is byte-identical and the C++ gates are untouched.
See loppers.py (optional pay-for-a-banked-point shape), wood_cutter.py (the Forest
before_action_space host), and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "truffle_slicer"


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite: "Play in Round 8 or Later"."""
    return state.round_number >= 8


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the pay-1-food-for-1-point exchange only on a wood-accumulation-space
    use, when the player has a wild boar and the food to pay, and it has not
    already fired this use. Never a dead-end."""
    if CARD_ID in triggers_resolved:                        # once per forest use
        return False
    if state.pending_stack[-1].space_id not in WOOD_ACCUMULATION_SPACES:
        return False
    p = state.players[idx]
    return p.animals.boar >= 1 and p.resources.food >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food for 1 banked bonus point. A simple state edit — no pending pushed."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=1),
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    # 1 bonus point per time the card was used (banked at fire time).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq, vps=0)
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
register_scoring(CARD_ID, _score)
