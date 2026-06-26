# CARD_IMPLEMENTATION_PLAN.md

**Status: implementation design doc for the *tractable* base-game card subset. Concrete build
plan + canonical code per category. The cross-cutting design decisions are settled (see "Decisions &
open sub-questions" at the end); one search-layer sub-question (`observe` hand-cardinality
bookkeeping) is deliberately left open for a later session.**

> **Implementation status (build order at the end):** **Build-order steps 1–4 are DONE** (the
> `feat(cards)` git history is the per-slice record). Steps 5–7 remain. Two notable deviations from the
> canonical code below, both decided during implementation: (a) the card Meeting Place **reuses the
> `meeting_place` slot** (mode-branched resolver), rather than a new `meeting_place_cards` SPACE_ID —
> the new id would ripple into the family NN encoder/policy dimensions; (b) **Basic Wish for Children
> was modeled as a proper parent frame mirroring House Redevelopment** (a `PendingFamilyGrowth`
> primitive then the optional minor), not the "growth-inline + minor-follow-up" sketch. Also:
> `PendingPlayMinor` carries **no `optional` field** — optionality lives at the parent frame's `Stop`,
> per ENGINE_IMPLEMENTATION.md §2 (no SkipTrigger). `CardStore` (II.7) is deferred until a card needs
> it. **Step 3 (the firing registries + scoped used-sets) is now DONE** (II.1 automatic-effect registry
> `register_auto`/`apply_auto_effects`/`AUTO_EFFECTS`; II.3 `used_this_turn`/`used_this_round`/`fired_once`
> + `engine._clear` + wiring; pure-additive, Family byte-identical, C++ gates green). The `mandatory`
> trigger flag (the third firing kind) is deferred to land with its phase-exit gate consumer in step 6.
>
> **Step 4a (the atomic-space action-space host) is DONE** — `PendingActionSpace` + `Proceed` +
> `should_host_space` indexes + `trigger_event` routing + the `_apply_fire_trigger` record-before-apply
> fix (so a granted-sub-action trigger's pushed pending isn't clobbered). Zero existing-frame changes,
> zero C++ changes (the host frame only ever appears in card games), Family byte-identical. **15 cards
> have landed** on the safe (no-structural-change) infra — Categories 1, 2, 3, 4-atomic, 10 — plus
> printed-VP scoring for kept minors:
> - **Cat 1 (scoring):** Stable Architect, Manger, Wool Blankets.
> - **Cat 2 (on-play):** Consultant, Priest, Market Stall, Clay Embankment, Young Animal Market.
> - **Cat 3 (auto income, atomic spaces):** Wood Cutter, Geologist, Corn Scoop, Stone Tongs, Pitchfork,
>   Loam Pit, Canoe.
> - **Cat 4 (granted sub-action, atomic spaces):** Assistant Tiller, Oven Firing Boy.
> - **Cat 10 (bounded conversion):** Mushroom Collector, Basket.
>
> **Step 4b — animal markets DONE.** The three animal-market frames were rewritten to the uniform
> non-atomic lifecycle (decided with the maintainer, choosing consistency over Family byte-identity):
> `CommitAccommodate` no longer auto-pops — it applies the accommodation, pivots the host frame to
> `phase="after"`, and fires `after_action_space`; the trailing `Stop` pops. The frames gained `phase` +
> a `space_id` property and dropped their per-frame `TRIGGER_EVENT` (routed via the bucket). **This is
> the first real C++ sync** — the three C++ market structs gained `phase`, the canonical serde + hash
> were updated, `CommitAccommodate` made non-auto-pop, and the market enumerator returns `[Stop]` in the
> after-phase; **all 136 C++ differential gates are green**. (Family-game markets now carry an extra,
> agent-auto-skipped `Stop` step — the conscious byte-identity departure.) **Cat 9 (Milk Jug) landed**:
> the first opponent-firing card, an any-player automatic effect on Cattle Market's after-phase.
> **Step 4b — multi-sub-action hosts DONE** (settled with the maintainer). The initial approach gave
> non-atomic space frames a `Stop`-gate trigger-surfacing model (`_after_action_space_fired` derived, no
> `phase` field). Cards landed under that approach: **Threshing Board** (Cat 4, after-trigger granting a
> bake on Farmland/Cultivation); **Firewood Collector** (Cat 3, after-auto wood) was landed here but
> subsequently **re-deferred** by the space-host refactor (§11.1 — its "end of that turn" semantics
> need a dedicated end-of-turn event that the firing migration does not add). This intermediate approach
> was then **fully superseded by the space-host refactor** (see below), which replaced the `Stop`-gate
> model with the four host mechanisms (Atomic / Commit-terminated / Delegating / Proceed-host), added
> `phase` + `triggers_resolved` to all the space-host parent frames, introduced `PendingSubActionSpace`
> folding Farmland/Fencing, and migrated after-auto firing out of `_apply_stop` to each host's
> work-complete boundary. Remaining non-atomic Cat 4/5: Moldboard Plow (needs CardStore), the
> build/renovate hooks (Cat 5).
>
> **Sub-action hook refactor DONE** (`SUBACTION_HOOK_REFACTOR.md`; mechanism only, no card modules).
> Every commit-terminated sub-action — `PendingSow`, `PendingBakeBread`, `PendingPlow`, `PendingRenovate`,
> `PendingBuildMajor`, `PendingFamilyGrowth`, `PendingPlayOccupation`, `PendingPlayMinor` — is now a
> uniform before/after host like `PendingActionSpace`/the markets: **`auto_pop=False`**, a `phase`
> (`"before"`/`"after"`) + `triggers_resolved`, and the commit **pivots the frame to its after-phase**
> (via the shared `_enter_after_phase` helper, which also fires `after_<id>` automatic effects at that
> flip — the after-window-open point); the trailing `Stop` pops. `PendingBuildMajor` dropped the
> now-redundant `build_chosen` (the after-gate keys on `phase`; the oven wrapper is pushed *after* the
> flip so the free bake pops back to an already-"after" host). The Family sub-action trace gained an
> agent-auto-skipped `Stop` per sub-action; the 5 Family-reachable frames (Sow/Bake/Plow/Renovate/
> BuildMajor) were C++-synced (`phase` field + flip + after-phase enumerator) — **all 136 differential
> gates green**. This **unblocks the Category-5 after-trigger grants** (Mining Hammer on `after_renovate`,
> Bread Paddle on `after_play_occupation`) and the after-auto build hooks. **Before-automatic effects now
> also fire at the sub-action push** (the initially-deferred §4d, lifted): a single central seam
> (`engine._fire_subaction_before_auto`, gated on `pending.SUBACTION_PENDING_IDS`) fires `before_<id>` autos
> when a leaf is pushed, called at the two push chokepoints (`_apply_choose_sub_action` + `_apply_fire_trigger`'s
> apply_fn) — so the sub-action layer now has the full before/after × auto/trigger suite. Lifecycle +
> hook coverage: `tests/test_subaction_hook_lifecycle.py`, `tests/test_subaction_hooks.py`.
>
> **Space-host refactor DONE** (`SPACE_HOST_REFACTOR.md`; mechanism only, no new card modules). The
> action-space *parent* frames are now uniform before/after hosts, in four mechanisms: **Atomic**
> (`PendingActionSpace`), **Commit-terminated** (the markets), **Delegating** (the new
> `PendingSubActionSpace` — folding Farmland/Fencing, always-wrapping the Major Improvement space,
> + Lessons — and `PendingMajorMinorImprovement` as the composite major/minor action, both
> auto-advancing when their one child pops), and **Proceed-host** (the and/or + and-then spaces +
> Meeting Place, which flip on an explicit `Proceed`). After-auto firing migrated out of `_apply_stop`
> (now pure-pop) to each host's work-complete boundary, so it lands after the work and before the
> after-triggers. The NN was preserved with **no retrain** by aliasing `Proceed` to `Stop` in the
> policy label fn + the encoder's `stop_is_legal` feature (+ C++ mirror). Milk Jug moved to
> `before_action_space`; Firewood Collector deferred (needs an end-of-turn event). The 9 Family-reachable
> frames are C++-synced; full suite + all C++ differential gates green. This unblocks the parent-hooking
> after cards (Sugar Baker, Full Peasant, Merchant, Plumber, …). Side Job stays Stop-terminated (Family-only,
> never card-hooked). Royal Wood still awaits a future end-of-turn event (Firewood Collector now lands on
> the `end_of_turn` event added in Unit 4).
>
> **Firing infrastructure COMPLETE for action spaces + commit-terminated sub-actions.** Every action
> space, the composite major/minor action, and the eight commit-terminated sub-actions now fire the
> full **before/after × automatic/trigger** suite — before-autos at push, after-autos at the
> work-complete boundary, before/after triggers via the enumerator — each backed by gap-catching tests
> (`tests/test_space_host_hooks.py`, `tests/test_subaction_hooks.py`, verified to fail without the firing).
>
> **Remaining firing deferrals (FUTURE WORK — not yet built):**
> - **Multi-shot builders** (`PendingBuildStables` / `PendingBuildRooms` / `PendingBuildFences`) — these
>   are Stop-terminated (build-loop, then `Stop`), so they have no `phase` host and **no before/after
>   firing yet**. Needed by the build-fence/stable/room cards (Hedge Keeper, Asparagus Gift, Loppers,
>   Lumberjack, Wall Builder, Pigswill, …). Approach: the derived `after_started` model (§2 of
>   `SUBACTION_HOOK_REFACTOR.md`, no `phase` field) for the after-event, plus a before-event at push.
>   This is the last *action-layer* firing gap; doing it would make the action/sub-action hook
>   infrastructure fully complete.
> - **Oven wrappers** (`PendingClayOven` / `PendingStoneOven`) — the free-bake sub-frames host no
>   firing. Niche (a card hooking specifically "the free bake after building an oven"); low priority.
> - The **round-start / Preparation / harvest (feed-breed)** phase hooks are a separate, larger system —
>   tracked as **Step 6** below, not an extension of the action-space firing work.
> - **Step 5** — `FutureReward` + Category 8 (deferred goods) → **DONE (Unit 2)**. Implemented with
>   design **(b)**, NOT the `future_resources`-generalization design (a) sketched in §II.5 below: the
>   Family-reachable `future_resources` (the Well's `tuple[Resources]`) is kept UNCHANGED, and a
>   **separate card-only `PlayerState.future_rewards: tuple[FutureReward]`** carries only what a
>   `Resources` slot cannot (animals + round-start effect-card hooks). Card-only + default-skipped →
>   Family byte-identical → **no C++ sync needed** (all C++ differential gates green untouched). See
>   the Unit-2 block below.
> - **Step 6** — phase hooks (`PendingPreparation`, `PendingHarvestField`, `PendingCardChoice` + the
>   mandatory-with-choice gate) → Cat 7, 6. **DONE.** Harvest-field hook — `PendingHarvestField` (II.6)
>   + the `harvest_field` event + Category 6 (Scythe Worker, Butter Churn, Three-Field Rotation, Loom).
>   **Start-of-round hook + mandatory-with-choice + end-of-turn event (Unit 4) DONE** —
>   `PendingPreparation` (II.6, card-dependent push in `_complete_preparation` → Family byte-identical,
>   no C++), the `start_of_round` event, the third firing kind (a `mandatory`-tagged trigger that gates
>   its host's Proceed/Stop and pushes `PendingCardChoice` + `CommitCardChoice` resolved by a card-keyed
>   resolver), `FireTrigger.variant` for the collapsed play-variant (Scholar), and a dedicated
>   `end_of_turn` event (fired at the turn-completion boundary in `_apply_stop`). Cards: **Small-scale
>   Farmer, Childless, Scullery, Groom, Plow Driver, Scholar** (Cat 7), **Seasonal Worker** (Cat 3,
>   mandatory-with-choice on Day Laborer), and **Firewood Collector un-deferred** onto `end_of_turn`.
> - **Step 7** — deferred cards (Organic Farmer, Mini Pasture, Shepherd's Crook, Acorns Basket) last.
>
> **CardStore + leftovers (Unit 5) DONE** — `CardStore` (II.7): a sparse, hashable per-player side-map
> `PlayerState.card_state` (sorted `(card_id, value)` tuple + `get`/`set`), card-only (added to the
> manual `PlayerState.__hash__` AND canonical's `_DEFAULT_SKIP_FIELDS`; the canonical walker serializes
> it generically as a frozen dataclass over a tuple) → the Family game is byte-identical (empty store
> omitted) → **no C++ change** (all 138 differential gates green untouched). Cards: **Tutor** (Cat 1 —
> `on_play` snapshots `len(occupations)`, scoring term returns `len(occupations) − 1 − snapshot`);
> **Big Country** (Cat 2 — immediate food + banked bonus points scaled by complete rounds left, scoring
> term reads the bank; prereq "all farmyard spaces used"); **Moldboard Plow** (Cat 4 — twice-per-game
> granted plow on Farmland's after-hook, uses-left in CardStore, decremented per fire); **Roof Ballaster**
> (Cat 2 — optional pay-1-food→1-stone-per-room, modeled as a play-VARIANT: a new
> `specs.PLAY_OCCUPATION_VARIANTS` registry + `CommitPlayOccupation.variant` surfaces one commit per legal
> variant, like Cooking Hearth's return-fireplace options); **Shifting Cultivation** (Cat 2, traveling —
> `on_play` pushes `PendingPlow`). The Shifting Cultivation **flip handling**: `_execute_play_minor` now
> flips the `PendingPlayMinor` host to `phase="after"` and fires the after-events BEFORE running
> `on_play` (mirroring how `_execute_build_major` flips `PendingBuildMajor` before pushing the oven
> wrapper), so the pushed `PendingPlow` lands on top of the already-flipped host and unwinds cleanly.
>
> **FutureReward + Category 8 (Unit 2) DONE** — the deferred-goods cards (`tests/test_cards_category8.py`,
> `tests/test_cards_one_shot_latch.py`, `tests/test_cards_future_reward.py`; full suite + C++ gates green).
> Infrastructure: **design (b)** for deferred rewards — goods/food ride the existing
> `future_resources`; a card-only `future_rewards: tuple[FutureReward]` (animals + effect-card hooks,
> default-skipped, in `PlayerState.__hash__`) carries the rest, so the Family game is byte-identical and
> **no C++ change was needed**. `engine._collect_future_rewards` distributes each round's slot at
> Preparation (animals auto-accommodated via the Pareto frontier — decision-free; effect hooks fired via
> a `ROUND_START_EFFECTS` registry). The **one-shot conditional latch** (II.3 / §6) —
> `register_conditional` + `engine._fire_ready_one_shots`, swept at the two points a standing house-
> material condition can change for the owner (right after a renovate, and right after a card is played) —
> latches in the per-game `fired_once` set. A shared `cards/schedules.py` (`schedule_resources` /
> `schedule_effect`) holds the round-slot math. Cards: **Wall Builder** (after-build-rooms auto),
> **Manservant** + **Clay Hut Builder** (conditional latch), **Pond Hut · Strawberry Patch · Large
> Greenhouse · Sack Cart · Thick Forest** (on-play goods minors; Thick Forest's "5 Clay in Your Supply"
> is a no-debit prereq), **Herring Pot** (`before_action_space` hook on Fishing, per the Trigger-Timing
> ruling — "each time you use [space]" fires BEFORE the space's effect), and **Handplow** (a round-start
> EFFECT on `future_rewards`, not goods). **One modeling compromise flagged for review:** Handplow's
> "you *can* plow" is modeled as forced-if-a-legal-cell-exists (the round-start `PendingPlow` has no
> decline path), so it cannot decline the plow — usually harmless (a free field), but declining can be
> strategically correct late game when a new field consumes a wanted farmyard cell; revisit if a
> declinable round-start primitive is wanted.
>
> **Deferred-within-category cards** still awaiting their infra: Cottager (build-or-renovate choice).

This doc is the concrete build plan for the **59 base-game cards that need no cost-modification,
no legality/affordability reachability search, no at-any-time conversion closure, and no per-card
goods-stack** — i.e. everything implementable on additive hooks today. It is the buildable
complement of the hard set called out in `CARD_SYSTEM_DESIGN.md` §8/§15.

- The **architecture** (terminology, the hook/trigger/automatic-effect model, the scoped-used-set
  reset model, the play-card pendings, `FutureReward`, the affordability problem) lives in
  **`CARD_SYSTEM_DESIGN.md`** and is not re-derived here. This doc says *how to write the code*.
- It is organized as **Part I — engine changes for card-vs-Family play** (mode, action-board
  deltas, private hands), then **Part II — the shared card infrastructure** (registries, the
  `PendingActionSpace` hook, scoped used-sets, play-card pendings, deferred rewards, the
  start-of-round / harvest-field / opponent hooks), then **Part III — the cards, by category**,
  each with a canonical worked example grounded in the real engine.

The guiding invariant throughout (from `CARD_SYSTEM_DESIGN.md` §11): **with no card in play the
Family game must behave byte-identically and the C++ differential gates must stay green.** Every
card field defaults empty/inert; every guard is O(1) and short-circuits on empty ownership.

---

## Scope — the 59 cards this doc covers

24 occupations + 35 minors, grouped by the engine machinery they need (Part III headings). Hard
cards excluded here and tracked in `CARD_SYSTEM_DESIGN.md`: cost-modifiers (Carpenter, Master
Bricklayer, Hedge Keeper, Frame Builder, Lumber Mill, Carpenter's Parlor, Rammed Clay), legality
changers (Conservator, Adoptive Parents, Paper Maker, Lasso, Sleeping Corner, Mantlepiece),
capacity-gating (Animal Tamer, Drinking Trough, Caravan→`wontfix`), at-any-time conversions / §15
(Sheep Walker, Grocer, Hard Porcelain, Clearing Spade), deferred subsystems (Claypipe cumulative
counter, Brook board-geometry, Beanfield field-card).

---

# Part I — Engine changes for card vs. no-card play

The Family game and the card game differ in engine-visible ways beyond "are there cards": the
**action board** differs and players have **private hands**. The board deltas (card mode vs. Family):
**Side Job** is *gone*; **Meeting Place** gives become-SP + an *optional* minor and *no food* (Family:
food-accumulation); **Lessons** is the occupation-play space (Family: unusable); and **Basic Wish for
Children**, **Major/Minor Improvement**, and **House Redevelopment** gain a play-a-minor option. (The
2-player extra tile is optional and never used, in either mode.) None of this can be inferred from
"are the hands empty" — it is a setup-level choice (`CARD_SYSTEM_DESIGN.md` §2/§11).

## I.1 The game mode

Today the action board is a fixed 25-entry tuple keyed positionally by `constants.SPACE_IDS`
(`farm_expansion, meeting_place, grain_seeds, farmland, lessons, day_laborer, forest, clay_pit,
reed_bank, fishing, side_job, …` + the stage cards). Legality iterates a single predicate dict,
`FAMILY_GAME_LEGALITY` (already renamed from `ALL_LEGALITY` in `legality.py`); resolution dispatches
on `space_id` through `ATOMIC_HANDLERS` / `NONATOMIC_HANDLERS`.

**The mode is an explicit `GameMode` field on `GameState`, read wherever the two variants diverge.**
The card game is coded directly, on its own terms; where a function's Family and card behavior
differ, we **branch on `state.mode` or write two functions** — we do *not* contort the card path to
make Family fall out as a degenerate special case. The win this buys: the Family branch is *literally
today's code*, so Family behavior is byte-identical by construction (not by a cleverness we have to
re-verify), which is exactly what keeps the C++ Family differential gates green.

```python
# constants.py
class GameMode(Enum):
    FAMILY = auto()
    CARDS  = auto()

# state.py — GameState gains one immutable field (default FAMILY → Family states unchanged in shape).
    mode: GameMode = GameMode.FAMILY
```

Placement enumeration is the first split, and it's purely a matter of **which predicate dict each
mode iterates** — the rule-deltas are just different keys:

```python
# legality.py
FAMILY_GAME_LEGALITY = {**ATOMIC_LEGALITY, **NON_ATOMIC_LEGALITY}   # the existing dict (no `lessons`, has `side_job`)
CARD_GAME_LEGALITY   = {**ATOMIC_LEGALITY_CARDS, **NON_ATOMIC_LEGALITY_CARDS}
# CARD_GAME_LEGALITY: adds "lessons" + "meeting_place_cards", drops "side_job"; the rest are the same.

def legal_placements(state: GameState) -> list[PlaceWorker]:
    if state.players[state.current_player].people_home < 1:
        return []
    table = FAMILY_GAME_LEGALITY if state.mode is GameMode.FAMILY else CARD_GAME_LEGALITY
    return [PlaceWorker(space=s) for s, pred in table.items() if pred(state)]
```

Because each mode iterates its own dict, a delta like "Lessons is usable in cards but not Family" is
expressed as **presence/absence of a key**: `lessons` is a key only in `CARD_GAME_LEGALITY`,
`side_job` only in `FAMILY_GAME_LEGALITY`. The Family dict *is* today's `FAMILY_GAME_LEGALITY`
unchanged, so Family enumeration is byte-identical. Resolution dispatch (`ATOMIC_HANDLERS` /
`NONATOMIC_HANDLERS`) stays keyed by `space_id`; card-only spaces add their own ids/handlers and
never appear on a Family board.

**Byte-identity / C++ note.** The new `mode` field — and the new card fields on `PlayerState`
(I.5, II.3) — change `canonical.dumps`, which the C++ Family differential gates compare against. To
keep those gates green during Python card development without an early C++ port, have `canonical.py`
**omit card fields (and `mode`) when they hold their default**, so a Family state serializes exactly
as today. This is one localized allowance in the tag-driven walker (a `default-skip` field-name set),
and it is the same trick that lets the eventual C++ card port add the fields incrementally.

## I.2 Side Job (present in Family, gone in cards)

Side Job is a permanent Family space (`side_job`, with `_initiate_side_job` pushing
`PendingSideJob`). The card board (built by `_make_action_spaces_cards` in setup) simply omits it,
and `CARD_GAME_LEGALITY` has no `side_job` key, so card-mode placement never enumerates it; nothing
else changes. (Its handler and pending stay in the codebase — just unreachable in card mode.)

## I.3 Meeting Place (food-accumulation in Family, play-a-minor in cards)

> **Implementation deviation (DONE):** the actual code **reuses the `meeting_place` slot** with a
> mode-branched resolver rather than a new `meeting_place_cards` SPACE_ID (see top status block). The
> space-host refactor also renamed `PendingMeetingPlaceCards` to `PendingMeetingPlace` and made it a
> single-optional Proceed-host. The canonical sketch below describes the original design rationale.

This is the one genuine resolver fork. Today `meeting_place` is a food-accumulation space
(`FOOD_ANIMAL_ACCUMULATION_RATES["meeting_place"] = ("food", 1)`) resolved by
`_resolve_meeting_place` (take accumulated food + become next-round starting player).

The card-game Meeting Place grants **become starting player (always) + *optionally* play one minor
improvement — and gives NO food** (unlike Family's food-accumulation). A player may use it just for
the SP, declining the minor (even if already SP). Give the card board a **distinct space id**
`meeting_place_cards` with its own non-atomic handler (cleaner than branching a shared resolver, and
it needs no runtime `mode` read — the card board simply carries the card-variant id):

```python
# resolution.py — card-mode Meeting Place: become SP (always), then OPTIONALLY play a minor (no food).
def _initiate_meeting_place_cards(state: GameState) -> GameState:
    state = _become_starting_player(state, state.current_player)   # extract this from _resolve_meeting_place
                                                                   # (today it's inline: fast_replace(starting_player=ap))
    return push(state, PendingPlayMinor(                            # see II.4 — PendingPlayMinor has no
        player_idx=state.current_player,                           # cost field; the minor pays its own
        initiated_by_id="space:meeting_place_cards"))              # printed cost. Optional → its enumerator
                                                                   # offers the playable minors + Stop (decline).
```

The Family board keeps `meeting_place` with today's resolver, untouched. The UI/encoder treat the
two ids as the same physical tile per mode (the card mode never shows `meeting_place`, and vice
versa).

## I.4 Lessons (unusable in Family, the occupation-play space in cards)

`lessons` has **no predicate in today's legality dict**, so the Family game can never surface it —
its "exclusion" is *absence from the dict*, not a filter (there is no `_legal_lessons` and no handler;
`_apply_place_worker`'s `NotImplementedError` is the backstop). In card mode it becomes the
occupation-play space: `CARD_GAME_LEGALITY` gives `lessons` a predicate (`FAMILY_GAME_LEGALITY` still
has no such key), surfacing it when the player can play an occupation from hand at this space's cost:

```python
# legality.py — a key only in CARD_GAME_LEGALITY
def _legal_lessons_cards(state: GameState) -> bool:
    if not _is_available(state, "lessons"):
        return False
    idx = state.current_player
    p = state.players[idx]
    if not p.hand_occupations:                                    # nothing to play
        return False
    return _can_afford(p, occupation_cost(len(p.occupations)))    # the single affordability gate
```

The Family path is untouched (Lessons stays unconditionally excluded). The card predicate reads the
decider's own hand off `state.players[...]` — which is why hands must live where `legal_actions` can
see them (I.5).

## I.5 Private hands

**Both players' hands live concretely on `PlayerState`** as frozensets (default empty → the Family
game is inert and byte-identical). `GameState` therefore stays a single, fully-determined world, and
`step` / `legal_actions` remain pure functions of `GameState` with no new arguments — they read the
decider's own hand off `state.players[decider].hand_*` (the only hand any decision ever needs; the
opponent's hand never gates the *current* decision).

```python
# state.py — additions to PlayerState (default empty/inert; Family game never populates them).
    hand_occupations:  frozenset = frozenset()   # frozenset[str] — card ids dealt, not yet played
    hand_minors:       frozenset = frozenset()
```

**The engine is deliberately perfect-information on a concrete world; hidden info is handled entirely
above it.** When the actual game runs, the driver holds the true world (both real hands) plus the
`Environment`. The opponent's hand being secret is *not the engine's concern*: it is handled by the
search, which is **ISMCTS with determinization** — once per search iteration it samples a concrete
opponent hand consistent with what the observer knows, producing a fully-determined `GameState`, and
runs ordinary perfect-information selection/rollout on it through unmodified `step` / `legal_actions`.
The engine never reasons about a belief or a distribution; it always sees concrete frozenset hands.
(Why not an optional "hand-override" argument to the enumerator instead? Because playing a card
*mutates* the hand — `step` removes it hand→tableau and that removal must persist — so the hand is
genuine `GameState` that `step` writes, not a transient input to enumeration. An override would leave
`step` with no hand to update, and create a second source of truth.)

The determinization itself is a **search-layer** function, not engine code:

```python
# search layer — fill the opponent's unknown hand for one ISMCTS iteration.
def determinize(observation: GameState, observer: int, rng) -> GameState:
    opp = 1 - observer
    pool = consistent_pool(observation, observer)        # configured pool − everything observer can see
    n_occ, n_min = opp_hand_counts(observation, opp)     # PUBLIC counts — see the note below
    opp_p = fast_replace(observation.players[opp],
        hand_occupations=frozenset(rng.choice(pool.occ,   n_occ, replace=False)),
        hand_minors     =frozenset(rng.choice(pool.minor, n_min, replace=False)))
    return fast_replace(observation, players=tuple(
        opp_p if j == opp else observation.players[j] for j in range(2)))
```

The competitive-Agricola **draft** makes this belief *narrow*, not uniform: you saw most of the
opponent's cards pass through your hands during the draft, so `consistent_pool` is small (genuine
uncertainty is mostly the first card of each type, fully hidden, and the last, one of a small known
set). That only tightens the sampler's distribution — it does not change anything engine-side. We do
**not** model the draft in the engine: per `CARD_SYSTEM_DESIGN.md` §2 the engine just deals from a
configured pool; the draft realism is a belief-construction concern for the eventual ISMCTS work
(§13), not part of this plan.

`observe(state, env, i)` is **new** — today the `Environment` has no projection (CLAUDE.md: "the
identity today", a forward-compat placeholder). It produces the observer's view — own hand intact,
opponent's hidden — via a **new `_anonymize` helper** (replaces a hand's ids with same-count anonymous
placeholders), and is the input the determinizer re-fills:

```python
# environment.py — masks the opponent's hand IDENTITY but must preserve its CARDINALITY (see note).
def observe(state: GameState, env: "Environment", i: int) -> GameState:
    opp = 1 - i
    masked_opp = fast_replace(state.players[opp],
        hand_occupations=_anonymize(state.players[opp].hand_occupations),   # keep count, hide ids
        hand_minors     =_anonymize(state.players[opp].hand_minors))
    players = tuple(masked_opp if j == opp else state.players[j] for j in range(2))
    return fast_replace(state, players=players)
```

> **Decided: `observe` masks identity but preserves cardinality** (the `_anonymize` sketch above).
> The determinizer needs *how many* cards the opponent holds per type, and that count is **public**
> (hands start 7+7 and shrink only through public plays), so the masked hand keeps the right size with
> anonymous placeholders. One bookkeeping detail remains: **passing minors** move a card from one hand
> to another as a public event, so the anonymized count must track passes. This lives entirely in the
> search/`observe` layer and does not change how hands are stored.

The byte-identity / C++ handling for these new fields is the `default-skip` serializer note in I.1.

## I.6 Setup by mode

`setup_env(seed)` gains a mode/pool argument; the Family path is the current default and is
unchanged:

```python
# setup.py
def setup_env(seed, *, card_pool=None):
    """card_pool=None → Family game (today's board, empty hands).
       card_pool=CardPool(occupations=[...], minors=[...]) → card game."""
    rng = np.random.default_rng(seed)
    ...
    if card_pool is None:
        board = BoardState(action_spaces=_make_action_spaces_family(), ...)   # today
        players = tuple(_make_player(food_for[p]) for p in range(2))          # empty hands
    else:
        board = BoardState(action_spaces=_make_action_spaces_cards(), ...)    # card board (the I.2–I.4 deltas)
        hands = _deal_hands(rng, card_pool)         # 7 occ + 7 minor each, uniform from the pool
        players = tuple(_make_player(food_for[p], hand_occupations=hands[p].occ,
                                     hand_minors=hands[p].minor) for p in range(2))
    ...
```

`setup_env` also sets the `GameState.mode` it constructs (`FAMILY` when `card_pool is None`, else
`CARDS`) — the single field the delta points (`legal_placements`, …) read; the mode is *chosen here at
setup*, not inferred later from runtime state. `_make_action_spaces_cards()` builds the card board:
today's spaces with the I.2–I.4 deltas (no Side Job; the play-minor Meeting Place; usable Lessons). The
two builders split today's single `_make_action_spaces` — `_make_action_spaces_family` *is* that
function, renamed (so the Family board is byte-identical).

---

# Part II — Shared card infrastructure

Build these once; the per-category cards (Part III) are then small. Each piece extends the existing
machinery the engine already has for Potter Ceramics and the harvest conversions — it is not new
scaffolding from scratch.

## II.1 Firing model: triggers, automatic effects, hooks

The engine already has the **trigger** path: `cards/triggers.register(event, card_id,
eligibility_fn, apply_fn)` populates `TRIGGERS` (event-keyed) + `CARDS` (id-keyed); an enumerator
offers a `FireTrigger(card_id)` for each owned, eligible, unfired card registered on the top frame's
event (derived as `trigger_event(frame)` — II.2); `_apply_fire_trigger` calls `apply_fn` and records
the id in the frame's `triggers_resolved`. Potter Ceramics is the worked example.

**Automatic effects** (mandatory, choice-free — Wood Cutter's +1 wood, Loom's harvest food) need a
**parallel registry applied directly at the hook**, never surfaced as a `FireTrigger`:

```python
# cards/triggers.py — additions (mirrors register()/TRIGGERS).
@dataclass(frozen=True)
class AutoEntry:
    card_id: str
    event: str
    eligibility_fn: Callable   # (state, owner_idx) -> bool
    apply_fn: Callable         # (state, owner_idx) -> GameState
    any_player: bool = False   # False = fires for the ACTING player; True = for every owner (Milk Jug)

AUTO_EFFECTS: dict[str, list[AutoEntry]] = {}

def register_auto(event, card_id, eligibility_fn, apply_fn, *, any_player=False) -> None:
    AUTO_EFFECTS.setdefault(event, []).append(
        AutoEntry(card_id, event, eligibility_fn, apply_fn, any_player))

def apply_auto_effects(state: GameState, event: str, acting_player: int) -> GameState:
    """Fire every owned, eligible automatic effect for `event`, in registration order. A no-op when
    AUTO_EFFECTS.get(event) is empty (the Family fast path). Own-action effects fire for the acting
    player; `any_player` effects fire for EACH owner (so Milk Jug fires for its owner even on the
    opponent's turn — its apply_fn/eligibility receive that owner as the index)."""
    for e in AUTO_EFFECTS.get(event, ()):
        owners = range(len(state.players)) if e.any_player else (acting_player,)
        for owner in owners:
            if _owns(state.players[owner], e.card_id) and e.eligibility_fn(state, owner):
                state = e.apply_fn(state, owner)
    return state

def _owns(p: PlayerState, card_id: str) -> bool:
    return card_id in p.occupations or card_id in p.minor_improvements
```

So a hook fires automatic effects by calling `apply_auto_effects(state, event, idx)`; triggers are
surfaced as `FireTrigger` options by the enumerator (unchanged Potter pattern). A single hook can
host both kinds (`CARD_SYSTEM_DESIGN.md` §0).

### The three firing kinds (incl. mandatory-with-choice)

Two firing kinds aren't enough: some effects are **mandatory but require a choice** — Seasonal
Worker from round 6 ("1 grain, *or* you may choose 1 vegetable") and Childless ("1 food + 1 crop *of
your choice*"). You can't decline (so not an optional trigger), but the engine can't apply it
silently (so not a plain automatic effect). The full taxonomy:

| Firing kind | Mechanism | Example |
|---|---|---|
| **Optional** | `FireTrigger` — the enumerator offers it; declining is implicit (pick a commit / `Stop` / `Proceed`) | Potter, Mushroom Collector |
| **Mandatory, no choice** | **automatic effect** — `apply_auto_effects` applies it directly, no `FireTrigger` clutter | Wood Cutter |
| **Mandatory, with choice** | a **trigger tagged `mandatory`** — surfaced as a `FireTrigger`, but the frame's **phase-exit action (`Proceed`/`Stop`) is gated off until it fires** | Seasonal Worker (r6+), Childless |

The mandatory-with-choice path **reuses the trigger machinery** rather than adding a separate
"auto-effect that pushes a frame" path — the win is **re-entrancy for free**: firing a trigger that
pushes a sub-decision, resolving it, returning to the hook, and re-enumerating is exactly what the
trigger loop already does. And **singleton-skip hides the "fire" step**: when the mandatory trigger
is the only legal action (its phase's exit gated off, no other triggers), the agent auto-fires it, so
the player sees only the *real* choice.

- **The gate:** the hook enumerator omits the phase-exit action while the current phase has an
  eligible, unfired `mandatory` trigger (before-phase → no `Proceed`; after-phase → no `Stop`).
- **Firing pushes the choice:** a mandatory trigger's `apply_fn` pushes a `PendingCardChoice` (II.6)
  for its decision; `triggers_resolved` records the fire so the gate reopens.
- **`mandatory` is a static registration flag**, gated by eligibility. Seasonal Worker is cleanest as
  an *always*-`mandatory` trigger whose `PendingCardChoice` **options are round-dependent**:
  `[grain]` pre-round-6 (a singleton → auto-resolves) and `[grain, veg]` from round 6 — so the
  round-6 rule lives in the options, not the firing kind. Childless: eligible only when its
  rooms/people condition holds; fires → +1 food + push the crop choice.

## II.2 The action-space hook — `PendingActionSpace`

Every action space — atomic and non-atomic — is a **space-host frame** that fires the coarse
`before_/after_action_space` event (routing below). The frame *class* differs only by need:

- **Non-atomic spaces keep their existing per-space frames** (`PendingGrainUtilization`,
  `PendingCattleMarket`, …). They carry space-specific sub-action state (`sow_chosen`, `gained`, …),
  so they earn a typed class; they are **not** replaced or wrapped.
- **Atomic spaces** have no sub-action state, so they share **one generic `PendingActionSpace`**. Its
  `space_id` is read off `initiated_by_id` (`"space:forest"` → `"forest"`), not stored twice.

Following `CARD_SYSTEM_DESIGN.md` §4, an atomic space stays atomic (no frame pushed) until a card
needs to fire on it:
- **Conditional push:** `_apply_place_worker` pushes the host frame only when
  `_should_host_space(state, space_id, acting_player)` is true; otherwise it takes today's atomic fast
  path. That test reads two registration-time indexes (below): the **acting** player's own-action
  cards for this space, plus — only where that index is non-empty — *any* player's opponent-firing
  cards. Family tableaus empty → both miss → atomic → byte-identical.
- **Lifecycle:** push (before-phase) → fire before automatic-effects + surface before-triggers →
  `Proceed` applies the space's primary effect and flips to the after-phase → after automatic-effects
  + after-triggers → `Stop` pops. **`Proceed` and `Stop` are handled like any other singleton.** When
  no before-(after-)trigger is eligible, the enumerator just returns `[Proceed]` (`[Stop]`) — a
  *singleton step the agent auto-applies*, exactly as it already does for today's singleton `Stop`s.
  We do **not** engine-auto-advance `Proceed`: the engine's "no auto-resolved singleton decisions"
  convention treats singleton `Proceed`s and singleton `Stop`s identically (both are recorded steps
  the agent skips), so the common path costs the same one auto-skipped step a singleton `Stop` already
  does — no special-casing, and consistent.

```python
# pending.py — the generic host frame for ATOMIC spaces (non-atomic spaces use their own classes).
@dataclass(frozen=True)
class PendingActionSpace:
    PENDING_ID: ClassVar[str] = "action_space"   # in the action-space routing bucket (below)
    player_idx: int
    initiated_by_id: str                 # "space:forest" → space_id property strips the prefix
    phase: str = "before"                # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    # gained: int = 0  — add only when a card keys on goods received at an atomic accumulation space
    #                    (YAGNI; the non-atomic market frames already carry their own `gained`).
    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]

# actions.py
@dataclass(frozen=True)
class Proceed:                           # before→after: apply primary effect, flip phase
    pass
```

```python
# engine._apply_place_worker — the conditional-push fork. The generic PendingActionSpace is pushed
# ONLY for atomic spaces; non-atomic spaces always go through their own handler (whose parent frame
# IS the space-host, so it needs no PendingActionSpace).
def _apply_place_worker(state, action):
    state = _apply_worker_placement(state, action.space)
    if action.space in NONATOMIC_HANDLERS:
        return NONATOMIC_HANDLERS[action.space](state)        # parent frame is the host; fires the event
    # atomic space — host with the generic frame only when a card could fire here, else today's path
    if _should_host_space(state, action.space, state.current_player):
        return push(state, PendingActionSpace(
            player_idx=state.current_player,
            initiated_by_id=f"space:{action.space}"))
    return ATOMIC_HANDLERS[action.space](state)               # fast path — unchanged
```

The primary effect applied by `Proceed` is the atomic space's existing resolver
(`ATOMIC_HANDLERS[space_id]`). **Non-atomic spaces are not wrapped** — they already *are* space-host
frames, so their existing parent (`PendingCattleMarket`, …) fires `before_action_space` when it is
pushed and `after_action_space` at its `Stop`, with its sub-action sequence running in between. No
`PendingActionSpace` nesting.

### Event routing — by `PENDING_ID`, with a space bucket

A frame's trigger event is derived from its **`PENDING_ID`** (the class-level kind), not from
`initiated_by_id`:

- A bucket of `PENDING_ID`s routes to the **coarse** action-space event — this covers the generic
  atomic frame **and** every non-atomic per-space frame, so all action spaces share one event and a
  card spanning several spaces registers **once** and filters `space_id`.
- Every other `PENDING_ID` (the sub-actions) routes to its own event, `before_/after_<PENDING_ID>`.

```python
# legality.py — derive the event the enumerator looks up (replaces reading a per-frame TRIGGER_EVENT)
ACTION_SPACE_PENDING_IDS: frozenset[str] = frozenset({   # PENDING_IDs (frame ids), not space ids
    "action_space", "farm_expansion", "farmland", "side_job", "grain_utilization",
    "sheep_market", "pig_market", "cattle_market", "major_minor_improvement",  # ← the frame's id, not "major_improvement"
    "house_redevelopment", "cultivation", "farm_redevelopment", "fencing"})

def trigger_event(frame) -> str:
    pid = type(frame).PENDING_ID
    base = "action_space" if pid in ACTION_SPACE_PENDING_IDS else pid
    return f"{frame.phase}_{base}"        # e.g. before_action_space, before_plow, after_renovate
```

**Why `PENDING_ID`, not `initiated_by_id`** (this is a correctness point, not a style preference): a
sub-action frame's `initiated_by_id` is its **parent's** id, not its own — `PendingPlow` pushed at
Farmland has `initiated_by_id = "farmland"` but `PENDING_ID = "plow"`. Routing on `initiated_by_id`
would mis-key every sub-action to its parent space; `PENDING_ID` routes `PendingPlow` correctly to
`before_plow`. So the two ids divide labor cleanly:

- **`PENDING_ID`** (class-level) → **event routing** (which event the frame fires).
- **`initiated_by_id` = `"space:<id>"`** → the **`space_id`** a card filters on in eligibility —
  still needed, because the coarse event doesn't name the space and the generic atomic frame's
  `PENDING_ID` is `"action_space"`, not the real space.

(The bucket can be the central `frozenset` above, or each space-host frame can declare
`EVENT_BASE = "action_space"` as a ClassVar — same result, no central set to keep in sync.) This
**revised `ENGINE_IMPLEMENTATION.md` invariant 9** (already updated there): `before_<PENDING_ID>`
still holds for sub-action frames, but space-host frames now share the `action_space` base.

**Two hosting indexes, not one** (the design-doc §4 own-vs-any tag, made concrete). Most cards fire
on the *acting* player's use of a space; only a few fire on *any* player's use (so they must host on
the opponent's turn too). Splitting the index keeps the all-players scan off the common path:

```python
# built at registration from each card's declared spaces + its own/any tag
OWN_ACTION_HOOK_CARDS: dict[str, frozenset[str]]   # fire on the ACTING player's use
ANY_PLAYER_HOOK_CARDS: dict[str, frozenset[str]]   # fire on ANY player's use (empty for almost every space)

def _should_host_space(state, space_id, acting_player) -> bool:
    owned = lambda p: p.occupations | p.minor_improvements          # PLAYED cards (a hand card can't fire)
    if owned(state.players[acting_player]) & OWN_ACTION_HOOK_CARDS.get(space_id, frozenset()):
        return True
    anyp = ANY_PLAYER_HOOK_CARDS.get(space_id, frozenset())
    return bool(anyp) and any(owned(p) & anyp for p in state.players)  # opponent scan only where anyp ≠ ∅
```

**Full-catalog scan — the any-player set is tiny in 2-player.** Reading every occupation and minor
across the base game + all five expansions: **no `1+` occupation fires on an opponent's action**, and
exactly **9 minors** do — **Milk Jug** (Cattle Market), **Hod** (Pig Market), **Corf** & **Material
Hub** (building-resource accumulation spaces), **Fishing Net** (Fishing), **Chapel** & **Forest Inn**
(card-created shared spaces), **Bassinet** (any non-accumulating space), and **Recycled Brick** (the
renovate *event*). **8 of the 9 are space-keyed** → they populate `ANY_PLAYER_HOOK_CARDS`, which is
empty for every other space, so the opponent scan is skipped everywhere else. The 9th, **Recycled
Brick, is NOT space-keyed** — it fires on the renovate event, so it rides the build/renovate hook
(Category 5), not `ANY_PLAYER_HOOK_CARDS`. For the **base implementable set, Milk Jug (Cattle Market)
is the only opponent-firing card**; the other 8 are expansion cards. Notes: **Chapel / Forest Inn**
are simple tolls (the opponent pays 1 food before using the space); **Fishing Net** is a more complex
toll (deferred); **Bassinet** is the outlier whose any-player entry spans *all* non-accumulating
spaces — still ownership-gated, so it only activates when a player has actually played it.

### Changes to the existing `Pending*` classes

> **Status: DONE** — all of the frame changes described below were completed by the sub-action hook
> refactor (`SUBACTION_HOOK_REFACTOR.md`) and the space-host refactor (`SPACE_HOST_REFACTOR.md`).
> `PendingFarmland` and `PendingFencing` were folded into `PendingSubActionSpace` (Delegating host);
> `PendingMeetingPlaceCards` was renamed `PendingMeetingPlace`; the C++ mirror for Family-reachable
> frames is complete. The text below is preserved as the design record of what was changed and why.

This hook model touches the engine's existing frames. The deltas, by frame group:

**Space-host parent frames** (now: `PendingGrainUtilization`, `PendingSubActionSpace` (folding
Farmland+Fencing), `PendingCultivation`, `PendingSideJob`, `PendingSheepMarket` / `Pig` / `Cattle`,
`PendingMajorMinorImprovement`, `PendingHouseRedevelopment`, `PendingFarmExpansion`,
`PendingFarmRedevelopment`, `PendingBasicWishForChildren`, `PendingMeetingPlace`):
- **`phase: str = "before"`** — all space-host frames now carry this (Proceed-hosts flip it on
  `Proceed`; Delegating hosts flip it on auto-advance; markets flip it on `CommitAccommodate`).
- **`space_id` property** — `initiated_by_id.split(":", 1)[1]`, present on all space-host frames,
  letting cards read the space uniformly across atomic and non-atomic hosts via `top.space_id`.
- **Per-space `TRIGGER_EVENT` ClassVars dropped** — event is now derived via `trigger_event(frame)`.
- **`triggers_resolved` present** on all frames that host triggers.
- **Sub-action fields unchanged** (`sow_chosen`, `gained`, the `*_chosen` flags, …).

**Sub-action frames** (`PendingPlow`, `PendingRenovate`, `PendingBakeBread`, `PendingBuildMajor`,
`PendingSow`, `PendingFamilyGrowth`, `PendingPlayOccupation`, `PendingPlayMinor`, …):
- **`TRIGGER_EVENT` dropped** — event derives to `before_/after_<PENDING_ID>`.
- **`phase` added to all commit-terminated sub-action frames** (the sub-action hook refactor gave
  `phase` + `triggers_resolved` to all eight; the commit flips to `"after"` and a trailing `Stop`
  pops — no longer YAGNI-deferred).
- **`PendingBuildFences` and multi-shot builders** (`PendingBuildStables`, `PendingBuildRooms`) are
  Stop-terminated, not commit-terminated, so they stay outside the sub-action hook refactor scope.

**Harvest frames** (`PendingHarvestFeed`, `PendingHarvestBreed`): **no change** — no in-scope card
fires on harvest-feed/breed (the harvest cards fire on the harvest-field hook, II.6).

**The enumerator** (`legality._enumerate_pending` / the trigger-finding step): reads `trigger_event(frame)`
(bucket + phase) rather than a per-frame `TRIGGER_EVENT` ClassVar.

**Field-scoping summary:** `phase` + `triggers_resolved` ride the uniform trigger-hosting interface;
`chosen` does not exist (per-space frames keep their typed sub-action fields). Family game behavior
is preserved (no card fires; `phase` defaults `"before"`); the C++ mirror for Family-reachable
frames is complete and all differential gates are green.

## II.3 Scoped used-sets + the reset model

Per `CARD_SYSTEM_DESIGN.md` §6, "have I fired this already?" is tracked by **scoped frozensets of
card-ids on `PlayerState`**, one per reset scope, cleared *at* the scope boundary by the code that
performs the transition. New `PlayerState` fields (default empty → Family inert):

```python
# state.py — additions to PlayerState
    used_this_turn:  frozenset = frozenset()   # reset in _advance_current_player AND on WORK entry
    used_this_round: frozenset = frozenset()   # reset on entry to PREPARATION
    fired_once:      frozenset = frozenset()   # per-game one-shots; never reset
```

(`harvest_conversions_used` already exists and is the per-harvest scope, reset in
`_resolve_harvest_field`.) The clearing helper and its call sites land on the *exact* phase-mutation
points the engine already has (from the phase-walk audit):

```python
# engine.py
def _clear(state: GameState, field: str) -> GameState:
    """Empty the named scoped set on BOTH players (off-turn firings must see a fresh latch)."""
    return fast_replace(state, players=tuple(
        fast_replace(p, **{field: frozenset()}) for p in state.players))
```

| Scope | Field | Exact call site (from the current engine) |
|---|---|---|
| per-turn | `used_this_turn` | top of `_advance_current_player`; and in `_complete_preparation` at the `phase=WORK` build |
| per-round | `used_this_round` | in `_complete_preparation` (entry to the new round) |
| per-harvest | `harvest_conversions_used` | already cleared in `_resolve_harvest_field` |
| per-game | `fired_once` | never |

The per-turn "in a turn" gate (`state.phase == WORK`) and the one-shot conditional latch
(`_fire_ready_one_shots`, level-triggered, hooked after renovate + on card-play) are the §6 code.

## II.4 Play-a-card pendings — `PendingPlayOccupation` / `PendingPlayMinor`

The reusable play-card primitives (`CARD_SYSTEM_DESIGN.md` §3). Pushed by Lessons / card-mode
Meeting Place / Basic Wish for Children / start-of-round Scholar / any card grant.

> **Wiring the existing improvement spaces (aside).** The "Major/Minor Improvement" space and "House
> Redevelopment" already push parent frames (`PendingMajorMinorImprovement`,
> `PendingHouseRedevelopment`) whose **minor / improvement branch is inert today** (no cards). When
> cards land, that branch's `ChooseSubAction` must push **`PendingPlayMinor`** (alongside the existing
> major branch that pushes `PendingBuildMajor`) — so playing a *minor* improvement is reachable from
> those two spaces, not only from Lessons/Meeting Place.
>
> **Placement legality changes only for Major/Minor Improvement.** It is today legal only if you can
> afford a *major*; in cards you can build a major **or** a minor, so its `CARD_GAME_LEGALITY` predicate
> becomes **`_can_afford_a_major(...) or bool(playable_minors(state, idx))`** (Family stays "can afford a
> major"). **House Redevelopment** and **Basic Wish for Children** keep their **primary-gated** legality
> — renovate, and *family-growth-with-room* respectively — with the minor an *optional follow-up* that
> appears only in the sub-action enumeration, never as a reason to place. Their placement predicates are
> **unchanged** from Family.

```python
# pending.py — events derive via PENDING_ID (II.2): before_/after_play_occupation, _play_minor.
@dataclass(frozen=True)
class PendingPlayOccupation:
    PENDING_ID: ClassVar[str] = "play_occupation"
    player_idx: int
    initiated_by_id: str
    cost: Resources = Resources()           # the REAL play cost (route-dependent — Lessons = occ-cost
                                            # step, Scholar = 1 food); charged at resolution.
    phase: str = "before"                   # Bread Paddle hooks after_play_occupation
    triggers_resolved: frozenset = frozenset()

@dataclass(frozen=True)
class PendingPlayMinor:
    PENDING_ID: ClassVar[str] = "play_minor"
    player_idx: int
    initiated_by_id: str
    triggers_resolved: frozenset = frozenset()
    # No cost field: a minor's price is its printed cost, read from the spec at resolution. Add a
    # discount (the likelier future need) / surcharge field only when a card actually needs one.
```

Enumeration reads the player's hand and surfaces a play-action per *playable* card; resolution moves
the card hand→tableau, charges the cost, runs the on-play effect, and (for passing minors) circulates
it:

```python
# legality.py
def occupation_cost(num_played: int) -> Resources:
    """The Lessons-space cost of playing your *next* occupation, given how many you've already played.
    2-player rule: the first is free, every later one costs 1 food. (Scholar charges a flat 1 food via
    its own fire path — occupation cost is route-specific, so each route supplies its own.)"""
    return Resources() if num_played == 0 else Resources(food=1)

def playable_occupations(state, idx) -> list[str]:
    """Just the occupations in hand. Occupations have NO prerequisites, and the play cost is
    per-play (route-dependent), not per-card — so every hand occupation is equally playable once you
    can afford a play at all. The affordability gate therefore lives at the PLACEMENT predicate
    (`_legal_lessons_cards` checks `_can_afford(p, occupation_cost(...))`; Scholar checks 1 food)."""
    return sorted(state.players[idx].hand_occupations)

def playable_minors(state, idx) -> list[str]:
    """Hand minors filtered PER-CARD — minors have varying printed costs AND prerequisites (unlike
    occupations). (`_can_afford` is the engine's affordability idiom — Resources has no `>=`.)"""
    p = state.players[idx]
    return [cid for cid in sorted(p.hand_minors)
            if prereq_met(MINORS[cid], state, idx) and _can_afford(p, MINORS[cid].cost)]
```

```python
# resolution.py — play a minor (occupation mirrors it; the on-play effect dispatch is the same).
def _execute_play_minor(state, idx, card_id) -> GameState:
    spec = MINORS[card_id]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - spec.cost, hand_minors=p.hand_minors - {card_id})
    if not spec.passing_left:                        # normal minor: keep it in your tableau
        p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    state = _update_player(state, idx, p)
    state = spec.on_play(state, idx)                 # immediate effect (runs either way)
    state = _fire_ready_one_shots(state, idx)        # §6 — catches "already living in stone" cases
    if spec.passing_left:                            # a passing minor (the card's `passing_left` field
                                                     # in the JSON): NOT kept — execute, then pass it on
        opp = 1 - idx                                # execute effect, then hand to the next player
        state = _update_player(state, opp, fast_replace(state.players[opp],
                    hand_minors=state.players[opp].hand_minors | {card_id}))
    return state
```

A **passing minor** is *never* added to `minor_improvements` — per §3 you execute its immediate
effect and then pass the card to the next player (it goes to the opponent's `hand_minors`, staying in
circulation). Keeping it in your tableau would wrongly score it and count it as owned for triggers.

`prereq_met` reads the printed `prerequisites` field (e.g. `"3 Occupations"`, `"2 Vegetable
Fields"`, `"Clay or Stone House"`) against public state — a condition check, not the §15
affordability search. The card spec objects (`OCCUPATIONS` / `MINORS`) carry each card's `on_play`
plus, for minors, its cost / prereq / passing flag. **Generating these from the JSON differs by card
type:** *minors* have structured `cost` / `prerequisites` / `passing_left` fields (note `passing_left`
is the string `"X"` or `null` — the loader maps `"X"` → `True`); *occupations* have **none** of those —
their JSON entries are just `name` / `card_category` / `text`, with the effect and any condition inline
in `text`. So an occupation's `on_play` (and condition, like Priest's) is **hand-written** regardless;
occupations have no prerequisites, and their cost is route-supplied via `occupation_cost`, not a JSON
field.

> **Cost and prerequisite are two separate fields — store/check them separately** (the JSON has both;
> `prerequisites` may be empty, `cost` may be 0). `prereq_met` reads `prerequisites` (a have-check,
> never spent); the **cost is *spent*** at play. The cost is *usually* `Resources`/food, but among the
> *in-scope* base minors there are three wrinkles:
> - **Young Animal Market** (`"1 Sheep"`) and **Bottles** (`"see below"`, a *computed* `1 clay + 1 food
>   per person`) — so the spendable cost must cover **`Resources` + `Animals`**, and a **computed
>   (state→cost)** form. **Preferred model: fold these into a spendable `cost` bundle** (a
>   `(Resources, Animals)` pair, or a `state→(Resources, Animals)` callable for Bottles) that
>   `_can_afford`/debit handle uniformly. (The alternative — *don't* model the cost, let the card's
>   effect check-and-remove it itself — is uglier here but will be the right tool for some expansion
>   cards with exotic "costs"; keep it in mind, don't use it for these three.)
> - **Thick Forest** (`"5 Clay in Your Supply"`) is **not a cost at all** — it's a **prerequisite**
>   (hold ≥5 clay, *don't* spend it) that happens to sit in the `cost` JSON field. The loader must
>   route a `"… in Your Supply"` entry to the *have-check* (with `prerequisites`), never a debit.
>
> (`"1 of Your People on \"Fishing\""` — Brook — is a worker-placement cost, but Brook is deferred/§7.)

## II.5 Deferred rewards — generalize `future_resources` to `FutureReward`

> **Status: implemented as design (b), NOT the generalization below (design (a)).** This section
> sketches replacing each `future_resources` slot with a `FutureReward`. The shipped Unit-2 code took
> the cleaner **design (b)** instead: `future_resources` is kept UNCHANGED (Family-reachable, C++-
> serialized, used by the Well + every goods-scheduling Category-8 card), and a **separate card-only
> `PlayerState.future_rewards: tuple[FutureReward]`** carries only what a `Resources` slot cannot —
> animals + round-start effect-card hooks. Card-only + canonical-default-skipped → Family byte-identical
> → **no C++ change**. The dataclass shape below (`animals` + `effect_card_ids`) is exactly what landed;
> only its *placement* differs (a sibling tuple, not a replacement). See the Unit-2 status block at the
> top of this doc.

`PlayerState.future_resources` is already a `tuple[Resources, ...]` of length 14, one slot per round,
added at round start in `_complete_preparation`. (Index convention, matching the engine's Well code:
slot `r` is collected *entering round `r+1`*, so "the next N round spaces" from the current
`round_number` is `range(round_number, round_number + N)` — not an off-by-one.) Generalize the slot to
a `FutureReward` (`CARD_SYSTEM_DESIGN.md` §7/§14-item-4) so it can also carry animals and effect-hooks:

```python
# state.py
@dataclass(frozen=True)
class FutureReward:
    resources: Resources = Resources()
    animals:   Animals   = Animals()
    effect_card_ids: frozenset = frozenset()   # round-start hooks (e.g. Handplow's deferred plow)
# PlayerState.future_resources: tuple[FutureReward, ...] = (FutureReward(),) * 14
```

`_complete_preparation` already distributes `future_resources[idx]`; extend that one spot to also
**accommodate** the animals (may surface the existing overflow/Pareto decision) and fire each
`effect_card_ids` hook. Scheduling is **additive** (repeated placers stack on the same round). The
Family game leaves every slot at the default → unchanged.

## II.6 Three new phase hooks

Each mirrors the existing harvest feed/breed pending pattern (one frame, presence hosts the
decision, resolved+popped before continuing). Wiring points are the exact phase-walk sites from the
engine audit. **All three frames are net-new — none exist in the engine today** (the start-of-round
phase is purely mechanical right now; there is no `PendingHarvestField`).

- **Start-of-round — `PendingPreparation` (new).** No start-of-round frame exists today —
  `_complete_preparation` runs straight through (increment round, refill, distribute
  `future_resources`, → WORK). Add `PendingPreparation`, pushed in `_complete_preparation` *before*
  the `phase=WORK` transition, for "at the start of each round you can…" cards. Hosts auto-effects
  (Small-scale Farmer, Childless, Scullery) and triggers (Plow Driver, Groom, Scholar). Round-scoped
  budgets use `used_this_round`.
  - **Make the push card-dependent**, exactly like the atomic action-space hook (II.2): push
    `PendingPreparation` only when some player owns a start-of-round card (a registration-time
    ownership index, the `_should_host_space` analog). Family game → no such card → no frame pushed →
    `_complete_preparation` is byte-identical to today. This is the right call: it keeps the common
    path free and the Family preparation phase unchanged.
- **Harvest-field — `PendingHarvestField`.** Pushed at the top of `_resolve_harvest_field`, *before*
  the mechanical "take 1 crop per field" runs, for field-phase income (Loom, Butter Churn,
  Three-Field Rotation, Scythe Worker).
- **Opponent-action hook.** Carried by `PendingActionSpace` (II.2) on the *opponent's* turn: when the
  acting player uses Cattle Market, `_should_host_space` returns true because the *other* player owns
  Milk Jug (in `ANY_PLAYER_HOOK_CARDS`), so the host frame is pushed. The after-phase then fires Milk
  Jug via `apply_auto_effects` with `any_player=True`, which runs it for its **owner** — not the
  frame's `player_idx` (that's the acting player). Owner routing lives in `apply_auto_effects`, not on
  the frame.

### `PendingCardChoice` — the forced-choice decision frame

The small **no-`Stop`** frame that a *mandatory-with-choice* trigger (II.1) pushes to surface its
decision — Seasonal Worker's grain/veg, Childless's crop, and any future "you must pick one of N"
effect. Its legal actions are exactly the options (a `CommitCardChoice(index)` per option) with **no
`Stop`/decline**, so the player must pick one; a single-option frame auto-resolves via singleton-skip.
It is the same shape as the harvest commits (`CommitConvert`/`CommitBreed` — mandatory, choose the
parameters, no decline), just made reusable across cards.

```python
# pending.py
@dataclass(frozen=True)
class PendingCardChoice:
    PENDING_ID: ClassVar[str] = "card_choice"
    player_idx: int
    initiated_by_id: str                  # "card:<id>" — which card pushed it (resolver dispatch)
    options: tuple = ()                   # tuple[Hashable, ...] — the choices, e.g. ("grain", "veg")
# actions.py: CommitCardChoice(index: int) picks options[index]; the pushing card's resolver
# (keyed on initiated_by_id's card) applies the chosen option.
```

One generic frame + a card-keyed resolver — no per-card frame. (Scholar may reuse this for its
occupation/minor route, depending on the enumeration choice in the open question below.)

## II.7 Per-card state store — `CardStore`

A few cards carry **persistent per-card state** beyond "played or not" — Tutor's snapshot, Moldboard
Plow's uses-left, later Grocer's goods stack. Two facts are tracked **separately**:

- **Which cards are played** stays as today: `occupations` / `minor_improvements` (frozensets of id
  strings) — fast membership, unchanged, already C++-mirrored. *Not touched.*
- **Per-card extra state** is one **sparse side-map per player**, `PlayerState.card_state: CardStore`,
  with an entry **only for the cards that store something.** A stateless card (the vast majority) has
  *no* entry — it exists solely as its id in the frozenset. (So it is *not* one object per played
  card; it's one map per player holding a handful of `(card_id, value)` pairs.)

`CardStore` is a hashable frozen-dataclass map (so `GameState` stays hashable for the transposition
table); being a frozen dataclass over a tuple field, the canonical serializer walks it with no
special-casing. Default empty → the Family game is inert.

```python
# state.py
@dataclass(frozen=True)
class CardStore:                          # PlayerState.card_state: CardStore = CardStore()
    items: tuple = ()                     # tuple[tuple[str, Hashable], ...], sorted by card_id
    def get(self, cid, default=None):
        for k, v in self.items:
            if k == cid: return v
        return default
    def set(self, cid, value) -> "CardStore":
        kept = tuple((k, v) for k, v in self.items if k != cid)   # drop old entry (one value per card)
        return CardStore(tuple(sorted(kept + ((cid, value),))))   # add, re-sort → canonical → stable hash
```

**Values are heterogeneous** — an `int` for the common case, a card-specific frozen payload dataclass
for the rare complex case (no new container machinery for the complex ones):
- Tutor → `int` snapshot (`card_state.set("tutor", len(p.occupations))`).
- Moldboard Plow → `int` uses-left (set to 2 on play, decremented per use).
- Grocer / future complex cards → their own `frozen GrocerState(stack=…)` as the value.

**Why a side-map** (vs. the alternatives weighed in design): a *positional list* is rigid and awkward
for sparse/heterogeneous data; *one object per played card* would replace the heavily-used id
frozensets (blast radius + lost `id in set` membership) and wrap every stateless card pointlessly;
*dedicated typed fields per card* are clean but leak card names into the schema and churn it per card.
The sparse `card_id → value` map leaves `occupations`/`minor_improvements` untouched and pays only for
the cards that carry state.

**Build now, defer payloads.** *(Status: `CardStore` + `int` values are LANDED — Tutor's snapshot, Big
Country's banked points, Moldboard Plow's uses-left all use the side-map.)* The typed payload shapes for
genuinely complex cards (`GrocerState`, …) are designed in the dedicated Grocer session
(`CARD_SYSTEM_DESIGN.md` §9) and slot into the same container without touching `PlayerState`'s schema
again.

---

# Part III — The cards, by category

Each category: the hook it uses, a **canonical worked example** (real card, real code grounded in
the engine), and the rest of the category as one-liners. Code reuses the helpers from Parts I–II.
(Module layout is **flat** — `agricola/cards/<id>.py`, as today (the game is always played with both
card types or neither, so there's no reason to split by type); the `cards/occupations/…` /
`cards/minors/…` paths in the examples are illustrative, not a directory split. Helpers shown bare —
e.g. `num_rooms`, `count_unfenced_stables` — are to-be-written derived-quantity functions, not
existing API.)

## Category 1 — End-game scoring terms (5)
**Stable Architect · Organic Farmer · Tutor · Manger · Wool Blankets**

Hook: a scoring registry summed by `scoring.score` into `bonus_points`.

```python
# scoring.py
SCORING_TERMS: list[tuple[str, Callable]] = []     # (card_id, fn); fn: (state, player_idx) -> int
def register_scoring(card_id, fn): SCORING_TERMS.append((card_id, fn))

# score(state, idx) gets a NEW ScoreBreakdown field `card_points` (kept separate from `bonus_points`,
# which is craft-building bonuses — don't conflate the two):
    card_points = sum(fn(state, idx) for card_id, fn in SCORING_TERMS
                      if _owns(state.players[idx], card_id))
```

**Canonical — Stable Architect** ("1 point per unfenced stable"):

```python
# cards/occupations/stable_architect.py
CARD_ID = "stable_architect"
def _score(state, idx):
    return count_unfenced_stables(state.players[idx].farmyard)   # derive from farmyard, no new state
register_scoring(CARD_ID, _score)
```

**Tutor** ("1 point per occupation played after this one") needs the *count at play time*, stored as
an `int` in the per-card **`CardStore`** side-map (II.7): `on_play` does
`card_state.set("tutor", len(p.occupations))`, and the scoring term returns
`len(p.occupations) − 1 − snapshot`. **Manger / Wool Blankets** are pure derived reads (pasture
coverage, house material) — register a `_score` like Stable Architect, no stored state.
**Organic Farmer is deferred** (see "Deferred cards"): animals are aggregate counts, so its `_score`
must compute the *arrangement-maximizing* assignment of animals to pastures (each qualifying pasture
needs ≥1 animal + ≥3 unused capacity, i.e. capacity ≥ 4 with few animals in it) — a non-trivial
optimization — and the end-game "remove animals to free capacity" play needs the deferred
before-scoring conversion phase (Sheep Walker; `CARD_SYSTEM_DESIGN.md` §7).

## Category 2 — On-play one-shot effects (9 + 1 deferred)
**Consultant · Priest · Roof Ballaster · Big Country · Bottles · Clay Embankment · Market Stall · Young Animal Market · Shifting Cultivation** (Mini Pasture deferred)

Hook: the `on_play` callback dispatched by `_execute_play_{occupation,minor}` (II.4). Of the 9 built
here, **four** are passing minors (also circulate): Clay Embankment, Market Stall, Young Animal Market,
Shifting Cultivation. **Shifting Cultivation** composes a primitive on play (push `PendingPlow`).
(The deferred Mini Pasture is the 5th passing minor and the other primitive-composer — a free
`PendingBuildFences` — see Deferred cards.)

**Canonical — Priest** (conditional immediate gain):

```python
# cards/occupations/priest.py — on_play(state, idx) -> GameState
def on_play(state, idx):
    p = state.players[idx]
    if p.house_material == HouseMaterial.CLAY and num_rooms(p) == 2:
        p = fast_replace(p, resources=p.resources + Resources(clay=3, reed=2, stone=2))
        state = _update_player(state, idx, p)
    return state
```

**Roof Ballaster** ("when played, you *may* pay **1 food total** to get **1 stone per room**") is an
*optional* on-play effect — all-or-nothing (1 food → `num_rooms` stone, or nothing). Model it as a
**play-variant**, like Cooking Hearth's return-fireplace options in `CommitBuildMajor`: playing Roof
Ballaster surfaces *two* play-actions — with-conversion (only when food ≥ 1) and without — and
`on_play` reads the chosen variant. No trigger, no extra frame, and the choice is resolved as part of
the play action. (This is the clean fit for *optional, play-time* effects; contrast the *mandatory,
hook-time* choices in II.1's forced-choice category.)

**Shifting Cultivation** `on_play` = `push(state, PendingPlow(player_idx=idx,
initiated_by_id="card:shifting_cultivation"))`. **Market Stall / Young Animal Market** are the
play-cost-as-exchange pattern (cost `1 grain`/`1 sheep`, `on_play` gains `1 veg`/`1 cattle`) +
passing. **Mini Pasture** is **deferred** (see "Deferred cards" — `PendingBuildFences` has no
cap/free/size fields today, and its "fence a space" semantics need a ruling).

## Category 3 — Action-space hook, automatic income (all built)
**Wood Cutter · Geologist · Canoe · Corn Scoop · Loam Pit · Stone Tongs · Pitchfork** (`register_auto`
on the space's before/after event). **Seasonal Worker** (Unit 4) is NOT a plain auto-effect — it is a
**mandatory-with-choice** trigger on the Day Laborer host (II.1): +1 grain each use, or +1 veg from
round 6, the choice surfaced as a round-dependent `PendingCardChoice`. **Firewood Collector** (Unit 4)
lands on the dedicated **`end_of_turn`** event (fired at the turn-completion boundary in `_apply_stop`),
no longer deferred.

Hook: `register_auto` on `before_action_space` (or `after_action_space` for post-work income),
filtered by `space_id`.

**Canonical — Wood Cutter** ("+1 wood each time you use a wood accumulation space"):

```python
# cards/occupations/wood_cutter.py
CARD_ID = "wood_cutter"
WOOD_SPACES = frozenset({"forest"})        # plus any future wood-accumulation ids; category filter

def _eligible(state, idx):
    # When a before_action_space trigger is consulted, the top frame is the space-host (atomic →
    # PendingActionSpace; non-atomic → its per-space frame). Read the space via the uniform `space_id`
    # property (every space-host frame has it) — do NOT `isinstance` against PendingActionSpace.
    return state.pending_stack[-1].space_id in WOOD_SPACES

def _apply(state, idx):
    p = state.players[idx]
    return _update_player(state, idx, fast_replace(p, resources=p.resources + Resources(wood=1)))

register_auto("before_action_space", CARD_ID, _eligible, _apply)
# also at registration: add CARD_ID to OWN_ACTION_HOOK_CARDS["forest"] (II.2) — so the host frame pushes
# on the owner's Forest use (the two indexes are built from mutable sets at registration, then frozen).
```

Order note: "+1 wood" is mandatory and order-independent of the accumulation pickup, so before vs
after doesn't matter — register on `before`. **Seasonal Worker** is a **mandatory-with-choice** trigger
(II.1), not a plain auto-effect: firing it pushes a `PendingCardChoice` whose options are
round-dependent — `[grain]` pre-round-6 (a singleton → auto-resolves to +1 grain) and `[grain, veg]`
from round 6 (the player picks) — and the Day Laborer hook's phase-exit is gated until it fires.
**Pitchfork** adds an eligibility clause (`get_space(state.board,"farmland").workers != (0,0)`).

## Category 4 — Action-space hook, granted sub-action (5)
**Oven Firing Boy · Assistant Tiller · Cottager · Threshing Board · Moldboard Plow**

Hook: a card-granted sub-action is an **optional trigger** (`register` — **not** `register_auto`)
whose `apply_fn` **pushes an existing primitive pending** — "grants a sub-action"
(`CARD_SYSTEM_DESIGN.md` §0, which calls it "mechanically a trigger"). **All of Category 4 are
triggers, full stop** — a grant is a choice the player may take, which is what a trigger *is*; it's
the correct model whether or not the sub-action is resolvable. Several reasons reinforce this (none is
the whole story on its own):
- **Player optionality.** Using the granted sub-action is the player's choice — a trigger they fire
  or decline; an auto-effect has no natural "decline."
- **Legality gating.** A trigger's *eligibility* can check the granted sub-action is actually
  resolvable, so we never push a dead-end pending (e.g. an extra Bake Bread with no grain — a frame
  whose only move is `Stop`).
- **Re-entrancy.** An auto-effect that pushed a frame would hit the trap II.1 avoids (a later
  auto-effect in the same `apply_auto_effects` loop would run *before* the player resolves the pushed
  frame); the trigger loop resolves the pushed primitive, then re-enumerates.

Firing the trigger (= taking the granted action) pushes the primitive; *not* firing = declining the grant.

**Canonical — Oven Firing Boy** ("each wood-accumulation use, an additional Bake Bread action"):

```python
# cards/occupations/oven_firing_boy.py
def _eligible(state, idx, triggers_resolved):    # 3-arg; once per space-use AND only when a bake is usable
    p = state.players[idx]
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in WOOD_SPACES
            and _can_bake_bread(state, p))       # gate on usability — never grant an unresolvable sub-action

def _apply(state, idx):
    return push(state, PendingBakeBread(player_idx=idx, initiated_by_id="card:oven_firing_boy"))

register("after_action_space", CARD_ID, _eligible, _apply)   # a TRIGGER (register), not register_auto
```

The bonus bake rides on the existing `PendingBakeBread` primitive — including Potter Ceramics firing
*inside* it, for free, because the trigger machinery is unchanged. **Assistant Tiller / Cottager**
push `PendingPlow` / a build-or-renovate primitive on the Day Laborer hook (Cottager pays the normal
build cost — clean today; entangled only once cost-mod cards exist, per §8). **Moldboard Plow** is
twice-per-game: store uses-left as an `int` in the `CardStore` side-map (II.7) — `_apply` reads
`card_state.get("moldboard_plow", 2)`, grants the plow when it's > 0, and decrements it.

## Category 5 — Build / renovate / fence / card-play hooks (5)
**Roughcaster · Junk Room · Mining Hammer · Bread Paddle · Dutch Windmill** (Shepherd's Crook deferred)

> **Status: DONE** (`tests/test_cards_category5.py`; full suite + C++ gates green). All five cards
> landed: Roughcaster (occupation), Junk Room / Mining Hammer / Bread Paddle / Dutch Windmill (minors).
> Engine wiring: the coarse `after_build_improvement` event is fired by both `_execute_build_major` and
> `_execute_play_minor` (Junk Room); `after_build_rooms` is fired once per build-rooms session at the
> session-ending `Stop` in `_apply_stop` (Roughcaster's clay-room clause — a clay *room* is built via the
> build-rooms primitive, not via build-major/play-minor, so it rides `after_build_rooms`, NOT the coarse
> `after_build_improvement` the canonical sketch below mentions). `after_renovate` / `after_bake_bread` /
> `after_play_occupation` come for free from the `after_<PENDING_ID>` host-pivot convention. All wiring is
> a no-op in the Family game (empty `AUTO_EFFECTS`/`TRIGGERS`) → byte-identical → no C++ change.

Hook: events fired by the build/renovate/fence/play primitives. Each sub-action frame's event
**derives from its `PENDING_ID`** (II.2) — `before_/after_renovate`, `_build_major`, `_bake_bread`, …
(no stored `TRIGGER_EVENT`). To fire a card *after* the effect, add the `phase` field for after-timing
(per the II.2 changes) and call `apply_auto_effects(state, f"after_{pending_id}", idx)` at the matching
point in the primitive's `_execute_*`. **One exception below:** Junk Room's `after_build_improvement`
is a **coarse hand-fired event** (like `action_space`) that *both* `_execute_build_major` *and*
`_execute_play_minor` fire — it deliberately spans "any improvement built," so it doesn't follow the
per-`PENDING_ID` rule.

**Canonical — Junk Room** ("each time after you build an improvement, +1 food"):

```python
# cards/minors/junk_room.py — automatic, on the improvement-built hook
def _apply(state, idx):
    p = state.players[idx]
    return _update_player(state, idx, fast_replace(p, resources=p.resources + Resources(food=1)))
register_auto("after_build_improvement", CARD_ID, _always_eligible, _apply)
# _execute_build_major / _execute_play_minor call apply_auto_effects(state,"after_build_improvement",idx)
```

**Roughcaster** = `after_build_improvement` auto-effect filtered to clay-room-build / clay→stone-renovate
(+3 food). **Mining Hammer** = on the renovate hook, *grants* a free stable (push `PendingBuildStables`,
cost `Resources()`, cap 1) — a **trigger** (Category-4 shape: grants push a primitive, so they're
triggers, not auto-effects) on a build hook. **Bread Paddle** = a **trigger** on `after_play_occupation`
that grants a Bake Bread. **Dutch Windmill** = on `after_bake_bread`, +3 food
gated on `round_number in {5,8,10,12,14}` (stateless). **Shepherd's Crook** is **deferred** (see
Deferred cards — its ≥4-pasture condition must be evaluated on the *net* result of the whole Build
Fences action, not per-`CommitBuildPasture`).

## Category 6 — Harvest-field hook (4)
**Scythe Worker · Butter Churn · Three-Field Rotation · Loom**

> **Status: DONE** (`tests/test_cards_category6.py`; full suite + C++ gates green). The
> `PendingHarvestField` host frame (`pending.py`) + a registration-time ownership index
> (`HARVEST_FIELD_CARDS` / `should_host_harvest_field` in `cards/triggers.py`) + the firing site
> (`_fire_harvest_field_hook`, called at the TOP of `_resolve_harvest_field` before the mechanical
> crop take) landed. The push is **card-dependent** (`should_host_harvest_field`): the Family game owns
> no harvest-field card → no frame pushed → the field resolution is byte-identical and the C++
> Family-only engine never sees the frame (NO C++ change). All four cards `register_auto` on the
> `harvest_field` event; Scythe Worker also has the Category-2 on-play +1 grain and Loom a Category-1
> scoring term (1 bonus point per 3 sheep). Firing *before* the take is load-bearing for Scythe Worker
> (it reads the still-sown grain fields) and Three-Field Rotation (its grain/veg/empty-field condition).

Hook: `PendingHarvestField` (II.6), event `harvest_field`. All automatic.

**Canonical — Loom** ("field phase: 1/2/3 food at ≥1/4/7 sheep" + a scoring term):

```python
# cards/minors/loom.py
def _apply(state, idx):
    sheep = state.players[idx].animals.sheep
    food = 3 if sheep >= 7 else 2 if sheep >= 4 else 1 if sheep >= 1 else 0
    p = state.players[idx]
    return _update_player(state, idx, fast_replace(p, resources=p.resources + Resources(food=food)))
register_auto("harvest_field", CARD_ID, _always_eligible, _apply)

def _score(state, idx):                         # the second clause: +1 VP per 3 sheep
    return state.players[idx].animals.sheep // 3
register_scoring(CARD_ID, _score)
```

`_resolve_harvest_field` calls `apply_auto_effects(state, "harvest_field", idx)` for each player
*before* the mechanical crop take. **Scythe Worker** also has an `on_play` +1 grain (Category 2
shape) plus its field-phase +grain-per-grain-field here. **Butter Churn / Three-Field Rotation** are
plain `harvest_field` auto-effects.

## Category 7 — Start-of-round phase (6)
**Small-scale Farmer · Childless · Scullery · Groom · Plow Driver · Scholar**

Hook: `PendingPreparation` (II.6), event `start_of_round`. Auto-effects fire immediately; triggers
surface as `FireTrigger`. Conditional cards gate on house material / room count; round budgets use
`used_this_round`.

**Canonical — Plow Driver** (trigger: "once in stone house, at round start pay 1 food to plow 1
field" — a fixed-price granted sub-action, not a cost-modifier):

```python
# cards/occupations/plow_driver.py
def _eligible(state, idx, triggers_resolved):
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.house_material == HouseMaterial.STONE
            and p.resources.food >= 1)

def _apply(state, idx):                          # charge 1 food, grant the plow primitive
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1),
                        used_this_round=p.used_this_round | {CARD_ID})
    state = _update_player(state, idx, p)
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:plow_driver"))

register("start_of_round", CARD_ID, _eligible, _apply)
```

**Groom** is the same shape granting a free stable (push `PendingBuildStables`, cost
`Resources(wood=1)`, cap 1). **Small-scale Farmer / Scullery** are auto-effects (`register_auto`)
gated on room-count / wooden-house. **Childless** is a **mandatory-with-choice** trigger (II.1):
eligible when its rooms/people condition holds, it applies +1 food and pushes a `PendingCardChoice`
for the grain/veg crop (phase-exit gated until resolved). **Scholar** lets you play an occupation
(1 food) *or* a minor (printed cost), enumerated as a **collapsed play-variant**: the start-of-round
frame surfaces `FireTrigger("scholar", variant="occupation")` (when a hand occupation is playable +
you have 1 food) and `FireTrigger("scholar", variant="minor")` (when a hand minor is playable), with
"do neither" = `Proceed`. So `FireTrigger` gains an optional **`variant`** field (default `None`,
backward-compatible); Scholar's `apply_fn(state, idx, variant)` pushes
`PendingPlayOccupation(cost=Resources(food=1))` or `PendingPlayMinor` accordingly. This drops the
intermediate route-choice node (the route is chosen *at* the fire) and keeps the two standard
play-card pendings. The hardest of this category — it needs the full II.4 play-card foundation.

## Category 8 — Deferred goods / effects on round spaces (10)
**Wall Builder · Manservant · Clay Hut Builder · Pond Hut · Large Greenhouse · Strawberry Patch · Sack Cart · Thick Forest · Herring Pot · Handplow** (Acorns Basket deferred)

Hook: schedule into `FutureReward` slots (II.5). Collected/accommodated/fired at round start.

**Canonical — Wall Builder** ("each room build, place 1 food on the next 4 round spaces"):

```python
# cards/occupations/wall_builder.py — automatic, on the room-built hook
def _apply(state, idx):
    p = state.players[idx]
    slots = list(p.future_resources)
    for r in range(state.round_number, min(state.round_number + 4, 14)):   # next 4 rounds
        slots[r] = fast_replace(slots[r], resources=slots[r].resources + Resources(food=1))
    return _update_player(state, idx, fast_replace(p, future_resources=tuple(slots)))
register_auto("after_build_room", CARD_ID, _always_eligible, _apply)
```

**Acorns Basket** is **deferred** (see Deferred cards — it's the only deferred-goods card that
schedules *animals*, forcing round-start accommodation). **Handplow** schedules
`effect_card_ids={"handplow"}` 5 rounds out; its round-start hook pushes `PendingPlow` (the exotic
effect case). **Manservant / Clay Hut Builder** schedule once,
gated on a house-material **one-shot conditional latch** (`fired_once` + `_fire_ready_one_shots`,
§6). The rest (Pond Hut, Large Greenhouse, Strawberry Patch, Sack Cart, Thick Forest, Herring Pot)
are plain goods schedules differing only in which rounds and which good.

## Category 9 — Opponent-action hook (1)
**Milk Jug** ("each time *any* player uses Cattle Market, you get 3 food; the other gets 1")

Hook: the Cattle Market space-host frame — **`PendingCattleMarket`** (Cattle Market is *non-atomic*,
so it keeps its per-space frame; **not** a `PendingActionSpace`) — firing the `after_action_space`
event for its **owner** even on the opponent's turn.

```python
# cards/minors/milk_jug.py
def _eligible(state, idx):                       # idx = the owner (any player), not necessarily active
    return state.pending_stack[-1].space_id == "cattle_market"   # `space_id` works on any space-host frame

def _apply(state, idx):                          # owner +3; the other player +1 (the printed effect)
    other = 1 - idx
    state = _update_player(state, idx,   fast_replace(state.players[idx],
                              resources=state.players[idx].resources + Resources(food=3)))
    state = _update_player(state, other, fast_replace(state.players[other],
                              resources=state.players[other].resources + Resources(food=1)))
    return state

register_auto("after_action_space", CARD_ID, _eligible, _apply, any_player=True)
# registration also adds CARD_ID to ANY_PLAYER_HOOK_CARDS["cattle_market"] (II.2), so the host frame
# is pushed on EITHER player's Cattle Market turn; `any_player=True` then runs _apply for the OWNER.
```

This is the first card needing the any-player host tag + per-owner routing (`CARD_SYSTEM_DESIGN.md`
§5); the structure is kept open by II.2's owner-indexed `_should_host_space`.

## Category 10 — Bounded-hook conversion, now-or-never (2)
**Mushroom Collector · Basket**

Hook: an optional **trigger** on the wood-accumulation `after_action_space` event. These convert
wood→food but *only* immediately after a wood space, so they never enter the §15 affordability
closure (see `CARD_SYSTEM_DESIGN.md` §8) — they are plain `FireTrigger` options.

**Canonical — Mushroom Collector** ("immediately after a wood-accumulation use, you may exchange 1
wood for 2 food"):

```python
# cards/occupations/mushroom_collector.py
def _eligible(state, idx, triggers_resolved):
    if CARD_ID in triggers_resolved:
        return False
    # Registered on after_action_space, so it's only consulted in the after-phase at a space-host
    # frame; read the space via the uniform `space_id` (no isinstance — wood spaces are atomic here,
    # but the pattern must hold for non-atomic spaces too).
    return state.pending_stack[-1].space_id in WOOD_SPACES and state.players[idx].resources.wood >= 1

def _apply(state, idx):
    p = state.players[idx]
    return _update_player(state, idx,
        fast_replace(p, resources=p.resources + Resources(wood=-1, food=2)))

register("after_action_space", CARD_ID, _eligible, _apply)
```

**Basket** is identical with `Resources(wood=-2, food=3)` and a `wood >= 2` guard.

---

# Deferred cards (do these last)

A few cards in this doc's scope need machinery that's heavier or under-specified enough to push to
the **end** of the implementation, after the rest are working — potentially under the maintainer's
guidance. They are not in the hard/§15 set (no affordability reachability), just costly here:

- **Organic Farmer** (scoring). Animals are aggregate counts, so its `_score` must compute the
  *point-maximizing assignment* of animals to pastures (a qualifying pasture needs ≥1 animal + ≥3
  unused capacity → capacity ≥ 4 with few animals in it). That optimization is non-trivial; defer it.
  The decision is **auto-compute the optimal arrangement** (no player choice — the lean) vs. surface
  it as a player decision. Related: the **before-scoring conversion phase** (`PendingBeforeScoring`,
  `CARD_SYSTEM_DESIGN.md` §7) — needed only for *removing* animals at end-game (Sheep Walker), itself
  deferred — so the whole end-game-animal story moves here as one unit.
- **Mini Pasture** (fencing). `PendingBuildFences` has **no** cap / free-cost / size fields today, so
  Mini Pasture's "fence one farmyard space, free" needs new constraints (1 pasture max, skip the wood
  debit, 1-cell shapes only) *or* a dedicated thin path that reuses the fence-universe legality. Plus
  a **ruling**: does "fence a farmyard space" allow *subdividing* an existing pasture into a 1-cell,
  or only enclosing a previously-unenclosed cell (adjacent to existing)? Pin before building.
  (From the text of the card, "If you already have pastures, the new one must be adjacent to an
  existing one". This resolves the ruling.)

- **Shepherd's Crook** (fence hook). "Each time you fence a *new* pasture covering ≥4 spaces, get 2
  sheep on it" must be evaluated on the **net result of the whole Build Fences action, not
  per-`CommitBuildPasture`** — because splitting a rules-atomic action into commits is a *tractability*
  artifact, and a card keying on the action must see it as the rules do. Per-commit firing is wrong:
  building a 2×2 then subdividing it within the same action nets to no new ≥4 pasture, so it must
  **not** fire (a per-commit hook would wrongly fire on the 2×2). **Approach:** snapshot the pastures
  when the Build Fences action *starts* (push of the fence pending), diff against the pastures when it
  *ends* (`Stop`), and fire for each genuinely-new ≥4 pasture in that net diff. Needs a pre-action
  pasture snapshot on the fence frame + an end-of-action diff — heavier than the simple hooks, hence
  deferred. (General principle for whoever implements: rules-atomic actions we split for tractability
  should fire card effects on the net, at action-end.)
- **Acorns Basket** (deferred goods → animals). The only deferred-goods card that schedules *animals*
  rather than goods/food, so it forces `FutureReward.animals` **and round-start accommodation**: when
  the boar is collected at round start it must be housed, and on overflow the player needs the
  release/convert Pareto frontier — which today lives only on the animal-market frames, so it's a
  net-new decision point in the otherwise decision-free preparation phase. **Approach:** reuse the
  existing accommodation machinery (`pareto_frontier` / `can_accommodate`) via a *generic* accommodate
  frame pushed from `_complete_preparation` on overflow; the common case (room available) auto-places
  with no decision. Deferred to keep the first deferred-goods pass goods/food-only.

(Sheep Walker and the other §15 conversion cards remain out of scope entirely — see
`CARD_SYSTEM_DESIGN.md` §15; the before-scoring phase is the shared infrastructure they'd need.)

---

# Build order

Front-load the shared infrastructure. The ordering constraint that matters: **nothing is testable
until a card can be played at all**, so the play-card foundation (II.4) comes early, *before* the
hook categories — not after.

1. **Part I — DONE.** The `GameMode` field + mode-branched placement (I.1), Side Job (absent in
   cards) / Meeting Place (slot-reused, mode-branched) / Lessons (I.2–I.4), private hands on
   `PlayerState` (I.5), setup-by-mode (I.6). Family game byte-identical; C++ gates green (default-skip).
2. **Play-card foundation — DONE** (`CardStore` deferred until a card needs it). `PendingPlayOccupation`
   (Lessons) + `PendingPlayMinor` across **all four entry points** (Major/Minor Improvement, House
   Redevelopment, Basic Wish — mirrored on House Redev via a `PendingFamilyGrowth` primitive — and
   Meeting Place) + enumeration + resolution (II.4). With the Category-1 scoring registry and the
   Category-2 `on_play` dispatch, **Categories 1 (scoring) and 2 (on-play) are testable end-to-end**;
   four cards landed (Consultant, Priest, Stable Architect, Market Stall).
3. **Firing registries — DONE.** `register_auto`/`apply_auto_effects` + `AUTO_EFFECTS`/`AutoEntry`/`_owns`
   (II.1, automatic-effect path), scoped used-sets `used_this_turn`/`used_this_round`/`fired_once` +
   `engine._clear` + wiring (II.3). Pure-additive; Family byte-identical; C++ gates green. (The third
   firing kind — the `mandatory`-tagged trigger — is deferred to its phase-exit-gate consumer, step 4/6.)
4. **`PendingActionSpace` hook — DONE** (II.2) — landed in two slices (4a + 4b), plus the sub-action hook refactor and space-host refactor which completed the full uniform host model:
   - **4a — atomic-space host: DONE.** The generic `PendingActionSpace` frame + `Proceed` action +
     conditional-push lifecycle in `_apply_place_worker` + `_apply_proceed` + the `should_host_space`
     hosting indexes (`OWN_/ANY_PLAYER_HOOK_CARDS` + `register_action_space_hook`) + `trigger_event`
     routing/bucket + the `_enumerate_pending_action_space` enumerator. The host frame is pushed ONLY
     for atomic spaces when a hooking card is owned, so it never appears in a Family game and the C++
     (Family-only) engine never sees it — **zero existing-frame changes, zero C++ changes, Family
     byte-identical.** Cards landed: **Category 3** automatic-income on atomic spaces — Wood Cutter,
     Geologist (occ); Corn Scoop, Stone Tongs, Pitchfork (minor). The FireTrigger path at the host is
     validated by a synthetic test card.
   - **4b — non-atomic-space hosts + C++ sync: DONE** (via the space-host refactor,
     `SPACE_HOST_REFACTOR.md`). The existing space-host parent frames gained `phase`, `triggers_resolved`,
     and a `space_id` property; their per-frame `TRIGGER_EVENT` ClassVars were dropped; event routing
     goes through `trigger_event`'s `PENDING_ID` bucket; `PendingFarmland`/`PendingFencing` were folded
     into the new `PendingSubActionSpace` (Delegating); the Proceed-host frames (`PendingGrainUtilization`,
     `PendingCultivation`, `PendingFarmExpansion`, `PendingHouseRedevelopment`, `PendingFarmRedevelopment`)
     gained `phase` and explicit `Proceed` boundaries; Meeting Place was renamed `PendingMeetingPlace` as
     a single-optional Proceed-host; after-auto firing migrated out of `_apply_stop` (now pure-pop) to
     each host's work-complete boundary; 9 Family-reachable frames C++-synced; full suite + all C++
     differential gates green. Unlocks **Category 4** (granted sub-actions), **5** (build/renovate
     hooks), **9** (Milk Jug, already landed). `PendingBasicWishForChildren` was converted to a
     Proceed-host (and-then) as a follow-up commit after 4b (card-only, no C++ mirror required;
     `basic_wish_for_children` added to `ACTION_SPACE_PENDING_IDS`; card-hook test added).
   - **Category 10** (Mushroom Collector, Basket) rides 4a's atomic-host trigger path — but both cards
     say *"place the [exchanged] wood on the accumulation space"*, which the Category-10 sketch code in
     Part III omits; implement the wood-return faithfully (the spent wood goes back onto the space, not
     to general supply).
5. **`FutureReward`** (II.5) — Category 8 (deferred goods).
6. **Phase hooks** — `PendingPreparation`, `PendingHarvestField`, `PendingCardChoice` (II.6) —
   Categories **7 (start-of-round)** and **6 (harvest-field)**.
7. **Deferred cards** (Organic Farmer, Mini Pasture, Shepherd's Crook, Acorns Basket) last.

**`CardStore` (II.7) + leftovers — DONE.** The sparse, hashable per-player side-map
`PlayerState.card_state: CardStore` (sorted `(card_id, value)` tuple + `get`/`set`); card-only (added
to the manual `PlayerState.__hash__` AND canonical's `_DEFAULT_SKIP_FIELDS`; the canonical walker
serializes it generically) → Family byte-identical → **no C++ change** (138 differential gates green
untouched). Cards landed: **Tutor** (Cat 1, snapshot + scoring), **Big Country** (Cat 2, immediate food
+ banked points; prereq "all spaces used"), **Moldboard Plow** (Cat 4, twice-per-game granted Farmland
plow with uses-left), **Roof Ballaster** (Cat 2, optional pay-1-food→1-stone-per-room via a new
play-VARIANT mechanism: `specs.PLAY_OCCUPATION_VARIANTS` + `CommitPlayOccupation.variant`),
**Shifting Cultivation** (Cat 2 traveling, `on_play` pushes `PendingPlow`). The play-minor flip order in
`_execute_play_minor` was reordered to flip the host to `phase="after"` BEFORE `on_play` runs (like the
oven case), so a pushing `on_play` lands its primitive on the already-flipped host and unwinds cleanly.

Each card is then a single small module registering into the relevant registry, mirroring
`cards/potter_ceramics.py`, and added to `cards/__init__.py` so its `register*()` calls fire at
import.

---

# Decisions & open sub-questions

**Settled (this session):**
- **Mode (I.1):** an explicit `GameMode` field on `GameState`; code card mode directly and
  branch / split functions where Family and card diverge (Family branch = today's code). Not an
  elegant-subset abstraction.
- **Hands (I.5):** both players' hands concrete on `PlayerState`; `step`/`legal_actions` stay pure
  functions of `GameState`; hidden info handled above the engine by ISMCTS determinization.
  *(This supersedes `CARD_SYSTEM_DESIGN.md` §2's "hands live in the Environment" wording — now
  reconciled in that doc's §2.)*
- **Action-space hook events (II.2):** a coarse `before_/after_action_space`, routed by a
  `PENDING_ID` bucket (all space-host frames share the `action_space` base; sub-action frames keep
  `<PENDING_ID>`). Non-atomic spaces keep their per-space frames (not wrapped, not dissolved); the
  generic `PendingActionSpace` is for atomic spaces only. Revises `ENGINE_IMPLEMENTATION.md`
  invariant 9 (already updated there).
- **Per-card state (II.7):** a sparse hashable `CardStore` side-map on `PlayerState` — `int` values
  for the common case (Tutor snapshot, Moldboard uses) now, typed payloads (Grocer) deferred to §9.
  The played-card frozensets are unchanged.
- **Lessons occupation cost (II.4):** 2-player rule — the **first occupation is free, every later one
  costs 1 food** (`occupation_cost`). Scholar is a flat 1 food via its own route. (This is a
  card-game rule, *not* in `RULES.md`, which is Family-only.)

**Open sub-questions (none block starting the engine work):**
1. **`observe` cardinality + passing-minor count bookkeeping (I.5)** — preserve the opponent's hand
   *count* (public) while hiding identities; account for passes. Search/`observe`-layer only.
