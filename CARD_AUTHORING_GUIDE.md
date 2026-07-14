# Card Authoring Guide

A practical, opinionated guide for a future coding session implementing **more Agricola
cards** (occupations and minor improvements). It tells you how to *read* a card, how to
*classify* it against the machinery already built, how to *fit it in*, and — most
importantly — **which cards to defer and ask the user about rather than guess.**

This guide assumes the engine and card infrastructure described in
`CARD_SYSTEM_DESIGN.md` (the design), `CARD_IMPLEMENTATION_PLAN.md` (the build plan +
current status), `SUBACTION_HOOK_REFACTOR.md` and `SPACE_HOST_REFACTOR.md` (the host
lifecycle), and `ENGINE_IMPLEMENTATION.md` §2/§6 (the pending stack + card-trigger
machinery). Read this first; reach for those for depth.

---

## 0. The cardinal rule: when in doubt, DEFER and ASK

**The single most important instruction in this document.** If you cannot confidently map
a card onto the existing machinery — its timing is ambiguous, it needs a mechanism that
does not exist yet, it interacts with another card in a way you are unsure about, or you
find yourself inventing new infrastructure to make it fit — **do not guess. Defer the
card and ask the user.**

The user understands Agricola's rules, rulings, and card interactions far better than a
coding agent does (they play at a world-class level). A card implemented on a plausible-
but-wrong reading is *worse* than an unimplemented card: it passes its tests, looks
finished, and is silently wrong in ways that only surface in real play. Several cards in
this project were deliberately deferred for exactly this reason (see §9).

Concretely:
- **Prefer deferring to guessing.** A deferred card costs nothing; a subtly-wrong card
  costs trust and is hard to find later.
- **Ask the user about timing, optionality, and interactions you are unsure of** — these
  are precisely the things a coding agent gets wrong and an expert gets right.
- **Ask before inventing new engine machinery for one card.** New infrastructure is a
  design decision, not a coding task; surface it.
- When you defer, record *why* (which mechanism is missing, or which ruling is unclear)
  in `CARD_DEFERRED_PLANS.md`, so the next session and the user can pick it up.
- **When delegating card work to a subagent, inject the load-bearing rulings from §2 into
  the prompt — and impress on them that precise rule-adherence IS the task, not a nicety.**

### 0.1 Rules fidelity is absolute — "I can't see a problem" is not authority

The cardinal rule above covers *doubt*. This section covers the more dangerous case:
**confidence**. A 2026-07-02 audit found that every rules deviation that reached the
codebase was committed by an agent who was *sure* its deviation was harmless — an invented
"the engine does not force accommodation on gains" convention that mis-scored games; a
during-feed implementation of an after-feeding card that created a food-laundering exploit;
a "field phase" card moved to the feed phase on a neutrality argument that was wrong (it
let Joinery food pay a cost that per the printed timing must be paid before feeding). The
project owner could construct a concrete problem for **every single one** of these
"harmless" deviations. The lesson is general: you cannot see the interaction space of 840
cards; the neutrality of a timing or mechanism shift is not something you are in a position
to establish.

Therefore:

- **You do not have the authority to implement a card differently from its printed text.**
  Not with a neutrality argument, not by citing another card as precedent, not
  "temporarily." If the machinery cannot express the printed behavior exactly, the card is
  a DEFER. A neutrality argument is a reason to *ask*, never a reason to *proceed*.
- **Docstrings may not self-ratify.** Phrases like "the established, accepted
  approximation," "behaviorally neutral," or "the same accepted home as X" are prohibited
  unless the docstring cites an **explicit user ruling with a date** ("user ruling
  2026-06-30: …"). An unattributed deviation claim in a docstring is itself a defer signal
  — and future sessions must treat existing ones as unratified, not as precedent.
- **This rule propagates to subagents verbatim.** Subagents drift toward convenience: they
  are handed a card and an implement instruction, and when the machinery doesn't fit they
  invent a bridge rather than fail their task. When you delegate implementation or triage,
  the prompt must state this section's rule explicitly ("if the printed behavior doesn't
  fit the machinery exactly, return the card as DEFERRED — do not approximate; an
  approximation you can justify is still a defer"), and the verify stage must check
  text-vs-implementation fidelity as its primary criterion, flagging *any* timing or
  mechanism delta regardless of the implementing agent's justification. An instruction not
  passed down is an instruction not given.
- **If you discover a past deviation, surface it to the user immediately** — do not fix it
  silently, extend it, or cite it as precedent.
  Subagents start cold and will guess at timing, optionality, eligibility, and cost — and
  guess wrong in the same ways documented here. Tell them explicitly: **a card that passes
  its own tests but reads the rules wrong is a FAILURE, not a success** (the agent's test
  only checks what it built, not what the rules require); when the text is silent or unclear,
  **defer (§0)** — do not pick the reading that is least work. Do not assume they will read
  this document. At minimum propagate, verbatim:
  - **"each time you [take / use / do X]" = the BEFORE window of X** — for **sub-actions**
    (Bake Bread / sow / plow / renovate / build) exactly as for action spaces
    (`before_bake_bread`, not `after`). The `after_` bias is a trap: after "just works" in a
    test because the mandatory sub-action already ran, but it is a BUG unless the text says
    "after". A reward is `after` **only** when it must read *what the action produced* or *its
    chosen target*; a **flat** reward fires **before**. (Beer Stein / Baking Sheet shipped on
    `after_bake_bread` — wrong.)
  - **The "you must do X normally to get the bonus" clarification is a GATE, not an ordering**
    — it means the bonus needs a completed X, not that it comes *after* X. Still `before` + a
    stranding guard.
  - **a before-trigger must not STRAND the host's mandatory sub-action** — its eligibility must
    verify that sub-action stays legal *after* the trigger spends its resources (grain for a
    before_bake conversion, cells for a Farmland plow grant, an occupation for a Lessons grant).
  - **a `/` or "or" in a COST is an alternative to pay ONE of, never a sum** (Club House
    shipped paying both) — a §0 today.
  - **"after the feeding phase" ≠ during feeding** — an exchange whose proceeds could pay the
    feeding must fire only after feeding resolves (Farm Store).
  - granted sub-actions are optional even when worded as commands; a decision-free animal
    grant must go through **`helpers.grant_animals`** (never a raw `p.animals + …`) so the
    accommodation barrier can surface the keep-which choice on overflow (§ below); counts
    ("Nth person", "in hand") must exclude same-turn artifacts.

Everything below helps you decide *whether* a card fits — and if it clearly does, *how*.
If it does not clearly fit: §0.

---

## 1. How to read a card (the framework)

Work through these steps for every card, in order. Do **not** skip step 1.

### Step 1 — Read the EXACT card text from the data files

Never reason from memory or from a paraphrase — **every time a card is named (by you or the
user), look up its exact text before reasoning about or implementing it.** This is a hard
rule: a paraphrase has burned us (e.g. "Side Job stable" / Feed Fence misreads). The
authoritative text lives in:

- `agricola/cards/data/revised_occupations.json`
- `agricola/cards/data/revised_minor_improvements.json`

**Use the lookup tool** rather than grepping the JSON by hand:

```
python scripts/card_text.py "feed fence" millwright "carpenter's parlor"
```

It searches both files by name **or** slug, prints the verbatim `text` plus
`cost`/`prerequisites`/`vps`/`passing_left` and deck/number/category, and marks whether each
card is already **IMPLEMENTED** (its slug is registered). `--exact` matches the full name.

Each entry has `deck`, `number`, `name`, `card_category`, `text`, and (for minors) `cost`,
`prerequisites`, `passing_left`, `vps`. The card id used throughout the code is the
slugified name (e.g. `"clay_hut_builder"`). Quote the exact text in the module docstring.

The full card set spans decks **A–E** — deck E is the Ephipparius expansion (the 5th
mini-expansion). Entries may also carry two fields sourced from the Unofficial Compendium:
`errata` and `clarifications` (the lookup tool prints both). **Always read these before
implementing a card** — `errata` is an *official correction that can change how the card
works* (e.g. "the jump may only be done once per turn", "remove the 'If you do' clause"), so
it overrides the printed `text`; `clarifications` resolve exactly the obscure timing/scope
rulings this guide is about (§2). A card with errata is a strong signal to slow down and, if
the corrected behaviour doesn't map cleanly onto the machinery, **defer and ask (§0)**.

### Step 2 — Classify the static facts

- **Occupation or minor?** Occupations register via `register_occupation`; minors via
  `register_minor` (which also carries cost / prerequisite / VPs / passing).
- **Cost** (minors): the spendable `Cost` (Resources + Animals) paid at play.
  - **Pitfall — "X in your supply" is a PREREQUISITE, not a cost.** Wording like *"5 Clay
    in your supply"* means *hold* ≥5 clay (a have-check), **not** spend it. Model it with
    a `prereq=` predicate and an empty `cost=Cost()`. (See `thick_forest.py`.)
- **Prerequisite**: "N occupations" → `min_occupations` / `max_occupations` bounds.
  Anything else (farm geometry, house material, goods held) → a custom `prereq` predicate.
- **Victory points**: a fixed printed VP → `vps=`. A *variable* VP (depends on end-state)
  → a scoring term via `register_scoring` (§4, "Scoring terms").
- **Passing** (traveling minors): `passing_left=True` — the card moves to the opponent
  after its on-play effect instead of staying in your tableau.

### Step 3 — Identify the effect's TIMING

This is where cards are won or lost. Ask: *when does the effect happen?*

- **On play** — a one-time effect when the card enters your tableau (gain goods, push a
  primitive). → `on_play`.
- **Triggered by an action / event** — "each time you use [space]", "each time you build a
  room", "when you renovate", etc. → a trigger or automatic effect on the relevant
  before/after event (§3).
- **At a phase boundary** — "at the start of each round", during the harvest field phase.
  → `start_of_round` / `harvest_field` hooks (§3).
- **A standing condition becomes true once** — "once you live in a stone house, …". →
  a one-shot conditional latch (§4).
- **Deferred to a future round** — "place goods on the next N round spaces". →
  `future_resources` / `future_rewards` (§4).
- **At end of game** — a scoring term (§4).
- **"At the end of that turn"** — ⚠️ **a distinct, currently-DEFERRED timing.** See the
  pitfalls in §2; do not implement these at the action-space pop.

### Step 4 — Identify the FIRING KIND

Three kinds (§3):

1. **Automatic effect** — mandatory and parameter-free ("you get 1 wood"). Applied
   directly at the hook, never offered as a choice. → `register_auto`.
2. **Optional trigger** — a "you may" / a granted sub-action. Surfaced as a `FireTrigger`
   the player can take or decline. → `register`.
3. **Mandatory-with-choice** — must happen, but the player picks how ("you must take 1
   grain or 1 vegetable"). → `register(..., mandatory=True)` + a `PendingCardChoice`.

> **Pitfall — a granted SUB-ACTION is optional even when worded as a command.** "Build a
> room", "plow a field" read like imperatives, but a card that *grants a sub-action* gives
> the player the *option* to take it; only an explicit **"you must"** is mandatory. Model
> grants as optional triggers (kind 2) with a decline path. A pure-goods grant with no
> downside ("you get 3 food") can be an automatic effect (kind 1). When unsure: §0.

### Step 5 — Identify the PRIMITIVE(s) it composes

Card effects should *compose* the engine's existing primitives, never re-implement them:
plow, sow, bake bread, build room, build stable, renovate, build fence, family growth,
gain goods, gain animals, play a card. Each is a reusable pending you `push`
(`PendingPlow`, `PendingBakeBread`, `PendingBuildRooms`, `PendingRenovate`, …) or a direct
state edit (gain goods). If a card seems to need a *new* primitive, that is a §0 moment.

### Step 6 — Map to a template and implement

Find the existing card with the same shape (§7 has the catalog), copy its structure, and
adapt. If no template matches, you are probably in §0 territory.

---

## 2. Obscure rules, rulings, and pitfalls (read this twice)

These are the things a coding agent reliably gets wrong. Most are settled rulings; when a
new one comes up that *isn't* settled here, that's a §0 (ask the user).

### "Each time you [take / use / do X]" fires BEFORE X — action spaces AND sub-actions

The official Trigger-Timing ruling: a bare *"each time you [do X]"* triggers in the
**before** phase of X, before X's own effect resolves — **not** after. This holds whether X
is an **action space** ("each time you use the 'Forest' space" → `before_action_space`) **or a
sub-action** ("each time you take a 'Bake Bread' action" → `before_bake_bread`; likewise sow /
plow / renovate / build). A card fires in the **after** phase **only** when its text says so
explicitly ("immediately after…", "after you …"). The phase is a **correctness** decision
fixed by the card text + the ruling — *never* chosen by convenience, and never "before/after
doesn't matter here, I'll pick one" (real bugs were caught from exactly that reasoning). When
the observable outcome would coincide either way, still classify by the ruling. This is the
same ruling that puts Milk Jug, Wood Cutter, Corn Scoop, Herring Pot, and Cottager on
`before_action_space`.

### Arrangement-conditioned benefits at the SAME instant must share ONE arrangement

Animals are not location-tracked; cards whose benefit is conditioned on an animal
ARRANGEMENT ("at least 1 unfenced stable without an animal" — Shepherd's Whistle,
ruling 16; "at least 1 sheep in a pasture" — Mineral Feeder, ruling 29) are
implemented as exists-an-arrangement tests. **Those tests may NOT be evaluated
independently for two cards reading the same instant**: the player holds one
arrangement at a time, so simultaneous benefits must be certified by a SINGLE
arrangement that satisfies all of them (user, 2026-07-06). Across *different*
instants independent tests are correct — real Agricola permits rearranging at any
time within capacity — so this bites only when a second arrangement-conditioned
card lands on an instant that already has one. No such pair exists today; if your
card creates one, STOP — the joint-satisfiability test is a design task for the
driver/user, not something to copy from the existing single-card implementations.

### "Immediately" in card text ALWAYS needs a user ruling

Whenever a card's text contains the word **"immediately"** in a timing phrase, stop and ask
the user what it means — never decide unilaterally. Sometimes it adds nothing: the user
ruled (2026-07-05, harvest-window ruling 18) that "IMMEDIATELY after each harvest" and
"after each harvest" name the SAME instant ("confusing and unnecessary" wording), and the
ladder's two after-harvest windows were merged. But the user was explicit that this does
**not** generalize — each occurrence gets its own ruling. The second instance proves the
point about asking: "immediately after the feeding phase" vs "after the feeding phase"
(Social Benefits vs Farm Store) ALSO collapsed (ruling 19, same day), but the user's
ruling carried an ordering (Social Benefits first, riding the autos-before-triggers
convention) that a silent merge would have had to guess at.
This is a different question from the before/after-phase classification above: there,
"immediately after…" is evidence the effect fires in the AFTER phase (unchanged); here, the
question is whether "immediately X" is a *separate, earlier instant* than plain "X".

**Flat reward → before; outcome-dependent reward → after.** The one legitimate reason to use
`after_<X>` without an explicit "after" in the text is that the effect must read *what X
produced* or *X's chosen target* — e.g. a reward scaled by how many rooms a build produced, or
Roughcaster needing to know a renovate went clay→stone (only knowable post-application). A
**flat** reward ("get 1 food", "turn 1 grain into 2 food") does **not** need the outcome, so it
fires **before**. Do not use "I put it after so the state was settled" as a reason — that is the
`after_` **convenience bias**, and it is the single most common timing bug: `after_` "just
works" in a test because the mandatory sub-action already ran and there is nothing left to
strand. That ease is exactly the trap.

> **The "you must [X] normally to get the bonus" clarification is a GATE, not an ordering.**
> A card like *Beer Stein* / *Baking Sheet* — "Each time you take a 'Bake Bread' action, you
> can [convert 1 grain to 2 food + a bonus point]," clarified "you must bake normally to make
> this exchange" — is `before_bake_bread`, **not** `after`. The clarification means the bonus is
> only available *as part of* a real bake (no bonus without baking); it does **not** say the
> bonus comes *after* the bake. With before-timing the gate is satisfied structurally — the
> `PendingBakeBread` before-phase offers only FireTrigger + CommitBake (no Stop), so a bake is
> still forced — **and you must add a stranding guard**: the exchange spends grain, so its
> eligibility has to verify a legal bake remains *after* the −1 grain (≥2 grain + a baker), or
> the mandatory bake is stranded. Both cards shipped on `after_bake_bread` on exactly the wrong
> reading of this clarification; that is the mistake this paragraph exists to stop.

> **⚠️ Never resolve a textual silence with a "these are equivalent" assumption — DEFER and ASK. The user will know.**
> Map the card's literal words to the precise mechanic. When the text is *silent* on
> something load-bearing — the order of a granted effect relative to the base action,
> optionality, whether two effects "commute" — that silence is resolved by the **Agricola
> rule default** (above), not by your judgment that "order doesn't matter here." If you
> cannot pin it down from the text plus the rules, **defer and ask. The user will know.**
>
> **This is not hypothetical.** The user has substantially deeper command of the Agricola
> rules and cardbase than the coding agent, and has repeatedly caught the agent confidently
> asserting that two choices were identical when they were not — the agent's inability to
> *find* a difference is not evidence that none exists. Two real bugs from exactly this:
> - A session moved **Moldboard Plow** from `after_action_space` to `before_action_space` (a
>   correct timing fix) but, assuming the bonus plow "commutes" with the base plow, added an
>   engine held-flip so it could be taken in *either order* — silently breaking enforce-first
>   for **every** `before_action_space` trigger on a delegating host.
> - A session put **Writing Desk** on `after_action_space`, reasoning the extra occupation
>   "was independent of the ramp." It is not: via Paper Maker ("each occupation after this
>   one"), after-timing lets you play Paper Maker as the base occupation and then have it
>   subsidize the granted one — which `before` (enforce-first) blocks.
>
> **The mechanic this established.** A `before_action_space` trigger on a delegating host
> (Farmland / Lessons / Major Improvement) fires **only** in the before-window; taking the
> mandatory sub-action closes that window and declines any unfired one. There is **no
> "either order."** A grant the player wants must be fired *before* using the space.

### A "/" or "or" in the COST means ALTERNATIVE cost (pay ONE), never a sum

A minor's printed cost like **"3 Wood / 2 Clay"** (or "3 wood or 2 clay") is an
**alternative**: you pay 3 wood *or* 2 clay — whichever you choose and can afford, **not
both**. Encoding it as `Cost(resources=Resources(wood=3, clay=2))` — paying BOTH — is a silent,
roughly double-price bug (this shipped on **Club House**). The machinery exists: the printed
first cost goes in `cost=` and each further alternative in `alt_costs=` (`register_minor`;
Chophouse "2 Wood / 2 Clay" is the template) — the play path enumerates one `CommitPlayMinor`
per affordable alternative. **Always scan the `cost` field for `/` or "or"** when classifying
(§1 step 2). A `/` in a *reward* or effect ("1 veg / 4 wood") is instead an OR-reward /
play-variant: for minors that is `register_play_minor_variant` (the wide play-variant seam —
Facades Carving, Plant Fertilizer, Automatic Water Trough; CARD_ENGINE_IMPLEMENTATION.md §3),
the minor analog of Roof Ballaster's occupation mechanism.

> **When the reward's "/" is COUPLED to a cost's "/", use `cost_labels`, not the variant
> surcharge.** A card like **Canvas Sack** ("*paying grain/reed for it, get 1 vegetable/4
> wood*") is not a free reward choice — the reward is *determined* by which alternative cost you
> paid (grain→veg, reed→wood, the slash-correlation rule). This is a genuine alternative COST, so
> it must stay cost-modifier-visible. Model it with `alt_costs` **plus** `cost_labels=` (parallel
> per-alternative labels): the alternatives still flow through `effective_payments`, and the
> chosen label is threaded into a 3-arg `on_play(state, idx, label)` that grants the matching
> reward. Do **not** reach for `register_play_minor_variant` here — a variant *surcharge* is an
> effect price that deliberately BYPASSES cost modifiers, which is wrong when the "/" is the
> card's actual cost. (Contrast Facades Carving, where the surcharge — food-for-points — really
> is an effect price.)

### "After the feeding phase" is NOT "during feeding" — a conversion must not feed itself

A harvest conversion registered with `register_harvest_conversion` is offered **during**
`HARVEST_FEED`, where its output can be routed back into paying the feeding cost. That is
correct for a food-**producing** feeding conversion, but WRONG for a card whose text says the
exchange happens **"after the feeding phase"** (e.g. **Farm Store**: "After the feeding phase of
each harvest, you can exchange exactly 1 food for … 1 vegetable"). Offered during feeding, the
player can buy a vegetable for 1 food and then **cook it with a Fireplace/Hearth to pay that
same feeding** — a food-laundering exploit the "after" wording exists to forbid. An
"after the feeding phase" exchange must fire **only once feeding is fully resolved** (after the
feeding payment / `CommitConvert`), so its proceeds cannot pay the feeding. There is no
post-feeding conversion window today → **§0: defer and ask** (or build the window with the
user), rather than shoehorning it into the during-feeding hook.

### "End of turn" is NOT "after the action's effects and triggers"

A worker-placement turn does not end when the action space's effect and all its
before/after triggers finish. The engine *currently* makes the action-space host pop
coincide with the turn end **only because nothing player-controllable sits between an
action's resolution and the turn ending today.** Once "at any time" effects exist (see
below), a player can act in that gap, and "end of turn" becomes a strictly later moment.

**Consequence:** cards that read **"at the end of that turn"** (e.g. Firewood Collector)
are **DEFERRED** — there is no correct anchor for end-of-turn until the at-any-time window
is defined. Do **not** implement them by firing at the action-space pop; that lands the
effect one window too early and is silently wrong. End-of-turn and at-any-time timings are
co-dependent and must be designed together (with the user — §0).

### A granted sub-action is optional (repeated because it's missed often)

See §1 step 4. "You can also build a room or renovate" (Cottager) is optional and a
*choice*; "you may plow" (Assistant Tiller, Plow Driver) is optional; only "you must" is
mandatory. Optional grants surface as `FireTrigger`s with a decline path (the host's
Proceed/Stop). Never force a granted sub-action.

### Optionality lives at the PARENT host, never as a per-frame "skip"

There is **no `SkipTrigger` action and no per-frame skip flag.** A player declines an
optional trigger by choosing something else at the host (a different commit, or the host's
Proceed/Stop). When you add a frame, mirror this: the *parent* host hosts the choice; the
pushed primitive, once entered, runs to completion. (See `ENGINE_IMPLEMENTATION.md` §2.)

### Always gate a grant on whether it's actually doable

Never offer a dead-end. A trigger's eligibility must check that the granted action is
*legal and affordable right now* — a plow grant requires a plowable cell, a build-room
grant requires affording the cost *and* a legal placement cell, a renovate grant requires
a non-stone house and the materials. Use the engine's own predicates (`_can_plow`,
`_can_build_room`, `_can_renovate`, `_can_bake_bread`, …) so the card matches native
legality. (Cottager's `_legal_variants` is the model.)

**And: a before-trigger must not STRAND the host's mandatory sub-action.** Any trigger that
fires *before* a host's mandatory, non-declinable sub-action (enforce-first) — whether a
`before_action_space` grant or a `before_<sub>` effect — and **consumes a resource that
mandatory sub-action needs** must gate its eligibility on that sub-action staying legal *after*
the trigger resolves, not merely on the trigger itself being doable. This is about the *shared
resource*, not just about granted sub-actions:
- **Cells** — a granted "plow 1 additional field" on Farmland requires **two** sequential
  plows (`_can_plow_twice`), not one (`_can_plow`): with a single plowable cell the grant would
  consume it and leave the base plow no target. (Plowing is adjacency-constrained — plowing one
  cell can open new adjacent targets — so this is a two-step simulation, not a cell count.)
- **Occupations** — an additional granted occupation on Lessons (Writing Desk) requires **≥2**
  playable occupations (one for the grant, one for the mandatory Lessons play).
- **Goods** — a `before_bake_bread` grain conversion (Beer Stein) must leave enough grain for
  the mandatory bake: eligibility requires ≥2 grain (1 to convert, ≥1 to bake) **plus** a baker,
  or it strands the bake. The same logic covers any before-trigger that spends grain/veg/wood/…
  a mandatory sub-action would otherwise use.

The delegating, single-mandatory-sub-action hosts (Farmland / Lessons / a live bake host) are
where the base action is strictly forced, so the guard is *required* there. On **Cultivation**
(whose mandatory work is plow **or** sow, so the base plow is declinable) the plow granters
still apply `must_preserve_base=True` + `_can_plow_twice` — a **user-approved** decision: it is
loss-less because spending a *limited* granted plow on a cell the *free* base plow could take is
strictly dominated, and no card rewards declining the base plow. Do not "simplify" that guard
away on Cultivation.

### before/after the host: what fires when

The uniform host lifecycle (every action space and sub-action; §3): **before-automatic
effects fire when the host is pushed → before-triggers are surfaced alongside the work →
the work happens — INCLUDING everything the effect pushed → after-automatic effects fire at
the work-complete boundary (the deferred commit flip / Proceed / auto-advance) →
after-triggers are surfaced → Stop pops.** After-autos fire at the *flip*, **not** at the
trailing Stop (Stop is a pure pop) — and for a commit-terminated host that flip is DEFERRED
(ruling 60, 2026-07-14): the executor marks `effect_initiated` and the engine flips only once
the effect's own pushed frames (an on_play's primitive, an oven's free bake) have resolved,
so an "after you [do X]" payout can never fund X's own effect (Bonehead × Established
Person). Getting this order wrong (firing after-autos at Stop, or before the effect) were
real regressions/bugs.

### Build Rooms / Build Stables / Build Fences is ONE action, not a sequence

**The rule.** Each of *Build Rooms*, *Build Stables*, and *Build Fences* is a **single,
instantaneous action that builds everything you pay for at once.** Building three rooms is
*one* action that produces three rooms simultaneously — there is no game-time moment, no
"step," and no recognized timing/event/trigger opportunity *between* the individual rooms.
The action has exactly two timing boundaries the rules recognize: just **before** it (its
cost/effects are about to happen) and just **after** it (everything it did is now done).

**The implementation.** For tractability — branching factor for MCTS / policy-head width
(the action-shaping Foundation: a layout is a *path* of small commits, not one choice over
all final layouts) — the engine resolves these actions as a **chain of one-piece commits**:
`CommitBuildRoom` / `CommitBuildStable` / `CommitBuildPasture`, each placing a single piece,
with the multi-shot host (`PendingBuildRooms` / `PendingBuildStables` / `PendingBuildFences`)
staying on top until `Proceed` ends the action. **This split is a search/representation
convenience, not a change to game semantics.** The chain must produce exactly the effects
the one-shot rule would.

**The invariant (load-bearing).** The chain's *internal* boundaries — the gaps between one
piece-commit and the next — are **not** a recognized time/event/trigger opportunity, so
**no card effect (trigger, automatic effect, reward, anything) may fire there.** Effects
fire only at the **action** boundaries: the host's before-phase (fired at push) and its
after-phase (fired at the `Proceed` work-complete flip). The before/after host model
enforces this — `before_/after_build_rooms` (etc.) fire at push/Proceed, never per piece —
so the way to *stay* correct is: **hook the action boundary, never a per-piece moment
(there is no such event to hook).**

**What this means when you author a card that interacts with one of these actions:**
- **Compute per-action effects over the WHOLE action, not per piece.** A budget, a count,
  a comparison, or a reward that the card text scopes to "when you build rooms/stables/
  fences" spans every piece of that one action.
  - *Millwright* ("replace up to 2 building resources … each time you build … rooms"): the
    2 is a per-**action** budget shared across every room/stable in the action — tracked in
    the card's `CardStore` (each piece-commit's debit reads the running count and caps,
    `record` adds what it used, the `after_build_*` auto resets it), **never** 2-per-piece.
  - *Shepherd's Crook* ("each time you fence a new pasture covering ≥4 spaces …"): snapshots
    the pasture decomposition in `before_build_fences` and computes the grant **once** in
    `after_build_fences` by diffing before-vs-after — **never** per `CommitBuildPasture`
    (that's also why a 6→4+2 split in one action grants only for the undivided 4).
  - *Feed Fence* ("for each new stable … for your last one, get 3 food"): the "last stable"
    is only knowable once the whole action is done → an after-phase computation, not per
    piece.
- **Do not invent a per-piece event or fire between commits.** If you find yourself wanting
  something to happen "after this one room but before the next," stop — that moment does not
  exist in the rules. It's either a before-action effect, an after-action effect, or a §0.

### Atomic spaces must be explicitly HOSTED to be hookable

A truly *atomic* action space (Forest, Day Laborer, Grain Seeds, Fishing, the accumulation
spaces) normally resolves in one step with **no host frame** — so there is nothing for a
before/after trigger to attach to. If your card hooks such a space, you must call
`register_action_space_hook(card_id, {space_id})` so the space gets a `PendingActionSpace`
host when your card is owned. **Non-atomic** spaces (Farm Expansion, Grain Utilization,
Cultivation, House Redevelopment, the animal markets, …) are always hosted, so they need
no hook registration — just register the trigger/auto on `before_/after_action_space` and
filter by `space_id` in the eligibility predicate.

### A pasture is not a `CellType` — empty fenced cells read as `EMPTY`

`CellType` has only `EMPTY / ROOM / FIELD / STABLE`; there is **no `PASTURE` value**.
Pastures are derived from the fence arrays, not stored on the cell — so a cell that is
fenced into a pasture but holds no stable keeps `cell_type == EMPTY`. Any card that reasons
about farmyard-space occupancy ("all spaces used," "an empty space," counting pastures, etc.)
must therefore **consult the fences, not just `cell_type`**: a cell is *used* when
`cell_type != EMPTY` **or** it is in `enclosed_cells(farmyard)` (from `agricola/helpers.py`,
which reads the cached `farmyard.pastures`). Checking `cell_type` alone silently undercounts
every empty pasture cell. This is exactly the bug that made **Big Country**'s "All Farmyard
Spaces Used" prerequisite reject a fully-fenced farm; `big_country.py`'s
`_all_farmyard_spaces_used` is the reference for the correct check. (Pasture *capacity* and
animal counts likewise come from `farmyard.pastures` / the accommodation helpers, never from
the grid.)

### Hidden information — do not leak hands

Each player's hand is private. The *engine* operates on full ground-truth `GameState`
(determinization for search is handled above the engine — it is not your concern when
writing a card effect). But never write a card whose *legal actions or visible effect*
depend on the opponent's hidden hand in a way that would reveal it. If a card seems to
require reading hidden information, that's a §0.

### Family byte-identity — card-only state must be invisible to the Family game

Any new field you add to `PlayerState`/`GameState` for cards **must default to a value the
Family game always holds**, and must be added to *both* the manual `PlayerState.__hash__`
(in `state.py`) and `canonical._DEFAULT_SKIP_FIELDS` (in `canonical.py`). This keeps the
Family game byte-identical and its C++ differential gates green (see §6). If you cannot
make the field default-skippable — i.e. the Family game can reach a non-default value —
then it is a **Family-reachable** change that must be ported to C++ too; that is a larger
undertaking and a §0.

### "At any time" conversions are NOT surfaced as standalone actions

The engine deliberately does not offer at-any-time grain/veg/animal→food conversions as
free-standing actions (a rational agent always defers them to the moment proceeds are
needed, so surfacing them only inflates the action set). They are bundled into the decision
points that need them (animal-overflow, capacity-blocked breeding, harvest feeding). Do
**not** add ad-hoc at-any-time conversions for a card's cost. Cards whose cost is payable
from convertible goods need the deferred at-any-time-cost machinery (§9) — that's a §0.

### Scoped "once per …" — pick the right scope

Several latches exist; choose deliberately:
- `triggers_resolved` (on a host frame) — "once per this host visit" (a trigger can't
  re-fire within one action). Handled automatically by the firing machinery.
- `used_this_round` — once per round (Plow Driver, Scholar).
- `used_this_turn` — once per turn.
- `fired_once` — once per game (conditional one-shots; never cleared).
- `CardStore` — arbitrary per-card persistent value (a counter, a snapshot).

---

## 3. The machinery — the firing model

### The host lifecycle (one paragraph)

Action spaces and sub-actions are **before/after hosts**. A host carries a `phase`
("before"→"after") and a `triggers_resolved` set. When pushed, its before-automatic
effects fire; its before-triggers are surfaced as `FireTrigger`s alongside the work
options. When the work completes (a single-commit sub-action marks `effect_initiated` at its commit
and the engine flips it once anything the effect pushed has resolved — the deferred
after-flip, ruling 60; a multi-shot builder — including `PendingBuildFences` — and an and/or
space *flip* on an explicit `Proceed`; a delegating space auto-advances), the host enters its
after-phase,
firing after-automatic effects; its after-triggers are surfaced alongside `Stop`; `Stop`
pops. (Every sub-action host now carries a `phase`; the lone Stop-terminated holdout is
`PendingSideJob`, a Family-only space that is never card-hooked.)

### Event names

A card registers an effect against an **event string**:

- **Action spaces:** `before_action_space` / `after_action_space` (one coarse event for all
  spaces; filter by `space_id` in eligibility). The composite improvement host uses
  `before_major_minor_improvement` / `after_major_minor_improvement`.
- **Sub-actions:** `before_<id>` / `after_<id>` for `id` in `sow`, `bake_bread`, `plow`,
  `renovate`, `build_major`, `build_rooms`, `build_stables`, `build_fences`,
  `play_occupation`, `play_minor`, `family_growth`. (`build_fences` joined the uniform
  host model — it flips to its after-phase on `Proceed`, like the other multi-shot
  builders; Shepherd's Crook hooks `before_/after_build_fences`.)
- **The preparation ladder** (ruling 54, 2026-07-14 as revised —
  CARD_ENGINE_IMPLEMENTATION.md §5d): every prep window id is an event string, in firing
  order `before_round` → (the reveal) → `reveal` → (collection) → `round_space_collection`
  → `start_of_round` → `replenishment` (post-refill) → `before_work` → `start_of_work`.
  Classify by the printed wording: "BEFORE the start of each round" → `before_round`
  (pre-reveal, pre-collection — Small Animal Breeder, Civic Facade; `round_number` is still
  the just-completed round there); "at the start of these rounds, you can [take the thing
  on the round space]" → `round_space_collection` (the schedule grants — Handplow, Plowman,
  Chain Float, Grassland Harrow, Small Greenhouse, Stable Planner, Tree Farm Joiner; user
  ruling 2026-07-14: a thing on the round space resolves at COLLECTION time); "at the
  start of each round" → `start_of_round`; "at the end of each preparation phase" /
  "before each work phase" → `before_work` (Pavior); "at the start of each work phase" →
  `start_of_work` (Freemason, Cob, Trout Pool, Museum Caretaker); "placed … during the
  preparation phase" → `replenishment` (Nest Site). Hosting is eligibility-driven — no
  hook registration; an auto-only card never makes a frame.
- **The round-end ladder** (§5c) and **harvest ladder** (§5b) likewise use their window ids
  as event strings (`returning_home`, `end_of_round`, `start_of_harvest`, …).
- (`end_of_turn` was removed with Firewood Collector — see §2 and §9; the old
  `harvest_field` event is deleted — harvest cards register on the window ladder.)

### The three firing kinds and how to register them

| Kind | Register with | Eligibility fn | Apply fn | Surfaced as |
|---|---|---|---|---|
| Automatic effect | `register_auto(event, card_id, eligible, apply, *, any_player=False, order=0)` | `(state, idx) -> bool` | `(state, idx) -> state` | nothing (applied at the hook; `order` sorts within one event — an auto that must read its same-instant peers' output registers late, Museum Caretaker) |
| Optional trigger | `register(event, card_id, eligible, apply)` | `(state, idx, triggers_resolved) -> bool` | `(state, idx) -> state` | a `FireTrigger` |
| Mandatory-with-choice | `register(event, card_id, eligible, apply, *, mandatory=True)` + `register_card_choice_resolver(card_id, resolver)` | `(state, idx, triggers_resolved) -> bool` | `(state, idx) -> state` (pushes `PendingCardChoice`) | a `FireTrigger` that gates the host's Proceed/Stop until fired |

Note the **eligibility-signature difference**: automatic effects take `(state, idx)`;
triggers take `(state, idx, triggers_resolved)`.

### Other registration helpers

- `register_action_space_hook(card_id, spaces, *, any_player=False)` — make an atomic space
  hosted when this card is owned (required for hooking atomic spaces; see §2).
  `any_player=True` hosts on *either* player's use (opponent hooks — Milk Jug).
- (`register_start_of_round_hook` is **GONE** — the preparation ladder's hosting is
  eligibility-driven: register on the window event and the frame appears exactly when your
  trigger is eligible. `register_harvest_field_hook` is likewise gone — harvest cards
  register on the harvest window ladder, §5b.)
- `register_conditional(card_id, condition_fn, apply_fn)` — a one-shot level-triggered
  effect (`condition_fn(state, idx) -> bool`; fires once, latched in `fired_once`).
- `register_play_variant_trigger(card_id, variants_fn)` — for a trigger that offers a
  *choice* between routes; `variants_fn(state, idx) -> list[str]` returns the legal routes,
  each surfaced as a distinct `FireTrigger(card_id, variant=…)`, and the apply fn becomes
  `(state, idx, variant) -> state` (Scholar, Cottager).
- `register_scoring(card_id, fn)` — an end-game scoring term; `fn(state, idx) -> int`.
- `register_occupation(card_id, on_play)` / `register_minor(card_id, *, cost, …, on_play)`
  — the static spec. `on_play(state, idx) -> state` (or `(state, idx, variant)` for a
  play-variant occupation — Roof Ballaster).

### Pushing a primitive from an apply fn

An apply fn may `push(state, PendingX(player_idx=idx, initiated_by_id="card:<id>", …))`.
The engine fires that primitive's before-autos at the push and resolves it before
returning to the host. Use `initiated_by_id="card:<card_id>"` as the provenance. For a
multi-shot grant capped at one (a single granted room/stable), push with `max_builds=1`.

---

## 4. The special mechanisms (when a card needs more than a hook)

- **Deferred goods (future round spaces)** — "place 1 food on each of the next 3 round
  spaces". Goods/food ride `PlayerState.future_resources` (a 14-slot `Resources` tuple);
  use the `schedule_resources` helper in `cards/schedules.py`. They're collected
  automatically at each round's start. (Pond Hut, Strawberry Patch, Sack Cart, Thick
  Forest, Large Greenhouse, Wall Builder.)
- **Deferred animals or a deferred EFFECT** — ride the card-only `future_rewards` tuple
  (animals are collected at round start via `grant_animals`, and the accommodation barrier
  asks the player which to keep if they overflow; an effect-card id surfaces an optional
  `start_of_round` trigger gated on the schedule). Handplow is the worked example of the
  deferred-optional-effect pattern; `schedule_effect` is the helper.
- **One-shot conditional latch** — "once you live in a stone house, …". `register_conditional`;
  fires the first moment the condition holds, swept after a renovate and after a card play,
  latched in `fired_once`. (Manservant, Clay Hut Builder.)
- **Per-card persistent state** — a counter or snapshot the card reads/writes over the
  game. Use the `CardStore` side-map (`PlayerState.card_state`, `get`/`set`). (Tutor's
  snapshot, Moldboard Plow's uses-left, Big Country's banked points.)
- **Scoring term** — a variable end-game VP. `register_scoring`. (Stable Architect, Manger,
  Wool Blankets, Big Country.)
- **Opponent-action hook** — fires on the *opponent's* use of a space. `any_player=True`.
  (Milk Jug.)
- **Play-variant choice** — a trigger offering two routes. `register_play_variant_trigger`.
  (Scholar, Cottager.)

---

## 5. The implementation recipe

1. **Read the card text** (§1 step 1) and write it verbatim into the module docstring.
2. **Classify** (§1 steps 2–5). If it doesn't clearly fit: **§0 — defer and ask.**
3. **Create `agricola/cards/<card_id>.py`**, copying the closest template (§7). The
   module's body is just the effect functions + the `register_*` calls at import.
4. **Register the import** in `agricola/cards/__init__.py` (this is what makes the card's
   `register_*` calls fire). Group it near similar cards with a one-line comment.
5. **Write tests** in `tests/test_cards_*.py` — at minimum: registration; the effect on the
   real engine flow that fires it (drive the actual placement/turn, don't poke frames where
   a real flow exists); eligibility boundaries (when it should and shouldn't be offered);
   optionality (it can be declined); and any "once per X" scoping. Mirror an existing card
   test file's idiom (`_own_occ`/`_own_minor` helpers, `run_actions`/`step` walks).
6. **Run the suite:** `~/miniconda3/bin/python -m pytest tests/ -n 4 --dist worksteal -q`.
   Card work is **card-only**, so it should be Family byte-identical and the C++ gates
   (`tests/test_cpp_*.py`) stay green untouched. If a C++ gate breaks, you made a
   Family-reachable change — stop and reconsider (§6).
7. **Update `CARD_IMPLEMENTATION_PLAN.md`** — mark the card done (or, if deferred, record
   *why*). This convention keeps the plan the source of truth for status.

---

## 6. The C++ engine and the differential gates

The C++ twin under `cpp/` is **Family-only** — it implements none of the card system
(`FireTrigger` literally throws there). The `tests/test_cpp_*.py` differential gates feed
it **Family** states only. Therefore:

- **Card-only work never touches C++ and the gates stay green without any C++ change.** This
  is by design and is why the gates passing after a card commit means "Family parity
  intact," *not* "the card logic was cross-validated." **Card logic is verified only by the
  Python test suite** — so write thorough Python tests.
- **A Family-reachable change is different.** If you change engine state/structure that the
  Family game can reach (a new `PlayerState` field the Family game populates, a change to a
  Family-reachable pending frame, legality, scoring, or the encoder), you **must** re-port
  it to C++ and keep the gates green — see the maintenance invariant in `CLAUDE.md`
  (Foundations) and `CPP_ENGINE_PLAN.md`. Most card work avoids this by keeping new state
  card-only and default-skipped (§2). If you can't, that's a §0.

---

## 7. Template catalog — which existing card to copy

Find the row that matches your card's shape and copy that module's structure.

| Card shape | Copy from |
|---|---|
| Cost modifier — reduction ("costs N less") | `bricklayer.py`, `lumber_mill.py`, `master_bricklayer.py` (state-dependent delta) |
| Cost modifier — whole-cost formula ("only costs X") | `carpenter.py`, `clay_plasterer.py` (conditional), `carpenters_parlor.py` |
| Cost modifier — conversion ("replace A with B") / per-action-budgeted sink | `frame_builder.py`, `millwright.py` (the per-action-budget + `record` pattern) |
| Cost modifier — renovate-target extension ("renovate wood→stone directly") | `conservator.py` (`register_renovate_target_extension`; cost follows the target) |
| On-play: gain goods | `consultant.py`, `clay_embankment.py` |
| On-play: push a MANDATORY primitive (plow/etc.) | `shifting_cultivation.py` |
| On-play OPTIONAL granted sub-action (renovate/build-fences/…) | `dwelling_plan.py`, `field_fences.py` — the generic `PendingGrantedSubAction` choose-or-decline wrapper (CARD_ENGINE_IMPLEMENTATION.md §6 Idioms). **The standard way**; the *only* correct home for a passing card's optional grant (an `after_play_minor` trigger can't host it). NOT `assistant_tiller.py` (that's the action-space-host trigger shape below). |
| Passing (traveling) minor | `market_stall.py` |
| Variable end-game VP (scoring term) | `stable_architect.py`, `manger.py`, `wool_blankets.py` |
| Automatic income on space use (before/after) | `wood_cutter.py`, `corn_scoop.py` |
| Optional granted sub-action ON AN ACTION SPACE (trigger; the host's Proceed/Stop is the decline) | `assistant_tiller.py`, `threshing_board.py`, `oven_firing_boy.py` |
| Mandatory-with-choice | `seasonal_worker.py`, `childless.py` |
| Play-variant choice (two routes) | `scholar.py` (start-of-round), `cottager.py` (action-space) |
| Opponent-action hook (`any_player`) | `milk_jug.py` |
| Start-of-round effect | `plow_driver.py`, `small_scale_farmer.py`, `scullery.py`, `groom.py` |
| Harvest-field effect | `scythe_worker.py`, `loom.py`, `butter_churn.py`, `three_field_rotation.py` |
| One-shot conditional latch | `manservant.py`, `clay_hut_builder.py` |
| Deferred goods (future round spaces) | `pond_hut.py`, `strawberry_patch.py`, `sack_cart.py`, `thick_forest.py`, `large_greenhouse.py`, `wall_builder.py` |
| Deferred optional effect (future round) | `handplow.py` |
| Per-card persistent state (`CardStore`) | `tutor.py`, `moldboard_plow.py`, `big_country.py` |
| Play-variant occupation (pay-or-not on play) | `roof_ballaster.py` |

If nothing matches, you are likely in §0.

---

## 8. A worked example — Cottager (B87)

Card text: *"Each time you use the 'Day Laborer' action space, you can also either build
exactly 1 room or renovate your house. Either way, you have to pay the cost."*

Walking the framework:
1. **Text** read from `revised_occupations.json` (deck B, #87).
2. **Static:** an occupation; no printed VP.
3. **Timing:** triggered by *using* Day Laborer → "each time you use" → **before**
   `action_space` on `day_laborer` (the ruling — §2). Day Laborer yields only food, so
   before/after is observationally neutral, but the ruling fixes it to *before*.
4. **Firing kind:** "you can also **either … or …**" → optional, and a **choice** between
   two routes → a **play-variant trigger** (kind 2 + the variant mechanism).
5. **Primitives:** build 1 room (`PendingBuildRooms`, `max_builds=1`) or renovate
   (`PendingRenovate`), each at the normal cost.
6. **Map:** Day Laborer is *atomic*, so `register_action_space_hook` is needed to host it.
   The two routes need `register_play_variant_trigger` with `variants_fn` returning
   `["room", "renovate"]` filtered by affordability/legality (`_can_build_room`,
   `_can_renovate`) — never offer a dead-end. Firing pushes the chosen primitive; the
   host's `triggers_resolved` gives once-per-use; the host's Proceed is the decline.

This required a *small, general* engine addition (expanding variant triggers at the
action-space host, not just the start-of-round host) — which was discussed with the user
before landing. A one-card engine change is exactly the kind of thing to surface (§0),
even when it turns out to be the right call.

---

## 9. The hard set — cards to DEFER and ASK about

These are **not** buildable on today's machinery. Do not attempt them without the user;
they need design decisions, not just code.

- **Cost-modifier cards** (a card that makes a build/renovate/improvement cheaper, or lets
  you pay it differently) — **NOW SUPPORTED** for renovate / build-room / build-major /
  play-minor / build-stable via the cost-modifier chokepoint (`COST_MODIFIER_DESIGN.md`;
  registries in `agricola/cards/cost_mods.py`: `register_reduction` / `register_formula` /
  `register_conversion`). See the §7 template row. Still deferred: **build-FENCE** cost cards
  (plan in `COST_MODIFIER_DESIGN.md` §9, not yet wired) and the *exotic* shapes — per-segment
  "Nth fence/room" discounts, per-action *total*-reduction budgets (Hunting Trophy), and a
  card whose cost is payable from at-any-time-convertible goods (the conversion-closure set,
  below).
- **Cards whose cost is payable from convertible goods** — needs the at-any-time-cost
  machinery (surface the Pareto-frontier conversion at the moment the cost is charged).
- **At-any-time conversion / "conversion closure" cards** — see §2; these are deliberately
  not standalone today.
- **Legality-changing cards** (a card that makes a normally-illegal action legal, or
  removes/changes a space) — needs the `*_EXTENSIONS` machinery generalized.
- **Per-card goods-stack cards** (goods accumulating *on the card*) — needs per-card goods
  state beyond `CardStore`'s scalar map.
- **"At the end of that turn" cards** (e.g. Firewood Collector) — DEFERRED until a true
  post-at-any-time turn-end boundary exists; co-dependent with the at-any-time design
  (§2). Do not anchor them to the action-space pop.
- **"Once per round, you can …" (use-it-or-lose-it) cards, "at round end" triggers, and
  round-end automatic effects** — DEFERRED pending a `PendingRoundEnd` frame (design in
  `CARD_DEFERRED_PLANS.md`). A card worded *"Once per round, you can [pay a good to gain
  something]"* — with **no** "at the start of each round" or person-placement qualifier — is a
  **use-it-or-lose-it** option usable at any point during the round, expiring at round end
  (members in the data: Corn Schnapps Distillery C64, Mandoline C46, Pellet Press D46). Because
  the engine deliberately does not surface anytime conversions (§2), the correct home is a
  round-end offering, **not** `start_of_round` (modeling it at round start wrongly forces the
  choice before the player has the goods and drops the anytime flexibility — Corn Schnapps was
  built that way and is now deferred). This is co-dependent with **round-end automatic effects**
  (e.g. Claypipe: "in the returning-home phase, if you gained ≥7 building resources this work
  phase, +2 food") and **"at round end" triggers**; all three share the `PendingRoundEnd`
  host, which must fire the **use-it-or-lose-it triggers FIRST**, then the automatic effects and
  at-round-end triggers. Do **not** approximate any of these with `start_of_round`. ("At any
  time, but only once per round" — Clay Carrier D122 — is instead the anytime-conversion family,
  §2.)
- **"After the feeding phase of each harvest, you can …" cards** — DEFERRED pending an after-phase
  on `PendingHarvestFeed` (design in `CARD_DEFERRED_PLANS.md`). These must fire only once feeding
  is fully resolved, so their proceeds can't pay that harvest's feeding; a during-feed
  `register_harvest_conversion` is **wrong** (e.g. Farm Store C41 lets you buy a vegetable for 1
  food then cook it to pay the feeding — the exact exploit the "after" wording forbids). No
  after-feed window exists today (`PendingHarvestFeed` has no phase model), and the harvest is the
  engine's most delicate subsystem, so building it is a §0. (Farm Store is archived in
  `archive/deferred_cards/`.) Contrast an ordinary during-feed conversion — "each harvest you can
  buy X for food" with no "after" — which correctly stays a `register_harvest_conversion`.
- **Individually deferred base cards** with known blockers: **Organic Farmer** (scoring over
  aggregate animal counts + the end-game "remove animals to free capacity" play),
  **Acorns Basket** (deferred animals scheduling). Revisit each only when its blocker
  lands. (**Mini Pasture** and **Shepherd's Crook** were on this list but are now
  IMPLEMENTED — `mini_pasture.py` via the restricted free-fence grant, `shepherds_crook.py`
  via the before/after `build_fences` CardStore snapshot.)
- **Animal grants have NO general accommodation path.** Animals are only kept-or-overflowed
  through the accommodation machinery at four points: the animal-market action spaces and
  breeding (`pareto_frontier` / `breeding_frontier`), harvest feeding, and the deterministic
  round-start collection of *scheduled* animals (`engine._collect_future_rewards`, which
  auto-takes the best accommodatable `pareto_frontier` point). A card that grants animals
  **immediately** — `p.animals + Animals(...)` in an `on_play` or trigger — bypasses all of
  this and simply inflates the count past capacity (silently wrong). So an immediate animal
  grant is a **defer-and-ask** unless the grant is guaranteed to fit (e.g. 2 sheep onto a
  brand-new ≥4-cell pasture, Shepherd's Crook). A "place N animals on the next round spaces"
  schedule is the safe shape — it routes through `_collect_future_rewards`'s accommodation.

`CARD_SYSTEM_DESIGN.md` §8/§15 is the authoritative list of the hard set and the flagged
cards; `CARD_IMPLEMENTATION_PLAN.md` tracks current per-card status. When a deferred card's
blocker is built, re-read its text (§1) and re-classify before implementing.

---

## 10. Discipline checklist (every card)

- [ ] Read the **exact** card text from the data files (`python scripts/card_text.py "<name>"`);
      quoted in the docstring.
- [ ] Classified timing + firing kind + primitives; it clearly fits — **or** deferred and
      asked (§0).
- [ ] Module created + imported in `cards/__init__.py`.
- [ ] Tests cover registration, the real-flow effect, eligibility boundaries, optionality,
      and scoping.
- [ ] Full suite green, including the C++ differential gates (untouched for card-only work).
- [ ] New card-only state (if any) is default-skipped in `canonical.py` + added to
      `PlayerState.__hash__`.
- [ ] `CARD_IMPLEMENTATION_PLAN.md` status updated.

And above all: **if you are unsure, defer and ask the user.** It is the cheapest correct
move and the one most likely to be right.
