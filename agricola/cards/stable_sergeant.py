"""Stable Sergeant (occupation, deck B #167; Bubulcus Expansion; players 4+).

Card text (verbatim): "When you play this card, you can pay 2 food to get 1
sheep, 1 wild boar, and 1 cattle, but only if you can accommodate all three
animals on your farm."
Category: Livestock Provider. No printed VPs.

Category 2 (on-play one-shot) with an OPTIONAL, accommodation-gated purchase —
the Automatic Water Trough shape lifted to an occupation. Modeled as a
play-variant occupation (`register_play_occupation_variant`):

- **the variants.** A zero-surcharge "decline" (always) plus a "buy" variant
  carrying the 2-food SURCHARGE, offered ONLY when the farm can accommodate all
  three new animals. The surcharge's affordability (liquidation-aware) is the
  play-occupation enumerator's standard gate — never re-checked here.

- **"only if you can accommodate all three animals on your farm."** The
  user-confirmed PERMISSIVE accommodation reading (2026-07-13, Automatic Water
  Trough): there must EXIST a way to house the three new animals, possibly by
  displacing/cooking animals already held (rearranging/discarding are free at any
  time). The gate is therefore "the Pareto keep-frontier over (current animals +
  1 sheep + 1 boar + 1 cattle) has a point keeping >= 1 of EACH of the three
  bought types."

- **resolving the buy.** `on_play` adds the three animals directly (NOT via
  `helpers.grant_animals`: the barrier's UNFILTERED keep-which frame could
  discard one of the three the purchase was conditioned on housing). When they do
  not simply fit, it pushes a `PendingAccommodate` with
  `min_keep = 1 sheep + 1 boar + 1 cattle`, whose enumerator offers exactly the
  frontier points that keep all three — the filtered frame IS this card's
  accommodation path.

Played via Lessons; card-only — the Family game is byte-identical and the C++
gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.helpers import accommodates, cooking_rates, pareto_frontier
from agricola.pending import PendingAccommodate, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "stable_sergeant"
_GAINED = Animals(sheep=1, boar=1, cattle=1)


def _can_accommodate_all_three(state: GameState, idx: int) -> bool:
    """The permissive gate: does the keep-frontier over (current animals + 1 of
    each type) contain a point keeping >= 1 sheep AND >= 1 boar AND >= 1 cattle?
    (Displacing/cooking other animals to make room is allowed.)"""
    p = state.players[idx]
    rates = cooking_rates(state, idx)[:3]
    frontier = pareto_frontier(state, p, _GAINED, rates)
    return any(a.sheep >= 1 and a.boar >= 1 and a.cattle >= 1 for a, _food in frontier)


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """Decline (always) + the 2-food buy variant when all three animals can be
    accommodated. Affordability of the 2-food surcharge is the enumerator's gate."""
    out = [("decline", Resources())]
    if _can_accommodate_all_three(state, idx):
        out.append(("buy", Resources(food=2)))
    return out


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the three animals (the 2-food surcharge was already debited by the
    executor). When they don't simply fit, the min_keep-filtered accommodation
    frame surfaces the displace-which choice — never discarding the purchase."""
    if variant != "buy":
        return state
    p = state.players[idx]
    p = fast_replace(p, animals=p.animals + _GAINED)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    if accommodates(state, p, p.animals.sheep, p.animals.boar, p.animals.cattle):
        return state
    return push(state, PendingAccommodate(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", min_keep=_GAINED))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
