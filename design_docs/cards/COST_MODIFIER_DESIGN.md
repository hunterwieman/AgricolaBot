# Cost-Modifier Cards — Design & Red-Team

> **The reference-of-record for the as-built cost machinery is `CARD_ENGINE_IMPLEMENTATION.md`
> §5.** This file is the design + red-team record (worked traces, attacks A1–A7, resolved forks).

**Status: design settled — the open forks O1–O5 are resolved by the user (see §6); the assumptions
A1–A7 are resolved or scoped out (see §5).** This document specifies the cost-resolution mechanism
for the card game's cost-modifier cards. It was written as a red-team: every load-bearing
assumption is paired with a concrete card or scenario that would falsify it. Where a fork needed a
rules ruling it was put to the user rather than guessed; those rulings are now folded in.

It is the design companion for the **cost-modifier** slice of Phase 3 (Cards). It assumes the
machinery in `CARD_SYSTEM_DESIGN.md` / `CARD_IMPLEMENTATION_PLAN.md` (the firing model, hosts,
registries) and the cost mechanics in `ENGINE_IMPLEMENTATION.md` §3 (the four cost buckets) and
§4.2–§4.3 (the Pareto-frontier-as-action-set pattern).

> **Catalog-coverage caveat (read once).** The catalog claims in this document — "the conversion
> set is 7 cards," "all chains are length 2," "zero benefit-from-spending breakers" — were
> established over the **672 cards in decks A–D** (the only decks in `agricola/cards/data/*.json`)
> and then **re-checked against the E deck** (Unofficial Compendium, 168 cards E001–E168, read from
> `Rulebooks/`): **E adds no new breaker** (no at-build-payment conversion, no frontier-breaking
> reward, no new payment route — see §4.8). So the model holds for **A–E**, though **only A–D are in
> the dataset / implemented** (E cards, incl. Pioneer E105, are not). Any deck **beyond E** must be
> re-checked when added; the **guard test (§4.7 / §8) is the backstop** — a future card that breaks
> an assumption (a length-3 chain, a payment-linked reward) turns it red rather than silently
> producing a wrong frontier.

---

## 1. The problem

Some cards change what an action costs. The canonical three:

- **Lumber Mill** (A75): "Every improvement costs you 1 wood less."
- **Carpenter** (B126): "Every new room only costs you 3 of the appropriate building resource and
  2 reed."
- **Frame Builder** (A123): "Each time you build a room/renovate, but only once per room/action,
  you can replace exactly 2 clay or 2 stone with 1 wood."

Implementing one today would mean editing cost logic at several scattered, *inconsistent* sites —
and at **both** the legality layer (is the action affordable / offered?) and the mechanics layer
(what is actually debited). The goal is a single mechanism so a cost card is implemented **once**.

### 1.1 The three kinds of cost card (rules-grounded)

"Cost-modifier card" hides three mechanically distinct things, with different stacking rules:

1. **Reduction** — subtracts a fixed amount of a resource from a class of builds (Lumber Mill,
   Bricklayer, Stonecutter, Chimney Sweep, Master Bricklayer). **Stack freely**: any number, any
   order. Always beneficial (strictly lowers a component, floored at 0), so effectively always
   applied. *(A "reduction" may also be a signed* increase *— see Dwelling Mound, §4.6.)*
2. **Formula card** — replaces the *whole* cost formula for a class of builds with a fixed
   alternative (Carpenter, Carpenter's Parlor, Clay Plasterer). **Optional, and you may use at
   most ONE** — you pick among {base formula} ∪ {your formula cards}. Two formula cards cannot
   both apply.
3. **Optional conversion** — while paying, you *may* substitute one resource for another. The full
   in-pool set is **7 cards** (§4 / §4.7): Frame Builder, Brushwood Collector, Millwright, Site
   Manager, Rammed Clay, Feed Fence, Forest School. **Stack freely** like reductions, but they are
   genuine *choices* (they change *which* goods you spend, not just how much), so they expand the
   action set.

A direct consequence: a reduction **stacks on top of** a chosen formula card, but two formula cards
do not stack. (So a hypothetical "3 wood off a wood room" reduction is strictly stronger than
Carpenter's Parlor, because it composes with Carpenter while Parlor cannot.) The mechanism must
reproduce exactly this: reductions and conversions compose with a chosen formula; formula choices
are mutually exclusive.

### 1.2 Scope

**In scope now:** the cost of **building a major improvement, playing a minor improvement,
building a room, and renovating.** (Build-stable and build-fence costs have the same shape and
join later — the design is built to extend, but they are not implemented in this slice.)

**Explicitly out of scope / deferred** (each is its own attack in §5, but not solved here):
costs payable from convertible goods (the at-any-time-cost hard set), pre-action resource grants
that change affordability (the speculative-legality problem — A7), benefit-from-spending cards (A1),
and per-card goods stacks. The design must **not break** in their presence; it just won't
*implement* them.

---

## 2. The mechanism under test

### 2.1 One chokepoint: `effective_payments`

A single function is the only place the full payment frontier is produced. Enumeration and the debit
read from it; legality reads its existence-view (`can_pay`, §2.6) rather than building the whole
frontier. A **`PaymentOption`** is the unit of payment: either a `Resources` vector, or a
non-resource route such as `ReturnImprovement(idx)` (Cooking-Hearth-via-Fireplace-return; §4.5 / A2).

```python
PaymentOption = Resources | ReturnImprovement   # ReturnImprovement(idx): a non-resource route

def effective_payments(state, idx, ctx) -> list[PaymentOption]:
    """All non-dominated ways player `idx` may pay for the build described by `ctx`.
    Family game (no cards): returns exactly [ctx.base]."""
    p = state.players[idx]

    # 1a. RESOURCE bases: the printed cost, plus each owned FORMULA card's alternative.
    #     The player uses <=1 formula — each seeds its OWN base and they never combine,
    #     so mutual exclusion is structural. (The <=1 choice is realized downstream: each
    #     formula yields its own frontier point and the agent picks one when it selects
    #     the commit.)
    resource_bases = [ctx.base] + formula_mods(ctx.action_kind, state, idx, ctx)

    # 1b. NON-RESOURCE routes (e.g. Cooking Hearth via Fireplace-return). These BYPASS
    #     steps 2-3 — you cannot convert/reduce "return a Fireplace" (§4.5 / A2).
    routes = base_routes(ctx.action_kind, state, idx, ctx)          # list[ReturnImprovement]

    # 2. CONVERSIONS expand each resource base into more candidates (each conversion
    #    applied once, sink-last; §2.4 / §4.7).
    cands = [c for b in resource_bases
               for c in expand_conversions(ctx.action_kind, state, idx, ctx, b)]

    # 3. REDUCTIONS — signed deltas, floor 0 — applied to every resource candidate.
    cands = [apply_reductions(ctx.action_kind, state, idx, ctx, c) for c in cands]

    # 4. Keep affordable, then Pareto-min over GOODS SPENT only. pareto_min_over_goods
    #    compares the Resources vector and NOTHING else — never any attached reward or the
    #    route tag. That exclusion is what keeps the alt-cost-minor case correct (A1) and
    #    leaves Pareto-incomparable routes (e.g. pay-grain vs pay-reed) both on the frontier.
    affordable = ([c for c in cands if _can_afford(p, c)]
                  + [r for r in routes if _route_affordable(p, r)])
    return pareto_min_over_goods(affordable)
```

The stacking rules are **emergent**, not hand-coded: a reduction yields a strictly-cheaper vector,
so the un-reduced one is Pareto-dominated and drops; formula cards never combine (each seeds its own
base); conversions trade goods and so are Pareto-*incomparable*, surviving as distinct frontier
points — exactly the payment choice we want to surface.

**Legality does not call this.** Building the whole frontier just to test non-emptiness is wasteful;
the legality path uses the short-circuiting `can_pay` (§2.6, A4).

### 2.2 The context object

The only thing each action contributes besides its base cost is a description of the build, so
modifiers can decide whether and how they apply.

```python
@dataclass(frozen=True)
class CostCtx:
    action_kind: str                            # "renovate"|"build_room"|"build_major"|"play_minor"
    base: Resources                             # base (printed) cost, computed by the action's adapter
    to_material: HouseMaterial | None = None    # renovate target (Clay Plasterer, Chimney Sweep)
    num_rooms:   int | None = None              # Master Bricklayer ("by rooms built")
    major_idx:   int | None = None
    card_id:     str | None = None
    space_id:    str | None = None              # entry-point scope (Hunting Trophy, House Artist)
    build_index: int | None = None              # Nth room/stable/fence (Carpenter's Apprentice)
```

One `CostCtx` with optional fields, not a per-action subclass hierarchy — modifier functions
dispatch on `action_kind` and read whatever fields they need, keeping the registry signatures
uniform.

### 2.3 Per-action adapters (the only irreducibly per-action code)

The base cost is genuinely different per action (`ROOM_COSTS[material]`, the
`MAJOR_IMPROVEMENT_COSTS` table, the renovate formula, a `MinorSpec.cost`), so it stays at the
action site. Everything downstream is shared. Each action is a one-liner:

```python
def _renovate_ctx(p) -> CostCtx:
    to   = _next_material(p.house_material)
    base = Resources(**{_material_field(to): _num_rooms(p), "reed": 1})
    return CostCtx("renovate", base, to_material=to, num_rooms=_num_rooms(p))
```

### 2.4 Ordering: conversions before reductions

Conversion-expansion (step 2) runs **before** reductions (step 3). Reason: a conversion like
"replace **exactly** 2 clay with 1 wood" requires that clay to still be in the cost; a reduction
applied first can strip it. Conversions-first can never block a later reduction (reductions are
always-valid subtractions), so it yields a *superset* of payment vectors — the more complete (and
more player-favorable) frontier. The worked trace in §4.3 shows a case where this ordering produces
an extra, legitimate frontier point that reduce-first would miss. *(The conversion stage itself runs
each conversion applied once (sink-last), not a general fixpoint; the full rule lives once in §4.7.)*

### 2.5 The registries and their accessors

A card adds one registry row; no engine edits. Registration (parallel to the trigger registries):

```python
register_formula(action_kind, card_id, applies(state, idx, ctx) -> bool,
                                        formula(state, idx, ctx) -> Resources)
register_reduction(action_kind, card_id, reduce(state, idx, ctx, cost: Resources) -> Resources)
register_conversion(action_kind, card_id, expand1(state, idx, ctx, cost: Resources) -> list[Resources])
```

The pipeline reads them through **fold accessors** (the plural forms `effective_payments` calls):

- **`formula_mods(action_kind, state, idx, ctx) -> list[Resources]`** — the `formula(...)` of each
  registered formula card for this `action_kind` whose `applies(...)` is true. One alternative base
  per eligible formula card (the player will use ≤1 — §2.1).
- **`apply_reductions(action_kind, state, idx, ctx, cost) -> Resources`** — fold every registered
  reduction for this `action_kind` that the player owns over `cost`. Each `reduce` returns a new
  cost; deltas are **signed** (a reduction may *add* — Dwelling Mound, §4.6) and every component is
  **floored at 0**. This signed/floor-0 contract lives here, where the fold is defined.
- **`expand_conversions(action_kind, state, idx, ctx, cost) -> list[Resources]`** — the
  apply-each-once (sink-last) conversion closure (§4.7). Always includes the unchanged `cost` (declining every conversion). A
  single `expand1` is a *generator* (returns several candidates — see Millwright, §4.4), and it
  always includes its unchanged input (declining that one conversion).

`base_routes(action_kind, state, idx, ctx) -> list[ReturnImprovement]` enumerates the non-resource
payment routes (today only Cooking-Hearth-via-Fireplace-return on majors; §4.5).

### 2.6 The three consumers

- **Legality (`is_legal`):** a **short-circuiting existence check**, never the full frontier:

  ```python
  def can_pay(state, idx, ctx) -> bool:
      """True iff SOME affordable payment exists. Short-circuits — does not build the frontier."""
      p = state.players[idx]
      if _can_afford(p, ctx.base):
          return True                                  # common case: base affordable, done
      # else: any formula base / non-resource route / conversion path affordable?
      #       (bounded search, stop at the first hit — no Pareto-min, no full closure)
      ...
      return False

  def _can_renovate(state, p):
      if p.house_material is HouseMaterial.STONE: return False   # material legality (not cost)
      return can_pay(state, _idx(p), _renovate_ctx(p))
  ```

  Non-cost gates (renovate's wood/clay-only material check; a major being unowned) stay separate.

- **Enumeration:** the frontier becomes the legal commits. **Wide** (renovate has no parameter;
  major's parameter is coupled to cost, not orthogonal — §3.4) expands the frontier directly:

  ```python
  for payment in effective_payments(state, idx, _renovate_ctx(p)):   # payment: PaymentOption
      actions.append(CommitRenovate(payment=payment))
  ```

  **Two-step** (build-room — cell is independent of payment) emits `CommitBuildRoom(row, col)` for
  geometry, then if >1 payment survives, a `PendingChooseCost` frame over the frontier (§3.7).
  (Wide-vs-two-step rule: factor only when the action parameter is *independent* of payment;
  otherwise the per-item frontier-size judgment applies — §3.4.)

- **Debit:** `_execute_renovate` applies `commit.payment` — `p.resources - payment` for a `Resources`
  payment, or the route's effect (return the named improvement) for a `ReturnImprovement`. The stored
  `cost` field on the pending disappears (§3.3).

---

## 3. Concrete interface changes (precision-forcing)

Every change is listed with its Family-byte-identity consequence.

### 3.1 Affordability refactor (the precondition)

Of the six affordability helpers, only three (`_can_afford_room`, `_can_build_room`,
`_can_build_stable`) already route through the cost-then-compare primitive `_can_afford(p, Resources)`.
**`_can_renovate` and `_can_afford_major` bypass it with inline formulas** (`res.clay >= num_rooms…`;
the per-index `idx==4 → stone>=3 and wood>=1`) — verified against the code (`legality.py` lines
371–385 and 388–429). They must first be converted to the materialize-a-cost-then-`can_pay` model.
This conversion is the precondition for everything else and is the bulk of the Family-reachable churn.

`_can_afford(p, Resources)` itself is unchanged — it stays the low-level component-wise primitive
that `effective_payments` / `can_pay` call internally.

### 3.2 Commit shape — explicit payment (DECIDED, O4)

The chosen payment rides on the commit as an explicit **`payment: PaymentOption`** — not a frontier
index. Self-describing; the debit is a trivial subtraction (or route effect); robust to any change
in frontier enumeration order; matches how the pointer-head policy scores candidate frontier entries
(§3.5); and **required** by the alt-cost minors (Canvas Sack, Grain Depot), whose reward depends on
*which* resource was paid — only the explicit payment records that at execute time. (`step` does not
verify legality, so a hand-built bad payment isn't caught, but that is already the engine's contract:
`action ∈ legal_actions` is the caller's responsibility.) A frontier index was rejected: it would
force `effective_payments` to recompute byte-identically at execute time and couple the commit to
enumeration order — fragile for replay and trained policies.

### 3.3 Removed / changed state

- `PendingRenovate.cost`, `PendingBuildRooms.cost` (the bucket-2 stored costs) — **removed**.
  They were a cache of a derived value; with cost cards the value depends on owned cards and (for
  multi-shot) on the running build count, so the cache acquires a sync invariant and goes stale
  (the Carpenter's-Apprentice "Nth room" case). Per the derived-not-cached Foundation, derive via
  `effective_payments` instead of storing.
- `CommitRenovate` and `CommitBuildMajor` (the **wide** commits) gain `payment: PaymentOption`
  (§3.2). `CommitBuildRoom` stays **geometry-only** (two-step — §3.4/§3.7): its payment rides on the
  two-step `CommitChooseCost`, or — when the frontier is a singleton (always in Family) — is the
  unique `effective_payments` point, recomputed and debited directly with no payment field.
- `_can_renovate` gains a `state` parameter (needs owned cards).

### 3.4 Wide vs. two-step, restated as the contract

| Action | Orthogonal param? | Shape | Why |
|---|---|---|---|
| Renovate | none | wide | payment is the only degree of freedom |
| Build major | which major (coupled to cost) | wide (today) | per-major frontiers small; revisit if large |
| Play minor | which card (coupled to cost) | wide (today) | per-card frontiers small; revisit if large |
| Build room | cell (independent of cost) | two-step | cell × payment is a true cross product |

### 3.5 Policy-head representation

A payment frontier is variable-length, so it is **pointer-head** territory — the same shape as
`animal_frontier` / `harvest_feed` (POLICY_HEAD.md): score each candidate off the shared embedding.
The fixed-vocab heads (`commit_*`) cannot represent it. Because a frontier entry is a `PaymentOption`,
the pointer head must encode the **whole `PaymentOption`** — including the non-resource
`ReturnImprovement` route, not just a `Resources` vector (e.g. a one-hot "route kind" feature plus the
resource vector). Flagged here so it isn't discovered late.

### 3.6 Family byte-identity & C++ scope (DECIDED: clean, O5)

The refactor is made **unconditionally** (not gated on `GameMode`). Family behavior is identical —
empty registries ⇒ `effective_payments` returns `[base]`, a singleton frontier, and `can_pay`
reduces to `_can_afford(p, base)` — but the *shapes* change, so the Family-only C++ twin must be
**re-ported** to keep the differential gates green. The re-port is mechanical because the Family
frontier is a singleton: the C++ logic (what's legal, what's debited) doesn't change, only the data
shapes. (The rejected alternative — keep a card-only legacy path with a vestigial `cost` field to
avoid the port — reintroduces the exact duplication this refactor removes. Per the user, a port is
never a reason to write worse Python.) The C++ change-list is §3.8.

### 3.7 `PendingChooseCost` (the two-step payment frame)

Used only by the two-step actions (build-room today; minors later) when >1 payment survives.

- **Fields:** `player_idx`, `payments: tuple[PaymentOption, ...]` (the frontier, frozen at push),
  and the in-progress build it belongs to (e.g. the room cell just committed) so the debit lands on
  the right primitive.
- **Enumerator:** one `CommitChooseCost(payment=<PaymentOption>)` per entry of `payments` — an
  **explicit `PaymentOption`, not an index** into `payments` (a frontier index was rejected, §3.2/O4).
- **Commit:** `CommitChooseCost` debits its `payment` and pops the frame, returning to the build host.

If the frontier is a singleton, the two-step path skips the frame and debits directly (no decision to
surface). *(Status: specified; may be deferred to the rooms milestone — renovate/major are wide and
don't need it.)*

### 3.8 C++ re-port change-list (parallel to §3.3)

Family-only C++ twin, all mechanical (singleton frontier):

- `CommitRenovate` / `CommitBuildMajor` serialization gains the `payment` field. **`CommitBuildRoom`
  is unchanged** (geometry-only); `CommitChooseCost` / `PendingChooseCost` are card-only — Family is
  always a singleton frontier, so the two-step frame never arises — and are **not** in the Family twin.
- `PendingRenovate` / `PendingBuildRooms` drop the `cost` field from their state + serialization.
- the C++ analogs of `_can_renovate` / `_can_afford_major` move to materialize-cost-then-afford.
- renovate/major **debit** reads the commit `payment`; the room **debit** recomputes the singleton
  `effective_payments` point (replacing the removed pending `cost`).
- the canonical-JSON contract (`agricola/canonical.py` ↔ C++) updates for the above shapes; the
  `tests/test_cpp_*.py` gates must stay green.

---

## 4. Worked card traces (the semantic red-team)

Hand-computed frontiers for adversarial combos. These check that the mechanism reproduces the
*rules*, which interface precision alone cannot. They double as the unit tests in §8.

### 4.1 Family renovate (sanity)

Wood→Clay, 3 rooms, no cards. `base = 3 clay + 1 reed`. No formulas/conversions/reductions. After
affordability + Pareto-min: `[3 clay + 1 reed]`. Singleton → one `CommitRenovate`, byte-identical
to today. ✓

### 4.2 Reductions + formula compose; Pareto-min collapses the dominated base

Wood→Clay, 3 rooms. Own **Clay Plasterer** (formula: renovate-to-clay = 1 clay + 1 reed) and
**Bricklayer** (reduction: renovation 1 clay less).

- Resource bases: `[3 clay+1 reed (printed), 1 clay+1 reed (Clay Plasterer)]`
- No conversions.
- Reductions (−1 clay) on each: `[2 clay+1 reed, 0 clay+1 reed]`
- Pareto-min: `0 clay+1 reed` dominates `2 clay+1 reed` → **frontier `[1 reed]`**.

Confirms the stacking rule: a reduction stacks on top of a chosen formula card (Bricklayer reduces
Clay Plasterer's already-reduced clay). ✓

### 4.3 Ordering matters — conversions-first yields a legitimate extra option

Wood→Clay, **2 rooms** (`base = 2 clay + 1 reed`). Own **Frame Builder** (conversion: replace
exactly 2 clay with 1 wood) and **Bricklayer** (reduction: 1 clay less).

- **Conversions-first (the design):** expand on base → `{2 clay+1 reed, 0 clay+1 wood+1 reed}`;
  then reduce −1 clay → `{1 clay+1 reed, 0 clay+1 wood+1 reed}`. Pareto-min: `(1 clay,1 reed)` vs
  `(1 wood,1 reed)` are incomparable → **frontier `[1 clay+1 reed, 1 wood+1 reed]`** (two options).
- **Reduce-first (rejected):** base −1 clay → `1 clay+1 reed`; Frame Builder needs 2 clay,
  only 1 present → can't apply → **frontier `[1 clay+1 reed]`** (one option).

Conversions-first surfaces the "pay 1 wood instead of 1 clay" route that reduce-first loses. ✓

### 4.4 A conversion as a multi-candidate generator (Millwright)

Clay→Stone, 3 rooms (`base = 3 stone + 1 reed`). Own **Millwright** ("replace up to 2 building
resources of **any type** with 1 grain each"). Here "any type" reduces to **stone only**, because
the base contains no wood or clay among its building resources — it's a base-cost artifact, not a
Millwright rule. So `expand1` emits: replace 0 (`3 stone+1 reed`), 1 stone (`2 stone+1 reed+1 grain`),
2 stone (`1 stone+1 reed+2 grain`). Pareto-min keeps all three (each trades stone for grain —
incomparable). Confirms a conversion is a *generator*, and Pareto-min bounds the surfaced set. ✓

**Per-action budget (a correctness subtlety — implemented).** Millwright's "up to 2" is **per
build-ACTION, not per single build.** In Agricola a "Build Rooms"/"Build Stables" action builds all
its rooms/stables at once; the engine resolves them one at a time for tractability, so the 2-grain
budget must be **shared across every room/stable built in the same action** (build 4 rooms ⇒ exchange
2 grain total, not 8). A naive per-`expand1` "up to 2" (the generator alone) gets this wrong — it
re-grants the full 2 to each room. Fix (the Shepherd's-Crook per-action-state pattern): the card keeps
a running count in its own `CardStore` slot — `expand1` caps offered swaps at `2 − used`; an optional
`record(state, idx, payment)` hook on `register_conversion` is called at each build's debit to add the
units that payment used (its grain delta — the printed base has no grain, so the count is exact even
through a Frame-Builder chain); and the card's `after_build_rooms`/`after_build_stables`/`after_renovate`
autos reset the count when the action completes. Renovate is a single build, so its budget never binds.
Family-invisible (CardStore defaults empty; the debit's `record` call is a no-op with no cards owned),
so no C++ change. **Residual:** counting units from the flat payment is exact only while each budgeted
conversion has a distinct payment signature; two *chained* budgeted conversions where the sink consumes
the feeder's output (Feed Fence → 1 clay → Millwright → 1 grain on a stable) would hide the feeder's
usage and need payment *provenance* — deferred with Feed Fence (the only such pairing), since Millwright
is currently the sole budgeted conversion.

### 4.5 Non-resource payment route (Cooking Hearth via Fireplace-return)

Build Cooking Hearth (major). Two base routes pre-exist: pay clay, **or** return a Fireplace you own.
The Fireplace-return is a **non-resource route**, emitted by `base_routes` as a
`ReturnImprovement(fireplace_idx)` that **bypasses steps 2–3** (you cannot reduce/convert "return a
Fireplace"). It enters the frontier directly, Pareto-incomparable to the clay-payment route, so both
survive; reductions/conversions still layer on the clay route. This is the `PaymentOption` sum type
(A2): the clay route is `Resources`, the return route is `ReturnImprovement`, and the commit carries
which. ✓ (generalizes to the exchange minors whose cost is "Return Fireplace/Cooking Hearth", e.g.
Oriental Fireplace).

### 4.6 Catalog provenance — three passes over decks A–D

Three sweeps over the **672-card A–D catalog** established the model's robustness (the E deck is
re-checked separately in §4.8; decks beyond E remain unchecked — see the top caveat). The triage buckets are labelled **X1–X6** (catalog-triage categories) and
the rulings **G1/G2** (G1 = reward depends on the payment → *would* break Pareto-min; G2 = reward for
the *act* of building → a safe trigger). G1 is the failure mode we hunt for: **no in-scope card is
classified G1** — the passes below show every payment-linked reward resolves to a G2 trigger:

- **Pass 1 — broad sweep, 58 cards** across six buckets: X1 benefit-from-spending (10), X2 min-spend
  (1), X3 convertible-good cost (0), X4 pre-action grant (12), X5 per-card goods stack (18),
  X6 other cost interaction (17).
- **Pass 2 — dedicated conversion re-read:** the in-pool conversion set is exactly **7** (§1.1 / §4.7).
- **Pass 3 — dedicated benefit-from-spending re-read, 25 candidates** (a superset of Pass 1's X1,
  read more carefully): triaged against the four in-scope actions, **zero are confirmed breakers**.

What each finding does to the model:

- **A1 / benefit-from-spending (Pass 3's 25).** ~16 out of scope (pay-for-points at harvest /
  at-any-time), 4 mislabeled reductions, 2 alt-cost minors that are *handled* (Canvas Sack `1 Grain/1
  Reed`; **Grain Depot** `2 Wood/2 Clay/2 Stone`, reward scales by which you pay — the routes are
  Pareto-incomparable so both survive, reward rides the explicit payment), 1 state-dependent base
  cost (**Bottles**, `(1 clay+1 food) × people` — fine, base cost can depend on state like renovate's
  `num_rooms`), 1 min-spend (Stone Company, deferred), and **Brick Hammer** (D80, "+1 stone per
  improvement costing ≥2 clay"). The boundary that resolves A1: **the cost frontier covers only the
  payment for the action itself; "pay extra → reward" effects (Bucksaw, Mining Hammer) are `after_*`
  triggers, never folded in.** Brick Hammer is **G2** — it reads the **printed** cost (`ctx.base`/the
  table), firing regardless of payment route (clay discount, conversions, even Fireplace-return for a
  Cooking Hearth), so it never touches the frontier's pruning.
- **X3 is EMPTY** — no in-scope action's cost must be paid by an at-any-time conversion. One feared
  interaction removed.
- **X4 (pre-action grants, 12) and X5 (per-card goods stacks, 18) are orthogonal** — they raise the
  *resources* side of `resources ≥ cost` (Master Workman, Knapper, Firewood), handled by the firing
  system + deferred `CardStore` + deferred speculative-legality. **None change `effective_payments`**
  (A7).
- **"Free build" cards are the empty-cost degenerate case** — Renovation Company / Established Person
  (free renovate), Hawktower / Mason (free room). `effective_payments` returns `[Resources()]`. What
  varies is only *timing* (on-play / start-of-round / at-any-time); the at-any-time anchor is a
  separate deferred concern, not a cost-mechanism one.
- **Cost ADDITIONS** — Dwelling Mound (C37, "pay 1 food per new field tile") *adds* cost. Handled by
  `apply_reductions` doing signed arithmetic (§2.5), not subtract-only. (Plow, out of scope now.)
- **X2 — one min-spend constraint** (Stone Company A23, "must spend at least 1 stone"). Would need a
  "payments must spend ≥ N of R" filter. One card → **DEFER**.

Net: the Pareto-min model holds across decks A–D. A1 is averted by the trigger/cost boundary; X4/X5
(30 cards) are the scoped-out resources-side problems; free builds and cost additions are native; the
only new model work deferred is the one min-spend filter.

### 4.7 The conversion-chaining rule (single source of truth)

Conversions act on the **running (already-modified) cost**, so they **chain** (ruled by the user,
O1). The complete in-pool chain set is narrow:

- **Millwright is the unique sink** — it consumes any building resource → grain, and nothing consumes
  grain. Every other conversion outputs wood or clay (both building resources) and can feed it.
- **All chains are length 2**, and exist only on rooms/renovate (Frame Builder→Millwright,
  Brushwood→Millwright), stables (Feed Fence→Millwright), and fences (Rammed Clay→Millwright) — never
  majors/minors. Worked: clay room `5 clay+2 reed` → FB→MW → `3 clay+2 reed+1 grain`; stable → MW →
  `1 grain`.

**Resolution: `expand_conversions` applies each conversion's generator EXACTLY ONCE, in sink-last
order.** Each conversion's `expand1` is internally *budgeted* — it returns the unchanged cost plus
every legal variant up to that conversion's own limit (Frame Builder's "once per room/action" ⇒ its
0/1-replacement variants; Millwright's "up to 2" ⇒ its 0/1/2-replacement variants). So applying a
conversion once exhausts its budget; **the conversions are sequenced (producers before the sink) so a
later conversion sees an earlier one's output** (the clay→wood→grain chain), and no conversion is
applied twice.

> **Why not "two rounds" (an earlier formulation, corrected during implementation):** applying *all*
> conversions in two undifferentiated rounds re-applies a conversion to its own output, which
> **double-counts a once-per-action conversion** — Frame Builder on a 4-clay cost would yield an
> illegal `4 clay → 2 wood`. Apply-each-once-sink-last is the fix, and is the running code.

```python
def expand_conversions(action_kind, state, idx, ctx, base) -> list[Resources]:
    convs = owned_conversions(action_kind, state, idx)   # owned generators, producers before sinks
    cands = {base}
    for fn in convs:                                     # each conversion applied ONCE
        cands = cands | {c for b in cands for c in fn(state, idx, ctx, b)}
    return list(cands)
```

(NOT a general until-stable fixpoint — that would be speculative generality for cards that don't
exist (YAGNI). The sink-last ordering is a registration-time `order` hint on `register_conversion`;
all current chains are length 2 with Millwright the only sink.)

**Guard (TEST-ONLY, zero runtime cost; §8):** assert apply-each-once-sink-last == the full
budget-respecting closure over a corpus with ALL conversion cards owned, and that the closure is
finite. If a future card (a deck beyond E — E itself adds no at-build conversion, §4.8) introduces a
longer chain or a second sink, the test goes red and we revisit the ordering then — minimal now, loud
later, never silently wrong. This never runs on the hot path: `can_pay` short-circuits on base
affordability, and the Family registries are empty (no-op), so the expansion runs only when
enumerating an actual
card-game build whose base is unaffordable.

### 4.8 E-deck (Unofficial Compendium) sweep — no new breaker

All 168 E-deck cards (E001–E168) were read from `Rulebooks/Agricola Revised Edition - Unofficial
Compendium.pdf` and run through the same triage. The three design-breaker checks all come back
clean *under this model's boundaries*:

- **Conversion chains — clean.** The E deck adds **no at-build-payment conversion at all** (its one
  substitution card, E060, is *occupation* cost — out of scope; the grain-chaining Hewer E142 fires
  in the *harvest feeding* phase, i.e. the harvest-conversion registry, not the build cost-resolver).
  So the conversion set stays **7**, all chains stay **length 2**, and the apply-each-once rule (§4.7)
  holds for A–E.
- **Payment-linked reward — flagged, but both are triggers.** **E054 Stone Weir** ("pay 1
  *additional* building resource of a type in the printed cost to get 3 food") is the Bucksaw pattern
  — an optional add-on payment, so an `after_build_major`/`after_play_minor` trigger whose eligibility
  reads the printed cost (like Brick Hammer); it does not change the build's payment, so the frontier
  stays pure (A1 boundary). **E156 Usufructuary** rewards on an *opponent's* clay-cost build — an
  `any_player` trigger reading the opponent's printed cost; never touches the active player's pruning.
- **New payment route — flagged E027, but it's a deferred card.** **E027 Bookmark** ("discard 6 food
  from this card to build a major at no cost") is an *at-any-time free build gated on a per-card food
  stack* — two already-deferred mechanisms (at-any-time window + `CardStore`), not a new
  `PaymentOption`. **E123 Mayor Candidate** and **E074 Stone Axe** are per-card goods stacks
  (deferred X5) that feed the *resources* side, not the frontier logic.

Everything else fits existing mechanisms: reductions (E087, E130, E150, E016 incl. a spatial
edge-fence one), empty-cost free builds (E001/E002/E089/E127/E148/E149), a fence formula card (E088,
out of scope now), and the pre-action grant **Pioneer E105** (A7 — now confirmed to exist, still
outside the implemented A–D pool). New deferred cards to revisit when the per-card-goods-stack /
at-any-time machinery lands: **E027, E074, E123**.

---

## 5. Assumptions & attacks

Each load-bearing claim, the probe that would falsify it, and current status.

**A1 — "Pareto-min over goods-spent is the correct pruning."** *(RESOLVED)*
Attack: a card where paying *more* or *with a specific resource* grants a reward makes a dominated
payment strictly better, wrongly pruned (the harvest-feed/begging-marker problem). **Resolution: the
cost frontier covers only the payment for the action; reward-for-payment effects are `after_*`
triggers (§4.6).** Across decks A–D (three passes, §4.6) zero cards force a dominated-but-rewarded
payment into the frontier; alt-cost minors (Canvas Sack, Grain Depot) are Pareto-*incomparable* so
both routes survive and the reward rides the explicit payment; Brick Hammer reads the *printed* cost
(G2). The E-deck re-check (§4.8) found two more payment-linked cards (E054 Stone Weir, E156
Usufructuary) — both handled by the same trigger boundary, not frontier breakers. **Status: RESOLVED
for A–E; the §4.7 guard + the trigger/cost boundary backstop decks beyond E.**

**A2 — "Base cost is cleanly separable from the modifier layer."** *(RESOLVED)*
Attack: Cooking Hearth's Fireplace-return is a base-cost *alternative* not expressible as `Resources`.
**Resolution: `PaymentOption = Resources | ReturnImprovement(idx)`; `effective_payments` returns
`list[PaymentOption]`; non-resource routes are emitted by `base_routes` and bypass steps 2–3 (§4.5);
the commit carries the route.** Generalizes to the "Return Fireplace/Cooking Hearth" exchange minors.

**A3 — "Convert-then-reduce captures the frontier."** *(RESOLVED)*
Part 1 (reductions): convert-then-reduce is complete w.r.t. reductions — a reduction only subtracts
and can't gate on "≥N present," so it can't *enable* a conversion; conversions-first is maximal.
"Convert reed→wood, then reduce the wood" is reduce-after-convert and is captured. Part 2
(conversions chain): ruled legal; handled by the apply-each-once (sink-last) expansion + guard test. **Full rule and
pseudocode: §4.7.**

**A4 — "The frontier stays small / bounded; recomputing per call is affordable."** *(ADDRESSED)*
`effective_payments` is pure, so it recomputes on every `legal_actions` that reaches a build path —
not once. Attack: the conversion expansion × Millwright ("up to 2") × a formula choice → candidate blow-up
on a hot path. Mitigations (design, not deferral):
- **Split existence from the frontier.** Legality uses `can_pay` (short-circuits on base
  affordability; else finds any one affordable route and stops). The **full frontier runs only in
  ENUMERATION** (at a build/renovate frame — rare vs. placement checks). Mirrors majors today:
  `_can_afford_any_major_improvement` (bool gate) vs. `_enumerate_pending_build_major` (the list).
- **Family is a no-op** — empty registries ⇒ `[base]`, today's cost.
- **Per-state dedup exists** — `legal_actions_cache()` (id-keyed) collapses repeat calls on one
  state object inside MCTS.
- **Escape hatch:** projection-keyed `lru_cache` (FRONTIER_OPT_DESIGN.md) keyed on
  `(action_kind, base, owned cost-cards, resources, build_index)` — no staleness — IF profiling shows
  it hot.
**Status: build without the memo, measure in the prototype, add it only if the profile demands it
(premature caching would violate derived-not-cached).**

**A5 — "The commit can carry the payment safely."** *(CONFIRMED, O4)*
Explicit `payment: PaymentOption` on the commit (§3.2) — also required for the alt-cost minors whose
reward depends on which resource was paid.

**A6 — "Family stays byte-identical via a mechanical C++ port."** *(RESOLVED, O5)*
Every signature/shape change (§3.3) is ported to the Family-only C++ twin (§3.8); the singleton
Family frontier makes the port pure shape-mirroring. The `tests/test_cpp_*.py` gates are the check.

**A7 — "Affordability is `resources ≥ cost`, and we own the cost side."** *(SCOPED OUT)*
Attack: pre-action resource grants raise the *resources* side, flipping affordability of a build that
looks unaffordable — a **class**, not one card: Pioneer (E105, Unofficial Compendium — confirmed present (§4.8) but
*outside our implemented A–D pool*: "before you use the most recent action-space card, you get 1
building resource of your choice and 1 food"), and the same effect emerges from **in-pool combos** — Outrider (C160, "before
you use the most recently revealed action-space card, you get 1 grain") + Millwright (pay building
cost with grain). **Already handled at the build:** the grant fires before the space's host (firing
order), and the grain-payment is a *conversion in the frontier*, so `effective_payments` sees the
granted grain and offers the route. The only deferred gap is *placement-time* speculation (deciding
to take the space before the grant fires) — the ENGINE §6 speculative-legality problem, orthogonal to
the cost mechanism. **Status: the cost mechanism needs no change; placement-time speculation
deferred; the cost frontier must not assume current `p.resources` is final.**

---

## 6. Resolved forks (the rulings)

- **O1 (conversion chaining).** ✅ Conversions act on the **running cost**, so they chain
  (clay→wood→grain). All chains length 2 (Millwright the unique sink). Handled by apply-each-once (sink-last) expansion
  + a test-only guard, never on the hot path. (§4.7, A3.)
- **O2 (benefit-from-spending boundary).** ✅ Reward-for-payment effects are triggers, not cost; the
  cost frontier covers only the action's own payment. Three smaller items confirmed native: empty-cost
  formulas (free builds), signed adjustments (cost additions), and the one min-spend filter (Stone
  Company) deferred. (§4.6, A1.)
- **O3 (Fireplace-return representation).** ✅ `PaymentOption = Resources | ReturnImprovement(idx)`;
  non-resource routes skip the reduce/convert steps. (A2, §4.5.)
- **O4 (commit shape).** ✅ Explicit `payment: PaymentOption` on the commit, not a frontier index.
  (§3.2, A5.)
- **O5 (staging).** ✅ Clean, unconditional refactor + mechanical C++ re-port. Principle: a port is
  never a reason to write worse Python. (§3.6, §3.8, A6.)

---

## 7. Confirmed positions (the design in one place)

1. One general `effective_payments(state, idx, ctx) -> list[PaymentOption]`; per-action adapters
   supply only base cost + `ctx`; legality uses the short-circuiting `can_pay`; `_can_afford` stays
   the low-level primitive.
2. Pipeline: resource bases (printed + each formula) + non-resource routes → conversions (each applied once, sink-last) →
   signed reductions → keep affordable → Pareto-min over goods spent only.
3. Explicit `payment: PaymentOption` on commits (O4).
4. Clean staging + mechanical C++ re-port (O5).
5. Pointer-head encodes the whole `PaymentOption` (incl. the return-improvement route).
6. The benefit-from-spending cards are handled as **triggers** (not deferred); the genuinely deferred
   set is convertible-good costs, at-any-time conversions, per-card goods stacks, pre-action grants
   (A7), and the one min-spend constraint (Stone Company).

---

## 8. Build plan & testing

### 8.1 Build order (the prototype slice first)

> **Status (2026-06-28):** steps 1–4 **DONE** plus step 5 **all four build actions DONE** (renovate,
> build-room, play-minor, build-major) — the doc's action coverage is complete (only build-stable, an
> owner-greenlit *extension*, remains). The cost chokepoint is wired end-to-end through **renovate**
> (wide), **build-major** (wide), **play-minor** (wide), and **build-room** (two-step `PendingChooseCost`)
> per §3.4's wide-vs-two-step table; the renovate / build-room / build-major Family shape changes are
> re-ported to the C++ twin. **Five live, dealable cost cards exercise all three modifier kinds AND the conversion chain:**
> Bricklayer (REDUCTION), Frame Builder (CONVERSION), Carpenter + Clay Plasterer (FORMULAs), Millwright
> (the conversion SINK + on-play grain). Both the §4.2 worked example (Clay Plasterer + Bricklayer → a
> renovate frontier of `[1 reed]`) and the §4.4/§4.7 chain (Frame Builder feeding Millwright → a clay
> room payable as 3 clay + 2 reed + 1 grain) exist as real-card tests.
>
> **Update (2026-07-02): the slice is complete.** All five build actions (renovate, build-room,
> build-major, play-minor, build-stable) resolve through the chokepoint, and **build-fence is
> implemented** per the §9 deferred-tally model (accrue → settle at Proceed, the one mode-branched
> path). The as-built reference is `CARD_ENGINE_IMPLEMENTATION.md` §5. (An earlier revision of this
> banner listed majors/build-stable as still-to-do while the sub-bullets below already marked them
> ✅ — the sub-bullets were right.)

1. **Chokepoint, no cards.** ✅ `PaymentOption`, `CostCtx`, `effective_payments`, `can_pay`,
   `pareto_min_over_goods`, `_route_affordable`; the registries + fold accessors (`formula_mods`,
   `apply_reductions`, `expand_conversions`, `base_routes`) — all empty-registry no-ops at first.
2. **Renovate end-to-end through it.** ✅ `_renovate_ctx`; `_can_renovate` → `can_pay` (gained
   `state`); the enumerator goes wide over `effective_payments`; `_execute_renovate` debits
   `commit.payment`; removed `PendingRenovate.cost`; `CommitRenovate` gained `payment`. Also wired
   the third renovate push-site (Cottager's Day-Laborer grant). The trace action-serde
   (`trace_replay.py`) gained a tagged `payment` shape; a `sole_renovate` test thunk + a callable-aware
   `run_actions` keep the renovate tests state-driven.
3. **Two real cards on renovate.** ✅ Bricklayer (reduction) + Frame Builder (conversion), now live
   in `cards/__init__` — exercises reductions, conversions, the §4.3 ordering, and the apply-each-once
   closure, both at the chokepoint and end-to-end through House Redevelopment.
   - **Renovate-target model (2026-06-28) — generalizes renovate beyond the next tier.** Renovation's
     *target* tier is now a degree of freedom: `_renovate_ctx(p, to_material)` is parameterized;
     `_legal_renovate_targets(state, p)` returns the next tier plus any **card-added** targets via the
     `RENOVATE_TARGET_EXTENSIONS` registry (mirrors `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`); the enumerator
     goes wide over (target × payment); `CommitRenovate` gained **`to_material`** and `_execute_renovate`
     upgrades to exactly it. **Conservator** (occupation A87) is the first user — a renovate-target
     extension adding wood→stone (skipping clay); the stone-tier cost flows through the chokepoint, so
     reductions/conversions compose per target and there's no payment-provenance guessing. Chosen over a
     cost-formula+flag model precisely to avoid that provenance trap, and it absorbs Wood Slide Hammer
     (another wood→stone-direct card) cleanly. `to_material` adds to the trace serde (the bare enum
     name) and was re-ported to C++ (Family target is always the next tier, byte-identical).
4. **C++ re-port** ✅ for the renovate shape changes (§3.8); `tests/test_cpp_*.py` green (139).
5. **Extend** to rooms (two-step + `PendingChooseCost`, §3.7), then minors, then majors, then
   build-stable. Build-fence is out of scope. Sub-status:
   - **Rooms** ✅ (2026-06-28). `_build_room_ctx`; `_can_afford_room` / `_can_build_room` →
     `can_pay` (gained `state`); the multi-shot enumerator gates on `can_pay` (CommitBuildRoom stays
     geometry-only); `_execute_build_room` resolves `effective_payments` per room — debits the
     singleton inline (Family) or pushes the two-step `PendingChooseCost` (a card offers >1 payment);
     removed `PendingBuildRooms.cost`; the new CARDS-only `PendingChooseCost` + `CommitChooseCost`
     frame/commit (Python-only — not in the Family C++ twin). Bricklayer (room −2 clay) + Frame
     Builder (room conversion) now bite on rooms. C++ re-ported (`PendingBuildRooms.cost` removed,
     `execute_build_room` recomputes `room_cost`). Web UI renders the payment-bearing actions.
   - **Minors** ✅ (2026-06-28) — **wide** (`CommitPlayMinor.payment`), matching §3.4. (Briefly shipped
     as recompute-singleton, then converted to wide for consistency with renovate/majors per the owner:
     the option count is never more than a handful and a future card-policy net must not constrain the
     engine design now.) `CommitPlayMinor` gains `payment`; the enumerator goes wide over (card,
     `effective_payments`); `_execute_play_minor` debits `commit.payment` for resources and the printed
     `cost.animals` separately (a minor's **animal** cost is not card-modifiable — `PaymentOption` is
     resource-only). CARDS-only → no C++. Bricklayer's `play_minor` −1 clay now bites (tested via Junk
     Room). (Resolved fork: the trained `commit_build_major`-style worry doesn't apply — there's no
     fixed minor head, and a future card-policy net is trained on cards, so it must not constrain the
     engine now.)
   - **Majors** ✅ (2026-06-28) — **wide** (`CommitBuildMajor.payment` replaces `return_fireplace_idx`),
     resolving the earlier flag. The owner chose wide: the option count is never more than a handful,
     and — the key correction — wide does NOT break the trained `commit_build_major` head. Verified
     against `policy_heads.py`: the head's 14-class vocab is fixed *label strings* (`m{idx}`,
     `m{idx}_rf{fp}`); going wide only rewrites the action→label adapter `_major_label` to read
     `payment` (a `Resources` → `m{idx}`, a `ReturnImprovement(fp)` → `m{idx}_rf{fp}`), leaving the
     vocab and the trained weights untouched (no retrain — in Family the decision set is a 1:1 relabel).
     Implementation: `_build_major_ctx`; `_can_afford_major` → `can_pay`; the Cooking-Hearth
     Fireplace-return becomes a built-in `base_route` (`ReturnImprovement`, §4.5); the enumerator goes
     wide over `effective_payments`; `_execute_build_major` returns the Fireplace for a route payment,
     else debits the Resources; `_major_label` rewritten; **C++ re-ported** (variant payment + serde +
     policy-label). The only residual is a CARDS-only edge: a future conversion/formula-on-major card
     would create two `Resources` payments for one major → a label collision in the fixed head (graceful
     — they'd share the prior), fixable by the pointer-head migration if it ever matters; no such card
     exists and CARDS has no trained policy.
   - **Build-stable** ✅ (2026-06-28) — same two-step shape as rooms (reuses `PendingChooseCost`),
     **Python-only / no C++ port**: unlike rooms/renovate, `PendingBuildStables.cost` is *kept* (the
     base is caller-dependent — Side Job 1 wood, Farm Expansion 2 wood, card grants 0 — not derivable
     from player state), so in Family the chokepoint's singleton == `top.cost` and the debit is
     byte-identical (the §3.3/§3.8 plan already excluded the stable cost field). `_build_stable_ctx`;
     `_can_build_stable` → `can_pay` (gained `state`; 7 call sites incl. mining_hammer / groom updated);
     the enumerator gates on `can_pay`; `_execute_build_stable` resolves `effective_payments` with the
     frame's base — singleton inline debit + `record` (Millwright's per-action budget, shared across
     stables of one action) or the two-step. Millwright now bites on stables (tested: a Farm-Expansion
     stable payable as 2 grain; the 2-grain budget shared across multiple stables in one action). The
     per-action-budget mechanism + the "one instantaneous action" invariant are written up in
     `CARD_AUTHORING_GUIDE.md` §2 ("Build Rooms / Build Stables / Build Fences is ONE action").

### 8.2 Test inventory

- **Unit (frontier correctness):** the §4.1–§4.5 hand-computed frontiers, each as a test asserting
  `effective_payments` returns exactly the listed set.
- **The chaining guard (out-of-game, the user-endorsed test):** over a corpus of build states with
  **all 7 conversion cards owned at once**, assert (a) apply-each-once-sink-last `expand_conversions`
  == the full budget-respecting closure, and (b) the closure is finite. Red on any future length-3
  chain or second sink. (§4.7.) *Status:* only **two** conversion cards are implemented so far
  (Frame Builder feeder + Millwright sink), so the full 7-card guard is not yet writable; the
  apply-each-once / sink-last behavior is currently covered by real-card tests —
  `test_frame_builder_not_double_applied` (a feeder fires at most once) and
  `test_frame_builder_millwright_chain_on_clay_room` (the feeder→sink chain produces the
  cheaper chained payment, and no payment ever holds 2 wood). Promote to the full 7-card guard
  as the remaining conversion cards land.
- **Affordability-refactor equivalence:** in Family, the new `_can_renovate` / `_can_afford_major`
  return byte-identical results to the old inline-formula versions over a state corpus.
- **Family byte-identity:** the full `pytest tests/` suite stays green, and the C++ differential gates
  `tests/test_cpp_*.py` stay green after the re-port — the proof that no-cards behavior is unchanged.
- **Per-card tests:** for each cost card, the effect on the real build flow, eligibility boundaries,
  optionality (can decline a conversion), and any scope ("once per room/action").
- **New-deck checklist (coverage caveat):** when a card from outside A–D is added, re-run the chaining
  guard and re-classify it against §1.1 / §4.6 before trusting the model on it.

---

## 9. Build-fence cost modifiers — design + implementation (DONE)

> **Status (2026-06-29):** **IMPLEMENTED.** The deferred-tally model + every named fence cost card
> are built and green (full suite incl. the C++ differential gates; Family byte-identical). The
> design below held; the as-built **refinements** (deltas worth knowing) are:
> - **Supply field on `PlayerState`** (§9.7), maintained **B-manual**: decremented per-commit in
>   *both* modes (the pieces move to the board when built); only the WOOD payment is deferred to the
>   Cards settle. (The §9.13-step-4 "lean Farmyard" was overruled by §9.7's `PlayerState` — `PlayerState`
>   it is. `helpers.buildable_fences(player)` = supply + on-card pools; the Family fence-scan path
>   inlines `15 − fences_built(farmyard)`.)
> - **Three free-fence sources are registry-driven** so the engine stays card-agnostic:
>   `FREE_FENCE_SEEDS` (per-action budget — Hedge Keeper, Hunting Trophy's fence clause),
>   `FREE_FENCE_EDGES` (per-edge positional — Briar Hedge, Field Fences), `FREE_FENCE_POOLS` (persistent
>   pool — Ash Trees), applied in the §9.4 greedy order positional → budget → pool.
> - **Millwright** is a plain `build_fence` conversion checked on the running total (§9.2) — no
>   settle-only gate; `CostCtx.settle` was removed.
> - **Field Fences'** granted Build Fences is **optional** — a `PendingGrantedBuildFences`
>   choose-or-decline wrapper (optionality at the parent's choose+Stop, not a per-frame flag).
> - **Hunting Trophy:** "Return or Cook 1 Wild Boar" = a 1-boar animal cost + an `on_play`
>   cook-for-food bonus (`cooking_rates[1]`); the House-Redev "1 building resource of your choice less"
>   discount is a `build_major`/`play_minor` conversion gated on a `PendingHouseRedevelopment` frame on
>   the stack (no entry-point/`space_id` threading needed — the host stays while the inner improvement
>   resolves).
>
> The git log (`feat(cards):` from the Millwright fix through Hunting Trophy, 2026-06-29) is the
> per-increment record. **Still deferred** (need new machinery, not the cost pipeline): the restricted
> grants (Mini Pasture — §9.8), the per-segment "Nth fence" cards (Carpenter's Apprentice), Carpenter's
> Bench's payment-source restriction, and Overhaul's raze-and-rebuild. Open Air Farmer is 4+ → out of
> scope.

Build-fence was the one build action held out of the cost-modifier wiring (renovate / build-room /
play-minor / build-major / build-stable were done first — §8.1); it is now wired in too. This section
is the full design for adding discounts, conversions, formulas, and free-fence effects to it.

### 9.1 What makes fences different (and why the per-commit model doesn't fit)

Fences are not build-stable with a different base. Four structural differences drive a different model:

- **The base cost is geometry-derived per commit.** A `CommitBuildPasture(cells)` costs the wood for
  the *new* fence edges that pasture encloses — `compute_new_fence_edges(farmyard, cells)` returns
  `(h_new, v_new, wood_cost)`. (The "4th cost bucket": cost as a pure function of state + geometry —
  ENGINE_IMPLEMENTATION §3.) So the ctx `base` is computed per commit from the chosen cells.
- **One `CommitBuildPasture` adds *many* edges.** Build-room / build-stable add *one* unit per commit,
  so per-commit payment is natural there. A pasture adds several edges at once, and the interesting
  fence discounts classify or budget *edges*.
- **"Build Fences" is ONE action** (CARD_AUTHORING_GUIDE §2): the engine resolves it as a multi-shot
  chain of `CommitBuildPasture`s on `PendingBuildFences`, flipping to its after-phase on `Proceed`. No
  effect fires *between* commits — the chain is not a recognized trigger time. Per-action budgets and
  totals (Millwright's "up to 2", Hedge Keeper's "3 free", Hunting Trophy's "3 wood less total") span
  the whole action.
- **Fences are limited pieces** (15 per player), and some cards move/remove pieces independently of
  building (§9.7).

The consequence: the natural unit of payment is **the whole action, not the pasture.** Every
interesting fence discount is per-edge (positional) or a per-action budget over edges — both want to
see all the action's edges together. So we **defer payment to the end of the action** (§9.2) rather
than debiting per commit.

### 9.2 The deferred-tally model

During the Build Fences action, each `CommitBuildPasture` **builds its edges and accumulates the
running cost on the frame — it does NOT debit.** At the action's after-host (the `Proceed`
work-complete flip), the engine **settles**: tally the accrued cost, present the payment, then fire
the after-grants. So the after-host order is **settle → pay → grants** (the owner-confirmed ordering:
a settled payment before Shepherd's-Crook-style grants).

Frame state on `PendingBuildFences` (the deferred path):
- **`accrued_cost: Resources`** — the running wood owed after frees (the base `effective_payments`
  consumes at settle, so Millwright / Rammed Clay conversions apply to the whole-action total).
- **`free_fence_budget: int`** — a *generic* per-action free-fence allowance, seeded at push and
  decremented as it covers paid edges (§9.4). Dies with the frame.
- **`build_fences_action: bool`** — literal Build Fences action vs card effect (§9.6).

Settle: `payments = effective_payments(state, idx, ctx with base=accrued_cost)`. Singleton (the common
case) → debit inline. >1 (a conversion offers a choice — Millwright / Rammed Clay) → push the two-step
`PendingChooseCost(action_kind="build_fence")` **once**, over the *whole-action* total. So a multi-pasture
layout with Millwright surfaces **one** payment menu against the full bill, with the full 2-grain budget
— not chained per-pasture menus. (This one menu can be bigger than other actions' — Rammed Clay's
wood/clay split × Millwright's up-to-2 grain × up to ~15 unpaid edges — but bounded at a few dozen
options (~50 worst case); fine for a pointer-head, just chunky as a human menu.)

Legality during building: each candidate `CommitBuildPasture` is gated on "**the running total stays
affordable**" (`can_pay` against `accrued_cost + this pasture`, conversions included), not on this
pasture's cost alone — so the player can never build a layout it can't pay for at settle.

**One shared affordability/free-fence function.** The "running total stays affordable" gate (legality)
and the actual settle debit (resolution) must compute the discount + free-fence allocation with the
*same* function — otherwise legality offers a pasture that resolution then can't pay for. The existing
1×1 fast path (`_any_legal_pasture_commit` — "if any pasture is legal, some 1×1 is") is **kept** for the
placement-time "is Build Fences available?" question; only its per-candidate affordability test swaps
the raw wood check for that shared `can_pay`-with-discounts. That shared function also has to
**anticipate** the per-action budget at *placement* time — the frame doesn't exist yet, so the budget
isn't seeded — by computing the budget the action *would* seed for this entry point (Hedge Keeper's +3
on any Build Fences action; Hunting Trophy's +3 only at Farm Redevelopment). Same budget-computing
function, just called speculatively; easy, one extra call site.

**The settle payment pause is ordinary stack resumption, not new machinery.** When the settle finds >1
payment and pushes `PendingChooseCost`, the wrap-up pauses; `CommitChooseCost` pops it and
`_advance_until_decision` — being state-driven — resumes and fires the grants. At most a boolean (or
just "`accrued_cost` is now settled") marks the wrap-up phase so resume continues to grants — quite
possibly nothing new is needed. Because payment is *before* any grant, nothing has fired during the
pause, so there is no interleaving to reason about. (So we keep `settle → pay → grants`; no reorder.)

### 9.3 Family vs Cards (Fork 1): deferred is the Cards model; Family stays per-commit

Deferred-tally is THE model — the engine is built around the cards game. **Family keeps the current
per-commit debit, behind a `game_mode == FAMILY` branch in the settle path.** Not a compromise:

- **The champion NN is preserved.** The Family encoder reads wood-in-supply and has no "unpaid fence
  liability" feature; deferring in Family would make mid-fencing states show too-much wood and
  miscalibrate the champion. Per-commit Family avoids encoder surgery + a retrain.
- **C++ stays mechanical.** The C++ twin is Family-only, so the *deferred logic never ports* — it's
  Cards-only Python. The frame gains its fields, but in Family they're inert/defaulted, so the C++
  re-port is "add the defaulted fields to the struct + serialization," not a control-flow change.
- **The future Cards NN is designed for the deferred trajectory from day one** (it encodes the accrued
  liability, or only evaluates at settle). So per-commit-Family / deferred-Cards lines up with "two
  modes, two NNs, two encoders."

### 9.4 The free-fence model (three sources + greedy order)

**As built**, a fence edge is freed by one of three source kinds, consumed **positional → per-action
budget → persistent pool**. Each kind is a **registry in `cards/cost_mods.py`**, so the engine stays
card-agnostic (it consults the registries; cards register one row at import):

1. **Positional, per-edge** (`FREE_FENCE_EDGES` / `register_free_fence_edges`) — Briar Hedge ("edge of
   the farmyard board"), Field Fences ("next to field tiles"). A card's `edge_fn(farmyard, h_new, v_new,
   …) -> (h_free_bm, v_free_bm)` returns which NEW edges it frees; the fold `positional_free_edge_count`
   unions them across owned cards and intersects with the new edges. The geometry rides **directly to
   the fold** (`h_new`/`v_new` computed in `_check_entry_legal` / `_execute_build_pasture`), NOT through
   the cost ctx — the scalar `wood_cost` alone is insufficient, but the ctx didn't need to grow. Briar
   Hedge uses `PERIMETER_H_BM`/`PERIMETER_V_BM` (board-edge masks in `fences.py`), ungated; Field Fences
   classifies field-adjacent edges and gates on `initiated_by_id == "card:field_fences"` (its grant).
2. **Per-action budget** (`FREE_FENCE_SEEDS` / `register_free_fence_seed`) — the generic
   `free_fence_budget` on the frame, seeded at push from `free_fence_budget_for(...)` (which sums every
   owned card's `seed_fn`), with the SAME function consulted at three sites so they can't drift (push-time
   seed in resolution, placement-time anticipation, during-building remaining). Hedge Keeper seeds +3 when
   `build_fences_action`; Hunting Trophy seeds +3 when the entry-point `space_id == "farm_redevelopment"`.
   **Unified:** "3 wood less total" ≡ "3 free fences" (a fence is always 1 wood/edge), so there is ONE
   per-action mechanism and sources **stack** (Hedge Keeper + Hunting Trophy on a Farm-Redev action → 6).
   The remaining budget rides on the frame (`free_fence_budget`), decremented per commit; dies with the
   frame (correct per-action lifetime).
3. **Persistent pool** (`FREE_FENCE_POOLS` / `register_free_fence_pool`) — Ash Trees' "5 fences from this
   card cost nothing" is a per-game pool in the card's CardStore (`free_fence_pool_remaining` /
   `spend_fence_pools`), separate from the per-action budget. Its fences **count toward
   `buildable_fences`** (a pasture unaffordable in wood alone becomes legal) and are **spent greedily
   PER-COMMIT** (in `_execute_build_pasture`, after positional + the frame budget) — not at settle: the
   running-total legality needs the pool decremented as you build so the next commit sees the remainder.
   A pool-covered edge uses a *card* piece, so it does **not** decrement the supply pile (§9.7); the
   supply / pool piece split is resolved per-commit alongside the spend. (Only the WOOD payment is
   deferred to the settle.) Greedy is loss-less: a fence is a flat 1 wood whenever built.

Order rationale: positional first (free, no budget, so a budget never covers an already-free edge);
the *expiring* per-action budget before the *persistent* pool (never leave a use-it-or-lose-it free
unused while spending a persistent one). Per-commit greedy with this order is optimal — every paid edge
is worth exactly 1 wood, so covering any is equivalent. The during-building affordability checks the
**running total** `accrued_cost.wood + this_pasture_paid` against the conversions (Millwright counted
once per action), not per-pasture — see §9.2.

### 9.5 Gating scopes — two frame signals, read at build-time

The `PendingBuildFences` frame records its **entry point at push** — which space pushed it (Fencing /
Farm Redevelopment) or, for a card grant, the card. This single fact, read off the frame, drives all
fence-discount scoping, and is available immediately at the `before_build_fences` host — *before* any
cost ctx exists (the ctx is built at settle). `_build_fence_ctx` then mirrors the *space* part into
`ctx.space_id`, so the existing cost-system space-scoping also works at settle. There are two genuinely
**distinct** signals (the earlier "they're the same `initiated_by_id` mechanism" claim was wrong):

| Scope | Example | Gate | Granularity |
|---|---|---|---|
| Always (when owned) | Briar Hedge | ownership only | — |
| Space-scoped | Hunting Trophy ("on Farm Redevelopment") | the frame's entry-point space (mirrored to `ctx.space_id`) | *which space* |
| Grant-scoped | Field Fences ("during *this* granted action") | the frame's `initiated_by_id` | *the exact pusher (a card)* |
| Cost-pipeline (when owned) | Millwright / Rammed Clay conversions | ownership, read off the ctx | — (settle-time) |

**Space-scoped and grant-scoped are different granularities.** Hunting Trophy's FENCE clause scopes to a
real *space* (Farm Redevelopment) via the frame's entry-point `space_id`. (Its *other*, non-fence clause —
the House-Redevelopment improvement discount — turned out NOT to need `space_id` on the improvement ctx at
all: as built it gates on a `PendingHouseRedevelopment` frame being on the stack while the inner
improvement resolves — see the §9 status note.) Field Fences isn't "a space" at all — its granted action is a card
effect — so `space_id` can't express it; it needs the *exact-pusher* `initiated_by_id`. Both signals
live on the frame (so a build-time free-fence seeder reads them at the before-host); only the space part
is mirrored into `ctx.space_id` for settle-time cost-pipeline use.

**Why provenance, not a card-state latch.** "During Field Fences' grant" is identically "the active
fence frame's `initiated_by_id` is `field_fences`," so the frame's existence *is* the scope — no
set/unset, no "off for the rest of the game" cleanup, no stale latch. A normal Fencing-space action gets
neither Hunting Trophy (wrong *space* — not Farm Redevelopment) nor Field Fences (wrong *pusher* — not
its grant) even when owned — which a plain ownership gate (like Briar Hedge) would get wrong. Provenance
is documented as exactly this
"card-gating breadcrumb." (Boundary: this works because each such card pushes its own frame, or scopes
to a space that does. A hypothetical "your *next* fence action — whoever starts it — is discounted" card
would need a one-shot latch; no such fence card exists.)

### 9.6 The `build_*_action` flags

`PendingBuildFences`, `PendingBuildStables`, and `PendingBuildRooms` each gain a
`build_{fences,stables,rooms}_action: bool` set at push time, distinguishing the **literal action**
(Fencing space / Farm Redevelopment for fences; Farm Expansion for stables/rooms; grant cards that say
"take a *Build Fences* action") from a **card effect that builds** (Mini Pasture "fence a space", Open
Air Farmer "build a pasture", Shelter/Hawktower "build a stable/room").

- **Set at push from the card's text**, not derived from `initiated_by_id` — Field Fences is
  card-initiated yet *is* a Build Fences action ("take a Build Fences action"), so provenance alone
  can't classify it.
- Its consumer is **action-scoped triggers** (Hedge Keeper: "each time you take a *Build Fences*
  action" — its clarification explicitly excludes Mini Pasture / Overhaul). It does NOT gate the
  before/after hosts (Millwright's per-action reset, Shepherd's Crook's snapshot fire regardless — a
  one-off card stable is still its own build action for budget/grant purposes).
- All three flags are added **now**, not deferred — the point of going action-by-action is uniform
  machinery; each is a defaulted bool + a mechanical defaulted C++ field.

### 9.7 Fence supply becomes stored state (stables stay derived)

**`fences_in_supply`** is converted from a **derived** helper (`15 − built` in `helpers.py`) to a
**stored `PlayerState` field** (a reserve pile is the player's, not part of the farmyard grid),
decremented on build and by cards. Reason: once a card moves or removes a piece *independently of
building*, the `cap − built` derivation is wrong:
- **Ash Trees** moves up to 5 fences from supply onto the card; building one from the card's pool puts
  an edge on the board (counted as "built") that **never left your supply** — so `supply ≠ 15 − built`.
- (Deferred: Loppers exchanges a fence out of supply; Midnight Fencer takes opponents' and can exceed 15.)

So fence supply is genuinely independent state, not a cache (a built piece may not have come from
supply). **`stables_in_supply` is NOT converted** — it stays the derived `4 − built`: the only card that
removes a stable from supply (**Open Air Farmer** — "removes 3 stables from play") is 4+ / out of scope,
so no in-scope card breaks `cap − built` for stables. (`buildable_fences(player)` = the stored supply +
the on-card pools is the "pieces you can place" count the legality uses; `fences_built(farmyard)` is the
pure board count the Family cached scan inlines.)
Family is byte-identical *in value* (always `cap − built` there, since no card moves pieces), so the
C++ re-port is mechanical (add the field, init to cap, decrement on build) + canonical serialization.
Building from a card pool (Ash Trees) does NOT decrement supply; building from supply (incl.
positionally-free Briar-Hedge edges — "you still use your fence pieces") does. **As built, the PIECE
split is resolved PER-COMMIT in both modes** — each `CommitBuildPasture` spends the pool greedily
(`spend_fence_pools`) and decrements supply by `wood_cost − pool_used` immediately, because the pieces
physically move to the board when built AND the during-building legality must see the remaining pool /
supply on the next commit. Only the WOOD is deferred: Family debits it per-commit (existing behavior),
Cards accrues it and pays once at the Proceed settle. (An earlier draft said the piece split happens "at
settle"; that can't work — the running-total legality needs the pool decremented per-commit. Rooms have
no piece-pile supply — board-space-limited — so no change there.)

Because the stored field is **redundant in Family** (always `cap − built`, a pure function of the fence
arrays), it adds no distinguishing power there — so MCTS transposition equivalence classes are unchanged
and the champion's behavior is undisturbed (§9.3); the field carries new information only in Cards.

**The fence-scan cache (Python-only) is eliminated in Cards, not rebuilt.** The legal-pasture scan is
memoized for MCTS speed in the Family game — `_legal_pasture_commits_cached` (legality.py), an
`lru_cache` keyed on `(farmyard, wood, subdivision_started)`, behind `opt_config.FENCE_SCAN_CACHE`. It
is **not** rebuilt card-aware: Cards mode has no MCTS bot, so there is nothing to speed up there, and a
card-aware key (owned cards + resources + free-fence budget + supply) would add complexity and lower the
hit rate for zero current benefit (revisit if/when a Cards searcher exists). Instead:
- The **Cards legality path computes fresh and never consults the cache** (microseconds against human
  play).
- The consult site carries a precondition **`assert`** (the key `(farmyard, wood, subdivision)` is
  complete only when no fence-cost modifier applies) so a future mis-wire **fails loud** rather than
  silently returning a stale legal-pasture set.
- The **Family path is unchanged** — it's the only path that reaches the cache, and there
  `fences_in_supply == 15 − built` is still derivable from the farmyard's fence arrays, so the scan keeps
  deriving its `fences_left` from `farmyard` internally (a one-line tweak: count built fences off the
  arrays rather than calling the now-`PlayerState` helper), and the cache signature / key stay as they
  are.

**C++ has no fence-scan cache** (`any_legal_pasture_commit`, cpp/legality.cpp, recomputes directly), so
none of the above touches the C++ twin.

### 9.8 Restrictions (Mini Pasture DONE) + the Open Air Farmer decomposition (out of scope)

> **Status (2026-06-29):** **Mini Pasture is IMPLEMENTED** — the first restricted grant, validating
> the `FenceRestrictions` descriptor below. It is a MANDATORY, free, NEW 1×1 enclosure
> (`FenceRestrictions(exact_size=1, forbid_subdivision=True, max_pastures=1)` + `free_fence_budget=4`
> + `build_fences_action=False`), pushed directly by its on_play and gated by a playability prereq (the
> card is unplayable unless a free 1×1 can be built — `_any_legal_pasture_commit` with the restrictions
> + free budget). **Open Air Farmer is 4+ → out of scope**, so the restricted-grant sub-project is
> effectively complete; the OAF decomposition below is kept as a design note should a 2-player analogue
> ever appear. No `require_adjacent` field was needed (the standard adjacency rule subsumes it).

The restricted-grant cards (Mini Pasture, Open Air Farmer, Shelter) are an *alternative-build* axis,
not a cost axis, so they were **deferred out of the cost slice** (they validate the `FenceRestrictions`
descriptor below on real cards): **Mini Pasture** (restriction + free + grant — no extra cost mechanics,
**now done**), then **Open Air Farmer** (would add its stable-consumption cost + the grant-scoped
flat-price formula — out of scope at 2 players). The restriction rides on the
frame as a **small structured descriptor** (serializable + hashable — NOT an open-ended callback, which
would break the frame's hash / canonical JSON):

```python
@dataclass(frozen=True)
class FenceRestrictions:
    max_pastures: int | None = None      # Mini Pasture / Open Air Farmer = 1
    exact_size:   int | None = None      # Mini Pasture = 1 cell, Open Air Farmer = 2
    forbid_subdivision: bool = False      # Mini Pasture (per owner): must be a NEW 1×1 enclosure, not a split of an existing pasture
```

> **Owner ruling (2026-06-29):** Mini Pasture is a **new 1×1 enclosure adjacent to an existing
> pasture, never a subdivision.** So `forbid_subdivision=True` + `exact_size=1` + `max_pastures=1`.
> No `require_adjacent` field is needed — the standard pasture-commit chain (`_check_entry_legal`)
> *already* requires a new (non-subdivision) pasture to touch an existing one when any exist
> (first-pasture rule otherwise), so the card-text "adjacent to an existing one" is subsumed by the
> existing adjacency rule once subdivisions are forbidden.

Default (all None/False) = unrestricted = normal Build Fences; the legality enumerator filters
candidates by it. **Open Air Farmer decomposes cleanly:** its own resolution pays the non-resource cost
(decrement 3 stables, §9.7), then pushes a `PendingBuildFences` carrying just the geometry restriction
(size 2, max 1) with `build_fences_action=False`; the frame never knows about stables. OAF's "pay a
total of 2 wood" is a grant-scoped **base-override formula** (flat 2 wood regardless of geometry),
provenance-gated like Field Fences but a *formula*, not Field Fences' positional discount.

### 9.9 State-placement rule (general — guides every future card)

The grant-scoping decision crystallizes when to use each state home. Three-way split by **lifetime and
meaning**:

- **`initiated_by_id`** = "which card/site caused *this exact frame*." An *identity*, for gating
  frame-scoped behavior (grant-scoping). Not a general state bag.
- **Dedicated frame fields** (`accrued_cost`, `free_fence_budget`, `build_*_action`, `FenceRestrictions`)
  = **frame-scoped state/parameters** that live and die with one frame.
- **CardStore** = **card-owned state with its own lifecycle**, spanning frames (Ash Trees' game-long
  pool, Millwright's per-action conversion budget, Shepherd's Crook's before→after snapshot).

Corollary for the encoder: a frame-scoped fact the NN needs (e.g. "Field Fences' grant is live") is
*derived by the encoder from the frame at encode time*, not pre-materialized onto the card — the engine
stays clean (provenance), the projection does the work, and the choice is reversible (add a card bool
later if a card-state-centric encoder ever prefers it).

### 9.10 Card coverage

**The cost slice (all IMPLEMENTED — see the §9 status note + the `feat(cards):` git log):**
Millwright-on-fences (a `build_fence` CONVERSION checked on the whole-action **running total**, so its
"up to 2 grain per action" cap is counted once — §9.2; the earlier settle-only gate, and `CostCtx.settle`,
were removed), Rammed Clay (wood→clay conversion + on-play clay), Hedge Keeper (per-action budget +3 on a
literal Build Fences action), Hunting Trophy (per-action fence budget +3, space-scoped to Farm
Redevelopment; an *animal* play cost — "return or cook a boar" = a 1-boar cost + an on-play cook-for-food
bonus; PLUS a non-fence House-Redevelopment improvement discount gated on a `PendingHouseRedevelopment`
stack frame), Briar Hedge (positional, board perimeter), Field Fences (an **optional** grant via the
`PendingGrantedBuildFences` choose-or-decline wrapper + a positional next-to-field discount, grant-scoped;
2-food *play* cost on the play-minor path), Ash Trees (persistent pool + supply −5), and **Mini Pasture**
(the restricted grant — §9.8, the `FenceRestrictions` descriptor + a mandatory free 1×1 + a playability
prereq). The free-fence-aware `_legal_fencing` placement guard landed alongside.

**Deferred (each its own §0 decision):** Carpenter's Apprentice (per-game "13th–15th fence" — needs a
cumulative segment counter + sub-pasture edge granularity), Wood Palisades (a parallel non-piece fence
type scoring VP — board-feature), Overhaul (raze-and-rebuild — new primitive), Master Fencer (recurring
start-of-round grant + a grant-scoped flat-price formula — the cost aspect fits formula+provenance,
deferred for the start-of-round recurrence), and the one genuinely new
cost-constraint type — **Carpenter's Bench's "use only the taken wood"** (a *payment-source restriction*
`effective_payments` can't express; flag for when it lands, so we don't claim the cost model is
complete).

**Separate axes / passes (not cost machinery):** the build-fence *trigger* cards (Asparagus Gift,
Blackberry Farmer, Trimmer, Lumberjack, Loppers, Stablehand, Toolbox — before/after hosts + the
decomposition diff, Shepherd's Crook precedent; round-space goods via `future_resources`, confirmed
built), grant-a-Build-Fences-action cards (Prophet, Established Person, Nail Basket, Trellis, Agrarian
Fences, Confidant), Fencing-space triggers (Pigswill, Wood Barterer), comparative scoring (Animal
Activist, Lord of the Manor), capacity modifiers (Animal Bedding, Stable Master), and extra-placement
action-economy cards (Stock Protector). **Out of scope (3+/4+ player):** Cattle Buyer (4+), Full
Peasant (3+) — the only effect-food-cost fence cards, both multiplayer.

### 9.11 Dependencies + food-cost separation (confirmed)

- **`FutureReward` is built.** `PlayerState.future_resources` (`tuple[Resources, ...]`, 14 slots)
  carries goods/food placed on round spaces (Well + Category-8 cards); `future_rewards` carries animals
  + round-start effect hooks. So the "place food/wood on the next round spaces" trigger cards are
  unblocked (the *count* comes from the after-host diff). Not a cost-slice dependency.
- **The build-fence cost machinery is 100% wood** (+ conversions to clay/grain). It never touches food,
  so it does not collide with the parallel food-cost refactor. The only overlap is **Field Fences'
  2-food *play* cost**, which is the play-minor path (the food refactor's territory), independent of its
  fence discount (ours) — implement the discount and let the play cost ride that refactor.

### 9.12 C++ scope

Family-only twin. **Ported (mechanical):** the stored `fences_in_supply` field on **`PlayerState`**
(init 15, decremented per-commit at the build site) — Family-reachable + serialized, so the C++
`PlayerState` field + canonical serialize/deserialize (after `harvest_conversions_used`) + the
build-site decrement + the hash all landed, with `tests/test_cpp_*.py` green. This was the **only** C++
touch in the whole effort (it rode with Ash Trees, §9.13 step 4). `stables_in_supply` did **NOT**
convert — it stays the derived `4 − built` (no in-scope card moves a stable out of supply; Open Air
Farmer, its only would-be consumer, is 4+ / out of scope), so it needed no C++ change. **Does NOT port
(all Python-only):** the three `build_*_action`
flags (turned out to be default-True canonical skip-fields — omitted from Family JSON, so the C++ twin
never sees them; **done, no C++ change**), the deferred-tally settle logic, `accrued_cost` /
`free_fence_budget` consumption (also inert-in-Family skip-fields), and the free-fence / provenance
machinery — all Cards-only (the C++ twin keeps Family's per-commit debit unchanged).

### 9.13 Build order (executed 2026-06-29 — value-first; the C++ gates changed once, in step 4)

All steps below are **DONE** (full suite + C++ differential gates green; Family byte-identical):

1. ✅ **The three `build_*_action` flags** — default-True canonical skip-fields (Python-only, no C++).
2. ✅ **The deferred-tally cost path** (Python-only): **2a** routed fence cost through `effective_payments`
   (a `build_fence` action_kind, `_build_fence_ctx`, fence WOOD legality via `can_pay`); **2b** added the
   Cards deferred-tally (`accrued_cost` / `free_fence_budget` skip-fields on `PendingBuildFences`, the
   settle = tally → pay → grants resuming after any `PendingChooseCost`, the `game_mode == FAMILY`
   per-commit branch, legality on the running total — Cards computes fresh, bypasses the scan cache +
   precondition `assert`).
3. ✅ **The cost-slice cards** (Python-only): Millwright-on-fences (running total, not a settle-gate),
   Rammed Clay, Hedge Keeper, Hunting Trophy (cook bonus + Farm-Redev frees + the stack-gated House-Redev
   discount), Briar Hedge (positional perimeter), Field Fences (an *optional* grant via
   `PendingGrantedBuildFences` + the field-adjacency discount). Plus the free-fence-aware `_legal_fencing`
   placement guard.
4. ✅ **Stored supply + Ash Trees** — `fences_in_supply` converted derived→stored on **`PlayerState`**
   (NOT Farmyard — the §9.7 call won over the earlier Farmyard lean here: a supply pile is the player's,
   and the Family fence-scan path inlines `15 − fences_built(farmyard)` so the cache key is untouched),
   with its mechanical C++ re-port (the **one** time the gates changed): the C++ `PlayerState` field +
   canonical serialize/deserialize after `harvest_conversions_used` + the build-site decrement + the hash.
   `stables_in_supply` stays **derived** (`4 − built`) — no in-scope card moves a stable out of supply
   (Open Air Farmer, its only consumer, is 4+ / out of scope). Ash Trees rides on the new field via the
   `FREE_FENCE_POOLS` registry (the third free-fence source).
5. ✅ **Mini Pasture** — the first restricted grant (the `FenceRestrictions` descriptor, §9.8): a
   mandatory free new 1×1 enclosure with a playability prereq. **Done.**
6. **Still deferred** (need new machinery, not the cost pipeline): the per-segment **"Nth fence"** cards
   (Carpenter's Apprentice — a per-game ordinal counter), **Carpenter's Bench's** payment-source
   restriction ("use only the taken wood"), **Overhaul's** raze-and-rebuild (a new primitive), and the
   MCTS-macro-cost interaction (moot — no card searcher today). Open Air Farmer is 4+ → out of scope.
