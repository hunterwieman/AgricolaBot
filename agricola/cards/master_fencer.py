"""Master Fencer (occupation, Ephipparius E88; players 1+).

Card text: "Once you live in a stone house, at the start of each round, you can pay 2 or
3 wood to build up to 3 or 4 fences, respectively."

A stone-house-gated start-of-round OPTIONAL play-variant trigger (the Scholar /
Plow Driver "Once you live in a stone house, at the start of each round" family,
surfaced wide like Green Grocer): once in a stone house — a standing gate checked
each round, not a one-shot — the round's `start_of_round` window offers one
FireTrigger per affordable-and-buildable variant:

- variant "2w_3f": pay 2 wood, build up to 3 fences;
- variant "3w_4f": pay 3 wood, build up to 4 fences.

Each variant is offered only when the player has the wood on hand AND some legal
pasture is buildable within its N free edges (never a dead grant): the eligibility
probe is `_any_legal_pasture_commit` with the SAME restrictions / free budget /
provenance the fired frame will carry — the exact anticipation idiom Mini Pasture's
prereq uses. Note a first pasture on a virgin farm needs 4 edges (a 1×1's full
boundary), so "2w_3f" there has no legal pasture and is not offered.

Firing a variant debits the wood immediately (PREPAID — the printed cost is the
whole payment) and pushes a `PendingBuildFences` with `free_fence_budget=N` (the N
fences are free — no further wood accrues at the Proceed settle) and
`FenceRestrictions(max_edges=N)` (user-blessed 2026-07-15): the whole-action
new-edge cap that FORBIDS exceeding N — without it, an over-budget edge would just
accrue a wood bill through the Cards deferred tally, wrong for "build up to N
fences". `build_fences_action=False` — a card effect, not the literal Build Fences
action, so action-scoped frees (Hedge Keeper) do not fire on it. The fence PIECES
still come from the player's supply (the general rule; the probe's supply check
covers it).

"Up to": the multi-shot frame's standard lifecycle — the player may Proceed after
any ≥1 pasture, so fewer than N fences may be placed. Not firing at all is the
decline ("you can"). Once per round via the window host's `triggers_resolved` +
the `used_this_round` latch (Scholar's shape). On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import HouseMaterial
from agricola.pending import FenceRestrictions, PendingBuildFences, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "master_fencer"
FRAME_ID = "card:master_fencer"

# variant -> (wood cost, max fences buildable). Card-text order.
_VARIANTS = {
    "2w_3f": (2, 3),
    "3w_4f": (3, 4),
}


def _can_build_within(state: GameState, idx: int, n_edges: int) -> bool:
    """Is some legal pasture buildable within `n_edges` free edges? Anticipates the
    fired grant exactly (same restrictions / free budget / provenance / non-action
    flag), so a variant is never offered as a dead grant."""
    from agricola.legality import _any_legal_pasture_commit
    return _any_legal_pasture_commit(
        state, state.players[idx],
        restrictions=FenceRestrictions(max_edges=n_edges),
        free_budget=n_edges,
        space_id=FRAME_ID, initiated_by_id=FRAME_ID, build_fences_action=False)


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The variants affordable-and-buildable right now, in card-text order:
    wood on hand for the cost AND a legal pasture within the variant's free
    edges. Empty -> nothing to offer this round."""
    p = state.players[idx]
    return [v for v, (cost, n) in _VARIANTS.items()
            if p.resources.wood >= cost and _can_build_within(state, idx, n)]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.house_material is HouseMaterial.STONE   # standing gate, per round
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Latch once-per-round, debit the variant's wood (prepaid — the whole
    payment), and push the capped free-fence grant."""
    cost, n = _VARIANTS[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(wood=cost),
                     used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingBuildFences(
        player_idx=idx, initiated_by_id=FRAME_ID,
        build_fences_action=False, free_fence_budget=n,
        restrictions=FenceRestrictions(max_edges=n)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
