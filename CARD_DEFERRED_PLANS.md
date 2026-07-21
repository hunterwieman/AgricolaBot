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

## Food-provider batch — deferred members (2026-07-15)

The 2026-07-15 food-provider batch (§1) implemented 20 minors and deferred three:

- **Oriental Fireplace (A60, minor)** and **Earth Oven (D59, minor)** — both ARE cooking
  improvements as minors: *"At any time: Vegetable / Sheep / (Wild boar) / Cattle → food; 'Bake
  Bread' action: Grain → food."* **Deferred into the cooking-modifier cluster** (ruling 42 — the
  Gypsy's Crock / Cooking Hearth Extension class): `helpers.cooking_rates` was hardcoded off the
  major-owner array with **no card-injection seam** *(no longer true as of 2026-07-21 — ruling 72
  built the additive-bonus fold, `cooking_mods.register_cooking_rate_bonus`, for Fatstock
  Stretcher; these two cards need the stronger improvement-INJECTION shape — a card that IS a
  cooking improvement contributing base rates — which remains undesigned)*. Two extra
  wrinkles for that design pass: the printed **cost is "return a Fireplace/Cooking Hearth"** (a
  non-resource `play_minor` route — `register_base_route` could carry it, but no minor uses that
  today) and the **"counts as 1 minor OR 1 major, whichever is convenient"** dual-classification.
  The bake-only half is a trivial `register_baking_spec_extension` once the cooking-rate seam lands.

- **Farmstead (C48, minor)** — *"After each turn in which you make at least one unused farmyard
  space used, you get 1 food."* **Deferred: end-of-turn timing** — the deliberately-unbuilt boundary
  (CARD_ENGINE_IMPLEMENTATION.md §8; the Firewood Collector case). "After each turn" needs a true
  post-turn anchor that does not exist yet (the action-space pop lands one window too early once
  at-any-time effects arrive). A per-sub-action approximation (autos on after_plow / after_build_* /
  after_build_fences with a once-per-turn latch) fires on the same turns but is an *approximation* of
  the end-of-turn semantics, so it stays deferred pending the end-of-turn / at-any-time design.

---

## Deck-B/E scoring-and-timing batch — deferred/held members (2026-07-13)

The batch that implemented Heirloom, Nave, Land Register, Misanthropy, Rod Collection, Upholstery,
Herbal Garden, Beaver Colony, Hook Knife, Ox Skull, and Cookery Lesson (§1) left three cards out:

- **Muck Rake (D29, minor)** — *"During scoring, you get 1 bonus point for exactly 1 unfenced stable
  holding exactly 1 sheep. The same applies to wild boar and cattle, if held in different unfenced
  stables."* **Deferred: the first scoring-time ANIMAL-ARRANGEMENT card.** No existing scoring term
  depends on how animals are arranged among pastures/stables (animals aren't location-tracked), and
  scoring it correctly needs a multi-slot arrangement-feasibility search (dedicate up to 3 distinct
  standalone stables to a lone sheep/boar/cattle while housing all other animals) — the doctored-
  player + `can_accommodate` technique (`shepherds_whistle`/`mineral_feeder`) extended to reserve
  several capacity-1 slots. Buildable, but it is also the card that would first trigger the
  arrangement-sharing ruling (§6, CARD_AUTHORING_GUIDE §2) if paired with a future scoring-arrangement
  card. Removed from this session at the user's direction; revisit as a deliberate scoring-arrangement
  task.
- **Breed Registry (D36, minor)** — *"During scoring, if you gained at most 2 sheep from sources
  other than breeding during the game and have not turned any sheep into food, you get 3 bonus
  points."* **Postponed (user-agreed 2026-07-13): needs game-long, all-players, gross provenance
  tracking that PREDATES the card's play.** Two per-player fields tracked from turn 1 — sheep
  obtained from non-breeding sources (GROSS, not net: discard/exchange diverges gross from net
  without cooking) and whether a sheep was ever cooked — instrumented at ~8–10 non-centralized
  sites (sheep market, breeding-exclusion, `grant_animals`, on-play direct adds, exchanges; and the
  four scattered cook sites), gated to card-mode for Family byte-identity. Real correctness risk
  (a missed site ships silently wrong). Best done deliberately, ideally alongside sibling
  "gained X from source Y" provenance cards so the instrumentation is built once.
- **Writing Chamber (C31, minor)** — *"During scoring, you get a number of bonus points equal to the
  total of negative points you have, to a maximum of 7 bonus points."* **NOT TO BE IMPLEMENTED**
  (explicit user directive 2026-07-13). Not a defer awaiting infrastructure — deliberately excluded;
  do not implement it in a future batch.

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
   distinction (or collapse one) unilaterally. The first flagged instance —
   Social Benefits vs Farm Store — was ruled the same day (ruling 19).
19. **"Immediately after the feeding phase" = "after the feeding phase", Social
   Benefits first** (ruled 2026-07-05): the feeding pair also collapses into
   one window (`after_feeding`), with Social Benefits ("if you have no food
   left, you get 1 wood and 1 clay") resolving BEFORE Farm Store's optional
   1-food exchange. No new machinery: Social Benefits is an automatic effect
   and Farm Store an optional trigger, and the standing within-window ordering
   (automatic effects before optional triggers) already delivers exactly that
   order — the user ruled the ordering should ride that convention rather than
   a separate window. Consequence: a player ending feeding with exactly 1 food
   cannot spend it at Farm Store and then collect the "no food left" grant
   (pinned by test_social_benefits_resolves_before_farm_store).
20. **In-breeding-phase card effects fire BEFORE the CommitBreed decision,
   not after** (ruled 2026-07-05, for Stone Importer's priced stone buy):
   the breed frame hosts pre-commit triggers (event "breeding") only while
   the breeding choice is still open; once CommitBreed resolves, the frame
   offers only the outcome-reactive grants (event "breeding_outcome" —
   Fodder Planter / Slurry Spreader C71's sows, which need to know the
   newborns) and Stop, all still inside the breeding phase. No separate
   window — the frame's own two stretches carry both.
21. **A mandatory, choice-free card effect fires automatically, never as a
   forced offer** (ruled 2026-07-05, for Potato Ridger's "with 4+ vegetables,
   you must do so"): the player gives no input — the effect is an automatic
   consequence, not a singleton FireTrigger the player must click. This
   aligns the harvest-occasion seam with the engine's standing firing
   classification (mandatory + choiceless = automatic effect). Consequence
   for two-tier cards: the occasion host records which per-occasion autos
   fired (`PendingHarvestOccasion.autos_fired`), and a card whose automatic
   tier reacted is excluded from offering its optional tier on the SAME
   occasion (Potato Ridger harvesting into 4 veg: the auto exchange drops
   supply to 3, and the optional at-3 offer must not then appear — "exactly
   1 vegetable" is once per occasion).
22. **A Grain-Thief-replaced field is NOT harvested** (ruled 2026-07-06,
   ratifying the 2026-07-05 implementer reading of "leave the grain on the
   field and take 1 grain from the general supply INSTEAD"): the field is
   untouched by the take and emits NO manifest entry — invisible to Grain
   Sieve's "at least 2 grain", Lynchet's harvested-tile count, and Food
   Merchant's per-grain buys; it cannot donate an "additional" good to Stable
   Manure, and Scythe Worker takes no additional grain from it. The
   replacement's supply grain is likewise not harvested (never in the
   manifest).

23. **Eternal Rye Cultivation's tiers are exclusive** (ruled 2026-07-06, with
   the printed errata's "or"): after each harvest, exactly 2 grain in supply →
   1 food; 3+ grain → 1 grain INSTEAD; never both.
24. **On-play optional choices on MINORS surface wide** (ruled 2026-07-06, for
   Facades Carving's food-for-points exchange — extending ruling 17's
   occupation pattern): one play option per route, via the new
   `PLAY_MINOR_VARIANTS`/`register_play_minor_variant` seam; the surcharge
   folds into the commit's payment (cost modifiers never see it), the benefit
   rides a variant-aware on_play.
25. **Field Cultivator counts field TILES and its takes arrive together**
   (ruled 2026-07-06): "each time you harvest a field tile" counts occasion
   entries (amounts ignored); harvesting k tiles in one take grants up to k
   pile-takes at once, top-down, each optional; unscoped (fires on
   card-played field phases too, per ruling 12).
26. **Earthenware Potter's "after the final harvest" is the after_harvest
   window at round 14** (ruled 2026-07-06 — the same instant Value Assets
   uses, run by the walk immediately before scoring), **and the player freely
   chooses how many people to pay 1 clay for.**
27. **Feed Pellets** (ruled 2026-07-06): the mid-feeding animal gain rides the
   standard decision-free-grant flow (accommodate or keep-or-cook via the
   barrier, which composes mid-FEED); the gained animal is cookable toward
   the same feeding; "exchange exactly 1 vegetable for 1 animal" is once per
   feeding phase TOTAL.
28. **Craft Brewery surfaces wide, encoded by field height** (ruled
   2026-07-06): one conversion option per grain-count group present ("take
   from a field holding X grain") — same-height fields are interchangeable,
   the canonical pick is scan-order — via the new
   `HarvestConversionSpec.variants_fn` seam. The field grain's removal is NOT
   a harvest (no occasion; ruling 12's lexicon).
29. **Mineral Feeder — LANDED 2026-07-06** (ruled the same day): "at least 1
   sheep in a pasture" means at least one sheep actually housed in a pasture
   (not all sheep) under SOME legal arrangement — tested by the user's
   per-pasture construction (dedicate pasture j to sheep, MAX-FILL it, test
   the remainder against the rest of the farm; exact, not a heuristic) — and
   the player may COOK animals to make such an arrangement possible (the
   Shepherd's Whistle case-B analog). The case-B frontier is over
   **(animals, grain)** — the user's framing: declining sits at (current, 0),
   each option at (kept, 1) — so options and the decline never dominate each
   other and animals-only Pareto among options is exact. Cooking a SHEEP can
   itself enable the arrangement (the user's Stockyard counterexample) and
   the enumeration handles it with no special-casing. Same-instant caution
   recorded in CARD_AUTHORING_GUIDE.md §2: two arrangement-conditioned cards
   on ONE instant need a joint-satisfiability test, never independent ones.
30. **Beer Stall — build plan RULED 2026-07-06 (supersedes the same-day
   defer)**: the user's design — a Pareto frontier over **animal counts PER
   grain-conversions-TAKEN k** (taken, not offered: different k values never
   dominate each other — more food, less grain, both excluded dimensions),
   with the k exchanges BUNDLED INTO each option alongside the
   cooking/rearrangement (which dissolves the cook-first sequencing problem
   that forced the original defer — nothing is sequenced through the feeding
   flow). An option = (kept animals, k) where the kept animals fit with k
   unfenced stables left empty (the k-stable generalization of Shepherd's
   Whistle's doctored blank) and k <= grain supply; firing cooks the
   released animals, pays k grain, grants 5k food. Proceed = (current
   animals, 0 conversions). Surfaces as a variant-bearing feeding conversion
   (the Craft Brewery seam); once per feeding via harvest_conversions_used.
   Not yet built — ready on the user's go.

31. **Uncaring Parents does not interact with the stone-house-bonus
   exclusivity clause** (ruled 2026-07-06): Half-Timbered House / Luxurious
   Hostel's "you can only use one card to get bonus points for your stone
   house" does NOT reach it — the user's reasoning (offered with a hedge):
   the house is not providing the points, it only provides a condition that
   lets the card give its per-harvest points. Uncaring Parents scores as a
   plain unrestricted term, stacking with those cards.
32. **A card-field is NOT a "field tile"** (ruled 2026-07-06 — the user:
   "very important to keep in mind"): when card-fields (Beanfield et al.)
   land, their harvest-manifest entries (source "card:<id>") do not count
   for any per-TILE reader. Field Cultivator already encodes this (its tile
   count filters to "cell:" entries, with a pinned test); Lynchet excludes
   them structurally (board adjacency). Every future per-tile card must
   filter the same way.
33. **The Lynchet interchangeability gap is KNOWN and deliberately deferred**
   (user decision 2026-07-06): same-height fields are treated as
   interchangeable by the group-encoded choices (Stable Manure / Scythe /
   Grain Thief / Craft Brewery) and by sowing's canonical cell fill, even
   though Lynchet's house-adjacency reading can distinguish them (a Lynchet
   owner is occasionally denied the better of two "identical" picks — e.g.
   which field Grain Thief replaces). The agreed eventual shape is a
   CONDITIONAL adjacency-aware group key (split groups by house-adjacency
   only when the acting player owns an adjacency-reading card), but the user
   chose to ignore the problem for now rather than widen the decision space.
   Nothing mis-scores; this is a knowingly-accepted approximation, on record
   so future sessions treat it as a decision, not an oversight.

31. *(31-33 recorded above with the wave that landed them.)*
34. **The anytime-converter class-1 build direction** (decided 2026-07-06):
   the user's generalized conversion frontier — the mid-harvest food-raise
   frame (`PendingFoodPayment`) extends its Pareto space from crops + animals
   to crops + animals + CAPPED building-resource conversions (Joinery up to
   1 wood, Stone Carver 1 stone, …), each source live only within its span
   (instant-scoped, derived from phase/cursor) and budgeted once per harvest
   via `harvest_conversions_used`, shared with the feeding crafts. **The
   FEEDING phase is NOT folded into this frontier** — its surface stays as
   is (individual craft fires before the payment commit), because (a) at
   that frame the two shapes are outcome-equivalent, (b) folding changes the
   Family feed action shape and so breaks the no-card AI + requires the C++
   re-port — the user's judgment: hard to reverse once done, easy to add
   later if minds change — and (c) folding would silently prejudge whether
   feeding conversions are distinct orderable events (see the Gypsy's Crock
   note below). REVISITABLE by design.
35. **Gypsy's Crock (C53) is PARKED pending dedicated design** (user,
   2026-07-06): its activation reads how conversion/bake instants are
   grouped ("at the same time" — the Oriental Fireplace clarification), i.e.
   the event-granularity of feeding conversions, a rules-and-machinery
   question the user wants thought through carefully before any
   implementation. Do not implement casually; do not let its needs leak into
   the converter build.

36. **The anytime food→resources / food→points buys are FREE-SPAN** (ruled
   2026-07-06): available throughout the harvest span (field phase through
   end-of-harvest), NOT anchored to the last in-harvest moment. This DROPS
   the previously-approved late-anchor approach (its dominance argument
   fell to the Social Benefits counterexample: buying before the
   post-feeding "no food left" check can be strictly profitable).
   Consequence: Furniture Carpenter migrates off its FEED-only seam to
   free-span when the converter cluster builds; Paintbrush's VP option and
   Stone Sculptor's buy are free-span. Revisitable ("we can change this
   later if we want").
37. **The frontier boundary rule CONFIRMED** (2026-07-06): the generalized
   conversion frontier (ruling 34) integrates PURE goods→food converters
   only; any card whose output carries a rider — goods (Ebonist, Basket
   Carrier) or points (Stone Sculptor, Paintbrush's VP option) — surfaces
   as a standalone free-span trigger instead. Revisitable.
38. **Lumber Virtuoso is available throughout the harvest** (ruled
   2026-07-06, resolving its ask-at-build timing question): free-span, not
   start-of-harvest-only (the official implementation's narrowing is not
   followed here). [3+] — a design input until 4p.
39. **Post-breed cooking protection** (ruled 2026-07-06, the user's catch):
   after the breed action has resolved, the PARENTS and the OFFSPRING of a
   type that bred may not be cooked for the rest of that harvest — only
   non-parents. The user's implementation sketch: a per-type cooking FLOOR
   on post-breed in-harvest conversions — a type may not be cooked from
   (min_parents + 1) or above down below (min_parents + 1), i.e. below 3,
   or below 2 for sheep with Dolly's Mother in play. This becomes LIVE
   exactly when the converter cluster lands (today nothing cooks animals
   after breeding — the feed payment precedes breeding and the breed
   commit's own bundled cooking happens AT the commit); the generalized
   raise frame and any post-breed cooking surface must apply the floor.
   EDGE RESOLVED (2026-07-06): the user KEPT the shorthand — the floor
   reads CURRENT counts at cook time (a type at >= 3 may not be cooked
   below 3; >= 2 not below 2 for sheep with Dolly's Mother) and, crucially,
   is STATELESS: no breed-record is needed at all — the user's own
   observation ("how would a player end at 3+ without
   [CORRECTION 2026-07-13, user-driven: this record originally claimed the
   shorthand "slightly over-protects the capacity-blocked corner (parents
   whose newborn never fit)". That is WRONG — at count 2 the floor (3) does
   not bind and both animals stay cookable, and under the official
   only-if-room rule a capacity-blocked pair never bred and is correctly
   unprotected, so the floor is EXACT there. The real over-protection
   corners are: (a) a breeding-SKIPPED player (Layabout) holding 3+ — the
   stateless floor cannot tell they never bred; (b) the currently
   unreachable class of post-breed non-breed animal gains reaching 3+.
   Neither has an explicit user ruling yet.]
   breeding?") exposed that the record was only required under the stricter
   parents-and-offspring reading.

40. **Whole-phase-per-player banding extends to FEED and BREED; the outer
   harvest moments stay shared** (ruled 2026-07-06, extending ruling 3): the
   virtual walk gains a FEED band (start_of_feeding → the payment →
   after_feeding) and a BREED band (start_of_breeding → the breeding →
   after_breeding), each resolved wholly by one player before the other
   begins (starting player first), exactly like the existing FIELD band —
   the payment/breeding frames push one player per band pass instead of
   pairwise. The four OUTER moments — immediately-before-harvest,
   start-of-harvest, end-of-harvest, after-harvest — are SEPARATE from the
   three phase bands and keep their own windows, resolving
   both-players-per-moment as today. No frame or card changes; a walk-order
   engine change (full suite + C++ gates on landing).
41. **Field Cultivator becomes AUTOMATIC-take-the-maximum** (ruled
   2026-07-06): the per-occasion pile take is no longer a choice — the owner
   takes min(tiles harvested, pile remaining) goods automatically, the
   Scythe Worker mandatory-max precedent (document the simplification in
   the module; if a card ever makes holding building resources a liability
   or partial takes meaningful, restore the choice — the trigger form is in
   git history).
42. **Cooking Hearth Extension (C62) is DEFERRED alongside Gypsy's Crock**
   (user, 2026-07-12): it is pulled OUT of the converter-cluster build
   (ruling 34's queue had slotted it there as a `cooking_rates` doubler).
   Both cards modify how cooking itself works, and the user wants to decide
   how cooking-modifier cards are implemented as one dedicated design pass
   (the ruling-35 class) rather than piecemeal. Do not implement until that
   decision is made.
43. **Lettuce Patch (C70) "immediately" placement** (ruled 2026-07-12 — a
   per-instance "immediately" ruling under the ruling-18 standing
   instruction): "you can immediately turn each vegetable you harvested from
   this card into 4 food" is an optional trigger offered at the take
   occasion, ALONGSIDE the other optional triggers that fire on the field
   phase's harvesting action (the PendingHarvestOccasion stretch — Food
   Merchant's home). "Immediately" does not jump the queue ahead of them.
44. **Crop Rotation Field (E70) "immediately sow"** (ruled 2026-07-12):
   the granted opposite-crop sow on itself surfaces at the SAME trigger
   location as Lettuce Patch's convert — the removal-occasion optional
   stretch. Normal sow semantics (costs the supply crop), targets only this
   card, declinable ("you can"). Its firing condition stays the wider
   "remove" verb (any last-crop departure, the E-deck lexicon) — when a
   future non-take remover (e.g. Game Provider) empties the card, the sow
   is offered at THAT removal's instant.
45. **"Field tile" vs "field" — the lexicon** (ruled 2026-07-12, extending
   ruling 32): "field TILES" means the plowed fields on the farmyard grid;
   "field" is the BROADER category and includes card-fields. So a card-field
   counts for field-count readers — the Fields scoring category and any
   "you need N fields" requirement — while per-TILE readers still exclude it
   (ruling 32 unchanged).
46. **Per-FIELD harvest modifiers reach card-fields** (ruled 2026-07-12):
   Scythe Worker's per-grain-field extra, Stable Manure's donors, Grain
   Thief's replace targets — a card-field holding the qualifying crop is
   eligible. The take-modifier fold-fns must scan card-fields alongside the
   grid cells when the card-fields wave lands.
47. **Wood Field (D75) / Rock Garden (E80) stack semantics** (ruled
   2026-07-12): "as though it were 2/3 fields" = 2/3 independently-sowable
   STACKS (each sown separately, grain-like 3 wood / veg-like 2 stone per
   sow); the field-phase take harvests 1 from EACH non-empty stack; "but it
   is considered 1 field" scopes only the field-count readers of ruling 45
   (each card counts as exactly 1 field there).
48. **The sow-grant lexicon + the capped-sow accounting** (ruled 2026-07-12,
   from the full-catalog sow survey; the official clarification pair
   adjudicates it): a GENERIC "Sow" grant — even limited ("for exactly 1
   field": Chief Forester A115, Furrows D3, Changeover D71) — may target
   wood/stone card-fields (Chief Forester's clarification: "You may sow 2
   wood onto the Wood Field D075"); a CROPS-EXPLICIT grant ("sow crops" /
   "1 crop": Fodder Planter D115, Apiary E23) may NOT (Fodder Planter's
   clarification: "You may not plant onto Wood Field D075 this way") —
   crop-growing card-fields remain legal targets for both. Cap accounting:
   a card-field consumes exactly ONE field-unit of any capped sow's budget
   regardless of stacks, and that one unit may fill ANY subset of its empty
   stacks ("You may plant 2 wood at once with 1 trigger" — the "may"
   implies 1 is also fine). Within a normal uncapped sow, stacks are sown
   independently (Plant Fertilizer C8's clarification treats them as
   independent piles). Encoding: `PendingSow.crops_only` flag set by
   crops-explicit granters; default False (generic) — Family-inert, so
   canonical default-skip. Side note for future sow-modifier cards: the
   catalog's good-vs-crop wording is deliberate (Skimmer Plow / Cow Patty /
   Wild Greens say "good"; Tinsmith Master is clarified to grain/veg only).

49. **The round-end timing ladder** (ruled 2026-07-12): the returning-home
   phase is the round's LAST phase (preparation, work, returning home), and
   the "end of the round" is a DISTINCT, LATER instant — the returning-home
   seam fires BEFORE the end-of-round seam. The rungs, in order:
   `end_of_work` (the work phase's end, still DURING the work phase —
   Straw Hat E10 / Iron Hoe E20 / Apiary E23 / Sundial E26 / Piggy Bank E27 /
   Master Renovator E87 name this instant directly; Archway's placement here
   was REVISED to the after_work rung by ruling 50), then
   `start_of_returning_home` (before the phase — Turnip Farmer, Minstrel,
   Bohemian, Food Distributor, Sample Stable Maker), then `returning_home`
   (the phase itself — the "in the returning home phase" family, Silage
   included: its printed anchor plainly names the phase), then
   `after_returning_home` ("immediately after each returning home phase" —
   Steam Plow D18 — is CONCURRENT with it, a per-instance "immediately"
   merge), then `end_of_round` (Baking Course D64, Credit A54, Lifting
   Machine A70, Sculpture Course B53 — the "at the end of each round"
   family). The "that does not end with a harvest" condition suppresses its
   bearer on harvest rounds; UNCONDITIONED returning-home cards fire
   normally on harvest rounds, in the returning-home phase that precedes
   the harvest — the returning-home phase is DISTINCT from the harvest.
   (Perennial Rye C84's anchorless "Each round that does not end with a
   harvest" placement: proposed end_of_round with its condition-family
   siblings, NOT yet confirmed by the user.)

50. **The after_work rung + the ambiguity-defer category** (ruled
   2026-07-12): a separate `after_work` hook sits AFTER the `end_of_work`
   hooks and before `start_of_returning_home` — its members are Informant
   B117 ("After each work phase...") and Archway D51 ("Immediately before
   the returning home phase..." — revising ruling 49's initial
   end-of-work placement; the user: "this inconsistent wording is
   annoying"). The full round-end ladder is therefore: end_of_work →
   after_work → start_of_returning_home → returning_home (fired BEFORE
   `_resolve_return_home` resets placements, so the live board is the event
   data — the user's Swimming Class design, generalized) →
   after_returning_home → end_of_round → (the harvest, on harvest rounds,
   or the next round's preparation). **Perennial Rye C84 is DEFERRED FOR
   AMBIGUITY** (its anchorless "Each round that does not end with a
   harvest" confused the user too) — the first member of the new
   ambiguity-defer category below, distinct from the power bans. Out of
   scope for this arc (confirmed): Delayed Wayfarer E125 (extends the work
   loop's termination), Steam Machine C25 / Market Master E131 (own-last-
   placement instants, not the shared boundary).

51. **Baking Course D64 supplies a GLOBAL baking rate** (ruled 2026-07-12):
   its second sentence ("'Bake Bread' action: Grain → 2 Food") is the card
   supplying an UNLIMITED grain→2-food conversion rate during ALL Bake
   Bread actions, "just like the fireplace does" — a standing baking source
   (the BAKING_SPEC_EXTENSIONS seam), NOT a rate scoped to the bake the
   card's first sentence grants. The grant itself is an optional
   end_of_round bake (non-harvest rounds, ruling 49's rung).

52. **Dolly's Mother does NOT reach Silage's mid-round breed** (ruled
   2026-07-12): Silage's pair threshold is a FLAT 2 for every type — Dolly's
   Mother's printed scope is "during the breeding phase of a harvest", which
   Silage's returning-home breed is not, so the `sheep_min_parents` seam
   deliberately does not apply there (it keeps reading through everywhere
   its printed scope covers).
53. **Heresy Teacher A113 is UN-IMPLEMENTED and moved to the ambiguity
   defers** (user, 2026-07-12): the sole producer of mixed grain+veg fields
   ("Place the vegetable below the grain") made every per-field interaction
   ruling too complicated and unclear (the Scythe-E73 "all the crops" gap,
   the crop-count group keys, the card-field mixed stacks). Its module +
   tests are archived under `archive/deferred_cards/` (never deleted). The
   card's own text is clear — the deferral is about its interaction surface.
   CONSEQUENCE: mixed grain+veg fields are now UNREACHABLE (grid and card
   stacks alike), so the flagged mixed-field wrinkles are moot until it (or
   another mixer) returns; the machinery keeps supporting mixture (the
   card-field 4-tuple stacks, the take's grain-precedence) — that generality
   stays correct and tested at the seam level.

Also settled in this design thread: C++ byte-identity is **not** a constraint on this
redesign — design the Python harvest machinery on its merits and re-port to `cpp/` if a
Family-shape change falls out (the user explicitly deprioritized gate-preservation here in
favor of the best card-engine design). And per the CLAUDE.md Phase-3 directive added
2026-07-03: **4-player is an eventual goal — [3+]/[4] cards are design inputs** for this
machinery (e.g. Old Miser's per-person feeding discount, Game Provider's immediately-before
field-crop discard, Champion Breeder's newborns-placed count), even though they aren't dealt
at 2 players.

54. **The preparation ladder** (ruled 2026-07-14; order REVISED by the user the
   same day). The start of the round IS the start of the preparation phase
   (the pre-ladder engine's single `start_of_round` event — fired at the END
   of preparation, after the WORK flip, conflating "start of each round" with
   "start of each work phase" — was wrong on both counts). The ruled order,
   each an explicitly DISTINCT instant: **before the round → round card
   revealed → round-space goods collected → start_of_round → replenishment →
   before the work phase → start of the work phase.** (The first draft
   collected before the reveal; the user corrected it — reveal first — which
   also restored the pre-ladder Family order, so the C++ twin needed no
   change in the end.) Built as the third timing ladder
   (`agricola/cards/preparation.py`, `engine._advance_preparation` —
   CARD_ENGINE_IMPLEMENTATION.md §5d); re-tagged by printed text:
   Freemason / Cob / Trout Pool → `start_of_work`, Nest Site →
   `replenishment`, Pavior ("at the END of each preparation phase") →
   `before_work`, Small Animal Breeder / Civic Facade ("BEFORE the start of
   each round") → the new `before_round` rung — the ladder's first instant,
   pre-reveal and pre-collection, so Small Animal Breeder's food threshold
   deliberately does NOT count this round's round-space income, and "the
   current round number" there is `round_number + 1` (pre-increment).
   RESOLVED same day: the round-space schedule grants ("at the start of
   these rounds, you can plow the field [on the round space]" — Handplow,
   Plowman, Chain Float, Grassland Harrow, Small Greenhouse, Stable Planner,
   Tree Farm Joiner) resolve at COLLECTION time — the
   `round_space_collection` window, post-reveal but before `start_of_round`
   — not the `start_of_round` rung. No rung question remains open.

55. **Museum Caretaker fires as auto AND trigger at `start_of_work`** (ruled
   2026-07-14): the mandatory "you get" is an automatic effect ordered AFTER
   the window's other autos (the `register_auto(order=)` mechanism — Freemason
   first), PLUS a trigger so same-window TRIGGER grants that newly complete
   the six-goods criterion still yield the point; hard cap 1 point per round
   (`used_this_round` latch shared by both paths). Implementation note (not
   part of the ruling): with today's catalog the trigger half has no live
   firing partner — Cob, the only implemented `start_of_work` trigger,
   requires ≥1 clay itself and cannot flip the criterion — the user confirmed
   2026-07-14 that this is fine; the machinery awaits a criterion-good-
   granting `start_of_work` trigger card.

56. **Sugar Baker's deposited food is a CardStore debt, not board state**
   (ruled 2026-07-14, option (b) of the two representations offered): the food
   owed to Grain Utilization's next visitor rides the owner's CardStore and is
   granted by an any_player `before_action_space` auto — rules-identical to
   food physically on the space (the space maxes at 1 food: any next visit
   collects in its before-phase), with no Grain Utilization machinery change.

57. **Clutterer counts passed-away travelers** (ruled 2026-07-14): "each card
   played after this one" includes a qualifying traveling minor (Wood Pile)
   the owner played and passed on — so the count accrues AT PLAY TIME (the
   `played_card_id` stamp on the play hosts), never as a scoring-time
   tableau diff.

58. **Blighter's "complete stage left to play" = 6 − stage_of_round(current
   round)** (ruled 2026-07-14): the in-progress stage is not complete (stage-2
   play banks 4; round 14 banks 0); and its "may not play any more
   occupations" is the occupation-play blocker consulted at the
   `playable_occupations` chokepoint (one gate, every route).

59. **Prodigy** (ruled 2026-07-14): "improvement" = majors AND minors; "your
   1st occupation" = literally the first occupation played all game, by any
   route; the per-improvement point count freezes at play (the banked-VP
   idiom), per the printed parenthetical.

60. **The deferred after-flip** (ruled 2026-07-14): an "after you [do X]" card
   effect fires after X's FULL effect — everything the effect pushed included
   — never in the gap between X's commit and X's own effect resolving. The
   motivating case: Bonehead's "immediately after each time you play a card
   from your hand, you get 1 wood from this card" must NOT hand over the wood
   in time to fund the played card's own effect (Established Person's granted
   fences). Built as the user's own design: commit executors set an
   `effect_initiated` work-complete signal on their host instead of flipping
   it inline, and `_advance_until_decision` flips the host (firing the
   after-autos, plus the coarse `after_build_improvement` for the two
   improvement hosts) once the host is back on top — i.e. after every frame
   the effect pushed (an on_play's primitive, an oven's free-bake wrapper) has
   resolved. Two corollaries the user approved in the same discussion: the
   **accommodation barrier resolves BEFORE the deferred flip** (a keep-which-
   animals choice raised by the effect is part of the effect settling, so the
   after-autos wait for it too), and the mechanism applies **uniformly to
   every commit-terminated host** (play occupation/minor, sow, bake, plow,
   renovate, build major, family growth, the three animal markets) — one flip
   rule shared with the Delegating hosts' `subaction_complete`. This is a
   Family-visible change (the ovens' free bake is the Family-reachable pushed
   child), re-ported to `cpp/` in the same change with all 139 differential
   gates green. Machinery reference: CARD_ENGINE_IMPLEMENTATION.md §2;
   ordering pins: `tests/test_deferred_after_flip.py`.

61. **The 2026-07-14 card-batch rulings** (all user-ruled in the batch's design
   discussion; each is quoted in its card module's docstring):
   - **Fish Farmer D110**: the use-bonus reading — using Reed Bank / Clay Pit /
     Forest while Fishing holds exactly 1 / exactly 2 / 3+ food pays +2 food
     from the CARD (general supply); no food ever sits on those spaces. The
     misprint "Grove" is corrected to "Forest" in the data file's text (the
     card's own errata), per the user's instruction that our displayed text
     say Forest.
   - **Kindling Gatherer E118**: only food the SPACE itself yields counts —
     card-provided food (Fish Farmer, Brook) never triggers it. Implemented as
     the fixed space list day_laborer + fishing (2p), with the one
     user-anticipated exception hard-coded: a Sugar Baker deposit on Grain
     Utilization IS food on a space, so collecting it pays the wood (the
     order=-1 before-auto reads the deposit before Sugar Baker's collection
     clears it). Traveling Players joins the list at 4 players.
   - **Sowing Master D109**: "an action space with the 'Sow' action" ≡ Grain
     Utilization or Cultivation today (the +2 food fires whether or not the
     player sowed); the equivalence breaks if a future card creates a new
     sow-bearing space — revisit the space list then.
   - **Informant B117**: "after each work phase" = the round-end ladder's
     `after_work` rung (the two wordings name one instant for this card).
   - **Merchant C96**: House Redevelopment's optional improvement step COUNTS
     ("the action is distinct from the action space"); "immediately after" is
     the ordinary after seam on the composite host; "a second time" forbids
     chaining off its own granted action (provenance-gated). OPEN LEAN parked
     for the user: a Merchant-granted second take does NOT fire Small Trader's
     space bonus (provenance ≠ the space) — matches Small Trader's own
     clarification, not explicitly ruled.
   - **Bonehead D118**: "immediately after each time you play a card" is the
     ordinary after seam; "including this one" is paid inside its own on_play
     (net 5 wood on the card, +1 to supply — the same instant), with a
     played_card_id guard so the generic after-auto (which under ruling 60 now
     runs post-on_play) cannot double-pay the self-play.
   - **Optionality confirmations**: Little Stick Knitter's growth, Young
     Farmer's sow, and Stallwright's stable are OPTIONS (triggers), and
     Stallwright additionally requires stable pieces in supply.
   - **Wide vs deep**: Green Grocer / Forest Trader / Bellfounder / Emergency
     Seller surface WIDE (variant triggers / play-variants; Emergency Seller's
     full multiset enumeration — worst case 126 — explicitly approved);
     Beneficiary is DEEP (play the card → an occ/minor/proceed parent → the
     chosen type's cards → the remaining type or proceed → end), built by
     generalizing `PendingGrantedSubAction` to a category set + `occ_cost`.
   - **Master Renovator E87**: "at the end of the work phases" = the round-end
     ladder's `end_of_work` rung; the discount is a renovate cost conversion
     scoped by the new `CostCtx.granted_by` provenance (seam 700d16a).
   - **Field Doctor E92**: "surrounded by 4 field tiles" = ALL surrounding
     cells of the 2-room house, orthogonal AND diagonal, on-board, are field
     tiles (the starting domino has exactly 4 such cells); the data-file text
     is corrected to "Wish for Children" per the card's clarification.

62. **Empty animal markets stay ILLEGAL to place on** (2026-07-14, prompted by
   Fir Cutter's empty-market question; briefly ruled legal, REVERSED by the
   user the same day — the `accumulated_amount > 0` gates stay in both
   engines). The state is unreachable in real play anyway (every revealed
   accumulation space refills each preparation, and a use occupies the space
   for the round), so nothing observable hinges on it today; if a future card
   makes empty+available reachable, re-raise the question. Fir Cutter's
   "empty market still pays" unit test exercises the host flow on a
   constructed state via `step` (which doesn't verify legality), so it
   documents the card's behavior without contradicting the gate.

63. **The 2026-07-15 follow-up-batch rulings** (each quoted in its card module):
   - **Cottar E122**: "immediately after paying its cost" is implemented as the
     improvement's ordinary AFTER window (after the improvement, its effect
     included) — the official online implementation's instant, chosen by the
     user for consistency despite the printed wording naming the payment
     moment. Landing it also gave the play-minor and build-major hosts the
     mandatory-Stop gate their after-phases lacked (the atomic-host pattern;
     Family-inert — the gate is a no-op with no mandatory registrant).
   - **Moral Crusader B106**: "immediately before the start of each round"
     names the SAME instant as the preparation ladder's `before_round` window.
   - **Tinsmith Master B115**: the per-field "+1 crop, you can" is MEANINGFULLY
     DECLINABLE — the sow commit carries per-crop-type boost counts (how many
     sown grain/veg fields take the +1), never an always-max simplification.
   - **`ActionSpaceState.revealed_round`** (user decision): every space records
     the round whose preparation revealed it (permanents 0; deliberately
     redundant with `revealed` to avoid reworking its consumers) — built for
     the reveal-order family (Task Artisan now; Master Workman, Sweep,
     Outrider/Pioneer later). Task Artisan rides the preparation ladder's
     `reveal` window with `revealed_round == round_number` as "appeared this
     round".
   - **Furniture Maker × Forest School — RULED (user, 2026-07-15)**:
     wood-substituted occupation food does NOT count as "food paid as
     occupation cost" (the player paid wood, not food), so Furniture Maker
     grants nothing for a Forest-School-substituted play. Built as a card-only
     guard (no engine change): Furniture Maker subtracts the substitution when
     `"forest_school"` is in the host's `triggers_resolved`. Exact for today's
     catalog because Forest School substitutes the WHOLE printed food cost in
     one fire; a future PARTIAL food-substitution card would need the
     substituted amount tracked. Pinned by
     `test_forest_school_substituted_food_pays_no_wood`.
   - **Emergent interaction noted (falls out of shared machinery, not coded)**:
     an Angler-granted improvement action can be Merchant-doubled — the
     granted composite fires the ordinary after window and Merchant's no-chain
     guard only blocks its own provenance; textually consistent since the
     grant IS "a Major or Minor Improvement action".

64. **The "Major or Minor Improvement" action vs the "Minor Improvement"
   action vs the action *space*** (ruled 2026-07-15 — the recurring
   confusion, now documented explicitly in RULES.md's Primitive Sub-Actions
   ⚠️ callout + CARD_ENGINE_IMPLEMENTATION.md §6). There are two DISTINCT
   primitive sub-actions: the **"Major or Minor Improvement" action** (build a
   major OR play a minor — offered by the Major Improvement space, House
   Redevelopment, and card grants; engine: `PendingMajorMinorImprovement` /
   `after_major_minor_improvement`) and the **"Minor Improvement" action**
   (play a minor only — offered by Meeting Place, Basic Wish for Children, and
   card grants; engine: a bare `PendingPlayMinor` / `after_play_minor`). Card
   text keys off the ACTION (the primitive), never the space. Consequences
   this ruling corrected:
   - **Small Trader** ("+3 food each time you take a 'Major or Minor
     Improvement' action to play an improvement from your hand") keys off the
     'Major or Minor Improvement' action — so it fires on House Redevelopment
     and card grants (Angler; a Merchant repeat), NOT only the Major
     Improvement space; and never on Meeting Place / Basic Wish (those are the
     'Minor Improvement' action). Its prior `initiated_by_id ==
     "space:major_improvement"` gate was an un-ratified narrow reading, removed
     — the `after_major_minor_improvement` event already scopes to the
     composite, so the gate is just `minor_chosen`. Still minors only
     ("from your hand").
   - **Merchant** ("after a 'Major or Minor Improvement' OR 'Minor
     Improvement' action, pay 1 food to take the action a second time") was
     incomplete — it only handled the composite. Now it fires on BOTH action
     types with a TYPE-MATCHED repeat (composite → a second composite; bare
     minor → a second bare minor), and — user-confirmed 2026-07-15 — chains off
     **card-granted** bare minors too (Beneficiary / Task Artisan / Sample
     Stable Maker), by symmetry with Angler firing it on the composite side.
     Guards: no self-chain (`card:merchant`), and the bare-minor clause
     excludes the composite's own child minor (`major_minor_improvement`,
     handled by the composite clause). MACHINERY NOTE surfaced: a card firing
     on two events shares ONE frame-dispatched `apply_fn` (fire dispatch is
     id-keyed via `CARDS`); per-event eligibility is safe (the enumerator reads
     event-keyed `TRIGGERS`).

65. **Forest School replaces the occupation's food cost PER FOOD, priced by the
   route** (2026-07-17; a live-defect find during the tier triage — the card was
   implemented, not deferred, so this is a fix ruling). Two halves:
   - **"Each food that an occupation costs" is a per-unit license**: the player
     may replace any subset — k wood → k food, k ≤ min(food cost, wood held) —
     so MIXED payments are legal (1 wood + 1 food on Writing Desk's 2-food
     granted play). Rebuilt as a play-variant trigger (one FireTrigger per k),
     each k guarded so the play stays payable AFTER the swap (the play host has
     no decline — the standing stranding rule; the same guard filters a k below
     the shortfall).
   - **The price is the frame's `PendingPlayOccupation.cost`**, never re-derived
     from the Lessons ramp. The original implementation computed
     `occupation_cost(len(occupations))` — right on Lessons (identical by
     construction) and coincidentally on Scholar (owning Scholar forces the ramp
     to 1, its flat price), wrong on every differently-priced granted route: a
     phantom 1-wood → 1-food swap on Seed Researcher's FREE play, a mis-sized
     swap on Writing Desk's 2-food play, and an under-recognizing affordability
     gate (2 wood + 0 food could not reach Writing Desk's grant).
   MACHINERY (both Family-inert): `OCCUPATION_FOOD_SOURCES` sources now receive
   the route's actual cost — `source_fn(state, idx, cost)`, all five registrants
   migrated (only Forest School reads it) — and the play-occupation enumerator
   expands variant triggers (`_expand_variant_triggers`, the same
   no-op-when-unregistered wrapper the atomic and delegating hosts use).

66. **The 2026-07-17 tier-1 batch rulings** (each quoted in its card module; the
   batch: Heart of Stone C21, Seed Almanac E18, Recycled Brick D77, Nail Basket
   E15, Profiteering E82, Double-Turn Plow A20, Furrows D3, Pole Barns E1,
   Lumber Pile E76, Thunderbolt E4, Night Loot E5 — 11 minors, all on existing
   seams, no engine change):
   - **"Immediately" adds nothing in this batch** (the standing per-instance
     check, ruled for all seven occurrences at once): the six on-play uses
     (Pole Barns, Furrows, Thunderbolt, Night Loot, Lumber Pile, Double-Turn
     Plow) are the ordinary on-play instant, and Heart of Stone's is the reveal
     window's instant. Triggers on the same instant fire in any player-chosen
     order.
   - **Pole Barns builds stables as a CARD EFFECT, not a "Build Stables"
     action** — the pushed frame carries `build_stables_action=False`, so an
     action-keyed card never fires on it (a verb-keyed "each time you build a
     stable" card still does). Contrast Nail Basket, whose grant IS the literal
     named "Build Fences" action (`build_fences_action=True`).
   - **Double-Turn Plow may stop after 1 field** (the multi-shot plow's
     Proceed-at-≥1; never forced to the second plow).
   - **Thunderbolt enumerates board fields BY GRAIN COUNT** (equal-count board
     fields are interchangeable — the fungible-board-field convention; the
     executor strikes the deterministic lowest-(row, col) representative), while
     each grain-bearing CARD field stays its own variant: card-crop removal
     routes through the ruling-44 `remove_card_crop` chokepoint so its
     registered reactions fire.
   - **Night Loot is unplayable with fewer than 2 different building-resource
     types on revealed accumulation spaces** (a prereq — never a dead-end and
     never a partial take).
   - **Nail Basket's "wood accumulation space" family is the
     `WOOD_ACCUMULATION_SPACES` constant** (agricola/constants.py), hooked over
     the whole set for 4-player forward-compatibility (only Forest is live at
     2 players).

67. **Occupation-cost substitutions are COST CONVERSIONS under
   `action_kind="play_occupation"`** (2026-07-20; Working Gloves E60 built on it,
   Forest School migrated onto it). The rulings:
   - **"Pay X in place of food" cards resolve through the `effective_payments`
     chokepoint**, never as triggers or food sources: one
     `CommitPlayOccupation(payment=...)` per Pareto-minimal way to pay the
     OCCUPATION COST PROPER (the frame's route-supplied cost). Consequences, all
     structural: dominated offers are pruned (the user's requirement — Working
     Gloves' 1-wood payment suppresses Forest School's 2-wood on a 2-food cost;
     identical vectors de-duplicate), double-replacement is inexpressible (a
     payment replaces each food unit at most once), and ruling 65's mixed
     payments are ordinary frontier points. The no-substitution path keeps the
     legacy `payment=None` commit shape.
   - **Surcharges and individual printed costs are SEPARATE from the occupation
     cost and may never be reduced or modified** (user, 2026-07-20) — even when
     the code debits them simultaneously. A play-variant surcharge (Roof
     Ballaster) is added to the debit on top of the chosen payment, outside the
     pipeline; each (variant, payment) commit is gated on the COMBINED debit
     being payable.
   - **Working Gloves always replaces min(2, cost.food)** — "(up to) 2" never
     makes a smaller replacement a real choice (same 1-resource price, strictly
     dominated). The 2026-07-17 catalog scan backs the design: the occupation
     cost proper never exceeds 2 food anywhere (base ramps cap at 2 at 3-4
     players; Moonshine/Writing Desk grant at 2; nothing raises it), so Forest
     School is weakly dominated whenever Working Gloves is co-owned — enforced
     by the prune, not by card logic.
   - **The executor stamps `PendingPlayOccupation.paid_cost`** (base-cost payment
     only, surcharge excluded) alongside `played_card_id`, so "food paid as
     occupation cost" readers (Furniture Maker, ruling 63) are exact under
     partial substitution — the old all-or-nothing `triggers_resolved` guard is
     gone with the trigger it read.
   MACHINERY (all card-only/Family-inert): the `play_occupation` ctx +
   `can_pay`-based `_payable_occupation` (food sources simulate on top),
   payment-carrying wide commits, `CommitPlayOccupation.payment` +
   `PendingPlayOccupation.paid_cost` (both canonical-default-skipped), and the
   occupation-food-source seam re-scoped to PRODUCERS only.

68. **The 2026-07-20 tier-2 batch rulings** are recorded in
   `CARD_ENGINE_IMPLEMENTATION.md` §1 (the batch entry) and quoted per-card in the
   ten tier-2 modules — the number is reserved here so the sequence stays navigable.

69. **The 2026-07-20 tier-3 batch rulings** (each quoted in its card module):
   - **A21 Family Friendly Home** (name corrected from the data JSON's erroneous
     "Family Friend Home"): the rooms>people measure occurs BEFORE the Build Rooms
     action — before the first room is built — so the card lives on
     `before_build_rooms`; and if rooms>people at that instant, the 1 food is given
     whether or not the family growth is accepted (an automatic effect beside the
     optional growth trigger). "Take a 'Build Rooms' action" is read as the NAMED
     action only — gated on `PendingBuildRooms.build_rooms_action`, with Cottager's
     granted build-1-room corrected to set it False per the §9.6 flag contract.
     (The named-action gate — originally the driver's application of the RULES.md
     doctrine — was USER-CONFIRMED 2026-07-20: "gated to the named action only -
     this is correct".)
   - **B17 Forest Plow**: fires AFTER the take — an explicit per-card override of
     the "each time you use = before" default (the deposit is "for the next
     visitor"; before-timing would let the player's own sweep scoop the deposited
     wood straight back). The 2 wood is paid from the player's supply whatever its
     origin, the just-taken wood included — the clarification decouples the effect
     from how much wood the space actually yielded.
   - **C73 Seaweed Fertilizer**: an "unconditional" Sow action = one with no
     constraint on the number of fields sown or the types of crops/goods sown —
     i.e. a `PendingSow` with `max_fields == 0`, `crops_only == False`, and
     `required_crop is None`. Modeled Seasonal-Worker-style (one mandatory
     `after_sow` trigger whose options are round-gated: grain-only before round 11,
     grain-or-vegetable from round 11); the sow host's after-phase gained the
     standard mandatory-Stop gate (mirroring the build-major after-phase).
   - **D80 Brick Hammer**: "costing at least 2 clay" reads the PRINTED cost, never
     the payment actually made; for an improvement with multiple printed
     alternative costs, ANY >=2-clay alternative qualifies even when the player
     paid the alternative without clay (so a Cooking Hearth bought by returning a
     Fireplace qualifies — printed 4/5 clay). Machinery: the ownership-gated
     `PendingBuildMajor.built_major_idx` identity stamp
     (`register_build_major_identity` in `cards/triggers.py`).
   - **D1 Zigzag Harrow**: "zigzag" means, verbatim, a pattern like
     {(x, y), (x+1, y), (x+1, y+1), (x+2, y+1)},
     {(x, y), (x, y+1), (x+1, y+1), (x+1, y+2)},
     {(x, y), (x+1, y-1), (x+1, y), (x+2, y-1)}, or
     {(x, y), (x-1, y+1), (x, y+1), (x-1, y+2)} — the four orientations of the
     S/Z tetromino; the plowed field plus 3 existing field TILES must form one,
     translated anywhere on the farmyard. Machinery: `PendingPlow.allowed_cells`
     (mirroring `PendingBuildStables.allowed_cells`).
   - **E3 Tea Time**: the vacated space is OPEN — what makes a space illegal to
     place on is solely the presence of a worker on it; there is no residual
     "used this round" block, so either player may use Grain Utilization again
     that round after the return.

70. **The 2026-07-20 approvals batch** (user approvals + the Stone Clearing
    engine layer; each card ruling quoted in its module):
   - **Cluster C3 is APPROVED** (user, 2026-07-20): "take a good off an
     accumulation space without placing a worker" is a sanctioned mechanism —
     an optional trigger that edits `sp.accumulated`. Both members built:
     **A82 Work Certificate** (an `after_action_space` play-variant trigger on
     every own space use; its printed threshold "at least 4 building resources
     on it" is read as the TYPELESS total on the space, any mix — contrast
     Material Hub's typed wording — and any building-resource type present is
     takeable (USER-CONFIRMED 2026-07-20: "typless total is correct, and the
     player can take any resource type that exists on the relevant space");
     its clarification "Can be immediately triggered" means the very
     use that plays the card may fire it, the machinery's natural
     ownership-at-fire-time behavior) and **B81 Handcart** (a `before_work`
     prep-window play-variant trigger; the space's FAMILY sets the threshold
     NUMBER — wood 6 / clay 5 / reed 4 / stone 4 — but per the user's ruling,
     2026-07-20 verbatim: "the X resources of the same type do not need to be
     the native type of the action space. Additionally, the player can take
     any resource from the space, not just the resource that has a count of
     X+." — so ANY single type reaching the number qualifies the space, and
     any building-resource type present is takeable. This CORRECTED the
     driver's first-pass native-type analog of the Material Hub ruling).
   - **C6 Stone Clearing — the engine layer** (user go-ahead 2026-07-20, with
     the explicit instruction that stone-holding fields must never read as
     empty for sowing, card prerequisites, or card effects): `Cell.stone` +
     the `Cell.field_empty` / `Cell.field_planted` single-definition
     predicates; every emptiness/planted read swept onto them (sow legality,
     the sow executor, the restricted wrapper, and the reader cards —
     Greening Plan, Potato Digger, Asparagus Gift, Fern Seeds, Fodder
     Planter, Slurry Spreader C71 now exclude stone fields from
     empty/unplanted; Field Clay, Garden Claw, Ash Trees count them as
     planted per the errata "considered planted until the stone is gone");
     the field-phase take harvests stone normally (1/phase to supply, a
     `crop="stone"` manifest entry). **The scope question was RULED same day**
     (user, 2026-07-20, verbatim): ""place 1 stone on each of your empty
     fields" cover[s] empty card-fields too … Stone Clearing should place 1
     stone on all fields, including cards like beanfield and wood field that
     have restrictions on what can be sowed on them (wood field would get 1
     stone not 2)" — so every empty card-field gets exactly 1 stone per CARD
     (into one stack), sow-goods restrictions never restrict the placement,
     and the module is IMPLEMENTED. One driver-adopted reading rides along,
     TENTATIVELY AGREED by the user (2026-07-20 — "this is an interesting
     question. I will tentatively agree"; provisional, may be revisited):
     stone in one Wood Field stack leaves the other
     stack wood-sowable (the machinery's established per-stack sowability —
     the same behavior as a half-wood-planted Wood Field; the errata's
     "considered planted" is the field-level reader status).

72. **The 2026-07-21 boundary-buster batch** (user rulings 2026-07-21; each
    quoted in its card module):
   - **Carpenter's Bench B15 is 🚫 WONTFIX** — its "the taken wood (and only
     that)" payment-source restriction is the §8 goods-provenance cost gap,
     ruled not worth building for this card.
   - **Stone Company A23**: "immediately after each time you use a Quarry
     space" = the quarry host's after window; the grant is the NAMED composite
     with the new `CostCtx.min_spend=Resources(stone=1)` filter (post-modifier,
     pre-Pareto — the printed Stonecutter clarification is emergent); the
     Fireplace-return route never satisfies the constraint; a Merchant repeat
     is a fresh, unconstrained composite.
   - **Firewood C75**: "Fireplace / Cooking Hearth / oven" are the RULES.md
     collective terms INCLUDING the minor improvements whose name's second
     word is Oven/Fireplace (slug suffix `_oven`/`_fireplace` — iron_oven,
     simple_oven today; `oven_site` excluded); the deposit wood is from the
     general supply; "up to 4" is offered take-max only (min(4, stock) — the
     ruling-41 dominance shape); firing restricts the pending build/play to
     the qualifying targets (`allowed_majors` ∩ / the new
     `PendingPlayMinor.allowed_cards`).
   - **Fatstock Stretcher D56**: implemented as +1 to the sheep and boar
     cooking rates, per-component ONLY where the base conversion exists —
     (2,2,3)→(3,3,3), (0,0,0) stays (0,0,0), (3,0,5)→(4,0,5); flows through
     `cooking_rates` into every cook site; card-driven exchanges (not via a
     cooking improvement) get nothing. This builds the cooking-rate injection
     seam (`cooking_mods.py`) — the ruling-42 cluster's additive member may
     proceed ahead of the full cooking-modifier design pass.
   - **Renovation Company A13** (un-deferred — its 2026-07-15 blocker was the
     then-missing zero-cost grant parameter, since built as `cost_override`):
     "immediately after" = within the card's play; the free renovate keeps
     the NORMAL target menu (Conservator's wood→stone composes, free either
     way); the decline is the play-variant choice (the clarification's
     non-bankable decline); under a renovate-forbid card the renovate variant
     is withheld (the never-offer-a-dead-end rule) and the card stays playable
     for its unconditional +3 clay.

---

## Deferred for AMBIGUITY (the printed text is unclear — distinct from the power bans)

Cards here are set aside because their PRINTED TEXT does not determine a reading —
not because of strength (the banned list) or missing machinery (the defer clusters).
Each entry needs the user to pick a reading (or an official clarification to
surface) before implementation.

- **Perennial Rye C84** (minor; "Each round that does not end with a harvest, you
  can pay 1 grain to breed exactly 1 type of animal. (This is not considered a
  breeding phase.)") — deferred 2026-07-12 (ruling 50): the timing anchor is
  missing entirely (every sibling names "the end of each round" or "the returning
  home phase"), and the user found the card's intent unclear ("perennial rye does
  seem confused").

- **Heresy Teacher A113** (occupation, [1+]; "Each time you use a 'Lessons' action
  space, you get 1 vegetable in each of your fields with at least 3 grain and no
  vegetable. Place the vegetable below the grain." Clarification: "Fields with both
  crops can count as a grain field or a vegetable field, but not both
  simultaneously.") — UN-implemented and placed here by the user 2026-07-12
  (ruling 53): the card itself is clear, but as the only mixed-field producer it
  made the per-field interaction rulings too complicated; archived under
  `archive/deferred_cards/`.

- **Lumber Virtuoso D129** (occupation, [3+]; "Each harvest in which you have at
  least 5 wood in your supply, you can discard down to 5 wood to take a "Build
  Stables" or "Build Wood Rooms" action by paying the usual costs." Clarification:
  the "Build Wooden Rooms" action is a "Build Rooms" action limited to wood.) —
  placed here by the user 2026-07-12 (superseding the earlier waits-for-4p
  status; ruling 38's free-span timing stands if it is ever un-deferred). The
  "discard down to 5 wood" quantity clause does not determine a reading.

## Deferred 2026-07-12 — Braid Maker E109 (the converter cluster's one defer)

**Braid Maker (E109, occupation)**: "Each harvest, you can use this card to exchange
1 reed for 2 food. You can build the Basketmaker's Workshop for 1 reed and 1 stone
even when taking a "Minor Impr." action." The FIRST clause fits the converter seam
exactly (a pure reed->2-food `HarvestConversionSpec` + `frontier_fire`). The SECOND
clause needs a seam that does not exist: a play-MINOR surface (Basic Wish's minor
branch, Meeting Place's optional minor, the improvement spaces' play-minor branch)
additionally offering the build of one specific MAJOR at an alternate cost. The
existing composite host runs the other direction (the Major/Minor space offering
both), and no legality extension lets a card inject a major build into minor-only
surfaces. Per §0.1 and the recorded 2026-07-12 refinement (HARVEST_HANDOFF.md §16
item 3), a card defers WHOLE when any clause doesn't fit — implementing only the
converter clause would be an approximation. Build proposal: a
`register_minor_action_major_build(card_id, major_idx, alt_cost)` legality
extension on the play-minor enumerators; small, but user-gated like the other
shared-infra proposals.

## Group A — small, well-scoped, high-yield (recommend building on approval)

### A1. Card-granted Family Growth with NO space placement
> **PRIMITIVE BUILT 2026-07-03** (commit "card-granted family growth — place_on_space=False"):
> `PendingFamilyGrowth.place_on_space` landed exactly as proposed below, with tests
> (`tests/test_family_growth_grant.py`). The member cards are NOT yet implemented — Autumn
> Mother (C92) and Bed in the Grain Field (C24) ride the harvest-window card wave
> (HARVEST_WINDOWS_DESIGN.md); A93 / B92 / A21 below still await their own batch, and the
> A21 question (room-count timing + food coupling) is still open.

**Cards unblocked:** A93 Bed Maker, B92 Little Stick Knitter, A21 Family Friendly Home (rescued;
name corrected 2026-07-20 — the data JSON's "Family Friend Home" was wrong).

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
**Question (A21 Family Friendly Home only) — RESOLVED (user ruling 2026-07-20, ruling 69):**
"if you have more rooms than people" is measured **before** the Build Rooms action (before the first
room is built) — the note above proposing `after_build_rooms` / a post-build default is superseded;
the card lives on `before_build_rooms`. And the **+1 food is unconditional on the condition**: if
rooms>people at that instant, the food is given whether or not the family growth is accepted.
(Implemented 2026-07-20 as `family_friendly_home.py`.)

### A2. "On your turn" build exclusion (off-turn builds don't trigger)
**Cards unblocked:** A43 Farmyard Manure, A74 Stable Tree.

**Blocker.** Both schedule goods "each time you build 1+ stables **on your turn**," and the printed
clarification excludes off-turn builds (Groom B089 / Stable Planner A089). A naïve `after_build_stables`
auto also fires on those start-of-round grants.

**Proposed build.** A card-local eligibility predicate — the build is "on your turn" iff **no
preparation-window choice frame is on the stack**. In the current card set every off-turn stable
build is a preparation-ladder grant (Groom at `start_of_round`, Stable Planner at
`round_space_collection`), which carries a `PendingHarvestWindow` frame with a prep window id at
the bottom of the stack; a real worker-placement build never does. So "no `PendingHarvestWindow`
whose `window_id` is in `preparation.PREP_STEPS`" in the auto's eligibility is exact today. No
engine change. I'd add a shared helper `_is_on_turn_build(state)` for reuse.

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
**Cards unblocked:** B1 Upscale Lifestyle; partially Renovation Company (A13 — **BUILT 2026-07-21**,
ruling 72, as a `cost_override` play-variant), Established Person (B88).

**Blocker.** A card that grants an **optional** renovation ("if you take the action…") can't use a bare
`PendingRenovate` — its before-phase enumerator emits only `CommitRenovate`, no `Stop`, so there's no
decline path.

**Proposed build.** A `PendingGrantedRenovate` choose-or-decline wrapper, exactly mirroring the existing
`PendingGrantedBuildFences` (sole sub-action `renovate` → push real `PendingRenovate`; the wrapper's
`Stop` is the decline). No change to House Redevelopment / Cottager.

**Effort:** ~20 lines. **Risk:** low-medium.

### A5. Bottom-row major classification — IMPLEMENTED (2026-07-15, `wage.py`)
**Card:** B7 Wage ("+1 food per owned bottom-row major improvement").

**Built:** `BOTTOM_ROW_MAJORS = frozenset({5, 6, 7, 8, 9})` (Clay Oven, Stone Oven, Joinery, Pottery,
Basketmaker's Workshop); Wage's on-play read counts owned bottom-row majors off
`board.major_improvement_owners`. Top row = {Fireplace ×2 (0,1), Cooking Hearth ×2 (2,3), Well (4)}.

**Confirmed (user, 2026-07-15):** the **Well (idx 4)** is TOP row — NOT counted by Wage; the
implementation is correct as-is. This top/bottom classification is now pinned (Well = top) for the
≥1 other card expected to reuse it.

### A6. `schedule_animals` helper + Acorns Basket
**Cards unblocked:** B84 Acorns Basket (and the boar half of B41 Hauberg with A3).

**Blocker.** No `schedule_animals` helper (only `schedule_resources` for `Resources` and
`schedule_effect` for effect ids). The accommodation path itself is **sound** (red-teamed this session).

**Proposed build.** Add `schedule_animals(state, idx, rounds, Animals)` to `cards/schedules.py`,
mirroring `schedule_resources` but writing `FutureReward(animals=…)` additively. Acorns Basket's
`on_play` then schedules 1 boar onto its target rounds.
**RESOLVED (2026-06-30, user ruling recorded in `acorns_basket.py`):** the 2 round spaces are the
NEXT 2 rounds (R+1, R+2). Built on `schedule_animals`; this item is done — kept for provenance.

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

### B5. Scheduled-goods provenance — B76 Ceilings — BUILT 2026-07-20
"On next renovate, remove the wood **this card** still has promised on round spaces." `future_resources`
is a flat additive tuple with no per-card provenance, so a blind subtract is wrong when another scheduler
wrote the same slots. **Plan (executed as written, user-approved 2026-07-20):** a CardStore record of
which round slots Ceilings seeded; the mandatory `after_renovate` auto subtracts only its own
still-future wood and clears the record (the once-only latch). `ceilings.py` is the exemplar for any
future "take back promised goods" card.

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

### C3. Take-from-accumulation-without-placement — RESOLVED: APPROVED (user, 2026-07-20; ruling 70)
You flagged this exact mechanism as a blocker; on 2026-07-20 you approved it. Both members are
IMPLEMENTED (ruling 70): **A82 Work Certificate** (`after_action_space` play-variant trigger,
typeless ≥4 threshold) and **B81 Handcart** (`before_work` prep-window play-variant trigger,
6/5/4/4 thresholds keyed to the space family but satisfiable by ANY single type, any present
type takeable — ruled 2026-07-20, correcting the first-pass native-type analog). Kept for
provenance; no longer a blocker for future cards of this shape.

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
  *rescued* — its adjacency is computed inline, no API needed). (**Shelter A1 was rescued and BUILT
  2026-07-20** — its 1-cell-pasture restriction is `PendingBuildStables.allowed_cells`, computed
  inline from `farmyard.pastures`, no geometry subsystem needed.)
- **Return-home / end-of-round / after-work-phase hook (no such phase event):** Curator (A100),
  Asparagus Knife (A58), Lifting Machine (A70), Silage (A84), Ale-Benches, Credit (A54),
  Sculpture Course (B53), Informant (B117), Toolbox (B27, turn-end build detection).
- **New shared action space:** Chapel (A39), Forest Inn (B42), Final Scenario (B23, owner-private space).
- **Randomness inside `step` (determinism invariant):** Paper Knife (A3), Moonshine (B3).
- **Temporary / extra worker:** Telegram (A22), Bassinet (A25), Stock Protector (B94),
  Walking Boots (B22), Lazy Sowman (A94, also needs a "declined sub-action" event).
- **Hidden round-space identity (reveal order is in the Environment, not GameState):** Knapper (A124),
  Master Workman (A126), Silokeeper (B112), Sweep (B120), Telegram's round-space half.
- **Card-as-animal-holder / new capacity slot:** the two ANONYMOUS-slot shapes were BUILT 2026-07-20
  (user direction: fold holders into the solver's capacity list, keep them distinct wherever card
  effects distinguish them) — `register_animal_cap_slots` (a pasture-like single-type bin; **Stockyard
  B12 implemented**) and `register_flexible_slots` (any-type mixable slots; **Petting Zoo E11
  implemented**, ruled mixed-type 2026-07-20; Feedyard B11's slot shape is now buildable — its
  after-breeding food payout is the remaining piece). TYPED (per-species) slots were BUILT 2026-07-21
  (`register_typed_slots` — the Dolly's-Mother greedy strip generalized to a per-type triple, plus
  `animal_holder_card_ids()` for "able to hold animals" wording): **Wildlife Reserve C11, Cattle Farm
  C12, Mud Patch A11 (eviction flags at after_sow / after_play_minor for the unplanted-count drops),
  and Sheep Agent D86 implemented**. The signature question resolved same day (user-approved): the
  whole chain was widened to carry GameState (`slots_fn(state, player_state)`; the doctored-player
  argument stays explicit), `helpers.completed_feeding_phases(state)` provides the GLOBAL game-time
  count (rulings: one shared count; ticks on harvest feeding regardless of participation, even if
  every player skipped), and **Truffle Searcher B86 + Woolgrower A148 [4] are implemented** — the
  typed-holder family is CLOSED. Special Food (B34) separately needs an accommodation event.
- **Per-card goods stack (beyond a CardStore scalar):** Hayloft Barn (B21), Muddy Puddles (B83),
  Forest Plow (B17, return-wood-to-space + partial-take legality — two 2026-07-20 rulings for its
  eventual build: it is an AFTER-window trigger, so the deposit lands after the sweeping player's
  `taken` stamp; and its returned wood on the space DOES count toward Material Hub's threshold for
  the next visitor — no deposit provenance needed, the native-type filter is final), Forest Stone
  (B48 — also an alternative cost), Maintenance Premium (**note:** B55 was *rescued* — it needs
  only a scalar).
- **Alternative printed cost ("A OR B" for the card's own play):** Baseboards (A4), Barley Mill (A64),
  Forest Stone (B48). `MinorSpec.cost` is a single `Cost`; no OR-alternation, and you don't own the card
  while playing it (so the cost-formula registry can't help). A small `alt_costs` list on `MinorSpec` +
  an affordability/choice at play would unblock all three — a candidate Group-A item if you want it.
- **Legality / sub-action-menu changes:** Wooden Shed (A10), Forest School (**rescued** via the existing
  occupancy-override registry), Agrarian Fences (B26) (**Oven Site A27 was rescued and BUILT
  2026-07-20** — `PendingBuildMajor.allowed_majors` + `granted_by` on the build-major ctx + a
  grant-scoped cost formula; **Stone Company A23 likewise BUILT 2026-07-21** — the
  `CostCtx.min_spend` payment filter, ruling 72), Carpenter's Hammer (A14, per-action build-count
  discount), Chief Forester (A115, capped sow).
- **Misc one-offs:** Shaving Horse (A48, "after you obtain wood" event), Winnowing Fan (A61, state-dependent
  baking-rate conversion), Potato Ridger (A59, optional-at-harvest-field — the field hook is auto-only),
  Reclamation Plow (A17) / Wheel/Double-Turn plows, Grain Depot (B65, reads which resource paid),
  Moral Crusader (B106) / Shoreforester (B116) (pre-refill round-space read), Clutterer (B100, fragile
  static "accumulation-space text" card set + exact scoring rule), Wood Palisades (B30, alt fence piece +
  supply-cap bypass), Hawktower (B14), Carpenter's Bench (B15 — 🚫 **WONTFIX, user ruling 2026-07-21**:
  its "the taken wood (and only that)" payment-source restriction is the §8 goods-provenance cost gap,
  ruled not worth building for this card), Grassland Harrow was **rescued**.

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

---

## Placement legality as reachability — the design arc (2026-07-06)

**Problem catalog of record: `LEGALITY_HARD_CASES.md` (repo root)** — the ten mechanisms
that break state-read placement legality, worked multi-card interactions, and per-mechanism
card lists; **solution sketch (ON HOLD): `PLACEMENT_REACHABILITY_DESIGN.md` (repo root)**,
backed by three full-catalog censuses (`CENSUS_AT_ANY_TIME.md`, `CENSUS_REACTIVE_TRIGGERS.md`,
`CENSUS_COST_IMPOSITION.md`, all repo root). The problem: cards that grant goods on placement,
at-any-time cards, and reactive cards (Potter's Yard family) make placement legality a
*reachability* question ("could the player complete this action?"), which the per-space
predicates in `legality.py` cannot answer. The design doc holds the general architecture
(a closure-by-simulation oracle), the phase ladder, and the soundness contract, but the
user is designing the approach — it is a sketch, not a plan. Nothing is implemented at this stamp; the reveal-order card
cluster (Brook / Master Workman / Knapper / Sweep / Silokeeper / Outrider / Pioneer /
Legworker / Bean Counter / Wholesaler / Pig Stalker / Task Artisan / Water Worker) is Phase
1's scope and supersedes this file's "Hidden round-space identity" long-tail entry when it
lands.

**Dated rulings recorded here:**
- **Reed Seller (D159) is permanently out of scope** (user ruling 2026-07-06): an at-any-time
  conversion the *opponent* can preempt by paying — free timing plus an out-of-turn opponent
  decision would need machinery nothing else in the 31-card at-any-time family needs, for one
  4+-only card. Do not re-triage.
- **Minstrel (A151) deferred** (2026-07-06): out-of-turn action-space use at returning home —
  a new subsystem (its errata "use the effect of that action space" doesn't change this).
- **Sidekick (A171) deferred** (2026-07-06): placing two workers in the same turn.
- **Witches' Dance Floor (D25) is permanently out of scope** (user ruling 2026-07-09,
  `status: wontfix` in the data): simultaneously a sowable field, an occupation, and
  the Fireplace major with all its effects, playable only via a Minor-Improvement
  action — a multi-identity chimera touching the card-as-field, identity-counting, and
  major-ownership subsystems at once. Do not re-triage.
