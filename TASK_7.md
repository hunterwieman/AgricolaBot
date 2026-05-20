# Task 7 — Harvest Phases and Rounds 5–14

This task implements the three harvest sub-phases — HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED — and unblocks rounds 5–14. After this task lands, the engine runs a complete Family game from `setup` to `Phase.BEFORE_SCORING` without halting; the only piece between a finished engine and a fully-playable game is the existing `scoring.py` (already in place).

The document is ordered top-down: engine architecture first, then state objects, then the resolution + legality machinery that drives each phase, then the algorithmic primitives those depend on, then integration glue and tests.

- **Part 1 — Preliminary refactor.** Extend `cooking_rates` to return a 4-tuple `(sheep, boar, cattle, veg)`. Three callers update mechanically.
- **Part 2 — Engine wiring & phase machine.** The full state machine for FIELD → FEED → BREED, `_advance_until_decision` extension, `_resolve_return_home` routing change, provenance prefix scheme for phase-driven pendings. The conceptual heart of the harvest.
- **Part 3 — Pendings, actions, and PlayerState changes.** Two new pending dataclasses (`PendingHarvestFeed`, `PendingHarvestBreed`), three new `Action` types (`CommitHarvestConversion`, `CommitConvert`, `CommitBreed`), the `harvest_conversions_used` field on `PlayerState`, and the `PendingDecision` / `Action` union updates.
- **Part 4 — Resolution functions.** `_resolve_harvest_field` (mechanical FIELD work + push + transition), `_initiate_harvest_feed` / `_initiate_harvest_breed` (pending-push helpers), `_execute_harvest_conversion`, `_execute_convert`, `_execute_breed`.
- **Part 5 — Legality enumerators.** `_enumerate_pending_harvest_feed`, `_enumerate_pending_harvest_breed`.
- **Part 6 — Helpers and registries.** `food_payment_frontier` (Pareto frontier of food-payment configs — usable wherever a card or action requires paying food), `harvest_feed_frontier` (harvest-specific wrapper that adds the begging dimension), `HARVEST_CONVERSIONS` registry paralleling the existing card-`TRIGGERS` registry.
- **Part 7 — Dispatch wiring and setup glue.** `COMMIT_SUBACTION_HANDLERS` additions and `setup` update.
- **Part 8 — Tests.**
- **Part 9 — Documentation.**
- **Part 10 — Order of work.** (Implementation sequence is bottom-up — cooking_rates → state-object types → helpers → resolution → legality → engine wiring. The doc's narrative order and the implementation order are intentionally different.)
- **Part 11 — Acceptance criteria.**
- **Appendix A — Out of scope.**

After this task, `random_agent_play` runs end-to-end from `setup` to `Phase.BEFORE_SCORING` over all 14 rounds, with all 6 harvests resolved.

---

## Scope

| Component | Status |
|---|---|
| `agricola/helpers.py` — `cooking_rates` extended to 4-tuple; `food_payment_frontier`, `harvest_feed_frontier` added | extended |
| `agricola/state.py` — `PlayerState.harvest_conversions_used: frozenset[str] = frozenset()` added | extended |
| `agricola/setup.py` — passes `harvest_conversions_used=frozenset()` to `_make_player` | extended |
| `agricola/cards/harvest_conversions.py` — `HARVEST_CONVERSIONS` registry, `HarvestConversionSpec` dataclass, `register_harvest_conversion` (paralleling `cards/triggers.py`) | new |
| `agricola/actions.py` — `CommitHarvestConversion`, `CommitConvert`, `CommitBreed`, all added to `Action` union | extended |
| `agricola/pending.py` — `PendingHarvestFeed`, `PendingHarvestBreed`, added to `PendingDecision` | extended |
| `agricola/legality.py` — `_enumerate_pending_harvest_feed`, `_enumerate_pending_harvest_breed`, both registered in `PENDING_ENUMERATORS` | extended |
| `agricola/resolution.py` — `_execute_harvest_conversion`, `_execute_convert`, `_execute_breed`, registered in `COMMIT_SUBACTION_HANDLERS` | extended |
| `agricola/engine.py` — `_advance_until_decision` extended with three harvest-phase branches; `_resolve_return_home` routes to HARVEST_FIELD on HARVEST_ROUNDS; new `_resolve_harvest_field` (mechanical + push FEED pendings + phase transition), `_initiate_harvest_feed`, `_initiate_harvest_breed` | extended |
| `tests/test_harvest_field.py` | new |
| `tests/test_harvest_feed.py` | new |
| `tests/test_harvest_breed.py` | new |
| `tests/test_harvest_integration.py` — end-to-end multi-round, multi-harvest scenarios; random-agent extension to rounds 5–14 | new |
| `tests/test_helpers.py` — update `cooking_rates` tests for the 4-tuple; new tests for `food_payment_frontier` and `harvest_feed_frontier` | extended |
| `tests/test_utils.py` — `IMPLEMENTED_NON_ATOMIC_SPACES` unchanged; `random_agent_play` now runs all 14 rounds (no other update needed — it already loops until `BEFORE_SCORING`) | extended |
| CLAUDE.md — Status table, harvest architecture narrative, provenance-prefix table, directory one-liners | updated |
| FILE_DESCRIPTIONS.md — per-file detail updates for every touched `agricola/*.py` and new module entry for `cards/harvest_conversions.py` | updated |
| TEST_DESCRIPTIONS.md — entries for the four new harvest test files; updates to the `test_helpers.py` entry | updated |
| CHANGES.md — new entry covering the 4-tuple cooking_rates refactor and the harvest architecture | updated |

**Out of scope** (deferred to future tasks):

- Card triggers on harvest pendings (`triggers_resolved` / `TRIGGER_EVENT` fields). Added per-pending when the first card needs them, following the Task 5D precedent.
- Cards beyond Potter Ceramics. The harvest-conversion registry is built to accept future card-supplied entries (e.g., Stone Sculptor), but no new card is implemented in this task.
- Compound card interactions (e.g., a card whose food yield enables another card's eligibility within FEED).
- Atomic-space trigger hosting (already deferred in Task 5C / Task 6).
- The `Resources`-can-go-negative scenario. Pre-debit + per-commit accounting ensures non-negative resource arithmetic throughout FEED. No `Resources` API change needed.

---

## Motivation

Harvest is the only phase in Agricola where the player makes strategic decisions outside the work phase. Three distinct sub-phases:

- **HARVEST_FIELD.** Mechanical. Take 1 crop from each planted field. No agent decisions; pure state transformation.
- **HARVEST_FEED.** Each adult requires 2 food; newborns from the just-ended round require 1 food. Players convert goods to food via three pathways (raw 1:1 grain/veg, cooking-improvement-mediated animal/veg conversion, and once-per-harvest craft conversions through Joinery / Pottery / Basketmaker's Workshop), and pay any shortfall with begging markers (−3 points each at scoring). The strategic surface is "which goods to convert in what order" plus "convert less and beg if preserving goods is worth more."
- **HARVEST_BREED.** Each animal type with ≥ 2 animals breeds (gains 1 newborn) if farm capacity allows. Players may eat or release animals immediately before breeding to alter the outcome. The existing `breeding_frontier` helper already enumerates Pareto-optimal post-breed configurations.

Two design rules shape this task:

**Gratuitous Stop for every player in every sub-phase.** Each player gets a pending frame in HARVEST_FEED and HARVEST_BREED, even when they have no meaningful decision (no convertibles, no breeding animals, no capacity issue). Three reasons:

1. Matches the engine's existing principle ("no auto-resolved singleton player decisions"). Trace uniformity for MCTS, replay, debugging.
2. Stable trigger-event hosts for cards. Cards like Conjurer ("at the breeding phase, +1 sheep"), Wood Distributor, "during feeding" effects need a pending frame to attach `before_*` / `after_*` events to. If the frame only exists for players-with-decisions, cards triggering from a 0-everything state would have nowhere to fire.
3. Symmetric with the parent-pending pattern that atomic spaces will eventually adopt for trigger-event hosting.

**Pareto frontier as the legality filter.** Rather than enumerating every (grain, veg, sheep, boar, cattle) tuple, `legal_actions` returns only the Pareto-optimal payment configurations. This collapses the action space from O(thousands) to O(tens) while preserving every strategically meaningful end-state, including partial-feed configurations where preserving grain (for sowing) or animals (for breeding) is worth the begging marker cost. Follows the precedent set by `pareto_frontier` (animal markets) and `breeding_frontier` (post-breed).

The "at any time" effects rule applies throughout: the player may only use cooking conversions when immediately beneficial (i.e., during FEED, not during work-phase actions). This is enforced structurally — cooking conversion only appears as a sub-action of `PendingHarvestFeed`, never elsewhere. Once-per-harvest crafts (Joinery / Pottery / Basketmaker) are exposed as binary yes/no decisions independent of food owed, since the use-it-or-lose-it nature means there's no future opportunity to preserve.

---
# Part 1 — Preliminary refactor: `cooking_rates` 4-tuple

## Change

`cooking_rates(state, player_idx)` currently returns `(sheep, boar, cattle)`. Extend to `(sheep, boar, cattle, veg)`:

```python
def cooking_rates(state: GameState, player_idx: int) -> tuple[int, int, int, int]:
    """Return (sheep_rate, boar_rate, cattle_rate, veg_rate) for at-any-time food conversion.

    Cooking Hearth (major idx 2 or 3) -> (2, 3, 4, 3)
    Fireplace      (major idx 0 or 1) -> (2, 2, 3, 2)
    Neither                           -> (0, 0, 0, 1)

    The veg rate has a 1:1 fallback (rules: "Grain and vegetables in personal supply
    count as 1 food each"). Animal rates have no such fallback — animals without a
    cooking improvement cannot be converted, so the rate is 0.
    """
```

The veg row is added per the rules: veg can always be converted at 1:1 even without a cooking improvement. Fireplace and Cooking Hearth raise the rate to 2 and 3 respectively (their at-any-time veg rates from the Major Improvement table).

## Callers to update

| Caller | Current use | After |
|---|---|---|
| `agricola/legality.py:1109` (`_enumerate_pending_X` — animal market) | `rates = cooking_rates(state, pending.player_idx)` then passes to `pareto_frontier(player_state, gained, rates)` | Unpack only first 3: `rates = cooking_rates(state, pending.player_idx)[:3]` (or destructure and slice). `pareto_frontier`'s signature stays `(sheep, boar, cattle)` — animal markets do not convert veg. |
| `agricola/resolution.py:1009` (`_execute_accommodate`) | Same shape | Same fix — slice to first 3. |
| `tests/test_helpers.py:384–417` (4 assertions) | `assert cooking_rates(state, 0) == (2, 3, 4)` etc. | Update to 4-tuple: `(2, 3, 4, 3)`, `(2, 2, 3, 2)`, `(0, 0, 0, 1)`. |

`pareto_frontier` and `breeding_frontier` both keep their 3-tuple `rates: tuple[int, int, int]` signature — neither converts veg, and changing them would couple unrelated code to a 4-tuple they don't use. The slicing happens at the two call sites that bridge from `cooking_rates` to those helpers.

A grep at implementation time for any other `cooking_rates(` call confirms the migration covers every site. The function is small and the callers are well-known, so this refactor is low-risk.

## Existing tests

All 520 pre-existing tests pass with the four updated assertions. No behavior change beyond the tuple width and the new 4th-element value.

---

# Part 2 — Engine wiring & phase machine

How the three harvest sub-phases (FIELD, FEED, BREED) integrate into the engine. The full state machine, the `_advance_until_decision` extension, and the `_resolve_return_home` routing change all live here. Subsequent parts drill into the state objects (Part 3), resolution functions (Part 4), legality enumerators (Part 5), and helper algorithms (Part 6) that this engine wiring depends on. The reader will encounter forward-references to `_resolve_harvest_field`, `_initiate_harvest_*`, `PendingHarvestFeed`, and `PendingHarvestBreed` here — these are defined in detail in later parts.

## 2.1 Phase semantics for the three harvest sub-phases

The three existing `Phase` values — `HARVEST_FIELD`, `HARVEST_FEED`, `HARVEST_BREED` — are sufficient. No new enum values are introduced.

The key design choice: **each `_resolve_*` phase resolver finishes its work by pushing the next phase's pendings and transitioning the phase value.** This mirrors `_resolve_preparation`, which already does six things (round_number, accumulation refill, future_resources distribution, newborn clear, current_player reset, phase=WORK) in one function. Combining "mechanical work" + "push pendings for next phase" + "set phase" keeps the phase semantics honest: when `phase == HARVEST_FEED`, the player is actively feeding (or the FEED frame on top has just been Stop'd to empty the stack — the exit signal).

The full state machine:

| Phase | Stack | What `_advance_until_decision` does |
|---|---|---|
| HARVEST_FIELD | empty | `_resolve_harvest_field`: mechanical FIELD work, reset `harvest_conversions_used`, push FEED pendings (via `_initiate_harvest_feed`), set `phase = HARVEST_FEED`. |
| HARVEST_FEED | non-empty | Outer guard returns. Player is deciding via `step`. |
| HARVEST_FEED | empty | All FEED pendings popped → this is the FEED-exit signal. Push BREED pendings (via `_initiate_harvest_breed`), set `phase = HARVEST_BREED`. |
| HARVEST_BREED | non-empty | Outer guard returns. Player is deciding. |
| HARVEST_BREED | empty | All BREED pendings popped → BREED-exit signal. Set `phase = PREPARATION` (round < 14) or `phase = BEFORE_SCORING` (round == 14). |

**Why "phase==X + empty stack" unambiguously means exit.** The only way to reach `phase == HARVEST_FEED` is via `_resolve_harvest_field`, which always pushes FEED pendings before transitioning. So the stack is non-empty immediately after the transition. The only way the stack becomes empty while `phase == HARVEST_FEED` is for all FEED pendings to have been popped via `Stop` — i.e., exit. Same for BREED.

**Idempotency.** Re-running `_advance_until_decision` on any returned state is idempotent: stack non-empty → outer guard returns immediately; stack empty → advances deterministically based on the phase. No auxiliary boolean flags, no sync invariants.

**Why not push pendings inside `_advance_until_decision`'s phase branch instead of inside `_resolve_harvest_field`?** It works either way — the branch could call `_resolve_harvest_field(state)` (mechanical only) then `_initiate_harvest_feed(state)` separately. Putting both in `_resolve_harvest_field` keeps the engine loop minimal (one resolver call per phase branch, matching `_resolve_preparation` / `_resolve_return_home`'s shape) and makes `_resolve_harvest_field` the single source of truth for "what happens when FIELD ends." The trade-off is that `_resolve_harvest_field` is now responsible for two distinct concerns — but they are naturally connected and the parallel with `_resolve_preparation` justifies it.

## 2.2 `_advance_until_decision` shape

```python
def _advance_until_decision(state: GameState) -> GameState:
    while True:
        if state.pending_stack:
            return state

        if state.phase == Phase.PREPARATION:
            state = _resolve_preparation(state)
            continue

        if state.phase == Phase.WORK:
            if all(p.people_home == 0 for p in state.players):
                state = dataclasses.replace(state, phase=Phase.RETURN_HOME)
                continue
            return state

        if state.phase == Phase.RETURN_HOME:
            state = _resolve_return_home(state)
            continue

        if state.phase == Phase.HARVEST_FIELD:
            state = _resolve_harvest_field(state)
            # _resolve_harvest_field pushes FEED pendings and sets phase=HARVEST_FEED;
            # the outer guard returns on the next iteration because the stack is non-empty.
            continue

        if state.phase == Phase.HARVEST_FEED:
            # Outer guard already returned for non-empty stack. Stack is empty here =
            # all FEED pendings have been Stop'd. Push BREED pendings, transition.
            state = _initiate_harvest_breed(state)
            state = dataclasses.replace(state, phase=Phase.HARVEST_BREED)
            continue

        if state.phase == Phase.HARVEST_BREED:
            # Stack empty = BREED done. Transition to PREPARATION or BEFORE_SCORING.
            if state.round_number >= NUM_ROUNDS:
                state = dataclasses.replace(state, phase=Phase.BEFORE_SCORING)
            else:
                state = dataclasses.replace(state, phase=Phase.PREPARATION)
            continue

        if state.phase == Phase.BEFORE_SCORING:
            return state

        raise AssertionError(f"Unexpected phase in advance loop: {state.phase}")
```

Idempotency preserved: any state with non-empty stack returns immediately at the outer guard; any state with empty stack auto-advances deterministically by phase. `BEFORE_SCORING` is the terminal sink. `NUM_ROUNDS == 14` from `constants.py`.

## 2.3 `_resolve_return_home` update

Replace the current "halt after round 4" logic with the harvest routing:

```python
def _resolve_return_home(state: GameState) -> GameState:
    """End-of-round bookkeeping: reset worker placements, return people home.
    Does NOT clear newborns (those survive to HARVEST_FEED for the 1-food discount).

    Transitions to HARVEST_FIELD on HARVEST_ROUNDS, otherwise to PREPARATION.
    Round 14's HARVEST_BREED transitions on to BEFORE_SCORING (handled in
    _advance_until_decision's HARVEST_BREED branch when the stack is empty,
    not here).
    """
    # 1. Reset worker tuples (unchanged).
    new_spaces = {
        space_id: dataclasses.replace(action_space, workers=(0, 0))
        for space_id, action_space in state.board.action_spaces.items()
    }
    new_board = dataclasses.replace(state.board, action_spaces=new_spaces)

    # 2. Return people home (unchanged).
    new_players = tuple(
        dataclasses.replace(p, people_home=p.people_total)
        for p in state.players
    )

    state = dataclasses.replace(state, players=new_players, board=new_board)

    # 3. Decide next phase.
    if state.round_number in HARVEST_ROUNDS:
        return dataclasses.replace(state, phase=Phase.HARVEST_FIELD)

    return dataclasses.replace(state, phase=Phase.PREPARATION)
```

`HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}` already lives in `agricola/constants.py`.

The `round_number >= 4 → BEFORE_SCORING` shortcut is removed entirely. Round 14's transition to BEFORE_SCORING happens in `_advance_until_decision`'s HARVEST_BREED-empty-stack branch (Part 2.2), not here.

## 2.4 `Phase` enum — unchanged

The existing `Phase` enum already includes `HARVEST_FIELD`, `HARVEST_FEED`, `HARVEST_BREED` from Task 5. No new values are added.

```python
class Phase(Enum):
    WORK = auto()
    RETURN_HOME = auto()
    PREPARATION = auto()
    HARVEST_FIELD = auto()
    HARVEST_FEED = auto()
    HARVEST_BREED = auto()
    BEFORE_SCORING = auto()
```

`HARVEST_FEED` and `HARVEST_BREED` carry two structural meanings depending on stack state: stack non-empty = "player is deciding"; stack empty = "all FEED/BREED pendings have been Stop'd, the phase is ready to exit." The engine loop distinguishes them by checking the stack inside each phase branch (covered in Part 2.2).

## 2.5 Provenance prefix scheme — third category

`initiated_by_id` gains a third namespace alongside the existing `"space:<id>"` and `"card:<id>"`:

| Push source | `initiated_by_id` value |
|---|---|
| `_initiate_harvest_feed` | `"phase:harvest_feed"` |
| `_initiate_harvest_breed` | `"phase:harvest_breed"` |

The `"phase:"` prefix is new and documented in CLAUDE.md's pending-provenance section. No risk of namespace collision: `"phase:"` is disjoint from `"space:"` and `"card:"`.

---

# Part 3 — Pendings, actions, and PlayerState changes

The state-shape changes for the harvest: a once-per-harvest budget on `PlayerState`, two new pending dataclasses (FEED and BREED), three new `Action` types, and the `PendingDecision` / `Action` union updates.

## 3.1 `PlayerState.harvest_conversions_used` field

`PlayerState` gains a new field tracking which once-per-harvest conversions have been used by this player in the current harvest:

```python
# In agricola/state.py — add to PlayerState (after newborns / begging_markers, before future_resources):

harvest_conversions_used: frozenset = frozenset()  # frozenset[str] of conversion_ids used this harvest
```

Default value `frozenset()`. Reset to `frozenset()` inside `_resolve_harvest_field` (see Part 4.1) — i.e., at the start of each harvest, before any FEED decisions. Persists across the FEED → BREED transition (BREED doesn't use it, but no reason to clear midway). Reset again at the next harvest's FIELD.

The "once per harvest" budget lives here rather than on `PendingHarvestFeed` per the CLAUDE.md guidance:

> Per-card budgets that DO span multiple events (once-per-round, once-per-game, once-per-harvest) live on `PlayerState` or `BoardState`, separate from pending frames.

Reset happens at HARVEST_FIELD entry, the natural boundary. The reset is one line per player; no sync invariant to maintain.

## 3.2 `PendingHarvestFeed`

```python
@dataclass(frozen=True)
class PendingHarvestFeed:
    PENDING_ID:        ClassVar[str] = "harvest_feed"
    player_idx:        int
    initiated_by_id:   str             # always "phase:harvest_feed"
    food_owed:         int             # decreases as crafts and CommitConvert produce food
    conversion_done:   bool = False    # set True by CommitConvert; gates Stop legality
```

**State semantics.**

- `food_owed` is set at push time to `max(0, need - p.resources.food)`, where `need = 2 * (people_total - newborns) + 1 * newborns = 2*people_total - newborns`. At push time, `p.resources.food` is also pre-debited by `min(need, p.resources.food)` — this implements the "Cannot withhold food tokens to intentionally over-beg" rule (RULES.md, Feeding Phase).
- Each `CommitHarvestConversion(conversion_id, use=True)` reduces `food_owed` by `min(food_out, food_owed)`. Surplus goes into the player's food supply.
- `CommitConvert(g, v, s, b, c)` reduces `food_owed` by `min(food_produced, food_owed)`, places surplus in supply, and adds the remaining `food_owed` to begging_markers. Then sets `conversion_done = True`.
- Stop is legal only after `conversion_done = True`.

**Why food_owed instead of a global flag.** Two reasons. (1) It lets the legality enumerator compute the conversion frontier cheaply — it only needs `food_owed`, not "starting-need minus food paid so far minus craft yields so far." (2) It folds craft yields into the same accounting as the conversion: the enumerator reads `food_owed` as the post-craft residual, and the conversion frontier is computed against that.

**No `triggers_resolved` / `TRIGGER_EVENT` yet.** Card triggers attaching to `before_harvest_feed` / `after_harvest_feed` will gain the fields when the first such card lands; today they would be dead weight.

**No `crafts_decided` field on the pending.** The "which crafts has the player decided about" state is read from `p.harvest_conversions_used` (which records every committed decision — both use=True and use=False). The pending doesn't duplicate this.

## 3.3 `PendingHarvestBreed`

```python
@dataclass(frozen=True)
class PendingHarvestBreed:
    PENDING_ID:        ClassVar[str] = "harvest_breed"
    player_idx:        int
    initiated_by_id:   str          # always "phase:harvest_breed"
    breed_chosen:      bool = False # set True by CommitBreed; gates Stop legality
```

**State semantics.**

- At push time, no resource changes. (Breeding fires at commit time, not at push.)
- `CommitBreed(s, b, c)` sets the player's animals to the chosen frontier point, adds food via the `breeding_frontier`'s `food_gained` term, and sets `breed_chosen = True`.
- Stop is legal only after `breed_chosen = True`.

No `triggers_resolved` / `TRIGGER_EVENT` — deferred. The natural events when cards arrive: `before_harvest_breed` (fires before any commit; could let a card add a sheep), `after_harvest_breed` (fires after commit; could grant a bonus). Both go on this pending when needed.

## 3.4 `PendingDecision` union update

```python
PendingDecision = Union[
    # ... all existing ...
    PendingHarvestFeed,
    PendingHarvestBreed,
]
```

## 3.5 `CommitHarvestConversion`

```python
@dataclass(frozen=True)
class CommitHarvestConversion(CommitSubAction):
    conversion_id: str   # must be a key in HARVEST_CONVERSIONS
    use:           bool  # True = fire the conversion, False = decide-not-to-use (records the decision)
```

Lands on `PendingHarvestFeed`. After commit, `conversion_id` is added to `player.harvest_conversions_used` (regardless of `use`'s value — both decisions count as "decided"). If `use=True`, the resource cost is debited and `food_out` is applied to `food_owed`.

Note that the decision is recorded on PlayerState, not on the pending — same forward-compatibility reason as the field's location. If a card pushed a copy of `PendingHarvestFeed` mid-decision, the budget would still be correctly shared across the two pendings.

## 3.6 `CommitConvert`

```python
@dataclass(frozen=True)
class CommitConvert(CommitSubAction):
    grain:  int   # grain CONSUMED for food conversion (subtracted from supply)
    veg:    int   # veg CONSUMED
    sheep:  int   # sheep CONSUMED (cooked)
    boar:   int   # boar CONSUMED (cooked)
    cattle: int   # cattle CONSUMED (cooked)
```

Lands on `PendingHarvestFeed`. The fields hold **consumed** amounts (subtracted from the player's supply), in contrast to `CommitAccommodate` and `CommitBreed` which hold final/remaining counts. The "consumed" convention is preferred for `CommitConvert` because: (1) the values are bounded by the per-good caps in the food-payment frontier (small fixed range, friendly to NN policy heads), (2) `(0,0,0,0,0)` always means "consume nothing" regardless of player state, and (3) there's no addition mechanic to combine with — pure subtraction maps cleanly to "convert these goods." `CommitBreed` and `CommitAccommodate` represent post-event states that combine subtraction with addition (newborns / market gains), where the consumed framing doesn't apply cleanly.

The legality enumerator builds `CommitConvert` by inverting the REMAINING tuples returned by `harvest_feed_frontier` (consumed = player_max - remaining).

After commit:

- `food_produced = commit.grain + commit.veg*rates[3] + commit.sheep*rates[0] + commit.boar*rates[1] + commit.cattle*rates[2]`.
- Player's grain/veg/animals decrement by the commit values.
- `food_owed -= min(food_produced, food_owed)`; surplus (`max(0, food_produced - food_owed)`) added to `p.resources.food`.
- `begging_markers += food_owed` (the remaining owed — begging assignment is owned by `_execute_convert`, not by Stop, preserving the Stop-only-pops convention).
- `pending.conversion_done` is set to `True` via `replace_top`.

`Stop` is the only legal action after `CommitConvert` (gratuitous trailing pop).

## 3.7 `CommitBreed`

```python
@dataclass(frozen=True)
class CommitBreed(CommitSubAction):
    sheep:  int   # final sheep count after breeding (chosen from breeding_frontier)
    boar:   int
    cattle: int
```

Lands on `PendingHarvestBreed`. The `(sheep, boar, cattle)` triple must match a Pareto-optimal point from `breeding_frontier(player_state, rates[:3])`. After commit:

- The player's animals are set to the chosen counts (any reduction relative to current = release-or-cook).
- The `food_gained` computed by `breeding_frontier` for this point is added to `p.resources.food`.
- `pending.breed_chosen` is set to `True`.

`Stop` is the only legal action after `CommitBreed`. There is no auto-pop on commit: the trailing Stop is the explicit exit, matching the other multi-stage pendings (`PendingClayOven`, `PendingStoneOven` etc.).

## 3.8 `Action` union update

```python
Action = Union[
    PlaceWorker,
    ChooseSubAction,
    CommitSow,
    CommitBake,
    CommitPlow,
    CommitBuildStable,
    CommitBuildRoom,
    CommitBuildMajor,
    CommitRenovate,
    CommitAccommodate,
    CommitBuildPasture,
    # New in Task 7:
    CommitHarvestConversion,
    CommitConvert,
    CommitBreed,
    FireTrigger,
    Stop,
]
```

---

# Part 4 — Resolution functions

Per the existing convention (CLAUDE.md "Function-name prefix taxonomy"), phase-bookkeeping resolvers (`_resolve_<phase>`) live in `agricola/engine.py` alongside `_resolve_return_home` / `_resolve_preparation`, while sub-action effect functions (`_execute_<sub_action>`) live in `agricola/resolution.py`. This task introduces both kinds:

| Function | File | Role |
|---|---|---|
| `_resolve_harvest_field` | `engine.py` | Phase bookkeeping: FIELD work + reset + push FEED + transition |
| `_initiate_harvest_feed` | `engine.py` | Helper for FEED pending push (called by `_resolve_harvest_field`) |
| `_initiate_harvest_breed` | `engine.py` | Helper for BREED pending push (called by `_advance_until_decision`'s HARVEST_FEED branch at FEED-exit) |
| `_execute_harvest_conversion` | `resolution.py` | Sub-action effect for `CommitHarvestConversion` |
| `_execute_convert` | `resolution.py` | Sub-action effect for `CommitConvert` |
| `_execute_breed` | `resolution.py` | Sub-action effect for `CommitBreed` |

The `_initiate_harvest_*` helpers live in `engine.py` (not `resolution.py`) because they push *phase-driven* pendings, not space-driven ones — distinct from the existing `_initiate_<nonatomic_space>` family. Placing them adjacent to `_resolve_harvest_field` keeps the phase-entry machinery in one place.

## 4.1 `_resolve_harvest_field`

Called from `_advance_until_decision` when phase is `HARVEST_FIELD`. Does three things in sequence: (1) mechanical field-crop harvest, (2) reset `harvest_conversions_used` on both players, (3) push FEED pendings via `_initiate_harvest_feed` and transition phase to `HARVEST_FEED`. The double-duty mirrors `_resolve_preparation`'s multi-concern shape and is justified in Part 2.1.

```python
def _resolve_harvest_field(state: GameState) -> GameState:
    """Mechanical FIELD work + reset once-per-harvest budget + push FEED pendings + transition phase.

    Step 1 (mechanical): take 1 crop from each planted field for each player. Mandatory
    for all fields. Grain takes precedence over veg per RULES.md (a field is sown with
    either grain or veg, never both — the elif fallback never fires for a typical sown field).
    Step 2 (budget reset): clear harvest_conversions_used on both players so the upcoming
    FEED phase starts with a fresh once-per-harvest budget.
    Step 3 (push + transition): push FEED pendings via _initiate_harvest_feed, set phase
    to HARVEST_FEED. After this returns, the stack is non-empty (one frame per player)
    and the outer loop's stack guard returns control to the agent.
    """
    new_players = []
    for p in state.players:
        grain_gain = 0
        veg_gain   = 0
        new_grid_rows = []
        for r in range(3):
            new_row = []
            for c in range(5):
                cell = p.farmyard.grid[r][c]
                if cell.cell_type == CellType.FIELD:
                    if cell.grain > 0:
                        grain_gain += 1
                        new_row.append(dataclasses.replace(cell, grain=cell.grain - 1))
                    elif cell.veg > 0:
                        veg_gain += 1
                        new_row.append(dataclasses.replace(cell, veg=cell.veg - 1))
                    else:
                        new_row.append(cell)  # empty field (already harvested or never sown)
                else:
                    new_row.append(cell)
            new_grid_rows.append(tuple(new_row))
        new_grid = tuple(new_grid_rows)

        new_farmyard = dataclasses.replace(p.farmyard, grid=new_grid)
        new_resources = p.resources + Resources(grain=grain_gain, veg=veg_gain)
        new_players.append(dataclasses.replace(
            p,
            farmyard=new_farmyard,
            resources=new_resources,
            harvest_conversions_used=frozenset(),  # reset for the upcoming FEED phase
        ))

    state = dataclasses.replace(state, players=tuple(new_players))

    # Push FEED pendings and transition phase. _initiate_harvest_feed pushes one
    # PendingHarvestFeed per player (SP-on-top), and pre-debits food.
    state = _initiate_harvest_feed(state)
    return dataclasses.replace(state, phase=Phase.HARVEST_FEED)
```

Reads through each field cell, takes 1 grain (if non-zero), otherwise 1 veg (if non-zero), otherwise nothing (empty field). Pasture cache is preserved unchanged (fields cannot be inside pastures).

The `harvest_conversions_used` reset and the FEED-pending push both land inside this function rather than being split out:

1. The reset belongs here because FIELD is the natural "harvest start" — both sub-phases that follow read the freshly-reset budget.
2. Pushing the FEED pendings inside `_resolve_harvest_field` (rather than a separate engine-loop branch) keeps `_advance_until_decision`'s harvest section minimal — one `_resolve_*` call per phase branch, matching `_resolve_preparation` / `_resolve_return_home`'s shape. The "what happens when FIELD ends" semantics is owned by one function.

## 4.2 `_initiate_harvest_feed`

Called by `_resolve_harvest_field` as its final step (Part 4.1). Pushes a `PendingHarvestFeed` for each player, ordered so the starting player's frame is on top, and pre-debits food per the "cannot withhold" rule. Also exposed as a standalone helper so tests can construct a FEED-only state without running FIELD mechanics.

```python
def _initiate_harvest_feed(state: GameState) -> GameState:
    """Push PendingHarvestFeed for each player. Starting player's frame ends up
    on top. Pre-debits food per the 'cannot withhold' rule.
    """
    # Compute push order: non-starting player first (bottom), starting player last (top).
    sp = state.starting_player
    push_order = [(sp + 1) % 2, sp]

    for idx in push_order:
        p = state.players[idx]
        need = 2 * p.people_total - p.newborns
        spent = min(need, p.resources.food)
        food_owed = need - spent

        new_player = dataclasses.replace(p, resources=p.resources + Resources(food=-spent))
        state = _update_player(state, idx, new_player)
        state = push(state, PendingHarvestFeed(
            player_idx=idx,
            initiated_by_id="phase:harvest_feed",
            food_owed=food_owed,
        ))

    return state
```

**Pre-debit semantics.** `spent = min(need, p.resources.food)` is debited from the player's food supply upfront; the remaining `food_owed` is what the conversions / begging must cover. This implements the "Cannot withhold food tokens" rule structurally. If the player has more food than `need`, the surplus stays in supply (no negative food, no over-pay).

**Push order.** Non-starting player pushed first (bottom of stack), starting player pushed second (top). When the starting player Stops, the non-starting player's pending becomes top automatically.

## 4.3 `_initiate_harvest_breed`

Same pattern as `_initiate_harvest_feed`, but no pre-debit (breeding doesn't consume food upfront).

```python
def _initiate_harvest_breed(state: GameState) -> GameState:
    """Push PendingHarvestBreed for each player. Starting player's frame on top."""
    sp = state.starting_player
    push_order = [(sp + 1) % 2, sp]

    for idx in push_order:
        state = push(state, PendingHarvestBreed(
            player_idx=idx,
            initiated_by_id="phase:harvest_breed",
        ))

    return state
```

## 4.4 `_execute_harvest_conversion`

Lands on `PendingHarvestFeed`. Applies the conversion if `use=True`; records the decision either way.

```python
def _execute_harvest_conversion(
    state: GameState, player_idx: int, commit: CommitHarvestConversion,
) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed)
    p = state.players[player_idx]
    # HARVEST_CONVERSIONS lives in agricola.cards.harvest_conversions (Part 6.3).
    spec = HARVEST_CONVERSIONS[commit.conversion_id]

    # Record the decision regardless of use's value. This makes harvest_conversions_used
    # a "decided" set, not a "used" set — both record_used and record_skipped end here.
    new_used = p.harvest_conversions_used | {commit.conversion_id}

    if not commit.use:
        # Skip: just record the decision; no resource change.
        new_player = dataclasses.replace(p, harvest_conversions_used=new_used)
        return _update_player(state, player_idx, new_player)

    # Fire: pay input cost, produce food_out food, apply to food_owed.
    food_owed_before = top.food_owed
    food_consumed_by_owed = min(spec.food_out, food_owed_before)
    food_surplus = spec.food_out - food_consumed_by_owed
    new_resources = p.resources - spec.input_cost + Resources(food=food_surplus)

    new_player = dataclasses.replace(
        p,
        resources=new_resources,
        harvest_conversions_used=new_used,
    )
    state = _update_player(state, player_idx, new_player)
    state = replace_top(state, dataclasses.replace(
        top, food_owed=food_owed_before - food_consumed_by_owed,
    ))

    # Optional side effect (e.g. Stone Sculptor's +1 point — None today).
    if spec.side_effect_fn is not None:
        state = spec.side_effect_fn(state, player_idx)

    return state
```

Registered in `COMMIT_SUBACTION_HANDLERS` with `auto_pop=False` — the pending stays on top to host further craft decisions and the conversion.

## 4.5 `_execute_convert`

Lands on `PendingHarvestFeed`. Applies the chosen conversion configuration, assigns begging, sets `conversion_done`.

```python
def _execute_convert(
    state: GameState, player_idx: int, commit: CommitConvert,
) -> GameState:
    """CommitConvert.grain/veg/sheep/boar/cattle are CONSUMED amounts —
    subtracted from the player's supply. food_produced computed directly
    from the commit fields via rates."""
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed)
    p = state.players[player_idx]
    sR, bR, cR, vR = cooking_rates(state, player_idx)

    food_produced = (
        commit.grain
        + commit.veg    * vR
        + commit.sheep  * sR
        + commit.boar   * bR
        + commit.cattle * cR
    )

    food_owed_before = top.food_owed
    food_consumed_by_owed = min(food_produced, food_owed_before)
    food_surplus = food_produced - food_consumed_by_owed
    food_owed_after = food_owed_before - food_consumed_by_owed
    begging_added = food_owed_after  # what's still owed becomes begging markers

    new_resources = p.resources + Resources(
        grain=-commit.grain,
        veg=-commit.veg,
        food=food_surplus,
    )
    new_animals = Animals(
        sheep=p.animals.sheep   - commit.sheep,
        boar=p.animals.boar     - commit.boar,
        cattle=p.animals.cattle - commit.cattle,
    )
    new_player = dataclasses.replace(
        p,
        resources=new_resources,
        animals=new_animals,
        begging_markers=p.begging_markers + begging_added,
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, dataclasses.replace(
        top, food_owed=0, conversion_done=True,
    ))
```

After this fires, `top.food_owed == 0` and `top.conversion_done == True`. Stop is the only legal next action.

Begging is assigned here rather than at Stop time — this preserves the Stop-only-pops convention. The decision is final at conversion time: no further craft uses or other food sources can fire after CommitConvert, so begging is fully determined by the state right after this commit.

Registered in `COMMIT_SUBACTION_HANDLERS` with `auto_pop=False`.

## 4.6 `_execute_breed`

Lands on `PendingHarvestBreed`. Sets animals to chosen frontier point and adds the food gained.

```python
def _execute_breed(
    state: GameState, player_idx: int, commit: CommitBreed,
) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed)
    p = state.players[player_idx]

    rates_3 = cooking_rates(state, player_idx)[:3]  # (sheep, boar, cattle) — breeding_frontier signature

    # Look up food_gained for this commit via breeding_frontier (the same set we
    # filter against in the enumerator). breeding_frontier is small (O(animals^3)).
    frontier = breeding_frontier(p, rates_3)
    food_gained = None
    chosen = Animals(sheep=commit.sheep, boar=commit.boar, cattle=commit.cattle)
    for (cfg, fg) in frontier:
        if cfg == chosen:
            food_gained = fg
            break
    assert food_gained is not None, f"CommitBreed {chosen} not in frontier {frontier}"

    new_player = dataclasses.replace(
        p,
        animals=chosen,
        resources=p.resources + Resources(food=food_gained),
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, dataclasses.replace(top, breed_chosen=True))
```

The lookup-from-frontier pattern (rather than recomputing food_gained from scratch) keeps the food formula in one place — `breeding_frontier` is the single source of truth.

Registered in `COMMIT_SUBACTION_HANDLERS` with `auto_pop=False` (Stop is the explicit exit).

---

# Part 5 — Legality enumerators

Both in `agricola/legality.py`.

## 5.1 `_enumerate_pending_harvest_feed`

Two regimes based on pending state:

1. **Crafts still pending OR conversion not yet done**: offer each undecided owned craft as `use=True/False`, AND offer all Pareto-frontier conversion points.
2. **Conversion done**: only `Stop` is legal.

```python
def _enumerate_pending_harvest_feed(
    state: GameState, pending: PendingHarvestFeed,
) -> list[Action]:
    from agricola.helpers import cooking_rates, harvest_feed_frontier
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS

    actions: list[Action] = []
    p = state.players[pending.player_idx]

    if pending.conversion_done:
        actions.append(Stop())
        return actions

    # Offer undecided owned conversions.
    for conversion_id, spec in HARVEST_CONVERSIONS.items():
        if conversion_id in p.harvest_conversions_used:
            continue  # already decided this harvest
        if not spec.is_owned_fn(state, pending.player_idx):
            continue  # player doesn't own this conversion source

        # use=False is always available (skip).
        actions.append(CommitHarvestConversion(conversion_id=conversion_id, use=False))

        # use=True only if player can afford the input cost.
        if _can_afford(p, spec.input_cost):
            actions.append(CommitHarvestConversion(conversion_id=conversion_id, use=True))

    # Offer all Pareto-frontier conversion points. harvest_feed_frontier always
    # returns at least one entry — the "consume nothing, beg everything" config
    # (max goods preserved) is always on the frontier.
    # The frontier returns REMAINING-goods tuples; CommitConvert takes CONSUMED
    # amounts. Invert by subtracting from the player's pre-conversion goods.
    rates = cooking_rates(state, pending.player_idx)  # 4-tuple
    grain_pre  = p.resources.grain
    veg_pre    = p.resources.veg
    sheep_pre  = p.animals.sheep
    boar_pre   = p.animals.boar
    cattle_pre = p.animals.cattle
    for ((g_rem, v_rem, s_rem, b_rem, c_rem), _begging) in harvest_feed_frontier(p, pending.food_owed, rates):
        actions.append(CommitConvert(
            grain=grain_pre  - g_rem,
            veg=veg_pre    - v_rem,
            sheep=sheep_pre  - s_rem,
            boar=boar_pre   - b_rem,
            cattle=cattle_pre - c_rem,
        ))

    return actions
```

**No ordering between crafts and conversion.** The agent can use a craft first, then commit conversion, then end (gratuitous Stop). Or commit conversion first, in which case no further crafts are offered (the post-`conversion_done` regime returns only Stop). Committing conversion first forfeits any undecided crafts — the same end-state is reachable by explicitly committing `use=False` for each craft beforehand. So in terms of outcome, the "convert-first" order is equivalent to "skip-all-crafts-then-convert," but the trace is shorter. Engine enforces neither order; both are legal.

**Pareto frontier always non-empty.** When `food_owed > 0`, the partial-feed configurations (e.g., `(0,0,0,0,0)` with `begging = food_owed`) are always frontier members. When `food_owed == 0`, the helper returns exactly `[((0, 0, 0, 0, 0), 0)]`.

**No early-fail "this player has no work to do" branch.** Even a player with 0 grain, 0 veg, 0 animals, 0 crafts, and `food_owed == 0` still sees one legal action: `CommitConvert(0, 0, 0, 0, 0)`. After committing, only `Stop` is legal. Total trace: 2 actions per player per FEED — that's the gratuitous floor.

## 5.2 `_enumerate_pending_harvest_breed`

```python
def _enumerate_pending_harvest_breed(
    state: GameState, pending: PendingHarvestBreed,
) -> list[Action]:
    from agricola.helpers import cooking_rates, breeding_frontier

    actions: list[Action] = []
    p = state.players[pending.player_idx]

    if pending.breed_chosen:
        actions.append(Stop())
        return actions

    rates_3 = cooking_rates(state, pending.player_idx)[:3]
    for (cfg, _food) in breeding_frontier(p, rates_3):
        actions.append(CommitBreed(sheep=cfg.sheep, boar=cfg.boar, cattle=cfg.cattle))

    return actions
```

The frontier is always non-empty — `breeding_frontier` includes at least the "do nothing" configuration (current animals, no breeding), which is feasible by definition. So every player always has at least one `CommitBreed`, even ones with 0 animals (the singleton `CommitBreed(0, 0, 0)`).

## 5.3 `PENDING_ENUMERATORS` registration

Add both to the table:

```python
PENDING_ENUMERATORS: dict[type, Callable] = {
    # ... existing entries ...
    PendingHarvestFeed:  _enumerate_pending_harvest_feed,
    PendingHarvestBreed: _enumerate_pending_harvest_breed,
}
```

---

# Part 6 — Helpers and registries

## 6.1 `food_payment_frontier` — the primary frontier helper

Lives in `agricola/helpers.py`, alongside `pareto_frontier` and `breeding_frontier`. Returns the Pareto-optimal list of `(grain_remaining, veg_remaining, sheep_remaining, boar_remaining, cattle_remaining)` tuples for fully paying `food_owed` food via crop/animal conversion. The return convention matches the existing frontier helpers: tuples are **remaining/final goods**, not consumed amounts.

**Scope.** This is the general-purpose food-payment frontier. It applies wherever a player pays food: card costs that demand a specific food amount, future effects with fixed food costs, and the harvest feeding (via `harvest_feed_frontier`, which composes this helper across paid levels). It does NOT consider partial payment or begging — that's harvest-specific and lives in `harvest_feed_frontier`.

```python
import math

def food_payment_frontier(
    player_state: PlayerState,
    food_owed: int,
    rates: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int, int]]:
    """Return Pareto-optimal (grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem)
    tuples for fully paying food_owed food via crop/animal conversion. The "rem"
    suffix indicates REMAINING goods after the conversion (matches the
    breeding_frontier / pareto_frontier convention).

    rates: (sheep_rate, boar_rate, cattle_rate, veg_rate). Grain is always 1:1.
    Pass rates from cooking_rates(state, player_idx).

    Pareto dimensions are the 5 goods (NOT food_surplus). See CLAUDE.md
    "Preserving optionality" Key Design Principle, specifically the "Pareto
    dominance over upstream goods" prescription — food is a one-way downstream
    derivative of crops/animals, so preserving goods strictly dominates
    preserving extra food. An over-converted config like (consume 3 grain) for
    food_owed=2 is Pareto-dominated by (consume 2 grain) on the (grain_rem)
    dim; the +1 surplus food contributes no Pareto value.

    `pareto_frontier`, `breeding_frontier`, and the food-payment frontiers all
    follow this rule uniformly — food is never a Pareto dim across any of them.

    Per-good enumeration caps:
    - grain consumed: 0..min(player.grain, food_owed)              # rate=1
    - veg consumed:   0..min(player.veg,    ceil(food_owed/vR))
    - sheep consumed: 0..min(player.sheep,  ceil(food_owed/sR)) if sR > 0 else 0
    - boar consumed:  0..min(player.boar,   ceil(food_owed/bR)) if bR > 0 else 0
    - cattle consumed: 0..min(player.cattle, ceil(food_owed/cR)) if cR > 0 else 0

    Each cap is the max useful consumption — converting more is always Pareto-
    dominated by converting one less.

    food_owed == 0 returns [(player.grain, player.veg, player.sheep,
    player.boar, player.cattle)] — only the no-conversion entry.

    For food_owed > 0 with insufficient player capacity (max food_produced <
    food_owed), returns []. Callers requiring a non-empty frontier (card payment
    actions) should pre-check feasibility; the harvest feeding path uses
    harvest_feed_frontier which always has at least the (all-goods-remaining,
    begging=food_owed) entry.
    """
    sR, bR, cR, vR = rates
    grain_max  = player_state.resources.grain
    veg_max    = player_state.resources.veg
    sheep_max  = player_state.animals.sheep
    boar_max   = player_state.animals.boar
    cattle_max = player_state.animals.cattle

    if food_owed == 0:
        return [(grain_max, veg_max, sheep_max, boar_max, cattle_max)]

    # Per-good consumption caps.
    grain_cap  = min(grain_max,  food_owed)
    veg_cap    = min(veg_max,    math.ceil(food_owed / vR))
    sheep_cap  = min(sheep_max,  math.ceil(food_owed / sR)) if sR > 0 else 0
    boar_cap   = min(boar_max,   math.ceil(food_owed / bR)) if bR > 0 else 0
    cattle_cap = min(cattle_max, math.ceil(food_owed / cR)) if cR > 0 else 0

    candidates: list[tuple[int, int, int, int, int]] = []
    for g in range(grain_cap + 1):
        for v in range(veg_cap + 1):
            for s in range(sheep_cap + 1):
                for b in range(boar_cap + 1):
                    for c in range(cattle_cap + 1):
                        food_produced = g + v*vR + s*sR + b*bR + c*cR
                        if food_produced < food_owed:
                            continue
                        remaining = (
                            grain_max  - g,
                            veg_max    - v,
                            sheep_max  - s,
                            boar_max   - b,
                            cattle_max - c,
                        )
                        candidates.append(remaining)

    # Pareto-filter on the 5-dim remaining-goods vector. NO food_surplus dim.
    def dominates(a, b):
        return all(ax >= bx for ax, bx in zip(a, b)) and any(ax > bx for ax, bx in zip(a, b))

    frontier: list[tuple[int, int, int, int, int]] = []
    for i, tup in enumerate(candidates):
        if not any(dominates(candidates[j], tup) for j in range(len(candidates)) if j != i):
            frontier.append(tup)

    return frontier
```

The per-good caps reduce enumeration substantially. For food_owed=2 with Cooking Hearth (cattle rate=4), `cattle_cap = ceil(2/4) = 1` — so the cattle dim has 2 values rather than `player.cattle + 1`.

## 6.2 `harvest_feed_frontier` — harvest-specific wrapper

Lives in `agricola/helpers.py`, immediately below `food_payment_frontier`. Composes `food_payment_frontier` across paid levels `[0, food_owed]` to model the harvest's "pay what you can, beg the rest" rule.

```python
def harvest_feed_frontier(
    player_state: PlayerState,
    food_owed: int,
    rates: tuple[int, int, int, int],
) -> list[tuple[tuple[int, int, int, int, int], int]]:
    """Return Pareto-optimal ((grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem),
    begging) pairs for paying as much of food_owed as the player chooses, begging
    the rest. "rem" = REMAINING goods (matches the breeding_frontier convention).

    Implementation: for each paid in [0, food_owed], call food_payment_frontier
    with that paid amount. For each returned config, compute the actual
    food it generates (from the remaining tuple). Admit the config to the
    candidate set ONLY at the paid level that matches its natural fit —
    `paid == min(food_generated, food_owed)`. This admits each config exactly
    once, with `begging = food_owed - paid` equal to its actual begging.
    Pareto-filter on the 6-dim end-state (grain_rem, veg_rem, sheep_rem,
    boar_rem, cattle_rem, -begging) where -begging is "more is better."

    The natural-fit filter prevents the "ghost begging" problem: a config
    producing F food qualifies for food_payment_frontier(paid=k) for every
    k ≤ F (capped at food_owed). Without the filter, the candidate set
    would hold up to F+1 copies of the same config, all but one with
    begging values that don't match the actual food generated. The filter
    keeps exactly the one entry whose `paid` matches reality.

    food_surplus is NOT a Pareto dim (see CLAUDE.md "Preserving optionality").

    food_owed == 0 returns [((player.grain, player.veg, player.sheep,
    player.boar, player.cattle), 0)].
    Frontier is always non-empty for food_owed > 0 because the all-remaining +
    begging=food_owed config (from paid=0, where it's the unique natural fit)
    is always a candidate and is always on the frontier (max goods preserved;
    -begging is the minimum, but no other config can match the goods AND
    beat it on -begging).
    """
    sR, bR, cR, vR = rates
    grain_max  = player_state.resources.grain
    veg_max    = player_state.resources.veg
    sheep_max  = player_state.animals.sheep
    boar_max   = player_state.animals.boar
    cattle_max = player_state.animals.cattle

    if food_owed == 0:
        return [((grain_max, veg_max, sheep_max, boar_max, cattle_max), 0)]

    # Aggregate candidates from each paid level, admitting each config at the
    # paid level matching its natural fit (= min(food_generated, food_owed)).
    # This keeps exactly one entry per config with the correct begging tag.
    candidates: list[tuple[tuple[int, int, int, int, int], int]] = []
    for paid in range(food_owed + 1):
        for remaining in food_payment_frontier(player_state, paid, rates):
            food_generated = (
                (grain_max  - remaining[0])
                + (veg_max    - remaining[1]) * vR
                + (sheep_max  - remaining[2]) * sR
                + (boar_max   - remaining[3]) * bR
                + (cattle_max - remaining[4]) * cR
            )
            if paid == min(food_generated, food_owed):
                candidates.append((remaining, food_owed - paid))

    # Pareto-filter on (grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem, -begging).
    def end_state(cand):
        remaining, beg = cand
        return (*remaining, -beg)

    def dominates(a, b):
        return all(ax >= bx for ax, bx in zip(a, b)) and any(ax > bx for ax, bx in zip(a, b))

    end_states = [end_state(cand) for cand in candidates]
    frontier: list[tuple[tuple[int, int, int, int, int], int]] = []
    for i, cand in enumerate(candidates):
        if not any(dominates(end_states[j], end_states[i]) for j in range(len(candidates)) if j != i):
            frontier.append(cand)

    return frontier
```

**Why the natural-fit filter is correct.** A config that produces F food qualifies for `food_payment_frontier(paid=k)` for every `k ∈ [1, min(F, food_owed)]`. Without filtering, each such config would land in the candidate set at every qualifying paid level — with a different `begging = food_owed - paid` each time. Only the entry whose `paid` matches `min(F, food_owed)` carries the correct begging:
- Partial-feed (`F < food_owed`): natural fit at `paid = F`, giving `begging = food_owed - F` = actual begging.
- Full-feed (`F >= food_owed`): natural fit at `paid = food_owed`, giving `begging = 0` = actual begging.

The filter `paid == min(food_generated, food_owed)` admits exactly one entry per config. No "ghost" entries with mismatched begging tags reach the Pareto-filter step.

**Note on the resolution semantics.** The begging tag on a frontier entry is purely informational — it's what the agent sees when comparing options. The actual outcome at commit time is computed by `_execute_convert`, which derives consumed goods from the chosen remaining tuple and routes `food_produced` into supply (as surplus) and/or against `food_owed` (with shortfall becoming begging). So even if a ghost entry slipped through, the agent's actual end-state would still be correct — but it would have made the decision against a misleading begging label. The natural-fit filter ensures the labels match reality.

## 6.3 `HARVEST_CONVERSIONS` registry

Lives in a new `agricola/cards/harvest_conversions.py` module — paralleling the existing `agricola/cards/triggers.py` registry. The three built-in entries (Joinery / Pottery / Basketmaker) register at module-load time; future cards (e.g., Stone Sculptor) register their own entries via `register_harvest_conversion(spec)`.

The dataclass:

```python
# In agricola/cards/harvest_conversions.py:

from typing import Callable, Optional
from dataclasses import dataclass

from agricola.resources import Resources

@dataclass(frozen=True)
class HarvestConversionSpec:
    conversion_id:     str                                                 # e.g. "joinery"
    input_cost:        Resources                                           # Resources spent to fire
    food_out:          int                                                 # food produced
    is_owned_fn:       Callable[["GameState", int], bool]                  # whether player_idx owns the source
    side_effect_fn:    Optional[Callable[["GameState", int], "GameState"]] = None
    # ^ Optional non-food effect (e.g. Stone Sculptor's +1 point). None for the
    # three crafts. Called after the food/resource accounting in _execute_harvest_conversion.
```

The three built-in entries:

```python
def _owns_major(idx: int):
    def fn(state, player_idx):
        return state.board.major_improvement_owners[idx] == player_idx
    return fn

HARVEST_CONVERSIONS: dict[str, HarvestConversionSpec] = {
    "joinery": HarvestConversionSpec(
        conversion_id="joinery",
        input_cost=Resources(wood=1),
        food_out=2,
        is_owned_fn=_owns_major(7),
    ),
    "pottery": HarvestConversionSpec(
        conversion_id="pottery",
        input_cost=Resources(clay=1),
        food_out=2,
        is_owned_fn=_owns_major(8),
    ),
    "basketmaker": HarvestConversionSpec(
        conversion_id="basketmaker",
        input_cost=Resources(reed=1),
        food_out=3,
        is_owned_fn=_owns_major(9),
    ),
}

def register_harvest_conversion(spec: HarvestConversionSpec) -> None:
    HARVEST_CONVERSIONS[spec.conversion_id] = spec
```

**Why `agricola/cards/harvest_conversions.py` (not `agricola/constants.py`).** The registry pattern parallels `agricola/cards/triggers.py` (which hosts the card-`TRIGGERS` registry, populated by `agricola.cards.__init__` importing each card module). The three crafts aren't cards per se — they're major improvements — but the registry shape is identical (id-keyed dict + `register_*` function). Co-locating with `cards/` keeps registries-of-effects in one directory and lets `cards/__init__.py` be the single import point for "load all registered effects at startup."

`agricola.cards.__init__` imports `harvest_conversions` early so the three built-in entries register before any caller reads `HARVEST_CONVERSIONS`. Future card modules (Stone Sculptor etc.) are also imported from `cards/__init__.py`, registering themselves via `register_harvest_conversion(...)` at import time.


---

# Part 7 — Dispatch wiring and setup glue

Final integration: registering the new commit types in `COMMIT_SUBACTION_HANDLERS` and initializing the new `PlayerState` field at game-setup time.

## 7.1 `COMMIT_SUBACTION_HANDLERS` additions

```python
COMMIT_SUBACTION_HANDLERS: dict[type, tuple] = {
    # ... all existing entries ...
    CommitHarvestConversion: (PendingHarvestFeed,  _execute_harvest_conversion, False),
    CommitConvert:              (PendingHarvestFeed,  _execute_convert,                False),
    CommitBreed:                (PendingHarvestBreed, _execute_breed,                  False),
}
```

All three use `auto_pop=False`: the pending stays on top because Stop is the explicit exit (matching the multi-shot pattern established in Task 5D).

## 7.2 `setup` update

Setup must initialize the new state field:

```python
# In agricola/setup.py — _make_player:
return PlayerState(
    resources=Resources(food=food),
    animals=Animals(),
    farmyard=_make_farmyard(),
    house_material=HouseMaterial.WOOD,
    people_total=2,
    people_home=2,
    newborns=0,
    begging_markers=0,
    harvest_conversions_used=frozenset(),  # NEW: clean budget at game start
)
```

Default value covers tests that don't go through `setup`, but explicit assignment in `_make_player` is the documented pattern.

---
# Part 8 — Tests

Four new test files plus updates to `test_helpers.py`.

## 8.1 `tests/test_harvest_field.py`

Mechanical-resolution tests. Uses prefabricated states from `factories.py`.

Coverage:
- **Single field, 1 grain remaining → 1 grain to supply.**
- **Single field, 1 veg remaining → 1 veg to supply.**
- **Multiple fields per player → 1 from each.**
- **Empty fields (no crops) → no change, no error.**
- **Both players harvest simultaneously** — each gets their own fields' crops.
- **`harvest_conversions_used` reset** — pre-fab a state where both players have non-empty `harvest_conversions_used`; after `_resolve_harvest_field`, both are empty.
- **Phase transition** — after `_resolve_harvest_field`, `state.phase == Phase.HARVEST_FEED`.
- **Pasture cache preserved** — fields cannot lie inside pastures; verify the cached `pastures` tuple is unchanged.
- **Newborns preserved** — `_resolve_harvest_field` does not touch `newborns` (the discount applies in FEED).

## 8.2 `tests/test_harvest_feed.py`

Engine-level integration tests for `PendingHarvestFeed`. Uses factories to set up specific FEED states.

Coverage:
> Frontier tuples below (from `food_payment_frontier` / `harvest_feed_frontier`) use the **REMAINING** convention — entries are `(grain_remaining, veg_remaining, sheep_remaining, boar_remaining, cattle_remaining)` after the conversion. `CommitConvert(grain=g, veg=v, ...)` uses the **CONSUMED** convention — values are subtracted from the player's supply at commit time. The enumerator inverts the frontier tuple (consumed = player_max - remaining) when constructing the CommitConvert.

- **Trivial FEED (no decisions, just Stop)** — player with 2 food, 1 person (need=2), no animals, no grain/veg, no crafts. `food_owed=0` after pre-debit. Legal actions: `[CommitConvert(grain=0, veg=0, sheep=0, boar=0, cattle=0)]` (consume nothing — the player has zero of every good to consume anyway). After commit, legal: `[Stop()]`. After Stop, pending popped, next player's pending on top (if applicable).
- **Pre-debit semantics** — player with 5 food, need=4. Push debits 4; resources.food=1; food_owed=0; FEED proceeds trivially.
- **Begging assignment** — player with 0 food, need=4, no convertibles. Legal: `[CommitConvert(0,0,0,0,0)]` (consume nothing — no convertibles available). After commit, begging_markers += 4. After Stop, pending popped.
- **Grain conversion (1:1)** — player with 0 food, 3 grain, need=2, no cooking. food_owed=2. `harvest_feed_frontier` returns three REMAINING points: `((1,0,0,0,0), 0)` (consume 2, keep 1, full pay), `((2,0,0,0,0), 1)` (consume 1, keep 2, beg 1), `((3,0,0,0,0), 2)` (consume 0, keep 3, beg 2). These become `CommitConvert(grain=2, ...)`, `CommitConvert(grain=1, ...)`, `CommitConvert(grain=0, ...)` after inversion. Verify selection of `CommitConvert(grain=2, ...)` leaves 1 grain and 0 begging.
- **Veg conversion (no cooking)** — player with 0 food, 2 veg, need=2, no cooking (veg rate=1). Frontier includes REMAINING `((0,0,0,0,0), 0)` → `CommitConvert(grain=0, veg=2, ...)`.
- **Veg conversion (with Fireplace)** — same player but with Fireplace. veg rate=2. Frontier includes REMAINING `((0,1,0,0,0), 0)` (1 veg remains) → `CommitConvert(grain=0, veg=1, ...)`.
- **Veg conversion (with Cooking Hearth)** — veg rate=3. need=3 → REMAINING `((0,1,0,0,0), 0)` → `CommitConvert(grain=0, veg=1, ...)`.
- **Animal cooking (Fireplace)** — player with Fireplace, 3 sheep, 2 boar, 1 cattle, 0 food, need=4. rates_animals=(2,2,3). `food_payment_frontier` returns exactly 5 REMAINING tuples: `(0,0,1,2,1)` (consume 2 sheep, keep 1 sheep + 2 boar + 1 cattle), `(0,0,3,0,1)` (consume 2 boar, keep 3 sheep + 1 cattle), `(0,0,2,1,1)` (consume 1 sheep + 1 boar = 4 food exact, keep 2 sheep + 1 boar + 1 cattle), `(0,0,2,2,0)` (consume 1 sheep + 1 cattle = 5 food, keep 2 sheep + 2 boar), `(0,0,3,1,0)` (consume 1 boar + 1 cattle = 5 food, keep 3 sheep + 1 boar). Each preserves a different combination of animals; none dominates the others on the (sheep, boar, cattle) Pareto dims. Surplus food differs across configs (0 for first three, 1 for last two) but is NOT a Pareto dim — see CLAUDE.md "Preserving optionality" Key Design Principle for the Pareto-over-upstream-goods prescription.
- **Cooking Hearth dominates Fireplace** — player with both. rates from `cooking_rates` reflect Hearth.
- **Joinery once-per-harvest** — player owns Joinery, has 1 wood, 0 food, need=4 (so food_owed=4 after pre-debit). Legal actions include `CommitHarvestConversion(joinery, use=True)` and `CommitHarvestConversion(joinery, use=False)`. After committing `use=True`, wood decreases by 1, food_owed decreases by 2 (now food_owed=2; food in supply unchanged because all 2 food went to owed, none to surplus). `"joinery"` is now in `p.harvest_conversions_used`; the enumerator no longer offers either `use=True` or `use=False` for Joinery on subsequent calls.
- **Joinery insufficient wood** — player owns Joinery, has 0 wood. Only `CommitHarvestConversion(joinery, use=False)` is legal (use=True excluded by affordability check).
- **Joinery always offered (food_owed=0)** — player owns Joinery, has 5 food, need=2 (food_owed=0 after pre-debit). `use=True` is still in legal actions — once-per-harvest, no preservation of optionality. Verify the agent CAN waste a wood if they choose.
- **Multiple crafts** — player owns Joinery + Pottery + Basketmaker, has appropriate resources, need=10. Legal actions: 3 craft-yes + 3 craft-no + conversion frontier. After all 3 crafts decided (in any order), only conversion frontier + already-decided constraint. Cross-product tested: at least one path through all 3.
- **Pareto excludes over-conversion** — player with 0 food, 3 grain, 3 veg, need=2, no cooking (veg rate=1). REMAINING tuple `(0,3,0,0,0)` (consume all 3 grain) should NOT be on the food_payment_frontier: Pareto-dominated by `(1,3,0,0,0)` (consume 2 grain — same veg remaining, more grain remaining). Both fully pay; the +1 surplus food in (consume-3-grain) has no Pareto value.
- **Pareto preserves full-feed tradeoffs** — same player as above. food_payment_frontier SHOULD include `(1,3,0,0,0)` (consume 2 grain), `(2,2,0,0,0)` (consume 1 grain + 1 veg), and `(3,1,0,0,0)` (consume 2 veg) — three full-feed configs that trade off grain vs veg preservation. None dominates the others on the goods dims.
- **Pareto frontier preserves "convert less and beg" choices** — player with 5 grain, 1 sheep, 0 food, need=4, Fireplace. harvest_feed_frontier should include `((1,0,1,0,0), 0)` (consume 4 grain, keep sheep), `((3,0,0,0,0), 0)` (consume 2 grain + 1 sheep = 2+2 = 4 food, keep 3 grain), AND `((5,0,1,0,0), 4)` (consume nothing, beg all 4). All Pareto-optimal in their own way — different goods-vs-begging tradeoffs.
- **`conversion_done` gates Stop** — Stop not in legal actions before CommitConvert; Stop is the only legal action after.
- **Trailing Stop is gratuitous** — after CommitConvert with `food_owed=0`, only Stop is legal. Verify trace shape: `[craft decisions], CommitConvert(...), Stop()`.
- **Push order — starting player on top** — given `state.starting_player=1`, push pendings; verify `pending_stack[-1].player_idx == 1`. After SP Stops, `pending_stack[-1].player_idx == 0`.
- **Newborn discount** — player with newborns=1, people_total=2 (so 1 adult + 1 newborn). need = 2*1 + 1*1 = 3, not 4. Verify food_owed.

## 8.3 `tests/test_harvest_breed.py`

Engine-level integration tests for `PendingHarvestBreed`.

Coverage:
> Note: `breeding_frontier` Pareto-filters over **animal counts only** (sheep, boar, cattle), matching `pareto_frontier` and the food-payment frontiers. Food is a deterministic consequence of the chosen post-breed configuration, returned alongside each frontier point but excluded from the dominance check. See CLAUDE.md "Preserving optionality" Key Design Principle for the umbrella concept and the "Pareto dominance over upstream goods" prescription that drops out of it.

- **No animals → trivial Stop** — player with 0 animals, no cooking. Frontier: `[(Animals(0,0,0), 0)]`. Legal: `[CommitBreed(0,0,0)]`. After commit, only Stop is legal.
- **Insufficient (1 each), no cooking → no breeding** — player with 1 sheep, 1 boar, 1 cattle, no cooking improvement (rates_3=(0,0,0)). All release configs have food=0. Pareto-filter (animals + food=0 everywhere) keeps configs that aren't strictly worse on any animal dim. With house pet capacity=1, only single-animal configs fit. Frontier = `{(Animals(1,0,0), 0), (Animals(0,1,0), 0), (Animals(0,0,1), 0)}`. Three points (one per animal type).
- **Single-type breeding (sheep), no cooking** — player with 2 sheep, 0 boar, 0 cattle, sufficient capacity (e.g., 2×1 pasture), no cooking. All configs have food=0. Frontier = `[(Animals(3,0,0), 0)]` — the max-sheep config dominates on the sheep dim with food tied.
- **Single-type breeding (sheep), with cooking** — same player but with Fireplace (rates_3=(2,2,3)). Frontier shape unchanged from the no-cooking case: `[(Animals(3,0,0), 0)]`. Cooking rates don't enter the dominance check (animal-only Pareto), and the frontier point's food is still 0 because no release happens at the optimum (the player breeds to 3 with no pre-breed eats). Confirms cooking rates affect food values only when a release is forced.
- **Breeding with capacity constraint forces a release** — player with 3 sheep + 1×1 pasture (sheep capacity = 2+1 = 3 via pasture + house pet). Breeding to 4 exceeds capacity. With Fireplace (rates_3=(2,2,3)), frontier = `[(Animals(3,0,0), 2)]` — single point. Food formula uses the breed-fired branch: `(s+1-sF)*sR = (3+1-3)*2 = 2`, since the player optimally eats 1 sheep pre-breed to enable the newborn (eat 0 yields no breed because cap-for-4 is missing, end at 3 with 0 food; eat 1 enables breeding because pre-breed-post-eat=2 fits in cap-3, end at 3 with 2 food). The optimal-play assumption baked into the food formula picks the higher-food path automatically.
- **Multi-type breeding, no cooking** — player with 2 sheep, 2 boar, 2 cattle, sufficient capacity (e.g., 3 pastures + house pet). All food=0. Frontier = `[(Animals(3,3,3), 0)]` — all bred.
- **Two 1×1 pastures, 2 sheep + 2 boar, Fireplace** — Two 1×1 pastures (cap 2 each) + house pet (1 flex). With one pasture for sheep and one for boar, the house pet slot is shared — only ONE type's newborn can use it. rates_3=(2,2,3). Frontier captures the "which type breeds" choice; release-for-food configs are all Pareto-dominated and pruned. Frontier = exactly `{(Animals(3,2,0), 0), (Animals(2,3,0), 0)}` (symmetric). `(3,3,0)` is infeasible. See `tests/test_helpers.py:test_breeding_two_pastures_two_sheep_two_boar`.
- **`breed_chosen` gates Stop** — Stop not legal before commit; Stop is only legal action after.
- **Push order — SP on top** — same as FEED.

## 8.4 `tests/test_harvest_integration.py`

End-to-end multi-round tests, mixing harvests with work rounds. Coverage:

- **Round 4 first harvest** — random agent plays through rounds 1-4, hits harvest, completes all three sub-phases. Verify final `phase == Phase.PREPARATION`, `round_number == 4` (not yet incremented to 5; that happens in PREPARATION). Then `_resolve_preparation` runs, round becomes 5, current_player = starting_player.
- **All 6 harvests in one game** — fixed-seed random-agent runs from setup to BEFORE_SCORING. Verify the harvest fires at rounds 4, 7, 9, 11, 13, 14 (count harvest entries via instrumented phase trace).
- **Round 14 ends in BEFORE_SCORING** — after round 14's HARVEST_BREED completes, phase is BEFORE_SCORING. `step` raises if called.
- **`harvest_conversions_used` resets correctly** — multi-harvest test where a player uses Joinery in harvest 1, then again in harvest 2 (allowed; fresh budget).
- **Newborn discount applied** — fabricate a state where a player has a newborn from round 4. At round-4 FEED, need = 2*(people_total - 1) + 1. Verify food_owed matches.
- **Random agent over 100 seeds** — `random_agent_play` runs 100 times to BEFORE_SCORING. None raise. Add a coverage assertion that across the 100 seeds, harvest_field/feed/breed pendings each are reached.
- **Begging-marker scoring impact** — extend an existing scoring test to confirm begging markers from the harvest propagate to `score(state, player_idx)`.

## 8.5 `tests/test_helpers.py` updates

- **`cooking_rates` 4-tuple** — 4 updated assertions per the Part 1 table.
> All tuples below use the REMAINING convention.

- **`food_payment_frontier` direct tests**:
  - `food_owed=0`, player with 3 grain + 1 sheep → returns `[(3,0,1,0,0)]` (no conversion, all goods remaining).
  - `food_owed=1`, 1 grain → returns `[(0,0,0,0,0)]` (consume the one grain).
  - `food_owed=4`, no cooking, 4 grain + 2 veg (veg rate=1) → frontier is exactly `{(0,2,0,0,0), (1,1,0,0,0), (2,0,0,0,0)}` — three full-feed configs (consume 4 grain / 3 grain + 1 veg / 2 grain + 2 veg) that pareto-trade-off grain vs veg preservation. Over-conversion configs like `(0,1,0,0,0)` (consume 4 grain + 1 veg = food=5) are excluded — Pareto-dominated by `(0,2,0,0,0)` (same grain, more veg). Verify the frontier is exactly these three points.
  - `food_owed=2`, Fireplace, 2 grain + 1 veg → frontier includes `(2,0,0,0,0)` (consume 1 veg for 2 food, keep grain) and `(0,1,0,0,0)` (consume 2 grain, keep veg) — both Pareto-optimal.
  - `food_owed=3`, with cooking, animal mix → animal-only-cooking configs.
- **`harvest_feed_frontier` direct tests**:
  - `food_owed=0`, player with 1 grain → returns `[((1,0,0,0,0), 0)]` (all goods remaining, no begging).
  - `food_owed=2`, 1 grain, no cooking → frontier is exactly `{((1,0,0,0,0), 2), ((0,0,0,0,0), 1)}`. Both partial-feed, neither dominates the other (more grain vs less begging).
  - `food_owed=2`, 2 grain, no cooking → frontier is exactly `{((0,0,0,0,0), 0), ((1,0,0,0,0), 1), ((2,0,0,0,0), 2)}` — one full-feed plus two partial-feed configs, all on the frontier (different points on the begging-vs-goods tradeoff). Verify all three are present and no others.
  - **Full-feed never dominated by partial-feed** — invariant test: for any state, a full-feed config (begging=0) is NEVER excluded by a partial-feed config. Reason: -begging is a Pareto dimension where full-feed has -0 (max); partial-feed has -beg < 0 (worse). So partial-feed cannot match the full-feed on all dims.
  - **food_payment_frontier matches harvest_feed_frontier's begging-zero subset** — invariant test: `food_payment_frontier(p, food_owed, rates) == [point for (point, beg) in harvest_feed_frontier(p, food_owed, rates) if beg == 0]`. Confirms the wrapper relationship.

## 8.6 `tests/test_utils.py` notes

`random_agent_play` doesn't need restructuring — it already loops while `phase != Phase.BEFORE_SCORING` and selects from `filter_implemented(legal_actions(...))`. But the filter list needs the three new commit types added so the random agent will actually pick them when surfaced by `legal_actions` during harvest.

Concretely: add `CommitHarvestConversion`, `CommitConvert`, `CommitBreed` to the list/set of accepted action types in `_is_implemented_action`. Pendings don't need to be filtered — they're not actions.

---

# Part 9 — Documentation

The documentation updates are split across four files. CLAUDE.md hosts only architectural narrative and high-level one-liners; per-file details live in FILE_DESCRIPTIONS.md; per-test-file coverage lives in TEST_DESCRIPTIONS.md; cross-cutting refactor records live in CHANGES.md. The four subsections below partition the work along those lines.

## 9.1 CLAUDE.md updates (architectural narrative + one-liners)

- **Status table**: Add seven new rows under Task 7 ("Harvest sub-phases — Field/Feed/Breed", "Cooking rates 4-tuple", "food_payment_frontier / harvest_feed_frontier", "HARVEST_CONVERSIONS registry", "PlayerState.harvest_conversions_used", "PendingHarvestFeed / PendingHarvestBreed + commits", "Rounds 5–14"). Remove the "Not yet implemented" lines for harvest and rounds 5–14.
- **"Engine and Turn Resolution Architecture" section**: extend the phase-transition narrative to include the harvest sub-phases. Add a "Harvest" subsection covering the FIELD → FEED → BREED progression, the gratuitous-Stop rule, the Pareto-frontier action filter, the once-per-harvest budget on PlayerState, and the dual stack-empty / stack-non-empty meaning of `HARVEST_FEED` / `HARVEST_BREED`.
- **Provenance prefix scheme**: add the `"phase:<id>"` row to the table alongside `"space:<id>"` and `"card:<id>"`.
- **"Card implementation status" section**: extend the trigger-mechanism note to mention `before_harvest_feed` / `after_harvest_feed` / `before_harvest_breed` / `after_harvest_breed` as future events. Note that `triggers_resolved` / `TRIGGER_EVENT` are intentionally absent from `PendingHarvestFeed` / `PendingHarvestBreed` per the Task 5D precedent. Add a forward-looking sentence: once the full card system lands, almost every pending will host trigger-style opt-in sub-decisions in the shape `PendingHarvestFeed` uses for the three craft majors — opportunities to take `Commit*` actions for cards that trigger on the space or sub-action, followed by the main action or sub-action commit.
- **Note on Pareto principle**: no separate documentation cascade — the Pareto-over-upstream-goods rule that the new frontiers follow (no `food_surplus` Pareto dim) is already the specific prescription dropping out of the **"Preserving optionality"** Key Design Principle in CLAUDE.md. The new helpers' docstrings cross-reference that principle; no edit to the principle text itself.
- **Directory Structure section**: update the one-liner for `agricola/cards/__init__.py` to mention the harvest_conversions import; add a one-liner for the new `agricola/cards/harvest_conversions.py`; add one-liners for `tests/test_harvest_field.py`, `tests/test_harvest_feed.py`, `tests/test_harvest_breed.py`, `tests/test_harvest_integration.py`. Brief edits only — detailed descriptions belong in FILE_DESCRIPTIONS.md / TEST_DESCRIPTIONS.md.
- **Documentation Files table**: no change.

## 9.2 FILE_DESCRIPTIONS.md updates (per-file detail)

- **`agricola/state.py`**: add `harvest_conversions_used: frozenset[str]` to the `PlayerState` description; note the reset point (`_resolve_harvest_field`) and that the field records both `use=True` and `use=False` decisions ("decided" set, not "used" set). No `GameState` changes needed (no new phase values, no auxiliary flags — see Part 2.1).
- **`agricola/constants.py`**: no changes — no `Phase` enum additions, no new constants. The harvest registry lives in `agricola/cards/harvest_conversions.py`, not `constants.py`.
- **`agricola/cards/harvest_conversions.py`**: NEW entry. `HARVEST_CONVERSIONS` dict, `HarvestConversionSpec` dataclass, `register_harvest_conversion(spec)` registration function. Three built-in entries: joinery, pottery, basketmaker. Imported by `agricola/cards/__init__.py` so the entries register at package import time.
- **`agricola/cards/__init__.py`**: extend description to note the new `harvest_conversions` import alongside the existing card module imports.
- **`agricola/helpers.py`**: extend the `cooking_rates` description to the 4-tuple shape (with the (0,0,0,1) fallback note for the veg dim). Add `food_payment_frontier` (general-purpose food-payment frontier, returns REMAINING tuples, Pareto-filtered on upstream goods only) and `harvest_feed_frontier` (harvest-specific wrapper composing `food_payment_frontier` across paid levels with the begging dimension added). Include the inline "may move to harvest.py" marker.
- **`agricola/pending.py`**: add `PendingHarvestFeed` (hosts trigger-style opt-in sub-decisions — the three craft majors — plus one main `CommitConvert`; `food_owed` + `conversion_done` fields) and `PendingHarvestBreed` (one `CommitBreed` + Stop; `breed_chosen` field). Add the `"phase:..."` provenance prefix to the prefix-scheme table inside this file's description.
- **`agricola/actions.py`**: add `CommitHarvestConversion`, `CommitConvert`, `CommitBreed` to the action class enumeration. Note their inclusion in the `Action` union. Document the CONSUMED-amounts convention used by `CommitConvert` (in contrast to the post-event-state convention used by `CommitBreed` / `CommitAccommodate`).
- **`agricola/legality.py`**: add `_enumerate_pending_harvest_feed` and `_enumerate_pending_harvest_breed`. Note their registration in `PENDING_ENUMERATORS`.
- **`agricola/resolution.py`**: add `_execute_harvest_conversion`, `_execute_convert`, `_execute_breed`. Note the three additions in `COMMIT_SUBACTION_HANDLERS` (all `auto_pop=False`).
- **`agricola/engine.py`**: update `_advance_until_decision` description to cover the three new harvest-phase branches and the dual stack-empty / stack-non-empty meaning of `HARVEST_FEED` / `HARVEST_BREED`. Update `_resolve_return_home` to note the routing to HARVEST_FIELD on HARVEST_ROUNDS. Add `_resolve_harvest_field` (mechanical FIELD work + once-per-harvest reset + push FEED pendings + transition to HARVEST_FEED), `_initiate_harvest_feed`, `_initiate_harvest_breed` — all three live in `engine.py` alongside the existing `_resolve_return_home` / `_resolve_preparation`, per the convention that phase-bookkeeping resolvers belong in `engine.py`.
- **`tests/factories.py` / `tests/test_utils.py`**: no description changes for `factories.py`; for `test_utils.py`, note that the `_is_implemented_action` filter now accepts `CommitHarvestConversion`, `CommitConvert`, `CommitBreed`.

## 9.3 TEST_DESCRIPTIONS.md updates (per-test-file coverage)

- **`tests/test_harvest_field.py`**: NEW. Mechanical-resolution tests for `_resolve_harvest_field` — single/multiple/empty fields per player, both players harvest simultaneously, `harvest_conversions_used` reset, phase transition to HARVEST_FEED, pasture cache preserved, newborns preserved.
- **`tests/test_harvest_feed.py`**: NEW. Engine-level integration tests for `PendingHarvestFeed` — trivial Stop, pre-debit semantics, begging assignment, raw grain 1:1 conversion, veg conversion (no cooking / Fireplace / Cooking Hearth), animal cooking (Fireplace), Cooking Hearth dominates Fireplace, Joinery once-per-harvest (including insufficient wood and food_owed=0 cases), multiple-craft cross-product, Pareto excludes over-conversion, Pareto preserves full-feed tradeoffs and "convert less and beg" choices, `conversion_done` gates Stop, trailing-Stop gratuity, push order (SP on top), newborn discount.
- **`tests/test_harvest_breed.py`**: NEW. Engine-level integration tests for `PendingHarvestBreed` — trivial Stop for 0-animal player, insufficient-animals no-breeding, single-type breeding (with and without cooking), capacity-constraint forces release, multi-type breeding, two-1×1-pasture house-pet contention, `breed_chosen` gates Stop, push order.
- **`tests/test_harvest_integration.py`**: NEW. End-to-end multi-round tests — round 4 first harvest, all 6 harvests in one game, round 14 terminal BEFORE_SCORING, `harvest_conversions_used` resets correctly across harvests, newborn discount applied, random-agent over 100 seeds, begging-marker scoring impact.
- **`tests/test_helpers.py`**: extend existing entry — `cooking_rates` updated to 4-tuple; new sections covering `food_payment_frontier` (direct tests including the food_owed=0 shortcut, partial-pay configs, Pareto-excludes-over-conversion invariants) and `harvest_feed_frontier` (begging-dim Pareto, full-feed-never-dominated invariant, `food_payment_frontier` matches the begging-zero subset invariant).

## 9.4 CHANGES.md entry

**Change 7 — Harvest phases, `cooking_rates` 4-tuple, food-payment Pareto helpers, dual-meaning phase pattern.**

Documents:

- `cooking_rates` extended from 3-tuple to 4-tuple `(sheep, boar, cattle, veg)`. Two call sites (legality + resolution) updated to slice; `pareto_frontier` and `breeding_frontier` signatures unchanged.
- New `food_payment_frontier` and `harvest_feed_frontier` in `helpers.py`. Pareto-filtered conversion options for paying food, with `harvest_feed_frontier` adding a begging dimension.
- New `HARVEST_CONVERSIONS` registry in `agricola/cards/harvest_conversions.py` paralleling `agricola/cards/triggers.py`. Built-in entries: joinery, pottery, basketmaker. Card extension hook: `register_harvest_conversion(spec)`.
- New `PlayerState.harvest_conversions_used: frozenset[str]` for once-per-harvest budget. Reset inside `_resolve_harvest_field`. Records both `use=True` and `use=False` decisions (a "decided" set, not a "used" set).
- New `PendingHarvestFeed` — hosts trigger-style opt-in sub-decisions (the three craft majors via `CommitHarvestConversion`) followed by one main `CommitConvert`. This is the same shape future card triggers will use across most pendings: opportunities to take `Commit*` actions for triggering effects, then the main commit. `PendingHarvestBreed` is the simpler one-`CommitBreed` + Stop shape. Begging is assigned by `_execute_convert`, not by Stop — preserves the Stop-only-pops convention.
- The existing `HARVEST_FEED` / `HARVEST_BREED` phase values now carry dual meaning: stack non-empty = player is deciding, stack empty = phase-exit signal. The discriminator works because the only way to reach phase=X with empty stack is for the entry-resolver to have pushed pendings (now drained). No new phase values or boolean flags needed.
- New `"phase:<id>"` namespace for `initiated_by_id` (alongside `"space:<id>"` and `"card:<id>"`). Phase-driven pending pushes use this prefix.
- New `Action` types: `CommitHarvestConversion`, `CommitConvert`, `CommitBreed`. All `auto_pop=False`.
- New `engine.py` functions: `_resolve_harvest_field` (mechanical + reset + push FEED + transition), `_initiate_harvest_feed`, `_initiate_harvest_breed`. `_resolve_return_home` updated to route to HARVEST_FIELD on HARVEST_ROUNDS.
- After this change, `step()` runs all 14 rounds end-to-end with all 6 harvests resolved. The engine has no remaining unimplemented phases.

---

# Part 10 — Order of work

Each step should leave the test suite green before proceeding. Note that the implementation order is bottom-up and does NOT match the doc's top-down narrative order. The doc reads top-down for clarity; implementation builds from primitives up to engine wiring.

1. **Part 1** — `cooking_rates` to 4-tuple. Two call sites updated to slice. Four test assertions updated. All 520 existing tests pass.
2. **Part 3.1** — `PlayerState.harvest_conversions_used` field. Default value lets existing tests pass unchanged. `setup` updated (Part 7.2).
3. **Part 6.3** — `HARVEST_CONVERSIONS` registry in `agricola/cards/harvest_conversions.py`. Three built-in entries. Imported from `agricola/cards/__init__.py`. No use sites yet — dead-code coexistence.
4. **Part 6.1 + 6.2** — `food_payment_frontier` and `harvest_feed_frontier` in `helpers.py`. New tests in `test_helpers.py` for both.
5. **Part 3.5–3.8** — New action types: `CommitHarvestConversion`, `CommitConvert`, `CommitBreed`. Added to `Action` union.
6. **Part 3.2–3.4** — `PendingHarvestFeed`, `PendingHarvestBreed` dataclasses. Added to `PendingDecision`.
7. **Part 4.4–4.6 + Part 5** — Effect functions (resolution.py) and legality enumerators (legality.py). Registered in `COMMIT_SUBACTION_HANDLERS` (Part 7.1) and `PENDING_ENUMERATORS`. Still no end-to-end harvest yet — `_advance_until_decision` doesn't know about harvest phases.
8. **Part 4.2–4.3** — `_initiate_harvest_feed`, `_initiate_harvest_breed` in `engine.py`. Standalone helpers used by Part 4.1 and by `_advance_until_decision`'s HARVEST_FEED branch.
9. **Part 4.1** — `_resolve_harvest_field` in `engine.py`. Calls `_initiate_harvest_feed`. New test file `tests/test_harvest_field.py`. (FIELD still doesn't run end-to-end because `_advance_until_decision` doesn't route to HARVEST_FIELD yet.)
10. **Part 2.2 + 2.3** — `_advance_until_decision` extended; `_resolve_return_home` routes to HARVEST_FIELD. Round 4 now transitions through harvest to PREPARATION. `random_agent_play` for short seeds may now run rounds 5–14.
11. **Part 8.2** — New test file `tests/test_harvest_feed.py`. All tests pass.
12. **Part 8.3** — New test file `tests/test_harvest_breed.py`. All tests pass.
13. **Part 8.4** — New test file `tests/test_harvest_integration.py`. End-to-end tests. Random-agent over 100 seeds passes.
14. **Part 8.6** — Update `tests/test_utils.py` filter to include new commit types.
15. **Part 9** — Documentation updates across CLAUDE.md (narrative + one-liners), FILE_DESCRIPTIONS.md (per-file detail), TEST_DESCRIPTIONS.md (per-test-file coverage), and CHANGES.md (Change 7 entry).

After step 15, the engine plays a complete Family game without raising.

---

# Part 11 — Acceptance criteria

- All 520 pre-existing tests pass (with the 4-tuple `cooking_rates` assertions updated).
- New test files pass: `tests/test_harvest_field.py`, `tests/test_harvest_feed.py`, `tests/test_harvest_breed.py`, `tests/test_harvest_integration.py`.
- New helper tests pass in `tests/test_helpers.py` (extended for `food_payment_frontier` and `harvest_feed_frontier`).
- `random_agent_play` runs end-to-end from `setup(seed)` to `Phase.BEFORE_SCORING` for **seeds 0–99**. All 100 reach BEFORE_SCORING without raising.
- The cumulative phase trace across the 100 seeds includes HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED at least once each.
- `step()` no longer raises in any case other than `Phase.BEFORE_SCORING`. There is no remaining `NotImplementedError` path for harvest phases.
- `PendingHarvestFeed` and `PendingHarvestBreed` are correctly hosted on the stack — at any point during a harvest, exactly one player's frame is on top, and the SP's frame is on top first (verified via a dedicated test).
- Begging markers correctly flow from `_execute_convert` into `PlayerState.begging_markers`; from there into `scoring.py`'s `score()`. Verified by an end-to-end test.
- `PlayerState.harvest_conversions_used` is reset to `frozenset()` inside every `_resolve_harvest_field` call. Verified by a multi-harvest test where a craft is used in harvest 1, then again in harvest 2.
- CLAUDE.md reflects the architecture after this task: harvest sub-phases documented (with the dual stack-empty / stack-non-empty meaning of `HARVEST_FEED` / `HARVEST_BREED` made explicit), `"phase:..."` prefix added to the provenance scheme, harvest pendings documented, `food_payment_frontier` / `harvest_feed_frontier` in the helpers description.
- CHANGES.md has a new Change 7 entry covering the cooking_rates refactor and the harvest architecture.

---

# Appendix A — Out of scope

- **Card triggers on harvest pendings.** `triggers_resolved` and `TRIGGER_EVENT` fields are not added to `PendingHarvestFeed` / `PendingHarvestBreed`. Follows the Task 5D precedent — these are dead weight without a card that uses them. Future cards attaching to `before_harvest_feed`, `after_harvest_feed`, `before_harvest_breed`, `after_harvest_breed` will add the fields when implemented.
- **New cards.** No new card is implemented in this task. The `HARVEST_CONVERSIONS` registry is built to accept future entries (e.g., Stone Sculptor: "Once per harvest: 1 stone → 1 food + 1 point"), but no card module is added.
- **Compound card interactions** at FEED — e.g., a card whose effect within FEED enables another card's eligibility. The pending-stack and registry pattern accommodate this in principle; the speculative-legality machinery needed for it is deferred to the future card-system task, same as for Pan-Baker × Potter-Ceramics.
- **Atomic-space trigger hosting** (separate Task 5C deferred item — has no harvest-specific dimension).
- **Once-per-turn card budget pattern** (Task 5D deferred item).
- **Animal-rearrangement actions** (e.g., a hypothetical "move animals between pastures" card) — animals are tracked by total counts, not per-pasture. Such a card would require richer animal-location state.
- **A "harvest.py" module.** Today `food_payment_frontier` and `harvest_feed_frontier` live in `helpers.py` alongside `pareto_frontier` and `breeding_frontier`. If harvest grows complex enough to warrant its own module (e.g., once cards add a wide range of harvest-specific events), both functions move with it. Marker comment in place.
- **Future-resource expansion.** Currently `PlayerState.future_resources: tuple[Resources, ...]` of length 14 covers per-round goods from Well. The harvest does not introduce new future_resources triggers; the Well's existing payouts integrate naturally via the existing PREPARATION distribution.
- **`Resources` negative-component prevention.** Pre-debit + per-commit accounting guarantees non-negative resource arithmetic throughout the harvest. No `Resources` API change.
