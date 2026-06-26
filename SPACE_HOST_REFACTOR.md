# SPACE_HOST_REFACTOR.md

**Status: LANDED (B1 + B2 + B3).** All three staged steps are implemented and all gates (the full
Python suite + the C++ differential harness) are green: **B1** (Proceed-hosts + the firing migration
+ the §9 NN `Proceed`-as-`Stop` alias + the §11.1 card consequences), **B2** (the Delegating hosts —
`PendingSubActionSpace` folding Farmland + Fencing + the always-wrapped Major Improvement space +
Lessons; `PendingMajorMinorImprovement` as the composite-action Delegating host out of the
action-space bucket; the `_advance_until_decision` auto-advance), and **B3** (Meeting Place renamed
`PendingMeetingPlace`, made the single-optional Proceed-host with `Proceed` legal from the start —
card-only, no C++). It is the successor to
`SUBACTION_HOOK_REFACTOR.md`, which is **already landed** (its sub-action frames already carry
`phase` + `triggers_resolved` in the live code — that doc's own status header is stale). Read it
first. That refactor (the *sub-action* pass) made every commit-terminated **sub-action** frame —
`PendingSow`, `PendingBakeBread`, `PendingPlow`, `PendingRenovate`, `PendingBuildMajor`,
`PendingPlayOccupation`, `PendingPlayMinor`, `PendingFamilyGrowth` — a uniform before/after host:
its commit pivots the frame to `phase="after"` (no auto-pop) and fires `after_<id>` automatic
effects at that flip, and a trailing `Stop` pops it. This refactor (the *space-host* pass) does
the analogous thing one level up, for the **action-space parent frames** — the frames a worker
placement pushes.

The implementing session lands it in the three staged steps of §14, re-greening every gate
(including the C++ differential harness) at each step.

---

## 1. Why this exists

A worker placement on a non-atomic space pushes a *parent* frame that sequences the space's
sub-actions (e.g. Grain Utilization pushes a frame that lets you sow and/or bake). Today those
parent frames terminate with a bare `Stop` and have no before/after phase, so a card cannot hook
"the space itself" the way it can now hook a sub-action.

The card pool needs hooks at **three distinct levels**, and a single space-use can fire at more
than one:

- **The action space** — e.g. *Plumber* ("after you use the **Major Improvement action space**,
  take a renovation"), *Young Farmer*, *Large-Scale Farmer*.
- **The composite action** — e.g. *Merchant* ("after you take a **Major or Minor Improvement
  action**, take it again"), *Field Merchant* ("each time you **decline** a Minor/Major
  Improvement action"). This action happens at the Major Improvement space *and* as House
  Redevelopment's optional second step, so its hook must live on a frame shared across those
  entry points.
- **The leaf primitive** — e.g. *Junk Room* / *Roughcaster* on the individual major/minor build,
  already handled by the sub-action pass (`after_build_major` / `after_play_minor`).

So each level needs its own frame firing its own event. This refactor gives the parent frames
that structure.

---

## 2. The organizing principle: after-autos fire when the work completes

Every host frame has the same shape: a **before-phase**, then its work, then an **after-phase**,
then it pops. The events fire at fixed points, and the ordering is load-bearing:

1. **before-automatic effects** fire at **push** (when the host is created).
2. **before-triggers** are surfaced by the enumerator throughout the before-phase.
3. The host does its **work** (an effect, a commit, or one-or-more sub-actions).
4. **after-automatic effects** fire **the instant the work completes** — *after* the work, and
   *before* the after-triggers are offered.
5. **after-triggers** are surfaced in the after-phase; the after-phase's `Stop` pops the frame.

Step 4's placement is the crux, and it is the thing the current engine gets **wrong**: today the
after-automatic effects fire in `_apply_stop` (when the player ends the turn), which is *after*
the optional after-triggers have already been offered. That order is backwards — a mandatory "you
get 1 wood" automatic must resolve before the player chooses among optional triggers, because a
trigger may want to spend what the automatic just handed out. This refactor moves every host's
after-auto firing to its work-complete boundary (so it lands after the work but before the
triggers), and makes `_apply_stop` a pure pop. The concrete per-mechanism firing sites are in §11.

---

## 3. The four host mechanisms

The parent frames divide by **what signals "work complete"** — which is exactly what fires the
after-autos and flips to the after-phase:

| Mechanism | "Work complete" boundary (= after-auto fires here) | Member frames |
|---|---|---|
| **Atomic** | `Proceed` runs the space's effect, then flips | `PendingActionSpace` (an otherwise-atomic space, hosted only when a card could fire on it) |
| **Commit-terminated** | the single mandatory commit flips the frame | the three animal markets |
| **Delegating** | the host pushes exactly one mandatory sub-action; when that child pops, an engine step auto-flips ("auto-advance") | `PendingSubActionSpace` (Farmland, Fencing, the Major Improvement space, Lessons); `PendingMajorMinorImprovement` (the composite major/minor action) |
| **Proceed-host** | the player's explicit `Proceed` flips the frame (the sub-actions already ran) | the and/or spaces (Grain Utilization, Cultivation, Farm Expansion); the and-then spaces (House Redevelopment, Farm Redevelopment, Basic Wish for Children); the single-optional Meeting Place |

The sub-action **leaves** from the prior pass (`PendingSow`, `PendingBakeBread`, …) also use the
commit-terminated mechanism, but they are *child* frames pushed inside a space, **not action
spaces**, so they are not listed above — they are the prior pass's domain. Atomic and the markets
are already in their final shape (the atomic host from the original card-hook work; the markets
from the sub-action pass — though their *firing site* still moves, §11). This refactor builds the
**Delegating** and **Proceed-host** mechanisms.

Delegating and Proceed-host differ only in *who* fires the boundary — the engine (Delegating) or
the player (Proceed-host) — and the choice is forced by the host's shape:

- A host with **exactly one mandatory** sub-action has a *deterministic* "done": the instant its
  one child completes, it is done — there is never another base action to offer, so its would-be
  `Proceed` is *always a singleton*. Auto-advancing it removes a guaranteed-singleton step rather
  than a real choice. → **Delegating.**
- A host with **multiple** sub-actions, or an **optional** one, has a *player-chosen* "done": the
  player may do more, or decline. That choice must be an explicit action. → **Proceed-host.**

(**Side Job is the one deliberate exception** — see §13. It is an and/or space mechanically, but
it is Family-only and can never be card-hooked, so it stays Stop-terminated as today rather than
being churned into a Proceed-host for no benefit.)

---

## 4. Per-mechanism lifecycles

Notation: **⟨X⟩** is a child sub-action's full sub-action-pass lifecycle — initiate it, commit it
(which flips the child to its own after-phase and fires its `after_X` autos), and a singleton
`Stop` pops it, leaving the parent on top with the child's effect applied. The parent's
after-phase is always `[after-triggers…, Stop]`, so only the before-phase and the boundary are
described.

The action that initiates a sub-action is the existing **`ChooseSubAction(name=…)`** (dispatched
through the existing `CHOOSE_SUBACTION_HANDLERS` table, keyed on the parent's frame type) — *not*
a new action type. (Note `CommitSubAction` is already the marker base class the `Commit*` family
subclasses; it is not a concrete action.)

### 4.1 Atomic (`PendingActionSpace`) — final shape; only the firing site moves

```
push → fire before_action_space autos
before: [before_action_space triggers, Proceed]
  Proceed → run the space's effect, flip to after, fire after_action_space autos   (after the effect)
after:  [after_action_space triggers, Stop] → Stop pops
```

### 4.2 Delegating (`PendingSubActionSpace`, `PendingMajorMinorImprovement`)

```
push → fire before_<event> autos
before: [before_<event> triggers, ChooseSubAction(name=…)]   # PendingMajorMinorImprovement offers the
                                                              # build-major / play-minor choice instead
  ChooseSubAction → subaction_complete = True, push the child
  ⟨child⟩ resolves and pops
  ── now subaction_complete && phase=="before": a transient state, never enumerated ──
  _advance_until_decision auto-advances: flip to after, fire after_<event> autos   (after the child)
after:  [after_<event> triggers, Stop] → Stop pops
```

No `Proceed`. The work-complete boundary is the child popping, detected by `_advance_until_decision`.

### 4.3 Proceed-host (the and/or, and-then, and single-optional spaces)

```
push → fire before_action_space autos
before: [before_action_space triggers, <the legal ChooseSubActions>, (Proceed once its gate is met)]
  the player does zero-or-more ⟨sub-action⟩s (per the space's rules)
  Proceed → flip to after, fire after_action_space autos   (the sub-actions already ran; Proceed
                                                             runs no effect of its own)
after:  [after_action_space triggers, Stop] → Stop pops
```

The `Proceed` gate differs by sub-kind:

- **and/or** (do at least one of two, either order): `Proceed` legal once `a_chosen or b_chosen`.
  - *both:* ⟨a⟩ → ⟨b⟩ → Proceed (or ⟨b⟩ → ⟨a⟩ → Proceed)
  - *one:* ⟨a⟩ → Proceed
- **and-then** (a mandatory first sub-action, then an optional second): while the mandatory is
  unchosen, offer only it (no `Proceed`); once done, offer the optional + `Proceed`.
  - *both:* ⟨mandatory⟩ → ⟨optional⟩ → Proceed
  - *mandatory only:* ⟨mandatory⟩ → Proceed
- **single-optional** (Meeting Place — one optional sub-action): `Proceed` legal **from the
  start** (it *is* the decline).
  - *take it:* ⟨sub-action⟩ → Proceed
  - *decline:* Proceed

---

## 5. The auto-advance mechanism (Delegating hosts) in detail

`_advance_until_decision`, run at the end of every `step`, gains one new transition. For a frame
on top that is in the Delegating category:

```
is-a-delegating-frame(top) AND top.subaction_complete AND top.phase == "before"
  → flip top to phase="after", fire after_<event> automatic effects
```

Three pieces:

- **`is-a-delegating-frame`** — a category marker (a `ClassVar` flag or a shared mixin/base) so
  the walk only inspects the right frames. This marker is what lets `PendingSubActionSpace` and
  `PendingMajorMinorImprovement` — different classes firing different events — share one
  mechanism.
- **`top.subaction_complete`** — the work-complete signal (§5.2).
- **`phase == "before"`** — keeps it idempotent: after the flip it is `"after"`, so re-running
  the walk is a no-op (consistent with `_advance_until_decision`'s existing state-driven,
  idempotent contract). Firing the after-autos is a state mutation, which the walk already does
  for the harvest and reveal transitions, so it is not a new kind of step.

### 5.1 Why this cannot skip a before-trigger

The `subaction_complete && phase=="before"` state is **purely transient**: it exists only between
the child's `Stop`-pop and the auto-advance, both inside a single `step`, so `legal_actions` is
**never** called on it. before-triggers are surfaced *only* while `subaction_complete == False`,
and choosing `ChooseSubAction` is the implicit decline of any unresolved ones (the rule: "you may
resolve before-triggers, then you use the space; using it closes the before-window"). So there is
no window in which a before-trigger is both eligible and unreachable. No card contract and no
assertion are required.

### 5.2 The `subaction_complete` signal

Each Delegating frame exposes a uniform `subaction_complete: bool`, set `True` the moment its
`ChooseSubAction` pushes the child. `_advance_until_decision` reads it. How it is backed differs
by frame, and **both forms are fine because the read is uniform**:

- `PendingSubActionSpace` carries it as an explicit field.
- `PendingMajorMinorImprovement` keeps its `major_chosen` / `minor_chosen` fields (they are NOT
  collapsible — *Cabbage Buyer* fires differently on renovate-then-**no** vs **minor** vs
  **major** improvement, so the three-way distinction is load-bearing) and exposes
  `subaction_complete` as a derived property, `major_chosen or minor_chosen`.

---

## 6. The Major/Minor Improvement three-layer nesting

The Major Improvement space is the one space whose composite action (`build a major OR play a
minor`) is itself hookable *and* reused elsewhere, so it needs all three event levels as three
separate frames:

```
Major Improvement space (always wrapped):
  PendingSubActionSpace("space:major_improvement")     ← fires action_space          (Plumber)
    └─ PendingMajorMinorImprovement                    ← fires major_minor_improvement (Merchant)
         └─ PendingBuildMajor / PendingPlayMinor        ← fires build_major / play_minor (Junk Room)
```

Both upper frames are Delegating, so both auto-advance. A trace for **a non-oven major** (an oven
major would additionally push the Clay/Stone Oven free-bake wrapper inside `PendingBuildMajor`,
per the sub-action pass — omitted here for clarity). `[auto]` marks an engine auto-advance (not a
player action); plain `Stop` is an agent/scripted singleton:

```
push PendingSubActionSpace          → fire before_action_space autos
  ChooseSubAction("improvement")    → subaction_complete=True, push PendingMajorMinorImprovement
                                       → fire before_major_minor_improvement autos
    ChooseSubAction(build_major)    → push PendingBuildMajor
    CommitBuildMajor                → (sub-action pass) flip + fire after_build_major
    Stop                            → pops PendingBuildMajor
  [auto] PendingMajorMinorImprovement(subaction_complete, before):
                                       flip, fire after_major_minor_improvement (Merchant)
  after: [Merchant triggers, Stop]  → Stop pops PendingMajorMinorImprovement
  [auto] PendingSubActionSpace(subaction_complete, before):
                                       flip, fire after_action_space (Plumber)
  after: [Plumber triggers, Stop]   → Stop pops PendingSubActionSpace. turn ends.
```

before-autos at push (pre-work), after-autos at each auto-advance (post-work, pre-trigger),
triggers in the right phases, both levels. (This is why the work cannot be deferred to `Proceed`
or to `Stop`: §2.)

**Reuse under House Redevelopment.** House Redevelopment's optional second step pushes the *same*
`PendingMajorMinorImprovement` — but **not** a `PendingSubActionSpace`, because House
Redevelopment is itself the space host (a Proceed-host) firing its own `action_space`. So under
House Redevelopment the stack is `[PendingHouseRedevelopment, PendingMajorMinorImprovement,
primitive]`: the composite-action and primitive events fire, but no *Major-Improvement-space*
event does — correct, since *Teacher's Desk* ("Major Improvement **or** House Redevelopment action
space") hooks House Redevelopment's own `action_space`, which it names separately.

**Always-wrapped.** The Major Improvement space pushes `PendingSubActionSpace` in every game,
including the Family game (where its before/after triggers are empty and it is a pair of
auto-skipped singletons). This is a conscious extra-frame cost chosen for uniformity over
minimizing the Family trace.

**Removing the conflation it fixes.** `PendingMajorMinorImprovement` becomes a pure
composite-action host and **leaves `ACTION_SPACE_PENDING_IDS`** (it fires `major_minor_improvement`,
not `action_space`). Today it is in that bucket, which means under House Redevelopment it would
fire a *second* `after_action_space` on top of House Redevelopment's own — masked only because no
space-scoped card exists yet. The split removes it.

---

## 7. Meeting Place — the single-optional Proceed-host

Meeting Place (card game) is `become starting player` (immediate, mandatory, triggers no cards)
then *optionally* play one minor. The optional minor means it cannot auto-advance (the decline has
no child to complete), so it is a Proceed-host with `Proceed` legal **from the start**:

```
push PendingMeetingPlace; apply become-SP immediately; fire before_action_space autos
before: [before_action_space triggers, ChooseSubAction("play_minor") (iff playable & not chosen), Proceed]
  play it:  ChooseSubAction → ⟨PendingPlayMinor⟩ → minor_chosen=True → before collapses to [Proceed] → Proceed
  decline:  Proceed
Proceed → flip to after, fire after_action_space autos
after:  [after_action_space triggers, Stop] → Stop pops
```

`PendingMeetingPlaceCards` is renamed `PendingMeetingPlace` and gains `phase` + `triggers_resolved`
(keeping `minor_chosen`); `meeting_place` is added to `ACTION_SPACE_PENDING_IDS`. It is
**card-only** (the Family Meeting Place stays the atomic food/SP resolver and never pushes this
frame), so it requires **no C++ mirror** — the one new-shaped host that is C++-free.

---

## 8. Lessons folds into Delegating

Lessons (card game) is an action space whose single, mandatory action is "play one occupation"
(no decline — placement legality guarantees a playable, affordable occupation). That is exactly
the Delegating shape, so Lessons becomes `PendingSubActionSpace("space:lessons")` whose
`ChooseSubAction("play_occupation")` pushes `PendingPlayOccupation` (a sub-action-pass leaf). It
thereby gains the `action_space` surface for free while `PendingPlayOccupation` keeps
`play_occupation`. The `ChooseSubAction` handler sets `PendingPlayOccupation.cost` (the occupation
cost) when it pushes, mirroring how Lessons computes it today. Card-only, so no C++ for the Lessons
use (the `PendingSubActionSpace` class is already C++-mirrored via Farmland/Fencing/Major-space).

---

## 9. Downstream NN impact — and why no model needs retraining

This refactor changes the **Family game's recorded-decision trace**: at the and/or and and-then
parents (Grain Util, Cultivation, Farm Expansion, House/Farm Redev — all Family spaces), the
"done" action changes from `Stop` to `Proceed`, and `Proceed` did not previously appear in the
Family game at all. Left unhandled, this would (a) blind the trained policy's `choose_subaction`
head at those points and stale its training labels, and (b) shift the value model's input vector
(via a feature that tracks whether `Stop` is legal). Both are avoided by **treating `Proceed` as
`Stop` everywhere the NN harness looks** — there is never a decision point where *both* are legal
(a host offers `Proceed` in its before-phase and `Stop` in its after-phase, never together), so
the alias is unambiguous, and it makes pre-refactor data and post-refactor data produce identical
labels. With the alias applied in **all three** spots below, **both the value and policy models
keep working unchanged — no retrain:**

1. **Policy / MCTS prior (in scope).** Add a single rule — `Proceed → STOP_LABEL` — to the shared
   `choose_subaction` label function (`_subaction_label`), right where `Stop → STOP_LABEL` already
   lives. That one rule does both jobs:
   - **Inference (the MCTS goal you're asking about):** at a parent's before-phase the legal "done"
     action is now `Proceed`, and the `make_policy_fn` combiner uses the label rule to attach the
     trained `choose_subaction` head's `STOP_LABEL` probability to that `Proceed` action — so the
     MCTS policy prior treats `Proceed` exactly as the head learned to treat `Stop`. **`mcts.py`
     itself is not touched**: it consumes `policy_fn` as a black box, so the alias lives entirely in
     the policy layer (`policy.py` / `policy_heads.py`). "Make MCTS read `Proceed` as `Stop`" is
     precisely "make the combiner map `Proceed` onto the head's `STOP_LABEL` slot."
   - **Training:** a recorded `chosen_action = Proceed` extracts to the same `STOP_LABEL`, so
     post-refactor self-play data aligns with the pre-refactor `Stop`-labeled corpus and the head
     needs no relabeling or retrain.
   (The `build_stop` head is unaffected — it serves the multi-shot room/stable builders, which stay
   `Stop`-terminated.)
2. **Encoder `stop_is_legal` feature** — the value/policy encoder has a feature for "is a
   turn-ending action available." It must count `Proceed` as such, or it flips `1→0` at every
   parent before-phase and silently changes the value model's input. **This is the value-critical
   spot.** Mirror the same change in the **C++ encoder** (for the differential gates).
3. **`restricted.py`** — check for any wrapper that filters on `Stop` at a parent and give it the
   same alias.

There is one residual, harmless today: in the *card* game a parent's before-phase `Proceed` and
its after-phase `Stop` (when after-triggers exist) both collapse to the one "done" label — a mild
conflation a future from-scratch card-agent training can split if it wants; the Family NN never
hits it (its after-phases are empty singletons).

Separately, the encoder reads frame *types* to tell which sub-action is mid-action (today via
`isinstance(frame, PendingFarmland)` / `PendingFencing`). When §10 folds those classes into
`PendingSubActionSpace`, the encoder must be updated to recognize the new frame and **emit the
same categories** (driven off `subaction_complete` / the space id), so the value model's features
are preserved. Same mirror in C++.

---

## 10. Frame inventory

`PendingSubActionSpace` and `PendingMajorMinorImprovement` both opt into the Delegating
auto-advance via the category marker. `PendingSubActionSpace` is the generic single-mandatory space
host; the specific child is dispatched by `space_id` (from `initiated_by_id`):
`farmland→PendingPlow`, `fencing→PendingBuildFences`, `major_improvement→PendingMajorMinorImprovement`,
`lessons→PendingPlayOccupation`.

**Removed / replaced:** `PendingFarmland` and `PendingFencing` are deleted and folded into
`PendingSubActionSpace` (child dispatched by `space_id`). `PendingMeetingPlaceCards` is renamed
`PendingMeetingPlace`.

**Frames that currently LACK `triggers_resolved` and must gain it:** `PendingGrainUtilization`,
`PendingFarmExpansion`, `PendingBasicWishForChildren`, `PendingMeetingPlaceCards`. (The others
named below already have it.)

| Frame | Mechanism | Event | Key fields beyond player_idx/initiated_by_id | Family-reachable → C++ |
|---|---|---|---|---|
| `PendingActionSpace` | Atomic | action_space | `phase`, `triggers_resolved` | yes *(only firing-site move)* |
| `PendingSubActionSpace` *(new; replaces Farmland+Fencing)* | Delegating | action_space | `phase`, `subaction_complete`, `triggers_resolved` | yes (Farmland/Fencing/Major-space); Lessons use card-only |
| `PendingMajorMinorImprovement` | Delegating | major_minor_improvement | `phase`, `major_chosen`, `minor_chosen`, `triggers_resolved` | yes |
| `PendingGrainUtilization` | Proceed-host (and/or) | action_space | `phase`*, `sow_chosen`, `bake_chosen`, `triggers_resolved`* | yes |
| `PendingCultivation` | Proceed-host (and/or) | action_space | `phase`*, `plow_chosen`, `sow_chosen`, `triggers_resolved` | yes |
| `PendingFarmExpansion` | Proceed-host (and/or) | action_space | `phase`*, `room_chosen`, `stable_chosen`, `triggers_resolved`* | yes |
| `PendingHouseRedevelopment` | Proceed-host (and-then) | action_space | `phase`*, `renovate_chosen`, `improvement_chosen`, `triggers_resolved` | yes |
| `PendingFarmRedevelopment` | Proceed-host (and-then) | action_space | `phase`*, `renovate_chosen`, `build_fences_chosen`, `triggers_resolved` | yes |
| `PendingBasicWishForChildren` | Proceed-host (and-then) | action_space | `phase`*, `family_growth_done`, `minor_chosen`, `triggers_resolved`* | card-only |
| `PendingMeetingPlace` *(rename)* | Proceed-host (single-optional) | action_space | `phase`*, `minor_chosen`, `triggers_resolved`* | card-only |
| markets ×3 | Commit-terminated | action_space | `phase`, `gained`, `triggers_resolved` | yes *(only firing-site move)* |
| `PendingSideJob` | **unchanged** (Stop-terminated; §13) | — | `stable_chosen`, `bake_chosen`, `triggers_resolved` | n/a |

`*` = field added by this refactor. `PendingSubActionSpace` shares `PENDING_ID = "action_space"`
with `PendingActionSpace` (both fire `action_space`; both are in `ACTION_SPACE_PENDING_IDS`). Safe
because `PENDING_ID` is used only for event derivation and bucket membership, never as a unique
dispatch key — the enumerator table and the canonical `__type__` are keyed on the class, which is
distinct.

**Dead code to remove:** the per-frame `TRIGGER_EVENT` ClassVars on the refactored parents (event
derivation goes through `trigger_event()` instead), and `legality._after_action_space_fired` (its
only caller, the old Cultivation enumerator, is replaced).

---

## 11. Engine-function changes (the firing migration)

The current engine fires `after_action_space` for every `ACTION_SPACE_PENDING_IDS` member in
`_apply_stop` — i.e. at turn-end, *after* the after-triggers were offered (the §2 ordering bug).
This refactor moves every host's after-auto firing to its work-complete boundary and empties
`_apply_stop`:

- **`_apply_stop` → pure pop.** Drop the `after_action_space` firing entirely. (This removes the
  double-fire risk for Proceed-hosts, which would otherwise fire at both `Proceed` and `Stop`, and
  fixes the ordering for the markets/atomic too.)
- **`_apply_proceed`** — currently asserts `isinstance(top, PendingActionSpace)`; **broaden it** to
  accept Proceed-hosts as well. For an **atomic** host it runs the space's effect, flips, and fires
  `after_action_space` (after the effect). For a **Proceed-host** it has no effect of its own (the
  sub-actions already ran), so it just flips and fires `after_action_space`.
- **`_execute_accommodate`** (the markets) — already applies the accommodation and flips; **add**
  the `after_action_space` firing right there (after the commit), instead of relying on
  `_apply_stop`.
- **`_advance_until_decision`** — the Delegating auto-advance (§5) fires `after_<event>` when the
  child pops (after the child's work).

Net: after-autos fire after the space's own work and before its after-triggers, uniformly; nothing
fires at `Stop`.

### 11.1 Existing-card consequences of the migration

Moving the `after_action_space` firing out of `_apply_stop` changes the behavior of the cards
already registered on that event, so B1 must handle them:

- **Milk Jug** (the only `after_action_space` **automatic** effect on a market — Cattle Market):
  **move it to `before_action_space`.** Its card text is "each time any player uses the Cattle
  Market…", and the ruling is that "each time you use [a space]" resolves *before* taking the
  space's action — so it was mis-registered as an after-effect to begin with. The migration is the
  natural moment to correct it; it then fires at the market frame's push, like the other
  `before_action_space` autos.
- **Firewood Collector** (`after_action_space` automatic on Farmland / Grain Util / Cultivation,
  "+1 wood **at the end of that turn**"): **defer it** (remove its registration + archive the
  module, drop/skip its test). The migration fires after-autos at the *work-complete* boundary
  (mid-turn, before the after-triggers), which is not the "end of that turn" the card specifies;
  honoring that wording needs a dedicated end-of-turn event this refactor does not add. It returns
  when that event exists.
- The `after_action_space` **trigger** cards (basket, mushroom_collector, assistant_tiller,
  oven_firing_boy, threshing_board) are **enumerator-surfaced**, not fired by `_apply_stop`, so the
  firing migration leaves them working. But their *surfacing point* moves into the new after-phase
  (e.g. threshing_board on Cultivation now appears after that space's `Proceed`, not at the old
  Stop-gate), so a few of their tests need updating to the new walk. No behavior change, only the
  trace.

These are the complete set of cards touching `after_action_space` today; nothing else is affected.

---

## 12. C++ sync scope

The Family-reachable frames that gain `phase` (and the auto-advance / `Proceed` behavior) must be
mirrored in C++ — the new fields and transitions reach Family states and so are not
default-skippable. The set: `PendingSubActionSpace` (replacing the C++ `PendingFarmland` /
`PendingFencing` structs, and used by the Major space), `PendingMajorMinorImprovement`,
`PendingGrainUtilization`, `PendingCultivation`, `PendingFarmExpansion`, `PendingHouseRedevelopment`,
`PendingFarmRedevelopment`. In addition:

- C++'s `apply_proceed` / `apply_stop` / `execute_accommodate` must move their firing per §11. The
  after-auto firing is a Family no-op (no automatic effects registered), but the **phase flips are
  observable** in the Family trace, so they are required.
- C++'s `advance_until_decision` must perform the Delegating auto-advance **flip**.
- The C++ encoder must mirror the `stop_is_legal` alias (§9) and the `PendingSubActionSpace`
  sub-action-category handling.

The card-only frames (`PendingMeetingPlace`, `PendingBasicWishForChildren`, the Lessons use of
`PendingSubActionSpace`, `PendingPlayOccupation`) never reach C++.

---

## 13. Deferred / out of scope

- **Side Job** stays Stop-terminated, exactly as today — it is an and/or space mechanically, but
  Side Job is Family-only (removed in the card game), so it can never be card-hooked and gains
  nothing from a Proceed-host conversion. It is the one deliberate exception to the and/or →
  Proceed-host rule; leaving it avoids a pure-churn Family-trace + C++ change.
- **The oven wrappers** (`PendingClayOven` / `PendingStoneOven`) — single-optional sub-frames of
  Build Major, but no card hooks them as a surface, so they stay exactly as-is (Stop-terminated
  optional bake; their free-bake `PendingBakeBread` already got the sub-action pass's flip+Stop).
  They are not action-space hosts.
- **A Lessons *space*-surface wrapper beyond what §8 gives** — Lessons already gets `action_space`
  via `PendingSubActionSpace`; nothing more is needed until a card requires it.

---

## 14. Staging

Land in three steps, each committing the Python change and the C++ sync together and re-greening
all gates (`pytest tests/` and `pytest tests/test_cpp_*.py`) before the next.

- **B1 — Proceed-hosts + the firing migration. (LANDED.)**
  - Give the five Proceed-host parents — `PendingGrainUtilization`, `PendingCultivation`,
    `PendingFarmExpansion`, `PendingHouseRedevelopment`, `PendingFarmRedevelopment` — `phase` (+
    `triggers_resolved` where missing: Grain Util, Farm Expansion) and the explicit `Proceed`
    boundary, replacing `Stop` in each of their five legality enumerators.
  - Do the §11 firing migration: broaden `_apply_proceed` (atomic + Proceed-host), move the
    markets' firing into `_execute_accommodate`, make `_apply_stop` pure-pop.
  - Apply the §9 NN alias (policy `_subaction_label`, encoder `stop_is_legal`, C++ encoder,
    `restricted.py`) — `Proceed` first appears in this step, so the alias must land here.
  - Handle the §11.1 existing-card consequences: move **Milk Jug** to `before_action_space`,
    **defer Firewood Collector**, and update the trigger-card tests whose surfacing point moves.
  - C++ sync: the five Proceed-host frames + the `apply_proceed`/`apply_stop`/`execute_accommodate`
    firing moves. (`PendingBasicWishForChildren` rides along, card-only.)
- **B2 — Delegating. (LANDED.)**
  - Introduce `PendingSubActionSpace` (folding in Farmland and Fencing, child dispatched by
    `space_id`; remove the two old classes); give `PendingMajorMinorImprovement` its Delegating
    lifecycle and remove it from `ACTION_SPACE_PENDING_IDS`; build the Major Improvement
    three-layer always-wrapper; add the `_advance_until_decision` auto-advance + the category
    marker + `subaction_complete`.
  - Update the encoder's frame-type sub-action handling for `PendingSubActionSpace` (§9, preserve
    features); mirror in C++.
  - Remove the dead `TRIGGER_EVENT` ClassVars and `_after_action_space_fired`.
  - The largest step; ~4 Family-reachable C++ frames plus the C++ auto-advance.
- **B3 — Meeting Place. (LANDED.)** Rename to `PendingMeetingPlace`, make it the single-optional
  Proceed-host. Card-only, no C++.

---

## 15. Verification / definition of done

- `pytest tests/ -n 4 --dist worksteal` green (Python).
- `pytest tests/test_cpp_*.py` green (C++ differential — the Family game is byte-identical
  *between* the two engines after each step).
- New lifecycle coverage for: an and/or `Proceed` walk (both options and one option); an and-then
  walk; the Major Improvement three-layer auto-advance nesting (and the same
  `PendingMajorMinorImprovement` reused under House Redevelopment); Lessons via
  `PendingSubActionSpace`; Meeting Place take-and-decline.
- A short `-O` run and a short self-play / MCTS run still work (singletons stepped through; the
  auto-advance records no new decisions; the trained value + policy models load and run unchanged
  under the `Proceed`-as-`Stop` alias).
</content>
