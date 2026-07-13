# Harvest-Window Arc — Session Handoff (2026-07-03 → 2026-07-06; Part II appended 2026-07-06)

> **Who this is for.** A fresh session (or a post-compaction continuation) picking up the
> card-engine work. The previous compaction preserved outcomes but lost the *reasoning*,
> and the resumed session was confused implementing card effects as a result. This
> document preserves the reasoning in full: every ruling with its derivation, every
> design argument with the counterexamples that shaped it, the bugs found and why they
> happened, and the exact state of the remaining work with per-item cautions.
>
> **Authority order.** The user is the rules authority. The dated ruling RECORDS are
> `CARD_DEFERRED_PLANS.md` → "Harvest-window redesign — user rulings" (17 numbered) and
> `design_docs/cards/HARVEST_WINDOWS_DESIGN.md` (the design of record; its §12 is the
> as-built code map). This handoff explains WHY those rulings say what they say; if this
> doc and a record ever disagree, the record wins and this doc has rotted — fix it.
> `CARD_AUTHORING_GUIDE.md` §0.1 (fidelity is absolute; an approximation you can justify
> is still a defer) governs all card work and goes VERBATIM into every subagent prompt.

---

## 1. What the harvest-window system is (one paragraph, then the pieces)

Printed card text names many distinct instants around a harvest ("immediately before
each harvest", "at the start of the field phase", "at the end of each harvest", …).
The engine now has an ordered ladder of 17 window ids threaded through the
FIELD → FEED → BREED walk (`agricola/cards/harvest_windows.py::HARVEST_WINDOWS`),
where each simple window's id doubles as a trigger/auto event string, and three
entries are sentinels for the engine's own machinery (the field-phase take, the
feeding frames, the breeding frames). Cards register on the instant their text names.
The walk is `engine._advance_harvest`; it resumes at `GameState.harvest_cursor` (a
VIRTUAL index — see §3). *(Updated 2026-07-12: since ruling 40's FEED/BREED banding
a FAMILY game carries the cursor while a payment/breeding frame is up — the C++ twin
mirrors it and the gates are green. Before that, every change in this arc was
card-only or Family-invisible.)*

## 2. The one-event model of the field phase (rulings 5, 11 — the core insight)

**Ruling 5**: the field-phase take is ONE singular event — it harvests 1 crop from
every planted field simultaneously; all per-field/per-crop consequences arrive at once.

**Ruling 11** (2026-07-05, the session's biggest correction): ALL field-phase
harvesting folds into that one event. Cards like Stable Manure ("harvest 1 additional
good from a number of fields…"), Scythe Worker ("1 additional grain from each of your
grain fields"), and Scythe E73 ("select exactly one of your fields and harvest all the
crops planted in it") do NOT create separate harvesting events — their extras are taken
*at the same time* as the take, inside the same occasion.

**How we know.** The user asserted the simultaneity reading; a two-agent full-catalog
sweep stress-tested it and found ZERO counterevidence:
- No card harvests from fields during a harvest outside the field phase.
- No card anywhere uses sequential wording ("then harvest again", "after you harvest
  your fields") — every during-phase harvesting effect is a *modifier* of the one
  event ("additional", "instead" — Grain Thief, "select one field and harvest all").
- Two official clarifications support it directly. **Potato Ridger A59** (the closest
  thing to a definition of the verb): *"'Harvest' is equivalent to the field phase, or
  any literal effect of a card saying 'Harvest a [crop/vegetable].'"* **Hayloft Barn
  B21** (official simultaneity semantics): *"Harvesting 2+ grain at once only counts as
  obtaining once, regardless of any other crops harvested."*

**Consequences that flipped earlier decisions:**
- The earlier recorded ruling 9 contrast ("Grain Sieve reads the take incl. Scythe
  Worker's fold-in but NOT Stable Manure's separate occasion") was superseded: Stable
  Manure's extras are IN the take, so **Grain Sieve counts them** toward "at least 2
  grain" (the user ruled this explicitly: the two cards provide near-identical benefits
  and must be treated identically).
- Stable Manure's first implementation (a free-order trigger emitting its own
  occasion, orderable before/after the take) was torn out and rebuilt as a take
  modifier. A whole open question ("can a post-take 1-remaining field donate?")
  dissolved — there is no post-take firing; donors need ≥2 at take time because the
  extra must be *additional* to the base take's 1.
- `emit_harvest_occasion` (the card-side separate-occasion seam) has NO during-phase
  user anymore. It survives for genuinely separate events: a Bumper-Crop-played field
  phase, future literal "Harvest a crop" card effects.

## 3. Ruling 3 and the virtual walk (per-player FIELD segment)

Within the FIELD segment (before_field_phase … after_field_phase, the take included),
the starting player resolves their ENTIRE segment before the other player begins
(ruling 3, PROVISIONAL — the user dislikes the later-player advantage; matches the
official implementation; revisit if distortive). Everywhere else windows resolve
window-major (both players per window, SP first). *(Updated 2026-07-12: ruling 40
extended the banding to FEED and BREED — three per-player bands, 26 virtual positions
at 2 players; the four outer moments stay window-major. §16's queue item 1 records
the landing.)*

Implementation: `harvest_cursor` indexes a VIRTUAL walk — the raw ladder with each
phase band repeated once per player (`walk_position(cursor, sp)` decodes; N players
= N band repeats, the shape 4p needs). The stakes the user
named when demanding this: Beer Table (end-of-field-phase: pay grain → 2 VP, opponent
gets 1 food) resolves in the SP's segment BEFORE the opponent's segment starts, so the
opponent's Cube Cutter can spend that food — the segment ordering deliberately creates
that line, and tests pin it.

## 4. The take-modifier seam and the claim-aware allocation (the collision bug)

`register_take_modifier(card_id, fold_fn, variants_fn=None)` in harvest_windows.py:
- **Auto fold-ins** (variants_fn None): choice-free; applied to every REAL-harvest take
  (inline and hosted). Scythe Worker (mandatory-max simplification stands: "you can"
  modeled as take-the-maximum, documented; if partial use ever matters it becomes
  choice-bearing — the old "wide trigger" upgrade path is obsolete).
- **Choice-bearing** (variants_fn given): the use is picked ON the take commit —
  `CommitFieldTake(modifiers=((card_id, variant), ...))`, one commit per combination,
  bare `()` = decline all. Owning one with a legal use is itself what hosts the
  during-window frame. Stable Manure (count vectors over (crop, remaining) donor
  groups), Scythe (one group key; empties one field of it).
- Both implemented members are printed "of each harvest" → fold-ins apply only to a
  real harvest's take (ruling 12); Bumper Crop's played phase runs `field_take` bare.

**The collision bug (found by Scythe's build agent, fixed by the driver).** Fold fns
originally returned their ideal per-cell extras independently; the enumerator offered
the cross-product of modifier choices; two modifiers targeting the same group both
canonicalized to the group's first field in scan order and their summed extras
over-harvested it — tripping the `field_take` assertion on an action the enumerator
had offered as legal. Scythe Worker + Stable Manure on a lone 2-grain field already
collided (pre-existing, latent because amounts had always been 1 before Scythe).

**The fix — claim-aware allocation.** Fold signature is now
`(state, idx, variant, claimed) -> dict | None` where `claimed` maps cells to extras
already allocated. Order: chosen modifiers in combo order (= registration order —
RIGID fixed-demand cards like Stable Manure register before FLEXIBLE ones like Scythe,
and this order is load-bearing for feasibility), autos LAST (Scythe Worker degrades
gracefully — an emptied field has no "additional" grain). A rigid fold returns None
when its demand can't be met under the claims; the enumerator drops that combination
(`fold_chosen_modifiers(...) is None`), so every offered CommitFieldTake is
executable. Scythe picks the max-spare field of its group (composes with a same-group
Stable Manure claim by preferring an unclaimed sibling). Regression tests pin: the
SW+SM 2-grain collision (rigid first, auto degrades), same-group Scythe+SM on ONE
field (feasible and exact), and on TWO fields (distinct-field routing).

**Grain Thief (unbuilt)** is a *replacement*, not an extra ("leave the grain on the
field and take 1 from the general supply instead") — the seam needs a per-cell
skip/replace extension when it lands, and its manifest shape (does a replaced field
emit an entry?) interacts with Lynchet's tile count — decide both together.

## 5. The occasion manifest and the counting rules (rulings 6, 9, 12 + the Slurry bug)

`HarvestOccasion(source, entries)`; each `HarvestEntry` is ONE FIELD:
`(source="cell:r,c", crop, amount, emptied)`. Under ruling 11 a real harvest's field
phase emits exactly ONE occasion (the take, fold-ins included — amounts can exceed 1).

**Counting granularity comes from the printed wording — this shipped a real bug once:**
- "for each grain FIELD that you harvest" / "each harvested field TILE" / "each time
  you take the last X from a field" → count ENTRIES (per field), IGNORE `amount`.
  Slurry Spreader was first written `2 * amount` per emptied grain entry — invisible
  while amounts were always 1, wrong the moment a fold-in emptied a 2-grain field in
  one event (paid 4 instead of 2). Its text pays per emptied FIELD. Barley Mill's
  prompt carried this lesson explicitly and it shipped correct.
- "for each GRAIN/VEGETABLE you harvest" → count UNITS (sum `amount`) — Crack Weeder,
  Potato Harvester.
- "if you harvest at least N X" → sum units once per occasion — Grain Sieve.

**Scoping (ruling 12, the harvest-verb lexicon):**
- "…in the field phase OF A/EACH HARVEST" → phase-scoped: gate on
  `state.phase == Phase.HARVEST_FIELD` (Crack Weeder, Potato Harvester, Slurry
  Spreader). This includes card-granted extras (they're in the take now anyway) and
  excludes a WORK-phase Bumper Crop take.
- Ruled take-only cards (ruling 9: Grain Sieve, Barley Mill — "bonuses are based off
  the specifics of what happened in that action") → gate `occasion.source == "take"`.
  The take source only ever comes from a real harvest's walk, so this also encodes
  harvest-scoping (Bumper Crop passes `source="card:bumper_crop"`).
- UNSCOPED harvest-verb reactors (Food Merchant "for each grain you harvest from a
  field", Field Cultivator "each time you harvest a field tile", the card-field
  self-triggers Melon Patch/Cherry Orchard) → fire on ANY verb-sense harvest,
  a played field phase included. The verb definition (ruling 12): crops moving to the
  player's supply via the FIELD-PHASE EFFECT (wherever it runs) or a literal card
  "Harvest" wording. "remove" (Crop Rotation Field E70) is WIDER — any crop departure
  from the card. The key textual evidence: the E-deck card-field family is a controlled
  experiment (E68/E69 "harvest the last" vs E70 "remove the last" — same family,
  deliberately different verbs). Changeover's "discard" is NOT evidence (the user's
  correction: its discard removes the crop FROM PLAY, not to the supply — a different
  movement entirely).
- The earlier fidelity fix: the delegation prompt had wrongly told the per-occasion
  trio to gate on `source == "take"`; the phase-scoped gate replaced it (a Stable
  Manure veg IS "a vegetable you take from a field in the field phase"). Post-ruling-11
  the two gates coincide for everything in-phase; the difference only matters for
  out-of-phase events.

**Lynchet** (migrated): counts take-occasion ENTRIES whose cell is orthogonally
adjacent to a room — per TILE, amount ignored, `source == "take"`. Why the migration
mattered: the old pre-take sown-adjacent-fields snapshot was extensionally equal in
every reachable state but breaks under Grain Thief (a replaced adjacent field is sown
but NOT harvested).

## 6. Skips (rulings 1, 2→14) and the skip registry

- **Ruling 1 (definite)**: a skipped PHASE has no boundaries — Lunchtime Beer's
  field+breeding skip suppresses every field-segment instant (take included) and every
  breeding-segment instant; feeding and the harvest's outer instants still run.
- **Ruling 14 (2026-07-05, supersedes the recorded ruling 2)**: Layabout's
  whole-harvest skip is TOTAL — before- and after-harvest boundaries INCLUDED
  (every window on the ladder), plus feeding (no cost, no begging) and breeding. The user dislikes
  this reading but rules to follow the official online implementation. (The original
  ruling 2 said outer boundaries survive; it was itself marked contested. History
  preserved in the record.)

Machinery: `register_harvest_skip(card_id, fn)` — per-card predicates
`(state, idx, window_id) -> bool` reading ROUND-KEYED latches in the card's own
card_state (harvest rounds are unique, so stale latches are inert with no clearing
step). The FEED/BREED entry points consult it with the sentinel ids to suppress a
skipper's frames. Lunchtime Beer's latch is set by its optional start-of-harvest
trigger (+1 food); Layabout's at play ("you must" → automatic), targeting
`min(r in HARVEST_ROUNDS if r >= round_number)` — the at-or-after convention (a play
always precedes its own round's harvest; same convention as Bed in the Grain Field).

## 7. The other rulings, compactly, with the reasoning

- **Ruling 4**: Bumper Crop / Harvest Festival Planning "immediately play/carry out
  the field phase" fire the EFFECT, not the phase and not a harvest (HFP's
  clarification: "This is not a harvest and is for you only"). Implementation: bare
  `field_take(state, idx, source="card:<id>")` + `emit_harvest_occasion` — no fold-ins
  (both modifiers are harvest-scoped), no phase-keyed reactors (phase gate), no
  take-only reactors (source gate). Bumper Crop is implemented with non-vacuous
  negative tests (same tableau fires Grain Sieve/Crack Weeder in a real harvest,
  silent through the card).
- **Ruling 10**: the post-breeding timeline — after-the-breeding-phase is INSIDE the
  harvest, end_of_harvest (#16) is the last chance for in-harvest conversions,
  after-the-harvest is outside. Winter Caretaker lives at end_of_harvest;
  Elephantgrass at after_harvest. (Correction to an earlier version of this doc:
  Value Assets is UNIMPLEMENTED — its catalog status is still "todo".)
- **Ruling 18 (2026-07-05)**: "immediately after each harvest" = "after each harvest"
  — the same instant; the ladder's two after-harvest windows merged into one
  (`after_harvest`). This resolved ruling 10's formerly-open ordering question by
  dissolving it. **Standing instruction: the equivalence does NOT generalize — every
  "immediately" in a card text gets its own user ruling, never a unilateral call.**
- **Ruling 19 (2026-07-05)**: the FEED pair collapses too — "immediately after the
  feeding phase" (Social Benefits) = "after the feeding phase" (Farm Store), one
  `after_feeding` window, **Social Benefits first**. The user's key insight: no new
  machinery is needed, because Social Benefits is an automatic effect and Farm Store
  an optional trigger, and the standing within-window ordering (autos before optional
  triggers) already delivers exactly that order. So a player ending feeding with
  exactly 1 food cannot spend it at Farm Store and then collect the "no food left"
  grant — behaviorally identical to the old two-window encoding, one rung shorter
  (pinned by test_social_benefits_resolves_before_farm_store).
- **Ruling 13**: a newborn from a card-granted growth at windows #1/#2 (Autumn Mother,
  Bed in the Grain Field) is fed 1 food — the standard newborn rule, ratified.
- **Ruling 15**: Cubbyhole's on-card food bank is NON-consuming (pays out every
  feeding, never depletes) — the literal reading; the text has no removal clause.
- **Ruling 17**: Baker's on-play "you can take a Bake Bread action" declines WIDE —
  "play Baker and bake" vs "play Baker, decline the bake" are two distinct
  CommitPlayOccupation variants (the Roof Ballaster PLAY_OCCUPATION_VARIANTS
  mechanism). The user REJECTED an after-play-trigger home because it would let the
  granted bake interleave with other after-play triggers in player-chosen order, which
  "when you play this card" does not license. Generalizes to future on-play optional
  grants. The pushed PendingBakeBread is committed once chosen (the variant choice was
  the decline moment) — no per-frame declinable flag was added, consistent with the
  standing invariant that optionality lives at the parent decision.

## 8. Ruling 16 — Shepherd's Whistle (the deepest reasoning chain; read all of it)

Text: "At the start of the breeding phase of each harvest, if you have at least 1
unfenced stable without an animal, you get 1 sheep."

**The modeling problem**: the engine stores animal TOTALS only; placement is derived
from capacity checks and freely rearrangeable — "a stable without an animal" has no
stored fact behind it.

**The ruled meaning (capacity-theoretic)**: a stable is FREE iff the player's current
animals can be accommodated with one unfenced stable removed from capacity. Computed
by handing the standard helpers (`extract_slots`, `can_accommodate`,
`pareto_frontier`) a DOCTORED player with one standalone STABLE cell blanked —
standalone stables are interchangeable for capacity, so which one doesn't matter.
Three cases: no unfenced stable → ineligible; free → the sheep is granted
AUTOMATICALLY (it provably fits — the animals fit without the stable and the sheep
takes it), positioned at start_of_breeding so the granted sheep can breed (tested:
a granted pair breeds when the newborn has room); not free → the player may MAKE one
free (below).

**The make-room frontier — three iterations, each correcting the last:**
1. *Original letter*: reduced-capacity Pareto keep-sets + the sheep; prune options
   identical to or dominated by the current holding (animals-only). Implemented.
2. *The user's dominance concern*: with 2 sheep + a Fireplace, "cook a sheep and let
   the Whistle replace it" ends at 2 sheep + 2 food — strictly better than declining
   (2 sheep + 0) — yet rule 1 pruned it as animal-identical. Question: doesn't the
   usual food-exclusion convention apply? **Answer: no — the convention is a theorem
   with a premise.** Food is excluded because early conversion forfeits optionality
   and the proceeds are obtainable later FROM UNCHANGED HOLDINGS. Here the card
   REPLACES the cooked animal, so nothing is forfeited and the decliner can never
   catch up (cooking later leaves them a sheep down). The premise fails → the
   exclusion doesn't apply to this comparison.
3. *The user's reformulation*: attribute the free sheep to ANY ≥1-sheep ending
   arrangement and compute food by difference; claim: every such ending is reachable
   with the grant. **Rejected on a concrete counterexample**: farm = one 2-cap
   pasture + one unfenced stable + the pet; holding (2 sheep, 1 boar, 1 cattle). The
   ending (2,1,1) fits FULL capacity, but its sheep-decremented form (1,1,1) has three
   TYPES and only two type-buckets remain with the stable removed (pastures are
   single-type) — it cannot fit reduced capacity, so the grant path to that ending
   does not exist and the formula would credit undeliverable food. The general lesson:
   capacity is type-buckets, not slot counts — reachability must be TESTED (the
   keep-set fits reduced capacity), never inferred from the ending.
4. **Final (as amended, implemented)**: the frontier is over animal counts PLUS a
   received-vs-declined dimension, where received dominates declined IFF the player
   has a sheep-conversion opportunity. Food is computed per option but is never a
   frontier dimension. Why this is exactly right: an option that cooked no sheep
   always adds a sheep over declining (survives on animals); an option that cooked a
   sheep survives iff cooking pays (the replacement arbitrage — and at zero rates it
   IS declining, pruned); among received options, animals-only dominance is EXACT
   because food differences equal the deferred cook-value of the animal difference
   (same rates), so no bloat. Declining stays as the frame's Proceed but is
   strategically dead when the replace option exists.

**The generalizable pattern**: any future card that *replaces* a convertible good it
induced you to spend breaks the food-exclusion premise the same way; this ruling is
the template. Conversely: when comparing options that all hold subsets of the same
goods at the same conversion rates, animals-only (goods-only) dominance is exact —
that identity (food difference = deferred cook-value of the goods difference) is
worth re-deriving before trusting any new frontier design.

## 8b. How the user rules — meta-patterns that predict future rulings

- **Official-implementation deference is the recurring tiebreaker.** Twice this arc the
  user ruled AGAINST their own preferred reading to match the official online
  implementation, saying so in the ruling: ruling 3 (whole-FIELD-segment-per-player —
  "the user dislikes it... but it is the simplest start", kept PROVISIONAL, revisit if
  distortive) and ruling 14 (Layabout's total cancellation — "I don't like this, but
  the official online game does it this way and we should follow that", REVERSING the
  user's own earlier ruling 2). When a timing/scope question is ambiguous: check the
  official implementation, expect deference with recorded disagreement, and treat the
  result as revisitable. This is deference, not worship — the user has also called an
  official clarification "a terrible rules decision" (the Shaving Horse separability
  ruling) and solved it by BANNING the card.
- **Rules claims are stress-tested against the catalog before they become rulings.**
  Rulings 11 and 12 were adopted only after full-catalog sweep agents hunted
  counterevidence (verbatim texts + clarifications, producers and consumers swept
  separately); and when the user proposed the Shepherd's Whistle reformulation they
  explicitly asked for a flaw in it ("I am curious if you can find a flaw in this
  reasoning") — the counterexample that answered them reshaped the ruling. Run the
  sweep BEFORE recording; hunt counterexamples in BOTH directions, including against
  the user's own proposals — that is the collaboration they want.
- **The autonomy contract** (stated for the overnight batch, endorsed by results):
  continue until done or blocked on the user; resolve or work around SMALL problems
  (engine bugs, test breakage, census errors — fix, then report prominently); park
  anything that IS a rules reading for the user even with a confident lean, presenting
  the lean and the evidence. Defers by subagents are reviewed, not overridden.
- **C++ byte-identity is NOT a constraint on card-engine design** (user, 2026-07-03,
  recorded in the design doc's constraints): design the Python machinery on its
  merits; if a Family-shape change falls out, re-port to `cpp/` and re-green the
  differential gates. This arc never needed a re-port — but do not contort a design to
  avoid one.
- **Track referents precisely.** After a message listing several open items, a bare
  "ok fix it" was misread once (Winnowing Fan vs Lynchet) — when multiple items are
  live, confirm the antecedent from the user's own thread of attention, not from
  whichever item was mentioned last by YOU.

## 9. Other mechanics built this arc (each with its one-line why)

- **Feeding income** (`register_auto("feeding", …)`): fires at the FEED entry, per
  player SP-first, BEFORE the payment decision — because "in the feeding phase, you
  get X food" must be payable. Consumers: Dentist's payout, Town Hall, Milking Place.
  Choice-free income only; in-feeding CONVERSIONS stay on HARVEST_CONVERSIONS.
- **The budget reset moved**: `harvest_conversions_used` resets at HARVEST ENTRY (not
  at the take) — so a phase-skipping player still gets a fresh budget and future
  anytime-in-harvest conversions start the harvest reset.
- **Post-take re-host** (inline path): after an inline take + occasion autos, the
  during-window trigger check runs ONCE MORE — take income can enable a trigger
  mid-window (Crack Weeder's food affording Cube Cutter's exchange; previously that
  legal play was silently denied). The hosted path never had the gap (live
  enumeration). Eligibility-conditional hosting is equivalent to "offered generally
  pre and post" because state changes at exactly the two checked instants.
- **House-pet negation** (`register_house_pet_negation`): Milking Place's "you can no
  longer hold animals in your house (not even via another card)" — drives
  `house_pet_capacity` to 0, beating Animal Tamer's raise; playing it flags the
  accommodation barrier so a housed animal is evicted through the standard
  keep-or-cook choice.
- **Derived stable supply with card removals** (`register_stable_supply_removal` in
  cost_mods): Market Stall C54's play cost "1 Stable from Your Supply" —
  `stables_in_supply(player) = 4 − built − card-recorded removals`, keeping the
  supply DERIVED (no PlayerState field, no canonical/C++ change; the stored-field
  route the defer analysis proposed remains available if reads get hot).
  `helpers.stables_built` was split out because `4 − supply` would double-count
  removals as buildings (capacity/Tumbrel/heuristic use it).
- **Winnowing Fan** (user ruling): a DIRECT best-rate 1-grain conversion at
  after_field_phase in lieu of a hook-suppressed bake — outcome-identical (the bake
  allocator is greedy-by-rate) and "This is not a 'Bake Bread' action" holds
  structurally (the primitive is never constructed; a probe test proves no bake hook
  fires).
- **Slug collision handling** (Market Stall C54 = `market_stall_c54`; B8 owns the
  name slug): the web UI meta join has a (slug, deck) alias table; doc_gen's
  `IMPL_FIX["C54"]` flipped to True with the reason documented; the JSON row's status
  was deliberately NOT flipped (the by_slug preference logic would let C54 shadow B8).
- **The legacy `harvest_field` seam is GONE** (2026-07-05): `PendingHarvestField`,
  `GameState.field_triggers_offered`, `_fire_harvest_field_autos`, the walk's legacy
  resume-here pause, `register_harvest_field_hook`/`HARVEST_FIELD_CARDS`/
  `should_host_harvest_field`, its enumerator. `_resolve_harvest_field` survives as a
  compat alias (assert HARVEST_FIELD + `_advance_harvest`; many tests drive the walk
  by that name). Removing the GameState field kept the Family canonical contract
  byte-identical (it was default-skipped) — gates confirmed.
- **Wood Rake's re-time** (the fourth mis-timing): "at least 7 goods in your fields
  BEFORE the final harvest" was measured pre-take INSIDE the harvest — indistinguishable
  until Straw Manure (same night) could add vegetables to fields at window #3.
  Re-homed to immediately_before_harvest, round-14-gated.

## 10. Process knowledge that made the waves work

(The generalized version is in auto-memory `feedback_agent_wave_process`; project
process is CARD_BATCH_HANDOFF.md. Deltas specific to this arc:)
- Waves ran off a scratchpad BRIEF file (machinery API + §0.1 verbatim + counting/
  scoping rules + report format) with per-card rulings inline in each prompt. The
  driver held every shared mutable file (cards/__init__.py — agents report their
  import line; the fidelity-lint ALLOWLIST; the progress ledger) and wired them once
  per wave. Two agents may share a test file only with "update ONLY your card's
  tests".
- Accidentally-stopped agents were resumed via SendMessage with a tree-state briefing
  ("X exists — verify before building on it; Y missing") — six recovered with zero
  lost work.
- Agents DEFER correctly when told an approximation is still a defer; the wave's
  defers (Winnowing Fan, Market Stall C54, Baker, Milking Place, Shepherd's Whistle)
  were all correct and all carried precise machinery-gap analyses that later became
  the build plans.
- **Report in GAME terms to the user** — card name, printed effect, what the engine
  can't express and why. Never internal window numbers/seam nicknames; the user was
  twice unable to act on artifact-vocabulary reports (memory
  `feedback_writing_no_hollow_jargon` carries the rule).
- The ledger (`CARD_IMPLEMENTATION_PROGRESS.md`) counts must match the registries
  after every wave (assert `len(MINORS)`/`len(OCCUPATIONS)` against the header lines).
  Current: **195 minors + 96 occupations implemented.**

## 11. Session commit log (2026-07-04/05, chronological)

`1bfdcb5` stage-1 ladder skeleton · `44c584c` A1 growth grant · `2ffcce5`/`6793167`/
`9f30c4c` docs · `acb7341` stage-2 during-window/manifest · `31bbc9c`
emit_harvest_occasion · `e3b12a3` migration wave A (+ the phase-gate fidelity fix) ·
`6636212` ruling 11 record · `64299fe` the take-fold-in seam (Stable Manure + Scythe
Worker reworked) · `268e185` Lynchet → take-occasion · `890578e` new-card wave B (12
cards + the post-take re-host fix) · `183626d` Wood Rake → #1 + legacy seam retired ·
`557da7c` Winnowing Fan + Market Stall C54 · `3d33427` rulings 13-14 · `a2d0904`
feeding income + skip machinery + Lunchtime Beer/Layabout · `2089c65` FEED/BREED batch
(9 cards + the claim-aware fold fix) · `66372eb` Baker/Milking Place/Shepherd's
Whistle (rulings 15-17) · `7d692d5` the received-vs-declined frontier amendment.

## 12. Remaining work, with per-item cautions

**LANDED 2026-07-05 (the breeding/occasion/replace/feeding wave — seven cards + four
seams, rulings 20-21 + the flagged Grain Thief reading):** Stone Importer (the breed
frame's pre-commit "breeding" triggers — ruling 20), Fodder Planter + Slurry Spreader
C71 (the breeding-outcome payload + capped/uncapped granted sows off the frame's
post-commit "breeding_outcome" stretch), Grain Thief (the replace-kind order-0
unscoped take-modifier; a replaced field emits NO manifest entry — RATIFIED as user ruling 2026-07-06,
and it surfaces at Bumper Crop via PendingCardChoice), Potato Ridger + Food Merchant
(the PendingHarvestOccasion optional-reaction host; Potato Ridger's 4+ tier is an
AUTO per ruling 21, with the host's autos_fired excluding its optional tier on the
same occasion), Child's Toy (the feeding_requirement chokepoint + fold — NOT delicate
after all: food_owed is a memo-key argument, so no cache hazard). Dung Collector
stays deferred (any-source newborns — never stretch the outcome event to it).

**Delicate — engine cores, extra care:**
- **Dolly's Mother — LANDED 2026-07-06** (the user's greedy-strip plan): the
  sheep-only card slot = the standard accommodation problem with a parked sheep
  removed and added back (exact by dominance; `helpers._sheep_slot_strip` /
  `accommodates`); single-parent breeding threads `sheep_min` as an ARGUMENT
  through `breeding_frontier`/`breeding_food_gained` (memo-key-joined — the
  feared cache hazard never arises). The two audit-found traps are pinned by
  tests: the breeding-outcome newborn report uses the card-aware threshold,
  and the strip reaches every accommodation decision point (barrier, markets
  via pareto_frontier, Shepherd's Whistle's doctored tests).
- **Old Miser [4]** (per-person feeding discount): rides the same
  `register_feeding_requirement` fold Child's Toy proved out; 4-player-only, so it
  waits for the 4p work, not for machinery.

**Bigger chunks:**
- **Card-fields** (§6): Beanfield, Lettuce Patch, Melon Patch, Cherry Orchard,
  Artichoke Field, Crop Rotation Field, Patch Caregiver, Wood Field, Rock Garden —
  crops living in CardStore, iterated by `field_take` alongside board fields (the
  manifest's `source="card:<id>"` entry shape was designed for this). Note their
  self-triggers' verb scoping from §5 above (E70's "remove" is any-departure).
  **RULING 32 (2026-07-06, the user: "very important"): a card-field is NOT a
  "field tile"** — its manifest entries never count for per-TILE readers (Field
  Cultivator already filters to "cell:" entries with a pinned test; every future
  per-tile card must do the same).
- **The anytime-in-harvest converters** (§10 of the design doc): Braid Maker, Basket
  Carrier, Ebonist, Stone Sculptor, Lumber Virtuoso + Furniture Carpenter's approved
  #16 anchor. Sub-questions (7)(8)(9) there are still the user's.

**Awaiting a user ruling:** nothing — both "immediately" pairs were ruled 2026-07-05
(rulings 18/19, both merged; ruling 19 put Social Benefits before Farm Store via
autos-before-triggers). The standing instruction stands: every FUTURE "immediately"
in a card text gets its own user ruling before encoding.

**Banned, never implement:** Witches' Dance Floor D25, Begging Student D97, Shaving
Horse A48 (Treegardener's clarification interaction with it is moot).

---

# PART II — the 2026-07-05 → 06 continuation (appended at session end, context ~800k)

> Part I above covers the arc through the FEED/BREED batch and rulings 1–17. This part
> covers everything after: rulings 18–41, three card waves + the arrangement trio (the
> catalog now at **206 minors + 103 occupations**, suite ~4,240 green, C++ gates green
> throughout — no re-port was ever needed), and the fully-specified build queue the next
> session executes. The ruling RECORD is `CARD_DEFERRED_PLANS.md` (41 numbered, dated);
> this part explains the reasoning and — per the user's explicit instruction for this
> handoff — **collects the general/meta-level instructions the user gave**, which bind
> future sessions as much as any ruling.

## 13. Meta-instructions from the user (2026-07-05/06) — READ THESE FIRST

1. **Every "immediately" in card text gets its own per-instance ruling** (ruling 18's
   standing instruction; auto-memory `feedback_ask_on_immediately`; CARD_AUTHORING_GUIDE
   §2). Ruling 18 collapsed "immediately after each harvest" = "after each harvest" and
   ruling 19 collapsed the feeding pair — but the user was explicit the equivalence does
   NOT generalize: surface each occurrence with its mechanical stakes and wait.
2. **Mandatory + choice-free = automatic, never a forced singleton button** (ruling 21).
   The user, on Potato Ridger's "you must do so": prefer the effect firing with no
   player input over a forced offer. Generalizes: align with the engine's standing
   automatic-effects classification whenever a "must" has no real choice.
3. **Full test suite per GROUP of cards, not per card** (auto-memory
   `feedback_full_suite_per_group`): targeted tests per card-only change; the
   multi-minute sweep at group boundaries and ALWAYS with engine-file edits.
4. **Web-UI label style: mechanical and terse, card name included** — the user:
   "in general i prefer more mechanical and less verbose, the player can interpret
   meaning from the card description." E.g. "Shepherd's Whistle: activate, keep
   sheep=2, boar=1"; "Beer Stall: convert 2, keep boar=1". Zero-count entries omitted.
5. **Same-instant arrangement-conditioned benefits need ONE shared arrangement**
   (the user's own caution, recorded in CARD_AUTHORING_GUIDE §2): two cards reading
   the same instant may not pass independent exists-an-arrangement tests — a joint
   test is a stop-and-design moment. Across different instants, independent tests are
   correct (real Agricola allows rearranging between moments). No same-instant pair
   exists yet.
6. **Reversibility calculus governs design pacing.** The user repeatedly attached
   "we can change this later" to rulings (free-span buys r36, the frontier boundary
   r37, the feeding-unfolded call under r34) and reasoned explicitly about direction:
   the feeding fold was rejected because it is "difficult to reverse (because it
   breaks the no card AI) and fairly easy to implement later." Prefer the
   cheap-to-reverse default; treat hard-to-reverse changes as defer-worthy; RECORD
   revisitability on the ruling.
7. **Some machinery questions need dedicated design sessions, not in-chat improvisation.**
   The user on Gypsy's Crock: "We need to think more carefully about it than you are
   doing right here." (Ruling 35 parks it: the event-granularity of feeding
   conversions.) When a question of that class appears, park it loudly — do not
   half-design it while discussing something else.
8. **The user supplies algorithms; the assistant's job is to formalize and hunt traps —
   in BOTH directions.** This session the user designed the greedy strip (Dolly's
   Mother), the per-pasture max-fill test (Mineral Feeder), the per-conversions-taken
   frontier (Beer Stall), and the height-group encoding (Craft Brewery) — each adopted
   after formal verification. The assistant's value-add was the traps (the newborn
   report the greedy plan would have missed; the capacity call-site sweep; the Social
   Benefits counterexample that killed the late anchor) and exactness proofs (max-fill,
   the strip-shift). Symmetrically, the user falsified two assistant claims ("exactly
   one candidate identical to Proceed"; "cooking a sheep can never help") — expect
   claims to be stress-tested, concede cleanly, and never present an unverified
   dominance argument as settled (§0.1's "I can't find a counterexample" warning keeps
   being vindicated).
9. **Keep the user's architecture model synced.** The user was unaware
   `PendingHarvestWindow`/`PendingFieldPhase` existed and thought `PendingHarvestField`
   still did ("i am really confused"). When explaining machinery, correct the frame
   inventory explicitly and explain top-down (the resolution that worked: the walk
   cursor is the "which moment" indicator promoted to GameState; per-moment frames are
   standard hosts; `PendingHarvestFeed.conversion_done` and `PendingFieldPhase.take_fired`
   ARE the familiar phase flags). See §17 below for the settled inventory.
10. **Doc regeneration must not erase hand-recorded rulings.** Regenerating the ledger
    from stale generator inputs ERASED the D25/D97 ban markers once; the fix was making
    the bans durable in the generator's own source (doc_gen PATCH text + snapshot
    status) — the standing procedure is now: refresh the snapshots' implemented-flags
    from the live registries, then run doc_gen (see §16.7).

## 14. Rulings 18–41 quick map (full text in CARD_DEFERRED_PLANS.md)

- **18/19** "immediately after" merges (harvest + feeding pairs; ladder now 15 ids;
  Social Benefits before Farm Store via autos-before-triggers) + the standing
  per-"immediately" instruction.
- **20** breed-frame triggers fire BEFORE CommitBreed (Stone Importer); outcome grants
  after it. **21** mandatory choice-free = auto (Potato Ridger 4+; autos_fired
  two-tier exclusivity). **22** a Grain-Thief-replaced field is NOT harvested (no
  manifest entry, invisible to all per-field/tile/unit readers).
- **23** Eternal Rye tiers exclusive. **24** minor on-play choices surface WIDE
  (PLAY_MINOR_VARIANTS; Facades Carving). **25** Field Cultivator counts TILES,
  k-at-once. **26** Earthenware Potter = after_harvest@round-14, free k choice.
  **27** Feed Pellets (mid-feed grant via the barrier; once per feeding total).
  **28** Craft Brewery wide by field HEIGHT (conversion variants seam).
- **29** Mineral Feeder (pastured-sheep = exists-arrangement via per-pasture MAX-FILL;
  cook-to-qualify options; landed). **30** Beer Stall (frontier over animals PER
  conversions-TAKEN k, exchanges bundled into the options — dissolved the cook-first
  sequencing defer; landed).
- **31** Uncaring Parents stacks with the stone-house-bonus cards. **32** a card-field
  is NOT a "field tile" (the user: "very important"; Field Cultivator filters to
  "cell:" entries). **33** the Lynchet same-height interchangeability gap is a KNOWN
  deferred approximation (conditional adjacency-aware group keys are the agreed
  eventual fix).
- **34** the generalized conversion frontier lands on the mid-harvest food-raise frame
  ONLY; feeding stays un-folded (reversibility + the r35 granularity question).
  **35** Gypsy's Crock parked for dedicated design. **36** the food→resources/points
  buys are FREE-SPAN (the late anchor is DEAD — its dominance argument fell to the
  Social Benefits counterexample; Furniture Carpenter migrates). **37** frontier
  integration = PURE goods→food converters only; rider outputs are standalone
  free-span triggers. **38** Lumber Virtuoso free-span [3+]. **39** the post-breed
  cooking floor, SHORTHAND form (stateless: a type at >= 3 current can't cook below 3;
  >= 2 / below 2 for sheep + Dolly's Mother) — the user kept the shorthand knowing it
  slightly over-protects the capacity-blocked corner; NO breed-record needed.
  **40** FEED/BREED band whole-phase-per-player like FIELD; the four OUTER moments
  (immediately-before/start-of-harvest, end-of-harvest, after-harvest) stay SHARED
  both-players windows. **41** Field Cultivator flips to AUTOMATIC-take-the-maximum
  (Scythe Worker precedent) — NOT yet implemented, queued.

## 15. What Part II landed (state at handoff)

Waves: the breeding/occasion wave (Stone Importer, Fodder Planter, Slurry Spreader
C71, Grain Thief, Potato Ridger, Food Merchant, Child's Toy — 7 agents + 4 driver
seams: breed-frame triggers, the BreedingOutcome payload, PendingHarvestOccasion, the
replace-kind TakeFold); the after-harvest wave (Value Assets, Uncaring Parents,
Eternal Rye Cultivation, Field Cultivator, Earthenware Potter, Facades Carving, Craft
Brewery, Feed Pellets — 8 agents + 2 driver seams: PLAY_MINOR_VARIANTS,
HarvestConversionSpec.variants_fn); the arrangement trio built BY THE DRIVER
(Dolly's Mother — greedy strip + sheep_min threading; Mineral Feeder; Beer Stall).
Every harvest-arc defer is now implemented or parked by explicit user decision.
Infrastructure: the qualified canonical default-skip ("Type.field"), the action
wire-encoding variant skip (Family byte-identity preserved for
CommitHarvestConversion), helpers.accommodates (the ownership-aware capacity entry),
feeding_requirement chokepoint, the ledger-regeneration procedure. Docs:
CARD_ENGINE_IMPLEMENTATION.md received the full fold-in (a parallel session) + this
session's amendments — it is CURRENT. HARVEST_CARDS_REVIEW.md's implemented-markers
are ~20 cards STALE (regenerate before trusting).

## 16. THE BUILD QUEUE (next session, in order, with per-item cautions)

1. **DONE 2026-07-12 (`479135e`) — FEED/BREED banding (ruling 40)** + the C++
   re-port, all 139 gates green. Three per-player bands (26-position virtual walk);
   one frame per band pass with per-pass feeding income; the cursor CARRIED while
   band frames are up (Family pauses 14/17/20/23 — the predicted Family-visible
   change; Family decision ORDER unchanged); phase derived from the walk position
   (flips at band entries); `_initiate_harvest_feed/_breed` kept as legacy test
   helpers (bare states resume at the second pass's after-window). The encoder's
   `has_fed` became band-aware — value-identical at every decision state, no
   ENCODING_VERSION bump. Every caution (a)-(d) played out as predicted.
2. **DONE 2026-07-12 (`4b651de`) — Field Cultivator → automatic-max (ruling 41)**: the
   occasion trigger became an occasion AUTO taking min(tiles, pile remaining); the
   "cell:"-only tile filter (ruling 32) and its pinned test kept; choice tests
   rewritten as automatic-fire tests.
3. **DONE 2026-07-12 (`444a679` the frontier core, `982c2ce` the raise-frame
   wiring, `f084826` the cards) — the converter cluster (rulings 34–39)**, the
   last harvest machinery. Landed: the generalized food_payment_frontier
   (span_converters subsets + ruling 39's floors, BOTH outside the cached core
   — zero new cache surfaces), HarvestConversionSpec.frontier_fire (the three
   craft majors + Stone Carver + Paintbrush's food branch reach the raise
   frame), in_conversion_span / post_breed_floors / available_span_converters,
   CommitFoodPayment.conversions, register_free_span_trigger (eleven surfaces
   per call; the feed frame is covered by the card's own conversion entry —
   one shared budget), and the cards: Stone Carver D108, Basket Carrier C105,
   Paintbrush E39 (one budget, three surfaces), Furniture Carpenter's
   free-span migration. The ruling-36 Social Benefits line is pinned. Braid
   Maker E109 DEFERRED whole (the play-minor major-build gap — recorded in
   CARD_DEFERRED_PLANS.md with a build proposal); Lumber Virtuoso [3+] was
   moved to the AMBIGUITY defers 2026-07-12 (its "discard down to 5 wood"
   clause; ruling 38's timing stands if un-deferred). USER
   FLAGS: the breeding-SKIPPER corner of ruling 39's stateless floor
   (over-protects a skipped player's animals — same accepted class as the
   capacity-blocked corner, but not explicitly ruled). Cooking Hearth
   Extension stays OUT (ruling 42).
   The build spec below is the historical record of the derivation:
   **PROGRESS 2026-07-12: step (a) — the generalized frontier core —
   is LANDED (`444a679`, helpers.food_payment_frontier + _food_payment_generalized
   + _food_payment_counts, 10 seam tests in tests/test_food_payment_generalized.py;
   the floors/converters sit OUTSIDE the cached core — no cache-key change at
   all, better than the spec's "keys extended"). NEXT: steps (b) the state-side
   derivations (available span converters — needs a purity flag or registry
   distinguishing pure goods->food HARVEST_CONVERSIONS entries from
   side-effect-bearing ones like Craft Brewery/Beer Keg/Furniture Carpenter,
   which are NOT frontier-eligible per ruling 37 — plus post_breed_floors(state,
   idx) reading cursor > sentinel_position("breeding", pass) and the breed
   frame's breed_chosen; sheep floor = capacity_mods.sheep_min_parents + 1;
   NOTE the breeding-SKIPPER corner: the stateless floor over-protects a
   skipped player's animals — same accepted class as ruling 39's
   capacity-blocked corner, FLAG to the user), CommitFoodPayment.conversions
   wiring (enumerator legality.py:~2676 + executor resolution.py:~630), then
   (c) the free-span helper and (d) the cards. DRIVER BUILD SPEC (build from
   this, don't re-derive):**
   (a) `food_payment_frontier(player_state, food_owed, rates)` gains two
   MEMO-KEY-JOINED arguments (the Dolly's Mother pattern — passed through both
   the baseline and `_food_payment_frontier_opt`/`_food_payment_points` paths,
   keys extended, no cache hazard): `span_converters: tuple` of
   (conversion_id, input_good, food_out) for each 0/1-fire converter currently
   available, and `animal_floors: tuple` (sheep, boar, cattle) for ruling 39.
   Converters are BINARY fires (the existing HARVEST_CONVERSIONS shape: fixed
   input_cost -> food_out, once per harvest): enumerate subsets S (tiny — <=
   ~5), food(S) offsets food_owed, and the Pareto space gains one
   remaining-count dim per DISTINCT building resource touched (wood/clay/
   reed/stone). Floors clip animal consumption caps: consumable = count - F
   when count >= F else count (F = 3, or 2 for sheep with Dolly's Mother —
   ruling 39's stateless shorthand; F applies only POST-BREED-for-that-player
   within the harvest, derived from phase/cursor vs the player's breed pass).
   (b) The CALLER (the PendingFoodPayment enumerator in legality.py) computes
   both args from state: converters = registered pure goods->food entries
   (the 3 craft majors + Stone Carver + Braid Maker) that are owned, in-span,
   and budget-unused (`conversion_id not in harvest_conversions_used` — the
   budget is SHARED with the feed-phase craft seam); in_span(player) = a
   harvest phase AND the walk has reached that player's FIELD band start
   (positions 2/7 for SP/other; before_field_phase vs start_of_field_phase is
   an unreachable corner today — no in-band cost frame exists — note it in the
   docstring). `CommitFoodPayment` gains `conversions: tuple[str,...] = ()`
   (card-only action, never on the Family wire — no C++ concern);
   `_execute_food_payment` debits the converter inputs, adds their food, and
   marks each fired id in harvest_conversions_used.
   (c) The free-span helper (`register_free_span_trigger(card_id, ...)` in
   harvest_windows.py): registers the card's optional trigger on every ladder
   window from before_field_phase through end_of_harvest + the "field_phase"
   during-event + a feed-frame surface (the craft seam or the frame's trigger
   stretch) — one helper, not 10 manual rows. Members: the rider-output buys
   (ruling 37): Basket Carrier, Paintbrush (one card, two output variants),
   Stone Sculptor when built; Lumber Virtuoso [3+] (ruling 38); Furniture
   Carpenter MIGRATES off its FEED-only seam here (update its ALLOWLIST/
   fidelity notes).
   (d) Pin the now-legal Social Benefits line: an in-span buy after feeding
   can deliberately zero food before the after_feeding check.
   Cooking Hearth Extension is OUT (ruling 42, deferred with Gypsy's Crock).
   TEXT-DERIVED REFINEMENTS (verbatim texts pulled 2026-07-12): Stone Carver
   D108 occ "turn exactly 1 stone into 3 food" — pure converter, frontier +
   craft seam. Braid Maker E109 occ: the reed->2-food clause is a pure
   converter, but the card has a SECOND clause ("You can build the
   Basketmaker's Workshop for 1 reed and 1 stone even when taking a 'Minor
   Impr.' action") needing the build-major-via-minor-action surface — assess
   that machinery separately; if it doesn't fit exactly, the CARD defers
   (both clauses) while the converter seam still lands via Stone Carver.
   Paintbrush E39 minor (1 wood, prereq 1 boar): "exchange exactly 1 clay for
   your choice of 2 food or 1 bonus point" — the FOOD branch is itself a pure
   converter (frontier + craft seam); only the VP branch is the ruling-37
   rider (free-span standalone); one conversion_id, shared once-per-harvest
   budget across both branches. Basket Carrier C105 occ: "Once each harvest,
   you can buy 1 wood, 1 reed, and 1 grain for 2 food total" — free-span
   rider. Lumber Virtuoso D129 is [3+]: per the Old Miser precedent it waits
   for the 4p work, NOT machinery — design the free-span helper to fit it,
   don't implement the module. Furniture Carpenter B101 (implemented,
   feed-seam `HarvestConversionSpec(food=2 -> bank 1 VP)` + scoring term, no
   ALLOWLIST note) migrates to free-span.
   FRONTIER-SHAPE DECISIONS (derived 2026-07-12, final layer): (1) the
   extension WRAPS the existing cached crop/animal core — subsets S of the
   binary converters are enumerated OUTSIDE it (inputs(S) must fit available
   building resources; food(S) offsets owe; the core runs at
   max(0, owe - food(S)) per S), so no new cache surface exists; ties on the
   full 9-good vector keep the SMALLER fired set (fewer burned budgets
   dominates — deliberate tie-break, document it). (2) RETURN SHAPE SWITCH:
   with span_converters == () the function returns the legacy 5-tuples
   (every existing caller unchanged); non-empty -> ((g,v,s,b,c,w,cl,r,st),
   fired_ids) pairs. (3) owe == 0 offers NO fires (deferring a budget
   preserves optionality — the span continues). (4) animal_floors applies
   ONLY to the raise frame: the FEED payment is always pre-breed under the
   banding (p's feed pass precedes p's breed pass), and the breed commit's
   bundled cooking is its own machinery; derive "p has bred" from cursor >
   sentinel_position("breeding", pass_of(p)) AND p's breed frame (if still
   up) records a done commit — check PendingHarvestBreed for its commit flag
   when building; floors formula: consumable = count - F if count >= F else
   count (F=3; sheep F=2 with Dolly's Mother in play).
   Original spec follows. Driver seams first: (i) the generalized `PendingFoodPayment` frontier —
   crops + animals + capped building-resource conversions, liveness derived from
   phase/cursor (the span = field phase start → end_of_harvest; a pre-field-phase
   cost like Autumn Mother's sees none), budgets shared with the feeding crafts via
   `harvest_conversions_used`, and **ruling 39's stateless cooking floor applied to
   any post-breed animal cooking**; (ii) free-span trigger membership (a card
   registered on every in-span window + the field_phase event + the feed craft seam —
   design a span-registration helper rather than 10 manual rows). Then the cards:
   Stone Carver + Braid Maker (pure converters: frontier + feeding craft), Basket
   Carrier + Paintbrush (rider outputs: standalone free-span; Paintbrush = one card,
   two output variants), Furniture Carpenter's
   migration off the FEED-only seam to free-span (its ALLOWLIST/fidelity notes
   update), and the three craft majors reachable through the raise frame in-span.
   Cooking Hearth Extension is OUT of this cluster (ruling 42, 2026-07-12):
   deferred alongside Gypsy's Crock until the user decides how cooking-modifier
   cards are implemented.
   CAUTION: the Social Benefits interaction is now legal CONTENT (a free-span buy
   before the after-feeding check can deliberately zero food) — pin it with a test.
4. **DONE 2026-07-12 (`70714fe` the seam, `f0f7999` the labels) — the label pass**:
   display.register_action_labeler / variant_label (pure string→string — the
   encodings carry their own numbers, so no state threading was needed); twelve
   per-card labelers in one authorial voice (§13.4's mechanical style); play_web
   routes all four variant surfaces through the registry (FireTrigger,
   CommitHarvestConversion, CommitFieldTake modifiers, CommitPlayMinor
   variants). Food Merchant's label omits the price (cost depends on occasion
   state not in the variant string — documented). The contextual decline label
   was NOT built (optional in the spec; nothing demanded it).
5. **DONE 2026-07-12 (`f427f71` seams, `329c8cd` the nine cards, `860fd5a` the reader
   sweep) — the card-fields wave**, rulings 43–48. The machinery is
   `agricola/cards/card_fields.py` (per-stack CardStore state, ruling-45 count helpers,
   `CommitSow.card_sows` + `PendingSow.crops_only` — Family-default-skipped, gates
   stayed green with no C++ re-port); all nine cards implemented; every implemented
   "field(s)"-reading card swept (26 modules); the NON-take-removal chokepoint
   (`remove_card_crop`, ruling 44) landed with Craft Brewery × Crop Rotation Field as
   its proven consumer pair. OPEN ITEM flagged to the user: Scythe E73's "harvest all
   the crops planted in it" on a MIXED field (Heresy Teacher's veg below grain — grid
   or card alike) takes only the grain (pre-existing take-precedence limitation,
   documented in scythe.py). Witches' Dance Floor stays BANNED.
6. **DONE 2026-07-12 (`25c84a0` the ladder, `3146fe6` the cards) — the round-end
   mechanism** (rulings 49-51): the seven-step ladder (end_of_work → after_work →
   start_of_returning_home → returning_home [PRE-reset: the live board is the
   event data] → the reset → after_returning_home → end_of_round) walked by
   engine._advance_round_end with GameState.round_end_cursor (card-only;
   Family byte-identical, no C++ change). Six cards landed: Credit, Sculpture
   Course, Swimming Class, Lifting Machine, Silage, Baking Course (ruling 51:
   a Fireplace-like global 2/grain source). Perennial Rye + Lumber Virtuoso
   went to the new DEFERRED-FOR-AMBIGUITY category (ruling 50). OPEN USER
   FLAG: Dolly's Mother × Silage — the spec routes Silage's sheep threshold
   through sheep_min_parents, but Dolly's printed scope is "during the
   breeding phase of a harvest"; a strict reading keeps Silage at 2.
   **THE QUEUE IS COMPLETE.** Post-queue rulings 52/53 (2026-07-12/13):
   Silage's threshold is a flat 2 (Dolly's Mother's seam does not reach the
   mid-round breed); Heresy Teacher is UN-implemented into the ambiguity
   defers (archive/deferred_cards/) — mixed fields are unreachable, mooting
   the Scythe-E73/group-key flags. Ruling 39's record was CORRECTED
   2026-07-13 (the "capacity-blocked over-protection" claim was wrong — the
   floor is exact there; the real unruled corner is the breeding-SKIPPER,
   plus the unreachable post-breed-gain class). The ambiguity category is
   now DURABLE in the ledger (doc_gen AMBIGUOUS_MIN/OCC tables + snapshot
   status "ambiguous" + the ❓ marker/section). What remains beyond the
   queue: the rest of CARD_DEFERRED_PLANS (largely user-gated clusters +
   the ambiguity defers), the C++ card port, the card-game agent.

7. **Ledger procedure** (do this at every integration): refresh the snapshots'
   implemented-flags from the live registries
   (`scripts/card_classify/data/{minors,occ}_cards.json`, set `implemented = slug in
   registry`), THEN run `scripts/card_classify/doc_gen.py`; assert the printed counts
   match `len(MINORS)`/`len(OCCUPATIONS)`. Bans and slug-collision cards live in
   doc_gen's PATCH/IMPL_FIX tables (durable), never as hand-edits to the output.

## 17. The settled frame inventory (the user-model sync of §13.9)

`PendingHarvestWindow` (per-moment, per-player choice host — stage 1, commit 1bfdcb5),
`PendingFieldPhase` (the field-phase during-host: the take + free-order triggers,
`take_fired` gate — stage 2), `PendingHarvestFeed` (the PAYMENT step only, not the
phase: crafts/Beer Stall + CommitConvert + Stop; `conversion_done` is its phase flag),
`PendingHarvestBreed` (the breeding decision: pre-commit "breeding" triggers +
CommitBreed + post-commit "breeding_outcome" grants + Stop), `PendingHarvestOccasion`
(optional reactions to one emitted occasion; carries the occasion + `autos_fired` —
this Part), and `PendingPreparation` (start-of-round, outside the harvest).
**`PendingHarvestField` no longer exists** (retired 2026-07-05). The sequencing
BETWEEN moments is `GameState.harvest_cursor` (the walk); frames pause it; the decider
is always `pending_stack[-1].player_idx`.
