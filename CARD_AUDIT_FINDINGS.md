# Card Audit — Findings

A standing record of implementation errors (and candidate errors) found in the implemented
Agricola card set, for the project owner (the rules authority) to adjudicate and resolve. Nothing
here has been changed in code — these are surfaced candidates with evidence and a **proposed fix**.

## How these were found

Two complementary methods, run over the implemented catalog (564 cards):

1. **Random-play fuzzing** — 40,000 full card games driven with random legal moves, checking for
   crashes, stuck states (a non-terminal position with *zero* legal moves), and corrupt state
   (negative goods, duplicate cards). Finds *crashes and freezes*; each is reproducible from its seed.
2. **Static reasoning sweeps** — agents reading each card's verbatim text (plus official errata and
   clarifications) against its code, and separately walking each **option-restriction point** to find
   cards that break the premise it relies on. Every finding was checked by an independent skeptic;
   only survivors are listed. Finds *wrong-result and collision* bugs that never crash.

**Confidence labels.** CONFIRMED = traced with a concrete failing case. PLAUSIBLE = likely wrong, not
fully confirmed. SPECULATIVE / rules-call = depends on a rules interpretation the owner should settle.
**Fix labels.** [verified] = fix traced to the exact mechanism. [direction] = approach is right, exact
patch needs a code-check. [design] = needs a design decision. [rules] = awaits the owner's ruling.

## Coverage (complete)

- **Crash/freeze axis:** the whole catalog (495/498 dealable cards exercised in fuzzing), plus a
  targeted static hunt for the stranding-freeze pattern across all 198 candidate cards.
- **Fidelity (text-vs-code):** **the entire catalog** — 97 clarification cards, 134 HIGH-risk, 176
  MED, 157 LOW (every implemented card, at depth proportional to its mechanical risk).
- **Collision axis:** all restriction points swept twice, exhaustively — collisions are *concentrated*
  around one premise (food value across the harvest), not scattered.

The MED + LOW tiers (333 cards) came back nearly clean (2 real bugs, 3 speculative), confirming the
bugs concentrate in the complex cards.

---

## Summary table

| # | Card(s) | Severity | Verdict | One-line | Fix |
|---|---|---|---|---|---|
| 1 | Work Certificate, Sheep Inspector | high | CONFIRMED | Crashes the game (variant-less trigger, 3-arg apply) | **concrete** |
| 2 | Confidant | high | CONFIRMED | Raw-food gate blocks a valid conversion (and crashes) | **concrete** |
| 3 | Writing Desk | high | CONFIRMED | Freezes (bonus occupation eats the required one's food) | direction (deferred this session) |
| 4 | Flail | high | CONFIRMED | Freezes (bonus bake eats the required sow's grain) | direction |
| 5 | Teacher's Desk | high | CONFIRMED | Freezes (bonus cooks the grain the renovate needs, via Millwright) | **WONTFIX — excluded from deal** |
| 6 | Drill Harrow | high | CONFIRMED | Freezes (payment burns the required sow's seed) | **concrete** |
| 19 | Threshing Board | high | CONFIRMED | Freezes — Flail's twin | direction |
| 7 | Tutor | high | CONFIRMED | Silently scores one point too few | **concrete** |
| 8 | Cookery Lesson | medium | CONFIRMED | Scores its point on a discard (no cooking) | **concrete** |
| 9 | Harvest Festival Planning | medium | CONFIRMED | Swallows the card play it grants | **concrete** |
| 10 | Rocky Terrain | medium | CONFIRMED | Never triggers when a field *card* is played | **concrete** |
| 20 | Tumbrel + sow-income family | medium | CONFIRMED | "Unconditional Sow" income fires on restricted sows | **concrete** (narrower than first stated) |
| 11 | Furniture Maker + Working Gloves | medium | CONFIRMED | Hides the best way to pay | concrete — **needs your sign-off** |
| 12 | Small Animal Breeder | medium | CONFIRMED | Hides the convert-to-hit-threshold play | **concrete** |
| 24 | Case Builder | medium | CONFIRMED | ≥2-food bonus never offers the convert-to-reach-it play | **concrete** |
| 25 | Social Benefits | low | CONFIRMED | No way to discard surplus food to reach 0 for the reward | ✅ **FIXED (implemented)** |
| 13 | Farm Store | medium | CONFIRMED | Post-feeding food sink can't be funded | **concrete** |
| 14 | Value Assets, Winter Caretaker | low | CONFIRMED | Same as Farm Store, weaker payoff | **concrete** |
| 21 | Carrot Museum | low | CONFIRMED | "Vegetable field" count omits card-fields | **concrete** |
| 15 | Pig Breeder | low | CONFIRMED | Miscounts animal room (4-player, latent) | **concrete** |
| 16 | Sheep Agent | low | PLAUSIBLE | Excludes Livestock Feeder by the wrong test | concrete (scope is a **rules call**) |
| 22 | Corf | low | SPECULATIVE | Keys on the two quarries, not "3 stone from any space" | **concrete** |
| 23 | Pub Owner | low | ~~SPECULATIVE~~ **NOT A BUG** | On-play grain condition — ruled Reading A, code is correct | **resolved** |
| 17 | Beer Tap | low | doc-only | Stale comment invites re-introducing a removed bug | **concrete** (comment) |
| 18 | (conversion-closure) | low | doc-only | A safety test the docs claim exists doesn't | direction |

Five patterns: crashes (1–2), stranding freezes (3–6, 19), harvest food-value collisions (12–14),
"unconditional-action" income firing on restricted grants (20), and one-off wrong-result bugs.

**No rules ruling is needed to fix most of these** — only #11 (a design call), #23 and the
interpretation half of a few others wait on you. The verified/direction items are ordinary engine bugs.

---

## Pattern A — Crashes

### 1. Work Certificate / Sheep Inspector — variant-less trigger crashes `step`  ·  high  ·  CONFIRMED
Both cards offer a choice each time you use a space, generated malformed and then applied by code that
throws. 442 times in testing. Root: both register **both** a plain `after_action_space` trigger and a
play-variant trigger, and their apply is 3-argument `_apply(state, idx, variant)`; when a variant-less
fire reaches `_apply_fire_trigger` (`agricola/engine.py:585`) it calls that with 2 args → crash.
- **Proposed fix [concrete — easy, Family-inert]:** the leak is the **~25 non-atomic host after-phase
  enumerators** that call `_eligible_fire_triggers` *directly*, without `_expand_variant_triggers`
  (only the atomic-space host at `legality.py:3037` and ~7 other sites wrap it). Both cards hook the
  whole `SPACE_IDS` list, so using any non-atomic space emits a bare `FireTrigger(…, variant=None)`.
  Two changes: (1) **fold the expansion into `_eligible_fire_triggers`** itself (`legality.py:2966`) so
  every present/future call site expands automatically, and make `_expand_variant_triggers` **idempotent**
  (pass a fire through unchanged if `variant is not None`) so the ~8 sites that already wrap it don't
  double-expand; (2) a **permanent fail-loud guard** in `_apply_fire_trigger` (`engine.py:~562`):
  raise if a `variant is None` fire arrives for a `PLAY_VARIANT_TRIGGERS`-registered card. No new
  state; `PLAY_VARIANT_TRIGGERS` is empty in Family so it's byte-identical (no C++ port). Verified
  sound by an independent pass. Repro: bias seed 105.

### 2. Confidant — raw-food gate prohibits a valid conversion (crash is a symptom)  ·  high  ·  CONFIRMED
Confidant places N food on the next N round spaces (N∈{2,3,4}) and gets it **back** over those rounds,
plus a sow/build-fences action each. The card gates the N-food placement on **raw food on hand only**,
refusing to let the player cook grain/veg into the food — on a "backdoor conversion" rationale. That
rationale is wrong: since the food comes back, funding the placement by conversion is just a normal
grain→food conversion at a genuine point of need (you net the actions for the tempo cost of the grain),
with no exploit. So a player with grain but low food is denied a genuinely valuable — sometimes optimal
— play. **This is a faithfulness bug** (the "restrictions must never prohibit optimal behavior"
principle), not merely the crash it also produces. The crash: because affordability is checked against
raw food, the base Lessons cost's own liquidation raises food between commit and resume, flipping the
`place_0` fallback out of the variant set; the resume re-derives the variants and can't find the stored
`place_0` → `KeyError`. `agricola/cards/confidant.py` (`_variants`), `agricola/resolution.py:560`.
Note: the module cites a ruling for the raw-food gate, but the record shows the user only said "seems
straightforward" (a go-ahead to build) — the raw-food-vs-conversion choice was the implementer's, never
adjudicated.
- **Proposed fix [concrete plan]:** make the placement surcharge **liquidation-payable**, funded
  through `PendingFoodPayment` like any other food cost. Details:
  1. Offer `place_c` when `maxfood ≥ occupation_cost + c` (you pay both at play; the c placed food
     returns over the next c rounds). `maxfood` = raw food + everything convertible to food.
  2. Offer the waste `place_0` iff you can play the occupation but no real `place_c` is affordable —
     `occ_cost ≤ maxfood < occ_cost + smallest_c` — **not** only `maxfood == occ_cost` (that would make
     Confidant unplayable when you can afford the occupation but not the min-2 placement).
  3. The round-cap (never place on more spaces than remain; `place_1` in R13, `place_0` in R14) is
     already handled by `_placement_counts`.
  Placement: the affordability check needs the route's `occupation_cost` (Lessons ramp vs Scholar's
  flat 1 vs a free granted play), which `_variants(state, idx)` doesn't currently receive. Cleanest is
  to let the enumerator own the decision — it already knows the route cost and runs the base+surcharge
  committability check — with `_variants` just listing the round-legal counts + a marked waste fallback,
  and the rule "offer the waste variant only if no real placement survives the check." (Alternatively,
  thread the route cost into `variants_fn`.) This is faithful (conversion allowed at a genuine point of
  need) *and* dissolves the crash — the variant set is then computed the same, liquidation-aware way at
  commit and resume, so `place_0` no longer appears-then-vanishes. Repro: seed 23.

---

## Pattern B — Stranding freezes (a bonus action strands the required one)

**A card grants a bonus action *before* your required action, and paying for the bonus consumes the
resource the required action needed — reaching a position with zero legal moves.** Five confirmed
(3–6, 19). A dedicated hunt across 198 candidates found only Threshing Board new, so the pattern is
*contained*: it hits grants that spend **food or grain**; the **plow** grants are already guarded
correctly.

**The fix template exists in the plow grants** (`must_preserve_base` / `safe_plow_cells`): a
before-grant that spends a shared resource must guarantee the required action stays possible after the
spend, and **enforce** it at the commit menu — not merely check feasibility at eligibility.

> **Fix principle (load-bearing — a fix that over-restricts is still a bug).** The enforcement must
> **remove only the genuine dead-ends** (the payment/spend configs that leave the required action
> *impossible*) and **preserve every choice among the valid ones** — never collapse the decision to a
> single pre-picked option. Reserving *a specific* good (e.g. always keep grain) stops the freeze but
> silently deletes the legitimate "keep the veg, spend the grain" line — the same over-restriction the
> collision audit hunts, one level down. The correct shape is a *disjunctive* constraint ("keep ≥1
> sowable seed"), which the Pareto frontier already half-does: it offers both keep-grain and keep-veg
> (they're incomparable, so both survive) and only the all-seeds-burned config needs dropping.

### 6. Drill Harrow — a safe payment is checked but not enforced  ·  high  ·  CONFIRMED
"Before a Sow, pay 3 food to plow." Eligibility (`_seed_reserving_liquidatable`) *proves* the 3 food
can be raised while keeping a seed, but `_apply` pushes `PendingFoodPayment(..., reserved=Cost())` —
reserving nothing — so the player can still cook their last seed and strand the sow.
`agricola/cards/drill_harrow.py:81-88`.
- **Proposed fix [concrete plan]:** keep ≥1 sowable seed via a *disjunctive* frontier filter, not a
  fixed reservation (a fixed `reserved=grain` forces which crop you keep, deleting the "keep veg, spend
  grain" line). Three small steps:
  1. Add a card-only boolean `keep_sowable_seed: bool = False` to `PendingFoodPayment` (canonical
     default-skip + add to the frame's `__hash__`; Family never sets it, so no C++ change).
  2. Drill Harrow's `_apply` pushes `PendingFoodPayment(..., keep_sowable_seed=True)` (drop the empty
     `reserved=Cost()`).
  3. In `_enumerate_pending_food_payment` (`legality.py:3556`), when `top.keep_sowable_seed`, drop
     commits that leave zero seeds — i.e. keep only those with `player.grain − c.grain ≥ 1 or
     player.veg − c.veg ≥ 1`. Each surviving commit is offered, so the player keeps the choice of which
     seed to keep and what else to cook.
  Correctness: a seed-keeping config is never Pareto-dominated by a seed-burning one (it has strictly
  more grain or veg), so the filter never empties given the existing eligibility guard
  (`_seed_reserving_liquidatable`) — the non-empty `assert` in the enumerator still holds. The filter
  matches the eligibility's grain-OR-veg check exactly. (Static finding from the HIGH sweep, no seed.)

### 4. Flail  ·  19. Threshing Board — bonus bake eats the required sow's grain  ·  high  ·  CONFIRMED
Both grant a Bake Bread on Cultivation. When plowing is impossible, *sow* is the only mandatory option,
and the granted bake can drain the last grain (with veg=0) → freeze. `agricola/cards/flail.py`,
`agricola/cards/threshing_board.py:31`.
- **Proposed fix [direction — not yet independently developed; its fix-dev agent errored]:** cap the
  granted `PendingBakeBread` to **leave ≥1 sowable seed** — leave ≥1 grain *only when* the sow can't fall
  back on veg (`_can_plow` False and veg=0); no cap when veg≥1 (baking all grain is then a legitimate
  choice — you sow the veg) or plow is available. Removes only the dead-end and preserves the choice of
  how much to bake / which crop to sow. Mechanism mirrors Drill Harrow's shape but on the bake frame: a
  card-only grain-preservation cap on the granted `PendingBakeBread` that its enumerator honors
  (bake ≤ grain−1 in the strand case). **Still needs the concrete `PendingBakeBread` cap mechanism
  confirmed** (does the frame have a cap field, or is one added?). Repro: seed 7654 (Flail).

### 3. Writing Desk — bonus occupation eats the required one's food  ·  high  ·  CONFIRMED
The granted second occupation's food payment can cook the grain/veg that would have funded the
*mandatory* Lessons occupation, leaving it unaffordable. Its guard checks ≥2 playable occupations and
the bonus's own cost, not the required play's survival. `agricola/cards/writing_desk.py:75`.
- **Proposed fix [direction]:** constrain the granted play's food payment so the **mandatory Lessons
  play stays affordable afterward** — drop only the payment configs that leave it unpayable, and
  preserve the player's choice among the rest (which goods to cook for the bonus vs keep for the
  required play). Per the fix principle, *not* a fixed reservation of specific goods. Also strengthen
  eligibility to require the required play survives the grant's maximum spend, so the grant is never
  offered as a guaranteed strand. Repro: seed 2499.

### 5. Teacher's Desk — bonus occupation eats the grain the mandatory renovate needs  ·  high  ·  CONFIRMED
Same class as Writing Desk (a before-grant strands the mandatory action), confirmed by replay. It is a
**three-card interaction**: House Redevelopment's mandatory renovate is payable (reed=0) only because
**Millwright** substitutes 1 grain for the missing reed (payment `2 clay + 1 grain`) — so grain is
load-bearing for the renovate. **Teacher's Desk** fires enforce-first (before the renovate), grants an
occupation play, and its 1-food cost is raised by cooking that same grain → the renovate is no longer
payable → the `PendingHouseRedevelopment` has zero legal moves → freeze. The placement was correctly
legal (`_can_renovate` was genuinely True at placement); the bug is the strand, not the placement.
`agricola/cards/teachers_desk.py`. Repro: seed 1966.
- **Resolution [WONTFIX — done]:** the card is marked `"status": "wontfix"` in
  `revised_minor_improvements.json` and the deal pool (`play_web._card_pool` via
  `_wontfix_excluded_slugs`) now excludes it — so Teacher's Desk is **kept in the codebase but never
  dealt in any game**. No behavioral fix pursued (user decision). If it's ever re-enabled, the fix
  would be the Writing-Desk shape (constrain the grant's food payment so the mandatory renovate stays
  payable, preserving choice).

---

## Pattern C — Harvest food-value collisions

The engine narrows the harvest choice set on the premise that **leftover food after feeding is
worthless**, so it never offers a way to end up holding spare food. False for cards that make
post-feeding food valuable. **Fix philosophy: push the food logic to each card's own point of need,
not into the general frontier.**

### 13. Farm Store  ·  14. Value Assets, Winter Caretaker — post-feeding sinks can't be funded  ·  med/low  ·  CONFIRMED
These *spend* food after feeding, but the frontier deletes the "carry spare food out of feeding" option
and their windows expose no way to cook grain into food. `agricola/cards/farm_store.py:84`, etc.
- **Proposed fix [concrete — easy, verified sound]:** make each buy **liquidation-aware**, reusing
  Cattle Feeder's idiom *verbatim* (`agricola/cards/cattle_feeder.py:69-79`): gate eligibility on
  `_liquidatable_to`, and on fire push a raise-only `PendingFoodPayment` with a registered resume that
  debits the food and grants the goods. Confined to the three card modules — no engine change. Mechanics
  confirmed: pushing the payment from a harvest-window trigger no-ops through `_fire_subaction_before_auto`
  (as Cattle Feeder does); `triggers_resolved` is stamped before `apply_fn`, so once-per-window survives
  the detour; `resume_kind` carries the buy variant with no new frame state. The player cooks *at the
  buy* instead of carrying surplus food; safe from food-laundering (fires after feeding is resolved).

### 12. Small Animal Breeder — convert-to-hit-threshold is hidden  ·  medium  ·  CONFIRMED
It grants +1 food at round start if you hold ≥(round-number) food; cooking grain to cross that
threshold can be worth it but is never offered (feed frontier deletes over-convert configs and
short-circuits when the feeding requirement is met; the same deletion recurs in breeding).
`agricola/helpers.py:986` + the breeding frontier; card `agricola/cards/small_animal_breeder.py:60`.
- **Proposed fix [concrete — moderate, verified sound]:** keep the existing mandatory `before_round`
  income auto (a pure gain, no downside), and **add a second, OPTIONAL `before_round` trigger** cloning
  the Childless template (`cards/childless.py`). Being non-mandatory, the window machinery pushes a
  `PendingHarvestWindow(window_id="before_round")` frame that surfaces `FireTrigger` + `Proceed`
  (Proceed = decline); firing offers the minimal conversions that cross the threshold and preserves the
  choice of which goods to convert. Eligibility: below the threshold but able to cross it by converting.
  Keeps the general frontier untouched. **Rests on** the principle you've endorsed — a player may convert
  crops/animals→food at a genuine point of need (here, to cross the threshold); it's an interpretation,
  not printed text, but it matches the engine's own optionality-bundling rule.
  **Scope note:** this collision is *food-specific* (food is the only good convertible at any time), so
  the analog set is tiny — essentially just this card, with Case Builder (on-play "≥2 food" sub-case) a
  minor cousin (F24) and Social Benefits (D76, the *inverse*: reward for food==0 — F25, **FIXED this
  session**). No general "threshold reward" system is needed.

### 25. Social Benefits — no way to discard surplus food to reach 0 (FIXED)  ·  low  ·  CONFIRMED → **FIXED this session**
Social Benefits: *"immediately after the feeding phase, if you have no food left, get 1 wood and 1 clay."*
A player holding **surplus** food after feeding could, per the rules, discard all of it to reach 0 and
collect the reward (RULES.md:127 "you may discard goods … at any time" + RULES.md:114 "goods … includes
food"), but the engine surfaced no discard, so the play was silently lost. (A full-catalog sweep confirmed
no food-spend *card* creates any additional Social Benefits interaction — the generic discard was the only
gap.) `agricola/cards/social_benefits.py`.
- **Fix [IMPLEMENTED — verified]:** added an OPTIONAL `after_feeding` trigger (alongside the existing
  auto) offered only when `food > 0`, that discards all food to 0 and grants the same 1 wood + 1 clay; the
  window's Proceed is the decline. Mutually exclusive with the auto (auto fires iff food==0, trigger offered
  iff food>0). Mirrors the `shepherds_whistle.py` auto+trigger-on-one-window precedent. Card-only /
  Family-inert. Tests: 18 pass (5 new), C++ differential gates green. **Not committed.**

### 24. Case Builder — the ≥2-food bonus never offers the convert-to-reach-it play  ·  medium  ·  CONFIRMED
On play, Case Builder grants 1 of each of {food, grain, veg, reed, wood}, plus a bonus for each of those
goods you *already* hold ≥2 of. For **food** (the only good convertible at any time) this is the same
collision as Small Animal Breeder: a player with <2 food who could cook goods to reach ≥2 is never offered
that conversion, so the food bonus is silently lost. (grain/veg/reed/wood thresholds don't collide — you
can't convert to them.) `agricola/cards/case_builder.py`. **This is a correctness bug — the card isn't
implemented as printed — not an optional nicety.**
- **Proposed fix [concrete — moderate]:** a `register_play_minor_variant` route that optionally converts
  goods→food to reach ≥2 food *before* the on-play bonus resolves. **Label variants by the conversion, not
  the bonus:** offer a "raise to ≥2 food (cooking X)" variant *only* when below 2 food and able to reach
  it; when already ≥2, no such variant exists and the base play grants the bonus automatically — so the
  "sometimes-default, sometimes-paid" confusion never arises (the raise-variant simply doesn't exist in the
  auto case). Offer the non-dominated raise routes only (cooking a good Case Builder *also* checks —
  grain/veg — can drop that good's bonus, so those routes may be dominated; cooking an animal usually isn't).

---

## Pattern D — "Unconditional action" income on restricted grants

### 20. Tumbrel and the sow-income family — pay out on restricted sows  ·  medium  ·  CONFIRMED
"Each time after an *unconditional* Sow, get 1 food per stable." The "after sow" event carries no record
of the sow's kind, so a card printing "**unconditional** Sow" fires on card-granted **restricted** sows
(Apiary's 1-field sow, etc.), which by the project's definition of "unconditional Sow" shouldn't qualify.
`agricola/cards/tumbrel.py:52`, `agricola/pending.py`.
- **Scope correction (verifier catch):** this applies ONLY to the cards that literally print
  "unconditional Sow" — **`tumbrel`, `garden_hoe`, `seed_pellets`, `seaweed_fertilizer`, `drill_harrow`**
  (and `seaweed_fertilizer` already gates correctly — it's the template). The other four (`gritter`,
  `field_spade`, `mud_patch`, `wild_greens`) print plain "each time you sow" / "each action in which you
  sow", so they *correctly* fire on any sow — they must **not** be gated (doing so was the over-restriction
  the verifier rejected).
- **Proposed fix [concrete — easy]:** add a shared `is_unconditional_sow(state)` helper (top frame is a
  `PendingSow` with `max_fields==0 and not crops_only and required_crop is None`), and gate the
  `after_sow`/`before_sow` eligibility of only the "unconditional"-printing cards on it. (`seaweed_fertilizer`
  already does exactly this — copy its `_eligible`.) Check each named card for whether it already gates
  before adding.

---

## Pattern E — One-off wrong-result and lost-option bugs

### 7. Tutor — scores one point too few  ·  high  ·  CONFIRMED
Subtracts Tutor from the count twice; always short by 1 when any occupation follows it. Silent, and a
test enshrines the wrong value. `agricola/cards/tutor.py:45`.
- **Proposed fix [verified]:** change `_score` from `len(p.occupations) - 1 - snapshot` to
  `max(0, len(p.occupations) - snapshot)` (the snapshot already excludes Tutor and everything before
  it). Also correct the test at `tests/test_cards_cardstore_cards.py:105-115`.

### 8. Cookery Lesson — scores its point on a discard  ·  medium  ·  CONFIRMED
Awards its point when the player merely discards excess animals (no cooking, no improvement).
`agricola/resolution.py:1970` fires the "animal cooked" reaction on excess *count* > 0 without checking
food was produced.
- **Proposed fix [concrete — easy, verified sound]:** one-line — in `_execute_accommodate`
  (`resolution.py:~1969`) gate the `note_animal_cook` fire on the already-computed local `food` (> 0)
  rather than the excess-animal count, so a zero-rate discard doesn't count as a cook. Matches its own
  documented "a discard is not a cook" contract.

### 9. Harvest Festival Planning — swallows the card play it grants  ·  medium  ·  CONFIRMED
Its gate uses the narrower "playable minors" query and drops composite-only minors (e.g. Wooden Shed),
then grants nothing. `agricola/cards/harvest_festival_planning.py:110`.
- **Proposed fix [verified]:** use the composite-inclusive query (`composite_only_ok=True`) in the gate,
  matching the enumerator it then offers.

### 10. Rocky Terrain — never triggers on field cards  ·  medium  ·  CONFIRMED
"Each time you plow a field (tile or card), you can buy 1 stone for 1 food," clarified "playing field
cards counts as plowing a field." The code only fires on grid plows (`before_plow`), not on playing a
field-card minor. The clarification settles the interpretation directly (playing a field card *is*
plowing), so this is a fidelity fix, not a rules call. `agricola/cards/rocky_terrain.py:99`.
- **Proposed fix [concrete — easy; one verifier correction]:** additionally fire the (optional,
  liquidation-aware) stone-buy when a **field-card** is played — a new eligibility gated on
  `played_card_id ∈ CARD_FIELDS`, keeping the existing `before_plow` registration for grid plows.
  **Correction:** register on **both** `after_play_minor` *and* `after_play_occupation` — the field-cards
  include two *occupations* (`field_caretaker`, `patch_caregiver`), which a play-minor-only hook would
  silently miss (the verifier's catch). Confined to `rocky_terrain.py`.

### 11. Furniture Maker + a food-substitution card — the payment prune drops a non-dominated payment  ·  medium  ·  CONFIRMED
The fault is `pareto_min_over_goods` (`agricola/cost.py:107`) itself: it prunes payments by dominance over
the goods spent, but **Furniture Maker rewards +1 wood per *food paid*** (`furniture_maker.py`), so paying
more food can be strictly better — invisible to a goods-only prune. Worked example (user's): FM + Working
Gloves + Forest School, 2-food occupation cost. Ways to pay: **A** = 1 wood + 1 food (Forest School swaps
1 food), **B** = 2 wood (Forest School swaps 2), **C** = 1 wood + 0 food (Working Gloves' bulk 2-food→1-wood
swap). Over goods, C dominates A and B → only C is offered. But with FM, A pays 1 food → +1 wood, so A's
*net* is just "1 food" — incomparable to C's "1 wood" and B's "2 wood". So A is genuinely non-dominated,
yet pruned and unreachable. (Note: Forest School emits every partial; it's the *prune*, not Working Gloves'
max-only shortcut, that deletes A — so the fix must be at the prune.) `agricola/cost.py:107`,
`agricola/cards/furniture_maker.py`, `agricola/cards/{forest_school,working_gloves}.py`.
- **Proposed fix [concrete exists — moderate, but NEEDS YOUR SIGN-OFF]:** a ~40-line reward-aware
  payment prune: add a `PAYMENT_REWARD` registry (`cost_mods.py`) that Furniture Maker registers into
  (`Resources(wood=payment.food)`, ownership-gated), have Working Gloves emit *all* substitution amounts
  when such a reward card is owned, and add a `pareto_min_over_net` that dominates over *goods − reward*
  instead of goods alone (`cost.py`). An independent pass judged it sound and non-over-restrictive. **But
  it (a) touches the general payment optimizer and (b) reverses a dated ruling that Working Gloves should
  "always emit only the maximum replacement."** So it's not hard to *build* — it's a **decision for you**:
  accept the small action-set widening + the ruling reversal, or leave this as a known, narrow lost-option.
- **Scope (full-catalog sweep, verified + user corrections):** Furniture Maker is the **only** card of
  concern. The only substitution cards it combines with are Forest School + Working Gloves (the only two
  `register_conversion("play_occupation")`). Two candidates the sweep raised are **not** issues: **Royal
  Wood** is already `wontfix` (banned, never dealt); **Contraband** (E54) is a *separate* optional
  pay-to-get-food transaction available regardless of how the base cost is paid, so it never routes through
  the prune.
- **To investigate later (user flag):** **Mayor Candidate** (E124, unimplemented) — *"…1 negative point
  for each wood and each stone in your supply. You can no longer discard wood or stone."* Because you can't
  discard wood/stone and they cost end-game points, an owner may prefer to **over-spend** wood/stone on a
  cost — an *inverse* payment-composition case (spend-more is better) that the goods-prune ("spend less is
  always better") would drop. Not litigated now; revisit when Mayor Candidate is implemented.

### 21. Carrot Museum — "vegetable field" omits card-fields  ·  low  ·  CONFIRMED
Counts only board fields, unlike its siblings Garden Hoe / Gritter (which include card-fields for the
identical phrase). `agricola/cards/carrot_museum.py:56-65`.
- **Proposed fix [verified]:** add `crop_card_field_count(player, "veg")` to `_veg_field_count`, exactly
  as Garden Hoe / Gritter do.

### 15. Pig Breeder — miscounts animal room (4-player, latent)  ·  low  ·  CONFIRMED
Its round-12 boar-breed "room" check uses raw `extract_slots` instead of the ownership-aware helper, so
it ignores typed-slot holders (Cattle Farm, Dolly's Mother, …). 4-player-only card, latent today.
`agricola/cards/pig_breeder.py:99-106`.
- **Proposed fix [verified]:** compute the "room" check through `breeding_frontier` / `accommodates`
  (which apply the typed-slot strip) rather than raw `extract_slots` + `can_accommodate`.

### 16. Sheep Agent — excludes Livestock Feeder by the wrong test  ·  low  ·  PLAUSIBLE
Decides "is this an animal-holder?" by which capacity registry the card used, wrongly excluding
Livestock Feeder (whose animals sit on grain, not the card). `agricola/cards/sheep_agent.py`.
- **Proposed fix [concrete — easy; scope RULED]:** replace the registry-inference predicate with an
  explicit **`ON_CARD_ANIMAL_HOLDERS`** allowlist (`register_on_card_holder(card_id)` in `capacity_mods.py`)
  that each genuine on-card holder registers into, so holder-ness is declared by the real semantic.
  **User ruling:** a card counts as a holder ONLY if its text literally says *"this card can hold
  [animals]"* (Truffle Searcher: *"This card can hold a number of wild boar…"*). Grain-based (Livestock
  Feeder), field-tile-based (Mud Patch), and house-based (Animal Tamer) holders do **NOT** count — so
  Sheep Agent grants each of them a slot. Build the allowlist from the literal "this card holds animals"
  cards; the stale docstring in `sheep_agent.py` that implies otherwise should be corrected.

### 22. Corf — keys on the quarry spaces, not the stone taken  ·  low  ·  SPECULATIVE
Hard-codes the two quarry spaces rather than "≥3 stone from any accumulation space." Identical today; a
latent coincidence-narrowing. `agricola/cards/corf.py:39`.
- **Proposed fix [verified]:** key on `top.taken.stone >= 3` at an accumulation host (or
  `STONE_ACCUMULATION_SPACES`) instead of the hardcoded quarry frozenset.

### 23. Pub Owner — on-play grain condition (RESOLVED: code is correct)  ·  low  ·  NOT A BUG
Text: *"Immediately, when you play this card, **and** at the end of each work phase, **in which** the
'Forest', 'Clay Pit', and 'Reed Bank' accumulation spaces are all occupied, you get 1 grain."* The
question was what the "in which … all occupied" clause modifies. **Reading A** (code): it modifies only
"each work phase" → **1 grain unconditionally on play**, plus 1 grain at each work-phase-end where the
three spaces are occupied. **Reading B**: it modifies both → the on-play grain also requires the three
spaces occupied at play. **User ruling: Reading A is correct** — the code (`pub_owner.py:61`, on-play
grain unconditional) is right. No change. 4-player-only card.

---

## Doc / hygiene (no gameplay effect)

### 17. Beer Tap — stale docstring  ·  low
A comment names Beer Tap as a live payment-frontier converter, contradicting the ruling that keeps it
out. Code is correct. `agricola/cards/harvest_conversions.py:66`.
- **Proposed fix [verified]:** correct the comment so a future editor doesn't re-add the removed
  frontier entry.

### 18. Missing conversion-closure backstop test  ·  low
A docstring claims a test guarantees the payment-conversion logic equals its full closure; the test
doesn't exist, and a design-doc claim is falsified by Master Renovator. `agricola/cards/cost_mods.py:165`,
`design_docs/cards/COST_MODIFIER_DESIGN.md` §4.8.
- **Proposed fix [direction]:** add the closure-equality test the docstring references (or correct the
  docstring + design-doc to match reality).

---

## Reproducing the fuzz findings

- Harness: `scratchpad/fuzz_cards.py` (`<n_games> <start_seed> [bias]`); failures in
  `scratchpad/fuzz_failures_{uniform,bias}.jsonl`; traces `scratchpad/fuzz_trace_*.pkl`; replay with
  `scratchpad/replay_dead.py <absolute_path_to_pkl>`. A seed reproduces a finding exactly.
