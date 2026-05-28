# First NN — AgricolaBot

Design spec for the first neural network value function for AgricolaBot. The goal: a learned drop-in replacement for `evaluate_hubris_v3` as the leaf evaluator in MCTS, with a higher ceiling than V3's hand-crafted linear-combiner form.

This is the working spec for the initial NN phase. It captures the input encoding, supervision target, data generation pipeline, architecture/training plan, and implementation notes in their current state — and flags what's still open.

> **For new sessions:** read CLAUDE.md (project status), V3_DESIGN.md (the heuristic this NN replaces and whose features inform this NN's inputs), MCTS_DESIGN.md (the consumer of this NN's outputs), and STRATEGY.md §5 (project-phase context for NN training).

**Document order.** Sections are arranged chronologically with the build order: overview → input format → label format → how data is generated → how the network is structured → how it's trained → how it's evaluated. Earlier sections are stable specs; later sections (§7 architecture, §8 training, §9 evaluation) are placeholders awaiting their own design rounds.

---

## 1. Goals and non-goals

### 1.1 Goals

- Train a **value-only** neural network that outputs an estimate of the score margin (P0 − P1) from a `GameState`.
- The network should be a **drop-in replacement** for `evaluate_hubris_v3` in MCTS (`agricola/agents/mcts.py`): same input/output contract, called the same way.
- Match or modestly exceed V3's playing strength as a standalone evaluator (1-turn lookahead) and as an MCTS leaf evaluator.
- Build the training infrastructure (data generation, training loop, eval) so subsequent phases (policy head, self-play data, larger architectures) can reuse it.

### 1.2 Non-goals

- **No policy head** in this version. Pure value network. PUCT and policy-guided MCTS come later.
- **No self-play data generation** in this version. Training data is generated from heuristic self-play (V1 + V3 + RandomAgent matchups). MCTS-self-play data and AlphaZero-style iteration are subsequent phases.
- **No imitation learning** from human game data. Per STRATEGY.md §5, that phase is deferred.
- **No cards.** Family game only, matching the rest of the engine.
- **No spatial CNN encoding of the farmyard.** Flat per-cell features only for this iteration; spatial encoding is a deliberate deferred design choice.

---

## 2. Strategic context

V3 is approaching its ceiling — additional CMA-ES tuning yields diminishing returns (see V3_TRAINING_PIPELINE.md). The bottleneck is the **evaluator paradigm**: V3 is a hand-designed feature combination, and its expressiveness is bounded by what was thought to encode. A neural network is the natural next step:

- Same features V3 uses → can it learn better combinations? (If yes: NN headroom comes from the combiner, not the features.)
- Richer features than V3 uses → does that help? (If yes: NN headroom comes from features V3 doesn't see.)

This first NN is designed to answer both questions. The input vector is a **superset** of V3's effective input (per §4), so improvements over V3 cleanly indicate where the gain lives.

**Phase ordering** (a → d roughly aligned with STRATEGY.md):

| Phase | What | Status |
|---|---|---|
| a | Supervised value NN, terminal-margin target | **This doc** |
| b | Richer state encoding (farmyard CNN, etc.) | Future |
| c | Policy head + PUCT in MCTS | Future |
| d | AlphaZero-style iterative self-play | Future |

---

## 3. Design principles

### 3.1 Input encoding is information-rich but flat

Include everything from V3's view plus the cheap obvious extras (accumulation amounts, action-space occupancy, stage cards revealed, mid-action context, harvest sub-phase indicators). Do NOT include things that require complex multi-step state extraction (full pending-stack contents below the top; full card-trigger registry state; spatial encoding of the farmyard).

The principle: include any feature that's cheap to compute and plausibly useful; skip features that complicate the encoder or are derivable trivially.

### 3.2 Pre-compute selectively

The principle is not "give the NN raw inputs and let it learn everything" — we do pre-compute some derived features (cooking rates, `food_owed_at_next_harvest`, breeding-pair indicators). It's not "pre-compute everything you can think of" either — that bakes in mistakes and wastes input slots.

The actual rule: **pre-compute a derivation when it meaningfully reduces learning burden, not by default.**

A derivation is worth pre-computing when ALL of these apply:

1. **Multi-step or lookup-shaped.** Cooking rates require a lookup over which majors are owned; `food_owed_at_next_harvest` requires combining harvest-distance, family-size, newborn-special-case, and per-person cost. These spend hidden-layer capacity if learned implicitly.
2. **Non-trivially nonlinear.** Sums, single-step products, and simple thresholds are not worth pre-computing — the first layer of an MLP handles them for free.
3. **Trustworthy.** A buggy or strategically-wrong derived feature actively misleads the network. If you wouldn't bet on the derivation being correct, include the raw inputs and let the NN derive its own version.

Concrete applications of the rule:

- **Include**: cooking rates (lookup over majors), `food_owed_at_next_harvest` (multi-step), breeding-pair indicators (combines animal count + capacity).
- **Skip**: `can_afford_X` (simple inequalities; trivially learnable from resources), `has_cooking_implement` (OR over majors-owned), crop-field pair counts (linear combination of the granular crop encoding).
- **Specifically excluded**: V3's `_food_term_hubris` output. Its derivation is multi-step but the author's own characterization is "janky" — fails the trustworthiness criterion. Its raw inputs (food, family, harvest distance, cooking rates, supply crops) are all included; the NN learns its own food-balance reasoning.

### 3.3 Mid-action states are encoded minimally

The pending stack is not encoded directly. Instead:
- `subaction_available`: a one-hot-set over the 7 sub-action category names, indicating what the active player could still choose to do this turn (active player only).
- `stop_is_legal`: bool.

This captures the relevant residual decision space without serializing stack contents. Singleton-Stop states (active parent, all subactions consumed) are never surfaced for evaluation thanks to the singleton-skip wrapper in `HeuristicAgent.__call__` and the MCTS expand path, so the all-zeros-flags ambiguity doesn't matter in practice.

Parent identity (which space the worker is mid-resolving at) is intentionally not encoded: in the Family game without card triggers, parent identity is path information rather than state information. The broader state encoding disambiguates the rare same-flag-vector-different-parent cases via differential resource/farmyard signals.

### 3.4 Supervision target: terminal margin

The training target for each (state, target) pair is the **score margin** at game end (P0 − P1), framed in the **current decider's** perspective at the state. This matches `_terminal_margin_value` in `agricola/agents/heuristic.py`. The terminal margin captures the actual game payoff, not V3's guess — so the NN can in principle exceed V3 even with V3-equivalent inputs.

**Alternatives considered:**

- **Win probability** (binary cross-entropy on win/loss). Throws away "how much you won by" — a 20-point win and a 2-point win are both "P0 wins" but very different positions. Bounded output is more robust to outliers; can be added later as a diagnostic ablation if margin-based training is unstable.
- **Multi-head (margin + win-prob).** One trunk, two output heads. The secondary head acts as an auxiliary loss that can help the trunk learn richer representations (KataGo-style). Mildly more complex; defer until v1 baseline is established.

Current choice: margin, MSE loss. **Normalize the margin target** during training (e.g., divide by an empirical stdev computed from the training set) so the optimizer sees a roughly-unit-scale signal; multiply back at inference. The normalization constants are baked into the model metadata.

---

## 4. Input encoding

The input vector has three groups: per-player features (mirrored for own and opponent), shared/board state, and active-player-only mid-action features.

All features are continuous-valued floats (binary flags encoded as 0.0 / 1.0). Normalization strategy is TBD (see §8).

### 4.1 Per-player features (×2: own player + opponent)

| Feature | Size | Notes |
|---|---|---|
| Resources (wood, clay, reed, stone, food) | 5 | Raw counts |
| `n_grain_fields_with_3`, `_with_2`, `_with_1` | 3 | Field-state-aware crop encoding |
| `n_veg_fields_with_2`, `_with_1` | 2 | Same |
| `n_empty_plowed_fields` | 1 | Plowed but unsown |
| `n_grain_supply`, `n_veg_supply` | 2 | In personal supply (not on fields) |
| Pasture capacities (5 slots, sorted descending, pad with 0) | 5 | Max 5 pastures per farmyard |
| `n_animal_slot_wildcards` | 1 | Sum of unfenced stables (each holds 1) + house pet slot (1) |
| `n_fenced_stables` | 1 | Separate from wildcards (scoring leaf: 1 pt each, max 4) |
| Animal counts (sheep, boar, cattle) | 3 | Raw counts |
| `n_wood_rooms`, `n_clay_rooms`, `n_stone_rooms` | 3 | Split encoding: scoring (1·clay + 2·stone) is a direct linear function of these. `n_rooms` is recoverable as the sum. In the Family game exactly one of these is nonzero at any time (renovation is all-or-nothing); the network learns the constraint implicitly. |
| `n_people`, `family_left_to_place_this_round`, `food_owed_at_next_harvest` | 3 | `n_people` = adults + newborns. `family_left_to_place_this_round` semantics: at a top-level `PlaceWorker` decision, includes the worker about to be placed (= total_workers − already_placed); mid-turn (worker already placed, resolving sub-actions), does NOT include the just-placed (= total_workers − already_placed_including_current); during harvest sub-phases, always 0. `food_owed` pre-computes harvest-feed math (adults × 2 + birth-round newborns × 1) and subsumes the adult/newborn split + harvest-distance reasoning. |
| `begging_markers` | 1 | Raw count; scoring penalty record |
| `n_unused_cells` | 1 | Farmyard cells not yet committed (scoring penalty: −1 each) |
| Cooking rates (sheep, boar, cattle, veg → food) | 4 | Lookup over majors owned; 0 if no cooking implement |
| Majors owned | 10 | Binary flag per major (indices 0-9 per `constants.MAJOR_IMPROVEMENT_COSTS` ordering) |
| Breeding-pair indicators (sheep, boar, cattle) | 3 | True iff ≥2 of that animal AND accommodation for newborn |
| Harvest-conversions-used (joinery, pottery, basketmaker) | 3 | The 3 once-per-harvest craft budgets |
| `is_starting_player` | 1 | Current SP (can change via Meeting Place) |
| `has_fed` | 1 | True iff this player has completed harvest feeding this harvest |
| `future_food_from_round_spaces` | 1 | Sum of Well-placed food on future round spaces owned by this player |

**Per-player total: ~54 features × 2 = ~108.**

### 4.2 Shared / board state

| Feature | Size | Notes |
|---|---|---|
| `round_number` | 1 | Raw 1-14 |
| `current_player` | 1 | 0 or 1; whose decision it is now |
| `in_harvest` | 1 | True iff phase ∈ {HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED} |
| `is_harvest_round_now` | 1 | True iff `round_number ∈ {4, 7, 9, 11, 13, 14}` |
| `accumulation_amounts` | 10 | Goods on each accumulation space (Forest, Clay Pit, Reed Bank, Fishing, Meeting Place, Sheep Market, Western Quarry, Pig Market, Cattle Market, Eastern Quarry) |
| `stage_cards_revealed` | 14 | Binary flag per stage card; permanents are always available so don't need a revealed bit |
| `space_available_now` | 25 | Binary per action space: 1 if revealed-and-not-occupied this round |
| `game_end_indicator` | 1 | 1 at `phase == BEFORE_SCORING`, 0 otherwise. See §4.5 for the zero-out rule on other features at terminal. |

**Shared total: ~54 features.**

### 4.3 Mid-action features (shared singletons, reflect active player)

A single copy of these features (not duplicated per-player), reflecting the active player's residual decision. In the Family game, `current_player == decider` always, so "active player" is unambiguous. All zeros when the pending stack is empty (no action in progress).

| Feature | Size | Notes |
|---|---|---|
| `subaction_available` | 7 | One bit per sub-action category. See computation rule below. |
| `stop_is_legal` | 1 | True iff `Stop` is in `legal_actions(state)`. Independent information from `subaction_available` for multi-shot pendings — e.g., mid-`PendingBuildStables` after one commit: `build_stables=1` AND `stop_is_legal=1`; before any commit: `build_stables=1` AND `stop_is_legal=0`. |

**Mid-action total: 8 features.**

#### `subaction_available` computation

The 7 sub-action categories: `build_rooms`, `build_stables`, `plow`, `bake_bread`, `sow`, `build_fences`, `build_major`.

**Computation rule** (OR across the full stack — captures "what could still happen this turn"):

1. Initialize the bit vector to all zeros.
2. For each pending frame in the stack:
   - If it's a **parent pending** with category-choice flags (`PendingGrainUtilization`, `PendingCultivation`, `PendingSideJob`, `PendingFarmExpansion`, `PendingHouseRedev`, `PendingFarmRedev`): set bits for each category whose `*_chosen` flag is False (still available to be chosen).
   - If it's a **sub-action pending** mid-resolving (`PendingBuildStables`, `PendingBuildRooms`, `PendingPlow`, `PendingBakeBread`, `PendingSow`, `PendingBuildFences`, `PendingBuildMajor`): set the bit for its own sub-action (it's "still happening").
3. The result is the union of "categories still to be chosen above us" and "the sub-action we're mid-resolving."

This gives the network a true "what's still possible this turn" signal rather than just "the immediate next decision."

**Excluded sub-actions and why:**

- **`renovate`**: only appears in `PendingHouseRedev` / `PendingFarmRedev`, which always resolve renovation first (mandatory). By the time any agent decision is needed at the parent, renovate is already done. The `CommitRenovate` itself is typically singleton (material choice is forced) so singleton-skip hides it from the agent.
- **`family_growth`**: only appears in `PendingBasicWish` / `PendingUrgentWish`. Singleton commit; never an agent decision.
- **Animal-market acquisitions** (Sheep/Pig/Cattle Market): atomic from the agent's perspective — one Pareto-frontier commit, no chain. The mid-action state is encoded indirectly via the worker-on-market-space signal.

### 4.4 Size summary

**Grand total: ~170 features.** Modest input size; standard MLP territory.

- Per-player × 2: ~108
- Shared/board: ~54 (includes `game_end_indicator`)
- Mid-action singletons: 8

### 4.5 Terminal-state encoding

Terminal states (`phase == Phase.BEFORE_SCORING`) appear in two contexts: (1) as training examples per §5.1, and (2) potentially at MCTS leaves if the search reaches a game-end state (e.g. late round 14 with Stop popping the last harvest pending). The encoder must handle them, but most of the per-decision features are meaningless at game end.

**Approach: zeros for next-decision features + a `game_end_indicator` bit** (the `game_end_indicator` feature on the shared/board state).

When the indicator is 1, the following features are forced to zero:

- `current_player` (no decider — game's over)
- `family_left_to_place_this_round` (no placements happening)
- `food_owed_at_next_harvest` (no next harvest)
- `in_harvest`, `has_fed`, `is_harvest_round_now` (no harvest)
- `future_food_from_round_spaces` (no future rounds)
- All mid-action features (`subaction_available`, `stop_is_legal`) (no pending stack at terminal)

Features that retain their values:

- Resources, animals, majors-owned, room counts, pasture capacities, etc. — these are the actual end-game state and the network needs them to compute the scoring function.
- `round_number` — 14 at terminal; not informative-by-zeroing.
- Accumulation amounts, worker occupancy, stage cards revealed — retained for consistency, though their relevance at terminal is weak.
- `begging_markers`, `n_unused_cells` — both contribute to scoring at terminal.

The network learns "when `game_end_indicator = 1`, ignore the zeroed features and treat the rest as a scoring-target setup." Mid-game examples (`game_end_indicator = 0`) form the bulk of training; terminal examples force the network to internalize the scoring function.

### 4.6 Encoding decisions explicitly considered and rejected

- **Spatial farmyard encoding** (3×5 grid with per-cell-type channels, fed to a CNN). Deferred — moderate upside, real architectural complexity, defer until non-spatial baseline is established.
- **Full pending-stack serialization**. Deferred — complex, low marginal value over `subaction_available + stop_is_legal`.
- **Card-trigger registry state** (`triggers_resolved`, etc.). Out of scope — Family game has no cards.
- **Worker occupancy as separate per-space-per-player encoding**. Collapsed into `space_available_now` — the differential info (who's where) doesn't matter absent card triggers.
- **`cooking_implement`/`baking_implement` bools** separate from majors-owned. Trivial OR over majors; the NN learns this.
- **`can_afford_X` indicators** (room, renovation, etc.). Trivial arithmetic; the NN learns this.
- **`_food_term_hubris` output as feature**. The function is "janky" (per author); inputs are included, derivation is left to the network.
- **Crop-field pair counts** (V3 input). Derivable from the granular crop encoding (per-state field counts + supply); the linear combination is cheap for the NN to learn.
- **`n_newborns` as separate count**. Folded into `food_owed_at_next_harvest`. The newborn count's only strategic role in the Family game is the 1-food-at-birth-round-harvest rule, which `food_owed` already accounts for. Newborns become adults at end-of-round, so post-harvest there's no separate signal worth preserving.
- **`stage_idx`** (1-6, derived from round). Dropped — `round_number` carries this info and stage-bracketing is a learnable nonlinearity.
- **`mid_action: bool`**. Dropped — the singleton-skip wrapper means active-parent-with-all-subactions-consumed states never reach evaluation; the all-zeros-flags ambiguity is invisible.

---

## 5. Supervision target

Training data: `(state, terminal_margin_from_decider_perspective)` pairs collected from heuristic self-play games.

For a game with terminal scores `(P0, P1)` and a state at decision-time-`t` whose decider is `d_t`:

```
target_t = score(d_t) - score(1 - d_t)
```

I.e., the eventual margin in the decider's frame at that state. This matches `_terminal_margin_value` semantics (the convention used by `evaluate_hubris_v3` at `Phase.BEFORE_SCORING`).

The NN outputs a single scalar: predicted margin in the decider's frame. Loss is MSE between predicted and actual margin.

**Target normalization.** During training, divide the target by an empirical scale factor (e.g., training-set stdev of margin) so the optimizer sees a roughly-unit-scale signal. At inference, multiply the output back. The normalization constant is baked into the model metadata so train and inference stay consistent.

See §3.4 for the discussion of alternative supervision targets (win-prob, multi-head).

### 5.1 Terminal-state training pairs

In addition to the per-decision (state, terminal_margin) pairs, each game contributes **one extra training pair from its terminal state** — `(terminal_state, exact_margin)`. The DataLoader expands a `GameRecord` into `N + 1` pairs: the `N` decision snapshots plus the terminal state.

The rationale:

- **Exact supervision signal.** At terminal, the margin IS the value (zero variance). Mid-game pairs are noisy — the same mid-state can lead to different terminal margins across game trajectories — whereas the terminal pair is deterministic and exact.
- **Late-game anchoring.** Without terminal examples, the NN's predictions on round-14 mid-action states (which are very close to terminal) may be poorly calibrated. Terminal examples anchor the high-confidence end of the value scale.
- **Hypothesis: learning the scoring rules helps mid-game prediction.** Training on terminal states forces the NN to internalize the scoring function (fields → 0/1/2/3/4 pts per the bracket, animals → bracketed, begging → −3 each, etc.). This understanding plausibly transfers back to mid-game evaluation — the NN can better reason about "what does it mean to have 4 fields here?" if it has learned the scoring brackets at terminal.
- **AlphaZero precedent.** Standard practice in value-net training.

Cost is negligible — one extra training pair per game against ~30-60 decision pairs already. ~2% data growth.

See §4.5 for how the encoder represents terminal states.

---

## 6. Data generation

The data pipeline produces `GameRecord` pickles via heuristic self-play. This is the section most fleshed out today — the encoder, model, training, and evaluation sections below remain placeholders.

### 6.1 Generation agents

Each game independently draws P0's config and P1's config from a small pool of "approved generation configs," with replacement. Temperatures are drawn **independently per agent** from a bimodal distribution: with 95% probability, uniform from [0.3, 1.0] (skilled-play mode); with 5% probability, fixed at T=4 (exploration mode). `restricted_legal_actions` ON for both seats (matches V1's tuning context).

Implied per-game mixture: ~90% of games have both agents in skilled mode, ~9.5% have one exploring + one skilled (the "explorer vs skilled" games, probably the most useful for state diversity), ~0.25% have both exploring. The bimodal shape avoids the "no man's land" of moderate-high temperatures that have neither great labels nor maximum diversity.

Approved pool (initial):
- V1 with `CONFIG_V1_T2` (the V1 round-2-tuned config)
- 3-5 of the strongest V3 configs from the iterative tuning pipeline (current `v3_best.json` plus the next-strongest candidates from `tuned_configs/`)

Rationale for mixed configs over single-config self-play:
- Agent performance among V1_T2 and the V3 candidates is not fully transitive (rock-paper-scissors patterns), so no single config is canonical.
- The NN's deployment context is MCTS — which explores states the data-generating agent wouldn't necessarily reach. Broader training distribution → better generalization.
- Future self-play loops will produce multi-source data anyway; building the pipeline to handle that now means it doesn't need to change later.

### 6.2 Snapshot semantics

A snapshot is recorded every time an agent's `__call__` is invoked with a non-singleton state. This naturally excludes:
- Singleton-action states (singleton-skip never invokes the agent on them)
- Terminal states (`Phase.BEFORE_SCORING`)
- States resolved by `_advance_until_decision` without agent intervention

Mid-action states are INCLUDED (Cultivation/Grain-Util sub-decisions, etc.) — the NN will be called on these during MCTS expansion, so it needs training examples for them.

Per snapshot, store:

```python
@dataclass(frozen=True)
class DecisionSnapshot:
    state: GameState
    chosen_action: Action  # for future policy-head training; cheap to include now
    decider_idx: int       # 0 or 1
```

Per game, store:

```python
@dataclass(frozen=True)
class GameRecord:
    data_version: int
    game_idx: int
    seed: int
    p0_config_path: str   # reference, not embedded — configs are versioned artifacts already
    p1_config_path: str
    p0_temperature: float   # drawn independently per agent (broader (T0, T1) coverage)
    p1_temperature: float
    p0_final_score: int
    p1_final_score: int
    winner: int | None    # 0, 1, or None for true tie (scores equal AND tiebreaker equal)
    terminal_state: GameState   # phase == BEFORE_SCORING. Used as an extra
                                 # training pair (§5.1) and as source of truth
                                 # for any game-end-derivable quantity
                                 # (score breakdown, tiebreaker, audit).
    decisions: tuple[DecisionSnapshot, ...]
```

Notes:
- Store raw `GameState`, not pre-encoded — lets the encoder evolve without regenerating data.
- Store final scores (P0 and P1), not "margin from decider perspective" — margin in any frame is derivable.
- Store `winner` explicitly (derivable from `terminal_state` but useful as a non-ambiguous direct signal for analytics over tied-score games).
- `data_version` integer in the schema; bumped on any change to the `GameRecord` shape (see §11.4). Loader refuses mismatched versions.

No sampling at generation time — every agent-call state is saved. Sub-sampling for training happens at DataLoader time, decoupled from the dataset.

### 6.3 File format & directory layout

Directory per generation run:

```
data/nn_training/runs/<run_id>/
    games/
        worker_00.pkl    # list[GameRecord] from worker 0
        worker_01.pkl
        ...
        worker_07.pkl    # one pickle per parallel worker
    metadata.json        # run-level metadata
```

`<run_id>` = ISO-8601 timestamp + short hash. Each generation invocation produces one new run directory; runs accumulate over time.

Per-worker batching (not per-game files) avoids the "tens of thousands of small files" pathology while keeping parallelism. Each worker incrementally re-writes its `.pkl` after each completed game (so an interrupted run doesn't lose work).

Format: pickle. Frozen dataclasses serialize natively. Pickle's caveats (version sensitivity if the `GameRecord` schema changes, no untrusted-source safety) are acceptable for our own data.

`metadata.json` schema:

```json
{
    "run_id": "20260527-abc123",
    "code_sha": "...",
    "host": "...",
    "approved_configs": ["tuned_configs/1779468329.json", "tuned_configs/v3_best.json", ...],
    "temperature_range": [0.3, 1.0],
    "restricted": true,
    "n_workers": 8,
    "planned_games": 5000,
    "completed_games": 5000,
    "errored_games": [],
    "base_seed": 1234567,
    "data_version": 1
}
```

### 6.4 Resume on existing data

The generation script supports resuming an interrupted run cleanly:

1. At the start of a run, deterministically pre-compute the full plan: `[(game_idx, seed, p0_config_path, p1_config_path, temperature), ...]` for all planned games. Save the plan in `metadata.json` on first invocation.
2. Workers are assigned contiguous slices of the plan (worker 0 → games 0-624, worker 1 → games 625-1249, ...).
3. On startup, each worker checks if its `worker_NN.pkl` exists. If so, load it and identify which `game_idx`s in its assigned range are already complete; skip those.
4. Worker plays remaining games and incrementally re-writes its `.pkl` after each one (so progress isn't lost again).

Re-running the same script after an interruption resumes from where it stopped. To extend an existing run (add more games), change the plan's target count and rerun — workers regenerate the plan, find the new entries, and produce only those.

### 6.5 Error handling

Per-game errors (engine bugs, unexpected states) are caught, logged with the failing game's seed and configs, and skipped. The run continues. The failed `game_idx` is recorded in `metadata.json` under `errored_games` for later investigation.

### 6.6 Validation pass

After generation, a separate `scripts/validate_nn_dataset.py` script loads N random records and asserts invariants:

- `data_version` matches the loader's current version
- `chosen_action ∈ legal_actions(state)` for each snapshot (engine consistency)
- `state.phase != Phase.BEFORE_SCORING` (no terminal snapshots saved)
- `len(decisions) > 0` (no empty games)
- Game-final scores match the labeled `p0_final_score` / `p1_final_score` (cross-check that no scoring drift snuck in between recording and labeling)

Failing the validation halts and reports specific game files for investigation.

### 6.7 Volume targets

Tiered approach:

1. **Pipeline-check run**: 50-100 games. ~3-5 minutes on 8 workers. Verify file layout, schema, basic invariants. Catches schema bugs cheap.
2. **Sanity-check run**: 500-1000 games. ~30-60 min. Spot-check records by eye; verify per-config distribution looks right; confirm `validate_nn_dataset.py` passes on a real-sized dataset.
3. **Production run**: 5000 games initially, scaling up to 10k-20k once the pipeline is validated and the architecture is ready.

Don't move on to architecture work until the 500-game run produces clean data.

### 6.8 Determinism

Each game's seed is `base_seed + game_idx`, with `base_seed` recorded in `metadata.json`. Given the same `metadata.json` and the same code SHA, the dataset is fully reproducible. Useful for debugging and for answering "did I regenerate or am I using stale data?"

---

## 7. Architecture (TBD)

**This section is a placeholder.** The architecture has not been designed yet.

Initial expectations:
- Multi-layer perceptron with 2-3 hidden layers
- Hidden width: 256-512
- Modern activation (SiLU / GELU)
- Layer norm or batch norm between layers (TBD)
- Single scalar output head, no nonlinearity on the output (raw margin)
- PyTorch framework (per STRATEGY.md decision)

To be designed:
- Exact depth and width
- Activation choice
- Normalization layer choice and placement
- Whether to use residual blocks
- Output head form (e.g., does it predict raw margin, normalized margin, tanh-bounded margin?)
- Input normalization / standardization scheme

---

## 8. Training (TBD)

This section is a placeholder pending architecture decisions. Items still to specify:

- Optimizer (Adam / AdamW), learning rate, weight decay
- Batch size, number of epochs, early stopping rule
- Train/val/test split by GAME (not by state — leakage). Proportions TBD.
- Checkpointing strategy
- Sub-sampling strategy at DataLoader time (every N-th snapshot per game vs K-per-game vs all)
- Loss function (MSE vs Huber)
- Normalization scheme (per-feature standardization computed from training split; baked into model metadata)
- Augmentations, if any (note: player-swap is NOT a free symmetry due to SP starting-food asymmetry)

---

## 9. Evaluation (TBD)

**This section is a placeholder.** Evaluation criteria are not fully designed yet.

Candidate metrics:
- **Held-out MSE / MAE** on (state, terminal_margin) pairs from games not used in training.
- **Match performance**: paired head-to-head matches of an `NNAgent` (1-turn lookahead, using the NN as evaluator) against `HubrisHeuristicV3` and `HubrisHeuristicV1` (with `CONFIG_V1_T2`). Win rate and average margin over N games (∼200 is sufficient given variance).
- **Drop-in MCTS performance**: replace `evaluate_hubris_v3` with the NN inside `MCTSSearch.evaluate_leaf` and run matches against the current MCTS variants (`scripts/play_mcts_match.py`).
- **Calibration**: scatter plot of predicted-margin vs actual-margin on the held-out set; ideal calibration is the identity line.

Success criteria (initial targets, subject to revision):
- NN-1-turn-lookahead is statistically indistinguishable from or stronger than V3 standalone (≥0 average margin in 200-game match).
- NN-MCTS at 200 sims is statistically indistinguishable from or stronger than V3-MCTS at the same sim count.

---

## 10. Open questions

- **Architecture sizing**: depth/width/normalization, see §7.
- **Training data volume**: how many games / state-snapshots are needed for the NN to plausibly match V3? Educated guess: 100k-1M (state, margin) pairs.
- **Normalization**: per-feature standardization (zero mean, unit variance using training-set statistics) vs raw inputs. Standardization is the default safe choice but adds a fixed-stats artifact to be carried with the model.

---

## 11. Implementation notes

### 11.1 File layout

The NN code lives in a subpackage at `agricola/agents/nn/`. Splitting into modules keeps each concern small and lets the schema/recording code stay PyTorch-free (so data-generation scripts don't need to import torch).

Implemented today:

- `agricola/agents/nn/schema.py` — `DATA_VERSION`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `load_game_records`, `compute_winner`. No PyTorch dependency.
- `agricola/agents/nn/recording.py` — `play_recording_game`. Depends on engine + Agent protocol. No PyTorch dependency.
- `agricola/agents/nn/encoder.py` — `ENCODING_VERSION` (version constant only today). `encode_state` is TBD; will be added once the architecture is locked in. Future PyTorch dependency.
- `agricola/agents/nn/__init__.py` — re-exports the public surface so external code can use `from agricola.agents.nn import GameRecord` etc.
- `scripts/generate_nn_training_data.py` — orchestrates heuristic self-play via the 8-config ensemble from `tuned_configs/DATA_GEN_ENSEMBLE.md`. Multiprocessing pool, deterministic plan, bimodal per-agent temperature draws, atomic per-game pickle writes, resume-on-existing per §6.4.
- `scripts/validate_nn_dataset.py` — post-generation invariant checker (§6.6). Supports random-sample validation for huge datasets via `--sample-size`. Failure reports group by check type and locate the offending game_idx + snapshot.

Planned but not yet implemented:

- `agricola/agents/nn/model.py` — `FirstNNValueModel` (PyTorch `nn.Module`).
- `agricola/agents/nn/agent.py` — `NNAgent` (Agent-protocol wrapper using the model).
- `scripts/train_first_nn.py` — PyTorch training loop. Reads training data, trains, checkpoints.
- `scripts/eval_first_nn.py` — matches NNAgent vs baselines, reports MSE / win-rate / margin.

Data and model artifacts:

- `data/nn_training/runs/` — generated datasets, organized by run.
- `nn_models/` — trained checkpoints + metadata sidecars.

### 11.2 Determinism

- Training is non-deterministic by default (CUDA + cuDNN). Capture and log seeds for reproducibility.
- Inference must be deterministic given a fixed model — verify with a smoke test.
- Data generation IS deterministic given (code SHA, configs, base seed) — see §6.8.

### 11.3 Persistence format

- Model: `torch.save(model.state_dict(), path)` — state dict only, not full pickle (lets us evolve the model class).
- Metadata: JSON sidecar with hyperparameters, training data hashes, **`ENCODING_VERSION`** and **`DATA_VERSION`** (see §11.4), normalization stats, code-commit SHA.

### 11.4 Schema versioning

Two parallel version counters guard against silently-broken inference / loading. They are independent — encoding can evolve while the dataset schema stays stable, or vice versa.

#### `ENCODING_VERSION`

A trained NN has a fixed input shape and feature ordering baked into its first layer's weights. If `encode_state` later changes (a feature added, removed, reordered, or its normalization tweaked), an old checkpoint loaded into the new code path will either fail with a shape mismatch (if you're lucky) or silently produce wrong predictions (if you're not). `ENCODING_VERSION` is the dead-simple protocol that prevents this.

Mechanism:

1. Define `ENCODING_VERSION: int` as a module-level constant in `agricola/agents/nn/encoder.py` (where `encode_state` will live). Start at `1`.
2. At training time, write `ENCODING_VERSION` into the model's JSON metadata sidecar.
3. At load time, compare the sidecar's recorded version to the current `ENCODING_VERSION`. Refuse to load if they don't match; raise a clear error.
4. Bump `ENCODING_VERSION` whenever a change to `encode_state` would cause it to produce different output for the same input state.

**Bump policy:** the load-bearing part. **If the function's output for the same input differs in any way, bump.** Includes adding/removing/reordering features, changing normalization parameters, and changing the semantics of any existing feature. Does NOT include refactors that preserve numerical output. When in doubt, bump.

**Optional refinement:** maintain a CHANGES-style log of what each version added/removed/changed (inline near `ENCODING_VERSION` or in a dedicated section here). Makes it possible to write a one-off translator if you ever want to evaluate an older checkpoint against a newer engine without retraining.

**Initial version:** `ENCODING_VERSION = 1` corresponds to the input vector specified in §4.

#### `DATA_VERSION`

Parallel mechanism for the on-disk dataset schema. `GameRecord` and `DecisionSnapshot` are pickled to disk; changing their shape (adding a field, renaming, reordering) can silently corrupt loading of old pickles or — worse — succeed with garbage fields.

Mechanism mirrors `ENCODING_VERSION`:

1. Define `DATA_VERSION: int` as a module-level constant in `agricola/agents/nn/schema.py` (alongside `GameRecord`). Start at `1`.
2. Every generated `GameRecord` stamps the current `DATA_VERSION` into its own `data_version` field.
3. The dataset loader (`scripts/validate_nn_dataset.py` and the training-time loader) compares each `GameRecord.data_version` against the current `DATA_VERSION`. Mismatched records raise a clear error.

**Bump policy:** increment whenever the `GameRecord` or `DecisionSnapshot` schema changes in a way that affects on-disk shape. Adding a field bumps. Renaming a field bumps. Adding a new entry to a stored union type bumps.

**Initial version:** `DATA_VERSION = 1` corresponds to the schema specified in §6.2.

---

## 12. Status

Current state:

- Input encoding specified (§4)
- Supervision target chosen (§5)
- Data generation pipeline specified AND implemented (§6, §11.1)
- Schema versioning protocol defined (§11.4)
- **Code implemented:**
  - `agricola/agents/nn/{schema,recording,encoder,__init__}.py` — schema dataclasses + recording driver + `ENCODING_VERSION` placeholder + public-surface re-exports
  - `scripts/generate_nn_training_data.py` — batch generator with multiprocessing pool, resume-on-existing, atomic per-game writes, bimodal per-agent temperature draws, deterministic planning
  - `scripts/validate_nn_dataset.py` — post-generation invariant checker (§6.6) with optional random sampling
- **Tests:** 41 new NN-related tests (16 schema/recording + 15 batch generator + 10 validation script). Full suite: 797 passing.
- **Datasets on disk:**
  - 50-game pipeline-check run (validated, all checks pass)
  - 1000-game sanity-check run (validated, all checks pass, 48 MB, 131s wall time on 8 workers)
  - 5000-game production run (in progress / completed depending on when you're reading this)

Outstanding:

- Architecture (§7), training section (§8), and evaluation criteria (§9) remain placeholders for subsequent design sessions.
- Encoder module (`agricola/agents/nn/encoder.py` currently holds only `ENCODING_VERSION`; `encode_state` itself is unimplemented pending architecture decisions).
- Model module (`agricola/agents/nn/model.py`).
- Agent-wrapper module (`agricola/agents/nn/agent.py`).
- Training script (`scripts/train_first_nn.py`).
- Evaluation script (`scripts/eval_first_nn.py`).
