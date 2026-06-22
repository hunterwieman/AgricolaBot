# CARD_SYSTEM_DESIGN.md

**Status: living design doc (Phase 3 — Cards). Decisions we've committed to + open questions, not a frozen spec.**

This is the design record for adding the full card system (Phase 3 in CLAUDE.md) to the
2-player engine. It captures the architecture decisions made in design discussion, the
implementation groupings for the base-game cards, and the open questions. Read alongside
`ENGINE_IMPLEMENTATION.md` §2 ("built with cards in mind") and §6 (card-trigger machinery),
`RULES.md` (the "Cards" section + "Trigger Timing"), and the card catalog under
`agricola/cards/data/` (+ `scripts/extract_card_data.py`, `scripts/card_workbook.py`).

The guiding constraint throughout: **card code is additive and fast-path-skipped when no card is
in play, so the Family game stays byte-identical and fast** — which is simultaneously the
performance guarantee and the thing that keeps the C++ differential gates green (see §11).

**Contents:** 0 Terminology · 1 Scope · 2 Setup/hands/pools · 3 Playing cards
(`PendingPlayOccupation`/`PendingPlayMinor`) · 4 Action-space hook (`PendingActionSpace`) ·
5 Firing architecture · 6 Scoped state & reset model · 7 New mechanisms · 8 Legality & multi-card
interaction · 9 Per-card storage & Grocer · 10 Implementation groups & build order · 11 Performance
& Family/full split · 12 C++ strategy · 13 Open questions · 14 Revisited implementation choices
(folds IMPLEMENTATION_CHOICES.md) · 15 The conversion-affordability problem (open, §15.1–15.7).

---

## 0. Terminology

These three words are used precisely throughout this doc. Keeping them distinct matters because a
single attachment point can carry effects of both firing kinds.

- **Hook** — a *seam in the engine's control flow* where card logic can attach: after a renovate,
  the harvest field phase, before/after using an action space, on playing a card, etc. A hook
  says *where/when*; it is agnostic to what attaches, and one hook can host many cards.
- **Trigger** — the **agent-chosen** firing path: the `FireTrigger` action + `TRIGGERS` registry,
  surfaced in `legal_actions` as an optional choice the player *decides* whether/how to take
  (e.g. Potter Ceramics, Mushroom Collector's optional swap, Sheep Walker, Frame Builder's
  substitution).
- **Automatic effect** — the **mandatory, choice-free** firing path: an effect applied directly
  at a hook with no `FireTrigger` and no entry in `legal_actions` (e.g. Loom's harvest food,
  Wood Cutter's +1 wood, Clay Hut Builder, Milk Jug's "you get 3 food").

So: **a hook is the attachment point; what attaches is either a trigger (chosen) or an automatic
effect (mandatory).** The two correspond to two firing paths — `FireTrigger` enumeration vs. a
direct helper call at the hook — and a single hook can carry both (the Forest hook hosts Wood
Cutter's automatic +1 wood *and* Mushroom Collector's choosable swap). A third recurring flavor,
**"grants a sub-action,"** is a hook whose effect *pushes an existing primitive pending* (Bake
Bread, plow) that the player then optionally uses — mechanically a trigger that composes a
primitive.

---

## 1. Scope

- **Revised Edition**, base game + the **Artifex, Bubulcus, Corbarius, Dulcinaria, Consul
  Dirigens** expansions. **2-player.** Occupations + minor improvements. The 10 major
  improvements are already implemented in the base engine; the 24 Consul Dirigens Parent cards
  are out of scope.
- The catalog lives in `agricola/cards/data/revised_occupations.json` (336) and
  `revised_minor_improvements.json` (336), each carrying a `status` field
  (`implemented` / `todo` / `wontfix`) browsable/filterable in `revised_cards.xlsx`.
- **Build order:** occupations first, then minors (minors mostly reuse the occupation
  machinery — see §10).

---

## 2. Setup, hands, and card pools

- **Private hands.** Each player is dealt **7 occupations + 7 minor improvements** into a
  **hidden hand**. This is the faithful model and introduces persistent *asymmetric* hidden
  information (see §13 — it's the project's biggest downstream consequence, on the agent side).
- **Hidden info lives in the `Environment`**, not `GameState` (the invariant from
  `HIDDEN_INFO_DESIGN.md`). `observe(state, env, i)` finally becomes non-identity: it splices in
  player *i*'s own hand and masks the opponent's. Setup deals the hands into the env.
- **Configurable card pools (decision).** Setup takes an **arbitrary crafted collection** of
  occupations + minors and deals the 7-each hands **uniformly** from that pool — any chosen subset
  of the catalog, no hard-coded deck.
- **The Family game is a distinct variant, not "the card game with an empty pool."** Beyond having
  no hand cards, it flips action-space rules: Side Job is *available*, Meeting Place is a
  *food-accumulation* space (not a play-a-minor opportunity), and the 2-player extra tile is unused
  (RULES.md Setup). So "Family vs card game" is a **mode** carrying rule deltas beyond the hand,
  not just an empty pool — see §11, which treats the mode as an explicit setup config.

---

## 3. Playing cards — `PendingPlayOccupation` / `PendingPlayMinor`

Playing a card is a **reusable, multi-caller pending** (the reusable sub-action-primitive pattern,
ENGINE_IMPLEMENTATION.md §3), named to match `PendingBuildMajor`:

- **`PendingPlayOccupation`** — pushed by Lessons (the occupation action space), by Scholar's
  round-start ability, and by any future card granting "play an occupation."
- **`PendingPlayMinor`** — pushed whenever the player gets to play a minor improvement. The main
  route is the *play-an-improvement* sub-action (which lets you play a major **or** a minor), offered
  from two spaces — the **Major/Minor Improvement** space and **House Redevelopment**. Minors are
  also played via **Basic Wish for Children**, **Meeting Place**, Scholar, and card grants. (There is
  no standalone "minor improvement" space — a minor is always one branch of a larger action.)

What they carry / how they work:

- **Card choice** is enumerated over the player's **private hand** — the playable cards whose
  **prerequisites** are met. This is where the hidden-hand model first reaches the enumerator
  (it reads the player's hand from `observe`).
- **Caller-supplied cost** (the cost-bucket pattern): Lessons uses the occupation-cost
  progression; Scholar pushes a flat 1-food cost. The occupation-cost progression is a pure
  function of **`len(p.occupations)`** — the frozenset already holds every occupation played by
  any method, so it *is* the lifetime counter (no separate field). Minor cost is the card's
  printed `cost`.
- **Prerequisite check** gates which hand cards are playable (RULES.md "Prerequisite vs.
  Condition" — prereq = met to PLAY; condition = met to USE).
- **On-play effect** is the pending's "primary effect," wrapped in **before/after phases** (the
  same shape as `PendingActionSpace`, §4) — because these pendings are the *play-hooks* hosting:
  Paper Maker (a **trigger** — "you may pay 1 wood…" before playing each occupation), Bread Paddle
  (**grants a sub-action** — a bonus Bake Bread per occupation played), Junk Room (an **automatic
  effect** — +1 food after building any improvement).
- **Passing minors** (deck numbers ≤ 9: A2/A5/A9/B2/B8 in base): when played, you execute the
  card's immediate effect and then **pass the card to the next player** instead of keeping it in
  your tableau — it stays in circulation indefinitely. `PendingPlayMinor`'s resolution handles the
  pass-and-keep-in-circulation for these.

---

## 4. The action-space hook — `PendingActionSpace`

Atomic spaces become non-atomic (push a parent pending) **only when a card needs to fire on
them** — the documented plan (ENGINE_IMPLEMENTATION.md §2 "built with cards in mind" / §6). One
**generic** pending hosts the hook:

- **`PendingActionSpace`** carries the **concrete `space_id`** of the space used. It does *not*
  add a new field for this — the id is read off the existing `initiated_by_id` provenance
  (`"space:forest"` → a `space_id` property strips the prefix), honoring "don't store two
  representations of one fact." Cards decide their granularity in their `eligibility_fn` (the per-card
  *firing* predicate, §5 — distinct from the *hosting* test `_should_host_space` below): specific
  (`space_id == "forest"`) or category (`space_id in WOOD_ACCUMULATION_SPACES`).
- **before / after phases.** Lifecycle: push frame (before) → before-firings → apply the space's
  **primary effect** → after-firings → Stop/pop. The before→after transition is a **`Proceed`**
  action that *applies the primary effect and flips the phase*; it is only surfaced when a
  before-**trigger** (a choice) is actually eligible — otherwise the engine auto-advances and
  applies any automatic before-effects, so the common path costs nothing. `Stop` retains its
  meaning (end the action) in the after phase — `Proceed` is a distinct action precisely so a
  before-phase `Stop` can't skip the primary effect.

### Conditional push (keep the card-less path free)

Push the host pending **only when the placing/affected player owns a card that could fire on this
space** — otherwise take today's atomic fast path. The test is **ownership, not eligibility**
(eligibility for *after*-firing effects can only be true post-primary-effect, e.g. Mushroom
Collector needs the wood it's about to gain; an eligibility check pre-primary would
false-negative). Read "could fire on this space" **conservatively — a card that could fire here in
*some* scenario, not one that can fire *right now*.** That's what `SPACE_HOOK_CARDS` encodes (built
once at registration from each card's declared spaces); a "can it fire right now" test would risk
silently dropping the host because we mis-judged some card interaction at the moment of the check.
Implementation:

```python
SPACE_HOOK_CARDS: dict[space_id, frozenset[card_id]]   # built at registration

def _should_host_space(state, space_id, acting_player) -> bool:
    cards = SPACE_HOOK_CARDS.get(space_id, frozenset())
    for p in state.players:                 # ALL players — opponent-fired effects (Milk Jug) fire on your turn
        if (p.occupations | p.minor_improvements) & cards:
            return True
    return False
```

- Tag each entry **own-action vs any-player-action** so an opponent's *self*-firing card doesn't
  force a host on your turn (precision) and an *opponent*-firing card does.
- Family game: empty hands → empty intersection → atomic fast path → **byte-identical to today**.
- Over-pushing is safe: if ownership says "maybe" but nothing actually fires, the before/after
  phases produce nothing → forced-singleton `Proceed`/`Stop`, auto-skipped.

---

## 5. Firing architecture (triggers, automatic effects, hooks)

- **How a card registers.** Each card supplies **its own** two functions and attaches them to a
  hook (named by an event string) via `register(event, card_id, eligibility_fn, apply_fn)`
  (`cards/triggers.py`):
  - its **eligibility predicate** `eligibility_fn(state, player_idx, triggers_resolved) -> bool`
    answers "can *this card's* effect fire at this hook right now?" — it may inspect the top
    pending (`state.pending_stack[-1]`), e.g. to read which space is in use;
  - its **effect** `apply_fn(state, player_idx) -> GameState` applies the card and returns the new
    state.

  Registration wires the card into the **trigger** path: `legal_actions` offers a `FireTrigger` for
  each owned card whose eligibility holds and that hasn't fired yet. **Automatic effects** don't go
  through this — they're applied directly at the hook, never offered as a `FireTrigger`.
- **Timing ruling (RULES.md "Trigger Timing"):** a bare "each time you use [space]" fires in the
  **before** phase (before the space's effect); cards that fire after say so explicitly
  ("immediately after…", "at the end of that turn") → **after** phase.
- **Trigger vs automatic effect.** A choice ("you may…") → a **trigger** surfaced as a
  `FireTrigger` (Potter, Mushroom Collector). A mandatory, parameterless effect ("you get…") →
  an **automatic effect** applied as a system transition at the hook (no `FireTrigger`, no
  `legal_actions` clutter). A single hook can carry both kinds.
- **Hook event keying.** Each hook is named by an *event string* that cards register against. Use a
  single coarse `before_action_space` / `after_action_space` event (rather than a separate event per
  space); each card filters by `space_id` in its eligibility predicate. (Don't confuse this event
  *key* with the before/after *phase* of the `PendingActionSpace` frame in §4 — the phase is the
  state the frame is in; the event is what cards register against.) Per-space precision for the
  *push* decision comes from `SPACE_HOOK_CARDS`, not from event keying.
- **Opponent-action hooks** (Milk Jug, and expansion Casual Worker / shared-space toll cards):
  the host pending fires the owner's effect on the *opponent's* action — automatic for Milk Jug
  ("you get 3 food"), or a **trigger** routed to the owner as *their* decision for Casual Worker
  ("choose food or a stable"). Route by frame `player_idx` (the decider rule), never hard-code
  the active player. The opponent-firing path is **deferred to the first such card (Milk Jug,
  when we reach base minors)**; the structure (own-vs-any index + `player_idx` routing) is kept
  open now so it slots in additively.

---

## 6. Scoped state & the reset model

Cards track "have I fired/used this already?" with a few **scoped sets of card-ids on
`PlayerState`** — one set per *reset scope* (per-turn, per-round, per-game, …) — rather than a
boolean per card. A card's id being in its scope's set means "spent for this scope," and clearing
that set resets every card of that scope at once (O(1); no per-card bookkeeping).

**The reset must happen *at* the scope boundary, not inside a resolver.** Each set is cleared the
moment its scope turns over — when the `phase` field changes, or a new turn begins — by the code
that performs that transition, never tucked inside the resolver that runs next. (A resolver can be
re-entered, or run after another effect has already acted, so resetting there risks double-clearing
or a stale set.)

| Scope | Field | Reset when | Example |
|---|---|---|---|
| per-action | frame `triggers_resolved` | frame pops | Potter Ceramics, Frame Builder |
| per-turn | `used_this_turn` (new, `PlayerState`) | `_advance_current_player` **and** entry to WORK | Farmyard Manure (expansion) |
| per-round | `used_this_round` (new, `PlayerState`) | entry to PREPARATION | Clay Carrier (once/round) |
| per-harvest | `harvest_conversions_used` | entry to HARVEST_FIELD | joinery/pottery/basketmaker |
| per-game | `fired_once` (new, `PlayerState`) | never | Clay Hut Builder, Manservant |

**Implementation:** a small helper `_clear(state, field)` sets the named frozenset to empty on
**every** player. Call it inline at each scope boundary, right next to the transition that triggers
it: at the `fast_replace(phase=…)` site for the phase-keyed scopes (`used_this_round` on entering
PREPARATION, `harvest_conversions_used` on entering HARVEST_FIELD), and — for the per-turn scope
(`used_this_turn`) — at the top of `_advance_current_player` *and* on WORK entry. Clearing *every*
player's set (not just the active player's) is required so an off-your-turn firing — your Casual
Worker building a stable during the opponent's turn → your Farmyard Manure — sees a fresh latch.
(A single `_enter_phase` wrapper owning "set phase + reset" was considered and rejected: its shared
logic is one `fast_replace` line and the per-turn reset isn't even phase-keyed, so it would be a
dispatch switch with little payoff over inline `_clear` calls at the few boundaries.)

- **"In a turn" gate:** per-turn cards' eligibility includes `state.phase == WORK` (we're ~98%
  confident `phase == WORK ⟺ in a turn`; verify no WORK-phase step sits outside a placement when
  implementing). Off-turn builds (Groom's prep-phase stable) thus don't fire per-turn cards.
- **Why the turn-reset is at the boundary, not at `_apply_place_worker`:** a turn may open with
  at-any-time actions *before* the worker is placed (Grocer), which must see fresh per-turn
  budgets — so the reset belongs at the turn boundary (advance / phase→WORK), not at placement.

### One-shot conditional automatic effects (level + latch)

For "once you live in / no longer live in [material]" cards (Clay Hut Builder, Manservant): a
card declares a `condition_fn(state, p) -> bool`; a helper `_fire_ready_one_shots(state, p)`
checks each owned one-shot card's condition and, if it holds and `card_id not in fired_once`,
fires (these are **automatic effects** — mandatory) and latches. Level-triggered + latch (not
edge detection) so it also catches the on-play-while-already-true case. Hooks (call sites):
**after a renovate** (the only house-material changer) and **on card-play**.

### Cumulative counters (Claypipe — deferred)

Claypipe ("food in return-home if you gained ≥7 building resources that work phase") needs a
genuinely **cumulative integer counter** (distinct from the set latches): a per-player
work-phase resource-acquisition count that increments on each building-resource gain, resets on
WORK entry, and is checked at the WORK→RETURN_HOME shift (an automatic effect at that hook). **Implementation deferred** — the open part is how the counter is fed
(instrumenting every resource-gain site without taxing the card-less path) and whether it
generalizes to other cards.

---

## 7. New mechanisms

- **Deferred rewards on round spaces** — *reuse and generalize the existing `future_resources`
  field*, which already implements this mechanism for the **Well** (a per-player `tuple[Resources, ...]`,
  one entry per round, collected at round start). Generalize it to a per-round `FutureReward`
  (the dataclass anticipated in IMPLEMENTATION_CHOICES.md item 4 — see §14):
  - `resources: Resources` + `animals: Animals`, both **additive** (so repeated placers like
    Herring Pot stack on the same round) — collected at round start: add the resources, then
    **accommodate** the animals (which may surface the overflow/Pareto decision).
  - `effect_card_ids: frozenset[str]` — card hooks for *non-object* deferred effects, fired at
    round start.

  Covers the goods cards (Pond Hut, Wall Builder, Clay Hut Builder, Manservant, Strawberry Patch,
  Sack Cart, Thick Forest, Large Greenhouse), the **animal** case (Acorns Basket → boar), and the
  **exotic** case via the effect hook: **Handplow**'s deferred hook pushes `PendingPlow` at the
  scheduled round's start — a round-start decision composing the existing plow primitive, not a
  bespoke effect. (Card-id membership in `effect_card_ids` suffices for the known exotic cards,
  which each schedule once; revisit if an exotic deferred effect ever needs multiplicity.)
- **Start-of-round phase — a `PendingPreparation` frame.** For "at the start of each round
  you can…" cards (Plow Driver, Groom, Scholar are **triggers**; Small-scale Farmer / Childless /
  Scullery are **automatic effects**), push a `PendingPreparation` at round entry — the same pattern
  the harvest uses (`PendingHarvestFeed` / `PendingHarvestBreed`): a pending whose presence hosts the
  round-start agent decisions, resolved and popped before WORK begins. Round-scoped budgets use
  `used_this_round`.
- **Harvest-field hook — a `PendingHarvestField` frame.** The FIELD phase is mechanical today
  (`_resolve_harvest_field` just takes 1 crop per planted field); field-phase cards need a decision
  point *before* that, so push a `PendingHarvestField` (mirroring the feed/breed pendings). It hosts
  the field-phase income cards — Loom, Butter Churn, Three-Field Rotation, Scythe Worker (all
  **automatic effects**) — **and Clearing Spade**: moving a crop into an empty field *before*
  "take 1 from each field" runs nets an extra harvested crop, so Clearing Spade wants to fire here.
  (It's a preserve-optionality card whose beneficial preemptive moments are hard to fully
  enumerate — the §15 theme.)
- **Capacity / static modifiers.** Permanent passive rule changes (no firing at all — they alter
  derived quantities or legality): animal/pasture capacity (Animal Tamer, Drinking Trough — these
  touch the accommodation frontier *and its cache key*), person capacity (Caravan), placement
  rules (Lasso, Sleeping Corner), field-like cards (Beanfield).
- **At-any-time conversions** (always **triggers** — optional). Per the optionality principle,
  bundled into the decision points where their proceeds are needed, not surfaced standalone
  (Sheep Walker, Hard Porcelain, Clearing Spade).
- **Board geometry (deferred).** Brook ("4 spaces above Fishing") and Sweep ("card left of the
  most-recently-placed") need a **static position/adjacency map** over the 2-player board piece
  (the contiguous piece; the left jigsaw is 4-player-only and out of scope). The exact adjacency
  sets get pinned against the board when those cards are implemented.

---

## 8. Legality & multi-card interaction

The Potter Ceramics pattern is an **OR-list of independent eligibility-broadening predicates**
(`BAKE_BREAD_ELIGIBILITY_EXTENSIONS` + a trigger doing the mid-action effect). It composes fine
for cards that *independently* make an action legal, but **not** for cards whose effects *chain*
— e.g. determining whether a renovate is legal with Grocer + Frame Builder + Conservator in play,
where affordability becomes "is there a sequence of bounded card conversions that makes the cost
payable?" — a small reachability search, not a disjunction.

**Decision: defer the general affordability/legality machinery** (the "speculative-legality" idea,
ENGINE_IMPLEMENTATION.md §6: apply owned-card effects to a hypothetical state, then check the
predicate). The tempting path — *lift* the harvest-feeding frontier (`harvest_feed_frontier` /
`food_payment`) from "pay food" to "pay a build cost" — turns out **not** to transfer cleanly once
conversion cards add bidirectional exchange; that whole problem, and exactly why the feeding
frontier breaks, is written up as **§15**. Build it when a couple of conversion cards are actually
on the docket.

**To avoid silent failures, every card whose effect can change a legality/affordability check is
flagged here** — when the deferred machinery is built, these are its test cases:

- **Cost modifiers** (affordability must account for them): *Occupations* — Carpenter,
  Master Bricklayer, Frame Builder, Conservator (path), Hedge Keeper. *Minors* — Lumber Mill,
  Carpenter's Parlor, Rammed Clay (pay fences with clay).
- **Conversions that change what you can afford:** *Occupations* — Sheep Walker, Grocer.
  *Minors* — Hard Porcelain, Basket.
- **Eligibility broadeners / path changers** (Potter-style): Conservator (renovate path),
  plus any future "do X without paying / even if you couldn't normally."
- **Capacity changes that gate sub-action legality:** Animal Tamer, Drinking Trough, Caravan
  (affect how many animals/people can be accommodated, which gates breeding/overflow decisions).

---

## 9. Per-card instance storage & Grocer (deferred)

Some cards carry per-instance state beyond a fired-flag — most notably **Grocer** (a fixed goods
stack on the card you buy from over time) and Tutor (which only needs an on-play **snapshot int**
of `len(occupations)`, scored as `final − snapshot`). The general per-card-state mechanism
(a `dict[card_id, <state>]` on `PlayerState`, or similar) is **deferred — to be designed
together with Grocer in a dedicated discussion** (per maintainer request). Tutor doesn't need it
(snapshot int suffices). The far harder *legality/affordability* half of the Grocer problem — how
conversion cards make `can_renovate` / `can_bake` a reachability search — is written up as its own
open problem in **§15**.

---

## 10. Implementation groups & build order

Cards are grouped by the **shared hook** each needs (build the hook once, then the cards are
small). Difficulty is driven by *which new machinery a card forces*, not its surface text. Where
a hook group mixes firing kinds, each card is tagged **(auto)** = automatic effect, **(trig)** =
agent-chosen trigger, **(sub)** = grants a sub-action.

### Base occupations (34 cards, players "1+")

1. **On-play one-shots** *(foundation: occupation-play action + on-play effect)* — Consultant,
   Priest, Roof Ballaster.
2. **Scoring terms** *(`scoring.py`)* — Stable Architect, Organic Farmer, Tutor (snapshot int).
3. **Cost / path modifiers** — Carpenter, Master Bricklayer, Frame Builder (trig), Conservator,
   Hedge Keeper.
4. **Action-space hook** *(`PendingActionSpace`)* — Wood Cutter (auto), Geologist (auto),
   Seasonal Worker (auto; veg choice from r6 = trig); Assistant Tiller (sub: plow),
   Cottager (sub: build/renovate), Oven Firing Boy (sub: Bake Bread); Mushroom Collector (trig),
   Firewood Collector (auto, after).
5. **Build/renovate hook** — Roughcaster (auto).
6. **Deferred goods on round spaces** — Wall Builder, Clay Hut Builder, Manservant (all auto;
   the latter two are one-shot conditionals).
7. **Start-of-round phase** — Small-scale Farmer (auto), Childless (auto, with a crop choice);
   Plow Driver (trig), Groom (trig); Scholar (trig — plays a card; hardest).
8. **Per-card store / at-any-time** — Grocer (deferred), Sheep Walker (trig).
9. **Standalone** — Animal Tamer (capacity static), Scythe Worker (auto harvest-field),
   Adoptive Parents (trig — worker/family dynamics), Paper Maker (trig — on the play-occupation
   hook).

### Base minors (48 cards) — mostly reuse the occupation hooks

- **Reuse Group 1 (on-play):** Shifting Cultivation, Clay Embankment, Young Animal Market,
  Big Country, Mini Pasture, Market Stall, Mantlepiece (also locks renovation).
- **Reuse Group 2 (conditional scoring):** Manger, Wool Blankets, Bottles (flat 4 VP +
  variable play cost). *Flat printed VPs on other cards are a trivial scoring sum, not scoring
  logic.*
- **Reuse Group 3 (cost-mod):** Lumber Mill, Carpenter's Parlor, Rammed Clay.
- **Reuse Group 4 (action-space hook):** Corn Scoop (auto), Stone Tongs (auto), Canoe (auto),
  Loam Pit (auto), Pitchfork (auto, conditional on Farmland occupied), Brook (auto,
  board-geometry), Herring Pot (auto, schedules deferred goods); Basket (trig); Threshing Board
  (sub: Bake Bread), Moldboard Plow (sub: plow, twice/game).
- **Reuse Group 5 (build/play hooks):** Shepherd's Crook (auto, fence hook), Junk Room (auto,
  improvement-play hook), Mining Hammer (sub, renovate hook), Bread Paddle (sub, occupation-play
  hook).
- **Reuse Group 6 (deferred goods):** Pond Hut, Large Greenhouse, Strawberry Patch, Sack Cart,
  Thick Forest, Acorns Basket, Handplow (scheduled plow).
- **Reuse Group 7 (start-of-round):** Scullery (auto).
- **Reuse Group 8 (at-any-time):** Clearing Spade (trig), Hard Porcelain (trig).
- **Static/passive modifiers:** Drinking Trough, Caravan, Lasso, Beanfield, Sleeping Corner.
- **Harvest-field hook (new):** Loom (auto), Butter Churn (auto), Three-Field Rotation (auto).
- **Opponent-action hook (new):** Milk Jug (auto — you get food on any player's Cattle Market use).
- **Cumulative / round-gated automatic effects:** Claypipe (auto; cumulative counter — §6),
  Dutch Windmill (auto; a per-Bake-Bread effect gated on `round_number ∈ {5,8,10,12,14}` —
  stateless, easy).

Minor-specific net-new lift: the **minor-play action + prerequisites + passing-minors**
(cross-cutting), the **harvest-field hook**, the **first opponent-action hook** (Milk Jug), and
Claypipe's cumulative counter. Everything else is assembly on the occupation foundation.

---

## 11. Performance & the Family/full split

**One engine, no parallel codebase.** The card system is **additive hooks** on the existing engine;
they self-disable via cheap O(1) guards (empty-ownership / empty-set checks), so when no relevant
card is in play the existing paths run unchanged. But the **Family game is a configured *variant*,
not merely "cards off"** (§2): it also flips a few action-space rules — Side Job available, Meeting
Place as food-accumulation, no 2-player tile. So the engine is parameterized by a **mode** (Family
vs. card game — a setup-level config) that sets those rule-delta spaces *and* whether hands are
dealt; the mode is *not* inferred from "are the hands empty?". Within a mode, the card hooks stay
inert when no relevant card is owned. Either way, there's no parallel codebase to diverge.

The governing principle: **card machinery must be fast-path-skipped, not merely present, when no
relevant card is in play, and every guard must be O(1).** Cost scales with *how many cards are
relevant right now* (gated by ownership + the per-event/per-space registries), never how many
cards exist. The per-turn wipe is an empty-check, not an unconditional rebuild; `_should_host_space`
is a set intersection that's empty for empty hands; trigger enumeration only runs when a host
pending is on the stack.

This is the *same* property as the C++-gate maintenance invariant: **"cards-disabled ≡ today's
engine, byte-identical"** keeps the Family differential gates green *and* is the Family-speed
guarantee. The card-vs-Family **mode** is an explicit setup config (it has to be — the Meeting Place
/ Side Job rule-deltas don't follow from the hand); the per-*card* hook gating, by contrast, is
ownership-derived (empty hands → inert). Add a cached "any cards in play" bit on `GameState` only if
profiling later shows the guards themselves are hot.

---

## 12. C++ strategy

**Python first, port to C++ separately later.** Cards must stay additive so the Family C++
differential gates stay green throughout Python card development (the card logic is simply
untested-against-C++ until the port). Cards-disabled must equal today's engine exactly. The C++
port of the card system happens as its own effort once the Python card engine is stable.

---

## 13. Open questions

- **Asymmetric hidden information (agent side — the big one).** Private hands give the *agent*
  persistent asymmetric hidden info for the first time (the round-card reveal was symmetric).
  MCTS needs determinization / information-set search over the opponent's hidden hand; the NN
  encoder must encode *your* hand and hide the opponent's; the policy gains a "which card from
  hand" (pointer-shaped) decision. The *engine* is ready (`observe`); this is squarely on the
  agent/training critical path. **Important, tracked, not yet relevant** — flagged so it isn't
  forgotten behind "engine's handled."
- **Grocer + the general per-card-state mechanism** (§9) — to be designed in a dedicated
  discussion.
- **The affordability/legality machinery** (§8; the hard core is the open problem in §15) —
  deferred; flagged cards are its test set.
- **Board-geometry adjacency** (§7) — exact "above Fishing" / "left of" sets pinned at
  implementation.
- **Cumulative-counter generalization** (§6, Claypipe) — whether a shared "resources gained this
  work phase" counter serves multiple cards, and how to feed it cheaply.
- **Deck-pool composition** — resolved as a configurable crafted pool (§2); the default pool for
  training/eval is still to be chosen.
- **`phase == WORK ⟺ in a turn`** (§6) — confirm there is no WORK-phase step outside a worker
  placement before the per-turn "in a turn" gate relies on it (~98% confident).

---

## 14. Revisited engine-implementation choices (folds IMPLEMENTATION_CHOICES.md)

Each item from `IMPLEMENTATION_CHOICES.md`, resolved against the *in-scope* cards (occupations
with `players == "1+"` + all minors, base + 5 expansions — verified by a catalog scan). Status:
**✓ decided** · **◐ decide-as-we-build-base** (a base card forces it) · **⊕ deferred-to-expansion**
(in scope, but no base card needs it — design at the first expansion card that does) ·
**○ not card-gated** · **⊘ to-revisit** (open discussion, not locked).

- **1. Worker `(int, int)` count tuple** — ⊕ (deferred to expansion; pending confirmation no base
  card needs it). Two sub-cases, only one of which needs new storage:
    - *State-derivable, no storage* — "Nth person you placed this round" (Catcher, Plow Hero, Wheel
      Plow) is derivable from the placement count (`people_total − people_home` at placement time);
      Steam Machine ("last space used is accumulation") and Bassinet ("a space holding exactly one
      person", `sum(workers)`) read public state. None need stored order.
    - *Needs a stored placement log* — only cards that *return or move the specific worker you placed
      first* (Henpecked Husband, Basket Chair, Seatmate) need to know *which space* was first → a
      per-player ordered placement log for the round (not the per-space tuple). These appear to be
      *expansion*-only, so no base card needs stored order — defer the log to the first such expansion
      card. The count tuple stays for everything else.
- **2. Animals as totals only** — ⊕. Base needs no change: Animal Tamer and Shepherd's Crook are
  capacity bumps / gains, not location tracking. *Expansion* cards make cards/tiles hold animals
  (Feedyard, Stockyard, Wildlife Reserve, Cattle Farm, Stable Master, Mud Patch, Sheep Agent,
  Livestock Feeder) → per-location/container animal tracking, added at the first such card.
- **3. String space IDs vs. enum** — ○ not card-gated. **Decided: leave plain strings.** They're
  typo-prone (a misspelled space ID is a silent miss / runtime `KeyError`, not a compile error) and
  give no autocomplete, but the engine runs fine on them today and hardening isn't worth the churn —
  especially since the canonical-JSON / C++ boundary serializes space IDs as strings anyway. Revisit
  only if typos in card modules actually start biting.
- **4. `future_resources` → `FutureReward`** — ◐ decided (see §7). Acorns Basket (boar) forces
  animals; Handplow (deferred plow) forces an effect hook. Implement the dataclass: per-round
  `FutureReward(resources, animals, effect_card_ids)`, generalizing the field the Well already uses.
- **5. Newborn tracking** — ◐ decide when building **Adoptive Parents** (base, occ Group 9): the
  offspring it grants must be markable as **not a newborn**. The scan confirms **no in-scope card
  changes the 2-food adult feeding cost** — so feeding cost is untouched; only newborn
  *classification* needs the exception (the other matches are Family-Growth *timing* cards, all
  expansion).
- **6. `_apply_worker_placement` private** — ○ not card-gated. (`_apply_worker_placement` is the
  internal helper that does the bookkeeping when a worker is placed — bump the space's worker count,
  decrement the player's `people_home`; the item was only ever about whether it lives privately in
  `resolution.py` or as a shared helper.) Stale — non-atomic handlers already need it — so promote it
  to a shared helper whenever convenient. Not a card concern; here only because §14 folds *every*
  IMPLEMENTATION_CHOICES item.

  *(`IMPLEMENTATION_CHOICES.md` has no item 7 — its numbering jumps 6 → 8.)*
- **8. `_can_build_room` hardcoded cost** — ◐ decide as we build the base cost-modifiers: Carpenter,
  Carpenter's Parlor, Lumber Mill (+ Conservator / Master Bricklayer / Frame Builder). Route
  build / renovate / fence / major costs through card-aware helpers (the cost-bucket work + the §8
  affordability concern; these cards are already in §8's flagged list).

- **9. `people_home < 1` one-worker guard** — ◐. The guard sits at the top of `legal_placements` and
  returns "no placements" when the player has no worker at home — enforcing the Family rule of
  *exactly one worker placed per turn*. **Extra-placement** cards break that assumption: **Lasso**
  ("place two people in a row"), Adoptive Parents, and expansion cards (Inner Districts Director,
  Nightworker, Canal Boatman, …) let you take a second placement, so the turn/placement logic must
  allow it. *(Sleeping Corner is a **different** relaxation — placing on an **occupied** space — which
  touches the occupancy check `_is_available`, not this guard; I'd wrongly lumped it here.)*
- **10. Card-extension pattern for legality helpers** — ⊘ **to revisit** (NOT locked). The pattern
  exists for Potter Ceramics (`BAKE_BREAD_ELIGIBILITY_EXTENSIONS`), but the maintainer wants to
  understand it before we commit to generalizing it — an open discussion item alongside Grocer and
  the affordability machinery (§8/§9), not a settled decision.
- **11. Compound card interactions** — ✓ deferred (§8), and the scan **confirms it's in-scope, not
  hypothetical**: Pan Baker (A122) + Potter Ceramics (D66) is the canonical case, both implementable,
  and on-placement gainers (Wood Cutter, Geologist, Seasonal Worker, Firewood Collector) can enable
  follow-on sub-actions. The deferred speculative-legality machinery (§8) is its fix.
- **12. `triggers_resolved` frame-scoped + per-card budgets on `PlayerState`** — ✓ decided; this is
  exactly the scoped used-set model (§6).
- **13. Sub-phase decomposition of phase resolvers** — ◐ decide now (base needs it): the
  start-of-round abilities (Group 7 — Plow Driver, Groom, Scholar, Childless, Small-scale Farmer,
  Scullery) and the return-home effects (Claypipe). Split PREPARATION / RETURN_HOME into sub-phases,
  integrated with the §6 reset model (inline `_clear` at each boundary), the `PendingPreparation`
  frame (§7), and the feed/breed pending pattern.
- **14. Hidden-info tuned for the symmetric case** — ✓ the asymmetric private-hand consequence is the
  headline open item (§13): ISMCTS / determinization, a real `observe`, encoder hand features.
  Tracked, not yet relevant.

---

## 15. The conversion-affordability problem (Grocer / Clay Carrier / Emissary) — OPEN, UNRESOLVED

This is the hardest open problem in the card system, and **no approach is chosen** — this section
records the problem and the options for a future session. It does **not** block the easy base
cards (on-play, scoring, simple cost-mods have no conversions, so legality stays today's simple
check). It gates **Grocer, Clay Carrier, Emissary** and the conversion-dependent affordability of
`can_renovate` / `can_bake` / `can_afford_room` / `can_play_card` whenever those cards are present.

### 15.1 The problem: complex card interactions make legality hard

A small set of cards let the player **pay food/goods for resources** — Grocer (1 food → the top
good of a fixed stack), Clay Carrier (2 food → 2 clay, once per round), Emissary (place a
*different* good → 1 stone) — and they interact with a wider conversion ecosystem: Hard Porcelain
(2/3/4 clay → 1/2/3 stone), Sheep Walker (1 sheep → boar/veg/stone), Cooking Hearth (veg/animals →
food at-any-time), Frame Builder (a cost-modifier: 2 stone → 1 wood when building), and the base
1:1 grain/veg → food conversion (no card needed). Verbatim card effects are embedded in §15.2.

By the **preserve-optionality** principle (Foundations), these conversions must be *deferred to
the moment their proceeds are spent* — never performed early, never surfaced as standalone
actions. The consequence: a legality predicate like `can_renovate` **cannot read the literal
supply**. It must answer *"is the cost reachable through some sequence of the player's available
conversions?"* — a reachability question over the closure of conversions.

### 15.2 Worked example — a legal renovation that takes a long conversion chain

**Verified `can_renovate → yes`.** Re-traced against the cards' real text (don't re-derive card
effects from memory — read them; the effects are embedded below for exactly that reason).

**State.** Supply: **1 food, 1 sheep**. House: **clay, 6 rooms** → renovate-to-stone costs
**6 stone + 1 reed**; with Frame Builder, **4 stone + 1 wood + 1 reed**.

**Cards in play (verbatim effects):**
- **Grocer** (occ A102): *"Pile the following goods on this card (wood, grain, reed, stone,
  vegetable, clay, reed, vegetable). At any time, you can buy the top good for 1 food."* (stack
  consumed top-first — wood first → … → vegetable last).
- **Clay Carrier** (occ D122, Dulcinaria): *"…At any time, but only once per round, you can buy
  2 clay for 2 food."* (its on-play "get 2 clay" is already spent in this state).
- **Emissary** (occ D124, Dulcinaria): *"At any time, you can place a good from your supply on
  this card to get 1 stone. You must place different goods on this card. (Food is also a good.)"*
  — it already holds 1 food + 1 clay, so the next placed good must be a *third, different* type.
- **Frame Builder** (occ A123): *"Each time you build a room/renovate, but only once per
  room/action, you can replace exactly 2 clay or 2 stone with 1 wood."* (renovate = one action →
  one 2-stone→1-wood swap).
- **Hard Porcelain** (minor B80): *"At any time, you can exchange 2/3/4 clay for 1/2/3 stone."*
- **Sheep Walker** (occ B104): *"At any time, you can exchange 1 sheep for either 1 wild boar,
  1 vegetable, or 1 stone."*
- **Cooking Hearth** (major): at any time veg→3 food; plus the *base* rule grain/veg → 1 food at
  1:1 with no card (RULES.md).

**The chain** (each step shows the running **food** balance; start: 1 food, 1 sheep):
1. sheep → veg (Sheep Walker), cook veg → 3 food (Hearth) ⇒ **food 4**.
2. spend all 4 on Grocer ⇒ +wood, grain, reed, stone (stack's top 4); **food 0**.
3. grain → 1 food (base 1:1), spend it on Grocer ⇒ +veg (5th); **food 0**.
4. cook veg → 3 food, spend all 3 on Grocer ⇒ +clay, reed, veg (6th–8th); **food 0**. Hold:
   1 wood, 1 clay, 2 reed, 1 stone, 1 veg.
5. cook veg → 3 food, spend 2 on Clay Carrier ⇒ +2 clay; **food 1**. Hold: 1 wood, 3 clay, 2 reed,
   1 stone.
6. 3 clay → 2 stone (Hard Porcelain); place 1 reed on Emissary → 1 stone. Hold: **1 wood, 4 stone,
   1 reed** (+ food 1).
7. Frame Builder swaps 2 stone → 1 wood ⇒ pay 4 stone + 1 wood + 1 reed ⇒ **renovate** (food 1
   left).

A non-obvious **yes** mobilizing seven cards over a ~7-step chain — including a base-card money
pump (buy a vegetable from Grocer for 1 food, cook it for 3 = **net +2 food**) bounded only by
Grocer's finite stack. Naive affordability bounds call it **no**; it is **yes**.

### 15.3 Why it's genuinely hard

- **Value-gaining cycles bounded only by finite stock.** Grocer sells a vegetable for 1 food;
  Cooking Hearth turns a vegetable into 3 food — a net **+2 food** pump (base cards!). So
  termination of any search rests on **finite inventory/budgets** (Grocer's 8-good stack, Clay
  Carrier once/round, one sheep), *not* on conversions being lossless. "No positive cycle" is
  false here.
- **The feeding frontier does not transfer.** The one place the engine already solves "pay a cost
  using conversions" — harvest feeding (`harvest_feed_frontier` / `food_payment`) — is tractable
  **only because its conversion graph is a DAG into a single sink** (goods → food, one-way). That
  acyclicity is what makes componentwise dominance over upstream goods *sound*, and that soundness
  is what makes the frontier cheap. Conversion cards add **reverse edges** (Grocer: food → goods),
  **cross edges** (Hard Porcelain: clay → stone), and **cycles** (Grocer+Hearth) → the graph is
  cyclic → componentwise dominance is **unsound**.
- **The dominance-failure witness.** Compare state A `{4 food, full Grocer stack}` with B
  `{3 food, 1 wood, stack-minus-the-top-wood}`. A → B in one Grocer-pop, and B can never reach A
  (you can't un-buy the wood or recover the food), so A strictly dominates B. But a componentwise
  check sees *A has less wood than B* and calls them **incomparable**, keeping both. Because
  food + a fuller stack can *manufacture* the wood B already cashed out, resources are **fungible**,
  and sound dominance here ≈ reachability — i.e. the cheap prune and the hard problem have
  collapsed into one. This is the crux: the pruning that makes feeding fast is gone.
- **Stateful/sequential machines blow up the state.** Most conversions are *stateless rate
  operators* (Hard Porcelain, Sheep Walker, Hearth) and stay feeding-frontier-shaped. **Grocer's
  ordered stack** is a sequential machine — each pop changes what's available next — so the search
  state must carry the stack position. Grocer is the card that turns a clean DP into a real search.
- **Correctness stakes.** An **under**-approximate legality silently *hides* legal moves; an
  **over**-approximate one *offers illegal* ones. Both break the engine's "`legal_actions` is
  exact" contract. A bound is acceptable only if **provably sound in the needed direction**.

### 15.4 What object do we actually need?

Not the full reachable frontier (overkill). Two cost-*specific* objects:
- **Legality** → `Feasibility(C)`: a yes/no reachability query, "can I reach a bundle ≥ C?" — no
  frontier, early-exits on first success.
- **Resolution** → `PaymentFrontier(C)`: the Pareto-non-dominated *leftover* bundles after paying
  C (the feeding frontier generalized to a build cost) — needed because *what you keep* matters
  downstream, exactly as at feeding.

They share one bounded search; legality just early-exits. And the search belongs in a **dedicated
solver, not as MCTS moves**: the conversion subproblem is deterministic, single-agent, local (no
opponent, no chance) — precisely what tree search is bad at — so surfacing conversions as tree
plies would waste depth and force off-distribution mid-conversion leaf evaluations.

### 15.5 Proposed approaches and their downsides (none chosen)

1. **Bounded cost-directed reachability search** (with dominance pruning). *Downside:* dominance is
   **unsound over fungible resources** (15.3, A-vs-B) → may fail to prune → blowup; Grocer's
   stateful stack enlarges the state; it's a search-inside-legality evaluated per action / per MCTS
   node (mitigations — ownership-gating, projection-keyed memoization, Agricola's small integer
   counts — are plausible but **unproven**, especially for the Grocer case).
2. **Let the player use Grocer / conversions at will** (surface them as actions). *Upside:* legality
   becomes trivially correct (no search; the game tree does it). *Downside:* **violates
   preserve-optionality**; bloats the action space + policy head; deepens MCTS with conversion
   plies; off-distribution mid-conversion leaf evals. (Counter: a strong NN policy might prune the
   weirdness, and preserve-optionality is partly a *tractability* device — it shrinks the action set
   — not purely a correctness rule; its correctness content (a rational agent never converts early,
   so the *value* is unchanged) still holds. But the deterministic-local argument says even the NN
   should prefer a solver.)
3. **Sound-but-incomplete legality** (depth-bound conversion chains to depth *k*). *Upside:* cheap,
   bounded, kills the niche-completeness fear. *Downside:* **fidelity loss** — the exotic 7-step
   renovation is ruled illegal; the agent can't find lines a strong human would. A tunable knob
   trading fidelity for tractability.
4. **Permissive legality + commit-time resolution + abort.** Offer plausibly-affordable actions
   cheaply; run the real search only at *commit*, down one path; void/abort if unpayable. *Downside:*
   breaks "`legal_actions` is exact"; renovate has no natural begging-style abort; MCTS sees
   possibly-illegal actions.
5. **Sound conservative over-approximation, exact search only in the contested band.** A true upper
   bound (treat conversions as freely available, ignore that they compete for inputs) cheaply
   rejects the easy NOs; the full search runs only when borderline. *Downside:* still needs the
   exact search sometimes; computing a *true* over-approx under the pumps requires the finite-stock
   bound.
6. **Decompose acyclic vs. cyclic core.** Handle the one-way-to-sink part with the feeding-frontier
   (sound dominance there); treat the food⇌goods exchange core (Grocer/Hearth, bounded by finite
   stack) as a separate small subproblem. *Downside:* **unproven** — gluing the two parts may
   reintroduce the fungibility blowup; may be a mirage.
7. **`wontfix` the intractable cards.** Don't implement the cards that create intractable
   interactions. *Downside:* cuts content for engine convenience.

### 15.6 Requirements any solution must meet

- **Sound** in the needed direction: never offers an illegal action and never hides a legal one —
  *or* knowingly, explicitly relaxes this (e.g. the depth-bound fidelity cut, approach 3).
- **Cheap enough for the MCTS hot path** (legality is evaluated at every node).
- **General** — handles whatever conversions are present without per-combination code (the
  niche-interaction risk; a hand-tuned search that misses a combo is a silent correctness bug).
- **Pure / deterministic** — a function of state only (the engine is functional).
- Either **honors preserve-optionality**, or (approach 2) explicitly and deliberately relaxes it.

### 15.7 Status

**Unresolved — the designated topic of the dedicated "Grocer session."** The §15.2 worked example
— now verified against the cards' real text — is the first test fixture: a `can_renovate → yes`
that naive bounds call no.
