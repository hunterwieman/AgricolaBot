# First NN — AgricolaBot

Design spec for the first neural network value function for AgricolaBot. The goal: a learned drop-in replacement for `evaluate_hubris_v3` as the leaf evaluator in MCTS, with a higher ceiling than V3's hand-crafted linear-combiner form.

This is the working spec for the initial NN phase. It captures the input encoding, supervision target, data generation pipeline, architecture/training plan, and implementation notes in their current state — and flags what's still open.

> **For new sessions:** read CLAUDE.md (project status), V3_DESIGN.md (the heuristic this NN replaces and whose features inform this NN's inputs), MCTS_DESIGN.md (the consumer of this NN's outputs), and STRATEGY.md §5 (project-phase context for NN training).

**Document order.** Sections are arranged chronologically with the build order: overview → input format → label format → how data is generated → how the network is structured → how it's trained → how it's evaluated → implementation notes → experiments → status → open questions. The design and implementation are complete for phase (a); §11 Experiments tracks planned and completed experiments (with stable `P#`/`C#` IDs) and §13 Open questions captures what remains.

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

**Output type: `np.ndarray` (float32), not `torch.Tensor`.** The encoder is numpy-only, which keeps the whole `agricola.agents.nn` package torch-free (only the eventual `model.py` imports torch). The training pipeline converts with `torch.from_numpy(arr)` at the model boundary — trivial and cheap. This preserves the §10.1 import-cost property: importing the package for data generation never pulls torch.

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
| Breeding-pair indicators (sheep, boar, cattle) | 3 | True iff ≥2 of that animal AND the farm can accommodate one more of it. **Independent** per type: each checked as if it's the only one breeding (i.e. `can_accommodate(caps, flex, ...this type +1...)`), not jointly. This deliberately differs from V3's `_v3_breeding_pair_counts`, which shares one capacity budget across types by priority. The independent version gives the NN raw per-type readiness and lets it learn the joint constraint from the capacity features. |
| Harvest-conversions-used (joinery, pottery, basketmaker) | 3 | The 3 once-per-harvest craft budgets |
| `is_starting_player` | 1 | Current SP (can change via Meeting Place) |
| `has_fed` | 1 | True iff this player has completed harvest feeding this harvest |
| `future_food_from_round_spaces` | 1 | Sum of Well-placed food on future round spaces owned by this player |

**Per-player total: ~54 features × 2 = ~108.**

### 4.2 Shared / board state

| Feature | Size | Notes |
|---|---|---|
| `round_number` | 1 | Raw 1-14 |
| `current_player_is_own` | 1 | 1.0 iff it's the perspective player's turn (`state.current_player == player_idx`). Perspective-relative rather than a raw 0/1 index, consistent with the own/opp block framing. |
| `in_harvest` | 1 | True iff phase ∈ {HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED} |
| `rounds_until_next_harvest` | 1 | Distance to the next harvest round (0 on a harvest round). Sawtooth in `round_number`, non-monotonic — a textbook pre-compute candidate (§3.2). Replaces the earlier `is_harvest_round_now` bit, which it subsumes (`== 0`). Complements `food_owed` (magnitude) with timing. |
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
- `in_harvest`, `has_fed`, `rounds_until_next_harvest` (no harvest pending)
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

The data pipeline produces `GameRecord` pickles via heuristic self-play. This is the section that was specified first and most thoroughly; the encoder, model, training, and evaluation pieces (§7-9) were built and validated against the §6.6 invariants.

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
- `data_version` integer in the schema; bumped on any change to the `GameRecord` shape (see §10.4). Loader refuses mismatched versions.

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

After generation, a separate `scripts/nn/validate_dataset.py` script loads N random records and asserts invariants:

- `data_version` matches the loader's current version
- `chosen_action ∈ legal_actions(state)` for each snapshot (engine consistency)
- `state.phase != Phase.BEFORE_SCORING` (no terminal snapshots saved)
- `len(decisions) > 0` (no empty games)
- Game-final scores match the labeled `p0_final_score` / `p1_final_score` (cross-check that no scoring drift snuck in between recording and labeling)

Failing the validation halts and reports specific game files for investigation.

### 6.7 Volume targets

Tiered approach:

1. **Pipeline-check run**: 50-100 games. ~3-5 minutes on 8 workers. Verify file layout, schema, basic invariants. Catches schema bugs cheap.
2. **Sanity-check run**: 500-1000 games. ~30-60 min. Spot-check records by eye; verify per-config distribution looks right; confirm `validate_dataset.py` passes on a real-sized dataset.
3. **Production run**: 5000 games initially, scaling up to 10k-20k once the pipeline is validated and the architecture is ready.

Don't move on to architecture work until the 500-game run produces clean data.

### 6.8 Determinism

Each game's seed is `base_seed + game_idx`, with `base_seed` recorded in `metadata.json`. Given the same `metadata.json` and the same code SHA, the dataset is fully reproducible. Useful for debugging and for answering "did I regenerate or am I using stale data?"

---

## 7. Architecture

The phase-(a) NN is a flat MLP value function — `state vector (170) → margin estimate (1)`. Intentionally simple to validate the full pipeline (data → encoder → model → evaluator → agent → match) before layering on structure. Implemented in `agricola/agents/nn/model.py`.

**Default architecture** (locked as the `ConfigurableMLP` defaults):

| Component | Choice |
|---|---|
| Topology | MLP, two hidden layers |
| Hidden widths | `[256, 256]` |
| Activation | GELU |
| Normalization | LayerNorm between layers |
| Dropout | 0.0 (no regularization in v1; revisit when val curve overfits) |
| Output head | Single scalar, no nonlinearity (raw margin in normalized space) |
| Total parameters | 110,849 |
| Framework | PyTorch |

LayerNorm was chosen over BatchNorm because MCTS-leaf inference is single-state (batch size 1), which BatchNorm handles poorly. Residual blocks were skipped because the network is shallow (2 hidden layers); they'd be worth revisiting only at 8+ layers (§7.1).

**Input/output normalization** lives in `NormalizedValueModel`, a wrapper module that registers fixed `input_mean`, `input_std`, and `target_std` buffers populated from a `NormStats` fit on the training split only. `forward(x)` returns normalized output (used in training MSE); `predict_margin(x)` denormalizes for inference. Burying normalization in the model means consumers can't forget to apply it and `.to(device)` moves the stats along with the weights.

**Antisymmetric inference via the differential wrapper.** The model itself learns from both perspectives via dual-perspective augmentation (§8.A), but there's no architectural guarantee that `V(s, 0) = −V(s, 1)` exactly. The `nn_evaluator_differential` wrapper in `agricola/agents/nn/agent.py` enforces exact antisymmetry at inference: encodes both perspectives, runs ONE batched-2 forward pass, returns `V(s, 0) − V(s, 1)` in P0's frame (`−V_diff` in P1's). This is the runtime analog of `make_differential_evaluator` for V3.

`ConfigurableMLP` is composable: pass `output_dim` other than 1 and it works as a sub-encoder. That's the seed of the §7.1 structured-architecture directions, which will reuse the same module as a building block.

### 7.1 Future / structured architecture directions (beyond the flat MLP)

The phase-(a) `ConfigurableMLP` treats the input as an unstructured flat vector — a universal approximator, but with no architectural prior for structure in the input. These are the structured variants worth pursuing once the flat baseline is established. Each is a *better inductive bias*, not a representability gain.

- **Shared per-player encoder (Siamese).** The own and opp blocks share identical feature layout. A shared sub-network `φ` could process each block with the *same weights* (`h_own = φ(own_block)`, `h_opp = φ(opp_block)`), then combine (`concat`, or the difference `h_own − h_opp`, or both sum and difference). Halves the per-player encoder parameters and biases the model toward treating players symmetrically. See §8 (Training) for the data-level and inference-level symmetry options that compose with this.

- **Spatial CNN over the farmyard.** The 3×5 grid has real spatial structure (field/pasture adjacency, room chaining). A small CNN with one channel per cell type (`(channels, 3, 5)`) would exploit locality/adjacency automatically instead of forcing the MLP to learn it from flat per-cell features. This is the phase-b encoding change flagged in §1.2 / §4.6 — it changes the *encoder output shape*, but not the training loop.

- **Antisymmetric output construction.** Build the value head so `V(state from P0) = −V(state from P1)` *exactly* by construction (e.g., `V = f(own, opp, shared) − f(opp, own, shared)`), enforcing the true antisymmetry of a zero-sum margin. The architectural analog of the existing `make_differential_evaluator` wrapper. See §8.

- **Multi-head outputs.** Value + win-probability, or (phase c) value + policy. A shared trunk with two heads; the secondary head acts as an auxiliary loss (§3.4). Changes the model class, not the training infrastructure.

---

## 8. Training

Implemented in `agricola/agents/nn/training.py`; the thin CLI wrapper is `scripts/nn/train_first.py`.

### 8.1 Pipeline

1. Load `GameRecord`s from one or more run directories via `load_all_games_from_runs`.
2. Split games **by index** (80/10/10 train/val/test, deterministic via `--split-seed`). Splitting by game — not by snapshot — prevents the same game's terminal-margin from leaking between splits.
3. Expand each game into descriptors:
   - Per non-singleton snapshot: 2 dual-perspective descriptors (§8.A).
   - Per terminal state: 2 dual-perspective descriptors (§5.1).
4. Pre-encode the chosen descriptors once into a dense `float32` numpy array via `encode_state`. DataLoader access is then array slicing, not a per-call encode.
5. Fit `NormStats` (per-feature input mean/std + scalar target_std) on the **training arrays only**; never peek at val/test.
6. Build three `AgricolaValueDataset`s and the `NormalizedValueModel`; train.

### 8.2 Hyperparameters

The reference model (Experiment C1) used:

| Knob | Value | Rationale |
|---|---|---|
| Optimizer | AdamW | Standard for MLPs; decoupled weight decay |
| Learning rate | 1e-3 | Plain default |
| Weight decay | 0.0 | First run; revisit if val curve creeps (it does — see Experiment C1; addressed in C5/C6) |
| Batch size | 512 | Whole training set fits in RAM, so batching is purely a noise/throughput knob |
| Loss | MSE on normalized targets | Targets divided by `target_std` so the loss scale doesn't depend on the data |
| Max epochs | 50 | Cap; never reached |
| Early stopping | val MSE patience = 10 | Restore best-val weights at end |
| Train fraction | 0.8 |  |
| Val fraction | 0.1 | Test = remainder (0.1) |
| Sub-sampling | None (all train descriptors) | 727k examples is small enough |

### 8.A Dual-perspective augmentation (the load-bearing trick)

For each non-singleton snapshot and each terminal state, **both** perspectives are added as training pairs: `(encode(s, 0), p0_margin)` and `(encode(s, 1), p1_margin)`. This is NOT a naive raw-state player-swap — it's a re-encoding of the same position from the other player's view, with SP asymmetry correctly preserved by per-player features (`is_starting_player`, starting-food deltas) and perspective-relative shared features (own/opp ordering). Both examples are valid, exact training pairs.

Effect: doubles the data and balances the `current_player_is_own` feature. (An earlier draft of this doc incorrectly called the swap an invalid symmetry; it's valid *when done via re-encoding*, which `encode_state(state, 1 − decider)` already does.)

Composes cleanly with the §7 differential-inference wrapper: training (§8.A) makes both perspectives valid examples; inference (the D wrapper) makes the answer antisymmetric by construction. Together they give a model that has *seen* both perspectives and *answers* antisymmetrically.

### 8.3 Outputs

Each `train(...)` invocation writes:

- `best.pt` — best-val checkpoint (state dict + `NormStats` buffers)
- `best.meta.json` — architecture config, `encoding_version`, hyperparams
- `train_log.jsonl` — per-epoch train/val MSE
- `train_curves.png` — train/val MSE plotted over epochs
- `calibration.png` — predicted-margin vs actual-margin scatter on held-out test
- `test_metrics.json` — final test MSE/MAE in raw-margin units
- `config.json` — full run configuration for reproducibility
- `norm_stats.json` — separate copy of `NormStats` as JSON

---

## 9. Evaluation

### 9.1 Methodology

Four metrics, in increasing order of "what actually matters":

- **Held-out MSE / MAE** on (state, terminal_margin) pairs from games never seen during training (the test split). Standard regression metric; useful for tracking model improvements without paying per-match cost.
- **`NNAgent` vs the 8-config data-gen ensemble.** Round-robin (100 games per opponent) via `scripts/nn/eval_vs_ensemble.py`. Aggregated win rate + average margin. Tests whether the NN matches a "median trained heuristic" on its own training distribution.
- **`NNAgent` vs `HubrisHeuristicV1` (with `CONFIG_V1_T2`).** The project's standalone-strongest agent. Tests whether the NN matches the best hand-crafted evaluator (the bar is high — V1 is the head-to-head winner against every V3 to date).
- **MCTS-NN vs NNAgent-1-turn.** Same model on both sides, MCTS at varied sim budgets vs greedy 1-turn lookahead. Run via `scripts/nn/play_match.py --p0 mcts --p1 nn`. Isolates the lift (or regression) tree search provides on top of the learned evaluator.
- **Calibration plot.** Predicted-margin vs actual-margin scatter on the test set; ideal is the identity line. A flatter line indicates the model is regressing toward the mean (predicting too conservatively).

### 9.2 Measured outcomes

Full results in §11. Headline figures:

- Test MAE = **6.87 points** (Experiment C1; best to date **6.73** at C6)
- `NNAgent` vs 8-config ensemble: **~60% aggregate win rate**; beats every V3 opponent; ties `t2` (V1) (Experiment C2)
- MCTS-NN-500 vs `NNAgent`-1-turn: **68-32, +3.54 avg margin**, p < 0.001 (Experiment C3)

### 9.3 Success criteria — design-phase targets, evaluated post-hoc

| Criterion (from design phase) | Outcome |
|---|---|
| NN-1-turn-lookahead ≥ V3 standalone (≥0 avg margin, 200-game match) | **Passed** — beats every V3 in the ensemble (Experiment C2) |
| NN-MCTS at 200 sims ≥ V3-MCTS at the same sim count | **Inverted finding** — V3-MCTS regressed against V3-standalone; NN-MCTS *lifts* against NN-standalone. The "≥ V3-MCTS" comparison is moot because V3-MCTS itself was below V3-standalone (Experiment C4). |

Outstanding evaluation work is itemized in §11.1 (planned experiments).

---

## 10. Implementation notes

### 10.1 File layout

The NN code lives in a subpackage at `agricola/agents/nn/`. Splitting into modules keeps each concern small and lets the schema/recording code stay PyTorch-free (so data-generation scripts don't need to import torch).

Implemented today:

- `agricola/agents/nn/schema.py` — `DATA_VERSION`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `load_game_records`, `compute_winner`. No PyTorch dependency.
- `agricola/agents/nn/recording.py` — `play_recording_game`. Depends on engine + Agent protocol. No PyTorch dependency.
- `agricola/agents/nn/encoder.py` — `encode_state(state, player_idx) -> np.ndarray` (float32, length `ENCODED_DIM = 170`), `ENCODING_VERSION`, `feature_names()`. Numpy-only (no torch). Implements the §4 spec including the OR-across-stack `subaction_available` walk and terminal-state zeroing. The `feature_names()` list doubles as the terminal-zeroing key set and as a debugging/golden-test aid.
- `agricola/agents/nn/dataset.py` — `build_datasets(run_dirs, *, train_sample_size, train_frac, val_frac, ...)` → `(train_ds, val_ds, test_ds, NormStats)`. Loads `GameRecord` pickles, by-game train/val/test split, expands each snapshot into 2 dual-perspective examples + 2 terminal pairs per game (§5.1 + the A augmentation from §8), random-pool sampling for the train split (decorrelates batches; val/test use all for low-variance metrics), pre-encodes once into `float32` arrays for fast DataLoader access. `NormStats` (per-feature input mean/std + target std) is computed on the training split only, persisted alongside the model. Imports torch — not re-exported from `__init__.py` to preserve the torch-free data-generation path; explicit `from agricola.agents.nn.dataset import ...` required.
- `agricola/agents/nn/__init__.py` — re-exports the public surface so external code can use `from agricola.agents.nn import GameRecord` etc.
- `scripts/nn/generate_training_data.py` — orchestrates heuristic self-play via the 8-config ensemble from `tuned_configs/DATA_GEN_ENSEMBLE.md`. Multiprocessing pool, deterministic plan, bimodal per-agent temperature draws, atomic per-game pickle writes, resume-on-existing per §6.4.
- `scripts/nn/validate_dataset.py` — post-generation invariant checker (§6.6). Supports random-sample validation for huge datasets via `--sample-size`. Failure reports group by check type and locate the offending game_idx + snapshot.

Planned but not yet implemented:

- `agricola/agents/nn/model.py` — `FirstNNValueModel` (PyTorch `nn.Module`).
- `agricola/agents/nn/agent.py` — `NNAgent` (Agent-protocol wrapper using the model).
- `scripts/nn/train_first.py` — PyTorch training loop. Reads training data, trains, checkpoints.
- `scripts/nn/eval_vs_ensemble.py` — matches NNAgent vs baselines, reports MSE / win-rate / margin.

Data and model artifacts:

- `data/nn_training/runs/` — generated datasets, organized by run.
- `nn_models/` — trained checkpoints + metadata sidecars.

### 10.2 Determinism

- Training is non-deterministic by default (CUDA + cuDNN). Capture and log seeds for reproducibility.
- Inference must be deterministic given a fixed model — verify with a smoke test.
- Data generation IS deterministic given (code SHA, configs, base seed) — see §6.8.

### 10.3 Persistence format

- Model: `torch.save(model.state_dict(), path)` — state dict only, not full pickle (lets us evolve the model class).
- Metadata: JSON sidecar with hyperparameters, training data hashes, **`ENCODING_VERSION`** and **`DATA_VERSION`** (see §10.4), normalization stats, code-commit SHA.

### 10.4 Schema versioning

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

**Version history:**
- `v1` — initial encoder per §4. Bug: `current_player_is_own` used raw `state.current_player`, which is stale during harvest sub-phases (FEED/BREED) and any out-of-turn trigger frame. Affected ~15% of training snapshots; the model trained on v1 features remained internally consistent but the feature carried noise rather than signal in those snapshots.
- `v2` — `current_player_is_own` now uses `decider_of(state)` (the pending-stack-aware canonical "who is to act?" query). Correct during harvest sub-phases and forward-compat with future cards that push out-of-turn trigger frames. The first v2 checkpoint will require a new training run; the v1 checkpoint `nn_models/20260529-162301-04fe/best.pt` will be rejected at load time by `EncodingVersionMismatch`, as designed.

#### `DATA_VERSION`

Parallel mechanism for the on-disk dataset schema. `GameRecord` and `DecisionSnapshot` are pickled to disk; changing their shape (adding a field, renaming, reordering) can silently corrupt loading of old pickles or — worse — succeed with garbage fields.

Mechanism mirrors `ENCODING_VERSION`:

1. Define `DATA_VERSION: int` as a module-level constant in `agricola/agents/nn/schema.py` (alongside `GameRecord`). Start at `1`.
2. Every generated `GameRecord` stamps the current `DATA_VERSION` into its own `data_version` field.
3. The dataset loader (`scripts/nn/validate_dataset.py` and the training-time loader) compares each `GameRecord.data_version` against the current `DATA_VERSION`. Mismatched records raise a clear error.

**Bump policy:** increment whenever the `GameRecord` or `DecisionSnapshot` schema changes in a way that affects on-disk shape. Adding a field bumps. Renaming a field bumps. Adding a new entry to a stored union type bumps.

**Initial version:** `DATA_VERSION = 1` corresponds to the schema specified in §6.2.

---

## 11. Experiments

NN experiments tracked through their lifecycle: an idea graduates from §13 Open questions into **Planned** (§11.1) once it has a concrete design, then moves to **Completed** (§11.2) with results + takeaway once run. Entries carry stable IDs (`P#` planned, `C#` completed) so cross-references survive renumbering. Comparison metric for almost everything is **gameplay** (win rate / margin), not loss — see §9.1.

### 11.1 Planned / in-flight

**P1 — Data-distribution ablation (in flight).** *Hypothesis: model quality is limited by the training-data distribution (heuristic diversity, temperature spread) and/or size, not by architecture.* Five 10k-game sections varying the heuristic mix and temperature regime, fixed v2-dropout architecture for all trained models:

| Section | Configs | Temp | Status |
|---|---|---|---|
| S1_standard_bimodal | all 8 | bimodal | done |
| S2_no_v1_bimodal | 7 V3 | bimodal | done |
| S3_strong3_bimodal | top-3 V3 | bimodal | done |
| S4_all_lowT | all 8 | T=0.3 | done |
| S5_no_v1_lowT | 7 V3 | T=0.3 | done |

All five sections generated. Models to train: per-section 10k models (M_10k_*) + M_15k_standard (existing 5k + S1) + M_55k_all (everything). Comparisons: **S1-vs-S4 (temperature regime) — run, see Experiment C11**; S1-vs-S2 (does t2/V1 matter), S1-vs-S3 (heuristic diversity at fixed size), S2-vs-S5 (T-regime among 7-V3), S4-vs-S5 (V1 among low-T), 5k→15k→55k (data scaling) — pending. Models trained so far: `M_10k_standard_bimodal` (S1), `M_10k_all_lowT` (S4).

**P2 — Supervision target / output head.** The current model regresses on **terminal margin** (linear head, MSE; §3.4/§5). Two bounded alternatives, same dataset and architecture, varying only head + loss:

| Variant | Head | Target | Loss |
|---|---|---|---|
| **margin** (current) | linear | `score_p − score_opp` | MSE |
| **outcome** | tanh | win/draw/loss `+1 / 0 / −1` | MSE |
| **win-prob** | sigmoid | win/draw/loss `1 / 0.5 / 0` | BCE |

Notes: **margin** gives the richest gradient (distinguishes a safe win from a narrow one) but is unbounded — large leaf values can distort MCTS UCB backups. **outcome** (tanh+MSE) is the AlphaZero value-head form, already zero-sum centered in `[−1,+1]`, drops into the existing sign-flip backprop with no recentering, and is what phase-c PUCT will want. **win-prob** (sigmoid+BCE) yields a calibrated probability; BCE is the Bernoulli NLL, punishing confident-wrong harder than MSE. `outcome` and `win-prob` encode the same target (`2·sigmoid − 1` spans the same range as `tanh`) — they differ only in loss-landscape. Optional loss-only sibling: **Huber** on the margin variant (linear tails → blowout games pull the fit less). **Comparison must be gameplay, not loss** — the heads output in different units, so train/val losses aren't comparable; evaluate via ensemble win-rate, head-to-head, and as MCTS leaf. Antisymmetry holds for all three. Most relevant for the MCTS-leaf use case (search rewards calibration over argmax-sharpness — see C3/C4) and for phase-c PUCT. Run after P1 so the dataset variable is clean.

**P3 — MCTS sim-count sweep.** Characterize the marginal-value-of-search curve for the NN leaf evaluator. Sweep e.g. 200 / 500 / 1500 / 5000 sims as head-to-heads (no shared tree when sims differ). Open sub-question: does the +3.54-to-+5.58 lift at 500 sims keep climbing or plateau? (From §13.3.)

Other planned-but-unscoped checks (from §11 outstanding work): match `NNAgent` / `MCTS-NN` vs `HubrisHeuristicV1` (`CONFIG_V1_T2`, the standalone-strongest agent); re-run the ensemble eval with per-opponent breakdown logged (prior run logged aggregate only).

### 11.2 Completed

**C1 — First full-data NN (reference model `04fe`).** Default architecture on the 5000-game dataset, 727,254 training examples (dual-perspective + terminal augmentation, 80/10/10 by-game split). Best epoch 1, val MSE 0.422, **test MAE 6.87**, `target_std` 14.40. Val curve crept up after epoch 1 (0.422 → 0.456 over 11 epochs) — fit the easy signal immediately, then memorized noise; early stop caught it. `nn_models/20260529-162301-04fe/best.pt` (ENCODING_VERSION=1, now incompatible).

**C2 — NNAgent vs 8-config ensemble.** `NNAgent` (differential, 1-turn) vs each config in `DATA_GEN_ENSEMBLE.md`, 100 games/opponent, V3 strict-restricted legality both seats. **~60% aggregate win rate**; beats every V3 opponent (often by 3-8 margin); **ties `t2`** (the lone V1 config). Likely cause: 7/8 training configs are V3, so the NN learned V3-style valuation — generalizes within V3 style, not to V1's. Motivates P1's V1-balance question.

**C3 — MCTS-NN-500 vs NNAgent-1-turn (on `04fe`).** Same model both sides; only difference is MCTS search vs 1-turn lookahead. MCTS: `leaf_differential=False`, 500 sims, c_uct=1.4, FPU 0, T=0.2, 4 random fencing macros + 1 greedy. 100 games. **68-32, +3.54 margin, p < 0.001.**

**C4 — Contrast with V3-evaluator MCTS.** C3 is the first MCTS config in the project that *lifts* strength rather than regressing it:

| Setup | Avg margin (MCTS − standalone) |
|---|---|
| MCTS-V1 vs V1-heuristic, 500 sims | −3.88 |
| MCTS-V3 vs V3-heuristic, 200 sims | −5.58 |
| **MCTS-NN vs NN-1-turn, 500 sims (C3)** | **+3.54** |

Plausible read: V3 is CMA-ES-tuned to be near-optimal as a single-position evaluator, so MCTS adds search noise faster than depth; the NN is noisier pointwise (MAE 6.87) and MCTS averages many leaf evals into a cleaner estimate. AlphaZero-style synergy in miniature. Validates the NN+MCTS direction; PUCT + policy head + higher sims (P3) are the natural follow-ups.

**C5 — Encoder v2 retrain + weight decay (`v2wd`).** First retrain after the v2 encoder fix, adding `weight_decay=1e-4`. **Test MAE 6.866 — essentially unchanged from C1.** Confirms (a) the encoder fix doesn't move aggregate MSE (most non-harvest snapshots were already correct), (b) wd=1e-4 is too weak to flatten the val curve. `nn_models/20260530-012100-v2wd/`.

**C6 — Dropout 0.2 (`v2dropout02`).** Same as C5 plus `dropout=0.2`, max_epochs=100, patience=20. **Test MAE 6.731 (~2% better than C5).** Best epoch 3 (vs 1); val curve drops 3 epochs then plateaus broadly instead of creeping. First real movement of the test metric — breaks the "6.87 noise floor" hypothesis. `nn_models/20260530-013000-v2dropout02/`. Current best NN.

**C7 — `v2wd` vs `v2dropout02` standalone (1000 games).** NNAgent-1-turn both sides, one model each. **No-dropout won 560-436** (avg margin −0.62 favoring no-dropout), p < 0.001. The dropout model is the *worse* standalone evaluator despite lower test MAE — MAE is not a reliable proxy for argmax-ranking quality.

**C8 — MCTS-NN-dropout-500 vs NNAgent-dropout-1-turn (100 games).** Same as C3 but on the dropout model. **80-19, +5.58 margin** — a *larger* MCTS lift than C3's +3.54 on the no-dropout model. So the dropout model is worse standalone (C7) but better as an MCTS leaf — consistent with "search rewards calibration; standalone argmax rewards sharpness." Indirect chaining estimate: MCTS-dropout ≈ +1.4 over MCTS-no-dropout.

**C9 — MCTS-dropout vs MCTS-no-dropout (partial, 52 of 100 games).** Direct head-to-head to test C8's indirect estimate. Killed before completion. Through 52 games: **27-24-1, +0.79 margin** — within noise of zero (SE ≈ ±2). Inconclusive but consistent with "very similar"; not yet rerun to completion.

**C10 — Parallelization characteristics.** For sizing future match/sweep runs:

| Mode | Per-game CPU | Per-game wallclock | Effective speedup |
|---|---|---|---|
| 1 worker | 62 s | 62 s | 1.0× |
| **4 workers** | ~44 s | **~11-19 s** | **~3-4× (the sweet spot)** |
| 8 workers | ~156 s | ~21 s | ~3.0× |

Past 4 workers, per-game CPU blows up because workers contend for the OS allocator / page cache / memory bandwidth even with `torch.set_num_threads(1)` pinned. The MLP is tiny and L2-resident; the bottleneck is Python-side (tree walks, action enumeration, encoding) run 4-8× in parallel. Not NN-specific — same wall hits V3-MCTS. Real fix is a vectorized batch encoder + batched leaf eval (sizeable refactor).

**C11 — S1 vs S4: training-data temperature regime (first P1 arm).** Two models, identical architecture (`[256,256]` GELU dropout-0.2 wd-1e-4) and identical 10k-game size, differing *only* in the temperature regime of the training data:
- **`M_10k_standard_bimodal`** (S1): all-8 configs, bimodal T (95% uniform[0.3,1.0] + 5% T=4) — diverse / exploratory states.
- **`M_10k_all_lowT`** (S4): all-8 configs, fixed T=0.3 — concentrated near-greedy states.

Test MAE (per-model, **not comparable**): S1 = 6.47, S4 = 4.87. The gap is mostly the *test distribution*, not model quality — S4's near-greedy games have low-variance terminal margins that are inherently easier to predict. This is why the comparison is gameplay, not loss.

Head-to-head, NNAgent (1-turn) both sides, same V3 strict-restricted legality, 1000 games:

| Side | Wins |
|---|---|
| **S1 / bimodal** (P0) | **735** |
| S4 / low-T (P1) | 264 |
| Draws | 1 |
| Avg margin (P0 − P1) | **+5.54** |

73.5% win rate for the bimodal model; z ≈ 14.9, p ≪ 0.001.

Takeaway: **diverse/exploratory training data trains a substantially stronger agent than concentrated near-greedy data**, despite the near-greedy model's far lower (but distribution-confounded) MAE — a sharp illustration that low test MAE ≠ strong play when the test distribution differs. The 5% T=4 exploration tail and the [0.3,1.0] temperature spread give the network a broader state distribution to learn from; the all-T=0.3 model overfits to a narrow near-greedy slice it rarely leaves at inference. First confirmation of P1's core hypothesis that data *distribution*, not just size, drives model quality — and a caution that future data-gen should preserve temperature diversity.

---

## 12. Status

Current state:

- Input encoding specified (§4)
- Supervision target chosen (§5)
- Data generation pipeline specified AND implemented (§6, §10.1)
- Schema versioning protocol defined (§10.4)
- **Code implemented:**
  - `agricola/agents/nn/{schema,recording,encoder,dataset,__init__}.py` — schema dataclasses + recording driver + the full input encoder + **the training-dataset builder** + public-surface re-exports
  - `encode_state(state, player_idx) -> np.ndarray` (numpy float32, length 170) implementing the §4 spec: per-player ×2 + shared + mid-action + terminal-state zeroing. Validated by encoding all 33,899 snapshot states + 750 terminal states from the 1000-game run with zero crashes, all finite, terminal zeroing correct.
  - `build_datasets(run_dirs, ...) → (train_ds, val_ds, test_ds, NormStats)`: by-game split, A augmentation + §5.1 terminal pairs, **paired sub-sampling** for train (state-level — dual-perspective pairs stay together), pre-encoded numpy arrays for fast DataLoader access. End-to-end run on the 5000-game production dataset: 200k train / 90k val / 91k test descriptors in ~2 min wall time; `target_std=14.39` (margin scale), input_std range [0.013, 7.777].
  - `model.py` — `ConfigurableMLP(input_dim, hidden_dims, output_dim=1, activation, norm, dropout)` (composable: usable as the full value net, as a per-player sub-encoder in a future Siamese, or as a head on top of a trunk) + `NormalizedValueModel(net, norm_stats)` (wraps any net with fixed normalization buffers; `forward(x)` returns normalized output for training, `predict_margin(x)` denormalizes for inference). Persistence: `<path>.pt` (state_dict including buffers) + `<path>.meta.json` (architecture config + `encoding_version` + optional `extras`). Default architecture (`hidden_dims=[256, 256]`, GELU, LayerNorm, dropout 0) = 110,849 params.
  - `training.py` — `train(run_dirs, out_dir, ...)` programmatic entry that builds datasets + model + optimizer, runs the per-epoch train/val loop with early stopping, saves best checkpoint + JSONL log + config + final test metrics + plots. Reusable from sweeps and custom scripts. Plus `train_one_epoch`, `evaluate`, `setup_seeds`, `make_run_id`, plot helpers.
  - `agent.py` — `NNAgent` (HeuristicAgent-style 1-turn lookahead backed by a trained `NormalizedValueModel`); `nn_evaluator` (single forward pass) and `nn_evaluator_differential` (D wrapper — batched-into-one-pass exact-antisymmetric `V(s,0) − V(s,1)` from FIRST_NN.md §8). Drop-in compatible with the existing `play_match.py` / `play_game` machinery.
  - `scripts/nn/generate_training_data.py` — batch generator with multiprocessing pool, resume-on-existing, atomic per-game writes, bimodal per-agent temperature draws, deterministic planning
  - `scripts/nn/validate_dataset.py` — post-generation invariant checker (§6.6) with optional random sampling
  - `scripts/nn/train_first.py` — thin CLI wrapper over `agricola.agents.nn.training.train(...)`
  - `scripts/nn/eval_vs_ensemble.py` — round-robin evaluation of a trained checkpoint vs the 8-config data-gen ensemble
  - `scripts/nn/play_match.py` — NN-backed match driver with per-seat dispatch (`--p0 {mcts,nn} --p1 {mcts,nn}`); the key tool for the Experiment C3 MCTS-NN-vs-NNAgent comparison
- **Tests:** 131 NN-related tests passing (16 schema/recording + 15 batch generator + 10 validation script + 28 encoder + 16 dataset + 27 model + 15 agent/training/integration). Full suite stays green.
- **Datasets on disk:**
  - 50-game pipeline-check run (validated, all checks pass)
  - 1000-game sanity-check run (validated, all checks pass, 48 MB, 131s wall time on 8 workers)
  - 5000-game production run (validated, all checks pass, 247 MB, ~19 min on 8 workers)
- **Trained checkpoints:**
  - `nn_models/20260529-153224-acb2/best.pt` — first end-to-end smoke-test (50k example sub-sample); see training log for details
  - `nn_models/20260529-162301-04fe/best.pt` — full-data production run on the 5000-game dataset; the current §11 reference checkpoint (test MAE = 6.87)
- **Matches run** — see §11 for the headline outcomes.

Outstanding evaluation / engineering work is tracked in §11.1 (planned experiments) and §13 (open questions).

Possible near-term refinement: cache pre-encoded dataset arrays to disk (keyed by run + split_seed + sample_size + ENCODING_VERSION) so iterating training runs doesn't pay the ~2-min build each time.

---

## 13. Open questions

Refreshed against current state — original items from the design phase (architecture sizing, training data volume, normalization scheme) are now resolved (§7 / §8). What remains:

### 13.1 Regularization / generalization

- Dropout 0.2 helped (Experiment C6: test MAE 6.87 → 6.73, healthier val curve), but the curve still creeps after the early plateau. Is there more to gain from **higher dropout (0.3+)**, **stronger weight decay**, or a **smaller model**? And is there an irreducible label-noise floor near ~6.7 MAE that no regularization breaks through?
- Within-game label correlation: ~150 snapshots per game share the same terminal margin, so the effective number of iid labels is closer to 2 × n_games than to n_descriptors. Does this matter operationally, or is the early-stop discipline enough? (P1's data-scaling arm probes this indirectly.)

### 13.2 Data distribution & V1 generalization

- `NNAgent` ties `t2` (the V1 config) and beats every V3 in the ensemble (Experiment C2). The training ensemble is 7-of-8 V3 — the most likely cause. Would a **V1-V3-balanced data-gen ensemble** close the t2 gap? (P1's S2/S5-vs-S1 arms probe the V1-presence axis.)
- Should training data include some **MCTS-NN self-play** rollouts to expose the model to higher-quality states than the heuristic ensemble produces? (Phase-(b) work, but worth flagging.)

### 13.3 MCTS-NN scaling

- Does **PUCT** (a learned policy prior) further improve on vanilla UCT once we add a policy head? Existing project work flagged PUCT + learned-value-NN + higher sims as the natural follow-up — this is the question it would answer. (The sim-budget half of this is operationalized as Experiment P3.)
- The strict-restricted legality wrapper was tuned for V3 internals (Cultivation sow-max, fence-pattern table). Is it the right legality filter for an NN evaluator, or does the NN's smoothness/noise pattern suggest a different restriction set?

### 13.4 Architecture

- Phase-(a) is locked at a flat MLP. The §7.1 directions — **Siamese encoder**, **spatial CNN over the farmyard**, **architecturally-antisymmetric output head**, **multi-head outputs** (value + win-probability, eventually value + policy) — are each a stronger inductive bias and worth a controlled comparison once the data pipeline matures.
- The output-head / supervision-target choice (raw margin vs bounded outcome vs win-probability) is operationalized as Experiment P2.

### 13.5 Trained-model lifecycle

- Promotion gating: there's no analog of `tuned_configs/v3_best.json` for NN checkpoints yet. Should there be a `nn_models/best.pt` pointer with a regression-gated update rule analogous to the V3 pipeline? (`nn_models/REGISTRY.md` currently records the current-best by hand.)
- Cross-run reproducibility: training is non-deterministic (CUDA + multi-threaded BLAS). Acceptable for now (early-stop catches the variance); revisit if checkpoint-to-checkpoint comparisons start mattering.
