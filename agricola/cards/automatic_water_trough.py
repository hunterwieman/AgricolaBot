"""Automatic Water Trough (minor improvement, C9; Corbarius Expansion; players -).

Card text: "If you can accommodate the animal, you can immediately buy 1
sheep/wild boar/cattle for 0/1/2 food."
Cost: 1 Wood. No prerequisite, no printed VPs. PASSING (traveling minor —
`passing_left='X'`: after the on-play effect the card moves to the opponent's
hand; the hand-transfer happens in `_execute_play_minor` BEFORE `on_play` runs,
so the purchase resolves for the player who played it).

The slashes correlate: sheep costs 0 food, wild boar 1, cattle 2. "You can buy"
is optional; the buy is a play-time choice, surfaced WIDE via the minor
play-variant seam (`register_play_minor_variant` — user direction 2026-07-13,
matching the standing "on-play optional choices surface wide" ruling): one
`CommitPlayMinor(variant=...)` per eligible animal plus an always-present
zero-surcharge "decline". Each animal variant's food price rides the variant
SURCHARGE, folded into the play payment at enumeration (so affordability —
including food raised by liquidation — is the enumerator's standard `_payable`
gate, never re-checked here).

"If you can accommodate the animal" — the user-confirmed PERMISSIVE reading
(2026-07-13): there must EXIST a way to house the new animal, possibly by
displacing/cooking animals you already hold (rearranging and discarding are
free at any time in Agricola). The gate is therefore "the Pareto keep-frontier
over (current animals + the purchase) has a point keeping >= 1 of the bought
type"; a variant failing it is not offered. On a non-decline play, `on_play`
adds the animal and — when it does not simply fit — pushes a
`PendingAccommodate` with `min_keep = the purchase`, whose enumerator offers
exactly the frontier points that keep >= 1 of the bought type (the choice can
never discard the animal the purchase was conditioned on housing). A
consequence the user confirmed as legitimate: at sheep capacity with a
Fireplace, "cook 1 sheep (+2 food), buy the replacement for 0 food" is a valid
config on that filtered frontier — real-rules-legal (discard/cook anytime, then
buy into the freed slot).

The animal is added directly (NOT via `helpers.grant_animals`): the barrier's
unfiltered keep-which frame would let the player discard the purchase itself,
which this card's accommodation clause forbids — the filtered frame IS this
card's accommodation path. Card-only state is empty; nothing here is
Family-reachable.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.helpers import accommodates, cooking_rates, pareto_frontier
from agricola.pending import PendingAccommodate, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "automatic_water_trough"

# (variant, Animals field, food price) — the correlated slashes.
_PURCHASES = (("sheep", 0), ("boar", 1), ("cattle", 2))


def _can_house_one_more(state: GameState, idx: int, animal: str) -> bool:
    """The permissive accommodation gate: does the keep-frontier over
    (current animals + 1 `animal`) contain a point keeping >= 1 of that type?
    (Displacing/cooking other animals to make room is allowed.)"""
    p = state.players[idx]
    rates = cooking_rates(state, idx)[:3]
    frontier = pareto_frontier(p, Animals(**{animal: 1}), rates)
    return any(getattr(a, animal) >= 1 for a, _food in frontier)


def _variants(state: GameState, idx: int):
    """One zero-surcharge decline (always) + one variant per animal whose
    accommodation gate passes; the food price is the variant surcharge (its
    affordability is the enumerator's standard `_payable` gate)."""
    out = [("decline", Resources())]
    for animal, price in _PURCHASES:
        if _can_house_one_more(state, idx, animal):
            out.append((animal, Resources(food=price)))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """Apply the chosen purchase. The food price was already debited (folded
    into the play payment as the variant surcharge); here the animal is added
    and, when it doesn't simply fit, the min_keep-filtered accommodation frame
    surfaces the displace-which choice."""
    if variant == "decline":
        return state
    gained = Animals(**{variant: 1})
    p = state.players[idx]
    p = fast_replace(p, animals=p.animals + gained)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    if accommodates(p, p.animals.sheep, p.animals.boar, p.animals.cattle):
        return state
    return push(state, PendingAccommodate(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", min_keep=gained))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    passing_left=True,
    on_play=_on_play,
)
register_play_minor_variant(CARD_ID, _variants)
