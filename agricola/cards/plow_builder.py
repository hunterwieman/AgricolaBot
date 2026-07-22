"""Plow Builder (occupation, E91; Ephipparius Expansion; players 1+).

Card text (verbatim): "You can build the Joinery when taking a "Minor
Improvement" action. If you use the Joinery (or an upgrade thereof) during the
harvest, you can pay 1 food to plow 1 field."

Category: Farm Planner. No on-play effect (played via Lessons; its on-play is
a no-op). Governing rulings — **rulings 74 + 75, 2026-07-21**
(CARD_DEFERRED_PLANS.md; quoted below):

> **Ruling 74 (user, 2026-07-21):** "Plow Builder (E91) — clause 1 rides the
> same minor-action-major-build seam as Braid Maker; clause 2 (reacting to a
> Joinery use during the harvest with a pay-1-food plow) returns to the user
> as a concrete proposal during the span-machinery wave."

> **Ruling 75 item 7 (user, 2026-07-21):** "Plow Builder: no Joinery upgrades
> exist today. The ruled design: a FUSED trigger — perform the Joinery
> conversion AND the pay-1-food plow as one fired action — available
> throughout the harvest (every span window), so the player can take the plow
> early; it shares the Joinery's once-per-harvest budget with the plain
> surfaces."

> **Ruling 76 item 3 (user, 2026-07-21):** "Plow Builder (E91) revised: the
> plow effect does not need to follow the Joinery use immediately — it is
> available at any later point in the harvest. Offer the standalone
> pay-1-food-plow trigger throughout the harvest iff the Joinery has been
> used this harvest (the `"joinery"` budget-used boolean), once per harvest;
> the fused use-Joinery-and-plow trigger is kept as well."

**"(or an upgrade thereof)" — future-expansion scope.** No Joinery upgrade
exists in the implemented catalog (ruling 75); the fused trigger below keys on
the Joinery (major 7) alone. If an upgrade card ever lands, its use during the
harvest must also carry this card's pay-1-food plow — extend the eligibility /
fire here then.

**Clause 1 — the Joinery at a named "Minor Improvement" action.** The
``register_minor_action_major_build`` seam (ruling 74; the Braid Maker
clause-2b shape): registration makes the named-action branch gates (Meeting
Place / Basic Wish / the composite wrapper's ``minor_is_action`` branch) OR-in
"a Plow Builder build is available", so the branch is takeable with NO
playable minor in hand; the swap itself is this card's optional
``before_play_minor`` trigger, whose eligibility is EXACTLY the seam's options
predicate (``minor_action_major_build_options`` returning a plow_builder
entry) AND the top frame being the NAMED action (``minor_improvement_action``
— never the Scholar-style card-effect plays or the composite's child minor) —
the gate<->trigger agreement the seam's caller contract demands. Firing calls
``helpers.swap_play_minor_to_build_major``, which replaces the play-minor
frame with a menu-restricted bare ``PendingBuildMajor((7,))``; the build then
runs the normal commit-terminated host lifecycle at the Joinery's NORMAL
printed cost (2 wood + 2 stone through the ordinary build-major chokepoint —
the card grants no price, so NO formula is registered; contrast Braid Maker's
printed 1-reed-1-stone price). Declining is implicit (play a hand minor
normally, or never enter the branch).

**Clause 2 — the harvest plow, two offers (rulings 75 item 7 + 76 item 3).**
Both live on every free-span surface (``register_free_span_trigger`` — the
player's field band through ``end_of_harvest``, the FIELD during-window and
the breed frame's pre-commit stretch included):

- **The FUSED use-Joinery-and-plow fire** (ruling 75's design, kept per
  ruling 76), so the plow can be taken EARLY in the harvest (e.g. at
  ``start_of_feeding``, where the net food gain can pay the feeding). ONE
  fire performs both halves: the Joinery conversion — debit its input
  (1 wood), add its food_out (2 food), and mark the Joinery's SHARED
  once-per-harvest budget (the built-in conversion id ``"joinery"`` in
  ``harvest_conversions_used`` — the same id the feed executor, the
  payment-frontier fire, and the ``craft_span_joinery`` window fire mark and
  check; the exchange amounts are READ from the registered spec, never
  duplicated, so this surface cannot drift from the feed surface) — AND the
  paid plow (below). Eligibility: owns Plow Builder (tableau — no mode gate
  needed, Family players own no cards), the player owns the Joinery (the
  spec's own owner-array predicate — the "(or an upgrade thereof)" seam
  above), the Joinery budget unused, the plow latch unused, the conversion
  input on hand (wood >= 1), and a plowable cell exists (``legality.
  _can_plow`` — a fired trigger is never a dead end). NO separate food gate:
  the conversion's +2 food always covers the 1-food plow cost (food_out
  2 >= 1, so the fire nets food +1 and can never drive food negative).

- **The STANDALONE pay-1-food-plow fire** (ruling 76 item 3): after a PLAIN
  Joinery use — the FEED offering, the payment-frontier fire, or the
  ``craft_span_joinery`` window trigger, none of which grants a plow — the
  plow may still come at ANY later point in the harvest. Eligibility: owns
  Plow Builder, the ``"joinery"`` budget IS used this harvest (the ruling's
  budget-used boolean), the plow latch unused, food >= 1 (no conversion
  covers the cost here), and a plowable cell exists.

**The paid plow** (both fires): debit the printed 1 food and push
``PendingPlow(initiated_by_id="card:plow_builder")`` (frame triggers carry no
cost layer — the direct-debit Stone Importer idiom; the pushed primitive
composes mid-harvest, the Autumn Mother / Dung Collector precedent).

**The once-per-harvest plow latch** — "you can pay 1 food to plow 1 field"
is once per harvest, shared between the two fires (a fused fire consumes it;
a standalone fire requires it unused): the card's own id ``"plow_builder"``
in ``harvest_conversions_used``. That set is the codebase's native store for
exactly this scope — per ``state.py``, "per-card budgets that span events
live on PlayerState", with the walk's fresh-FIELD-entry reset giving the
per-harvest lifetime with no clearing step — and an extra non-conversion id
is inert to every other reader (the feed enumerator and the payment frontier
iterate the ``HARVEST_CONVERSIONS`` registry's ids and only test membership;
the Family encoder tests the three craft ids by name). A round-keyed
CardStore latch would hand-replicate the same scope with round arithmetic
for no benefit. The reset also gives ruling 76's cross-harvest shape for
free: a new harvest clears BOTH ids, so the standalone needs a fresh Joinery
use.

"You can …" on both fires: declining is simply not firing (the host frame's
Proceed/Stop is always available alongside). Once fired, the plow is part of
the fired action (optionality lives at the FireTrigger, the standard
granted-sub-action shape).

**One trigger entry serves both fires.** The two offers are mutually
exclusive in time — the fused fire requires the ``"joinery"`` budget UNUSED,
the standalone requires it USED — so a single registered span trigger
(eligibility = fused-eligible OR standalone-eligible; the apply dispatches
on the same budget boolean) is total and unambiguous: any offered
``FireTrigger(card_id="plow_builder")`` means exactly one thing in its
state. Registering the standalone as a second entry under the same card id
would collide in the card-id-keyed ``triggers.CARDS`` dispatch, and a
craft-span-style pseudo-id would need an ownership override and a web label
for no gain.

One card, triggers on several events — every surface shares ONE apply fn
dispatching on context (the firewood / Merchant / Braid Maker pattern:
``triggers.CARDS`` is card-id-keyed, so each ``register`` call overwrites
``CARDS[CARD_ID]``, benign only because every entry carries this same fn).

Card-only registries are ownership-gated and empty in the Family game
(occupations exist only under ``GameMode.CARDS``), so the Family trace stays
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.cost import RESOURCE_FIELDS
from agricola.helpers import swap_play_minor_to_build_major
from agricola.legality import (
    _can_plow,
    minor_action_major_build_options,
    register_minor_action_major_build,
)
from agricola.pending import PendingPlayMinor, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Resources

if TYPE_CHECKING:
    from agricola.state import GameState

CARD_ID = "plow_builder"

JOINERY_IDX = 7                    # the Joinery's major-improvement index
JOINERY_CONVERSION_ID = "joinery"  # the built-in conversion / shared budget id
_PLOW_FOOD_COST = 1                # the printed "pay 1 food to plow 1 field"

# The Joinery's exchange is READ from its registered spec (input_cost /
# food_out / owner predicate), never duplicated, so the fused surface cannot
# drift from the feed surface. The built-in row is a pure single-good -> food
# exchange; a rider or variant appearing there would mean the fused fire below
# no longer mirrors the feed fire — fail loud at import rather than diverge.
_JOINERY_SPEC = HARVEST_CONVERSIONS[JOINERY_CONVERSION_ID]
assert _JOINERY_SPEC.side_effect_fn is None and _JOINERY_SPEC.variants_fn is None
# The no-separate-food-gate arithmetic: the conversion's food_out always
# covers the plow's food cost, so the fused fire nets food >= 0 change.
assert _JOINERY_SPEC.food_out >= _PLOW_FOOD_COST


# --- Clause 2: the harvest plow — the fused and standalone span fires --------

# The once-per-harvest plow latch (shared by both fires): the card's own id in
# `harvest_conversions_used` — the native per-harvest budget store, reset at
# the walk's fresh FIELD entry, inert to every other reader (see docstring).
PLOW_LATCH_ID = CARD_ID


def _fused_eligible(state: "GameState", idx: int) -> bool:
    """The fused use-Joinery-and-plow fire: owns the Joinery (the spec's
    owner-array predicate), the Joinery's shared once-per-harvest budget
    unused, the plow latch unused, the conversion input (1 wood) on hand, and
    a plowable cell exists. No separate food gate — the conversion's +2 food
    covers the 1-food plow cost (see the import-time assertion). Tableau
    ownership is checked by the caller (_span_eligible)."""
    p = state.players[idx]
    if not _JOINERY_SPEC.is_owned_fn(state, idx):
        return False
    if JOINERY_CONVERSION_ID in p.harvest_conversions_used:
        return False
    if PLOW_LATCH_ID in p.harvest_conversions_used:
        return False
    if not all(getattr(p.resources, f) >= getattr(_JOINERY_SPEC.input_cost, f)
               for f in RESOURCE_FIELDS):
        return False
    return _can_plow(p)


def _standalone_eligible(state: "GameState", idx: int) -> bool:
    """The standalone pay-1-food-plow fire (ruling 76 item 3): the Joinery
    HAS been used this harvest (the budget-used boolean — any surface: feed,
    frontier, craft-span window, or the fused fire), the plow latch unused,
    the 1 food on hand (no conversion covers it here), and a plowable cell
    exists. Tableau ownership is checked by the caller (_span_eligible)."""
    p = state.players[idx]
    if JOINERY_CONVERSION_ID not in p.harvest_conversions_used:
        return False
    if PLOW_LATCH_ID in p.harvest_conversions_used:
        return False
    return p.resources.food >= _PLOW_FOOD_COST and _can_plow(p)


def _span_eligible(state: "GameState", idx: int, triggers_resolved) -> bool:
    """The one span-trigger eligibility: owns the card (tableau), and either
    fire is available. The two are mutually exclusive in time (the
    ``"joinery"`` budget boolean discriminates), so the offered FireTrigger
    is always unambiguous."""
    if CARD_ID not in state.players[idx].occupations:
        return False
    return _fused_eligible(state, idx) or _standalone_eligible(state, idx)


def _span_fire(state: "GameState", idx: int) -> "GameState":
    """The span fire, dispatching on the same boolean the eligibilities
    discriminate on. Joinery budget unused -> the FUSED fire (ruling 75 item
    7): the Joinery conversion exactly as the feed surface performs it —
    debit the spec's input, add its food_out, mark the SHARED budget id —
    plus the plow. Joinery budget used -> the STANDALONE fire (ruling 76 item
    3): just the paid plow. Both debit the plow's printed 1 food directly
    (frame triggers carry no cost layer), mark the shared plow latch, and
    push the plow primitive."""
    p = state.players[idx]
    if JOINERY_CONVERSION_ID in p.harvest_conversions_used:
        # Standalone (ruling 76 item 3): pay 1 food, plow — the Joinery was
        # used earlier this harvest by a plain surface.
        p = fast_replace(
            p,
            resources=p.resources - Resources(food=_PLOW_FOOD_COST),
            harvest_conversions_used=(
                p.harvest_conversions_used | {PLOW_LATCH_ID}),
        )
    else:
        # Fused (ruling 75 item 7): the Joinery conversion + the paid plow as
        # one fired action, consuming BOTH latches.
        p = fast_replace(
            p,
            resources=(p.resources - _JOINERY_SPEC.input_cost
                       + Resources(food=_JOINERY_SPEC.food_out)
                       - Resources(food=_PLOW_FOOD_COST)),
            harvest_conversions_used=(
                p.harvest_conversions_used
                | {JOINERY_CONVERSION_ID, PLOW_LATCH_ID}),
        )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


# --- Clause 1: the Joinery build at a named "Minor Improvement" action -------

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
    firewood / Merchant / Braid Maker pattern: `triggers.CARDS` is
    card-id-keyed, so a card with triggers on several events must dispatch on
    context inside one apply_fn — each `register` call overwrites
    CARDS[CARD_ID], benign only because every entry carries this same fn).
    The two surfaces' host frames are disjoint: a fire with the play-minor
    frame on top IS the before_play_minor swap (the seam asserts the named
    action); every other registered event is a free-span surface, so the fire
    is the fused Joinery-use + plow."""
    top = state.pending_stack[-1]
    if isinstance(top, PendingPlayMinor):
        # Clause 1: the play-minor frame becomes a menu-restricted bare
        # PendingBuildMajor for the Joinery (the seam owns the pop+push and
        # the before_build_major autos), priced normally by the chokepoint.
        return swap_play_minor_to_build_major(state, JOINERY_IDX)
    return _span_fire(state, idx)


# Pure recurring-effect occupation: played via Lessons, its on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Clause 2 — the ONE span trigger serving both fires (rulings 75 item 7 + 76
# item 3): the fused use-Joinery-and-plow while the Joinery budget is unused,
# the standalone pay-1-food-plow once it is used, on the shared plow latch.
# Eligibility is per-event (the enumerator reads the event-keyed TRIGGERS
# entries); the apply is the card's ONE shared dispatch fn (see _fire_apply).
register_free_span_trigger(CARD_ID, _span_eligible, _fire_apply)

# Clause 1 — the named-minor-action build: the branch gate registration + the
# swap trigger (eligibility == the seam's options predicate, per its contract;
# the apply is the same shared dispatch fn — the CARDS overwrite is benign).
# The Joinery builds at its NORMAL printed cost: no formula registered.
register_minor_action_major_build(CARD_ID, JOINERY_IDX)
register("before_play_minor", CARD_ID, _swap_eligible, _fire_apply)
