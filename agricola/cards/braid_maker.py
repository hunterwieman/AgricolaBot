"""Braid Maker (occupation, E109; Ephipparius Expansion; players 1+).

Card text (verbatim): "Each harvest, you can use this card to exchange 1 reed
for 2 food. You can build the Basketmaker's Workshop for 1 reed and 1 stone
even when taking a "Minor Impr." action."

Category: Food Provider. No on-play effect (played via Lessons; its on-play is
a no-op). Governing ruling — **ruling 74, 2026-07-21** (CARD_DEFERRED_PLANS.md;
quoted below). It SUPERSEDES the card's old defer entry ("Deferred 2026-07-12 —
Braid Maker E109, the converter cluster's one defer"): the missing seam that
entry named — a play-minor surface additionally offering the build of one
specific major — has since been built as
``legality.register_minor_action_major_build``.

> **Ruling 74 (user, 2026-07-21):** "The 1-reed-1-stone Basketmaker's cost
> applies to major builds too (user) — a formula — and at 'Minor Improvement'
> actions via the approved `register_minor_action_major_build` seam. The
> reed→2-food exchange is a **harvest-span conversion** (user): available in
> any harvest-time `PendingFoodPayment`, at feeding, and at a final
> `end_of_harvest` offering. **General pattern (user):** every resource→food
> conversion printed without a specific harvest phase — Joinery / Pottery /
> Basketmaker's included — follows the span pattern."

Two clauses, three mechanisms:

**Clause 1 — the reed→2-food exchange.** A pure building-resource → food
converter, once per harvest ("Each harvest, you can…" — the standard
``harvest_conversions_used`` budget, id ``"braid_maker"``, reset at each fresh
harvest FIELD entry). Per ruling 74 it is a harvest-SPAN conversion, so ONE
budget is spendable on any of three surfaces (the Paintbrush food-branch
shape):

1. **The FEED payment frame** — a ``HarvestConversionSpec`` (1 reed in, 2 food
   out, no riders, no variants). This is also what puts the card on the feed
   frame's offer list; the seam's executor debits the reed, adds the food, and
   marks the budget.
2. **The generalized in-harvest raise frame** (rulings 34/37, 2026-07-12: a
   pure converter joins the payment frontier) — ``frontier_fire=((0, 0, 0, 0,
   1, 0), 2)`` (the 6-tuple (grain,veg,wood,clay,reed,stone); 1 reed) on the
   same spec, so any harvest-time ``PendingFoodPayment`` frontier
   offers the fire. ``_execute_food_payment`` debits the reed, adds the food,
   and marks the SAME budget.
3. **The free span** (ruling 36, 2026-07-12, extended to this card by ruling
   74's span classification): ``register_free_span_trigger`` puts an optional
   ``FireTrigger`` on every in-span window/event — the player's field band
   through ``end_of_harvest`` (the ruling's "final end_of_harvest offering"),
   the FIELD during-window and the breed frame's pre-commit stretch included.
   The window machinery carries no cost layer or budget bookkeeping of its
   own, so the apply debits the reed, grants the food, and marks the shared
   budget itself (the basket_carrier idiom).

Any one surface's fire marks ``"braid_maker"`` in ``harvest_conversions_used``,
withholding the other surfaces for the rest of that harvest; the next harvest
offers it afresh.

**Clause 2a — the 1-reed-1-stone price.** A whole-cost ``register_formula`` on
``build_major``, applying whenever the major being built is the Basketmaker's
Workshop (index 9) — owner-gated as usual by the fold accessor. Per ruling 74
the price applies to MAJOR builds too (the Major Improvement space, House
Redevelopment, any granted build), not only the minor-action route — so the
formula carries no provenance scoping (contrast Oven Site's ``granted_by``
gate, whose discount is grant-confined). Modeling the price as a PIPELINE
FORMULA (the Oven Site precedent, user ruling 2026-07-20) is deliberate: other
owned reductions/conversions stack on top of the 1 reed + 1 stone through the
``effective_payments`` chokepoint, and the printed 2-reed-2-stone base is
Pareto-dominated by it, so only the discounted payment (and any
further-discounted variants) surfaces.

**Clause 2b — the build at a named "Minor Improvement" action.** The
``register_minor_action_major_build`` seam (ruling 74): registration makes the
named-action branch gates (Meeting Place / Basic Wish / the composite wrapper's
``minor_is_action`` branch) OR-in "a Braid Maker build is available", so the
branch is takeable with NO playable minor in hand; the swap itself is this
card's optional ``before_play_minor`` trigger, whose eligibility is EXACTLY the
seam's options predicate (``minor_action_major_build_options`` returning a
braid_maker entry) AND the top frame being the NAMED action
(``minor_improvement_action`` — never the Scholar-style card-effect plays or
the composite's child minor). Firing calls
``helpers.swap_play_minor_to_build_major``, which replaces the play-minor frame
with a menu-restricted bare ``PendingBuildMajor((9,))``; the build then runs
the normal commit-terminated host lifecycle, priced by the formula above.
Declining is implicit (play a hand minor normally, or never enter the branch).

Card-only state is empty in the Family game (occupations exist only under
``GameMode.CARDS``; every registry row here is ownership-gated), so the Family
trace stays byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.helpers import swap_play_minor_to_build_major
from agricola.legality import (
    minor_action_major_build_options,
    register_minor_action_major_build,
)
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources

if TYPE_CHECKING:
    from agricola.state import GameState

CARD_ID = "braid_maker"

BASKETMAKER_IDX = 9        # the Basketmaker's Workshop major-improvement index


def _replace_player(state: "GameState", idx: int, p) -> "GameState":
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _owns_occupation(state: "GameState", idx: int) -> bool:
    """is_owned_fn for the feed-seam entry: has this player PLAYED the card?

    Registrations are global and the HARVEST_FEED conversion enumerator gates
    only on is_owned_fn (the Furniture Carpenter caution), so the
    occupation-ownership check must live here."""
    return CARD_ID in state.players[idx].occupations


# --- Clause 1: the reed -> 2-food harvest-span exchange ----------------------

def _span_eligible(state: "GameState", idx: int, triggers_resolved) -> bool:
    """Free-span trigger eligibility: owns the card, the once-per-harvest
    budget is unused (SHARED with the feed-seam / raise-frame fires via
    ``harvest_conversions_used``), and the reed is on hand."""
    p = state.players[idx]
    return (CARD_ID in p.occupations
            and CARD_ID not in p.harvest_conversions_used
            and p.resources.reed >= 1)


def _span_exchange(state: "GameState", idx: int) -> "GameState":
    """Free-span trigger fire: debit the 1 reed, grant the 2 food, mark the
    shared budget (the window machinery carries no cost layer or budget
    bookkeeping of its own — the basket_carrier idiom)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(reed=-1, food=2),
        harvest_conversions_used=p.harvest_conversions_used | {CARD_ID},
    )
    return _replace_player(state, idx, p)


# --- Clause 2a: the 1-reed-1-stone Basketmaker's price -----------------------

def _formula_applies(state, idx, ctx) -> bool:
    """The price covers EVERY build of the Basketmaker's Workshop by the owner
    (ruling 74: major builds too) — keyed on which major the ctx builds, with
    no provenance scoping. Ownership is gated by the fold accessor."""
    return ctx.major_idx == BASKETMAKER_IDX


def _formula(state, idx, ctx) -> Resources:
    """"…for 1 reed and 1 stone" — a whole-cost alternative base; further
    reductions/conversions stack on it downstream (the Oven Site precedent,
    user ruling 2026-07-20)."""
    return Resources(reed=1, stone=1)


# --- Clause 2b: the swap at a named "Minor Improvement" action ---------------

def _swap_eligible(state: "GameState", idx: int, triggers_resolved) -> bool:
    """The seam's caller contract (helpers.swap_play_minor_to_build_major):
    eligibility MUST be ``minor_action_major_build_options`` — the same
    predicate the named-action branch gates consult, so a gated-in branch can
    never reach a zero-action frame — AND the top frame being the NAMED "Minor
    Improvement" action (``minor_improvement_action``; a card-effect play or
    the composite's child minor is not the named action)."""
    top = state.pending_stack[-1]
    if not (isinstance(top, PendingPlayMinor) and top.minor_improvement_action):
        return False
    return any(cid == CARD_ID
               for cid, _midx in minor_action_major_build_options(state, idx))


def _fire_apply(state: "GameState", idx: int) -> "GameState":
    """The card's ONE trigger apply, shared by every registered event (the
    firewood / Merchant pattern: `triggers.CARDS` is card-id-keyed, so a card
    with triggers on several events must dispatch on context inside one
    apply_fn — each `register` call overwrites CARDS[CARD_ID], benign only
    because every entry carries this same fn). The two surfaces' host frames
    are disjoint: a fire with the play-minor frame on top IS the
    before_play_minor swap (the seam asserts the named action); every other
    registered event is a free-span surface, so the fire is the reed
    exchange."""
    top = state.pending_stack[-1]
    if isinstance(top, PendingPlayMinor):
        # Clause 2b: the play-minor frame becomes a menu-restricted bare
        # PendingBuildMajor for the Basketmaker's Workshop (the seam owns the
        # pop+push and the before_build_major autos).
        return swap_play_minor_to_build_major(state, BASKETMAKER_IDX)
    return _span_exchange(state, idx)


# Pure recurring-effect occupation: played via Lessons, its on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Clause 1, surfaces 1+2 — the FEED offer list and (frontier_fire) the
# generalized raise frame / payment frontier, sharing one budget.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(reed=1),
    food_out=2,
    is_owned_fn=_owns_occupation,
    frontier_fire=((0, 0, 0, 0, 1, 0), 2),   # (grain,veg,wood,clay,reed,stone) -> food
))

# Clause 1, surface 3 — the free span (rulings 36 + 74): an optional trigger on
# every in-span window/event, field band through end_of_harvest. Eligibility is
# per-event (the enumerator reads the event-keyed TRIGGERS entries); the apply
# is the card's ONE shared dispatch fn (see _fire_apply).
register_free_span_trigger(CARD_ID, _span_eligible, _fire_apply)

# Clause 2a — the whole-cost 1-reed-1-stone formula on every Basketmaker's build.
register_formula("build_major", CARD_ID, _formula_applies, _formula)

# Clause 2b — the named-minor-action build: the branch gate registration + the
# swap trigger (eligibility == the seam's options predicate, per its contract;
# the apply is the same shared dispatch fn — the CARDS overwrite is benign).
register_minor_action_major_build(CARD_ID, BASKETMAKER_IDX)
register("before_play_minor", CARD_ID, _swap_eligible, _fire_apply)
