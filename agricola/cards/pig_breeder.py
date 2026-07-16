"""Pig Breeder (occupation, deck A #165; Artifex Expansion; players 4+).

Card text (verbatim): "When you play this card, you immediately get 1 wild boar.
Your wild boar breed at the end of round 12 (if there is room for the new wild
boar)."
Category: Livestock Provider. No printed VPs.

Two effects:

- **on-play.** +1 wild boar via `helpers.grant_animals`, so an over-capacity gain
  reconciles at the accommodation barrier.

- **the round-12 boar breed — a real breeding DECISION, offered WIDE.** "if there
  is room" is the standard Agricola breeding rule: the player may cook/release
  animals to make room for the newborn boar (RULES: "You CAN eat animals
  immediately before breeding to make room for newborns"). So this is the harvest
  breeding frontier (`helpers.breeding_frontier`) restricted to ONE type. It is
  computed here from the public capacity helpers rather than that shared function,
  because `breeding_food_gained` assumes every eligible type BRED (it would
  mis-credit kept sheep/cattle when only boar breed); the boar-only food is just
  the cook value of whatever is removed.

  Algorithm (mirrors `breeding_frontier`): breeding fires whenever >= 2 boar are
  KEPT, so the final boar count is `bF = (kept) + 1` anywhere in [3, b+1] and
  cooking a boar is itself a make-room move — when keeping all b+1 won't fit, a
  cooked parent is *free food* because breeding replaces it. Enumerate every
  post-config (sheep/cattle only reducible; boar in [3, b+1]) that fits
  (`can_accommodate` over `extract_slots`), keep the Pareto-optimal ones over the
  three ANIMAL counts. Keeping more of every type dominates, so a reduction only
  survives where it is NEEDED to house the boar — no gratuitous food-cooking. Since
  opening one boar slot means reducing exactly ONE type, the frontier is at most
  three configs (reduce sheep / cook a boar / reduce cattle), each carrying the cook
  value of everything it removed.

  One subtraction: the "cook a boar, breed one back" config that makes NO food (no
  cooking improvement) is dropped — it leaves the animals unchanged at zero food,
  i.e. it is identical to declining, which Proceed already offers (user ruling
  2026-07-15). It is offered only when the cooking generates food (a
  strictly-better-than-nothing option the player may still decline).

  The surviving configs are offered WIDE — one `FireTrigger` per config via
  `register_play_variant_trigger` on the `end_of_round` window (round 12, a
  non-harvest round, so no interaction with the real harvest breeding). The window
  host's **Proceed implicitly declines the breed** — offered alongside the configs,
  like any optional trigger (a free boar is strictly better than nothing, yet the
  player may still decline it). `triggers_resolved` makes it fire once. If no config
  survives (can't breed, or the only breed makes no food), the card isn't hosted.

Card-only (the frontier is computed from public helpers; no engine file touched) —
the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.helpers import (
    can_accommodate, cooking_rates, extract_slots, grant_animals,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "pig_breeder"
_BREED_ROUND = 12


def _owns(state: GameState, idx: int) -> bool:
    return CARD_ID in state.players[idx].occupations


def _frontier(state: GameState, idx: int) -> list[tuple[Animals, int]]:
    """Pareto-optimal (final animals, food) outcomes for breeding 1 boar, the
    player free to cook/release animals to make room. Empty if the player has < 2
    boar or the boar cannot be housed even after cooking down to a single breed.

    Breeding fires whenever at least 2 boar are KEPT: the player cooks the herd
    down to `r` boar (r in [2, b]) and the newborn brings the final to `bF = r+1`
    in [3, b+1] — so cooking a boar is itself a valid make-room move, and when
    keeping all b+1 is infeasible it is *free food* (breeding replaces the cooked
    parent). Sheep and cattle do NOT breed here (they breed at the real harvest,
    not round 12), so they can only be reduced: `sF <= s`, `cF <= c`.

    Food is the cook value of everything removed — sheep `(s-sF)`, cattle `(c-cF)`,
    and boar `(b+1-bF)` (the parents cooked before breeding) — at the owner's
    cooking rates (0 without a cooking improvement = a free release).

    Pareto over the three animal counts (keeping more of every type dominates), so
    a reduction survives only where it is NEEDED to house the boar — never a
    gratuitous food-cook. Opening one boar slot means reducing exactly ONE type, so
    the frontier is at most three configs (reduce sheep / cook boar / reduce cattle),
    each the minimum reduction on its branch.
    """
    p = state.players[idx]
    s, b, c = p.animals.sheep, p.animals.boar, p.animals.cattle
    if b < 2:
        return []
    sR, bR, cR = cooking_rates(state, idx)[:3]
    caps, flex = extract_slots(p)
    feasible = [
        (Animals(sheep=sF, boar=bF, cattle=cF),
         (s - sF) * sR + (b + 1 - bF) * bR + (c - cF) * cR)
        for sF in range(s + 1)
        for cF in range(c + 1)
        for bF in range(3, b + 2)          # final boar r+1 for kept r in [2, b]
        if can_accommodate(caps, flex, sF, bF, cF)
    ]

    def dominated(cfg: Animals) -> bool:
        return any(o.sheep >= cfg.sheep and o.boar >= cfg.boar
                   and o.cattle >= cfg.cattle and o != cfg
                   for o, _food in feasible)

    frontier = [(cfg, food) for cfg, food in feasible if not dominated(cfg)]
    # Drop the "cook a boar, breed one back" config when it makes NO food (no cooking
    # improvement): it then leaves the animals unchanged at zero food — identical to
    # declining, which the window's Proceed already offers (user ruling 2026-07-15).
    # Offered only when it generates food (a strictly-better-than-nothing option).
    frontier = [(cfg, food) for cfg, food in frontier
                if not (cfg == p.animals and food == 0)]
    frontier.sort(key=lambda cf: (cf[0].sheep, cf[0].boar, cf[0].cattle))
    return frontier


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """One variant per breeding config (its index into the deterministic
    frontier). Empty off round 12, unowned, or when no config can house the boar."""
    if state.round_number != _BREED_ROUND or not _owns(state, idx):
        return []
    return [str(i) for i in range(len(_frontier(state, idx)))]


def _eligible(state: GameState, idx: int, _triggers_resolved) -> bool:
    return bool(_legal_variants(state, idx))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Set the animals to the chosen config (the removed sheep/cattle are
    cooked/released) and bank the config's cook-value food."""
    cfg, food = _frontier(state, idx)[int(variant)]
    p = state.players[idx]
    p = fast_replace(p, animals=cfg, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _on_play(state: GameState, idx: int) -> GameState:
    return grant_animals(state, idx, Animals(boar=1))


register_occupation(CARD_ID, _on_play)
register("end_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
