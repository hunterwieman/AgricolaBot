"""Loppers (minor improvement, A34; Artifex Expansion; Points Provider; cost 1 wood;
prereq 2 occupations).

Card text: "Each time you build 1 or more fences, you can also use this card to
exchange 1 wood and 1 fence in your supply for 2 food and 1 bonus point."

An OPTIONAL after-build-fences trigger (the text says "you CAN also use this
card"). After the player has built at least one fence in a build-fences action,
the build_fences host flips to its after-phase (reached via Proceed, which itself
requires `pastures_built >= 1` — so "you build 1 or more fences" is satisfied by
construction, no extra fence-count guard needed). In the after-phase the host
enumerates this card as a `FireTrigger(card_id="loppers")` alongside `Stop`;
declining is simply choosing `Stop` (the host pop) without firing it.

Firing exchanges 1 wood + 1 fence-from-supply for 2 food + 1 bonus point:
  - The fence spent is one piece from the STORED SUPPLY PILE specifically
    (`fences_in_supply`, the location-4 stockpile), NOT `helpers.buildable_fences`
    (which also counts on-card pools like Ash Trees). Gate AND debit
    `fences_in_supply`.
  - The bonus point is BANKED in the per-card CardStore (vps=0 on the spec) and
    emitted by `register_scoring` at end-game — the same one-shot-points pattern
    Big Country uses, because the points are earned at play-time but only scored
    later. The count in the store is "how many times Loppers was used."

Eligibility never offers a dead-end (CARD_AUTHORING_GUIDE §2): it gates on having
1 wood AND 1 fence in supply to pay. "Once per use" is automatic — `_apply_fire_trigger`
stamps `triggers_resolved | {card_id}` before applying, and `_eligible` reads it, so the
card can fire at most once per build-fences action. (The card may, however, be used in
every separate build-fences action over the game, hence the cumulative bank count.)

Card-only state (the CardStore int + the per-frame `triggers_resolved`) defaults
canonically, so the Family game is byte-identical and the C++ gates are untouched.
See ox_goad.py (optional after-event trigger shape), big_country.py (CardStore
bank + register_scoring), and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "loppers"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the exchange only when it can actually be paid and hasn't fired this
    use. Pay = 1 wood + 1 fence from the stored supply pile. Never a dead-end."""
    if CARD_ID in triggers_resolved:                       # once per build-fences action
        return False
    p = state.players[idx]
    return p.resources.wood >= 1 and p.fences_in_supply >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Exchange 1 wood + 1 fence-from-supply for 2 food + 1 banked bonus point.
    A simple state edit — no pending pushed."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=1) + Resources(food=2),
        fences_in_supply=p.fences_in_supply - 1,
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    # 1 bonus point per time the card was used (banked at fire time).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), min_occupations=2)
register("after_build_fences", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
