# Cost-Modifier Cards — Design & Red-Team

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
> room payable as 3 clay + 2 reed + 1 grain) exist as real-card tests. **Still to do:** **majors**
> (⚠ FLAGGED — wide breaks the trained `commit_build_major` policy head; see step 5 sub-status for the
> recommended recompute-singleton path, deferred to the owner) and **build-stable** (owner-greenlit,
> after the doc — Millwright's stable clause is already registered, so this is mostly the same two-step
> wiring as build-room + a small Family C++ re-port for `PendingBuildStables.cost`). Build-fence is out
> of scope.

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

## 9. Build-fence cost modifiers — plan (NOT YET IMPLEMENTED)

Build-fence was held out of the cost-modifier wiring (renovate / build-room / play-minor / build-major
/ build-stable are done). This section is the plan for extending discounts + conversions to it. The
base wiring is straightforward and mirrors build-stable; the *exotic* fence cards are genuine §0s.

### 9.1 What makes fences different

- **The base cost is geometry-derived, not a stored/fixed value.** A `CommitBuildPasture(cells)` costs
  the wood for the *new* fence edges that pasture encloses — `compute_new_fence_edges(farmyard, cells)`
  returns `(h_new, v_new, wood_cost)` and `_execute_build_pasture` debits `Resources(wood=wood_cost)`.
  (This is the "4th cost bucket" — cost as a pure function of state+geometry — ENGINE_IMPLEMENTATION §3.)
  So the cost-ctx's `base` is computed per commit from the chosen cells, not read off the frame.
- **"Build Fences" is ONE action** (the §2 / CARD_AUTHORING_GUIDE §2 rule): the engine resolves it as a
  multi-shot chain of `CommitBuildPasture`s on `PendingBuildFences`, flipping to its after-phase on
  `Proceed`. Per-action budgets/totals (Millwright; "N wood less total") span the whole action.
- **MCTS macro-fencing.** `mcts.py` collapses a fence layout into a single `MacroFencingAction` (a path
  of pasture-commits) to bound tree depth. It assumes each commit's cost is deterministic. With a cost
  card that surfaces a payment *choice* (the two-step), that assumption breaks — but CARDS mode has no
  trained policy / MCTS bot today, so this is **moot now**; flag it for whenever a card-game searcher is
  built (the macro would need to thread the per-pasture payment choice, or fence-cost cards be excluded
  from macro collapse).

### 9.2 The base wiring (straightforward; mirrors build-stable, Python-only / no C++)

- **`_build_fence_ctx(state, p, cells)`** → `CostCtx("build_fence", Resources(wood=wood_cost), build_index=<num_built>, space_id=<"fencing" | "farm_redevelopment">)`, where `wood_cost` comes from
  `compute_new_fence_edges`. `space_id` lets a card scope to one entry point (Hunting Trophy is
  Farm-Redevelopment-only).
- **Legality:** the `_any_legal_pasture_commit` / per-candidate scan gates on `can_pay(state, idx,
  _build_fence_ctx(...))` instead of a raw wood check, so a card makes an otherwise-unaffordable pasture
  payable. (Perf note: the universe scan is cached behind `FENCE_SCAN_CACHE`; adding a per-candidate
  `can_pay` adds a cost-resolution per candidate — measure, and keep the Family path on the cheap
  `_can_afford` fast path inside `can_pay`.)
- **`_execute_build_pasture`:** resolve `payments = effective_payments(state, idx, _build_fence_ctx(...))`
  with the geometry-derived base; singleton (always in Family) → debit inline + `record_conversion_usage("build_fence", …)`; >1 → push the two-step `PendingChooseCost(action_kind="build_fence")`. `CommitBuildPasture`
  stays geometry-only (`cells`); `PendingBuildFences` keeps no stored cost (it never had one). Because the
  Family frontier is the singleton `wood_cost`, **Family stays byte-identical and the C++ twin needs no
  change** — exactly like build-stable.
- **Millwright on fences:** add `"build_fence"` to Millwright's `register_conversion` set + an
  `after_build_fences` reset auto (its per-action grain budget then shares across the whole fencing
  action, via the existing CardStore `record` mechanism). This handles the user's "Rammed Clay → /
  Feed-Fence-style → Millwright" fence chains for the simple per-action-budget case.

### 9.3 The exotic fence cards (§0 — decide per card before implementing)

- **Per-action TOTAL reductions / free counts** — Hunting Trophy ("fences on Farm Redevelopment cost a
  total of 3 wood less"), Hedge Keeper ("3 free fences per action"). These are a per-ACTION *reduction*
  budget (a total across the action), whereas the current per-action mechanism budgets *conversions*
  (the `record` hook on `register_conversion`). Extending it to reductions (a per-action reduction
  allowance in CardStore, decremented per pasture, reset at `after_build_fences`) is a modest but real
  generalization — decide the API with the owner.
- **Per-fence-segment "Nth fence" cards** — Carpenter's Apprentice ("your 13th–15th fence each cost
  nothing"). The cost is per new *edge*; "Nth fence" counts cumulative fence segments *across the game*,
  and a single `CommitBuildPasture` can add several edges of which only some are the 13th–15th. This
  needs a per-game fence-segment counter (CardStore) AND sub-pasture edge granularity in the cost — more
  than the per-pasture chokepoint models. **Defer.**
- **Conversions that only exist on fences** — Rammed Clay (fence wood→clay), etc.: fine under §9.2's
  base wiring once build-fence is a registered `action_kind`; just register the conversion. (Rammed Clay
  also has an on-play clay gain — a separate Category-2 effect.)

### 9.4 Recommended order

1. §9.2 base wiring + Millwright-on-fences (Python-only, no C++, mirrors build-stable) — covers the
   plain discount/conversion fence cards.
2. The per-action **total-reduction** generalization (Hunting Trophy / Hedge Keeper) — one API decision.
3. Defer the per-segment "Nth fence" cards and revisit the MCTS-macro-cost interaction only if/when a
   card-game searcher is built.
