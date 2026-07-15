"""Beneficiary (occupation, Ephipparius Expansion; deck E #97; players 1+).

Card text: "If this is your 3rd occupation, you can immediately play another
occupation for an occupation cost of 1 food and/or play 1 minor improvement by
paying its cost."

User design (2026-07-14, deep not wide): "we will play the card, then offer the
occ/minor/proceed option, then offer cards of the relevant type, then offer the
occ/minor/proceed option (with either occ or minor no longer available) then end."

Mechanism — the multi-category `PendingGrantedSubAction` wrapper (the generic
optional-grant frame shared with Field Fences / Trellis / Dwelling Plan, extended
2026-07-14 to a category SET for exactly this card's "and/or"): `on_play` pushes it
with `subactions=("play_occupation", "play_minor")` and `occ_cost=Resources(food=1)`
(the printed "occupation cost of 1 food"; the minor "pays its cost" — the normal
play-minor path, so no cost parameter). The wrapper offers one
`ChooseSubAction(<category>)` per untaken, currently-doable category plus `Stop`,
so the and/or semantics — either order, at most one of each, decline any time —
fall out of the frame: choose one, its primitive host resolves fully (the played
card's own on_play runs normally inside it), control returns to the wrapper with
that category spent, the other (if still doable) is re-offered, then Stop ends the
grant. Per-category eligibility is the wrapper's enumerator (a playable + payable
hand occupation for `play_occupation`, mirroring the Lessons gate; a playable hand
minor for `play_minor`, mirroring Meeting Place), so a dead branch is simply not
offered.

"If this is your 3rd occupation": `_execute_play_occupation` moves the card
hand→tableau BEFORE running on_play, so Beneficiary is already in `p.occupations`
when this runs — `len(p.occupations) == 3` is exactly "Beneficiary is the 3rd".
Played as a non-3rd occupation the card is still playable; its effect is simply a
no-op. The wrapper is also not pushed when NEITHER branch is currently doable (a
frame offering only Stop would be dead weight); each branch's liveness is anyway
re-checked per decision by the wrapper's enumerator.

The deferred after-flip (ruling 60, 2026-07-14) means Beneficiary's own play host
flips to its after-phase only after the whole granted chain resolves — so any
`after_play_occupation` reactions to playing Beneficiary see the grant's plays too.

Card-only (empty registries in the Family game); the Family game is byte-identical
and the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "beneficiary"
FRAME_ID = "card:beneficiary"   # the granted plays' provenance
_OCC_COST = Resources(food=1)   # "for an occupation cost of 1 food"


def _on_play(state: GameState, idx: int) -> GameState:
    # local imports: card modules can't import legality/pending at module load
    # (load-order), matching the Field Fences / Trellis idiom.
    from agricola.legality import (
        _payable_occupation,
        playable_minors,
        playable_occupations,
    )
    from agricola.pending import PendingGrantedSubAction, push

    p = state.players[idx]
    # Beneficiary is already in the tableau (the executor's hand->tableau move
    # precedes on_play), so ==3 means it IS the 3rd occupation played.
    if len(p.occupations) != 3:
        return state
    # Push the wrapper only when at least one branch is doable right now (each
    # branch's liveness is re-checked per decision by the wrapper's enumerator).
    occ_live = (bool(playable_occupations(state, idx))
                and _payable_occupation(state, idx, p, _OCC_COST))
    minor_live = bool(playable_minors(state, idx))
    if not (occ_live or minor_live):
        return state
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id=FRAME_ID,
        subactions=("play_occupation", "play_minor"),
        occ_cost=_OCC_COST))


register_occupation(CARD_ID, _on_play)
