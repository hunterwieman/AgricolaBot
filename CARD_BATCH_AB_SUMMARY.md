# Artifex/Bubulcus Card Batch — Final Outcome, Conclusions & Open Items (2026-06-30)

The durable record of the A/B card-implementation session. Companion to `CARD_BATCH_TRIAGE.md`
(per-card specs), `CARD_DEFERRED_PLANS.md` (deferred-group build plans), and `CARD_BATCH_HANDOFF.md`
(the repeatable process + machinery cheat-sheet, gitignored local-only). Written so the conclusions
survive context compaction.

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
