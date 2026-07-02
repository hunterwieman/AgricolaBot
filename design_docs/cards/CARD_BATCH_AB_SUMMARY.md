# Card-Implementation Batch — Final Outcome, Conclusions & Open Items (decks A–D; 2026-06-30)

The durable record of the card-implementation work so far. **Sections 1–N cover the Artifex/Bubulcus
(A/B) batch; the "Decks C & D" section at the end covers the non-A/B cards** (Corbarius C committed,
Dulcinaria D in progress). Companion to `CARD_BATCH_TRIAGE.md` (A/B per-card specs), `CARD_TRIAGE_CDE.md`
+ `card_triage_cde_specs.json` (C/D per-card specs), `CARD_DEFERRED_PLANS.md` (deferred-group build
plans), `scripts/card_batch/` (the reusable generators), and `CARD_BATCH_HANDOFF.md` (the repeatable
process + machinery cheat-sheet + authoritative live status, gitignored local-only). Written so the
conclusions survive context compaction.

**Headline totals (2026-06-30):** A/B 76 cards + deck C 59 cards committed → **218 cards registered**
(134 minors + 84 occupations), full suite **3028 passed**, C++ Family gates intact, on `main`, **not
pushed**. Deck D (48 cards) implementing.

## Landed & committed
- Commits: `439a0d2` feat(cards) [76 modules + 76 tests + __init__ + schedules + 2 fixes],
  `b994bc1` docs(cards). On `main`, **not pushed** (awaiting user confirmation).
- **76 cards implemented, tested, wired; full suite GREEN (2455 passed, C++ Family gates intact).**
  - 35 Artifex (A) + 32 Bubulcus (B) tier-1/2 (from the categorization hypotheses, reviewer-validated).
  - 8 rescued tier-3: nest_site, maintenance_premium, grassland_harrow, baking_sheet, pottery_yard,
    beer_keg, forest_school, forestry_studies.
  - 1 base: acorns_basket (1 boar onto the **next 2 rounds** R+1,R+2 — user-confirmed — via the new
    reusable `schedule_animals` helper in `cards/schedules.py`).
- Registry now holds **159 cards** (100 minors + 59 occupations).

## Two real bugs caught by the adversarial-verify stage (fixed + regression-tested)
1. **Catcher (A107):** the "Nth person placed this round" index was `people_total − people_home`,
   which over-counts by 1 after a same-round Wish-for-Children birth (a newborn bumps `people_total`
   but NOT `people_home`). Fixed to `n_placed = (people_total − newborns) − people_home`. Added two
   coverage tests (the prior tests set people counts directly and never exercised a newborn).
2. **Hand Truck (B67):** it registered only the `before_bake_bread` auto, so `_can_bake_bread`
   (grain ≥ 1) gated the action away at 0 grain — defeating the card's whole point (take a Bake Bread
   action at 0 grain to harvest its grain, then bake). Fixed by adding a `register_bake_bread_extension`
   (owns Hand Truck + a baker + ≥1 person on an accumulation space), the Potter Ceramics pattern. Added
   two legality-gate coverage tests (the prior tests force-stepped `ChooseSubAction(bake_bread)`, which
   bypasses `legal_actions`, masking the gap).
- The other 5 verify flags were "card not in __init__.py" — **by design** (agents were told not to
  touch __init__; I wire it centrally). All resolved by the central wiring step.

## Interpretation defaults I chose (USER: confirm or override — each is a one-line change)
- **A103 Portmonger → BANDED**, not cumulative: take exactly 1 food → 1 veg; 2 → 1 grain; 3+ → 1 reed
  (one good by band). Rationale: the codebase's own slash-tier precedent (Loom, Gift Basket, Milking
  Parlor) is all single-tier; the open "3+" band implies one top reward. The triage said cumulative; I
  corrected it.
- **B101 Furniture Carpenter → Joinery ONLY (major idx 7)** for "Joinery or an upgrade thereof":
  this engine's 10 majors have no Joinery upgrade, so "an upgrade thereof" maps to nothing reachable.
  Implemented via `HarvestConversionSpec.side_effect_fn` (food→VP — verified a real, designed mechanism;
  docstring names "Stone Sculptor +1 point per harvest").
- **Grassland Harrow (B18):** the round offset = building-resources-in-supply is counted AFTER the
  2-wood play cost is debited (the engine debits a minor's cost before its on_play). Defensible reading
  ("the wood you spent is gone"); flag if the intended ruling counts before paying.

## Open USER questions (also in CARD_DEFERRED_PLANS.md)
- **Bottom-row majors (B7 Wage):** proposed bottom = {Clay Oven 5, Stone Oven 6, Joinery 7, Pottery 8,
  Basketmaker 9}, top = {Fireplaces 0/1, Cooking Hearths 2/3, Well 4}. Unsure: is the **Well (4)** top or
  bottom? (Reused by ≥1 other deferred card.) — card itself DEFERRED pending this.
- **B5 Store of Experience:** passing/traveling minor or kept? (`passing_left` data is unreliable; text
  silent.) — DEFERRED pending this; otherwise ~15 lines.
- **A21 Family Friend Home:** "more rooms than people" measured before or after the just-built rooms? Does
  its +1 food couple to firing the growth? (In the family-growth-no-placement group.)
- **meeting_place over-count:** Wood Pile (B4) and Hand Truck (B67) count the owner's workers over
  `ACCUMULATION_SPACES`, which includes `meeting_place` — a become-starting-player space with NO goods
  accumulation in the card game. A worker there arguably should NOT count. Kept (consistent between the
  two) + flagged in code comments; likely wants exclusion. One-line fix if confirmed.

## Deferred set (build plans in CARD_DEFERRED_PLANS.md)
- **18 from the A/B triage**, clustered: card_granted_family_growth_no_placement (A93, B92, +A21 from
  rescue), off_turn_build_exclusion (A43, A74), minor_play_variant (B41, B9), optional_renovate (B1),
  bottom_row_major (B7), passing_minor_status (B5), passing_minor_after_event (B49),
  resource_threshold_latch (B35), build_payment_provenance (A41), consumed_space_snapshot (A95),
  scheduled_goods_provenance (B76), food_to_good_buy (B70, B82), at_any_time_conversion (B29),
  action_substitution (A97).
- **6 rescued-but-deferred:** Wheel Plow (multi-plow chain, unproven), Confidant (very complex),
  Forest Stone (alternative "2 wood OR 1 stone" cost — `MinorSpec.cost` can't express it; same blocker
  as Baseboards/Barley Mill), Family Friend Home (family-growth-no-placement), Work Certificate
  (take-from-accumulation-without-a-worker — user-flagged blocker), Clutterer (fragile static
  "accumulation-space text" card set + unconfirmed scoring rule).
- **The long tail** (geometry, return-home/end-of-round hooks, new shared spaces, randomness, temp extra
  workers, hidden round-space identity, card-as-animal-holder, per-card goods stacks) stays deferred —
  each needs a real subsystem. A cheap win flagged: a small `alt_costs` list on `MinorSpec` would unblock
  Baseboards / Barley Mill / Forest Stone.

## Red-team result (you asked): scheduled-animal accommodation is SOUND
`engine._collect_future_rewards` collects `future_rewards.animals` at round start and accommodates via
the SAME `pareto_frontier`/`can_accommodate`/`extract_slots` machinery as the animal markets
(max-total-kept, decision-free, deterministic). Tested. Only diverges from tabletop in multi-animal
tight-capacity grants (no in-scope card). **IMMEDIATE animal grants still have no accommodation** —
those stay defer-and-ask.

## Remaining scope (next: triage all of C/D/E)
Per-deck unimplemented after this batch: **A 92, B 98, C 162, D 162, E 165** (decks A–E each total 168;
they interleave Base + the named expansion). C/D/E ≈ **489** is the next target (essentially untouched:
C 6 impl, D 6, E 3). The A/B "remaining" (190) = the deferred set above + cards never in the A/B
categorization; revisit after C/D/E.

## Process learnings (apply to C/D/E — full method in CARD_BATCH_HANDOFF.md)
- Workflow `args` global is unreliable — **inline the CARDS array** in the script.
- **No raw backticks** inside template-literal strings in the script (parse error); build multi-line
  strings with `[...].join('\n')`.
- Implement agents must **NOT touch `__init__.py`** (wire centrally) or any shared file.
- The verify stage reliably distinguishes wiring gaps (expected) from real logic bugs (Catcher, Hand
  Truck) — keep it; scrutinize every flag.
- An agent can produce correct files but fail its StructuredOutput return (Beer Keg) — check the disk,
  salvage rather than re-run.
- Resume a paused workflow with `Workflow({scriptPath, resumeFromRunId})` (cached completions).
- New cards that extend a registry break existing **exact-set** test assertions (e.g.
  `HARVEST_FIELD_CARDS == {...}`) — fix those to **subset** checks.
- For C/D/E there are NO categorization hypotheses — the triage agent classifies from the verbatim text
  alone (cheat-sheet in the handoff). Defer liberally; the from-scratch classification IS the tiering.

---

## Addendum — residual details, proposals & process notes (answering "anything else?")

### Per-card residual decisions / risks (beyond the headline interpretation defaults)
- **Catcher (A107) — newborn ruling (mine):** a newborn does NOT count as a "person you place"
  (you don't *place* a newborn; it's born) — encoded by `(people_total − newborns) − people_home`.
  The verify agent left this rules question open; this is my call. Confirm if you disagree.
- **Beer Keg (A62) — prefix-based once-per-harvest guard is slightly fragile:** the 3 variants
  (`beer_keg_1/2/3`) enforce once-per-harvest via `is_owned_fn` checking
  `not any(cid.startswith("beer_keg") for cid in harvest_conversions_used)`. Correct today, but a
  future `conversion_id` beginning "beer_keg…" would collide. If we add more multi-variant harvest
  conversions, switch to an explicit variant-group field instead of `startswith`.
- **Nest Site (A49) — couples to Reed Bank rate == 1:** eligibility uses
  `reed_bank.accumulated.reed >= 2` as the proxy for "1 reed placed on a *non-empty* Reed Bank"
  (post-refill = pre+1). Breaks if any card ever changes Reed Bank's accumulation rate. Fine now; note it.
- **Pottery Yard (B31) — VERIFIED correct + consistent:** "+2 iff ≥2 orthogonally-adjacent unused
  spaces" matches verbatim; "Pottery (or an Upgrade Thereof)" implemented as owning Pottery (idx 8)
  ONLY — the SAME "or an upgrade thereof → base major only" default I chose for B101 (Joinery idx 7).
  The two are consistent: if you rule "upgrade" includes the other workshops, BOTH change together.
- **Grassland Harrow (B18) — n==0 edge handled:** with 0 building resources left after the 2-wood
  cost, the field schedules onto the already-current round (a wasted but legal play). Handled, not forced.
- **Forest School (A28)** is the first card combining `occupancy_override` + `occupation_food_source`;
  sound, but watch if a later card stacks more onto Lessons.

### Where the residual risk actually is (verification honesty)
Of the 67 A/B cards I personally deep-read only ~6 (Beer Keg, Forest School, Catcher, Hand Truck,
Grassland Harrow, Pottery Yard) + the templates. The other ~61 I trusted: the agent's own passing
test + the adversarial-verify verdict (`correct` for ~60; 7 flagged = 5 wiring + 2 real bugs I fixed)
+ the green full suite. Adversarial-verify is good but not infallible, so residual risk concentrates
in the ~60 "verify-said-correct, not personally read" cards — especially any with non-trivial
before/after or harvest/trigger ordering. Cheap follow-up if you want more assurance: a second
adversarial sweep over just those, or spot-read the ordering-sensitive ones.

### PROPOSED shared-infra additions (prioritized) — build once, unblock many across ALL decks
The deferred cards cluster onto a few missing mechanisms, and **C/D/E will hit the SAME ones
repeatedly**. Building the small ones (with your approval) BEFORE/early in the C/D/E implement pass
unblocks far more than deferring each card individually — a strategic lever that should raise the
C/D/E yield substantially. Small → large:
1. **`place_on_space: bool = True` on `PendingFamilyGrowth`** (card-only, default-skip) → A93, B92,
   A21 + every card-granted family growth. ~15 lines.
2. **A "card-game accumulation spaces" set** = `ACCUMULATION_SPACES − {meeting_place}` → fixes Wood
   Pile / Hand Truck and any future "people/goods on an accumulation space" card. ~3 lines + the
   meeting_place ruling.
3. **`_is_on_turn_build(state)` helper** (no `PendingPreparation` on the stack) → off-turn-build
   exclusion (A43, A74) + reusable. ~5 lines.
4. **`alt_costs` (an OR-cost list) on `MinorSpec`** + the play-time choice → Baseboards, Barley Mill,
   Forest Stone + likely several C/D/E cards. ~20 lines.
5. **`PLAY_MINOR_VARIANTS` registry** (mirror `register_play_occupation_variant`) → B9, B41 + the
   whole "you decide what to start with" family. ~30 lines.
6. **`PendingGrantedRenovate`** choose-or-decline wrapper (mirror `PendingGrantedBuildFences`) → B1,
   Renovation Company, Established Person. ~20 lines.
Bigger design decisions (need your call first): a SURFACED harvest-field host (optional harvest
triggers — Potato Ridger etc.); a standalone optional buy-conversion frame (food→good buys / the
Grocer family — B70, B82); a return-home / end-of-round phase hook (the whole return-home cluster);
per-card goods-stack state (Hayloft Barn, Muddy Puddles, …).

### Process improvements for the C/D/E pass (folding the A/B learnings back in)
- **Tell the verify agents that a card's absence from `__init__.py` is EXPECTED** (central wiring) so
  they don't flag it — in A/B that was 5 of 7 flags, noise that nearly buried the 2 real bugs.
- **Agent self-tests have a structural blind spot:** they test what the agent BUILT, not what it
  SHOULD have built — both real bugs lived in paths the agent's own test never exercised (Catcher's
  newborn, Hand Truck's 0-grain). Keep the adversarial-verify + full-suite gate, and have verify
  explicitly ask "what real-game path does this test NOT cover?"
- **From-scratch C/D/E triage is less-vetted than A/B** (no hypotheses, and I cannot human-review 489
  specs the way I reviewed 85). So C/D/E implement+verify needs EXTRA scrutiny and even more
  defer-liberal triage; lean on the pipeline's self-protection (implementers defer if it doesn't fit).

### Calibration & deck composition
- A/B yield ≈ 78% of triaged tier-1/2 + rescue cards implemented (76 of ~97 attempted); ~3% real-bug
  rate post-verify (2/67). Expect a LOWER implement rate from-scratch on C/D/E.
- **Decks A–E each total 168 and INTERLEAVE Base (Revised) + the named expansion** (e.g. Acorns Basket
  is "Base (Revised) · deck B"). So C/D/E's 489 unimplemented includes Base cards — some will match
  already-built patterns (cost-modifiers, scoring, on-play goods). Not pure-expansion.

---

## Decks C & D (Corbarius / Dulcinaria) — outcome (the non-A/B cards)

### What landed (deck C: DONE + committed)
- **59 deck-C cards** — tier-1 `87bea91` (23), tier-2 `2e3a9de` (36). Full suite **3028 passed**.
- **2 deferred + archived** (to `archive/deferred_cards/`): **canvas_sack** (`1 Grain/1 Reed → 1 veg/4
  wood` — a minor play-variant) and **granary** (`3 Wood/3 Clay` — an alternative cost). Both are the
  "**a `/` in a card's COST or REWARD means OR**" pattern, which `MinorSpec.cost` / the (nonexistent)
  minor play-variant can't express → defer. The slim-schema "/"-cost guard **auto-deferred granary**;
  I caught canvas_sack on manual review (its agent skipped verify — see below).
- Notable deck-C cards/patterns: **Cowherd** grants a market animal correctly by **bumping the Cattle
  Market pending's `gained` count** (routes the extra cattle through accommodation — never `p.animals +=`).
  A cluster of **multi-variant harvest-conversion** cards (Beer Keg, Farm Store, Home Brewer, Winter
  Caretaker, Elephantgrass Plant, Studio) use N `HarvestConversionSpec` entries + a cross-variant
  once-per-harvest `startswith` guard + a CardStore VP/goods bank scored via `register_scoring`.
  **Skillful Renovator** reuses the Catcher `(people_total − newborns) − people_home` person-index idiom.
  **Straw-Thatched Roof** is a cost-modifier (zero out reed for renovate/build-room). **Stable** pushes a
  free `PendingBuildStables` on play. **Trellis** grants an optional Build-Fences on Pig Market.

### Deck D (IN PROGRESS — not yet integrated)
- 48 deck-D implement cards (from the *partial* D triage) are being implemented by workflow
  `wf_3942c631-fae`. When it lands: salvage any StructuredOutput-failures from disk, scrutinize verify
  flags + "/"-cost auto-defers, wire `__init__.py`, full suite, commit (see `CARD_BATCH_HANDOFF.md` §6).
  The deck-D implement card list = the entries with `deck=D, decision=implement` in
  `card_triage_cde_specs.json` (or regenerate via `scripts/card_batch/gen_impl.py … D all`).

### Process wins carried into C/D
- The **SLIM return schema** (4-field impl / 3-field verify) cut the StructuredOutput failure rate from
  ~29% (deck-C tier-1) to ~0 (deck-C tier-2). The **"/"-cost auto-defer guard** in the implement prompt
  works. A root **`conftest.py`** (`collect_ignore=["archive"]`) lets deferred-card files live in
  `archive/` without breaking pytest collection. The reusable **`scripts/card_batch/gen_impl.py`**
  generator emits a deck/tier implement workflow in one command.
- **Watch on the StructuredOutput-failures:** those agents WROTE correct files but couldn't return — they
  skip the adversarial-verify pass, so they must be salvaged from disk and manually scrutinized (that is
  exactly how canvas_sack's play-variant bug was caught — 7 deck-C tier-1 agents hit this).

### C/D interpretation calls / open questions (per-card detail in `CARD_TRIAGE_CDE.md` + the spec JSONs)
- "Pottery (or an Upgrade Thereof)" (Pottery Yard) implemented as Pottery-only — **consistent with the
  B101 Joinery-only default** (they move together if you rule "upgrade" includes the workshops).
- A few triage-flagged readings to confirm: Straw-Thatched Roof "3 Grain Fields" = ≥3 fields carrying
  grain; Stable "Immediately build 1 stable" treated as mandatory-on-play (consistent with the Mini
  Pasture ruling); corn_schnapps_distillery's "once per round, you can" modeled at the start_of_round
  host; winter_caretaker's food→veg buy surfaces in the FEED sub-phase (once-per-harvest enforced).

### C/D deferred clusters
- **147 defers so far** (deck C 101 + deck D 46), clustered in `CARD_TRIAGE_CDE.md`. Same blocker
  families as A/B (geometry, return-home/end-of-round hooks, new shared spaces, randomness, temp extra
  workers, hidden round-space identity, card-as-animal-holder, per-card goods stacks, "/"-cost /
  play-variant, immediate animal grants, at-any-time conversions) — to be consolidated into
  `CARD_DEFERRED_PLANS.md` alongside the A/B groups. The 6 proposed shared-infra additions (above)
  would unblock many of them across ALL decks at once.

### Remaining (and calibration)
- **~233 cards still UN-TRIAGED**: deck D-rest (~68) + all of deck E (165) — the C/D/E triage hit the
  **monthly spend limit** during deck D. Re-triage them (regenerate the triage workflow's CARDS;
  reference `scripts/card_batch/card-triage-cde.example.js`), then implement. Plus the A/B "remaining"
  (A 92, B 98 = the A/B deferred set + Base cards never triaged).
- **Deck-C yield:** 59 implemented of 61 implement-triaged (≈97% of the *implement* set), i.e. 59 of 162
  total deck-C unimplemented (~36% implement rate from-scratch) — the rest deferred. 0 real bugs found
  by verify on deck C (vs 2/67 on A/B), but **fewer C cards were personally deep-read by me** than A/B,
  so residual risk concentrates in the verify-passed-but-not-personally-read C cards (esp. the 7
  StructuredOutput-skipped tier-1 ones, of which canvas_sack was the one real bug).
