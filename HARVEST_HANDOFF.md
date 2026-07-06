# Harvest-Window Arc — Session Handoff (2026-07-03 → 2026-07-05)

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
VIRTUAL index — see §3) and a Family game never sets the cursor or hosts a frame
(byte-identical, C++ gates untouched — every change in this arc was card-only or
Family-invisible, verified by the differential gates at every commit).

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
window-major (both players per window, SP first). FEED/BREED are NOT banded yet —
deferred until a member card's ordering depends on it.

Implementation: `harvest_cursor` indexes a VIRTUAL walk — the raw ladder with the
FIELD band repeated once per player (`walk_position(cursor, sp)` decodes; 21 positions
at 2 players since the 2026-07-05 after-harvest window merge; N players = N band
repeats, the shape 4p needs). The stakes the user
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
unscoped take-modifier; a replaced field emits NO manifest entry — flagged reading,
and it surfaces at Bumper Crop via PendingCardChoice), Potato Ridger + Food Merchant
(the PendingHarvestOccasion optional-reaction host; Potato Ridger's 4+ tier is an
AUTO per ruling 21, with the host's autos_fired excluding its optional tier on the
same occasion), Child's Toy (the feeding_requirement chokepoint + fold — NOT delicate
after all: food_owed is a memo-key argument, so no cache hazard). Dung Collector
stays deferred (any-source newborns — never stretch the outcome event to it).

**Delicate — engine cores, extra care:**
- **Dolly's Mother** (sheep breed with 1 instead of a pair): the breeding-eligibility
  fold touches `breeding_frontier`, which is MEMOIZED with projection keys
  (FRONTIER_OPT_DESIGN.md). A card-dependent input MUST join the cache key or the
  cache must flush on ownership change — the classic hidden-global-input footgun the
  opt design warns about. Do not bolt the fold on without re-reading that doc.
- **Old Miser [4]** (per-person feeding discount): rides the same
  `register_feeding_requirement` fold Child's Toy proved out; 4-player-only, so it
  waits for the 4p work, not for machinery.

**Bigger chunks:**
- **Card-fields** (§6): Beanfield, Lettuce Patch, Melon Patch, Cherry Orchard,
  Artichoke Field, Crop Rotation Field, Patch Caregiver, Wood Field, Rock Garden —
  crops living in CardStore, iterated by `field_take` alongside board fields (the
  manifest's `source="card:<id>"` entry shape was designed for this). Note their
  self-triggers' verb scoping from §5 above (E70's "remove" is any-departure).
- **The anytime-in-harvest converters** (§10 of the design doc): Braid Maker, Basket
  Carrier, Ebonist, Stone Sculptor, Lumber Virtuoso + Furniture Carpenter's approved
  #16 anchor. Sub-questions (7)(8)(9) there are still the user's.

**Awaiting a user ruling:** nothing — both "immediately" pairs were ruled 2026-07-05
(rulings 18/19, both merged; ruling 19 put Social Benefits before Farm Store via
autos-before-triggers). The standing instruction stands: every FUTURE "immediately"
in a card text gets its own user ruling before encoding.

**Banned, never implement:** Witches' Dance Floor D25, Begging Student D97, Shaving
Horse A48 (Treegardener's clarification interaction with it is moot).
