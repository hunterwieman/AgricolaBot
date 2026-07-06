# Deferred-Card Design Plans (Artifex / Bubulcus + rescued base cards)

_Written 2026-06-30 (overnight autonomous session). The companion to `CARD_BATCH_TRIAGE.md`
(the 67 implemented this session) — this doc covers everything **deferred**, clustered by the
single mechanism/decision that blocks each cluster, with a concrete build proposal, effort/risk,
and the questions only you can answer. Goal: a fast morning decision surface — approve a group
and I build every card in it._

The clusters are ordered **cheapest-and-highest-yield first**. Group A items are small, well-scoped
engine additions that each unblock multiple cards and keep the Family game byte-identical. Group B
needs more design care. Group C is the deliberate engine boundaries (a real design decision). The
long tail of genuinely-blocked cards (geometry, new shared spaces, return-home hooks, randomness,
temp extra workers, hidden round-space identity, card-as-animal-holder, per-card goods stacks) is
summarized at the end — those need substantial new subsystems and are correctly deferred.

> Convention reminder (verified this session): a card-only field added to `PlayerState`/a pending
> must default to a Family-game value and be added to the manual `__hash__` + `canonical._DEFAULT_SKIP_FIELDS`,
> so the Family game stays byte-identical and the C++ gates stay green. Every Group-A/B plan respects this.

---

## PRIORITY: three mis-timed harvest cards awaiting the user's disposition (2026-07-02)

**The problem.** A 2026-07-02 fidelity audit found three **implemented, live** harvest cards whose
printed timing is *not* the feeding phase but which were implemented as feeding-phase conversions
(entries in the `HARVEST_CONVERSIONS` registry, surfaced during HARVEST_FEED). The implementing
sessions justified the shift with neutrality arguments written into their own docstrings ("the
established, accepted approximation") — **never ratified by the user**, and the user has since
ruled (CARD_AUTHORING_GUIDE.md §0.1; CARD_ENGINE_IMPLEMENTATION.md §6, first ruling) that such
shifts are never acceptable: a card is implemented exactly as printed or it is deferred. The
audit was systematic (a census of every non-builtin `HARVEST_CONVERSIONS` registrant and every
`HARVEST_FIELD_CARDS` member against its printed text, plus a repo-wide self-ratification-language
lint) — **these three are the complete set**; every other harvest card is faithful.

**The three cards and their exact deltas:**

1. **`cube_cutter`** (occupation, C98). Text: *"In the field phase of each harvest, you can use
   this card to exchange exactly 1 wood and 1 food for 1 bonus point."* Implemented during FEED.
   The shift is **permissive**: at FEED the player can first cook wood→food (Joinery / craft
   conversions fire in FEED) and pay *that* food; at the printed field-phase timing the food must
   already be on hand before any feeding conversions run.
   **Remedy available TODAY**: the field phase now has an optional-choice host — commit 9c785e7
   built `PendingHarvestField` trigger surfacing (with a Proceed decline) for Stable Manure, under
   a user ruling. Re-time cube_cutter onto a `harvest_field` optional trigger (keep once-per-
   harvest bookkeeping; the VP bank in CardStore + `register_scoring` stays as-is), drop its
   `HARVEST_CONVERSIONS` entry, and rewrite the docstring with the faithful timing.

2. **`winter_caretaker`** (occupation). Text: *"At the end of each harvest, you can buy exactly
   1 vegetable for 2 food."* Implemented during FEED. The shift is **restrictive**: food gained in
   the breed phase (`breeding_food_gained`) cannot be used, and the buy competes with feeding.
   **No faithful hook exists yet** — "end of each harvest" is post-BREED, which is exactly the
   territory of the user-gated round-end / after-feeding designs below (`PendingRoundEnd` /
   the `PendingHarvestFeed` after-phase). Options: re-defer (Farm Store precedent), or hold until
   that machinery is approved and built, then re-time.

3. **`elephantgrass_plant`** (minor). Text: *"Immediately after each harvest, you can use this
   card to exchange exactly 1 reed for 1 bonus point."* Implemented during FEED. No concrete
   behavioral delta was found (reed does not move during FEED/BREED) — but per the fidelity
   ruling that is a reason to ask, not to keep. Same options as winter_caretaker (its faithful
   window is the same post-harvest instant), **or** the user may explicitly ratify the FEED seam
   for this card with a dated ruling.

**Per-card dispositions available to the user:** (a) **re-time** onto the correct hook
(cube_cutter: possible now; the other two: after the round-end/after-feeding build);
(b) **re-defer** — the Farm Store precedent: move module + test to `archive/deferred_cards/`,
unwire from `agricola/cards/__init__.py`, record here; (c) **ratify as-is** with an explicit
dated ruling added to the docstring.

**Mechanics for whichever session executes** (all card-only — Family byte-identity and the C++
gates are untouched): each card's entry in the `ALLOWLIST` of
`tests/test_card_fidelity_lint.py` MUST be removed as part of its resolution (the lint then
enforces the outcome); on a re-time, verify once-per-harvest scoping survives the registry move;
on a re-defer, update `CARD_IMPLEMENTATION_PROGRESS.md` and CARD_ENGINE_IMPLEMENTATION.md §1's
census; run the full suite. Read CARD_AUTHORING_GUIDE.md §0.1 before starting — the fidelity
rule, including its subagent clause, governs this work.

---

## Harvest-window redesign — user rulings settled so far (2026-07-03)

> **The full design lives in `design_docs/cards/HARVEST_WINDOWS_DESIGN.md`**
> (the 18-window ladder, the during-field-phase model with the take-occasion manifest, the
> FEED/BREED seams, the one-batch migration list for implemented cards — including the three
> mis-timed cards from the priority section above — and the open questions awaiting the
> user). **Build status (2026-07-04): stages 1–2 are IMPLEMENTED** — the ladder walk, the
> per-player FIELD band (ruling 3), the take-occasion manifest (`PendingFieldPhase` +
> `CommitFieldTake` + the occasion registries) are live; the design doc's §12 carries the
> as-built map, and the delegated migration batch (§7 there) is the next step. The rulings
> below are recorded in both places; this list is the quick reference.

Context: a design-in-progress to split the harvest into explicit, ordered timing windows
(immediately-before-harvest → start-of-harvest → before-field-phase → start-of-field-phase →
during-field-phase → end-of-field-phase → after-field-phase → the feeding/breeding analogues).
Within the during-field-phase window, optional card triggers and the mandatory crop take may
resolve in any player-chosen order (the take behaves like a mandatory trigger gating the
window's exit; take-*modifying* effects become ineligible once the take fires). Rulings the
user made during this design — cite these, dated, in the docstrings of the cards they govern:

1. **A skipped phase has no boundaries.** A player who skips the field phase (Lunchtime Beer
   E58) fires NO before-/start-/during-/end-/after-field-phase effects that harvest. (Definite.)
2. ~~Layabout's harvest skip does NOT suppress harvest-boundary effects~~ **SUPERSEDED
   2026-07-05 by ruling 14**: Layabout cancels before- AND after-harvest trigger effects —
   the whole ladder, outer boundaries included — following the official online
   implementation. (The user dislikes this reading but rules to follow the official
   game; the original ruling here had gone the other way and was itself marked
   contested.)
3. **Player interleaving within a harvest window: whole-phase-per-player, starting player
   first** (the BoardGameArena convention), adopted **provisionally**. The user dislikes it —
   the printed rules imply no fixed order, and a fixed order advantages the later-deciding
   player — but it is the simplest start and matches the existing per-player harvest frames.
   Revisit if it proves distortive.
4. **Bumper Crop (E25) / Harvest Festival Planning (C72) trigger the field-phase *effect*
   (the crop take), not the field phase itself** — no field-phase-keyed card effects fire
   during them (per the user; C72's clarification "this is not a harvest" is the same idea one
   level up). They may be hard-coded through a shared take function; a Pending frame becomes
   necessary only if optional crops-off-field triggers must surface inside them.

5. **The field-phase take is a singular event.** Harvesting all crops from all fields is one
   game event; effects that scale per-field or per-crop (Slurry Spreader's per-last-crop food,
   Barley Mill's per-grain-field food) scale over that one event's contents and all arrive at
   once — there is no per-field sequence of moments inside the take. Each *card-granted*
   harvest firing (Scythe, Stable Manure, a card-field effect) is its own separate occasion.
6. **"Each time you obtain at least 1 X" counts OCCASIONS; "for each X you obtain/harvest"
   counts UNITS** — both read the same event. Hayloft Barn's clarification ("harvesting 2+
   grain at once only counts as obtaining once") is occasion-counting for that card's "each
   time" wording, NOT a general rule that batches away quantities: obtaining 2 grain at once
   is one *time* but still 2 *grain* (Agricultural Labourer's per-grain clay scales by 2).
   Beware over-generalizing any single card's clarification into event semantics — and beware
   the converse too: some card wordings are just imprecise, so don't infer deep event
   structure from one card's phrasing without checking siblings.
7. **Witches' Dance Floor (D25) and Begging Student (D97) are BANNED — never implement**
   (user rulings 2026-07-03; both marked 🚫 in `CARD_IMPLEMENTATION_PROGRESS.md`, like
   Shaving Horse A48). Begging Student's ban also moots the registration-liveness question
   (HARVEST_WINDOWS_DESIGN.md §11) unless another mid-harvest card-play member appears.
8. **Anytime-in-harvest triggers** ("each harvest, you can…", incl. the Joinery / Pottery /
   Basketmaker built-ins — full analysis in HARVEST_WINDOWS_DESIGN.md §10): good→food
   converters surface ONLY inside the feed payment and in-harvest food raises (the user's
   own optionality-constrained proposal); pure-VP food buys surface ONLY at a single late
   anchor after breeding (**approved 2026-07-03**; Furniture Carpenter migrates off its
   FEED-only seam accordingly); buys generating **goods** that can become food (Basket
   Carrier, Ebonist) are offered **throughout the harvest, not selectively** (ruled
   2026-07-03).
9. **Grain Sieve / Barley Mill fire ONCE, off the take occasion** (ruled 2026-07-03): their
   bonuses read "the specifics of what happened in" the main field-phase crop take — not a
   window-wide aggregate over card-granted extra harvests. And **Home Brewer re-homes to
   the after-field-phase window** (ruled 2026-07-03), off `HARVEST_CONVERSIONS`.
10. **The post-breeding timeline** (ruled 2026-07-03): breeding phase → after-the-breeding-
   phase (Feedyard — INSIDE the harvest; its food can fund the last-chance conversions, and
   it dies with a skipped breeding) → the last chance for in-harvest conversions (the
   anytime span's end; end-of-harvest cards live here) → after the harvest (Value Assets,
   Elephantgrass Plant — outside). Details + the designated (Feedyard, Winter Caretaker)
   regression pair: HARVEST_WINDOWS_DESIGN.md §10.
11. **All field-phase harvesting is ONE simultaneous event — every during-phase harvesting
   card folds into the take** (ruled 2026-07-05, supersedes ruling 9's Scythe-Worker-vs-
   Stable-Manure contrast): the only event in a harvest in which a player harvests goods
   from fields is the field phase's main event; card extras (Stable Manure, Scythe Worker,
   Scythe E73's widening, Grain Thief's replacement) are taken AT THE SAME TIME as that
   event, part of the same occasion — never a separate, sequenced harvesting event. A
   two-agent full-catalog sweep (2026-07-05) found zero counterevidence: no in-harvest
   field-harvesting outside the field phase, no sequential wording anywhere, and two
   official clarifications in support (Potato Ridger A59: "'Harvest' is equivalent to the
   field phase, or any literal effect of a card saying 'Harvest a [crop]'"; Hayloft Barn
   B21: "Harvesting 2+ grain at once only counts as obtaining once"). Consequence, ruled
   explicitly: **Grain Sieve treats Stable Manure's extras exactly as Scythe Worker's** —
   both are in the take occasion and count toward "at least 2 grain." Implementation:
   Stable Manure reworks from its wave-A free-order/own-occasion form onto the take
   fold-in seam; a during-the-field-phase separate occasion no longer exists
   (`emit_harvest_occasion` remains for genuinely separate events — a Bumper-Crop-played
   field phase, future literal "Harvest a crop" effects).
12. **The harvest-verb lexicon** (ruled 2026-07-05): "harvest" as an EVENT is a real
   harvest's field phase (Harvest Festival Planning's "this is not a harvest" scopes the
   event sense). "Harvest" as a VERB means taking crops off fields into the player's
   supply via the FIELD-PHASE EFFECT — wherever that effect runs, so crops taken by a
   card-played field phase (Bumper Crop) ARE harvested in the verb sense — or via a card
   effect literally worded "Harvest a [crop]" (Potato Ridger's clarification, the
   definition). Crop-off-field movements worded otherwise are not harvests: "remove"
   (Crop Rotation Field E70) is the wider any-departure verb — the E68/E69 ("harvest the
   last") vs E70 ("remove the last") same-family contrast is the key evidence — and
   Changeover's "discard" removes the crop FROM PLAY, not to the supply, so it is a
   different movement entirely (not evidence about the harvest verb either way).
   Reactor scoping follows each card's own printed frame: "…in the field phase OF A/EACH
   HARVEST" (Crack Weeder, Potato Harvester, Slurry Spreader — confirmed field-phase-
   restricted, correcting a sweep-agent mis-filing — Grain Sieve, Barley Mill, Lynchet,
   Artichoke Field) fires only in real harvests' field phases; unscoped harvest-verb
   reactors (Food Merchant, Field Cultivator, Melon Patch, Cherry Orchard) fire on any
   verb-sense harvest, a played field phase included; E70's "remove" fires on any crop
   departure from that card.
13. **A card-granted newborn is fed 1 food** (ratified 2026-07-05): a Family Growth
   granted at the immediately-before-harvest / start-of-harvest windows (Autumn Mother,
   Bed in the Grain Field) produces a standard newborn — 1 food at that harvest's
   feeding, exactly like a same-round Wish-space newborn. The engine's uniform newborn
   rule stands as-is.
14. **Layabout cancels ALL harvest-relative effects for the skipping player** (ruled
   2026-07-05, supersedes ruling 2): before-harvest and after-harvest triggers included —
   windows #1 through #18 are all suppressed, plus the feeding and breeding frames.
   This follows the official online implementation; the user dislikes the reading but
   rules to match it. Also resolves the design doc's open question #2 (window #1 does
   NOT fire for a Layabout player). Cite this ruling, dated, in Layabout's docstring
   when built.
15. **Cubbyhole's payout is NON-consuming** (ratified 2026-07-05): the on-card food
   bank pays out at every feeding phase and is never depleted — the literal reading
   of "you get food equal to the amount on this card" (no removal clause).
16. **Shepherd's Whistle's condition is capacity-theoretic** (ruled 2026-07-05;
   dominance rule AMENDED same day): "at least 1 unfenced stable without an
   animal" — since animals are not location-tracked, a stable is free iff the
   player's animals can be accommodated with one unfenced stable removed from
   capacity. No unfenced stable: ineligible. A stable free by that test: the
   sheep is granted automatically. Otherwise the player may CHOOSE to free one:
   the options are the Pareto keep-sets under the reduced capacity, each plus
   the granted sheep (reachability is TESTED this way, never inferred from the
   ending — a 3-type holding can fit full capacity while its sheep-decremented
   form fails the reduced capacity). **The frontier is over animal counts PLUS
   a received-vs-declined dimension, where received dominates declined iff the
   player has a sheep-conversion opportunity** (a cook-a-sheep-and-replace-it
   option then beats declining — the food is non-deferrable because the card
   replaces the cooked animal, so the usual food-exclusion premise fails; with
   no conversion the same option is identical to declining and is pruned).
   Food generated is computed per option but is never a frontier dimension
   (the standing convention — among received options, animals-only dominance
   is exact: food differences equal the deferred cook-value of the animal
   difference).
17. **Baker's on-play decline is WIDE** (ruled 2026-07-05): a "when you play this
   card, you CAN take a [sub-action]" grant is offered as PLAY-VARIANTS of the
   play action itself — "play Baker and bake" vs "play Baker and decline the
   bake" are two distinct CommitPlayOccupation choices (the existing
   PLAY_OCCUPATION_VARIANTS mechanism, Roof Ballaster's pay-or-not shape). The
   user rejected the alternative (an after-play trigger with Stop to decline)
   because it would let the granted bake interleave with OTHER after-play
   triggers in player-chosen order, which "when you play this card" does not
   license. Once the bake variant is chosen, the pushed PendingBakeBread is
   committed (the variant choice was the decline moment). When no bake is
   usable at play time, the plain variant-less play is offered alone.
18. **"Immediately after each harvest" = "after each harvest"** (ruled
   2026-07-05): the two phrasings name the SAME instant — the user called the
   wording distinction "confusing and unnecessary". The ladder's two separate
   after-harvest windows were merged into one (`after_harvest`); Elephantgrass
   Plant (printed "immediately after") and Value Assets (printed "after",
   unimplemented) both live there. **This does NOT generalize automatically:**
   the user's standing instruction is that EVERY occurrence of "immediately" in
   a card text gets its own user ruling — sometimes it means the same as the
   phrase without it, sometimes not. Never encode an "immediately" timing
   distinction (or collapse one) unilaterally. Open instance flagged the same
   day: Social Benefits ("immediately after the feeding phase") vs Farm Store
   ("after the feeding phase") sit on two separate ladder windows — awaiting
   the user's ruling on whether that pair also collapses.

Also settled in this design thread: C++ byte-identity is **not** a constraint on this
redesign — design the Python harvest machinery on its merits and re-port to `cpp/` if a
Family-shape change falls out (the user explicitly deprioritized gate-preservation here in
favor of the best card-engine design). And per the CLAUDE.md Phase-3 directive added
2026-07-03: **4-player is an eventual goal — [3+]/[4] cards are design inputs** for this
machinery (e.g. Old Miser's per-person feeding discount, Game Provider's immediately-before
field-crop discard, Champion Breeder's newborns-placed count), even though they aren't dealt
at 2 players.

---

## Group A — small, well-scoped, high-yield (recommend building on approval)

### A1. Card-granted Family Growth with NO space placement
> **PRIMITIVE BUILT 2026-07-03** (commit "card-granted family growth — place_on_space=False"):
> `PendingFamilyGrowth.place_on_space` landed exactly as proposed below, with tests
> (`tests/test_family_growth_grant.py`). The member cards are NOT yet implemented — Autumn
> Mother (C92) and Bed in the Grain Field (C24) ride the harvest-window card wave
> (HARVEST_WINDOWS_DESIGN.md); A93 / B92 / A21 below still await their own batch, and the
> A21 question (room-count timing + food coupling) is still open.

**Cards unblocked:** A93 Bed Maker, B92 Little Stick Knitter, A21 Family Friend Home (rescued).

**Blocker.** Per the rules (your ruling), a card-granted "Family Growth" places the newborn on **no
action space**. But the engine's only growth primitive, `PendingFamilyGrowth`, resolves through
`_execute_family_growth` → `_resolve_wish_for_children`, which **forces** placing the newborn worker
on a board space (`_update_space(space_id, workers=…)`). So there is no correct `initiated_by_id` for
a card grant — a real space id mis-places the newborn (and would be read by worker-scanning cards like
Wood Pile), and a `"card:…"` id `KeyError`s.

**Proposed build.** Add `place_on_space: bool = True` to `PendingFamilyGrowth` (card-only, default
`True` → Family byte-identical; add to `__hash__` + skip-fields). Factor the people-increment out of
`_resolve_wish_for_children`; in `_execute_family_growth`, when `place_on_space=False`, increment
`people_total`/`newborns` **without** the `_update_space` call. Each card pushes
`PendingFamilyGrowth(initiated_by_id="card:<id>", place_on_space=False)` from an **optional**
`after_build_rooms` (A93, A21) / `before_action_space` sheep_market (B92) trigger, with eligibility
gated on the room predicate `people_total < 5 and people_total < _num_rooms(p)` (the primitive does
**not** self-check this) and, for A93, the 1-wood-1-grain cost.

**Effort:** ~15 lines engine + 3 thin card modules. **Risk:** low.
**Question (A21 Family Friend Home only):** "if you have more rooms than people" — measured **before**
or **after** the just-built rooms? (`after_build_rooms` naturally reads the post-build count.) And does
its **+1 food** couple to firing the growth, or is it unconditional on the build? I'll default to
post-build count + food-bundled-with-growth unless you say otherwise.

### A2. "On your turn" build exclusion (off-turn builds don't trigger)
**Cards unblocked:** A43 Farmyard Manure, A74 Stable Tree.

**Blocker.** Both schedule goods "each time you build 1+ stables **on your turn**," and the printed
clarification excludes off-turn builds (Groom B089 / Stable Planner A089). A naïve `after_build_stables`
auto also fires on those start-of-round grants.

**Proposed build.** A card-local eligibility predicate — the build is "on your turn" iff **no
`PendingPreparation` frame is on the stack**. In the current card set every off-turn stable build is a
`start_of_round` grant (Groom, Stable Planner), which carries a `PendingPreparation` frame at the
bottom of the stack; a real worker-placement build never does. So
`not any(isinstance(f, PendingPreparation) for f in state.pending_stack)` in the auto's eligibility is
exact today. No engine change. I'd add a shared helper `_is_on_turn_build(state)` for reuse.

**Effort:** ~5 lines/card + a 3-line helper. **Risk:** low-medium — correct for *all* current off-turn
sources; a future card that builds stables on the **opponent's** turn would need the predicate widened
(flag it then). I recommend building; it's a clean, testable predicate.

### A3. Minor-improvement play-variant (on-play binary choice)
**Cards unblocked:** B41 Hauberg (with A6 schedule_animals), B9 Beating Rod (partial — see note), and the
whole "you decide what to start with" family; also a prerequisite for some Group-B renovate cards.

**Blocker.** A *minor* with an on-play choice ("get 1 reed **or** −1 reed +1 cattle"; "start with
wood **or** boar") can't be expressed — play-variant machinery is **occupation-only**
(`register_play_occupation_variant`; `CommitPlayMinor` has no `variant`, the enumerator emits no
per-variant commits).

**Proposed build.** Mirror the occupation path: a `PLAY_MINOR_VARIANTS` registry +
`register_play_minor_variant(card_id, variants_fn)`; the `PendingPlayMinor` enumerator offers one
`CommitPlayMinor` per legal variant; `on_play` becomes `(state, idx, variant)`. (Symmetric with the
existing Roof-Ballaster occupation path, so the shape is proven.)

**Effort:** ~30 lines engine. **Risk:** medium (new enumerator branch; needs a test for the
two-variant offer + each on_play).
**Note (B9 Beating Rod):** even with this, the "+1 cattle" variant is an **immediate** animal grant,
which has no accommodation path (only scheduled/market/breeding/harvest do). So B9 needs *both* this
**and** an immediate-animal-accommodation decision — keep it deferred until we decide the immediate-grant
policy (see C-note). B41 Hauberg, by contrast, **schedules** its boar (sound per the red-team), so it is
fully unblocked by A3 + A6.

### A4. Optional renovate grant (declinable)
**Cards unblocked:** B1 Upscale Lifestyle; partially Renovation Company (A13), Established Person (B88).

**Blocker.** A card that grants an **optional** renovation ("if you take the action…") can't use a bare
`PendingRenovate` — its before-phase enumerator emits only `CommitRenovate`, no `Stop`, so there's no
decline path.

**Proposed build.** A `PendingGrantedRenovate` choose-or-decline wrapper, exactly mirroring the existing
`PendingGrantedBuildFences` (sole sub-action `renovate` → push real `PendingRenovate`; the wrapper's
`Stop` is the decline). No change to House Redevelopment / Cottager.

**Effort:** ~20 lines. **Risk:** low-medium.

### A5. Bottom-row major classification
**Card unblocked:** B7 Wage ("+1 food per owned bottom-row major improvement").

**Blocker.** Needs a `BOTTOM_ROW_MAJORS` constant that doesn't exist; its membership is a rules fact.

**Proposed build.** Add the constant + a ~10-line `register_scoring`/on-play read.
**Question:** confirm the bottom-row set. My proposed reading of the Revised supply board:
**bottom = {Clay Oven (5), Stone Oven (6), Joinery (7), Pottery (8), Basketmaker's Workshop (9)}**,
**top = {Fireplace ×2 (0,1), Cooking Hearth ×2 (2,3), Well (4)}**. The only one I'm unsure of is the
**Well (idx 4)** — top or bottom row? (≥1 other deferred/expansion card reuses this, so it's worth pinning.)

### A6. `schedule_animals` helper + Acorns Basket
**Cards unblocked:** B84 Acorns Basket (and the boar half of B41 Hauberg with A3).

**Blocker.** No `schedule_animals` helper (only `schedule_resources` for `Resources` and
`schedule_effect` for effect ids). The accommodation path itself is **sound** (red-teamed this session).

**Proposed build.** Add `schedule_animals(state, idx, rounds, Animals)` to `cards/schedules.py`,
mirroring `schedule_resources` but writing `FutureReward(animals=…)` additively. Acorns Basket's
`on_play` then schedules 1 boar onto its target rounds.
**Question:** Acorns Basket's text is "Place 1 wild boar on each of **the 2 round spaces**" — the data
doesn't say *which* two (the physical card's diagram designates them). Which 2 rounds? (If it's simply
"the next 2 rounds," say so and I'll build it.)

### A7. Passing-status confirmation
**Card unblocked:** B5 Store of Experience (an otherwise-trivial tiered on-play; ~15 lines once known).
**Question:** is Store of Experience a **passing/traveling** minor (like Market Stall — executed then
handed to the opponent) or **kept**? Its text gives no passing instruction and the `passing_left` data
field has proven unreliable (it appears on both traveling and kept cards). Passing changes ownership +
scoring, so I won't guess.

---

## Group B — medium infra (build with more design care)

### B1. Resource high-water-mark latch — B35 Hook Knife
"Once this game, when you have 8 sheep → +2 VP." The one-shot latch sweep (`_fire_ready_one_shots`) only
runs at the play-card/renovate seams, never on an animal-count change, so it never fires at the right
moment. **Plan:** either call the sweep at every animal-count-increasing site (markets, breeding,
scheduled collection), or add a dedicated resource-threshold latch checked there. Generalizes to
boar/cattle/grain/veg threshold cards. **Medium effort, medium risk** (new call sites).

### B2. Passing-card-excluded after-event — B49 Scales
"+2 food when your occupations = your improvements; **passing cards never trigger this**." But
`after_play_minor` fires for passing minors too, and the auto signature `(state, owner)` can't tell a
passing-fire from a coincidentally-equal count. **Plan:** add an `after_play_kept_minor` event fired only
when `minor_improvements` actually grew (cleaner than threading the card id through every auto). **Medium.**

### B3. Build-payment provenance — A41 Vegetable Slicer
"+2 wood +1 veg when you build a Cooking Hearth **by returning a Fireplace**." `after_build_major` never
receives `commit.payment`, and post-build state can't distinguish "upgraded from my Fireplace" from
"never owned one." **Plan:** thread the `CommitBuildMajor` payment/variant into the `after_build_major`
event, or snapshot fireplace ownership before/after via CardStore. **Medium.**

### B4. Consumed-space snapshot + improvement grant — A95 Angler
"Each time you take ≤2 food from Fishing → you may play a Minor/Major Improvement." The catch amount is
zeroed by the resolver, so the ≤2 test needs a **before**-snapshot (CardStore), and firing pushes a
`PendingMajorMinorImprovement`. **Plan:** before_action_space snapshot the catch; after_action_space
optional trigger gated on stored catch ≤2 → push the improvement. **Verify** a card can push
`PendingMajorMinorImprovement`. **Medium.**

### B5. Scheduled-goods provenance — B76 Ceilings
"On next renovate, remove the wood **this card** still has promised on round spaces." `future_resources`
is a flat additive tuple with no per-card provenance, so a blind subtract is wrong when another scheduler
wrote the same slots. **Plan:** a CardStore record of which round slots Ceilings seeded + amounts;
`after_renovate` subtracts only its own remaining wood. **Medium** (generalizes to any "take back promised
goods" card).

---

## Group C — deliberate engine boundaries (a design decision, not just code)

### C1. Standalone "buy food → good" / at-any-time conversion
**Cards:** B70 New Purchase (round-start 2 food→1 grain / 4 food→1 veg), B82 Value Assets (post-harvest
food→building-resource buys), B29 Cookery Lesson (use a cooking improvement *the same turn*), B32 Kettle,
B69 Potters Market, A60 Oriental Fireplace, plus the §15 Grocer/Clay Carrier family.
**The boundary.** The engine deliberately never surfaces at-any-time / standalone conversions (a rational
agent defers them to where proceeds are needed). These cards each want a standalone optional buy. **Decision
needed:** do we introduce a standalone optional buy-conversion frame, and where is it hosted? B70 fits the
existing `start_of_round` host cleanly (it's the mildest — round-start-gated, no affordability closure); B82
additionally needs an **after-harvest** host that doesn't exist. I'd suggest starting with **B70 alone** as
the first member (lowest risk) if you want to test the shape.

### C2. Action substitution — A97 Freshman
"Instead of taking a Bake Bread action, you can play an occupation." Substitution (not the additive grant
the triage first assumed) + a legality change. Needs substitution machinery. **Question:** scope of "each
time you get a Bake Bread action" — only Grain Utilization's bake, or every granted bake (Oven Firing Boy /
Bread Paddle / the ovens)? And does its once-per-turn cap span sources? Defer until the substitution model
is designed with you.

### C3. Take-from-accumulation-without-placement — A82 Work Certificate (rescued), B81 Handcart
You flagged this exact mechanism as a blocker. The rescue pass argued it's just editing `sp.accumulated`
(as Basket/Mushroom Collector do). **Decision needed:** are you comfortable surfacing an optional "take 1
building resource off an accumulation space holding ≥N, no worker placed" as an `after_action_space` /
`start_of_round` trigger? If yes, both are ~clean (PendingCardChoice over the qualifying spaces). I deferred
to your call since you named it.

### C4. Multi-plow chain — A18 Wheel Plow (rescued)
The rescue proposed chaining `PendingPlow` via an `after_plow` re-arm (a 2-plow grant, once per game). It's
plausible but **unproven** — no existing card chains plows this way, and the re-arm/termination gating
(only re-arm from this card's own chain, cap at 2) needs careful testing. **Decision:** want me to build it
as proposed, or hold for the cleaner "bounded multi-plow" primitive (which would also unblock Double-Turn
Plow A20)?

### C5. Complex composition — B93 Confidant (rescued)
Buildable in principle (play-occupation-variant N=2/3/4 + scheduled food + a round-start sow/fences play-
variant grant), but it composes 4–5 mechanisms at once — high implementation risk. I'd build it **after**
A3 (minor play-variant) lands and only with a careful test. Holding for your go-ahead.

---

## The long tail — genuinely blocked (each needs a substantial new subsystem)

These are correctly deferred; grouped by the missing subsystem, for visibility (not proposing to build):

- **Grid/adjacency geometry:** Homekeeper (A85), Farm Hand (B85), Future Building Site (B38),
  Love for Agriculture (B72), Pottery-Yard-style orthogonal adjacency (**note:** B31 Pottery Yard was
  *rescued* — its adjacency is computed inline, no API needed), Shelter (A1, 1-cell-pasture restriction).
- **Return-home / end-of-round / after-work-phase hook (no such phase event):** Curator (A100),
  Asparagus Knife (A58), Lifting Machine (A70), Silage (A84), Ale-Benches, Credit (A54),
  Sculpture Course (B53), Informant (B117), Toolbox (B27, turn-end build detection).
- **New shared action space:** Chapel (A39), Forest Inn (B42), Final Scenario (B23, owner-private space).
- **Randomness inside `step` (determinism invariant):** Paper Knife (A3), Moonshine (B3).
- **Temporary / extra worker:** Telegram (A22), Bassinet (A25), Stock Protector (B94),
  Walking Boots (B22), Lazy Sowman (A94, also needs a "declined sub-action" event).
- **Hidden round-space identity (reveal order is in the Environment, not GameState):** Knapper (A124),
  Master Workman (A126), Silokeeper (B112), Sweep (B120), Telegram's round-space half.
- **Card-as-animal-holder / new capacity slot:** Truffle Searcher (B86), Feedyard (B11), Stockyard (B12),
  Mud Patch (A11), Special Food (B34, needs an accommodation event).
- **Per-card goods stack (beyond a CardStore scalar):** Hayloft Barn (B21), Muddy Puddles (B83),
  Forest Plow (B17, return-wood-to-space + partial-take legality), Forest Stone (B48 — also an
  alternative cost), Maintenance Premium (**note:** B55 was *rescued* — it needs only a scalar).
- **Alternative printed cost ("A OR B" for the card's own play):** Baseboards (A4), Barley Mill (A64),
  Forest Stone (B48). `MinorSpec.cost` is a single `Cost`; no OR-alternation, and you don't own the card
  while playing it (so the cost-formula registry can't help). A small `alt_costs` list on `MinorSpec` +
  an affordability/choice at play would unblock all three — a candidate Group-A item if you want it.
- **Legality / sub-action-menu changes:** Wooden Shed (A10), Forest School (**rescued** via the existing
  occupancy-override registry), Agrarian Fences (B26), Oven Site (A27, constrained build-major),
  Stone Company (A23), Carpenter's Hammer (A14, per-action build-count discount), Chief Forester (A115,
  capped sow).
- **Misc one-offs:** Shaving Horse (A48, "after you obtain wood" event), Winnowing Fan (A61, state-dependent
  baking-rate conversion), Potato Ridger (A59, optional-at-harvest-field — the field hook is auto-only),
  Reclamation Plow (A17) / Wheel/Double-Turn plows, Grain Depot (B65, reads which resource paid),
  Moral Crusader (B106) / Shoreforester (B116) (pre-refill round-space read), Clutterer (B100, fragile
  static "accumulation-space text" card set + exact scoring rule), Wood Palisades (B30, alt fence piece +
  supply-cap bypass), Hawktower (B14), Carpenter's Bench (B15), Grassland Harrow was **rescued**.

---

## Summary for the morning

- **Group A (6 build-items, ~7 cards + a family):** all small, Family-safe, high-yield. Approve any subset
  and I build them. **Questions embedded:** A1 (A21 room-count timing + food coupling), A5 (bottom-row majors,
  esp. the Well), A6 (Acorns Basket's 2 rounds), A7 (B5 passing?).
- **Group B (5 cards):** medium infra; I can build on approval, each with a focused test.
- **Group C (decisions):** standalone conversions (C1), action substitution (C2), take-without-placement
  (C3, you flagged it), multi-plow (C4), Confidant (C5).
- The long tail stays deferred (real subsystems). One cheap extra: a small `alt_costs` on `MinorSpec`
  would unblock Baseboards / Barley Mill / Forest Stone — say the word.

---

## Round-end effects — the `PendingRoundEnd` frame (design; NOT yet implemented)

**User-directed plan (2026-07-01). Deferred: do not implement until scheduled.** Three related
card families all resolve at the end of a round and none has a home in the engine today. They
share one new phase frame, `PendingRoundEnd`, pushed at the round-end boundary (the
**returning-home phase**, i.e. `RETURN_HOME`, before `PREPARATION`/the reveal).

### The three families the frame hosts

1. **Use-it-or-lose-it "once per round, you can …" options.** Cards worded *"Once per round, you
   can [pay a good to gain something]"* with **no** "at the start of each round" and **no**
   person-placement qualifier. They are usable at **any point during the round** and the option
   **expires at round end** if unused. The engine deliberately does not surface anytime
   conversions (a rational agent defers them to the last useful moment — see
   `CARD_AUTHORING_GUIDE.md` §2), so the correct realization is to offer each still-unused option
   as an **optional round-end `FireTrigger`** (the last moment it can be used). Modeling them at
   `start_of_round` is **wrong** (it forces the choice before the player has acquired the goods
   and removes the anytime flexibility). Members in the current data:
   - **Corn Schnapps Distillery (C64)** — pay 1 grain → 1 food on each of the next 4 round spaces.
     *(Was implemented at `start_of_round`; DEFERRED + archived 2026-07-01.)*
   - **Mandoline (C46)** — pay 1 vegetable → 1 bonus point + food on next round spaces. *(not implemented)*
   - **Pellet Press (D46)** — pay 1 reed → food on each of the next 4 round spaces. *(not implemented)*
   - *Not this family:* Tea House (D53, tied to skipping the 2nd person placement — a
     placement-time effect); Clay Carrier (D122, "at any time, but only once per round" — the
     anytime-conversion family, a separate deferral); Guest Room (E22, different mechanism).

2. **Round-end automatic effects** (choice-free). Example: **Claypipe** — "In the returning-home
   phase of each round, if you gained at least 7 building resources in the preceding work phase,
   you get 2 food." (Also needs a new *"building resources gained this work phase"* counter — a
   small piece of extra infra beyond the frame itself.)

3. **"At round end" triggers** — optional/at-round-end-worded card effects (the general case of
   family 2, surfaced as `FireTrigger`s rather than autos).

### Firing order (load-bearing)

Within `PendingRoundEnd`, resolve in this order:
1. **use-it-or-lose-it triggers FIRST** (family 1) — so their proceeds are on hand *before* the
   round-end automatics/at-round-end triggers compute or consume state;
2. then **round-end automatic effects** (family 2);
3. then **"at round end" triggers** (family 3).

### Status
Design only, per user direction — **do not implement yet.** When built, re-read each member
card's exact text (§1) and re-classify. Corn Schnapps Distillery's module + test are preserved in
`archive/deferred_cards/` and should be un-archived and rebuilt on this frame.

---

## After-the-feeding-phase conversions — `PendingHarvestFeed` after-phase (design; NOT implemented)

**Deferred 2026-07-01 (user-approved deferral).** Cards worded *"After the feeding phase of
each harvest, you can …"* must fire **once feeding is fully resolved**, so their proceeds
cannot pay that harvest's feeding. Today they have no home: `PendingHarvestFeed` has **no
phase/after model** (its only fields are `player_idx`, `initiated_by_id`, `conversion_done`),
and the harvest-conversion registry (`register_harvest_conversion` → `CommitHarvestConversion`)
offers its conversions **during** `HARVEST_FEED`.

**The bug this caused (now deferred):** **Farm Store (C41)** — "After the feeding phase of each
harvest, you can exchange exactly 1 food for 2 different building resources of your choice or 1
vegetable" — was implemented as a during-feed `register_harvest_conversion`. Offered during
feeding, a player can buy a **vegetable** for 1 food and then **cook it** (Fireplace/Hearth) to
pay that same feeding — a food-laundering exploit the "after" wording exists to forbid. Farm
Store's module + test are archived in `archive/deferred_cards/`.

**What's needed:** give `PendingHarvestFeed` a before/after phase (or add a distinct
post-feed frame pushed after the feeding payment resolves) that hosts **after-feed triggers** —
offered only after `CommitConvert`/the feeding payment is done, so their output cannot re-enter
the feeding calculation. This is harvest-subsystem surgery (the feed frontier + deferred food
payment are the engine's most delicate area — see CLAUDE.md Foundations / the harvest §), hence
deferred. Any other "after the feeding phase" card joins Farm Store here. When built, un-archive
Farm Store, move it off `register_harvest_conversion` onto the new after-feed hook, and re-test.

---

## "Before the start of each round" — a distinct hook (design; NOT implemented)

**Deferred 2026-07-01 (user-directed).** Cards worded *"Before the start of each round, …"*
need a dedicated hook that does not exist yet.

**The card that needs it:** **resource_analyzer** (occupation) — "Before the start of each
round, if you have more building resources than all other players of at least two types, you
get 1 food." It was implemented as a `start_of_round` auto, which is WRONG on two counts:
1. `start_of_round` fires at step 5 of `_complete_preparation` — *after* step 2 distributes the
   new round's scheduled income (`future_resources`). So the building-resource comparison reads
   *post-income* counts, whereas "before the start of the round" wants the pre-income snapshot.
   The divergence is reachable: building-resource scheduling cards exist (club_house schedules
   stone, cesspit clay, thick_forest wood), so at such a boundary the comparison can flip.
2. More fundamentally, "before the start of round R+1" is its OWN instant — **not** the
   end-of-round-R boundary (the `PendingRoundEnd` family). A **harvest** falls between the two
   on harvest rounds (WORK → RETURN_HOME → *harvest* → PREPARATION), and end-of-round effects
   must fire **before** before-start-of-round effects. So this is a separate, strictly-later
   hook, ordered: end-of-round effects → (harvest, if any) → **before-start-of-round effects** →
   the round's income/reveal.

**What's needed:** a distinct "before the start of each round" hook that fires after the harvest
(and after any `PendingRoundEnd` end-of-round effects) but **before** the round's income
distribution — so a card reads the pre-income, post-harvest state. Module + test for
resource_analyzer are archived in `archive/deferred_cards/`; un-archive and move it onto this
hook when it exists. (Do NOT approximate with `start_of_round` — that is the post-income instant
this hook exists to avoid.)
