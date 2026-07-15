"""Field Spade (minor improvement, Ephipparius E79; cost 1 wood).

Card text (verbatim): "Each time after you sow in at least 1 field, you get 1
stone."

A Sow action always plants in at least 1 field (the engine forbids a zero-field
sow: ``_enumerate_pending_sow`` requires "board + card sows >= 1 total"), so "after
you sow in at least 1 field" fires after every completed Sow. The reward is a flat,
mandatory +1 stone, and the text says "AFTER" explicitly → an automatic effect
(``register_auto``) on the ``after_sow`` window (the Garden Hoe after-hook shape,
minus its veg-count condition — Field Spade is crop-agnostic and needs no snapshot).
It fires at the CommitSow before->after phase flip, once per sow action.

No crop or "unconditional sow" restriction is printed, so it fires on any sow
(Grain Utilization, Cultivation, or a card-granted sow) once the fields are filled.
Played via an improvement space; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "field_spade"


def _grant_stone(state: GameState, idx: int) -> GameState:
    """after_sow: a sow just completed (which always plants >=1 field) -> +1 stone."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(stone=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("after_sow", CARD_ID, lambda state, idx: True, _grant_stone)
