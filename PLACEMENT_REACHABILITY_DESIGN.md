# Placement legality as reachability — the design of record

> **Status (updated 2026-07-09): ON HOLD — solution sketches only, not a plan of record.**
> The user is designing the legality approach themselves; the problem statement of record
> is **`LEGALITY_HARD_CASES.md`** (same directory), and nothing below is approved or
> implemented. Kept because the architecture analysis and phase-ladder reasoning may be
> reusable once the user's design lands.
> Evidence base: `CENSUS_AT_ANY_TIME.md`, `CENSUS_REACTIVE_TRIGGERS.md`,
> `CENSUS_COST_IMPOSITION.md` (same directory — full-catalog sweeps). The reveal-order
> card cluster (Brook, Master Workman, Knapper, Sweep, Silokeeper, Outrider, Pioneer,
> Legworker, Bean Counter, Wholesaler, Pig Stalker, Task Artisan, Water Worker) remains
> the intended first implementation batch, gated on that design.

## 1. The problem

The engine decides whether a worker placement is legal with a per-space predicate over the
current state (`legality.py` — `FAMILY_GAME_LEGALITY` / `CARD_GAME_LEGALITY`, dispatched by
`legal_placements`). Several predicates are **resource-gated**: Fencing requires an
affordable pasture commit, the two renovation spaces require `_can_renovate`, Grain
Utilization requires grain (or a bake source), card-mode Lessons requires a *payable*
occupation, the improvement spaces require an affordable build/play. In the Family game this
is exactly right: what the player holds **is** what the player can spend.

Cards break the identity between *holdings* and *spendable resources* in three compounding
ways:

1. **Placement grants.** "Each time (before) you use [space], you get X" — the goods arrive
   after the placement decision but before the space's mandatory work, so they can pay for
   that work. A 0-clay player placing on House Redevelopment while owning Sweep (whose
   target is that space this round) IS legal by the rules; the predicate says no.
2. **At-any-time cards** (31 in the catalog, all currently unimplemented — see census). The
   player can inject conversions, purchases, and even builds/renovations *between any two
   decisions*, including between a placement and its work. Stable Cleaner ("at any time,
   build stables for 1 wood + 1 food each, no person") can create resources' worth of board
   state mid-turn.
3. **Reactive cards** (153 in the catalog, 47 implemented). Effects that fire automatically
   off state changes *however caused* — Potter's Yard pays clay/food when any farmyard cell
   becomes used; Barrow Pusher (implemented) pays clay+food per new field tile from any
   source. Any mutation made by (1) or (2) can trigger these, and their payouts compound.

The worked counterexample (user, 2026-07-06): a before-placement food grant + Stable
Cleaner + Potter's Yard. Place on House Redevelopment with zero clay → the grant supplies
food → Stable Cleaner builds a stable mid-turn (1 wood + 1 food) → the stable turns a cell
used → Potter's Yard pays 1 clay → the mandatory renovation is now affordable. The
placement was legal, and no per-family patch (space-scoped grant bundles, transform
previews) sees it, because the enabling resources come from cards not attached to the
placement at all.

**The correct definition.** A placement is legal iff there exists a finite sequence of
player-controlled choices from the post-placement state — firing available triggers and
options, exercising at-any-time capabilities, choosing payments — under which the
placement's mandatory work completes. Legality is *reachability over the player's option
closure*, and the current predicates are the special case where the closure contains no
moves. Mandatory-vs-optional matters for **execution** (what must happen), not for
**legality** (what could) — the player controls the choices either way.

## 2. What the censuses established

Both sweeps covered all 840 cards; full tables in the census files.

- **The at-any-time family is closed**: exactly 31 cards, all carrying the literal phrase,
  none implemented. Everything else in the catalog anchors to a named space, phase, or
  event. Planning against a fixed list is possible; the family cannot ambush us.
- **The difficulty core is ~10 at-any-time cards** — food→build-resource converters
  (several drawing from depleting card piles: Grocer, Seed Trader, Muddy Puddles) and
  free-timing farmyard/board mutators (Stable Cleaner, Trowel, Stone House Reconstruction,
  Mason, Master Builder, Piggy Bank, Roll-Over Plow, Changeover, Clearing Spade).
- **Reactive cards chain**: ~60 of the 153 have payloads that feed affordability or mutate
  the farmyard, i.e. can trigger further reactions. The canonical reactor (Potter's Yard)
  needs a `cell-became-used` event that does not exist; other members need the
  deliberately-absent any-source goods-gained / newborns-gained events (§8 of
  `CARD_ENGINE_IMPLEMENTATION.md`).
- **Cross-pair net-positive resource cycles exist but are designer-bounded** (Clay Carrier
  + Large Pottery nets +2 food/round, cut by Clay Carrier's once-per-round). Boundedness
  comes from once-per-X latches, depleting piles, and budgets — all *state the engine
  already holds or will hold in CardStore*, so a closure search terminates by consuming
  them, never by trusting an analytical argument.
- **One inverted case**: Fishing Net *taxes* the opponent's Fishing placement (they must
  first pay the owner 1 food). A cost, not a grant — placement legality must then also
  check payability of mandatory costs. Grants extend legality (an OR); costs restrict it
  (an AND). The two need separate seams.

## 3. The architecture: one oracle, closure by simulation

One function answers every "could the player complete X?" question:

```
can_complete(state, player_idx, goal) -> bool
    # goal: a predicate over state, e.g. "the printed placement predicate for space S"
    #       or "this host's mandatory work is affordable"
```

### A worked call — how it runs and how cost cards compose

Round 8 of a Cards game. House Redevelopment was revealed in round 5; the round-8 card was
just turned up, so Sweep's target ("the card left of the most recently placed") is the
round-5 slot — House Redevelopment. The player owns **Sweep** and **Frame Builder**, lives
in a 3-room wood house, holds 1 wood + 1 reed + **0 clay**. Renovating costs 3 clay + 1
reed.

*Without the oracle:* the printed predicate calls `_can_renovate` → `can_pay` → the cost
pipeline, which builds the payment menu — the printed base (3 clay + 1 reed) plus Frame
Builder's conversion variant (1 clay + 1 wood + 1 reed). At 0 clay neither is affordable →
False → the space is not offered. Wrong by the rules: placing there fires Sweep before the
work, and 2 clay arrives in time to pay.

*With the oracle:* the predicate said no, so the wrapper asks
`can_complete(state, p, goal = that same predicate)`:

1. **Gather the free moves available here.** Phase 1: only the grants that will certainly
   fire on this placement — Sweep's registration answers +2 clay. (Later phases add moves:
   optional triggers, at-any-time options, pile buys.)
2. **Apply a move to get a successor state** — not by adjusting numbers in an
   oracle-private model, but by producing the state the effect itself would produce. In
   Phase 1 the effects ARE pure goods additions, so `fast_replace` is provably identical;
   from Phase 3 an edge literally runs the card's apply function through the engine, so
   anything registered on the resulting events fires inside the hypothetical too.
3. **Ask the goal at the successor.** The same predicate runs again, rebuilding the
   payment menu from 2 clay + 1 wood + 1 reed: the base is still unpayable, **Frame
   Builder's variant is payable** → True.
4. First success ends the search; the space is offered. Exhaustion → stays off the list.

That is the composition rule in miniature: **the oracle never re-implements affordability —
it changes the input state and re-asks the engine's own question, and every cost card
lives inside that question.** Formula cards seeding alternative bases, reductions, ordered
conversion chains, a minor's `alt_costs`/`cost_fn`, the food-liquidation layer, free-fence
budgets — all already sit inside `effective_payments`/`can_pay`/`_payable` as pure
functions of state. A card that *gives goods* and a card that *changes what goods are
needed* never get pairwise code; they meet inside the predicate call (Sweep×Frame Builder
above; Outrider×Millwright — the grain matters only because Millwright's conversion is in
the fold; Brook×any-food-cost-minor via liquidation).

### The search, when more than one move exists

Phase 1 barely searches (mandatory grants → one path, × Pioneer's four choices). With a
richer option set the oracle walks a tree: at each node, list the currently-available free
moves; apply one through the real machinery; check the goal; recurse. A pile buy (Grocer)
changes both the pile and the food supply, which changes which moves exist next — the
successor state carries all of that because the real apply functions recorded it.

- **Memoization** on a projection of state (resources + relevant CardStore slices +
  farmyard hash once mutating moves exist): two orders reaching the same holdings collapse.
- **Termination is inherited, not assumed**: every move consumes something the successor
  records — goods stocks fall, piles shorten, once-per-X latches set — so paths cannot
  cycle. A depth/node cap exists only as a safety valve and **asserts loudly** if ever hit
  (a silent cap would report "illegal" for a legal placement — a rules deviation; no
  silent caps, ever).
- **Why edges must run through the engine**: modeling Stable Cleaner oracle-side as
  "−1 wood −1 food +1 stable" would require the oracle to also know every card that
  *reacts* to a stable appearing — and each new reactive card would silently invalidate
  it. Stepping the engine inverts the maintenance burden: when Phase 3 gives the engine a
  cell-became-used event and Potter's Yard registers on it, the Stable-Cleaner edge fires
  Potter's Yard inside the hypothetical with zero oracle changes.

Two scope notes: `goal` is a parameter — placement legality passes the printed predicate;
the mid-host stranding guard passes "this host's mandatory work is still affordable." And
the oracle only ever answers, never acts: on a yes, the player places, the grant genuinely
fires through the ordinary machinery, and the ordinary enumerators see real goods — nothing
downstream consults the oracle.

Algebraic shortcuts (summing goods bundles, cross-products over choices) are **provable
special cases** of this search, usable exactly when no reaction can fire and no option
interacts — which is a checkable property of the *implemented* card set, not a hope. Phase
1 below is such a case, and its correctness condition is stated as an invariant that later
phases must re-verify before widening.

**Where the oracle hooks:**

- `legal_placements` — the comprehension's predicate call becomes
  `predicate(state) or can_complete(...)` (only evaluated when the printed predicate says
  no and the player owns relevant cards; Family mode short-circuits on empty registries —
  byte-identical, zero cost).
- The **sub-action gates** inside host enumerators (`_can_renovate` at ChooseSubAction
  time, etc.) — the same question one level down; same oracle, later phase.
- The **AND-side** (mandatory costs like Fishing Net's tax): a separate conjunct
  `can_pay_mandatory_costs(...)` at the same chokepoints. Never expressed through the
  OR-seam.

**What this deliberately does not decide:** where at-any-time options surface as *real
actions* during execution. That is the action-space blowup problem (Foundations'
"preserving optionality" bundling doctrine, §8's end-of-turn co-dependence), it shapes MCTS
branching, and it needs its own design round with the user. The oracle only ever answers
hypotheticals; the execution surface is a separate, co-designed decision. Precedent that a
narrow surface can work: the stone-house start-of-round gates (Plow Driver, Groom, Scholar)
bundle a recurring option into one phase host.

## 4. The phase ladder

Each phase widens the oracle's edge set; each states the invariant that made the previous
phase exact, and what re-verification the widening requires.

**Phase 1 (this session) — certain, space-scoped, goods-valued grants.**
Registry: `register_placement_grant_preview(card_id, fn, kind)` where
`fn(state, idx, space_id) -> tuple[Resources, ...]` returns the *alternative* bundles the
card will grant before that space's work (singleton for autos; four `resource+food`
bundles for Pioneer's mandatory choice). `kind ∈ {"mandatory", "optional"}` is in the
schema from day one; Phase 1 registers only mandatory cards (all this cluster needs).
Combiner: base = sum of mandatory auto bundles; × alternatives per choice card; legal iff
any combination satisfies the printed predicate on a `fast_replace`d state.
**Exactness invariant: a goods bundle applied via `fast_replace` is exact iff no registered
effect reacts to resource gains.** True today — the engine has no goods-gained event, and
the census confirms every implemented acquisition-reactive card is space-take-scoped
(Portmonger reads the space's take, not pool deltas). A test asserts the relevant event
registries stay empty, so Phase 3 work trips it deliberately rather than silently.
Companion execution fixes, shipped together: the **uniform mandatory-trigger gate** (a
mandatory before-trigger withholds the host's work options on every host kind — today only
the atomic host gates; delegating hosts, Proceed-hosts, and the markets do not), and the
**stranding guard on choice options** evaluated existentially against the *other*
still-unfired mandatory grants (so two grant cards that jointly enable the work don't
empty each other's option lists). Collection is **owner-agnostic** (an opponent-owned card
that pays the actor is visible) — one loop bound, cheap now.

**Phase 2 — optional triggers as legality sources** (user direction 2026-07-06: this is
the end goal; "optional might also combine with mandatory to make a space legal").
Optional entries contribute `{skip, bundle}` factors to the same combiner — or,
equivalently, become edges in the small search. Execution needs no new mechanism: work
options are only offered when affordable, and mandatory-work hosts have no exit until the
work is done, so a player who placed counting on an optional trigger finds `FireTrigger`
as the only legal action — the trigger becomes required de facto, which is the rules-
correct reading of "you chose this line by placing." Requires a dead-end audit: a player
must not be able to fire some *other* trigger that consumes the enabling trigger's input
mid-host (the existing stranding-guard family, re-checked when the first such card lands).

**Phase 3 — non-goods payloads and cascades.** Grants whose payload mutates the farmyard
(granted plow/build/room), animal grants (liquidatable via cooking), and reactions. The
enabling work is **engine events, not oracle features**: `cell-became-used`,
any-source goods-gained, any-source newborns-gained — each built as an ordinary auto event
family because *execution* needs them anyway (Potter's Yard, Kindling Gatherer, Dung
Collector are unimplementable without them). Once effects apply through those events, the
oracle's edges inherit cascades for free, and bundle algebra is retired for transform
edges (`fast_replace` is exactly what Phase 1's invariant no longer licenses).

**Phase 4 — the at-any-time family.** Two coupled designs, done with the user: the
**execution surface** (where the 31 cards' options appear as actions — per-decision-point
bundling? a turn-boundary window? — co-dependent with §8's end-of-turn question) and the
**full closure oracle** (at-any-time edges available at every node). Includes the
Grocer-class question: goods-on-card affordability where Pareto dominance is unsound
(`CARD_SYSTEM_DESIGN.md` §15). Piles are ≤8 items, so **exact bounded search over pile
states** looks feasible and is the default proposal; the user has suggested
bound/approximate may be acceptable — if any approximation is adopted, its *direction*
must be ruled per case (an over-approximation offers placements that might dead-end; an
under-approximation silently removes legal actions — rules-fidelity treats these very
differently).

## 4b. What actually forces the tree — the necessity census (2026-07-06)

Full engine-step tree search is forced only by **chains**: a free move that mutates
non-pool state, whose consequence (a goods-paying reactor, or a state-gated predicate)
changes affordability. Single cards do not force it — Stable Cleaner alone only *spends*
and is legality-inert; Potter's Yard alone is an ordinary auto in real execution; Grocer's
pile is 9 enumerable prefix-buys (its §15 dominance problem afflicts the execution-side
payment frontier, not the legality existential). Partitioning every legality-relevant card:

- **Tier A — force the tree (all unimplemented).** Mutators: `stable_cleaner`,
  `piggy_bank`, `mason`, `master_builder`, `trowel`, `stone_house_reconstruction`,
  `roll_over_plow`, `changeover`, `clearing_spade`, `sower`, `muddy_puddles`. Amplifiers:
  `potters_yard`, `farmstead` (unimplemented) — plus already-implemented reactors that
  would fire inside a hypothetical once any mutator exists (`barrow_pusher`,
  `rocky_terrain`, `junk_room`, `skillful_renovator`, `roughcaster`). Implementing
  reactors is always safe; **implementing any mutator is what makes the tree necessary.**
- **Tier B — iterated pool algebra, no engine stepping** (the `expand_conversions` idiom,
  widened): `kettle`, `hard_porcelain`, `clay_firer`, `large_pottery`,
  `basketmakers_wife`, `emissary`, `sheep_walker`, `clay_carrier`, `oriental_fireplace`,
  `earth_oven`, `boar_spear`, `crudit` (food half), `seed_trader`, `grocer`. Exact and
  sound while nothing reacts to pool changes (the Phase-1 invariant).
- **Tier C — at-any-time but legality-inert**: `stable_yard`, `land_consolidation`,
  `pen_builder`, `salter`, `whisky_distiller`, `potters_market` (scheduled outputs arrive
  too late for the current placement), `reed_seller` (ruled out 2026-07-06).
- **Tier 0/1 — bundle seam** (Phases 1–2): the reveal-order cluster, `bookshelf`,
  `patron`, and kin.

**Consequence:** tree search is necessary for zero implemented cards today; Phases 1–2
plus a Tier-B closure cover everything else in the catalog. Building the tree is
equivalent to deciding to implement Tier A's mutators — a card-by-card user decision that
can shrink the machinery need, potentially to nothing (the Reed Seller precedent).

**The guard-side class — spending before-triggers (user-identified 2026-07-09).** The
mirror of the grants: a before-trigger whose cost competes with the host's mandatory work
(Writing Desk — "play 1 additional occupation for 2 food" on Lessons, whose mandatory
play then costs the 1-food ramp). These never force a tree (single step) but force the
stranding guard to be a **post-fire simulation**, not componentwise checks on the current
state. **Writing Desk's implemented guard has this hole today** (checks ≥2 hand
occupations + the 2 food payable now; never re-checks the mandatory ramp after −2 food):
with exactly 2 food and nothing liquidatable, firing reaches an empty-action dead state.
Phase-1 fix, sharing Pioneer's guard helper: eligibility = mandatory work completable on
the post-fire state, shipped as **combined payability** (grant cost + mandatory cost
through `_payable_occupation` — exact for fungible food since liquidation overshoot
banks). Known temporary narrowness, pending user ruling: a fire enabled only by the
granted occupation's own on-play income is under-offered until Phase 3's
engine-step edges make the per-occupation simulation natural.

**The pattern generalized (2026-07-09).** The class is *(spending option) × (costly
mandatory work on the same host)*, and both factors are enumerable. Costly-mandatory
hosts today: Lessons (ramp), the Major/Minor Improvement space (the composite's mandatory
child is a costed build-or-play), the two renovation spaces, Fencing, Grain Utilization
(grain for sow/bake — the Beer Stein sub-action guards already police this). Free-mandatory
hosts (Farmland, Day Laborer, accumulation takes) are immune only until a **tax card**
prices them — and the census (`CENSUS_COST_IMPOSITION.md`, 2026-07-09) found the family is
**8 cards, none implemented**: one owner self-tax on free mandatory work (**Dwelling Mound
C37** — 1 food per new field tile, payable before placing, which will give plowing a cost
chokepoint the day it lands), two opponent-taxed base spaces (Fishing Net C51, Forest
Guardian B138 — the AND-side seam's first members, both player-to-player transfers), three
card-created toll spaces (Chapel/Forest Inn/Alchemists Lab — already in the shared-space
defer family), and two recurring-upkeep cards (Credit A54 — round-end family; Animal
Catcher C168). So today's guards need only the costly-mandatory host list; the immunity of
the free hosts is a checked fact, not an assumption. Consequences: (1) guards compute the mandatory
work's cost **through the payability chokepoints** (taxes flow in automatically), never
per-host constants; (2) guards are a **post-fire chokepoint re-run**, never componentwise
printed-cost checks — cost-modifier conversions widen which goods matter (spending 1 wood
can destroy Frame Builder's `2 clay → 1 wood` renovate variant); (3) **Phase-1 audit item:**
every implemented spending trigger on a costly-mandatory host is re-checked for
before-timing + guard completeness under conversion interplay (Writing Desk failed;
Beer Stein/Baking Sheet believed correct; Bucksaw and Loppers timings to verify).

**Open rules question (user to answer): forbid vs fizzle.** The guard approach forbids a
self-stranding fire at the offer. The alternative reading — Agricola's "do as much as you
can" convention — would allow the fire and let an unpayable mandatory obligation lapse (a
"fizzle" path: mandatory work skipped when impossible). Different machinery AND different
games (under fizzle, Writing Desk at exactly 2 food legally dodges the Lessons play).
Fix shape blocked on this ruling; the working assumption is forbid.

**MCTS dead-line pruning (evaluated 2026-07-09, user proposal): adopted as a backstop,
rejected as the correctness story.** In the future card-game agent, an expanded node with
zero legal actions is a proven dead line — score it a loss and search routes around it;
build this into the ISMCTS agent as defense-in-depth against residual guard gaps. It
cannot replace guards: it protects only the bot (a web-UI human still hits the raw dead
state, and non-terminal ⇒ non-empty `legal_actions` is load-bearing for replay/tests/
self-play data), it addresses only over-offering (never the under-offering half — grants
wrongly denied), and attribution is lossy when the fatal choice sits plies above the
empty leaf.

## 5. Soundness conditions (the registration contract)

1. **Player-controlled availability** — every edge is a choice the player can actually
   make at that point; certainty (mandatory) vs option changes execution, not legality.
2. **Fire-time exactness** — a preview's bundles/transforms equal what the effect will
   actually grant, evaluated at-fire-time; eligibility must be invariant across the
   placement instant (nothing here may read "is this space occupied").
3. **Independence, or search** — the bundle combiner assumes grants don't couple (one
   card's eligibility/amount reading another's output). Coupled cards either defer or
   force the sequential-search path. (Census: no implemented pair couples today.)
4. **Costs are AND-side** — a mandatory cost (Fishing Net) never enters the OR-seam.
5. **Owner-agnostic collection** — scan both players' tableaus; the fn decides whom it
   pays.
6. **No silent caps** — any bound that would change an answer asserts loudly.

## 6. What this supersedes, and what it does not touch

- `CARD_ENGINE_IMPLEMENTATION.md` §8's "no speculative placement-time legality" line is
  **rewritten when Phase 1 lands**: placement legality is existential over
  player-controlled grants; the mandatory slice is implemented, the rest is this ladder.
  ("Speculative" was a defer marker, not a rules position.)
- The Foundations bundling doctrine (never surface standalone conversions to the *agent*)
  is untouched — it governs the execution surface (Phase 4's open half), not the legality
  oracle, which is a hidden hypothetical.
- The C++ twin is unaffected until a card-game port exists; everything here is
  Family-inert behind empty registries.

## 7. Rulings needed from the user

- **R1 (Phase 1 go/no-go):** the preview seam as specced + the mandatory-gate fix + the
  reveal-order cluster.
- **R2 (approximation policy):** confirm "exact search, loud assert on safety caps" as the
  default; any per-card approximation (Grocer-class bounding) gets its own dated ruling
  with an explicit over/under direction.
- **R3 (Phase 4 sequencing):** the at-any-time execution surface is a separate design
  round — nothing in the family gets implemented until then.
- **Settled:** Reed Seller (D159) permanently out of scope — user ruling 2026-07-06.
