# Food Payment & At-Any-Time Liquidation — Design

**Status: build-order steps 1–4 implemented (2026-06-29); step 5 deferred.** Liquidation-aware
affordability, the `PendingFoodPayment` produce-then-pay frame (play-minor + play-occupation resume),
Roof Ballaster's variant surcharge, and **Ox Goad** (pay 2 food from an `after_action_space` trigger,
then plow — the first food-from-a-trigger card, via the `FOOD_PAYMENT_RESUMES` registry generalization
of `_resume`) are landed and tested (`tests/test_cards_food_payment.py`); the Family game stays
byte-identical (C++ gates green). Still ahead: build-cost food (step 5). This document specifies how a
player pays the **food** costs that the card game introduces, including the ability to raise food mid-turn by
converting crops and animals (the "at-any-time" liquidation that the Family game only ever needs at
harvest feeding). It is the design companion for the food-payment slice of Phase 3 (Cards). It
assumes the cost machinery in `COST_MODIFIER_DESIGN.md` (the `effective_payments` cost pipeline) and
the harvest-feeding frontier in `ENGINE_IMPLEMENTATION.md` §4.

---

## 1. The problem

Several card effects cost **food**, and a player should be able to pay even when their food *supply*
is short, by converting grain / vegetables / animals to food at the moment of need:

- **Occupation play** (via Lessons): the 2nd+ occupation costs 1 food.
- **Food-cost minors** — e.g. **Shifting Cultivation** (A2): "cost 2 Food".
- **Roof Ballaster** (B123): on play, optionally pay 1 food per room → stone.
- **Ox Goad** (E19): after using Cattle Market, optionally pay 2 food → plow a field.

In Agricola a player may, at any time, eat raw grain or vegetables (1 food each) and — with a
Fireplace or Cooking Hearth — cook animals to food. So a food cost is payable as long as
`food_on_hand + everything_liquidatable ≥ cost`. The engine already computes exactly this Pareto
frontier of conversions for harvest feeding (`food_payment_frontier`); this design reuses it.

### 1.1 Preserve optionality — the conversion is *bundled*, never standalone

Per the Foundations rule (CLAUDE.md), an at-any-time conversion can always be deferred to the exact
moment its proceeds are needed, so surfacing a standalone "convert grain → food" action only inflates
the action set with a move a rational agent never makes. We therefore **never** offer liquidation as
its own action. Instead, when a food cost cannot be paid from supply, we present — *at the payment
point* — the Pareto frontier of conversion bundles that raise the shortfall, and the player picks one.
Dominance is computed over the **goods spent only**, never the food produced (an over-converting bundle
is dominated by a smaller one on the upstream goods; the surplus food is not a Pareto dimension). This
is the same rule `food_payment_frontier` already implements for feeding.

---

## 2. The central decision — produce-then-pay, *not* a cost-pipeline conversion

The cost game already has a chokepoint, `effective_payments` (COST_MODIFIER_DESIGN.md), that produces
every non-dominated way to pay a cost. The tempting move is to model "pay food, or grain instead, or a
cooked animal instead" as just another *conversion* in that pipeline. **We do not**, for a structural
reason:

> `effective_payments` is **subtract-only** and **resource-only**. Each payment it returns is a
> `Resources` vector and the debit is `p.resources - payment`. Food liquidation's defining operation
> is **produce-then-pay with banked overshoot**: cooking 1 sheep (→ 2 food) to pay a 1-food cost
> *raises* food by a net +1 (sheep −1, food +1). No non-negative `Resources` subtraction can express
> a payment that *increases* food, and animals are not in the `Resources` vector at all.

Grain and vegetables convert at rate 1, so paying with them *is* expressible as a subtraction
(`grain −1` covers `food 1`) — but that is a coincidence of the 1:1 rate, not evidence that food
liquidation belongs in the pipeline. The moment animals (lumpy, rate > 1, hearth-gated) or any banked
overshoot are involved, the subtract-only model breaks. So:

**Food liquidation is *food production*, a layer above the cost pipeline — not a payment route inside
it.** The pipeline keeps doing its job (choosing among building-resource routes) and treats food as a
component it does **not** itself liquidate.

This also means liquidation is the right home for *every* food cost, not just card-play costs: a
trigger that costs food (Ox Goad), an option folded into a play (Roof Ballaster), and a future
food-bearing build cost all reach for the same helper.

---

## 3. The mechanism — three layers

1. **Affordability (existence).** A liquidation-aware check, `_liquidatable_to`, answers "can this
   food cost be paid, counting liquidation?" It is consulted by the legality gates so a food-short-but-
   liquidatable card is *offered*.
2. **Production (the choice + execution).** A new `PendingFoodPayment` frame, driven by
   `food_payment_frontier`, is pushed **at execution** when a chosen payment needs more food than is on
   hand. It offers the conversion frontier, applies the chosen bundle (banking any overshoot), then
   resumes the action it serves.
3. **The cost pipeline treats food as a component it does not liquidate.** `effective_payments` returns
   payments that may name more food than the player holds; execution sources the shortfall via layer 2.

### 3.1 New action and frame

```python
# actions.py — CONSUMED-goods convention, mirroring CommitConvert
@dataclass(frozen=True)
class CommitFoodPayment(CommitSubAction):
    grain: int; veg: int; sheep: int; boar: int; cattle: int

# pending.py — the food-sourcing frame. RAISE-ONLY (it never debits); `owe` DERIVED live.
@dataclass(frozen=True)
class PendingFoodPayment:
    PENDING_ID = "food_payment"
    player_idx: int
    food_needed: int            # raise supply to cover this; the RESUMED action debits the cost
    resume_kind: str            # "rerun" (re-dispatch `action`) | a card id (grant registry) — §6
    reserved: Cost = Cost()     # goods the conversion must NOT consume (the cost's convertible part)
    action: Action | None = None  # the stored commit to re-dispatch when resume_kind == "rerun"
```

Two design points the implementation settled (they replace an earlier "pre-debit + body-split,
raise-and-debit" sketch):

- **Raise-only, not raise-and-debit.** The frame only *produces* food (banking overshoot) until supply
  covers `food_needed`; it does **not** debit. The thing it resumes debits the full cost itself, from the
  now-sufficient supply. This makes one mechanism serve both a *re-run of a cost-paying commit* (the
  resumed executor debits) and a *card grant* (its resume debits — Ox Goad). `owe = food_needed −
  p.resources.food` is recomputed live (never stored), exactly as `PendingHarvestFeed` derives
  `food_owed`.
- **`reserved`, not pre-debit.** Rather than pre-debiting the cost's non-food and finishing via a
  separate "body half", the frame carries the cost's convertible goods in `reserved`, and the enumerator
  runs `food_payment_frontier` over `(player goods − reserved)` — so a good the cost still needs is never
  offered as conversion fuel (the no-double-spend, §5). This unifies playing a minor and building a major
  into the same shape: *store the commit → reserve its convertible cost goods → raise the food → re-run
  the commit*, with no per-type body functions. (It is the execution-time twin of the affordability
  gate's `reserved_animals`, §4.)

---

## 4. Affordability — the liquidation-aware gate

One shared predicate, the joint **reserve-then-liquidate** check:

```python
def _liquidatable_to(state, idx, p, cost: Resources, reserved_animals: Animals = Animals()) -> bool:
    if not _can_afford(p, fast_replace(cost, food=0)):            # non-food must be on hand
        return False
    if not _can_afford_minor_animals(p, reserved_animals):
        return False
    owe = cost.food - p.resources.food
    if owe <= 0:
        return True
    rem = p.resources - fast_replace(cost, food=0)                # food untouched; non-food reserved
    sR, bR, cR, vR = cooking_rates(state, idx)
    max_food = (rem.grain + rem.veg * vR
                + (p.animals.sheep  - reserved_animals.sheep)  * sR
                + (p.animals.boar   - reserved_animals.boar)   * bR
                + (p.animals.cattle - reserved_animals.cattle) * cR)
    return max_food >= owe
```

**Two correctness requirements — both load-bearing:**

- **Gate↔frontier agreement.** Two *different* functions decide whether a card is playable: the
  *gate* (`can_pay` / `playable_minors` — does this card light up?) and the *menu*
  (`effective_payments` — which pay buttons exist?). The minor enumerator is literally
  `for cid in playable_minors: for payment in effective_payments(ctx): emit`. If the gate is
  liquidation-aware but the menu's affordability filter is not, a food-short-but-liquidatable card is
  marked playable yet produces **zero** buttons → a frame with no legal action → a dead state. So
  `_liquidatable_to` must replace the food-component affordability in **both** `can_pay` *and* the
  `effective_payments` "keep affordable" step (the pipeline's only food-aware edit), and the gate's
  max-producible-food math must agree with `food_payment_frontier`'s feasibility — both must use the
  same rates over the same convertible goods, so "max producible ≥ owe" (the gate) holds exactly when
  the frontier is non-empty (execution). (The per-good caps inside `food_payment_frontier` are a
  Pareto-optimization detail, not the feasibility test.)

- **Animal reservation (`reserved_animals`).** Liquidation can cook animals, so if the cost *also* has
  an animal component the animals needed to pay it must be reserved before counting them as
  liquidation fuel. The cost pipeline is resource-only and doesn't carry animals, so `CostCtx` gains a
  `reserved_animals` field that `_play_minor_ctx` fills from `spec.cost.animals`, read by
  `_liquidatable_to`. *Latent today* — no minor in the catalog costs both food and an animal — but the
  wiring is written correctly so the first such card is right, with a guard test.

**Family path guard.** Gate `_liquidatable_to` behind `cost.food > 0`
(`_can_afford(p, base) or (base.food > 0 and _liquidatable_to(...))`). A Family build cost has
`food == 0`, so it takes the exact current `_can_afford` path with no extra work on the hot legality
path. This is a speed/clarity choice, **not** a "don't change Family" mandate — if a better card design
needed to change the Family shapes we would port the C++ to match (Family C++ is cheap to re-port and
never a reason to compromise the card design).

### 4.1 The gates that change

- `playable_minors` → already calls `can_pay(...)`; make `can_pay`'s food-component test
  liquidation-aware, and the same in `effective_payments`' affordability filter.
- `_legal_lessons_cards` → replace `_can_afford(p, occupation_cost(n))` with
  `_liquidatable_to(state, idx, p, occupation_cost(n))`. (Occupations stay off `effective_payments` —
  no cost card touches occupation play cost, so routing them through the full pipeline buys nothing.)

---

## 5. Execution — reserve, push, resume

Split each play executor into a **charge half** (debit, or detect shortfall and push) and a **body
half** — the existing post-debit logic, preserved unchanged: move the card hand→tableau (or pass it),
Each cost-paying executor gains a **food-shortfall entry guard** and is otherwise unchanged. The guard:
if the cost's food exceeds the food on hand, reserve the cost's convertible goods and push a *raise-only*
`PendingFoodPayment` carrying the commit; otherwise debit the full cost and run as today. The guard is
**re-entrant** — after the food is raised, the resume re-dispatches the *same* commit, the guard's
food check now passes, and the executor debits and completes. No charge/body split; the executor is one
whole function reached identically by the direct path and the re-run.

```python
def _execute_play_minor(state, idx, action):
    spec = MINORS[action.card_id]; p = state.players[idx]; pay = action.payment   # Resources
    if p.resources.food < pay.food:                              # raise the shortfall, then re-run
        reserved = Cost(resources=fast_replace(pay, food=0), animals=spec.cost.animals)
        return push(state, PendingFoodPayment(idx, food_needed=pay.food,
                                              resume_kind="rerun", reserved=reserved, action=action))
    p = fast_replace(p, resources=p.resources - pay, animals=p.animals - spec.cost.animals, ...)
    ...  # move card hand→tableau (or pass), pivot to after-phase, run on_play, fire one-shots
```

The `CommitFoodPayment` handler applies the chosen conversion **raise-only** (no debit), pops itself, and
resumes:

```python
def _execute_food_payment(state, idx, action):
    top = state.pending_stack[-1]
    sR, bR, cR, vR = cooking_rates(state, idx)
    produced = action.grain + action.veg*vR + action.sheep*sR + action.boar*bR + action.cattle*cR
    p = state.players[idx]
    p = fast_replace(p,                                           # RAISE-ONLY: add produced, never debit
        resources=(p.resources - Resources(grain=action.grain, veg=action.veg)
                   + Resources(food=produced)),
        animals=p.animals - Animals(action.sheep, action.boar, action.cattle))
    state = _update_player(pop(state), idx, p)                    # pop PendingFoodPayment
    return _resume(state, idx, top)                              # §6
```

**Stack invariant.** After the pop, the host (`PendingPlayMinor` / `PendingBuildMajor` / …) is back on
top, so the re-run reads the right top and its after-phase pivot — and a pushing `on_play` (Shifting
Cultivation → `PendingPlow`) — land exactly as on the direct path.

**Closed frame.** While `PendingFoodPayment` is on top the only legal actions are its frontier points
— no triggers, no Stop — so nothing interleaves between committing to the action and paying for it,
matching the rule that paying for a play/effect is atomic.

---

## 6. The continuation — data, not a closure

When the food is raised, the engine must continue with whatever the food was *for*. A frame is a frozen
dataclass that has to be hashable (MCTS transposition table) and JSON-serializable (the canonical C++
contract), so it **cannot** store a function describing "what to do next." The continuation is recorded
as plain data and `_resume` dispatches on it. There are exactly two shapes:

| `resume_kind` | Who | What `_resume` does |
|---|---|---|
| `"rerun"` | any cost-paying commit — play a minor, play an occupation, build a major, future food-bearing builds | re-dispatch the stored `action` through the normal `COMMIT_SUBACTION_HANDLERS` table; the executor's own shortfall guard now passes, so it debits the full cost and completes. **Not** wrapped in `_fire_subaction_before_auto` — the executor owns its own firing |
| a card id | a card grant — Ox Goad (pay 2 food → plow); later Resource Recycler (pay → free room) | call the card's registered `FOOD_PAYMENT_RESUMES[id]` (debit the food + push the granted primitive), **wrapped** in `_fire_subaction_before_auto` so the fresh leaf's before-autos fire, mirroring `_apply_fire_trigger`'s post-apply seam |

The `"rerun"` branch is the unification: storing the commit and re-dispatching it covers minors, occupations,
majors and the coming build-cost-food cards with one path and no per-type body functions. A grant is the one
genuinely different shape (it pushes a leaf rather than re-running a host that ends in its after-phase), which
is exactly why it is wrapped and `"rerun"` is not.

---

## 7. Worked examples (the arithmetic, including banking)

All assume a food cost paid via `PendingFoodPayment`; `rates` from `cooking_rates`.

- **Grain, exact.** Cost 2 food; player has 0 food, 2 grain. `owe = 2`. Frontier: consume 2 grain
  (→ 2 food). End: 0 food, 0 grain. No overshoot.
- **Animal, with banking.** Cost 1 food; player has 0 food, 1 sheep, a hearth (sheep → 2). `owe = 1`.
  The only frontier point consumes 1 sheep (you cannot make exactly 1). `produced = 2`; food =
  `0 + 2 − 1 = 1` **banked**, sheep 0. Correct: you cooked a sheep for 2 food, paid 1, kept 1.
- **Partial food on hand.** Cost 3 food; player has 1 food, 1 sheep (hearth). `owe = 3 − 1 = 2`.
  Consume 1 sheep (→ 2); food = `1 + 2 − 3 = 0`, sheep 0. No overshoot.
- **No hearth.** Animals contribute 0 (`cooking_rates` returns 0 for animals without a cooking
  improvement), so the frontier is over grain/veg only — automatically, no special case.

---

## 8. Roof Ballaster — the "paid option" cost lives on the variant

Roof Ballaster's benefit is *immediate and needs no further choice* (pay 1 food → N stone, done), so it
folds into a **play variant**: the play surfaces as two complete actions, "pay" and "decline" (the
existing variant mechanism, like Cooking Hearth's Fireplace-return). The optional 1 food is therefore a
**surcharge on the play cost**, handled by the machinery above with no special path.

- The variant declares its **own cost** (return `(variant, cost)` from the variants function — a full
  `Cost`, not a bare food number), rather than a side table. General principle: *a cost lives on
  whatever surfaces the option* (a variant here; a trigger for Ox Goad), and routes through the shared
  affordability + `PendingFoodPayment` path.
- Total food for the chosen variant = base play cost + the variant's surcharge → `food_to_debit`.
- `on_play("pay")` grants the stone and **no longer debits food itself** (the surcharge is already in
  `food_to_debit`). This also **fixes a latent bug**: the current `_variants` gates "pay" on
  `food >= 1` read *before* the play cost is debited, so a 2nd-occupation play with exactly 1 food would
  drive food negative; routing the whole cost through one liquidation-aware check removes the double
  debit.

This is *only* a cost-placement principle — it does **not** mean Roof Ballaster and Ox Goad share a
mechanism. Roof Ballaster is wide variants of one atomic action; Ox Goad is a trigger with a sequential
cost-then-effect. They share only the `PendingFoodPayment` payment path, not their structure.

---

## 9. Scope — in now, deferred, out

**In scope now** (the cards being implemented need them):
- Occupation play costs (Lessons) and food-cost minors (Shifting Cultivation).
- Roof Ballaster (variant surcharge).
- **Animal liquidation** — *included*, because `food_payment_frontier` already enumerates
  grain+veg+animals together; excluding animals would mean *crippling* the helper, not saving work.

**Supported pattern, implement with the relevant cards:**
- Ox Goad (E19) — a trigger that pays food then grants a plow: `after_action_space` trigger (Cattle
  Market) + `PendingFoodPayment(food_to_debit=2)` + `PendingPlow`. Eligibility: can afford 2 food (with
  liquidation) **and** a plowable field exists. Lands with the E-deck trigger work.

**Deferred — food in a *build* cost (rooms / stables / renovate / fences):**
- The cost frontier and the food-shortfall push would need to be added to the *build* executors, and
  each needs its own build-specific resume context (which cell, which material). Only three catalog
  cards put food in a build cost, and all are out of the current path:
  - **Stable Cleaner** (C94) — *at-any-time* Build Stables at "1 wood + 1 food per stable". Deferred
    (also in the at-any-time hard set).
  - **Trowel** (D13) — *at-any-time* renovate to stone at "1 stone + 1 reed + 1 food per room" from
    wood. Deferred (also at-any-time).
  - **Resource Recycler** (C149) — *not* a food-in-build-cost: it's the Ox Goad pattern (pay 2 food via
    a trigger → build a *free* room) and is **4+ players only**, so out of the 2-player scope entirely.
  - **Wood Expert** (D117, "pay 1 food instead of up to 2 wood per *improvement*") would put food in a
    **build-major** payment (improvements = majors + minors; minors are already covered by the card-play
    path). Build-major liquidation is the natural first extension when Wood Expert is implemented.
- So: defer all build-cost food until a card forces it. The machinery is built to extend — adding a
  build executor's shortfall-push + a new `resume_kind` — but no implemented card needs it.

---

## 10. Preserve-optionality consequence — skip when food suffices

`PendingFoodPayment` is pushed **only** when the chosen payment needs more food than is on hand, so a
food-rich player simply pays food with no extra decision. This is the desired "don't surface a
conversion when none is needed" behavior. The one accepted incompleteness: a food-rich player is never
offered "spend grain to *preserve* food" (pay a 2-food cost with 2 grain while holding food) — a real
but marginal choice. The cost pipeline does not enumerate grain/veg breakdowns of a food cost (that is
`PendingFoodPayment`'s job, and it only runs when short), so that option is dropped by construction. A
fully rules-complete engine could surface it; we judge the branching cost not worth the marginal value,
and an agent-layer restriction could reintroduce it later if ever wanted.

---

## 11. C++ / Family

`PendingFoodPayment` and `CommitFoodPayment` are **card-only** — a Family game never produces them, so
the Family C++ twin and its differential gates are unaffected. The only shared (ported) code touched is
the affordability path, and the `cost.food > 0` guard keeps the Family path running the identical
`_can_afford` it runs today, so the gates stay green with no re-port. (Were a future card design to
change Family shapes, re-porting the Family C++ is an accepted maintenance cost, not a design
constraint.)

---

## 12. Red-team summary (ranked by real risk)

1. **Gate↔frontier agreement (must-do).** Make *both* `can_pay` and the `effective_payments`
   affordability filter liquidation-aware, or a playable card emits no buttons → dead state. Not a
   design flaw — "do both halves of one change." Highest priority because it breaks at runtime.
2. **Animal double-count (latent).** Reserve the animal cost before counting animals as liquidation
   fuel (`reserved_animals` on `CostCtx`). No catalog card triggers it (none cost food + animals), but
   wire it right with a guard test.
3. **Family guard (perf/clarity).** The `cost.food > 0` guard; not correctness.
4. **Build-cost extension is not free** — each build executor needs its own shortfall-push and resume
   context; deferred until a card needs it (§9).

Implementation hygiene (no design impact): don't let the body half re-debit; assert the frontier is
non-empty at the enumerator (so a feasibility mismatch fails loud); read Roof Ballaster's base play
cost off the frame rather than recomputing.

---

## 13. Build order

1. **[DONE]** **`_liquidatable_to` + both affordability sites** (`can_pay` / `effective_payments` filter
   + `_legal_lessons_cards`), guarded by `cost.food > 0`; `reserved_animals` on `CostCtx`. Smallest
   verifiable slice — affordability only, no new frame yet. Family stays byte-identical.
2. **[DONE]** **`PendingFoodPayment` / `CommitFoodPayment`** + the enumerator + the charge/body split for
   `play_minor` and `play_occupation` + the `_resume` switch. End-to-end for Shifting Cultivation and a
   liquidation-paid occupation.
3. **[DONE]** **Roof Ballaster** — per-variant cost on the variants function (now
   `variants_fn -> list[(variant, Resources surcharge)]`, the enumerator filters by liquidation-aware
   affordability of base+surcharge); `on_play("pay")` grants stone without re-debiting; the latent-bug
   fix.
4. **[DONE]** **Ox Goad** — an optional `after_action_space` trigger on Cattle Market whose apply
   charges 2 food (via the shared food-payment path) then grants a `PendingPlow`. Introduced the
   `FOOD_PAYMENT_RESUMES` registry (the third consumer, generalizing `_resume`'s switch): the frame's
   `resume_kind` is the card id, and `_resume` fires the granted leaf's before-autos at the registry
   branch (mirroring `_apply_fire_trigger`'s seam for the food-on-hand path). Eligibility gates on both
   2-food affordability (with liquidation) AND a plowable cell; the plow is mandatory once the trigger
   is fired (optionality is the FireTrigger).
5. **Build-cost food** — deferred; revisit per card (Wood Expert → build-major first).

---

## 14. Test plan

- **Frontier/banking unit tests:** the §7 examples, asserting the resulting supply (including banked
  overshoot) and the offered frontier.
- **Affordability:** food-short-but-liquidatable card is offered; food-and-truly-unaffordable card is
  not; the food+animal-cost case (the `reserved_animals` guard) — constructed via a test factory since
  no real card has that cost yet.
- **Gate↔frontier agreement:** a state where a minor is playable only via liquidation produces ≥1
  `CommitPlayMinor`, and the resulting `PendingFoodPayment` has a non-empty frontier.
- **Skip-when-sufficient:** a food-rich play debits food directly with no `PendingFoodPayment` pushed.
- **Resume integrity:** a pushing `on_play` (Shifting Cultivation → plow) lands correctly after a
  liquidation-paid play; passing minors still pass.
- **Roof Ballaster:** "pay" with insufficient food but liquidatable goods plays + grants stone + banks
  overshoot; the formerly-buggy "2nd occupation, exactly 1 food" case no longer drives food negative.
- **Family byte-identity:** the full suite and the C++ differential gates stay green (the guard makes
  the Family affordability path identical).
