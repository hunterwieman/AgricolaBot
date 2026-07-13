"""Shepherd's Whistle (minor improvement, E83; Ephipparius Expansion).

Card text (verbatim): "At the start of the breeding phase of each harvest, if
you have at least 1 unfenced stable without an animal, you get 1 sheep."
Cost: 1 Wood. No prerequisite, no printed VPs.

**The condition is capacity-theoretic — user ruling 16 (2026-07-05).** Animals
are not location-tracked (the engine stores totals; placement is derived), so
"an unfenced stable without an animal" has no stored fact behind it. The ruled
meaning: a stable is FREE iff the player's current animals can be accommodated
with one unfenced stable removed from capacity. Positioned at the
`start_of_breeding` window — before the breeding decision — so the granted
sheep can breed this harvest.

Three cases:
- **No unfenced stable** → ineligible, nothing happens.
- **A stable is free by the reduced-capacity test** → the sheep is granted
  AUTOMATICALLY ("you get" — a window auto; it provably fits: the animals fit
  without the stable, and the sheep takes it).
- **No stable is free, but the player may MAKE one free** → an optional
  play-variant trigger: each option is a Pareto-optimal keep-set of the
  current animals under the reduced capacity (released animals cook at the
  player's cooking rates, exactly the acquisition-overflow model), plus the
  granted sheep. **The frontier is over animal counts plus a
  received-vs-declined dimension** (ruling 16 as amended 2026-07-05):
  received dominates declined iff the player has a sheep-conversion
  opportunity — so a cook-a-sheep-and-replace-it option (animal-identical to
  declining, food in hand) SURVIVES and strategically supersedes declining
  when cooking pays, and is pruned only at zero rates (where it IS declining).
  Food is computed per option, never a frontier dimension (among received
  options animals-only dominance is exact — food differences equal the
  deferred cook-value of the animal difference). Declining via Proceed keeps
  the current animals with NO sheep: an unobtained sheep is never cooked.

The reduced capacity is computed by handing the standard helpers a DOCTORED
player with one standalone-stable cell blanked — standalone stables are
interchangeable for capacity, and `extract_slots` / `pareto_frontier` then
see exactly "the farm minus one unfenced stable".
"""
from __future__ import annotations

import re

from agricola.cards.display import register_action_labeler
from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.cards.triggers import register, register_auto, register_play_variant_trigger
from agricola.constants import CellType
from agricola.helpers import (
    accommodates,
    cooking_rates,
    pareto_frontier,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "shepherds_whistle"
WINDOW_ID = "start_of_breeding"


def _without_one_standalone_stable(state: GameState, idx: int):
    """A doctored PlayerState with one standalone (unfenced) STABLE cell
    blanked — the reduced-capacity farm the ruling's test runs on. None when
    the player has no unfenced stable."""
    p = state.players[idx]
    enclosed = {cell for past in p.farmyard.pastures for cell in past.cells}
    for r in range(3):
        for c in range(5):
            if (p.farmyard.grid[r][c].cell_type == CellType.STABLE
                    and (r, c) not in enclosed):
                grid = tuple(
                    tuple(
                        fast_replace(cell, cell_type=CellType.EMPTY)
                        if (rr, cc) == (r, c) else cell
                        for cc, cell in enumerate(row))
                    for rr, row in enumerate(p.farmyard.grid))
                return fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid))
    return None


def _stable_is_free(state: GameState, idx: int) -> bool:
    """The ruled test: current animals fit with one unfenced stable removed.
    Via the ownership-aware `accommodates` (the reduced player still carries
    the player's cards, so a sheep-only card slot — Dolly's Mother — composes:
    its parked sheep frees farm capacity here too)."""
    reduced = _without_one_standalone_stable(state, idx)
    if reduced is None:
        return False
    a = state.players[idx].animals
    return accommodates(reduced, a.sheep, a.boar, a.cattle)


# --- Case A: a stable is free -> automatic sheep --------------------------

def _auto_eligible(state: GameState, idx: int) -> bool:
    return (count_unfenced_stables(state.players[idx].farmyard) >= 1
            and _stable_is_free(state, idx))


def _auto_apply(state: GameState, idx: int) -> GameState:
    # Provably fits: the animals fit without the stable; the sheep takes it.
    p = state.players[idx]
    p = fast_replace(p, animals=p.animals + Animals(sheep=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Case B: make a stable free (Pareto options) or decline ---------------

def _options(state: GameState, idx: int) -> list:
    """The surviving (ending_animals, cook_food) options: reduced-capacity
    Pareto keep-sets + the granted sheep. Survival vs declining rides the
    received-vs-declined frontier dimension (ruling 16 as amended): declining
    prunes an option only when the option's animals never exceed the current
    holding AND no sheep-conversion opportunity orders received above
    declined — i.e. a sheep-cooking option survives exactly when cooking
    pays (the card replaces the cooked sheep, so its food is non-deferrable).
    Among the options themselves the keep-sets are already mutually
    Pareto-optimal (animals-only, exact)."""
    reduced = _without_one_standalone_stable(state, idx)
    if reduced is None:
        return []
    cur = state.players[idx].animals
    rates = cooking_rates(state, idx)[:3]
    sheep_convertible = rates[0] > 0
    out = []
    for kept, food in pareto_frontier(reduced, Animals(), rates):
        opt = kept + Animals(sheep=1)
        adds_animals = (opt.sheep > cur.sheep or opt.boar > cur.boar
                        or opt.cattle > cur.cattle)
        if adds_animals or sheep_convertible:
            out.append((opt, food))
    return out


def _trig_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    return (count_unfenced_stables(state.players[idx].farmyard) >= 1
            and not _stable_is_free(state, idx)
            and bool(_options(state, idx)))


def _variants(state: GameState, idx: int) -> list[str]:
    """One variant per surviving option, encoded as the FINAL animal vector
    "s<n>b<n>c<n>" (the granted sheep included)."""
    return [f"s{a.sheep}b{a.boar}c{a.cattle}"
            for a, _food in _options(state, idx)]


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Resolve the chosen option: keep the encoded animals (the granted sheep
    included), cook the released ones at the player's rates."""
    for a, food in _options(state, idx):
        if f"s{a.sheep}b{a.boar}c{a.cattle}" == variant:
            p = state.players[idx]
            p = fast_replace(
                p, animals=a,
                resources=p.resources + Resources(food=food))
            return fast_replace(
                state,
                players=tuple(p if i == idx else state.players[i]
                              for i in range(2)))
    raise AssertionError(f"shepherds_whistle variant {variant!r} not offered")


_VARIANT_RE = re.compile(r"^s(\d+)b(\d+)c(\d+)$")


def _action_label(variant: str) -> str | None:
    """Web-UI label for a make-room variant (mechanical, terse): the final
    animal vector the option keeps (the granted sheep included), zero counts
    omitted — "activate, keep sheep=2, boar=1"."""
    m = _VARIANT_RE.match(variant)
    if m is None:
        return None
    keeps = [f"{name}={n}"
             for name, n in zip(("sheep", "boar", "cattle"), map(int, m.groups()))
             if n]
    return "activate, keep " + ", ".join(keeps) if keeps else "activate"


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto(WINDOW_ID, CARD_ID, _auto_eligible, _auto_apply)
register(WINDOW_ID, CARD_ID, _trig_eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
register_action_labeler(CARD_ID, _action_label)
