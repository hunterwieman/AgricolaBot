"""Bartering Hut (minor improvement, E9; Ephipparius Expansion; players -).

Card text: "Up to two times: Immediately spend any 2/3/4 building resources for
1 sheep/wild boar/cattle from the general supply."
Free (no cost), no prerequisite, no printed VPs. PASSING (traveling minor —
`passing_left='X'`: after the on-play effect the card moves to the opponent's
hand; the hand-transfer happens BEFORE `on_play` runs, so the purchases resolve
for the player who played it).

The slashes correlate: 2 resources -> sheep, 3 -> wild boar, 4 -> cattle; "any
N building resources" is any multiset of wood/clay/reed/stone summing to N.
"Up to two times" is bounded by this one play (an on-play effect on a traveling
card — the card can travel back and be played again later, resetting the
budget), tracked as a uses-counter in CardStore, reset to 2 at each `on_play`.

The purchase choice is deliberately NOT widened into the play action (user
direction 2026-07-13 — a wide play would multiply the play-minor menu by every
composition): `on_play` pushes a `PendingCardChoice` whose options are
"decline" plus one `(animal, wood, clay, reed, stone)` tuple per AFFORDABLE
composition (each count <= the player's holdings; <= 10/20/35 per tier, so <= 66
options in the wealthiest state, typically far fewer). No Pareto pruning
exists to apply — same-size compositions spend different goods vectors, so all
are mutually incomparable. Resolving a purchase debits the composition, grants
the animal, and — if a use remains and any purchase is still affordable —
pushes the same choice again (options recomputed post-debit). "decline" ends
the effect (declining the first purchase forfeits the second, per the user's
plan); with nothing affordable, no frame is pushed at all.

Unlike Automatic Water Trough this card has NO accommodation clause, so the
animal routes through `helpers.grant_animals` + the standard UNFILTERED
accommodation barrier (user-confirmed 2026-07-13): buy-then-cook is
expressible (standard acquisition rules — house it or cook/return it), and an
overflow from purchase #1 interleaves its keep-which frame before the second
choice frame (whose composition options only spend building resources, which
accommodation never changes — the pre-computed options stay valid).
"""
from __future__ import annotations

from itertools import combinations_with_replacement

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_card_choice_resolver
from agricola.helpers import grant_animals
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "bartering_hut"

# (Animals field, resources to spend) — the correlated slashes.
_TIERS = (("sheep", 2), ("boar", 3), ("cattle", 4))
_RES_FIELDS = ("wood", "clay", "reed", "stone")


def _options(state: GameState, idx: int) -> tuple:
    """"decline" + one (animal, wood, clay, reed, stone) tuple per affordable
    composition: a multiset of the four building resources summing to the
    tier's price, each count within the player's holdings."""
    res = state.players[idx].resources
    holdings = tuple(getattr(res, f) for f in _RES_FIELDS)
    opts: list = ["decline"]
    for animal, n in _TIERS:
        for combo in combinations_with_replacement(range(4), n):
            counts = [0, 0, 0, 0]
            for j in combo:
                counts[j] += 1
            if all(counts[k] <= holdings[k] for k in range(4)):
                opts.append((animal, *counts))
    return tuple(opts)


def _push_choice(state: GameState, idx: int) -> GameState:
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
        options=_options(state, idx)))


def _on_play(state: GameState, idx: int) -> GameState:
    """Reset the per-play budget to 2 and surface the first purchase choice
    (skipped entirely when no composition is affordable)."""
    if len(_options(state, idx)) == 1:      # only "decline" -> nothing to offer
        return state
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, 2))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return _push_choice(state, idx)


def _resolve(state: GameState, idx: int, option) -> GameState:
    """Apply the pick and pop the frame. A purchase debits its composition,
    grants the animal (grant_animals -> the unfiltered barrier), and re-pushes
    the choice while a use and an affordable purchase remain; "decline" ends
    the effect."""
    state = pop(state)
    if option == "decline":
        return state
    animal, wood, clay, reed, stone = option
    p = state.players[idx]
    uses_left = (p.card_state.get(CARD_ID, 0) or 0) - 1
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=wood, clay=clay, reed=reed, stone=stone),
        card_state=p.card_state.set(CARD_ID, uses_left),
    )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    state = grant_animals(state, idx, Animals(**{animal: 1}))
    if uses_left > 0 and len(_options(state, idx)) > 1:
        return _push_choice(state, idx)
    return state


register_minor(CARD_ID, passing_left=True, on_play=_on_play)
register_card_choice_resolver(CARD_ID, _resolve)
