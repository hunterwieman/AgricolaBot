"""Seaweed Fertilizer (minor improvement, Corbarius C73; cost 2 Food; no prereq;
not traveling; category Crop Provider).

Card text: "Each time after you take an unconditional \"Sow\" action, you get
1 grain from the general supply. From round 11 on, you can get 1 vegetable
instead."

USER RULING (2026-07-20): "unconditional" means a Sow action with NO constraint
on the number of fields sown or the types of crops/goods sown — i.e. a
`PendingSow` whose `max_fields == 0` (uncapped) AND `crops_only == False` AND
`required_crop is None`. The action-space sows (Grain Utilization, Cultivation)
and unrestricted card-granted Sow actions qualify; restricted grants (a capped
`max_fields >= 1` sow, a crops-only sow, a forced-crop sow like Fern Seeds') do
not.

The Seasonal Worker shape — the MANDATORY-WITH-CHOICE firing kind (II.1) whose
choice, not firing, is round-gated: one `mandatory`-tagged trigger on the sow
host's `after_sow` window whose PendingCardChoice OPTIONS are round-dependent —
`("grain",)` before round 11 (a singleton the agent auto-resolves, i.e. always
+1 grain) and `("grain", "veg")` from round 11 on. The round-11 rule lives in
the options, not the firing kind. The sow host's after-phase WITHHOLDS Stop
while this trigger is owned, eligible, and unfired (the build-major/Cottar
atomic-host gate, mirrored in `_enumerate_pending_sow`'s after branch), so the
gain is never skippable. The grain/vegetable comes from the general supply
(player-edit idiom, no supply pool to debit).

Play cost 2 Food rides the standard food-payment machinery (nothing special
here). No on-play effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_card_choice_resolver
from agricola.pending import PendingCardChoice, PendingSow, pop, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "seaweed_fertilizer"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Fires only after an UNCONDITIONAL sow (user ruling 2026-07-20): the host
    PendingSow is uncapped (`max_fields == 0`), not crops-only, and not
    forced-crop. Once per sow action via `triggers_resolved`."""
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingSow)
            and top.player_idx == idx
            and top.max_fields == 0
            and not top.crops_only
            and top.required_crop is None)


def _apply(state: GameState, idx: int) -> GameState:
    # Options are round-dependent: grain-only pre-round-11, grain-or-veg from
    # round 11 on ("From round 11 on, you can get 1 vegetable instead").
    options = ("grain", "veg") if state.round_number >= 11 else ("grain",)
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id="card:seaweed_fertilizer",
        options=options))


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    p = state.players[idx]
    gain = Resources(grain=1) if chosen == "grain" else Resources(veg=1)
    p = fast_replace(p, resources=p.resources + gain)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return pop(state)   # resolver owns the PendingCardChoice frame


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)))
register("after_sow", CARD_ID, _eligible, _apply, mandatory=True)
register_card_choice_resolver(CARD_ID, _resolve)
