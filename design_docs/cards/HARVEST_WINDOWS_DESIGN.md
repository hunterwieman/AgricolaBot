# Harvest Windows — Design

> **Status: STAGES 1–2 IMPLEMENTED (2026-07-03/04); stages 3–4 remain design.** Stage 1 (§9)
> landed in commit 1bfdcb5 (A1 in 44c584c): `agricola/cards/harvest_windows.py` (the ladder table,
> hosting index, `register_harvest_window_hook`, the skip-guard seam), `PendingHarvestWindow`,
> `GameState.harvest_cursor`, and `engine._advance_harvest` replacing the three harvest
> phase-cases. **Stage 2 (2026-07-04) rebuilt window #5 on the take-occasion manifest (§4)**:
> `HarvestOccasion`/`HarvestEntry` + the `PendingFieldPhase` during-window host (free-order
> triggers around the mandatory `CommitFieldTake`; `agricola/pending.py`), the shared bare
> `resolution.field_take` (Bumper Crop's ruling-4 entry point, `source`-tagged), the
> per-occasion registries (`register_harvest_occasion_auto` / `_trigger` in
> `harvest_windows.py`; trigger surfacing is a loud-guard seam until its first member), and
> **ruling 3 realized for the FIELD segment**: `harvest_cursor` now indexes a VIRTUAL walk
> (`walk_position` — the FIELD band #3–#7 repeated per player, SP's whole segment first).
> The once-per-harvest conversion-budget reset moved from the take to harvest entry (so
> phase-skippers and future anytime-conversions stay correct). The legacy `harvest_field`
> event + `PendingHarvestField` + `field_triggers_offered` survive as the per-player legacy
> stage inside `engine._field_phase_step` until the §7 migration retires them. Full suite
> green including the untouched C++ differential gates; coverage:
> `tests/test_field_phase_window.py` + `tests/test_harvest_windows.py`. Remaining ordering
> note: the FEED/BREED segments are still WINDOW-major (whole-segment-per-player there is
> deferred until a member card's ordering depends on it). **The §7 migration wave A landed
> 2026-07-04** (the three mis-timed cards re-timed, ~14 cards re-homed; fidelity-lint
> ALLOWLIST emptied). **The take-fold-in seam landed 2026-07-05 (ruling 11)**:
> `TAKE_MODIFIERS` / `register_take_modifier` in `harvest_windows.py`, per-cell
> `extra_takes` on `field_take`, choice-bearing modifiers as `CommitFieldTake(modifiers=…)`
> variants — Stable Manure reworked onto it (its wave-A free-order/own-occasion form
> superseded) and Scythe Worker migrated off the legacy hook as an auto fold-in; §4b is
> as-built. Legacy `harvest_field` seam still carries lynchet (user ruling pending) and
> wood_rake. Drafted with the user across the 2026-07-02/03
> sessions; the dated **user rulings** are recorded both here and in `CARD_DEFERRED_PLANS.md`
> ("Harvest-window redesign — user rulings"). Everything not marked as a ruling or as landed
> is a **proposal**. The user is the rules authority (CARD_AUTHORING_GUIDE.md §0.1 governs
> all implementation work).

## 0. The problem

Roughly 120 catalog cards fire at harvest-relative instants, but the engine gives them only
two homes: the field-phase hook (`harvest_field` autos + the `PendingHarvestField` choice
host) and the during-feed conversion registry (`HARVEST_CONVERSIONS`). Every other printed
instant — "at the start of each harvest," "after the field phase," "after the feeding
phase," "at the end of each harvest," breeding-phase effects — has either been shoehorned
into the wrong seam (the three mis-timed cards in `CARD_DEFERRED_PLANS.md`'s priority
section: Cube Cutter, Winter Caretaker, Elephantgrass Plant), archived (Farm Store), or
never attempted. A 2026-07-02/03 census (two full-catalog sweeps) mapped every harvest-
relative wording; this document turns that map into machinery: an explicit, ordered ladder
of **timing windows** threaded through the existing FIELD → FEED → BREED walk, each window a
hostable seam that cards register into.

Design constraints inherited from the project:

- **Rules fidelity is absolute** — each window exists because printed card text names its
  instant; windows are never merged on a "no observable difference" argument
  (CARD_AUTHORING_GUIDE.md §0.1).
- **The harvest is the engine's most delicate subsystem** (the feed frontier + deferred food
  payment) — the FEED windows *wrap* the existing feeding machinery; they do not reopen it.
- **C++ byte-identity is NOT a constraint here** (user, 2026-07-03): design the Python
  machinery on its merits; if a Family-shape change falls out, re-port to `cpp/` and keep the
  differential gates green by re-sync, not by design distortion.
- **[3+]/[4] cards are design inputs** (user directive 2026-07-03, now in CLAUDE.md Phase 3):
  they aren't dealt at 2 players, but the windows and seams must accommodate their shapes
  (Old Miser's feeding discount, Game Provider's pre-harvest field discard, Champion
  Breeder's newborn count, Midnight Fencer's start-of-last-harvest).

## 1. The window ladder

The harvest detours the round walk on rounds {4, 7, 9, 11, 13, 14}: WORK → RETURN_HOME →
**harvest** → PREPARATION. The ladder below is the complete ordered set of card-visible
instants, derived from RULES.md's four-slot timing model — between any two consecutive game
steps the slots are *(1) immediately before → (2) the step → (3) immediately after → (4)
after*, and "at the start of X" / "at the end of X" are the first / last moments *inside* X.
Adjacent-numbered windows are distinct, strictly ordered instants; within one window,
resolution order is player-chosen (§3).

| # | window id | printed wordings served | members found by the census (2p pool unless marked) |
|---|---|---|---|
| — | *(round end / returning home)* | "in the returning home phase", "at the end of each round" | the `PendingRoundEnd` family — separate design, `CARD_DEFERRED_PLANS.md`; fires **before** everything below |
| 1 | `immediately_before_harvest` | "immediately before each harvest" | Autumn Mother, Haydryer (each harvest — the earlier "round-14-gated" annotation was wrong for it, per its printed text), Transactor (round-14-gated); Game Provider [4] |
| 2 | `start_of_harvest` | "at the start of each harvest" | Raised Bed, Pipe Smoker, Animal Driver, Dentist (bank wood), Recluse, Bed in the Grain Field, **Lunchtime Beer's skip choice**, Bale of Straw (migrates here); Midnight Fencer [4], Wealthy Man [4]. *(Begging Student is BANNED — user ruling 2026-07-03.)* |
| 3 | `before_field_phase` | "before the field phase" | Straw Manure |
| 4 | `start_of_field_phase` | "at the start of the field phase" | Three-Field Rotation (migrates here) |
| 5 | `field_phase` (the during-window) | "in/during the field phase", "each time you harvest…" | §4 — the take + the four during-classes |
| 6 | `end_of_field_phase` | "at the end of the field phase" | Beer Table |
| 7 | `after_field_phase` | "after the field phase" | Winnowing Fan, Market Stall C54, Home Brewer (re-home RULED 2026-07-03 — §7) |
| 8 | `start_of_feeding` | "at the start of each feeding phase" | Baker (a granted bake), Cubbyhole |
| 9 | *(during feeding)* | "in the feeding phase" | the existing `HARVEST_CONVERSIONS` seam (unchanged) + feeding-income autos (Town Hall, Milking Place, Dentist's payout) + the feeding-cost fold (§5); Old Miser [4] |
| 10 | `immediately_after_feeding` | "immediately after the feeding phase" | Social Benefits |
| 11 | `after_feeding` | "after the feeding phase" | Farm Store (un-archive; the previously-designed `PendingHarvestFeed` after-phase collapses into this window) |
| 12 | `start_of_breeding` | "at the start of the breeding phase" | Shepherd's Whistle |
| 13 | *(during breeding)* | "in the breeding phase" | breeding-eligibility fold (Dolly's Mother) + in-phase triggers (Stone Importer, Nth-harvest-priced) |
| 14 | `breeding_outcome` (payload event) | "for each newborn…", "if you get newborns of ≥2 types" | Fodder Planter, Slurry Spreader C71; Champion Breeder [3+]; Dung Collector is **broader** (any newborn-animal gain — flag, §8) |
| 15 | `after_breeding` | "after the breeding phase" | Feedyard (also blocked on card-as-animal-holder) |
| 16 | `end_of_harvest` | "at the end of each harvest" | Ropemaker, Uncaring Parents, **Winter Caretaker (re-time target)** |
| 17 | `immediately_after_harvest` | "immediately after each harvest" | **Elephantgrass Plant (re-time target)** |
| 18 | `after_harvest` | "after each harvest" | Value Assets, Eternal Rye Cultivation |
| — | *(before the start of the next round)* | "before the start of each round" | the separate hook already designed in `CARD_DEFERRED_PLANS.md` (resource_analyzer); fires **after** #18, before income/reveal |

**Ordering derivation to confirm (open question #1).** Windows 16–18 order as end-of-harvest
(last moment *inside* the harvest) → immediately-after (slot 3) → after (slot 4), by the
four-slot model. A concrete pair shows the FEED analog is real: if Farm Store (`after_feeding`)
could spend your last food *before* Social Benefits (`immediately_after_feeding`) checked "if
you have no food left," the check flips — the slot model puts Social Benefits first. The
16→17→18 ordering has no constructible 2p pair yet; it is proposed on the model alone.

**Windows are data, not code.** The ladder is one ordered table (`HARVEST_WINDOWS` in
`agricola/cards/…`); adding a window a future card names is a table row, not a subsystem.

## 2. Frames and hosting

One generic frame serves every simple window:

- **`PendingHarvestWindow(window_id, player_idx, initiated_by_id, triggers_resolved)`** — a
  per-player choice host in the mold of `PendingPreparation` / the existing
  `PendingHarvestField` choice host. Its enumerator surfaces the window's eligible
  `FireTrigger`s (via the existing `_eligible_fire_triggers`, with the **window id as the
  event string** — the `PendingPreparation`/"start_of_round" literal-event precedent);
  `Proceed` declines/pops. Variant expansion works as everywhere else.
- **Autos need no frame.** Mandatory choice-free window effects fire mechanically inside the
  harvest walk (`apply_auto_effects(state, window_id, player)`), exactly like today's
  transient field-phase auto host. A frame is pushed for a player **only when they have ≥ 1
  eligible trigger** in that window (or, in the during-window, a pending mandatory take —
  §4). No registrations → no frame → the walk passes straight through: a cardless harvest is
  mechanically identical to today's.
- **Hosting guard**: `should_host_harvest_window(state, window_id, idx)` consults a
  registration-time index `HARVEST_WINDOW_CARDS[window_id] → {card ids}` (the
  `should_host_space` pattern; O(1) on the empty set).
- **Walk cursor.** The harvest walk needs to know which window it is in across `step`
  boundaries (several windows can each pause for agent decisions). The PREPARATION-style
  derivable discriminator does not scale to 18 windows, so: a card-only
  **`GameState.harvest_cursor: int | None = None`** (index into the ladder; `None` outside a
  harvest; default-skipped in `canonical.py`). This generalizes — and on migration replaces —
  the single-purpose `field_triggers_offered` bool.
- **Registration API**: reuse the one firing system. `register(window_id, card_id, elig,
  apply)` / `register_auto(window_id, …)` for the effects, plus
  `register_harvest_window_hook(card_id, window_id)` for the hosting index (the
  `register_harvest_field_hook` shape, generalized). Existing `harvest_field` registrations
  migrate to window #5's ids in the one-batch migration (§7).

## 3. Player ordering and the skip guards

- **Whole-phase-per-player, starting player first** *(user ruling 3, PROVISIONAL — the user
  dislikes the later-player advantage; revisit if distortive)*: within each of FIELD / FEED /
  BREED, the starting player walks **all** of their windows to completion, then the other
  player. The pre-FIELD windows (#1–2) and post-BREED windows (#16–18) likewise resolve
  SP-first per window. This matches the BGA convention and the existing per-player frame
  stacking (SP decides first).
- **A skipped phase has no boundaries** *(user ruling 1, definite)*: a player who skips the
  field phase (Lunchtime Beer, chosen in window #2) fires **none** of windows #3–#7 that
  harvest; a Lunchtime Beer player also skips breeding, so none of #12–#15.
- **A skipped harvest is cancelled WHOLE, outer boundaries included** *(ruling 14,
  2026-07-05 — supersedes the earlier contested ruling 2, and follows the official online
  implementation, which the user dislikes but rules to match)*: Layabout's whole-harvest
  skip (latched in CardStore at play, consumed at that harvest) suppresses EVERY
  harvest-relative effect for the skipping player — windows #1 through #18, the feeding
  frames, and the breeding frames. "After each harvest" cards (Value Assets) do NOT fire
  for the skipper; neither does `immediately_before_harvest` (#1) — the former open
  question #2, now resolved.
- Implementation: each per-player window push is guarded on that player's skip state for the
  current harvest. Lunchtime Beer's skip is a frame-scoped fact of this harvest — proposed
  home: a card-only per-harvest skip descriptor derived at window #2 and carried on the walk
  (CardStore latch + the cursor), not a new `PlayerState` field.
- **"Completed harvests / feeding phases" counters stay derived** (Facades Carving, Harvest
  House, Truffle Searcher): computable from `round_number` and the harvest-round set — no
  stored counter. *Flag:* if a per-player skip is ever ruled to make a feeding phase "not
  completed" for that player, the derivation needs the skip history; defer until such a card
  is built.

## 4. The during-window (#5): four classes and the take

The core novelty. Per the census + rulings, "during the field phase" content is **four
distinct classes**, not one:

**(a) Free-ordered independent triggers.** Cube Cutter's exchange and Treegardener's
optional buy — NON-harvesting during-phase effects, legal at any point in the window, before
or after the take, in any player-chosen order. Surfaced as ordinary `FireTrigger`s on the
during-frame; `triggers_resolved` gives once-per-phase. *(The additional-harvest cards —
Scythe E73, Stable Manure — were originally drafted into this class; ruling 11 (2026-07-05)
moved them to class (b): a full-catalog sweep found ALL during-phase harvesting is written
as a modifier of the one take event, never a separate sequenced harvest.)*

**(b) Take-modifiers — every during-phase harvesting card (ruling 11; AS BUILT
2026-07-05).** All field-phase harvesting is ONE simultaneous event: these cards' extras
are taken at the same time as the base take, inside the same occasion. The seam is the
`TAKE_MODIFIERS` registry (`register_take_modifier` in `harvest_windows.py`), whose
fold-fns contribute per-cell EXTRA units to `field_take`'s `extra_takes`; the manifest
entry for a benefited cell carries the combined `amount` and the NET `emptied` flag, so
every occasion consumer sees the extras as part of the take (Grain Sieve counts them —
the ruled Scythe-Worker/Stable-Manure equivalence). Two kinds:
- **Auto fold-ins** (`variants_fn=None`) — choice-free, applied to every real-harvest take
  for their owner, inline and hosted alike. *Scythe Worker* (its mandatory-max
  simplification stands: optional by text, modeled as take-the-maximum; if partial use
  ever matters it becomes a choice-bearing modifier — the old wide-trigger upgrade path is
  obsolete). *Scythe E73* joins here or as choice-bearing (it selects one field).
- **Choice-bearing modifiers** (`variants_fn` given) — the use is picked ON the take
  commit: `CommitFieldTake(modifiers=((card_id, variant), ...))`, one commit per legal
  combination, the bare `()` declining all (each is a "you can"). Owning one with a legal
  use is itself what hosts the during-frame. *Stable Manure* (which-fields count vectors);
  *Grain Thief*'s per-grain-field replacement joins this shape (a replacement rather than
  an extra — the seam grows a per-cell skip/replace map when it lands).
- The §4b one-way gate is now STRUCTURAL: the modifiers are parameters of the take commit
  itself, so committing any take implicitly declines every unchosen use — the event they
  would have modified has happened.
- Both implemented members are printed "of each harvest" → fold-ins apply only to a real
  harvest's take (ruling 12); a card-played field phase (Bumper Crop) runs `field_take`
  bare.

**(c) The take.** The window's own mandatory work: `CommitFieldTake` is the only path to
`Proceed` (the enumerator withholds the exit until `take_fired`), variant-expanded by the
choice-bearing modifiers above and bare otherwise. When the player has no during-window
decision at all (no eligible trigger, no choice-bearing modifier use), no frame exists and
the take runs mechanically inline — with the auto fold-ins applied — in the walk. **The
take is one event** *(user ruling 5)*: it harvests 1 crop from every planted field **and
card-field** (§6) simultaneously, plus every fold-in's extras; all its per-field/per-crop
consequences arrive at once.

**(d) Consequences, off the occasion manifest.** Every harvesting **occasion** appends one
record to a frame-scoped log on the during-frame. Under ruling 11 a real harvest's field
phase has exactly ONE occasion — the take, fold-ins included; separate occasions arise only
from out-of-phase harvesting events (a Bumper-Crop-played field phase via the bare
`field_take`, future literal "Harvest a crop" effects via `emit_harvest_occasion`):

```python
@dataclass(frozen=True)
class HarvestOccasion:          # one per harvesting event
    source: str                 # "take" | "card:<id>"
    entries: tuple[HarvestEntry, ...]

@dataclass(frozen=True)
class HarvestEntry:             # one per (source, crop) it harvested
    source: str                 # "cell:r,c" | "card:<id>"
    crop: str                   # grain | veg | wood | stone (card-fields)
    amount: int
    emptied: bool               # this harvest took the source's last crop
```

Consumers, with their granularity fixed by rulings 5–6 ("each time" counts occasions, "for
each X" counts units; both read the same manifest):

- **Per-occasion autos** — fire immediately after each occasion applies, reading that
  occasion: Slurry Spreader (per `emptied` grain/veg entry), Crack Weeder and Potato
  Harvester (per veg unit), Field Cultivator (per field-tile entry), the card-field
  self-triggers (Artichoke Field, Cherry Orchard / Melon Patch on `emptied`).
- **Per-occasion optional triggers** — surfaced after an occasion, gated on its manifest:
  Potato Ridger (its "can… / must with 4+" tiering; per its official clarification these
  fire on *card* harvest occasions too), Food Merchant (per grain unit, `emptied` discount),
  Melon Patch's granted plow.
- **Take-occasion autos (RULED 2026-07-03; amended by ruling 11, 2026-07-05)** — Grain
  Sieve and Barley Mill **fire once, with the take occasion**: "the crops are taken off of
  fields (the main field-phase effect) and their bonuses are based off of the specifics of
  what happened in that action" (user's words). They read the take occasion's manifest —
  which per ruling 11 (CARD_DEFERRED_PLANS.md) includes EVERY during-phase harvesting
  card's contribution: Scythe Worker's extras, **Stable Manure's extras** (the original
  ruling-9 contrast between those two is superseded — a 2026-07-05 full-catalog sweep
  established that ALL field-phase harvesting is one simultaneous event; there is no
  during-phase "separate occasion"), Scythe E73's widening, Grain Thief's replacements.
  They are NOT window-exit aggregates — the window has only the one harvesting occasion.
- **Flat state-readers** (Butter Churn, Loom, Milking Stool, Wood Harvester, Land Surveyor)
  don't read the manifest at all — they are plain window autos, order-insensitive.

This is the payload-bearing seam the firing system deliberately lacked
(CARD_ENGINE_IMPLEMENTATION.md §8 "events carry no payload"): a **new, harvest-scoped
registry pair** — `register_harvest_occasion_auto(card_id, fn)` /
`register_harvest_occasion_trigger(card_id, elig, apply)` with `(state, idx, occasion)`
signatures — rather than a payload retrofit of the global event system. The manifest lives on
the frame (frame-scoped state, per the state-placement rule) and dies with it.

**The take as a shared function.** The take's mechanics (iterate planted sources, remove one
crop each, move to supply, emit the occasion) are factored into one function used by (i) the
harvest walk and (ii) **Bumper Crop / Harvest Festival Planning**, which per user ruling 4
trigger *the field-phase effect, not the field phase*: they call the bare function — no
frame, no window autos, no phase-keyed cards — but per-occasion consequences that are not
phase-keyed (E70 Crop Rotation Field's "each time you **remove** the last…", which by its
wording fires on non-harvest removals too) still attach through the occasion it emits.

**Obtain-triggers (future).** The take also constitutes one *obtain* occasion per good type
(2 grain arriving at once = one *time* you obtained ≥1 grain, still 2 grain — ruling 6, the
Hayloft Barn clarification read correctly). No obtain-family card is implemented yet (the
census's one "implemented" member was a misclassification), so the general goods-arrival
chokepoint (the `grant_animals` pattern for resources) is **out of scope here**; this design
only commits the take to emitting its arrivals in one batched call per good so that seam can
attach later without reshaping the harvest.

## 5. The FEED and BREED windows

**FEED.** The deferred-payment feeding core is untouched. Around it:
- `start_of_feeding` (#8): Baker's granted bake (push `PendingBakeBread` — the standard
  granted-sub-action shape), Cubbyhole's payout.
- During feeding (#9): `HARVEST_CONVERSIONS` stays exactly as-is for cards printed "in the
  feeding phase" or bare "each harvest" conversions; feeding-*income* autos (Town Hall,
  Milking Place, Dentist) fire at the FEED entry, before the payment decision, so their food
  is payable. **New small seam — the feeding-cost fold**: `register_feeding_requirement(
  card_id, fn)`, folded when computing each player's food requirement (2/adult + 1/newborn
  base): Child's Toy (newborns cost 2), Old Miser [4] (−1 per person). Two members, one 2p —
  built when either lands, but the requirement computation should be chokepointed now.
- `immediately_after_feeding` (#10) then `after_feeding` (#11): the anti-food-laundering
  windows — proceeds cannot pay the feeding that already resolved. Window #11 **is** the
  previously-sketched "PendingHarvestFeed after-phase" (`CARD_DEFERRED_PLANS.md`), realized
  as a ladder window instead of a frame phase; un-archive Farm Store onto it.

**BREED.** The breeding frontier is untouched. Around it:
- `start_of_breeding` (#12): Shepherd's Whistle (its granted sheep routes through
  `grant_animals` and can then breed — that is why the instant exists).
- During breeding (#13): **the breeding-eligibility fold** — `register_breeding_eligibility(
  card_id, fn)` letting Dolly's Mother lower the sheep pair-threshold to 1 — consulted where
  `breeding_frontier` asks "which types can breed"; plus ordinary window triggers (Stone
  Importer's Nth-harvest-priced stone buy; note the "no eating/exchanging animals during
  breeding" rule is not violated — it buys with food).
- `breeding_outcome` (#14): a payload event carrying the newborns actually placed (known at
  the breed commit): Fodder Planter (a granted sow per newborn), Slurry Spreader C71 (sow on
  ≥2 types), Champion Breeder [3+] (VP by count). Same payload-registry shape as the harvest
  occasion (`(state, idx, outcome)`), not a global-event retrofit. *Flag:* Dung Collector's
  "each time you get 2 or more newborn animals" is **any-source** (markets grants included) —
  it needs a newborn-gain event wider than this window; defer it, don't stretch #14.
- `after_breeding` (#15): Feedyard (still separately blocked on card-as-animal-holder).

## 6. Card-fields feed the take

Eight 2p-pool cards are fields (Beanfield, Patch Caregiver, Lettuce Patch, Cherry Orchard
(wood), Melon Patch, Crop Rotation Field, Artichoke Field; **Witches' Dance Floor D25 is
BANNED — user ruling 2026-07-03 — never implement**). None is implemented; when they land:
- their crops live in CardStore (the card-as-goods-holder pattern),
- the shared take function iterates them alongside board fields (one crop each, same
  occasion),
- their `HarvestEntry.source = "card:<id>"` lets their self-triggers filter, and Cherry
  Orchard's wood rides the same `crop` field.
Card-field implementation is **not** part of this build — the design only fixes the manifest
shape so they slot in without reshaping it.

## 7. Migration of implemented cards (one batch)

Per the agreed sequencing: agree the ladder → build frames + manifest → migrate every
implemented harvest card in **one batch**, shrinking `tests/test_card_fidelity_lint.py`'s
ALLOWLIST as each mis-timed card is resolved (the priority section's contract). The list:

| Card | Today | Under this design |
|---|---|---|
| Cube Cutter ⚠️ | `HARVEST_CONVERSIONS` (mis-timed) | window #5 free-ordered trigger — **resolves mis-timed #1** |
| Winter Caretaker ⚠️ | `HARVEST_CONVERSIONS` (mis-timed) | window #16 trigger — **resolves mis-timed #2** |
| Elephantgrass Plant ⚠️ | `HARVEST_CONVERSIONS` (mis-timed) | window #17 trigger — **resolves mis-timed #3** |
| Farm Store (archived) | — | un-archive onto window #11 |
| Bale of Straw | `harvest_field` auto | window #2 auto (printed "start of each harvest") |
| Three-Field Rotation | `harvest_field` auto | window #4 auto |
| Butter Churn, Loom, Milking Stool, Wood Harvester | `harvest_field` autos | window #5 flat autos (unchanged semantics) |
| Lynchet | `harvest_field` auto | **verify at migration**: "each *harvested* field tile adjacent to your house" — confirm whether the current pre-take grid read matches the manifest-derived meaning (open question #4) |
| Scythe Worker | ~~`harvest_field` auto (pre-take mutation)~~ | **DONE 2026-07-05**: AUTO take fold-in (`register_take_modifier`, §4b / ruling 11) — its extras ride the take occasion's amounts; mandatory-max simplification stands (partial use would become a choice-bearing modifier) |
| Slurry Spreader A106 | `harvest_field` auto (registration-order grid read) | per-occasion auto on `emptied` entries — now correct under free order |
| Grain Sieve | `harvest_field` auto (pre-take read) | **take-occasion auto (ruling 9)** — fires once, off the take occasion's manifest (`occasion.source == "take"`); NOT a window-exit aggregate (that earlier idea is superseded — §4d) |
| Crack Weeder, Potato Harvester | `harvest_field` autos (pre-take reads) | per-occasion autos (per veg unit) |
| Stable Manure | ~~`PendingHarvestField` variant trigger~~ | **DONE 2026-07-05**: CHOICE-BEARING take-modifier (ruling 11 — the wave-A class-(a)/own-occasion form was superseded): its count-vector choice surfaces as `CommitFieldTake(modifiers=...)` variants; extras fold into the one take occasion (Grain Sieve counts them) |
| Beer Keg, Beer Tap, Studio, Schnapps Distiller, Schnapps Distillery | `HARVEST_CONVERSIONS` | **stay** — printed "in the feeding phase" is exactly that seam |
| Furniture Carpenter | `HARVEST_CONVERSIONS` (FEED-only) | the **#16 late anchor** (§10 — anchoring approved 2026-07-03; its "each harvest" is unanchored, and FEED-only strands breed-step food) |
| Home Brewer | `HARVEST_CONVERSIONS` (the audited equivalence reading) | **window #7 `after_field_phase` (RULED 2026-07-03)** |
| Dutch Windmill, Harvest House, Wood Rake | counters/space hooks | untouched (no window content) |

`register_harvest_field_hook` / the `harvest_field` event and `field_triggers_offered` are
retired in the same batch (superseded by windows #3–#5 and the cursor).

## 8. Open questions for the user

1. Confirm the post-harvest ordering **#16 end-of-harvest → #17 immediately-after → #18
   after** (derived from the four-slot model; no constructible 2p pair yet).
2. Does `immediately_before_harvest` (#1) fire for a player skipping the harvest via
   Layabout? (Unruled; nothing blocks on it.)
3. RESOLVED 2026-07-03 — Grain Sieve / Barley Mill fire ONCE, off the take occasion's
   specifics (§4d).
4. Lynchet's "harvested field tile" reading, at migration time (§7).
5. RESOLVED 2026-07-03 — Home Brewer re-homes to window #7 (§7).
6. Dung Collector's any-source newborn event (§5) — defer, or widen when the breed windows
   are built?

## 9. Build stages

Each stage lands green independently; card behavior changes only in stage 2's batch.

1. **The ladder + frames**: `HARVEST_WINDOWS`, `PendingHarvestWindow`, the cursor, hosting
   guards, registration seams, skip guards, player ordering. No card migrates; existing
   `harvest_field` / `HARVEST_CONVERSIONS` paths still run. Full suite green; a cardless
   harvest byte-identical.
2. **The take + manifest + the one-batch migration** (§7): the shared take function, the
   occasion registries, all implemented-card moves, the three mis-timed resolutions, the
   fidelity-lint ALLOWLIST shrink, retire `harvest_field`/`field_triggers_offered`.
   *Split in execution (2026-07-04): the MACHINERY half — take function, manifest,
   `PendingFieldPhase`, occasion registries, the per-player FIELD band — landed inline
   (§12 has the as-built map); the MIGRATION half is the delegated batch, and the legacy
   seam retires with it.*
3. **The FEED/BREED extras**: windows #8–#15 content seams (feeding-cost fold,
   breeding-eligibility fold, breeding-outcome payload), un-archive Farm Store.
4. **New-card authoring waves** over the opened windows (start-of-harvest backlog ~10 cards,
   feed-seam conversions ~10, per-occasion consequence cards, end-of-harvest set), each per
   the standard batch process.

## 10. Anytime-in-harvest optional triggers

*(Added 2026-07-03 after the ladder was drafted — the user raised the family; the census
below is a fresh sweep of both catalogs for every "each harvest / once each harvest"-worded
card with no phase anchor.)*

Some effects are usable **at any point during the harvest** rather than at one window:
worded bare *"Each harvest, you can …"*. Per the user (2026-07-03): their live span is
**from the start of the field phase** (not before it — windows #1–#4 are outside it)
through the harvest's later phases and the in-between windows. *Open: where the span ends —
window #16 (`end_of_harvest`, the last instant inside the harvest) is the natural reading;
#17–#18 are outside.*

**The complete member set:**

| Card | Kind | In → Out | Notes |
|---|---|---|---|
| **Joinery / Pottery / Basketmaker's Workshop** | built-in majors | 1 wood/clay/reed → 2/2/3 food | "once per harvest"; today surfaced only during FEED |
| Furniture Carpenter B101 [1+] ✅ | occ | 2 food → 1 VP | gated on any player owning Joinery; today at the FEED seam |
| Basket Carrier C105 [1+] | occ | 2 food → 1 wood + 1 reed + 1 grain | "once each harvest" |
| Stone Carver D108 [1+] | occ | 1 stone → 3 food | |
| Braid Maker E109 [1+] | occ | 1 reed → 2 food | (its build-extension clause is separate) |
| Paintbrush E39 | minor | 1 clay → 2 food **or** 1 VP | output choice — two variants |
| Cooking Hearth Extension C62 | minor | — | doubles each cooking improvement's conversion once per harvest — a **rate modifier**, not a standalone trigger (§ below) |
| Ebonist D155 [4] | occ | 1 wood → 1 food + 1 grain | mixed output |
| Veggie Lover E132 [3+] | occ | 1 grain + 1 veg → 6 food | |
| Stone Sculptor E153 [4] | occ | 1 stone → 1 VP + 1 food | mixed output |
| Omnifarmer E134 [3+] | occ | place 1 *harvested* crop / 1 newborn on card | inputs only exist after field / breed events |
| Lumber Virtuoso D129 [3+] | occ | ≥5 wood gate → a granted Build Stables / Build Wood Rooms action | an action grant, not a conversion |

**Two realizations considered; the user prefers (b) where it is loss-less:**

(a) **Free membership** — each card is an optional trigger in every window of its span.
Simple, obviously faithful, widens every window's action set.

(b) **Optionality-constrained surfacing** (the Foundations "preserving optionality"
principle): never surface the conversion standalone; bundle it into the decision points
where its proceeds are needed. The per-class analysis:

- **good → food converters** (Stone Carver, Braid Maker, Veggie Lover, Ebonist's food half,
  **the three built-in craft majors**): (b) works cleanly — surface them **inside the feed
  payment frontier and inside any in-harvest food raise** (a `PendingFoodPayment` opened by
  a harvest-window trigger's food cost, e.g. Cube Cutter's). Their output is food, food's
  only uses are food costs, and food is never better banked early. One machinery
  consequence: the food-raise helpers need an **instant-scoped converter-liveness** notion —
  concretely, the frontier builder receives the current instant (from the walk cursor / the
  decision context it is invoked at) and filters conversion *sources* by each source's live
  span; no new stored state, just an argument. A window-#1 food cost (Autumn Mother's
  3-food growth) may use the game-wide anytime cooking conversions but NOT these (not live
  before the field phase), while a window-#5 cost may use both.
- **food → pure-VP buys** (Furniture Carpenter; Paintbrush's VP variant; Stone Sculptor's
  VP half): a candidate single **late anchor** at window **#16**. The dominance argument:
  feeding is the only forced in-harvest food consumer, and firing early enough to induce
  begging is strictly worse than losing the buy (−2 food +1 VP +1 marker nets −2 vs 0) — so
  deferring to the last instant loses nothing. **Why #16 and not "right before the breeding
  phase"** (a candidate the user raised, noting animals cannot be cooked at any point
  *during* the breeding phase): food still arrives between that instant and #16 —
  (i) the engine's own breed-step bundled conversions (the rules' "eat animals immediately
  before breeding to make room", modeled inside the breed decision — the existing
  `breeding_food_gained`, present even cardless), (ii) Feedyard's per-empty-spot food at
  window #15, (iii) Sheep Keeper B154 [4] (2 food when the 7th sheep — possibly a newborn —
  arrives). The project precedent agrees: Winter Caretaker's audited delta was exactly
  "breed-phase food cannot reach an end-of-harvest effect." (Boar Spear's explicit "outside
  of the breeding phase" carve-out is corroborating evidence the rules treat breed-phase
  animal gains specially.) **The dominance argument itself still needs the user's
  ratification** (it is exactly the class of "I can't find a counterexample" reasoning §0.1
  warns about). **User 2026-07-03: the anchoring approach is approved.** Consequence:
  Furniture Carpenter migrates off its FEED-only seam onto the #16 anchor (its current
  surfacing is *restrictive* in the same corner as Winter Caretaker's audited delta — food
  gained at the breed step can't reach it); added to the §7 migration table.
- **goods-output / mixed-output buys** (Basket Carrier, Ebonist's grain half): (b) is
  **lossy by construction** — their outputs feed non-food sinks earlier than any food
  moment (Basket Carrier's grain → Beer Table's end-of-field-phase grain cost; Ebonist's
  grain → the after-field-phase grain exchanges). **User ruling 2026-07-03: these are
  offered THROUGHOUT the harvest span, not selectively** — an effect generating goods that
  can become food gets free window membership (option (a)); do not attempt a constrained
  surfacing for this class. **Stone
  Sculptor is Ebonist-shaped** (a building resource → food + X) **but escapes this class**:
  its X is a bonus point, which feeds nothing — so food-need moments (the food half) plus
  the #16 anchor (the VP half) cover it with no free membership.
- **action grants / placers** (Lumber Virtuoso, Omnifarmer): not conversions — (b) does not
  apply. Lumber Virtuoso's printed timing is **genuinely unclear** ("Each harvest in which
  you have at least 5 wood…" names no instant): the BoardGameArena implementation offers it
  only at the *beginning* of the harvest, while a free-span reading is strategically rich in
  both directions (field-phase wood income feeds its ≥5-wood gate; its stables raise
  breeding capacity and Beer Stall's empty-stable count). [3+], so nothing blocks — recorded
  here as an explicit **ask-the-user-at-build** timing question, per §0.1. Omnifarmer
  surfaces where its inputs exist (a per-occasion consequence trigger in the field phase; a
  breeding-outcome trigger).
- **Cooking Hearth Extension**: folds into `cooking_rates` wherever cooking conversions
  already surface during the harvest — the frontier enumerates each improvement's doubled
  variant, budgeted once per improvement per harvest in CardStore. No standalone trigger.

Status of this section's questions (2026-07-03): the **late-anchor approach is approved**
(with Furniture Carpenter's migration), and the **goods-generating buys are ruled free-span**
(see the class bullets above); the **class-1 constrained surfacing is the user's own stated
preference** (their original framing of option (b)) and is treated as the adopted direction.
**RESOLVED (user ruling 2026-07-03): the post-breeding timeline is breeding phase →
after-the-breeding-phase (#15, INSIDE the harvest — Feedyard's food is within the anytime
span and reachable by #16 buys; it dies with a skipped breeding per ruling 1) → the last
chance for in-harvest conversions (#16 — the anytime span ENDS here, resolving former open
question 7) → after the harvest (#17–#18, outside).** The stakes that decided it (funding /
skips / ordering) are preserved in the git history of this section; the (Feedyard, Winter
Caretaker) pair is the designated regression test of this boundary when the stages land.

One sharpening of §8's open question #1 discovered after it was written: the #17 → #18
ordering now HAS a constructible 2p pair — **Elephantgrass Plant (#17: 1 reed → 1 VP) vs
Value Assets (#18: buys incl. 2 food → 1 reed)**. Slot order (#17 first) means a reedless
player cannot buy a reed at #18 and feed it back to Elephantgrass; the reverse order would
allow it. Confirm the slot-model order is the intended rules reading.

## 11. Skeleton stress-cases — specific member effects that constrain skeleton choices

*(Added 2026-07-03 at the user's direction: the specific benefits cards provide genuinely
inform skeleton-level choices, so this inventory is kept next to the skeleton design rather
than deferred to each card's build stage. Grouped by the skeleton decision each informs.)*

**Player interleaving (§3's provisional ruling) — the stakes, made concrete.**
Beer Table (#6: pay 1 grain → 2 VP, *all other players get 1 food*) × Cube Cutter (#5:
1 wood + 1 food → 1 VP). The granularity decides whether the funding line exists and for
whom: **whole-phase-per-player (adopted)** → only the *non-starter's* Cube Cutter can spend
the starter's Beer Table food (asymmetric, later player privileged — the user's stated
objection); **window-by-window alternation** → neither can (both #5 windows close before any
#6 fires); **true any-order simultaneity** → both can. Related: Transactor (#1, "take ALL
building resources left on the entire game board") is winner-take-all under any fixed order
when both players own it — though fixed SP-first is also Agricola's general convention for
resolving simultaneous effects, which is a point *in favor* of the provisional ruling.
Furniture Carpenter's any-player Joinery read and Midnight Fencer's [4] take-from-opponents
are the other cross-player members; both are order-benign in 2p.

**The walk must host pushed primitive frames mid-harvest.** Granted sub-actions fire from
harvest windows: a sow (Fodder Planter per newborn, Slurry Spreader C71), a bake (Baker at
#8; Winnowing Fan's constrained bake at #7), builds (Lumber Virtuoso — rooms/stables whose
capacity then feeds breeding), family growth (Autumn Mother at #1, Bed in the Grain Field at
#2), an occupation play (Begging Student at #2). The pending-stack already supports frames
above a host; the skeleton requirement is that the **walk cursor tolerates arbitrary
sub-stacks** pausing inside any window.

**The feeding bill is computed at FEED time, never precomputed.** Window #1–#2 family
growths (Autumn Mother, Bed in the Grain Field) add a mouth to *this* harvest's feeding;
mid-harvest builds and grants shift capacity and goods. Nothing about the feed may be
derived before window #8. *(At-build rules question: is a window-#1/#2 growth's newborn fed
1 food — "born in the round just ended" — or 2?)*

**Mid-harvest animal grants meet the accommodation barrier and breeding pairs.** Haydryer
(#1 cattle buy), Game Provider [4] (#1 boars), Animal Driver [3+] (#2), Feed Pellets
(during FEED: veg → an animal of a type you have), Shepherd's Whistle (#12 sheep) — each
routes through `grant_animals`, so the barrier must reconcile at decision boundaries
*inside* the harvest walk; and each can create a breeding pair before #13, so breeding
eligibility is read live at the breed step, never earlier.

**Registration liveness inside one harvest (MOOT for now).** The only card that plays a
card mid-harvest — Begging Student, whose occupation played at #2 raised "does its
field-phase effect fire in the SAME harvest?" — is **BANNED (user ruling 2026-07-03)**. The
question sleeps unless another mid-harvest card-play member appears; the skeleton consults
registries live per window regardless, so no design change hangs on it.

**Fields mutate outside the field phase.** Craft Brewery pays 1 grain *from a field* during
FEED; Straw Manure adds vegetables at #3; Stone Clearing plants stone mid-round. No skeleton
change — but the manifest/aggregate readers of §4 must never assume field contents are
static outside window #5.

**Two-window card state.** Dentist banks wood at #2 and pays food per banked wood at #9 —
the CardStore-spanning pattern; the skeleton needs no feature, but tests should cover a
card reading state written by an earlier window of the same harvest.

## 12. Post-stage-2 handoff — START HERE (updated 2026-07-04)

*A self-contained "resume the build" brief for a fresh session. Read §1–§4 for the design;
this section is the as-built code map + the next step (the delegated migration batch). All
of §0–§11 is the authority; this only orients.*

### Where the build stands (committed, working tree clean)

- Stage 1 (**`1bfdcb5`**, A1 in **`44c584c`**): the ladder, `PendingHarvestWindow`,
  `harvest_cursor`, `_advance_harvest`, `PendingFamilyGrowth.place_on_space=False`.
- **Stage 2 (2026-07-04)**: window #5 rebuilt on the take-occasion manifest + ruling 3
  realized for the FIELD segment (details below).
- Full suite green (`~/miniconda3/bin/python -m pytest tests/ -n 4 --dist worksteal`); C++
  differential gates untouched (Family byte-identical: cursor always None, no window/field
  frames, canonical JSON unchanged; the per-player take order commutes).

### The as-built code map (grounded, post-stage-2)

- `agricola/cards/harvest_windows.py` — the ladder (`HARVEST_WINDOWS`, `WINDOW_INDEX`,
  `SENTINEL_WINDOWS`); the **virtual walk** (`FIELD_BAND_START/END/LEN`, `WALK_LENGTH`,
  `walk_position(cursor, sp) -> (window_idx, band_player|None)` — the FIELD band #3–#7
  repeated per player, SP first, ruling 3; N-player-generalizable); the hosting index
  (`register_harvest_window_hook` — "field_phase" IS registrable, feeding/breeding are not);
  the skip seam (`HARVEST_SKIP_CARDS` + `window_skipped`, loud-guarded); the **occasion
  registries** (`register_harvest_occasion_auto` / `register_harvest_occasion_trigger`,
  `(state, owner_idx, occasion)` signatures, `apply_harvest_occasion_autos` — occasion
  TRIGGERS are a loud-guard seam until the first member builds the surfacing); the
  **take-fold-in seam (ruling 11, 2026-07-05)**: `TAKE_MODIFIERS` /
  `register_take_modifier(card_id, fold_fn, variants_fn=None)` — auto fold-ins
  (`auto_take_fold_ins`; Scythe Worker) apply to every real-harvest take, choice-bearing
  modifiers (`choice_take_modifiers` / `fold_chosen_modifiers`; Stable Manure) surface as
  take-commit variants and force the during-frame.
- `agricola/pending.py` — `HarvestEntry(source, crop, amount, emptied)` /
  `HarvestOccasion(source, entries)` (source `"take"` or `"card:<id>"`);
  **`PendingFieldPhase`**(player_idx, take_fired, occasions, triggers_resolved) — the
  during-window host; `PendingHarvestWindow` (simple windows); legacy `PendingHarvestField`
  (the pre-migration `harvest_field` stage, per-player, at most one out at a time).
- `agricola/resolution.py` — **`field_take(state, idx, *, source="take",
  extra_takes=None)`** — the shared bare take (grain precedence, one singular occasion
  whose entries carry base+fold-in amounts and NET emptied flags; NO budget reset / autos /
  frames — ruling 4's Bumper-Crop entry point, which passes no fold-ins per ruling 12);
  `_execute_field_take` — the CommitFieldTake executor (fold the commit's chosen modifiers
  + the autos → take → record-first on the frame → occasion autos; no pop);
  `emit_harvest_occasion` — the seam for genuinely SEPARATE occasions (out-of-phase
  events only, post-ruling-11).
- `agricola/engine.py`:
  - `_advance_harvest` — walks the VIRTUAL ladder from `harvest_cursor` (or phase-derived);
    resets both players' `harvest_conversions_used` at the harvest's FRESH ENTRY (moved from
    the take — correct under future phase-skips and anytime-conversions); window-major
    `_process_simple_window` outside the band, per-player `_process_band_window` inside it;
    FEED/BREED sentinels unchanged.
  - `_field_phase_step(state, idx)` — one player's during-window: legacy `harvest_field`
    autos + "field_phase" window autos (pre-take, exactly once) → legacy trigger frame
    (pause "here", flag-discriminated) → `PendingFieldPhase` if a "field_phase" trigger is
    eligible (pause "next" — the frame owns the take) → else inline `field_take` + occasion
    autos.
  - `_resolve_harvest_field` — compat alias (assert HARVEST_FIELD + `_advance_harvest`);
    the legacy card tests drive it by this name.
- `agricola/legality.py` — `_enumerate_pending_field_phase`: free-order "field_phase"
  FireTriggers + the take-commit while unfired, VARIANT-EXPANDED over the choice-bearing
  modifiers (one `CommitFieldTake(modifiers=…)` per combination, bare `()` = decline all);
  `Proceed` only after the take (and no unfired mandatory trigger).
- `agricola/actions.py` — `CommitFieldTake(modifiers=())` — (card_id, variant) pairs;
  Grain Thief's replacement joins as another modifier kind when it lands.
- Coverage: `tests/test_field_phase_window.py` (manifest, free order, mandatory gate, band
  ordering, bare take) + `tests/test_harvest_windows.py` (stage 1) +
  `tests/test_card_stable_manure.py` (the legacy stage under the band).

### Next step — the remaining migrations + the new-card wave

- **Migration wave A LANDED 2026-07-04** (nine delegated agents + a driver fidelity fix):
  the three mis-timed cards (Cube Cutter→#5, Winter Caretaker→#16, Elephantgrass→#17),
  Home Brewer→#7, Bale of Straw→#2, Three-Field Rotation→#4, the four flat autos→#5,
  Grain Sieve→take-occasion auto, Crack Weeder / Potato Harvester / Slurry Spreader→
  field-phase-scoped occasion autos, Stable Manure→#5; ALLOWLIST emptied. **The fold-in
  rework LANDED 2026-07-05** (ruling 11): Stable Manure and Scythe Worker are
  take-modifiers.
- **The legacy `harvest_field` seam is RETIRED (2026-07-05)**. Lynchet migrated to a
  take-occasion per-TILE auto (the §8 #4 recommendation, made moot-safe by rulings
  11/12: extras can't create a tile edge case and a played field phase stays silent via
  the source gate; robust under Grain Thief's future replacement). Wood Rake — whose
  "before the final harvest" turned out to be another shoehorned timing, made LIVE by
  Straw Manure's #3 vegetable adds — migrated to window #1, round-14-gated. With the
  seam empty, its machinery was deleted: `PendingHarvestField`,
  `GameState.field_triggers_offered` (state shape unchanged on the canonical contract —
  the field was default-skipped), `_fire_harvest_field_autos`, the walk's legacy
  "resume-here" pause, `register_harvest_field_hook` / `HARVEST_FIELD_CARDS` /
  `should_host_harvest_field`, `_enumerate_pending_harvest_field`. `_resolve_harvest_field`
  survives as the compat alias (tests drive the walk by that name). Still held: Farm
  Store (un-archive →#11), Furniture Carpenter (→#16 anchor).
- **New-card wave B LANDED 2026-07-05** (eight delegated agents): Haydryer, Transactor,
  Raised Bed, Pipe Smoker, Recluse (start_of_round + start_of_harvest, per its two printed
  clauses), Straw Manure, Beer Table, Land Surveyor, Treegardener, Barley Mill, Autumn
  Mother + Bed in the Grain Field (the first A1 growth-grant consumers; Autumn Mother's
  3-food cost rides the food-payment resume seam). The wave's two defers LANDED
  2026-07-05 on user rulings: **Winnowing Fan** as a direct best-rate 1-grain
  conversion at #7 (in lieu of a hook-suppressed bake — outcome-identical, since the
  bake allocator is greedy-by-rate, and "not a Bake Bread action" holds structurally;
  a probe test proves no bake hook fires) and **Market Stall C54** (card_id
  `market_stall_c54`; B8 owns the name slug — web-meta alias + doc_gen IMPL_FIX
  updated) with its stable play cost expressed through a DERIVED supply:
  `stables_in_supply(player) = 4 − built − card-recorded removals`
  (`register_stable_supply_removal` in cost_mods; `helpers.stables_built` split out
  for built-count consumers) — no stored field, Family shape + C++ contract
  untouched. A wave-surfaced engine fix landed with it: the during-window frame is now
  RE-HOSTED post-take on the inline path when a per-occasion consequence enables a
  trigger mid-window (Crack Weeder income affording Cube Cutter's exchange).
  Still held: Dentist (stage-3 feeding-income seam), Lunchtime Beer (the skip-seam
  engine surgery), Scythe E73 / Grain Thief (the second modifier wave).
- Stale-premise note: §8 open question #2 (does window #1 fire for a Layabout skipper?)
  said "both member cards are unimplemented" — Haydryer and Transactor now ARE
  implemented; the question must be resolved before Layabout lands (nothing blocks
  today). Also open, from the A1 consumers: is a window-#1/#2 newborn fed 1 food or 2 at
  this harvest? The engine feeds 1 (the standard newborn rule) — ratify or overrule.

### Durable references

- **Design of record:** this file (§1 ladder, §2 frames, §3 ordering/skips, §4 during-window,
  §5 FEED/BREED, §6 card-fields, §7 migration, §8 open Qs, §10 anytime triggers, §11 stress).
- **Rulings quick list:** `CARD_DEFERRED_PLANS.md` "Harvest-window redesign — user rulings"
  (12 numbered + C++/4p notes). **Card census (verbatim, grouped by window):**
  `design_docs/cards/HARVEST_CARDS_REVIEW.md` (130 cards).
- **Open questions still needing the user:** §8 #1 (confirm the #17-before-#18 ordering
  derivation — both members are now implemented, and the ladder already encodes
  Elephantgrass #17 → Value Assets #18) and #6 (Dung Collector's any-source newborn
  event — defer, don't stretch #14); §10 (7) span end #16, (8) late-anchor ratification,
  (9) craft-major surfacing. RESOLVED: #2 (Layabout — ruling 14, whole-harvest
  cancellation incl. windows #1/#17/#18), #4 (Lynchet — migrated 2026-07-05). Newborn
  feeding for window-#1/#2 growths RATIFIED at 1 food (ruling 13).
