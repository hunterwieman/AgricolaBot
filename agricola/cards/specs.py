"""Occupation card specifications: the on-play effect callbacks the engine
dispatches when an occupation is played from hand.

Occupations carry no structured cost / prerequisite in the card data (their JSON
entries are just name / category / text — see CARD_IMPLEMENTATION_PLAN.md II.4),
so each occupation's effect is hand-written as a card module under
`agricola/cards/` that calls `register_occupation`. The registry is populated at
import of the `agricola.cards` package (engine.py imports it at load), mirroring
the trigger / harvest-conversion registries.

The play COST is route-dependent (Lessons charges `occupation_cost`; later Scholar
charges 1 food), so it lives on the play pending, not here — a spec is purely the
card's effect. The parallel `MINORS` registry (structured cost / prereq / passing)
lands with the minor-play path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from agricola.resources import Cost


def _noop_on_play(state, idx):
    """Default on-play effect: do nothing (pure-scoring / passive cards)."""
    return state


@dataclass(frozen=True)
class OccupationSpec:
    card_id: str
    on_play: Callable  # (state: GameState, owner_idx: int) -> GameState


OCCUPATIONS: dict[str, OccupationSpec] = {}


def register_occupation(card_id: str, on_play: Callable) -> None:
    """Register an occupation's on-play effect (called at card-module import)."""
    OCCUPATIONS[card_id] = OccupationSpec(card_id=card_id, on_play=on_play)


# ---------------------------------------------------------------------------
# Play-time variant occupations (CARD_IMPLEMENTATION_PLAN.md Category 2 — Roof
# Ballaster)
# ---------------------------------------------------------------------------
# An occupation whose on-play carries an OPTIONAL, all-or-nothing choice — Roof
# Ballaster: "you MAY pay 1 food to get 1 stone per room" — is modeled as a
# play-VARIANT, exactly like Cooking Hearth's return-fireplace options in
# CommitBuildMajor: playing it surfaces one CommitPlayOccupation per legal variant
# (e.g. "with"/"without" the conversion), and the on-play reads the chosen variant.
# No trigger, no extra frame — the choice is part of the single play action.
#
# A card registers a `variants_fn(state, idx) -> list[str]` here; the
# PendingPlayOccupation enumerator expands its one CommitPlayOccupation into one
# per returned variant, and `_execute_play_occupation` threads the chosen variant
# into the on-play (calling it with 3 args only for these cards). A card with no
# registered variants_fn plays via a single variant-less CommitPlayOccupation —
# the unchanged common path. Empty registry in the Family game.
#
# variants_fn signature: (state, player_idx) -> list[str]  (must be non-empty —
# at minimum the "do nothing" variant, so the card is always playable).
PLAY_OCCUPATION_VARIANTS: dict[str, Callable] = {}


def register_play_occupation_variant(card_id: str, variants_fn: Callable) -> None:
    """Register an occupation's legal-play-variant enumerator (called at import)."""
    PLAY_OCCUPATION_VARIANTS[card_id] = variants_fn


@dataclass(frozen=True)
class MinorSpec:
    """A minor improvement's static definition (CARD_IMPLEMENTATION_PLAN.md II.4).

    cost            — the spendable Cost (Resources + Animals), paid at play.
    min/max_occupations — the dominant prerequisite (occupations-count): >=N via
                      min, <=N via max, exactly-N via min==max, "no occupations"
                      via max=0. Covers ~76 of the 154 prereq-bearing minors.
    prereq          — optional custom predicate (state, idx) -> bool for every
                      OTHER prerequisite shape (farm geometry, house material,
                      round timing, supply comparisons, improvements-count, …).
    passing_left    — a traveling minor: executed then passed to the opponent,
                      NEVER kept in the tableau.
    vps             — printed victory points (scored when kept; 0/None -> 0).
    on_play         — immediate effect (state, idx) -> state; default no-op.
    """
    card_id: str
    cost: Cost = Cost()
    min_occupations: int = 0
    max_occupations: Optional[int] = None
    prereq: Optional[Callable] = None
    passing_left: bool = False
    vps: int = 0
    on_play: Callable = _noop_on_play


MINORS: dict[str, MinorSpec] = {}


def register_minor(
    card_id: str,
    *,
    cost: Cost = Cost(),
    min_occupations: int = 0,
    max_occupations: Optional[int] = None,
    prereq: Optional[Callable] = None,
    passing_left: bool = False,
    vps: int = 0,
    on_play: Callable = _noop_on_play,
) -> None:
    """Register a minor improvement's spec (called at card-module import)."""
    MINORS[card_id] = MinorSpec(
        card_id=card_id, cost=cost, min_occupations=min_occupations,
        max_occupations=max_occupations, prereq=prereq, passing_left=passing_left,
        vps=vps, on_play=on_play,
    )


def prereq_met(spec: MinorSpec, state, idx: int) -> bool:
    """True iff player `idx` meets `spec`'s prerequisite — the occupation-count
    bounds AND the custom predicate (if any). A prerequisite is a HAVE-check,
    never spent (distinct from the cost)."""
    n_occ = len(state.players[idx].occupations)
    if n_occ < spec.min_occupations:
        return False
    if spec.max_occupations is not None and n_occ > spec.max_occupations:
        return False
    if spec.prereq is not None and not spec.prereq(state, idx):
        return False
    return True
