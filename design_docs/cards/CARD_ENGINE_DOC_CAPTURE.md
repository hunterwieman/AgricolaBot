# CARD_ENGINE_IMPLEMENTATION.md integration capture (2026-07-05)

> **Purpose.** The harvest-window arc (2026-07-03 → 05) added several permanent
> mechanics to the card engine that belong in `CARD_ENGINE_IMPLEMENTATION.md` (the
> as-built reference-of-record). The building session's context was too deep to edit
> that large doc directly, so this file captures WHAT to fold in and WHERE; a fresh
> session should integrate it with the codebase open, then delete this file (or mark
> it folded). The reasoning behind everything here is in `HARVEST_HANDOFF.md`; the
> dated rulings are in `CARD_DEFERRED_PLANS.md`; the harvest design detail is
> `design_docs/cards/HARVEST_WINDOWS_DESIGN.md` (§12 = as-built map). This capture is
> the doc-integration checklist, not a fourth copy of the design.

## New permanent machinery to document (by CARD_ENGINE_IMPLEMENTATION section family)

### 1. The harvest timing-window system (new major section; pointer to HARVEST_WINDOWS_DESIGN.md)
- The 15-id ladder in `agricola/cards/harvest_windows.py` (was 17 — rulings 18/19,
  2026-07-05, merged "immediately after each harvest" into `after_harvest` and
  "immediately after the feeding phase" into `after_feeding`: the same instants;
  ruling 19's ordering — Social Benefits before Farm Store — rides the standing
  autos-before-optional-triggers within-window convention, no extra machinery. The
  standing instruction, already added to CARD_AUTHORING_GUIDE.md §2: EVERY
  "immediately" in a card text gets its own user ruling — the equivalence does not
  generalize automatically); simple-window ids double as
  trigger/auto EVENT strings (`register(<window_id>, …)` / `register_auto`), plus
  `register_harvest_window_hook(card_id, window_id)` for the membership index.
  Registrable: every simple window, `"field_phase"` (during-window triggers + pre-take
  flat autos), `"feeding"` (choice-free INCOME autos only — fire at FEED entry before
  the payment decision). NOT registrable: `"breeding"`.
- `PendingHarvestWindow` (per-player simple-window choice host; once-per-window via
  `triggers_resolved`; Proceed declines/pops) and `PendingFieldPhase` (the FIELD
  during-window host: free-order triggers around the mandatory `CommitFieldTake`,
  which is the only path to Proceed; `take_fired`, frame-scoped `occasions` manifest).
- `GameState.harvest_cursor`: a VIRTUAL-walk index (the ladder with the FIELD band
  #3–#7 repeated per player, SP first — ruling 3; `walk_position` decodes; N-player
  generalizable). Card-only, hash-included, canonical default-skipped.
- The walk `engine._advance_harvest` + `_field_phase_step` (window autos → host the
  frame iff a live decision: an eligible "field_phase" trigger OR a choice-bearing
  take-modifier use → else inline take → post-take trigger RE-CHECK, hosting the frame
  take_fired=True when take income enabled a trigger mid-window).
- The once-per-harvest conversion-budget reset now happens at HARVEST ENTRY, not the
  take (skip- and anytime-conversion-proof).
- Family fast path: empty registries, no frames, cursor always None, canonical JSON
  byte-identical — the C++ gates never needed a re-port for this entire arc.

### 2. The take-occasion manifest (the payload-bearing seam §8 said didn't exist)
- `HarvestOccasion(source, entries)` / `HarvestEntry(source="cell:r,c", crop, amount,
  emptied)` in pending.py; ONE occasion per real field phase (ruling 11 — all
  during-phase harvesting folds into the take; there is no during-phase separate
  occasion).
- `resolution.field_take(state, idx, *, source="take", extra_takes=None)` — the shared
  bare take (grain precedence; combined amounts + NET emptied flags; asserts fold-ins
  never over-harvest). Bumper-Crop-style cards call it bare with their own source
  (ruling 4) + `resolution.emit_harvest_occasion` (append to a live during-frame's
  manifest if any + fire occasion autos).
- `register_harvest_occasion_auto(card_id, elig, apply)` — `(state, owner_idx,
  occasion)` signatures; fires wherever an occasion is emitted.
  `register_harvest_occasion_trigger` exists behind a LOUD GUARD (surfacing unbuilt;
  first members Potato Ridger / Food Merchant).
- **The counting/scoping doctrine** (document prominently — a real bug shipped from
  it): entries = FIELDS ("each grain field", "each harvested tile", "take the last X
  from a field" → ignore `amount`); units = sum of amounts ("for each grain/vegetable");
  thresholds sum units once per occasion. Scoping: "…field phase OF A/EACH HARVEST" →
  `state.phase == HARVEST_FIELD`; ruled take-only (Grain Sieve, Barley Mill, Lynchet)
  → `occasion.source == "take"`; unscoped harvest-verb reactors fire on any verb-sense
  harvest (ruling 12's lexicon: harvest-verb = via the field-phase effect wherever it
  runs, or literal "Harvest" wording; "remove" is wider; "obtain" wider still).

### 3. Take-modifiers (the §4b class, as built)
- `TAKE_MODIFIERS` / `register_take_modifier(card_id, fold_fn, variants_fn=None)`:
  auto fold-ins (Scythe Worker) vs choice-bearing (Stable Manure, Scythe) surfacing as
  `CommitFieldTake(modifiers=((card_id, variant), …))` variants; owning a usable
  choice-bearing modifier hosts the during-frame.
- **Claim-aware allocation** (the collision fix): fold signature
  `(state, idx, variant, claimed) -> extras | None`; chosen modifiers allocate in
  combo order (= registration order; RIGID before FLEXIBLE is load-bearing), autos
  last (graceful degradation); a None fold marks the COMBINATION infeasible and the
  enumerator drops it — every offered commit is executable. Both harvest-scoped
  members apply to real-harvest takes only (ruling 12).
- Future: Grain Thief needs a per-cell skip/REPLACE extension (+ its manifest-entry
  shape decided jointly with Lynchet's tile count).

### 4. Harvest skips
- `HARVEST_SKIP_CARDS` / `register_harvest_skip(card_id, fn)` — per-card predicates
  `(state, idx, window_id) -> bool` over ROUND-KEYED card_state latches (stale = inert,
  no clearing). Consulted per simple window, per FIELD-band step, and by the FEED/BREED
  entry points with the sentinel ids (a skipper gets no feeding/breeding frames — and
  no feeding income). Members: Lunchtime Beer (ruling 1: field+breeding phases WITH
  boundaries; still feeds; +1 food on the optional start-of-harvest choice), Layabout
  (ruling 14: TOTAL — all windows, feeding, breeding; follows the official
  implementation over the user's own preference).

### 5. Smaller permanent seams
- **Feeding income**: `register_auto("feeding", …)` fires in `_initiate_harvest_feed`
  per player SP-first before frames are pushed. Consumers: Dentist (two-window card:
  wood bank at start_of_harvest + per-wood payout here), Town Hall, Milking Place.
- **House-pet negation**: `capacity_mods.register_house_pet_negation(card_id)` —
  `house_pet_capacity` returns 0 for an owner, beating every raise (Milking Place's
  "not even via another card"; Animal Tamer overridden). Playing a negation card flags
  the accommodation barrier (`animals_need_accommodation`) to evict a housed animal
  through the standard keep-or-cook frame.
- **Derived stable supply with removals**: `cost_mods.register_stable_supply_removal
  (card_id, store_key)`; `helpers.stables_in_supply(player) = 4 − stables_built(fy) −
  removals`; `stables_built` split out for built-count consumers. Chosen over a stored
  PlayerState field to keep the Family shape/canonical/C++ untouched (the derived-not-
  stored default; the stored route documented as available if reads get hot).
  Consumer: Market Stall C54's play cost (card_id `market_stall_c54` — slug collision
  with B8; web-meta (slug, deck) alias + doc_gen IMPL_FIX True).
- **Wide-play on-play grants** (ruling 17, the Baker pattern): an optional on-play
  sub-action grant is offered as PLAY-VARIANTS (`PLAY_OCCUPATION_VARIANTS`, the Roof
  Ballaster mechanism) — never an after-play trigger (ordering not licensed). The
  granted frame is committed once the variant is chosen.
- **The A1 growth grant in production**: Autumn Mother (3-food cost through the
  food-payment resume seam, `register_food_payment_resume`) and Bed in the Grain Field
  (one-shot next-harvest by round arithmetic, decline consumes) — the first window
  triggers whose apply pushes primitive frames mid-harvest; the walk hosts them
  unchanged.
- **Shepherd's Whistle's frontier** (ruling 16 as amended): reduced capacity via a
  DOCTORED player (one standalone STABLE cell blanked → the standard helpers see
  "farm minus one unfenced stable"); the option frontier is over animals PLUS a
  received-vs-declined dimension ordered iff a sheep-conversion opportunity exists;
  food computed per option, never a dominance term. Document the generalizable
  pattern: a card that REPLACES a convertible good it induced you to spend breaks the
  food-exclusion premise (its proceeds are non-deferrable), and among same-rate
  subset options goods-only dominance is exact (food differences = deferred
  cook-value of the goods difference).

### 6. Retirements / supersessions to reflect
- The legacy `harvest_field` event, `PendingHarvestField`,
  `GameState.field_triggers_offered`, `should_host_harvest_field` /
  `HARVEST_FIELD_CARDS` / `register_harvest_field_hook` are DELETED (2026-07-05).
  `_resolve_harvest_field` remains as a compat alias into the walk. Any §-references
  to the "harvest-field hook" / "Category 6 hook" as live machinery are stale;
  rewrite them as history pointing at the window system.
- `HARVEST_CONVERSIONS` is now ONLY for printed feeding-phase conversions (the three
  formerly mis-timed cards left it; Furniture Carpenter's #16 anchor still pending).
- §8's "events carry no payload" boundary: amend — the harvest OCCASION registries are
  the deliberate payload-bearing exception (and the planned breeding-outcome event
  will be the second, same shape).

### 7. Census/status corrections encountered (fix wherever mirrored)
- Haydryer is "each harvest" (the round-14 annotation belonged to Transactor only).
- Ledger counts as of the last commit: 195 minors + 96 occupations implemented; the
  counts must always be re-asserted against `len(MINORS)`/`len(OCCUPATIONS)`.
- Defers with build plans on record: NONE remaining from this arc (Winnowing Fan,
  Market Stall C54, Baker, Milking Place, Shepherd's Whistle all landed on rulings);
  still-open work is listed in HARVEST_HANDOFF.md §12.
