# Possible Next Steps

Last updated **2026-07-22** — reconciled against the code after ~247 commits since the previous
(2026-06-27) revision. This is a planning document, not a commitment. The 2026-06-27 version was
organized around the *first* card batch and the Family→cards transition; almost all of that has
since landed (the trigger/hook system, CardStore, draft mode, the timing-window ladders, ~560
cards). It has been reorganized to lead with the two workstreams that dominate what remains —
**card machinery still to build** (§1) and **card categories still to implement** (§2) — followed
by the smaller fixes (§3), non-card features (§4), the card-game AI pipeline (§5), and misc (§6).
A record of what was removed as complete is at the bottom (§ "Completed since 2026-06-27").

> **Two standing cautions when using this doc.**
> 1. **The card census is a live number — always re-derive it, never trust a written count**
>    (this doc's, CLAUDE.md's, the ledger's, or the JSON `status` fields — all lag reality):
>    ```bash
>    ~/miniconda3/bin/python -c "from agricola.cards.specs import OCCUPATIONS, MINORS; print(len(OCCUPATIONS), len(MINORS))"
>    ```
>    At this revision it returns **232 occupations + 331 minors = 563** of the 840-card catalog.
> 2. **Some design docs are themselves stale on "what exists."** In particular
>    `CARD_ENGINE_IMPLEMENTATION.md` §8 and `CARD_DEFERRED_PLANS.md`'s bottom sections still label
>    several *built* mechanisms "unbuilt" — the before-scoring decision window, the
>    before-round-start hook, the `PendingRoundEnd` round-end ladder, and the after-feeding-phase
>    conversions frame are all live in the code. Verify against the code, not the doc's prose, before
>    concluding something needs building. (Cleaning up those stale sections is itself a small
>    follow-up task — see §6.)

---

## 1. Card machinery still to build

The remaining Phase-3 *engine* work. Each item is a subsystem or seam that blocks a class of cards;
most are **user-gated** (they need a rules/design decision before code, per the cardinal rule that a
card which doesn't cleanly fit is deferred to the user, never approximated). Ordered roughly by how
many cards each unblocks.

### A. Placement legality as reachability (the big open subsystem) — USER-GATED

The engine decides whether a worker placement is legal with a per-space predicate over the *current*
state. A family of cards breaks that model: a placement can grant goods **after** the placement
decision but **before** the space's mandatory work (Sweep grants clay in time to pay a renovation the
predicate calls unaffordable), so the correct definition is *reachability* — a placement is legal iff
some finite sequence of the granted sub-actions can complete it. Design work exists
(`PLACEMENT_REACHABILITY_DESIGN.md`, with a phased build sketch; `LEGALITY_HARD_CASES.md` catalogs ten
mechanism classes M1–M10 that break state-read legality). Only the narrowest slice is handled today
(the M1 Lessons-payment sub-family via `_payable_occupation`'s single-source simulation, plus the
fence-budget anticipation). This is **on hold pending the user's design choice**; it is the umbrella
that also covers:

- **The reveal-order card cluster** (~13 cards: Brook, Master Workman, Knapper, Sweep, Silokeeper,
  Outrider, Pioneer, Legworker, Bean Counter, Wholesaler, Pig Stalker, Task Artisan, Water Worker) —
  before-placement income keyed to the **hidden** round-card reveal order (which lives in the
  `Environment`, not `GameState`). The design's "intended first implementation batch."
- **Speculative placement-time legality** — deciding to place *because* a not-yet-fired grant would
  make the action affordable (the Pan-Baker-enables-Potter shape).
- **Grocer / conversion-reachability legality** — cards that hold goods *on the card* and let you
  spend them, making affordability a reachability question over interleaved buys and spends where
  componentwise Pareto dominance is unsound under fungibility. The **storage** half is built
  (`interim_storage` in CardStore; Forest Stone and Porter ride it); the **legality** half is the open
  part (`CARD_SYSTEM_DESIGN.md` §15 has a 7-step fixture + 7 candidate approaches).
- **Confirmed live legality defects** surfaced by the catalog (`LEGALITY_HARD_CASES.md` §13): Writing
  Desk's fire-guard can strand on the post-spend Lessons ramp; Wood Workshop / Thresher / Seed Pellets
  under-offer. Some are independently point-fixable; the general fix is this oracle.

### B. At-any-time standalone conversions + the end-of-turn event (co-dependent) — USER-GATED

The literal **"at any time"** phrase appears on **exactly 31 cards** — a closed, enumerable family,
**none implemented**, consistent with the deliberate engine boundary (the "preserving optionality"
principle bundles conversions into the decision points that need their proceeds rather than surfacing
them standalone; food liquidation, §"Completed", is that principle applied to food costs). What's
missing is the general case where a conversion's proceeds are a **non-food good** ("buy 1 wood for 1
food at any time") — there is no bundling point for it yet (`CENSUS_AT_ANY_TIME.md`; ~10 in the
difficulty core: Grocer, Seed Trader, Emissary, Trowel, Stone House Reconstruction, Mason, Master
Builder, Piggy Bank, Roll-Over Plow, Changeover, Clearing Spade). This is **co-dependent with the
end-of-turn event**: a hook fired at the space-host pop lands one window too early once anytime
effects exist (goods would still be spendable within the turn), so the two must be designed together.
Named blocked consumers of the end-of-turn hook: Firewood Collector, Farmstead, Toolbox (turn-end
build detection). Partial progress on the round-start/harvest-gated *variant* of buy-conversions (New
Purchase, Value Assets, Cookery Lesson, Green Grocer built); the genuinely-anytime family is the
blocked core.

### C. Any-source firing events (the general event-payload gap)

The general firing system names an event (`after_play_minor`, …) but carries **no payload** — no data
about *what caused* it. Three "however-caused" event families do not exist and block the hardest
reactive cards (`CENSUS_REACTIVE_TRIGGERS.md` catalogs 153 reactive cards; the payload-blocked ones
are the tail):

- a **cell-became-used** event (Potter's Yard A40, Farmstead C48);
- an **any-source goods-gained** event (Kindling Gatherer, Mattock);
- an **any-source newborns-gained** event (a markets-included "each time you get newborns" trigger).

Two deliberate exceptions were already built, both *harvest-scoped* registries rather than general
events: the harvest occasion manifest and the breeding-outcome payload (which is how Dung Collector /
Champion Breeder landed without this). Adding payloads to the general system is a firing-API change —
defer until a cluster justifies it, then decide the API.

### D. Cost-imposition (tax) family + the AND-side placement seam

A small family (`CENSUS_COST_IMPOSITION.md`, 8 cards) imposes a **mandatory cost on an otherwise-free
action**. Two are built (Credit A54, Animal Catcher C168) — but both are the recurring-upkeep-with-
begging-fallback shape, which needs *no* legality change. The unbuilt piece is the **"AND-side"
placement seam**: when a card makes a currently-free action cost something, the placement predicate
must check that mandatory cost is payable. **Dwelling Mound** is the pivotal card — it puts a cost on
the currently-free plow primitive. Zero AND-side members built.

### E. Temporary / extra worker

Support for a worker that acts without becoming a family member — a meeple borrowed from supply that
places like a worker, returns to supply (not home) at return-home, needs no food, and scores nothing
— plus the related "place two workers in one turn" shape. No such machinery exists.
`TEMP_WORKER_DESIGN.md` is a draft. Blocks Motivator E93, Telegram A22, Bassinet A25, Stock Protector
B94, Lazy Sowman A94 (also needs a "declined sub-action" event), Sidekick A171, Lasso B24; interacts
with Canal Boatman / Sheep Inspector / Tea Time. The base field the design leans on
(`workers_in_supply`) already exists. (Walking Boots B22 was also in this cluster but now carries a
`wontfix` marker in the card data — see the data-vs-doc note in §2.E.)

### F. New shared action space registered from a card

Some cards introduce a brand-new action space to the board — shared (Chapel A39, Forest Inn B42) or
owner-private (Final Scenario B23). There is no seam to register a new space from a card; the action
board, legality enumeration, and the NN encoder all assume the fixed space set. Substantial.

### G. Randomness inside `step` (in-turn chance events) — USER-GATED

Paper Knife A3 and Moonshine B3 need randomness resolved *inside* `step()`, which collides with the
load-bearing "determinism after setup" invariant. Supporting them means a nature-step / chance-node
model for in-turn randomness, analogous to the round-card reveal. Deliberate engine boundary; needs a
design decision.

### H. New sub-action primitives (raze-and-rebuild)

**Overhaul (C001)** needs a "raze all your fences, then rebuild up to 3 from supply, keeping animals"
primitive in one atomic effect. No `PendingRaze` / raze primitive exists. A concrete waiting consumer;
a flagged cost/build-model gap.

### I. End-game arrangement / capacity scoring

The end-game **decision window** already exists — `register_before_scoring` +
`engine._push_before_scoring_choice` at the `BEFORE_SCORING` boundary, in use by Ox Skull (§8 of the
card engine doc still calls this "unbuilt" — it is stale). What remains unbuilt is the *scoring
computation* behind two consumers: **Organic Farmer (B98)** needs per-pasture arrangement/capacity
geometry ("1 point per pasture with ≥1 animal and unused capacity for ≥3 more"), and **Sheep Walker**
needs end-game conversions whose **proceeds are points**. (Organic Farmer is the last unbuilt member of
the old Milestone-1 deferral list.)

### J. Per-card goods stack (beyond a CardStore scalar)

CardStore holds only scalars today. Cards that park **multiple goods on the card over time** need a
real per-card goods stack: Hayloft Barn B21, Muddy Puddles B83. (Forest Plow's return-wood-to-space
and Maintenance Premium's scalar were rescued without it.)

### K. Small open per-cluster seams (each a targeted, mostly-cheap build)

The big subsystems above dwarf a set of small, well-scoped seams that each unblock one or a few cards.
Batch these opportunistically:

- **`after_play_kept_minor` event** (fires only when `minor_improvements` actually grew, so a
  *passing* minor doesn't trigger it) — Scales B49.
- **Per-action build-count cost discount** — Carpenter's Hammer A14.
- **Fence-legality change** — Agrarian Fences B26.
- **Grid/adjacency geometry** (most were rescued by inline adjacency; these 3 remain) — Farm Hand B85,
  Future Building Site B38, Love for Agriculture B72. Likely cheap; re-triage per card.
- **Super-linear multi-tier converter in the payment frontier** (USER-GATED) — Beer Tap's 2/3/4 grain
  → 3/6/9 food doesn't fit the fixed-rate raise frame (forces the once-per-harvest budget at the
  smallest covering tier, silently removing a save-for-later config). Beer Tap is feed-seam-only for
  now; the full-frontier handling is an open design question (`CARD_ENGINE_IMPLEMENTATION.md` §8,
  ruling 78 item 1).
- **Decline income for a played-but-unusable composite** (USER-GATED) — Harvest Festival Planning
  pushes a "Major or Minor Improvement" composite from its own on-play resolution; when it has *no*
  legal child it pushes nothing and pays nothing. Whether that should pay under the
  "could-not-use = declining" principle is a user call (ruling 78 item 4).
- **Round-end use-it-or-lose-it conversion members** — the round-end ladder exists, but the "once per
  round you can pay X→gain Y, expiring at round end, scheduled onto the next round's spaces" shape is
  not built onto it: Corn Schnapps Distillery C64 (archived), Mandoline C46, Pellet Press D46; plus
  Claypipe (a choice-free round-end automatic needing a "building resources gained this work phase"
  counter).
- **Misc one-offs** — Wood Palisades B30 (alternative fence piece + supply-cap bypass), Hawktower B14.
  (Shaving Horse A48 — an "after you obtain wood" event — was also here but now carries a `wontfix`
  marker in the card data; see §2.E.)

### L. Documented cost-model gap with no current consumer (park, don't build)

**Payment-source restriction** — a build paid *only* from goods that came from a specific source
("use only the taken wood"). `effective_payments` has no concept of goods provenance. The one card
that needed it, **Carpenter's Bench B15, is WONTFIX** (user ruling 2026-07-21), so this has no waiting
consumer. Keep it flagged so the cost model isn't mistaken for complete; build only if a future card
resurfaces the need.

---

## 2. Card catalog — categories still to implement

The single largest *ongoing* Phase-3 workstream: keep implementing the 840-card catalog (420
occupations + 420 minors; Base Revised + Artifex + Bubulcus + Corbarius + Dulcinaria + Consul Dirigens
+ Ephipparius; decks A–E, 84+84 each). At this revision **563 are built (232 occ + 331 min, ~67%)**,
leaving **277 unimplemented (188 occ + 89 min)**. There is no untouched expansion or deck — every one
is partially done, so this is breadth-wide template work, not a fresh start. The 277 break down as:

### A. Tractable seam-fit cards — the copy-a-template bulk

The card machinery is built and rich (66 `register_*` seams; CLAUDE.md's "~35" undercounts). Most
not-yet-reached, non-blocked cards fit an existing pattern and are "copy an existing template" work,
bucketed by the categorization docs (`design_docs/cards/ARTIFEX_CATEGORIZATION.md`,
`BUBULCUS_CATEGORIZATION.md`, `CARD_TRIAGE_CDE.md`, `CARD_BATCH_TRIAGE.md`). This is the bulk of the
~120 implementable two-player cards — everything left once the §1-blocked, ambiguity-deferred (§2.C),
and Group-C (§2.D) cards are set aside. It is where steady batch progress happens; each batch still
goes through the per-card verifier (fidelity-first) and updates the Status section.

### B. 3+/4+ occupations (~144) — design inputs now, dealt only in 4-player

Occupations carry a player-count field (minors are all "1+"). Of the 188 remaining occupations, only
**44 are "1+"** (dealt in the current 2-player game); **65 are "3+" and 79 are "4+"** — **144 not dealt
in 2-player**. So the remaining work that touches the *live* 2-player card game is **44 occ + 89 min =
133 cards**. Per the 2026-07-03 directive, the 144 higher-count occupations are **design inputs** for
shared machinery (survey their shapes when building hooks/registries) and are the concrete card list
for the eventual 4-player variant (§4).

### C. Deferred for ambiguity (3) — need a user reading, not machinery — USER-GATED

The printed text does not determine a single reading; each needs the user to pick an interpretation
before it can be built: **Perennial Rye C84** (no timing anchor, ruling 50), **Heresy Teacher A113**
(the only mixed grain/veg-field producer; per-field interaction too fiddly, ruling 53), **Lumber
Virtuoso D129** (3+; ambiguous scope, ruling 51).

### D. Group-C boundary decisions (a further cluster, ~8–12 cards) — USER-GATED

`CARD_DEFERRED_PLANS.md` Group C holds deliberate engine boundaries that are *design decisions*: the
at-any-time buy-conversion family (C1 — partly crossed; Kettle B32, Potters' Market B69, Oriental
Fireplace A60, Clay Carrier D122 remain), **action substitution** (C2 — the "instead of action X, do
Y" model; no such model exists. Its one named consumer, Freshman A97, now carries a `wontfix` marker,
so like the payment-source gap in §1.L this boundary has no live consumer — build only if a future
card resurfaces it), the remaining multi-plow member (C4 — Reclamation Plow A17, reusing the
Wheel/Double-Turn mechanism now built), and **Confidant B93** (C5 — buildable but composes 4–5
mechanisms at once; held for an explicit go-ahead + careful test).

### E. WONTFIX (13) — record, never implement

13 cards are marked `status: wontfix` in the card data (`revised_occupations.json` /
`revised_minor_improvements.json`): 3 occupations (Freshman A97, Begging Student D97, Nightworker C125)
+ 10 minors (Shaving Horse A48, Caravan, Carpenter's Bench B15, Walking Boots B22, Carriage Trip,
Small Potter's Oven, Recruitment, Witches' Dance Floor D25, Royal Wood, Guest Room). Some have explicit
user rulings behind them (Carpenter's Bench — goods-provenance cost gap; Witches' Dance Floor — a
field/occupation/major chimera). The true implementable remainder is therefore **264** (277 − 13),
which splits cleanly into **120 two-player-relevant** cards (dealt in the current game) + **144
three-plus-only** occupations (§2.B).

> **Data-vs-doc discrepancy worth reconciling.** Two of these `wontfix`-marked minors — **Shaving
> Horse A48** and **Walking Boots B22** — are still listed as merely *deferred* (blocked on a
> subsystem, not excluded) in `CARD_DEFERRED_PLANS.md`'s long tail. The card data and the deferred-plans
> doc disagree on whether they are permanent exclusions or future work; a quick user ruling would settle
> it. Until then this doc treats the `wontfix` marker as authoritative and keeps them out of the active
> build lists.

---

## 3. Implementation fixes & smaller gaps

The survivors of the old "Implementation Fixes" section. Its completed members (at-any-time food costs,
the trigger/hook system, CardStore, the first-batch audit) have moved to the Completed record below.

### A. Scythe Worker's optionality + the grant-vs-forced posture

The field-phase **choice machinery this once called for now exists** and is in use:
`PendingHarvestField` hosts a during-window decision when a choice-bearing take-modifier is eligible
(`register_take_modifier(..., variants_fn=…)`; Stable Manure, Scythe E73, Grain Thief). Two loose ends
remain: (1) **Scythe Worker itself** is still a mandatory auto fold-in by deliberate YAGNI — take-all
is strictly optimal with today's cards, and taking the extra grain depletes the field, so the
optionality only matters once a card rewards keeping grain in fields; migrating it is then a small
change (add `variants_fn`, the Stable-Manure shape), not new structure. (2) The broad "granted
sub-actions are optional" principle is built into the framework (decline seams, the named-action-grant
unfired-decline sweep) and enforced per-card by the standing verifier — but a discrete *retroactive
full-catalog* grant-vs-forced sweep is not a verifiably-completed one-time pass.

### B. Oven purchase implementation review

`PendingClayOven` / `PendingStoneOven` still exist unchanged (`pending.py:616`/`:632`, pushed from
`resolution.py` on `major_idx == 5/6`) — the review the old entry called for was never performed.
Decide whether the two oven pending types are the right abstraction or whether the oven-purchase flow
should collapse into the generic `CommitBuildMajor` path (they add two pending types for a narrow
use case). Low priority; a cleanup, not a blocker.

---

## 4. Additional game features / variants (non-card)

### A. 4-player variant

A real undertaking. Player-alternation already uses modular arithmetic that generalizes to N players,
but `setup`, the action board (3-/4-player games add accumulation spaces), the starting-player model,
and hand-dealing all assume 2 players. The concrete card list it needs is the ~144 "3+/4+"-only
occupations (§2.B). Long-term possibility, not near-term scope; but per the 2026-07-03 directive, give
the 3+/4+ cards real weight as design inputs when building shared card machinery *now*.

### B. Game replay viewer

A browser mode that loads a downloaded `.json` trace and steps through it move-by-move with the full
board rendered at each step. Only the *producing* side exists today (the web server emits a
self-contained seed+seats+moves trace; a headless Python `trace_replay` helper replays it for bug
repro). The in-browser step-through UI is unbuilt. Useful for post-game analysis and debugging without
running the server.

---

## 5. Card-game AI pipeline

Repeat the Phase-2 agent process (MCTS → NN → self-play) for the richer card game. **None of this is
started** — the web UI's Cards mode is human-vs-random or human-vs-human. Items are ordered by
dependency; the pieces interlock, so this is a program, not a checklist.

### A. Port the card game engine to C++

Extend the C++ twin (`cpp/`, today a faithful *Family-only* engine) to the full card game so card
self-play runs at C++ speed (~4×), as Family already does. The differential harness
(`tests/test_cpp_*.py`) keeps the port honest; follow the same staged-build + green-gate discipline.

**When, and the cost it locks in.** A *throughput* lever, not a correctness prerequisite: the card
game can self-play in pure Python first, and only needs C++ once data generation is the bottleneck
(the order the Family pipeline followed). The reason not to rush: today, card-only state and logic
never reach C++, so card changes stay "free" against the C++ gates and churn freely. The moment cards
live in C++, *every* future change to card rules / legality / scoring / encoder / state shape must be
re-ported to keep the gates green. **Port when the card system is stable enough that the ongoing
two-engine tax is worth the self-play speed** — not mid-development.

**Scope has grown.** The Python catalog is now 563 registry entries (was a small first batch when this
was first written), so stage 5 ("the card catalog in C++") is a much larger job and grows with the
Python catalog.

**Staged plan** (each gated green before the next, mirroring the Family port):
1. **Extend the differential harness to card states first** — teach the corpus generators to deal
   card-mode games (`setup_env(seed, card_pool=…)`) and play random card games; assert C++ matches
   Python over *card* states. The safety net every later stage leans on.
2. **State-model + serialization parity** — add card-only state to the C++ `GameState`/`PlayerState`
   (mode, private hands, played-card sets, scoped used-sets, CardStore, the card-new pending frames)
   and their canonical (de)serialization + hashing. Card-only fields are canonical-default-skipped, so
   Family JSON is unaffected; card states emit them and C++ must round-trip them in declaration order.
3. **Setup with a card pool** — mirror `setup_env`'s seeded hand deal exactly, so identical
   `(seed, pool)` yields a byte-identical start on both sides. (Now includes the draft path.)
4. **The firing infrastructure** — un-stub the host model: the card registries (triggers / autos /
   mandatory-with-choice), `apply_auto_effects`, before/after firing, the action-space host, and the
   phase hooks (start-of-round, the harvest/round-end/preparation timing ladders). Smoke-gate with one
   synthetic card before the catalog.
5. **The card catalog** — reimplement each card's cost / prerequisite / on-play / trigger / auto in
   C++, in batches by category, with the card-mode differential gate per batch. Scales with the card
   count (563 and growing).
6. **Mode-branched legality / resolution + card-play actions** — port the card-mode deltas in
   `legal_actions` / `step`, then run the full card-mode random-game differential to green.

**Boundary.** This port is *engine* parity only (`step`, `legal_actions`, scoring, canonical, hash over
card states). It stops short of the NN — the card encoding (5C) and ISMCTS (5E) sit above the engine. The
gates compare full ground-truth `GameState`s, so hidden hands don't complicate the engine
differential (determinization is an agent-layer concern).

### B. Augment the non-card AI to play with cards (bootstrap agent)

Before training a card NN, a playable card-game agent is needed to generate data. The most practical
bootstrap is the existing joint-trunk bot for non-card decisions + a simple heuristic (or random) for
card-play choices. Assess how much card-play quality matters for data diversity. Only the random
fallback exists today.

### C. Card encoding for the NN

The ~170-feature encoder has no representation of private hands or played cards. Decide how to encode
them — one-hot over the card vocabulary, a bag-of-features summary, or a learned card embedding — and
implement it as a new `ENCODING_VERSION` / encoder-registry row (`EncoderSpec` in `encoder.py`). The
choice shapes the NN architecture. (`DecisionSnapshot` stores the raw `GameState`, so trying an
encoder is a re-encode + retrain, never a data regen.)

### D. Training pipeline for the card game

Adapt the self-play loop — generation, joint shared-trunk training, C++ export, evaluation — to the
card game. The Family pipeline is the template; the additions are the card encoding (5C) and ISMCTS
(5E). Blocked on B, C, E.

### E. ISMCTS for hidden hand information

The card game adds **asymmetric** hidden information: each player's hand is private. (The Family game's
only hidden state — the round-card reveal order — is *symmetric*, lives in the `Environment`, and is
already handled correctly by explicit **chance nodes**; `HIDDEN_INFO_DESIGN.md` chose chance nodes
precisely because the symmetric case makes ISMCTS unnecessary.) The current MCTS handles that reveal
but assumes perfect information about hands, so it cannot play the card game correctly. Information Set
MCTS with determinization — sampling the opponent's possible hands at each node — is the standard
approach and remains unbuilt; `HIDDEN_INFO_DESIGN.md` documents it as the intended extension.

### F. Card-game heuristic for data bootstrapping

AlphaZero-style self-play needs *some* agent for the initial corpus (the heuristic ensemble served this
role for the Family game). Decide whether to write a lightweight card-play heuristic (evaluate each
playable card by its expected effect) or rely on the non-card bot + random card plays and accept
noisier initial data. Overlaps 5B.

---

## 6. Other

### A. Web UI fix punch list (mostly done)

`FRONTEND_FIXES.md` items **1–10 (the usability-critical set) are all landed**. Four low-priority
cosmetic items remain open (11–14): room-material cell coloring, stacked newborn tokens, a mid-game
full-score-breakdown modal, and readable labels for tuple-valued card-choice options (e.g. Bartering
Hut). None blocking; work through opportunistically.

### B. NN leaf-batching

The single largest remaining MCTS speedup per `SPEEDUPS.md` Part 2: batch multiple leaf evaluations
into one NN forward pass (with virtual loss) instead of one per leaf. Unbuilt in both Python and C++.
Deferred until sim budgets grow large enough that NN forward-pass cost dominates MCTS cost again.

### C. Prune stale "unbuilt" claims from the card docs (doc hygiene)

`CARD_ENGINE_IMPLEMENTATION.md` §8 and the bottom of `CARD_DEFERRED_PLANS.md` still describe as
"unbuilt / design only" several mechanisms that are now live: the before-scoring decision window
(Ox Skull), the before-round-start hook (`resource_analyzer` + the `before_round` window), the
`PendingRoundEnd` round-end ladder (`round_end.py`), and the after-feeding-phase conversions frame
(`farm_store` + the `after_feeding` window). A short pass to correct those sections would prevent
future sessions (and this doc's readers) from re-deferring built work.

---

## Completed since 2026-06-27 (removed from the active list)

Items from the previous revision that are now done, kept as a record so their absence above isn't
mistaken for an oversight:

- **1A — At-any-time food conversions for card costs.** ✅ Built as a produce-then-pay liquidation
  layer: goods/animals → food at the moment food is owed, surfaced as a Pareto frontier
  (`PendingFoodPayment` + `food_payment_frontier`, gated by `_liquidatable_to`/`_payable`;
  `CARD_ENGINE_IMPLEMENTATION.md` §5.3). The residual **non-food-good** conversion case is now §1.B.
- **1C — First-batch correctness audit** (Consultant, Priest, Stable Architect, Market Stall). ✅
  Superseded: those four are implemented, tested, and covered by the **catalog-wide** JSON-vs-
  compendium text audit (`COMPENDIUM_DIFFS_REPORT.md`). Per-card text-vs-code fidelity is now a
  standing process (`scripts/card_verify/` + the rules-fidelity verifier prompt), not a one-batch task.
- **1E — Trigger/hook system (Milestone 2).** ✅ The entire card firing system: the three firing kinds,
  before/after-action-space lifecycle hosts, scoped used-sets (`CARD_ENGINE_IMPLEMENTATION.md` §2;
  `agricola/cards/triggers.py`).
- **1F — CardStore (per-card persistent state).** ✅ Built (`agricola/state.py`; used across the
  catalog, incl. `interim_storage`).
- **1G — Deferred Milestone-1 cards.** ✅ Mostly done: **Mini Pasture, Shepherd's Crook, Acorns Basket**
  implemented; only **Organic Farmer** remains (now §1.I — end-game arrangement scoring).
- **2A — Draft mode.** ✅ Built end-to-end: `setup_env(seed, card_pool=…, draft=True)` → `Phase.DRAFT`
  → `CommitDraftPick`, the default Cards-mode hand setup, with a full pick-and-pass web UI + pass-and-
  play handoff overlay. (Loose end: no dedicated engine test for the draft path.)
- **Machinery that was "deferred/design-only" and has since landed:** the action/reward-replacement
  seam (Animal Catcher, Pet Lover); the minor on-play **play-variant** registry; **`alt_costs`** on
  `MinorSpec` (Baseboards, Barley Mill, Forest Stone); the generic **declinable granted-subaction**
  wrapper; the **animal-holder slot** subsystem (anonymous single-type, flexible, and per-species
  typed); the **family-growth housing-capacity** system; the **harvest / round-end / preparation
  timing-window ladders**; the **before-scoring decision window**; the **before-round-start hook**;
  the **after-feeding-phase conversions** frame; **card-as-action-space**; the **multi-plow** chain
  (Wheel / Double-Turn Plow); and most of `CARD_DEFERRED_PLANS.md` **Groups A and B** (only Established
  Person B88 and Scales B49 remain from those two groups — folded into §1.K / §2.A).
