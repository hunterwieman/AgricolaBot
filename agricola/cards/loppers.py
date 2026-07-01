"""Loppers (minor improvement, A34; Artifex Expansion; Points Provider; cost 1 wood;
prereq 2 occupations).

Card text: "Each time you build 1 or more fences, you can also use this card to
exchange 1 wood and 1 fence in your supply for 2 food and 1 bonus point."

An OPTIONAL "each time you build 1 or more fences" exchange (the text says "you
CAN also use this card"). Two rulings govern the timing and the eligibility:

BEFORE timing. "Each time you [take / use / do X]" fires in the BEFORE window of
X's host, NOT after (CARD_AUTHORING_GUIDE — '"Each time you ... X" fires BEFORE
X'). Loppers is a FLAT exchange: it reads nothing about which pastures were built
or how big they are — unlike Shepherd's Crook / trimmer / asparagus_gift, whose
grants depend on the *outcome* of the fencing (a new >= 4-space pasture, etc.) and
therefore genuinely must resolve after. Loppers has no such outcome dependence, so
its correct home is `before_build_fences`: the exchange is offered when
PendingBuildFences is pushed (its before-phase), enumerated as a
`FireTrigger(card_id="loppers")` alongside the pasture commits, before any pasture
is committed. Declining is simply not firing it (choosing a commit / Proceed
instead). The card's "1 or more fences" gate is guaranteed by construction: taking
a Build Fences action at all means at least one fence will be built (Proceed is
illegal until `pastures_built >= 1`), so no explicit fence-count guard is needed.

The stranding guard (CARD_AUTHORING_GUIDE — "a before-trigger must not STRAND the
host's mandatory sub-action"). Because the exchange fires BEFORE the mandatory
fencing build, it must not consume resources the build then needs. It spends 1
wood + 1 fence from the stored supply pile, and a Build Fences host is only
satisfied by committing >= 1 legal pasture afterward — which needs BOTH enough
fence pieces still in supply AND enough wood to pay that pasture's segments. So
eligibility confirms that after paying (-1 wood, -1 fence in supply) at least one
legal pasture is STILL buildable, using the same predicate the fencing-placement
legality uses: `_any_legal_pasture_commit` (it reads `p.resources.wood` and
`buildable_fences(p) = fences_in_supply + on-card pools`, so decrementing both on
a player copy is exactly the post-payment affordability question). Without this
guard the card could be fired into a dead end — pay, then have no legal build to
complete the mandatory action.

Payment detail — the fence spent is one piece from the STORED SUPPLY PILE
specifically (`fences_in_supply`, the location-4 stockpile), NOT
`helpers.buildable_fences` (which also counts on-card pools like Ash Trees). Gate
AND debit `fences_in_supply`.

Scoring. The bonus point is BANKED in the per-card CardStore (vps=0 on the spec)
and emitted by `register_scoring` at end-game — the same one-shot-points pattern
Big Country uses, because the points are earned at play-time but only scored later.
The count in the store is "how many times Loppers was used."

"Once per use" is automatic — `_apply_fire_trigger` stamps
`triggers_resolved | {card_id}` before applying, and `_eligible` reads it, so the
card can fire at most once per build-fences action. (It may, however, be used in
every separate build-fences action over the game, hence the cumulative bank count.)

Card-only state (the CardStore int + the per-frame `triggers_resolved`) defaults
canonically, so the Family game is byte-identical and the C++ gates are untouched.
See potter_ceramics.py (optional before-event exchange trigger shape),
big_country.py (CardStore bank + register_scoring), and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _any_legal_pasture_commit
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "loppers"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the exchange only when it can be paid, hasn't fired this use, and does
    NOT strand the mandatory fencing build.

    Pay = 1 wood + 1 fence from the stored supply pile. The stranding guard
    confirms that after paying, at least one legal pasture is still buildable —
    because the exchange fires BEFORE the build, and the Build Fences host requires
    >= 1 legal pasture commit to complete (it must not be fired into a dead end).
    """
    if CARD_ID in triggers_resolved:                       # once per build-fences action
        return False
    p = state.players[idx]
    if p.resources.wood < 1 or p.fences_in_supply < 1:     # can't pay
        return False
    # Stranding guard: simulate the payment (-1 wood, -1 fence in supply) into a full
    # state copy and require that a legal pasture is still buildable afterward — the
    # exchange fires BEFORE the build, and the Build Fences host requires >= 1 legal
    # pasture commit to complete, so paying must not leave a dead end.
    #
    # The modified player is spliced back at the SAME index (not passed as a bare
    # copy): `_any_legal_pasture_commit` identifies the player by object identity
    # against `state.players` to derive its index (for the Cards free-fence budget /
    # positional gating), so a detached copy would be mis-attributed to player 1.
    # `_any_legal_pasture_commit` reads p.resources.wood and buildable_fences(p)
    # (= fences_in_supply + on-card pools), so both debits are reflected.
    p_after = fast_replace(
        p,
        resources=p.resources - Resources(wood=1),
        fences_in_supply=p.fences_in_supply - 1,
    )
    state_after = fast_replace(
        state,
        players=tuple(p_after if i == idx else state.players[i] for i in range(2)),
    )
    return _any_legal_pasture_commit(state_after, state_after.players[idx])


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
register("before_build_fences", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
