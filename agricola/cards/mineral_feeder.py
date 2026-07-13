"""Mineral Feeder (minor improvement, C67; Corbarius Expansion; Crop Provider).

Card text (verbatim): "At the start of each round that does not end with a
harvest, if you have at least 1 sheep in a pasture, you get 1 grain."
Cost: 1 Reed. VPs: 1. No prerequisite.

**The condition is arrangement-theoretic — user ruling 29 (2026-07-06).**
Animals are not location-tracked, so "at least 1 sheep in a pasture" (at least
one, not all — the user's clarification) means: *some legal arrangement of the
player's animals houses a sheep in a pasture*. The user also ruled the player
must be offered the option to COOK animals to make such an arrangement possible
when rearrangement alone cannot — the Shepherd's Whistle (ruling 16) analog.

**The satisfiability test (the user's construction, 2026-07-06):** for each
pasture j, dedicate j to sheep and MAX-FILL it (absorbing min(cap_j, sheep)
sheep — absorbing more only relieves the rest of the farm, so max-fill per
pasture is exact, not a heuristic); the condition holds iff the remaining
animals fit the remaining farm for some j. A Dolly's Mother sheep-slot strips
from the leftover sheep (the parked sheep is not the pastured one).

Three cases, at the start-of-round host (`PendingPreparation`), gated on the
round NOT ending with a harvest (rounds 4/7/9/11/13/14 end with harvests):

- **Satisfiable with current animals** → +1 grain AUTOMATICALLY ("you get" —
  mandatory and choice-free, ruling 21's classification; a qualifying player
  would always arrange to qualify).
- **Not satisfiable, but a keep-set of the current animals is** → an optional
  play-variant trigger: one option per Pareto-optimal qualifying keep-set
  (released animals cook at the player's rates), each granting the 1 grain.
  **The frontier is over (animals, grain received)** — the user's framing:
  declining (Proceed) sits at (current animals, 0 grain), every option at
  (kept, 1 grain), so options never dominate or tie the decline (a
  no-cooking qualifying keep-set is the automatic case), and among options
  animals-only dominance is exact (same rates — food differences equal the
  deferred cook-value of the animal difference). Cooking a SHEEP can itself
  enable the arrangement (the user's counterexample: sheep crowding a
  single-type holder), and the enumeration considers it like any other
  release — no special-casing.
- **No qualifying keep-set** (no sheep, or no pasture) → nothing.

The two tiers are mutually exclusive by construction (satisfiable-as-held vs
not), so no same-instant double-fire guard is needed. Once per round comes
from the preparation frame's ``triggers_resolved``.

SAME-INSTANT CAUTION (recorded in CARD_AUTHORING_GUIDE.md §2, user
2026-07-06): this card's exists-an-arrangement test may not be evaluated
independently alongside another arrangement-conditioned card reading the SAME
instant — simultaneous benefits need one shared arrangement. No such card
shares the start-of-round instant today.

Card-only registries throughout; the Family game is byte-identical.
"""
from __future__ import annotations

import re

from agricola.cards.capacity_mods import sheep_slot_count
from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register,
    register_auto,
    register_play_variant_trigger,
    register_start_of_round_hook,
)
from agricola.constants import HARVEST_ROUNDS
from agricola.helpers import can_accommodate, cooking_rates, extract_slots
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "mineral_feeder"


def _pastured_sheep_possible(player: PlayerState, a: Animals) -> bool:
    """Can `a` be arranged on this player's farm with >= 1 sheep in a pasture?

    The user's per-pasture construction: dedicate pasture j to sheep,
    max-fill it, and test the remainder against the rest of the farm; any j
    succeeding proves an arrangement. A Dolly's Mother sheep-slot strips from
    the LEFTOVER sheep only. Also the full-fit proof: a successful j yields a
    complete arrangement, so no separate can-they-fit-at-all check is needed.
    """
    if a.sheep < 1:
        return False
    caps, flex = extract_slots(player)
    strip = sheep_slot_count(player)
    for j in range(len(caps)):
        rest = caps[:j] + caps[j + 1:]
        s_left = max(0, a.sheep - caps[j])            # j absorbs min(cap, sheep)
        s_left = max(0, s_left - strip)               # card slot takes leftovers
        if can_accommodate(rest, flex, s_left, a.boar, a.cattle):
            return True
    return False


def _round_qualifies(state: GameState) -> bool:
    """The printed timing: a round that does NOT end with a harvest."""
    return state.round_number not in HARVEST_ROUNDS


# --- Case A: satisfiable with current animals -> automatic grain ------------

def _auto_eligible(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    return _round_qualifies(state) and _pastured_sheep_possible(p, p.animals)


def _auto_apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Case B: cook to qualify (Pareto options) or decline ---------------------

def _options(state: GameState, idx: int) -> list:
    """The surviving (kept_animals, cook_food) options: Pareto-optimal (over
    animal counts) keep-sets of the current animals that admit a pastured
    sheep. The frontier is over (animals, grain) — every option carries the
    1 grain, the decline (Proceed) carries 0 — so options and the decline
    never dominate each other, and among options animals-only Pareto is
    exact. Small, cold-path enumeration (a card-local constrained frontier,
    the Shepherd's Whistle idiom — `pareto_frontier`'s memoized fast paths
    are deliberately not touched)."""
    p = state.players[idx]
    cur = p.animals
    qualifying = [
        Animals(sheep=s, boar=b, cattle=c)
        for s in range(cur.sheep + 1)
        for b in range(cur.boar + 1)
        for c in range(cur.cattle + 1)
        if _pastured_sheep_possible(p, Animals(sheep=s, boar=b, cattle=c))
    ]

    def dominates(x: Animals, y: Animals) -> bool:
        return (x.sheep >= y.sheep and x.boar >= y.boar and x.cattle >= y.cattle
                and x != y)

    sR, bR, cR = cooking_rates(state, idx)[:3]
    return [
        (k,
         (cur.sheep - k.sheep) * sR
         + (cur.boar - k.boar) * bR
         + (cur.cattle - k.cattle) * cR)
        for k in qualifying
        if not any(dominates(o, k) for o in qualifying)
    ]


def _trig_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    p = state.players[idx]
    return (_round_qualifies(state)
            and not _pastured_sheep_possible(p, p.animals)
            and bool(_options(state, idx)))


def _variants(state: GameState, idx: int) -> list[str]:
    """One variant per surviving option, encoded as the KEPT animal vector
    "s<n>b<n>c<n>" (the Shepherd's Whistle encoding)."""
    return [f"s{k.sheep}b{k.boar}c{k.cattle}" for k, _food in _options(state, idx)]


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Resolve the chosen option: keep the encoded animals, cook the released
    ones at the player's rates, and take the 1 grain."""
    for k, food in _options(state, idx):
        if f"s{k.sheep}b{k.boar}c{k.cattle}" == variant:
            p = state.players[idx]
            p = fast_replace(
                p, animals=k,
                resources=p.resources + Resources(food=food, grain=1))
            return fast_replace(
                state,
                players=tuple(p if i == idx else state.players[i]
                              for i in range(2)))
    raise AssertionError(f"mineral_feeder variant {variant!r} not offered")


_VARIANT_RE = re.compile(r"^s(\d+)b(\d+)c(\d+)$")


def _action_label(variant: str) -> str | None:
    """Web-UI label for a cook-to-qualify variant (mechanical, terse): the
    kept animal vector, zero counts omitted — "activate, keep sheep=1,
    boar=2"."""
    m = _VARIANT_RE.match(variant)
    if m is None:
        return None
    keeps = [f"{name}={n}"
             for name, n in zip(("sheep", "boar", "cattle"), map(int, m.groups()))
             if n]
    return "activate, keep " + ", ".join(keeps) if keeps else "activate"


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), vps=1)
register_auto("start_of_round", CARD_ID, _auto_eligible, _auto_apply)
register("start_of_round", CARD_ID, _trig_eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_start_of_round_hook(CARD_ID)
register_action_labeler(CARD_ID, _action_label)
