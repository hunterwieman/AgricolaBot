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
# (e.g. "pay"/"decline"), and the on-play reads the chosen variant. No trigger, no
# extra frame — the choice is part of the single play action.
#
# A card registers a `variants_fn(state, idx) -> list[(variant: str, surcharge:
# Resources)]` here. Each variant declares its own food/resource SURCHARGE on top of the
# base play cost (FOOD_PAYMENT_DESIGN.md §8 — the cost lives on the option that surfaces it,
# not a side table). The PendingPlayOccupation enumerator offers one CommitPlayOccupation per
# variant whose base+surcharge is payable (liquidation-aware), `_execute_play_occupation`
# folds the chosen variant's surcharge into the debited play cost (routing any food shortfall
# through PendingFoodPayment) and threads the variant into the on-play (3-arg call), and the
# on-play grants the variant's BENEFIT without re-debiting the surcharge. A card with no
# registered variants_fn plays via a single variant-less CommitPlayOccupation — the unchanged
# common path. Empty registry in the Family game. Surcharges are resource-only today (an
# animal surcharge would need the occupation executor to debit animals — deferred, no card
# needs it).
#
# variants_fn signature: (state, player_idx) -> list[tuple[str, Resources]]  (must be
# non-empty — at minimum a zero-surcharge "do nothing" variant, so the card is always
# playable).
PLAY_OCCUPATION_VARIANTS: dict[str, Callable] = {}

# The (variant × payment) stranding pair-gate (user ruling 75, 2026-07-21). The problem it
# solves: a variant's eligibility gate runs PRE-play, but the occupation cost debits before
# the variant's on_play pushes its granted frame — so a payment can consume the very resource
# the granted frame needs, reaching a frame with zero legal actions (Stable Master's 1-wood
# build after Working Gloves paid the occupation cost with the player's only wood). The ruled
# shape: "a wide display of (payment × build/no-build) pairs — the build variant is offered
# only with payments that leave the build doable; the decline variant with every payment."
# A card whose variant grants a resource-dependent effect registers `pair_ok_fn` beside its
# variants_fn; the play-occupation enumerator consults it per (variant, payment) pair on a
# SIMULATED post-debit state, and the PendingFoodPayment enumerator consults it per
# liquidation bundle when the stored resume commit is such a variant play (so a bundle that
# cooks the needed resource — Baker's grain at the 1:1 base rate — is withheld too).
PLAY_OCCUPATION_PAIR_GATES: dict[str, Callable] = {}


def register_play_occupation_variant(
    card_id: str, variants_fn: Callable, pair_ok_fn: Callable | None = None,
) -> None:
    """Register an occupation's legal-play-variant enumerator (called at import).

    `pair_ok_fn(state, idx, variant, payment) -> bool` — the optional stranding
    pair-gate (ruling 75 above). `state` is the SIMULATED state as it will stand
    after the occupation-cost debit (chosen base payment + surcharge subtracted;
    on the food-shortfall path, additionally after the candidate liquidation
    bundle has been applied) — i.e. the state the variant's on_play will run on.
    `payment` is the total vector being debited. Return False to withhold this
    (variant, payment) pair (or, at PendingFoodPayment, this liquidation bundle).
    A decline variant's gate should return True unconditionally — per the ruling,
    decline pairs are always offered."""
    PLAY_OCCUPATION_VARIANTS[card_id] = variants_fn
    if pair_ok_fn is not None:
        PLAY_OCCUPATION_PAIR_GATES[card_id] = pair_ok_fn
    else:
        PLAY_OCCUPATION_PAIR_GATES.pop(card_id, None)   # keep the two dicts in sync


# The minor analog (built 2026-07-06 for Facades Carving's on-play
# food-for-points choice; user ruling: on-play optional choices surface WIDE —
# ruling 17's rationale extended to minors). Each variant's SURCHARGE (a
# Resources vector, paid ON TOP of the card's cost-modifier-resolved play cost)
# is folded into the commit's `payment` at enumeration — cost MODIFIERS never
# see it (a discount card reduces the card's cost, not the effect's price) —
# and the variant is threaded to a 3-arg on_play, which grants the BENEFIT.
# The variant list must be non-empty (include a zero-surcharge route so the
# card is always playable when its base cost is).
#
# variants_fn signature: (state, player_idx) -> list[tuple[str, Resources]].
PLAY_MINOR_VARIANTS: dict[str, Callable] = {}


def register_play_minor_variant(card_id: str, variants_fn: Callable) -> None:
    """Register a minor's legal-play-variant enumerator (called at import)."""
    PLAY_MINOR_VARIANTS[card_id] = variants_fn


# The per-PAYMENT play gate for minors (user ruling 2026-07-27 — Grassland Harrow's
# corrected prerequisite "1 Building Resource in Your Supply AFTER PAYMENT"). A plain
# prerequisite is a pre-play HAVE-check (`prereq_met`); this registry handles the rarer
# shape whose check reads the state AFTER the play cost has been debited — so playability
# depends on WHICH payment is chosen, and the play is legal iff SOME payment's post-debit
# state passes, with only qualifying payments offered at the commit. The minor-side
# analog of the occupation (variant x payment) pair-gate above (ruling 75): the gate is
# consulted per payment on a SIMULATED post-debit state at both decision points —
# `playable_minors`' existence check / the play-minor commit enumerator
# (`_minor_payment_ok`), and, when the payment's food is short, per liquidation bundle
# (the food-short probe there + `_filter_minor_payment_gate_bundles` at the
# PendingFoodPayment frame) — the two sides sharing one simulation so a food-short
# payment is offered iff at least one bundle survives, and the frame then offers exactly
# the surviving bundles. Empty in the Family game and for every plain-prereq card.
PLAY_MINOR_PAYMENT_GATES: dict[str, Callable] = {}


def register_play_minor_payment_gate(card_id: str, gate_fn: Callable) -> None:
    """Register a minor's per-payment play gate (called at card-module import).

    `gate_fn(post_state, idx, payment) -> bool` — `post_state` is the SIMULATED state
    as it will stand after the play's full cost debit (the chosen resource `payment`
    plus the chosen alternative's animal portion subtracted; on the food-shortfall
    path, additionally after the candidate liquidation bundle has been applied) — i.e.
    the state the card's on_play will run on. Return False to withhold this payment
    (or, at PendingFoodPayment, this liquidation bundle)."""
    PLAY_MINOR_PAYMENT_GATES[card_id] = gate_fn


# ---------------------------------------------------------------------------
# Post-food-payment continuations (FOOD_PAYMENT_DESIGN.md §6)
# ---------------------------------------------------------------------------
# When a card's food cost is raised mid-action via a PendingFoodPayment frame, the
# engine must continue with whatever the food was FOR once the payment commits. The
# frame can't store a closure (it is frozen / hashable / JSON-serializable), so the
# continuation is recorded as data — the frame's `resume_kind` — and dispatched by
# `_resume` (resolution.py). `resume_kind == "rerun"` re-dispatches the stored commit (the
# unified path for play-minor / play-occupation / build-major). A CARD-SPECIFIC GRANT
# continuation (Ox Goad: pay 2 food → grant a plow) registers here under the card id, which
# the frame carries as its `resume_kind`; `_resume` falls through to this registry for any
# non-"rerun" key. apply_fn signature: (state, owner_idx) -> state — it debits the food (the
# frame is raise-only) and typically pushes the granted primitive (e.g. PendingPlow).
FOOD_PAYMENT_RESUMES: dict[str, Callable] = {}


def register_food_payment_resume(resume_kind: str, apply_fn: Callable) -> None:
    """Register a card's post-food-payment continuation (called at card-module import)."""
    FOOD_PAYMENT_RESUMES[resume_kind] = apply_fn


# Per-resume-kind PRESERVE checks on the food-payment frame (ruling 82, 2026-07-26):
# a card whose raised fee funds an action with its OWN goods requirement (the
# same-worker jump into Grain Utilization / the Major-Minor Improvement space)
# registers `fn(post_bundle_state, idx) -> bool`. The frame's enumerator offers only
# the liquidation bundles whose simulated post-state passes — so the player can
# always raise the fee (a plain food-on-hand gate would make rules-legal moves
# unplayable — never acceptable), but never via a bundle that cooks the very good
# the destination needs. Eligibility probes existence via
# `legality.raisable_food_preserving`. The play-occupation pair-gate is this idea's
# older sibling; this registry is the generic form for card-grant resume kinds.
FOOD_PAYMENT_PRESERVE_CHECKS: dict[str, Callable] = {}


def register_food_payment_preserve(resume_kind: str, fn: Callable) -> None:
    """Register a per-bundle preserve predicate for `resume_kind`'s food frame
    (called at card-module import)."""
    FOOD_PAYMENT_PRESERVE_CHECKS[resume_kind] = fn


# ---------------------------------------------------------------------------
# Occupation-cost food sources (Paper Maker — PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md)
# ---------------------------------------------------------------------------
# A card that, at the moment of playing an occupation, can PRODUCE food usable for the
# occupation's food cost (Paper Maker: "pay 1 wood to get 1 food per occupation"). Such a
# card is implemented as a `before_play_occupation` trigger (so it fires as a real, optional
# step — and is still offered when you already have enough food, a pure value trade). But the
# occupation-affordability GATE (Lessons / Scholar) must also know the food is reachable, or a
# play payable only by firing the source would never be offered (you'd never reach the frame
# to fire it). Each source registers here a `(state, idx) -> (food_produced, inputs:
# Resources) | None` — its food AND the resources it consumes — so the gate can simulate
# firing it (spend inputs, add food) and re-check `_payable`, which reserves the inputs from
# any competing liquidation (forward-compatible with a future wood->food liquidation).
OCCUPATION_FOOD_SOURCES: dict[str, Callable] = {}


def register_occupation_food_source(card_id: str, source_fn: Callable) -> None:
    """Register a card that can produce food toward an occupation play cost (Paper Maker,
    Forest School). `source_fn(state, idx, cost) -> (food_produced, inputs: Resources) | None`
    — `cost` is the route's ACTUAL play cost being gated (the frame's, never re-derived from
    the Lessons ramp; ruling 65, 2026-07-17), so a cost-sized source (Forest School's per-food
    swap) simulates against the real price. Sources whose output doesn't depend on the price
    (Paper Maker, Bookshelf, Tasting, Whale Oil) ignore the argument."""
    OCCUPATION_FOOD_SOURCES[card_id] = source_fn


# Cards that FORBID their owner any further occupation plays (Blighter: "You may
# not play any more occupations"). Consulted by `legality.playable_occupations` —
# the single chokepoint every occupation-play route (Lessons, Scholar, card
# grants) enumerates through — so an owned blocker empties the playable set at
# the source. Ownership-gated: a blocker still in HAND blocks nothing. Family
# fast path: the set is empty and the check is one truthiness test.
OCCUPATION_PLAY_BLOCKERS: set[str] = set()


def register_occupation_play_blocker(card_id: str) -> None:
    """Register a played card as blocking its owner's future occupation plays."""
    OCCUPATION_PLAY_BLOCKERS.add(card_id)


@dataclass(frozen=True)
class MinorSpec:
    """A minor improvement's static definition (CARD_IMPLEMENTATION_PLAN.md II.4).

    cost            — the spendable Cost (Resources + Animals), paid at play.
    alt_costs       — additional ALTERNATIVE costs for cards printed with a "/"
                      cost (e.g. Chophouse "2 Wood / 2 Clay"): the full set of
                      ways to pay is `(cost,) + alt_costs`, and the player pays
                      exactly ONE affordable member. Default () → the ordinary
                      single-cost card (only `cost` applies). Not combinable with
                      `cost_fn` (a scaling cost has no printed alternatives).
    cost_labels     — optional per-alternative labels, parallel to
                      `(cost,) + alt_costs` (same length). When set, the chosen
                      alternative's label is threaded into a 3-arg
                      `on_play(state, idx, label)`, so a card whose REWARD is
                      coupled to which cost it paid (Canvas Sack "paying
                      grain/reed … get 1 vegetable/4 wood") can grant the matching
                      benefit. Distinct from a play-variant surcharge: the cost
                      here is a REAL alternative cost that still flows through the
                      cost-modifier chokepoint (`effective_payments`), so a
                      discount card sees it — which a variant surcharge does not.
                      Default () → the reward does not depend on the alternative.
    cost_fn         — optional (state, idx) -> Cost; when present, overrides
                      `cost` at play time (for cards whose cost scales with game
                      state, e.g. Bottles: people_total × clay+food).
    min/max_occupations — the dominant prerequisite (occupations-count): >=N via
                      min, <=N via max, exactly-N via min==max, "no occupations"
                      via max=0. Covers ~76 of the 154 prereq-bearing minors.
    prereq          — optional custom predicate (state, idx) -> bool for every
                      OTHER prerequisite shape (farm geometry, house material,
                      round timing, supply comparisons, improvements-count, …).
    prereq_reserved — goods a PREREQUISITE reads that food-liquidation could
                      consume (user ruling 2026-07-27; CARD_AUTHORING_GUIDE.md
                      §0.5 / CARD_ENGINE_IMPLEMENTATION.md §5.3: a raise frame
                      simulates conversions that notionally happened BEFORE the
                      play, so the post-raise state must still satisfy
                      everything the gate checked — including this spec's
                      prerequisite). Folded into the play's reservation on BOTH
                      sides: the affordability gate excludes these goods as
                      conversion fuel (`_liquidatable_to`, via the play-minor
                      CostCtx), and the executor's food-shortfall frame adds
                      them to `PendingFoodPayment.reserved` so no offered
                      bundle cooks them (Beer Keg's 2 prereq grain under a
                      Wood-Expert food payment; Paintbrush's prereq boar).
                      Default empty — the prerequisite reads nothing
                      liquidatable, the near-universal case. NOTE: additive on
                      top of the printed cost's own goods; a card whose printed
                      COST spends the prereq-read good does NOT declare it
                      (Sheep Rug — prereq checked before payment, its cost
                      sheep is legal tender; ruled correct as printed
                      2026-07-27).
    passing_left    — a traveling minor: executed then passed to the opponent,
                      NEVER kept in the tableau.
    vps             — printed victory points (scored when kept; 0/None -> 0).
    on_play         — immediate effect (state, idx) -> state; default no-op.
    """
    card_id: str
    cost: Cost = Cost()
    alt_costs: tuple[Cost, ...] = ()
    cost_labels: tuple[str, ...] = ()
    cost_fn: Optional[Callable] = None
    min_occupations: int = 0
    max_occupations: Optional[int] = None
    prereq: Optional[Callable] = None
    prereq_reserved: Cost = Cost()
    passing_left: bool = False
    vps: int = 0
    on_play: Callable = _noop_on_play


MINORS: dict[str, MinorSpec] = {}


def register_minor(
    card_id: str,
    *,
    cost: Cost = Cost(),
    alt_costs: tuple[Cost, ...] = (),
    cost_labels: tuple[str, ...] = (),
    cost_fn: Optional[Callable] = None,
    min_occupations: int = 0,
    max_occupations: Optional[int] = None,
    prereq: Optional[Callable] = None,
    prereq_reserved: Cost = Cost(),
    passing_left: bool = False,
    vps: int = 0,
    on_play: Callable = _noop_on_play,
) -> None:
    """Register a minor improvement's spec (called at card-module import)."""
    assert not cost_labels or len(cost_labels) == 1 + len(alt_costs), (
        "cost_labels must be parallel to (cost,) + alt_costs"
    )
    MINORS[card_id] = MinorSpec(
        card_id=card_id, cost=cost, alt_costs=alt_costs, cost_labels=cost_labels,
        cost_fn=cost_fn, min_occupations=min_occupations,
        max_occupations=max_occupations, prereq=prereq,
        prereq_reserved=prereq_reserved, passing_left=passing_left,
        vps=vps, on_play=on_play,
    )


def play_minor_reserved(spec: MinorSpec, payment, chosen_animals) -> Cost:
    """The full reservation for playing `spec` with resource `payment` + the chosen
    alternative's `chosen_animals` — the goods a food-raising liquidation must NOT
    consume. Two components: the cost's own convertible goods (the payment's non-food
    resources + its animal portion — FOOD_PAYMENT_DESIGN.md §5, no double-spend) plus
    the spec's `prereq_reserved` (prerequisite-read goods; user ruling 2026-07-27 —
    conversions notionally precede the play, so they may not consume what the
    prerequisite gate checked).

    The ONE construction behind both sides of the contract: `_execute_play_minor`
    builds the pushed `PendingFoodPayment.reserved` from it, and the play-minor
    payment-gate probe (`legality._minor_payment_ok`) mirrors the frame through it —
    shared so the gate and the frame can never disagree about which bundles exist."""
    from agricola.replace import fast_replace
    return Cost(
        resources=fast_replace(payment, food=0) + spec.prereq_reserved.resources,
        animals=chosen_animals + spec.prereq_reserved.animals,
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
