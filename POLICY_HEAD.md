# Policy Head — AgricolaBot

Design spec for the supervised, behavioral-cloning **policy** for AgricolaBot, trained from the
existing heuristic-ensemble game data and exposing a prior for PUCT to consume.

§1–§10 are the original **v1 placement-only** spec (the first slice of FIRST_NN.md's phase (c),
"policy head + PUCT"): the action representation, supervision target, the two loss variants, model,
training, and evaluation. **The policy has since grown to cover every decision type** — six more
fixed heads and two pointer heads, assembled into two end-to-end combiners; that work is in §11
("the other heads") and §14 (status). Read §11/§14 for the current state; §1–§10 for the foundational
design that all the heads share.

> **For new sessions:** read `FIRST_NN.md` (the value net this sits beside — same encoder, data,
> and infrastructure), `MCTS_DESIGN.md` (the search this prior will steer), and CLAUDE.md §2
> (project status). **PUCT itself is being designed/implemented separately — this doc covers only
> training the policy function and the `policy_prior` surface PUCT calls.**

---

## 1. Context

The end-goal agent is an AlphaZero-style net with a **value head and a policy head** driving
**PUCT** search. The value slice is done and is the strongest agent to date (FIRST_NN.md), but
search still uses **vanilla UCT** with no learned prior. PUCT needs a policy prior `P(s, a)` to
focus search and shrink the effective branching factor — existing project work flagged
"PUCT + learned-value-NN + higher sims" as the natural next step (FIRST_NN.md §13.3).

We already have what a *first* policy needs. Every recorded `DecisionSnapshot` stores the
`chosen_action` + `decider_idx` (added "for future policy-head training; cheap to include now"),
across tens of thousands of heuristic-ensemble games (generated under a *mix* of legality
wrappers — see §3). So a **supervised behavioral-cloning (BC)** policy is trainable today
with **no new data generation** and no MCTS visit-count (π) targets (which we don't have on disk).

This v1 trains a standalone worker-placement policy by BC and validates the policy-head + eventual
multi-head machinery before the harder heads and the self-play loop.

---

## 2. Goals & non-goals

### Goals
- Train a **placement policy** — a 25-way classifier over the action spaces (`SPACE_IDS`) — by
  behavioral cloning of the ensemble's `chosen_action` at worker-placement decisions.
- Run **two loss variants** as the headline experiment: unweighted cross-entropy, and
  advantage-weighted (AWR) cross-entropy.
- Expose `policy_prior(state, model)` — the prior distribution over legal placements that PUCT
  will read.
- Reuse the value net's infrastructure (encoder, `ConfigurableMLP`, normalization-wrapper +
  `ENCODING_VERSION` persistence pattern, dataset split, training loop) so later heads compose.

### Non-goals (deferred) — *for the v1 placement slice; most are now built (see §11/§14)*
- **Sub-action heads** (plow/sow/bake/build/renovate), the **pointer heads** for the
  Pareto-frontier commits (animal accommodate / breed / convert), and **fencing** — were v1
  non-goals; **all are now built** (§11). Only the plow/stable/room *cell* choice remains
  unlearned (no spatial encoder).
- **PUCT** — separate session; we ship only the prior it calls.
- **Shared-trunk joint value+policy net** — v1 is a *separate* policy net; the joint net is a
  self-play-phase concern (§9).
- No new data generation; no visit-count targets.

---

## 3. Action representation — factored heads, fixed placement head first

Agricola's decision points are **typed by the pending-stack top** (the dispatch `legal_actions`
already performs): an empty stack is a worker-placement choice; each non-empty top is one
sub-action category. This makes a **factored policy** — one head per decision type, dispatched on
the stack top — the natural representation, and per-decision-point head dispatch falls out of the
engine's own structure (so "run only the relevant head" is free at inference).

**Realized as a `DecisionHead` spec** (`agricola/agents/nn/policy_heads.py`): each head declares
`owns(state)` (the pending-top predicate), its output `vocab`, `target_index(action)` (chosen →
class), and `legal_mask(state)`. The dataset / model / training / `policy_prior` are all driven by a
head spec, so adding a head is *data*, not new modules. The `HEADS` registry currently holds three:

- **`placement`** (25 classes = `SPACE_IDS`) — the empty-stack worker-placement choice; built first
  (clean fixed vocab, highest-leverage branching, most/cleanest data).
- **`choose_subaction`** (8 classes) — the parent-pending "which sub-action, or Stop": `sow`,
  `bake_bread`, `build_stables`, `build_rooms`, `plow`, `build_fences`, `improvement`, `Stop`
  (`build_stable` merged into `build_stables`; `build_major`/`renovate` excluded as structurally
  singleton).
- **`commit_build_major`** (14 classes) — "which major to buy": one class per `(major_idx,
  return_fireplace_idx)` (8 non-hearth majors + the 2 Cooking Hearths × {pay-full, return-fireplace
  0/1}).

The variable/parameterized commits (animal frontiers, fencing) need different machinery (§11) and
remain deferred.

- **Vocabulary = `SPACE_INDEX`** (25 classes; `agricola/constants.py`). `lessons` is excluded
  upstream by `legal_placements`, so its class is **permanently dead** (always masked off) — kept
  only to keep indices aligned with `SPACE_INDEX`.
- **Legality = regular `restricted_legal_actions`**. The data was generated under a *mix* of
  wrappers (per-game: default regular, the strict-blend dir under strict — see
  `generate_training_data.py`), but **worker-placement legality is wrapper-invariant**: at an empty
  pending stack regular applies no restriction (`restricted.py:176`), strict returns the regular
  result unchanged (`restricted.py:568`), and `legal_placements` already drops `lessons` for all of
  them — the restriction wrappers only ever filter *sub-actions*. So every game's recorded
  placements (and their legal sets) match what regular `restricted_legal_actions` produces at
  inference, regardless of that game's generation wrapper → no train/serve skew. (The
  branching-reduction the strict wrapper does at sub-action level is the role we expect a *learned
  prior* to take over later.)

**The `restricted.py` forcing-fix (what enabled the sub-action heads).** The regular wrapper
originally applied three *ordering* filters (plow-before-sow, rooms-before-stables, sow-before-bake)
that, at the initial parent-pending decision (where the engine offers no `Stop`), collapsed the
choice to a forced singleton — **force-plowing / force-building-a-room**. That removed a legitimate
option (sow-only / keep-the-cell-flexible — a cell plowed into a field can't later become a
pasture/stable/room), making it a *lossy* prior, and it left `plow`/`build_rooms` with **zero**
ChooseSubAction training data. We dropped all three ordering filters (keeping the cell-priority and
room-cap filters); in the regenerated `hidden_info_v2_10k`, `plow`/`build_rooms` went from 0 to the
two most common ChooseSubActions. (The cell-priority filters still force *which* cell — relaxing
those is the separate prerequisite for a future plow/stable/room *cell* head; §11.)

---

## 4. Input encoding

Reuse `encode_state(state, player_idx) -> np.ndarray` verbatim (`agricola/agents/nn/encoder.py`,
`ENCODED_DIM = 170`, `ENCODING_VERSION = 2`). The policy net's input is identical to the value
net's; only the head and the supervision differ.

**Single perspective — the decider's view only.** This is the key departure from the value net's
dual-perspective augmentation (FIRST_NN.md §8.A). The BC target is *the decider's* chosen action;
encoding the same position from the opponent's view paired with that label is meaningless. So each
placement snapshot yields exactly **one** example: `encode_state(state, decider_idx)`.

---

## 5. Supervision target — behavioral cloning + the two loss variants

Training data is `(state, chosen_space, legal_mask)` triples extracted from the recorded games. For
each **non-terminal** snapshot with `isinstance(chosen_action, PlaceWorker)`:

| Field | Value |
|---|---|
| input `x` | `encode_state(state, decider_idx)` |
| target | `SPACE_INDEX[chosen_action.space]` (0–24) |
| legal mask | `bool[25]`: the spaces of `filter_implemented(restricted_legal_actions(state))` that are `PlaceWorker` |
| weight (variant 2 only) | AWR weight `wᵢ = clip(exp(Aᵢ/β), 0, w_max)`, advantage `Aᵢ = Rᵢ − V_θ(sᵢ)` (decider frame) — see *The loss* |

Notes:
- **Keep all temperatures.** The data is bimodal (95% `T∈[0.3,1.0]`, 5% `T=4`); the 5% near-random
  tail is tolerable label noise, and under the weighted variant those (usually-losing) explorer
  moves get downweighted automatically.
- **Hard invariant:** `mask[target]` is always True (the chosen action is in its own legal set).
  A violation indicates encoder/legality drift and fails loudly.
- **By-game split** via `dataset._seed_split` (per-game seed-hash, rename-proof) — no game straddles
  train/val/test.
- **Defensive loading:** count games from the worker pickles, **not** `metadata.json` counters
  (some report 0 — treat the counters as unreliable and verify actual game presence at
  implementation).

### The loss

Both variants are **cross-entropy on the legal-masked logits** vs the target space — illegal
classes get `−inf` logits, so they receive neither gradient nor probability (the target is always
legal, by the invariant above). A per-example weight `w_i` selects the variant:

```
L = − (Σ_i wᵢ · log softmax(masked_logits(sᵢ))[aᵢ]) / (Σ_i wᵢ)        # weighted mean
```

This **weighted mean** is self-normalizing — scaling all `wᵢ` by a constant leaves `L` unchanged,
and `wᵢ = 1` everywhere reduces it exactly to the unweighted mean — so no separate weight
renormalization is needed, and the weighted run's loss scale matches the unweighted baseline
automatically.

1. **`unweighted`** — `wᵢ = 1`. Clones the ensemble's *average* placement policy (losers'
   moves included). The honest baseline.
2. **`awr` (advantage-weighted regression)** — `wᵢ = clip(exp(Aᵢ / β), 0, w_max)`, with advantage
   `Aᵢ = Rᵢ − V_θ(sᵢ)`: the game's **actual terminal margin** `Rᵢ` (decider frame, from the stored
   final scores) minus the **value net's estimate** `V_θ(sᵢ)` at that state (decider frame, via the
   differential evaluator). `β` = the advantage scale (default `std(A)`, configurable); `w_max`
   clips runaway weights (default 6). The established AWR/MARWIL form. `V_θ(s)` is the
   **single-perspective** value (`predict_margin` on the decider's encoding — the *same* 170-vector
   already built as the policy input `x`), so the marginal cost is one batched value-MLP forward
   over the encodings we compute anyway (seconds, one-time, cacheable), plus loading a value
   checkpoint (`--value-ckpt`, default the champion `nn_models/best`).

> **Why advantage-weighting beats raw outcome-weighting.** The `V_θ(s)` **baseline** is the whole
> point — it removes the "this move sat in an already-winning position" confound that plain
> margin-weighting suffers. A fine move in a won position has high return *and* high `V(s)`, so its
> advantage ≈ 0 (correct — it added little); a move that rescues a losing position has `R > V(s)` →
> positive advantage (correctly rewarded). Using the real terminal return keeps the signal unbiased
> for the actual outcome; the baseline cuts variance and the position confound. Residual limits:
> terminal return is still coarse end-of-game credit for one placement (volume averages the
> *variance*; the baseline is what fixes the *bias*), and `V_θ` is imperfect. The eventual ideal
> target is the **MCTS visit distribution** (AlphaZero), available once self-play recording exists.
> For a *prior* — corrected by search + value — AWR is a well-grounded, cheap step up from both
> uniform and naive margin-weighting (e.g. a sigmoid of the final margin, with no baseline).

---

## 6. Model

Reuse the value stack's building blocks (`agricola/agents/nn/model.py`):
- **Net:** `ConfigurableMLP(input_dim=170, hidden_dims=[256, 256], output_dim=25,
  activation="gelu", norm="layer", dropout=0.2, head="linear")` → 25 raw logits. Mirrors the
  champion value architecture, which also makes warm-start a clean transplant (§7).
- **Wrapper `NormalizedPolicyModel(net, PolicyNormStats)`** — input-normalization buffers
  (`input_mean`/`input_std`) only; **no** target normalization (classification). Methods:
  `forward(x) -> logits`; `predict_logits(x, mask)` (illegal → `−inf`); `policy_probs(x, mask)`
  (masked softmax — illegal columns exactly 0; all-False-mask guard avoids NaN). Persistence
  mirrors `NormalizedValueModel.save/load` (state_dict + `.meta.json`; hard-fail on
  `ENCODING_VERSION` mismatch via the shared `EncodingVersionMismatch`; `ConfigurableMLP` is
  already in `NET_REGISTRY`).
- **`PolicyNormStats`** — a dedicated 3-field struct (`input_mean`, `input_std`,
  `encoding_version`); no `target_std`/`target_mode` (meaningless for a classifier).

---

## 7. Warm-start (optional)

The champion value net is `[256, 256]` (identical trunk shape), so its **trunk** (the two
`Linear + LayerNorm` blocks) transplants directly into the policy net. This reuses the codebase's
existing **shape-tolerant transplant** (`training.py:484`): copy every net-weight tensor whose name
*and* shape match (the trunk Linears/LayerNorms do; the `256→25` head doesn't match the value net's
`256→1`, so it stays freshly-initialized). The policy's `PolicyNormStats` are **fit fresh on the
policy data** (not carried from the value net) — consistent with how value warm-start works, and
the trunk adapts to the fresh input scale since all layers fine-tune at the normal LR.

Default recipe is **from-scratch**; warm-start (`--init-from <value_ckpt>`, e.g. `nn_models/best`)
is an ablation, and requires `--hidden-dims 256,256` to match the value trunk. It also doubles as
the bridge to the joint net (§9).

---

## 8. Training & evaluation

### Training
Parallels `agricola/agents/nn/training.py`: load → by-game split → fit input-norm on the train
split → (optional warm-start trunk transplant, §7) → AdamW + early-stop on **val cross-entropy** →
best checkpoint + per-epoch log + curves + metadata JSON. Reuses `setup_seeds` / `make_run_id` / `current_git_sha` and the plot-helper pattern.
Default arch/regularization mirrors the value net (`[256, 256]`, GELU, LayerNorm, dropout 0.2,
wd 1e-4).

### Metrics (held-out; by-game split)
- **Val cross-entropy** — the early-stop / checkpoint-selection criterion.
- **Top-1 / Top-3 accuracy** — fraction where the chosen space is the model's #1 / within top-3
  highest-probability *legal* spaces. Reported **both** over all held-out placements **and over the
  winners' subset** (the cleaner "did it learn *good* moves" signal). Test split scored once.
- The eval metric stays a **fixed, unweighted** definition regardless of the training weight, so the
  two loss variants are comparable on one ruler.

**These are agreement-with-recorded-moves, not strength.** Top-1's ceiling is well below 100% by
design — the data is temperature-sampled from a *diverse* ensemble, so a state has no unique
"correct" label; that's why top-3 (the more PUCT-relevant "are the good moves near the top?") is
paired in. **The real test is PUCT lift** (separate session); val CE / top-k are the cheap per-epoch
stand-ins.

### Gameplay sanity check (optional, v1)
A standalone `PolicyAgent` (argmax placements + pruned-random sub-actions) vs the 8-config ensemble
would confirm the policy learned something strategically real beyond raw accuracy. Expected to be
*weaker* than `NNAgent` (placement-only with random sub-actions), so it's a floor check, not a
strength claim. Listed as optional — primary v1 deliverable is the two trained models + their
accuracy metrics.

---

## 9. Multi-head trajectory (future, for context)

`separate policy net (v1)` → `warm-started policy net (trunk from value, §7)` → `shared-trunk joint
value+policy net` trained with `L = value_MSE + λ · policy_CE` (the AlphaZero form, most valuable in
the self-play loop where both heads retrain on fresh data). v1's warm-start is the deliberate
bridge: it *is* "value trunk + policy head," one step from the joint net — without risking the
champion value head by jointly retraining it now.

---

## 10. Consumer surface (what PUCT calls)

```python
NO_PRIOR = None

@torch.no_grad()
def policy_prior(state, model, *, legal_actions_fn=restricted_legal_actions
                ) -> dict[PlaceWorker, float] | None:
    # empty pending stack & not terminal → {PlaceWorker(space): prob} over exactly the legal
    #     placements (masked softmax, sums to 1).
    # non-placement (non-empty pending stack) or terminal → NO_PRIOR.
```

Keys are reconstructed `PlaceWorker` instances (frozen-dataclass value-equal to the engine's legal
actions), so PUCT looks priors up by the action objects it already holds. Returning an explicit
`NO_PRIOR` sentinel off placement decisions leaves the fallback policy (uniform over legal children,
or value-only expansion) in PUCT's hands — the correct separation for the two-session split.

---

## 11. The other heads (built since the v1 placement slice)

The factored policy now spans **every** decision type. Beyond the three early fixed heads
(`placement`, `choose_subaction`, `commit_build_major`), four more fixed `DecisionHead`s and two
`PointerHead`s have landed; per-checkpoint metrics are in REGISTRY.md.

**Fixed heads added:** `commit_sow` (104-way, `1 ≤ g+v ≤ 13`), `commit_bake` (6-way, `grain ∈ 1..6`),
`fencing` (110-way; see below), and `build_stop` (2-way; see below).

### Pointer heads (score-the-legal-set) — `animal_frontier`, `harvest_feed`

A `PointerHead` (`policy_heads.py`) handles a variable-cardinality frontier: it `enumerate`s the
legal commits (re-deriving the *same* engine frontier the legality enumerator uses, so the candidate
set + order match what MCTS sees) and gives each a small **action-delta** feature row. The model
concatenates the **shared state encoding** onto every candidate (so per-candidate features carry only
what *differs*), scores each `[state ; Δ]` row to a scalar, and **softmaxes over the legal set**.

- **`animal_frontier`** owns `CommitBreed` (harvest breeding) **and** `CommitAccommodate` (the three
  animal markets) — both are `(sheep, boar, cattle)` post-counts from a `(config, food)` frontier, so
  one head/featurizer serves both (doubling the data; the state encoding's `phase`/`round`/`in_harvest`
  disambiguates context). Δ = `(sheep_kept, boar_kept, cattle_kept, food_gained)` — **kept counts are
  the raw commit fields** (not a subtracted delta — pre-counts are already in the state encoding).
- **`harvest_feed`** owns `PendingHarvestFeed` (pre-`conversion_done`): the **heterogeneous** legal
  set of `CommitConvert` Pareto-frontier points *and* `CommitHarvestConversion` craft toggles
  (`use=False` was removed at the engine level, so a toggle is fire-only). 10-dim tagged-union Δ:
  `[is_toggle, joinery, pottery, basketmaker, consumed(g,v,s,b,c), begging]`.

**Ragged training, no padding.** Each example is a snapshot's *list* of candidates + the chosen
position. A batch flattens to one `(ΣK, ·)` tensor + `segment_id` + `chosen_flat`; the scorer runs
once over all candidates and a **segment-softmax** (`scatter_reduce` amax + `index_add_`) normalizes
per snapshot. Loss is weighted **segment-CE**; metrics are within-frontier top-1/top-3 (overall +
winners). AWR carries over unchanged (per-snapshot `V_θ(s)` weight). The by-game split is identical
to the fixed heads.

**Data scope.** Both pointer heads train on the **union of all DATA_VERSION-2 hidden-info runs**
(`hidden_info_v2_10k` + `hidden_info_bimodal_20k` + `hidden_info_nnblend_10k`) — valid because a
pointer head enumerates the *full* engine frontier, so the recorded chosen commit is always in its
candidate set regardless of which wrapper generated the game (the v2-only constraint of §13 is
specific to the `choose_subaction` head, whose *labels* the forcing-fix changed).

### `build_stop` — learned P(stop) for multi-shot Build Rooms / Build Stables

At `PendingBuildRooms`/`PendingBuildStables` with `num_built ≥ 1` (⟺ Stop legal), the *which cell*
has no encoder signal but *when to stop* does (current rooms/stables, resources — the encoder's
`subaction_avail_build_rooms/stables` flags distinguish them). A 2-class build-vs-stop head learns
`P(stop)`; `policy.py`'s combiner expands the `build` class onto the cell-priority cell →
`{cell: P(build), Stop: P(stop)}`. This replaces the crude uniform 50/50 the cell-priority fallback
gives (which was ~6× too high on Stop for rooms). Fencing's stop is handled by its own head, not here.

### `fencing` — a deliberate spatially-blind experiment

`fencing` is a 110-class head: the 109 shapes of the RESTRICTED fence universe (`fences.py`) + Stop,
trained with FULL legality (no restricted/strict wrapper). Its output classes are *spatial* (specific
cell-sets) but the encoder has **no per-cell features**, so it leans on the legal mask + learned
canonical-shape priors. Top-1 is only ~28% — the evidence that **spatial encoding is fencing's real
bottleneck**. The principled upgrade is a 3×5 cell-type grid in the encoder + a spatial head; deferred.

### Still deferred

- **Plow / stable / room *cell* choice** stays uniform-over-cell-priority (no encoder signal); a
  learned cell head needs the spatial encoder above.
- **Self-play visit-count (π) targets** — the AlphaZero ideal, once a self-play loop exists.

---

## 12. Implementation notes

### File layout (mirrors the value-net module split; all import torch, none re-exported from `agricola/agents/nn/__init__.py`)

| File | Contents |
|---|---|
| `agricola/agents/nn/policy_heads.py` | `DecisionHead` spec + `HEADS` registry (`placement`, `choose_subaction`, `commit_build_major`, `commit_sow`, `commit_bake`, `fencing`, `build_stop`) — each: `owns`, `vocab`, `target_index`, `legal_mask`. **Also** the `PointerHead` spec + `POINTER_HEADS` registry (`animal_frontier`, `harvest_feed`): `owns`, `candidate_dim`, `enumerate_candidates(state) -> [(action, feature_vec)]`. Torch-free; adding a head = a new spec here. |
| `agricola/agents/nn/policy_dataset.py` | `PolicyNormStats`; `AgricolaPolicyDataset`; `_decision_rows(games, head)` (head-driven extraction, single-perspective); `build_policy_datasets[_from_games](..., head=...)` → `(train, val, test, PolicyNormStats, info)`. Streams pickles. For `awr`, computes `A = R − V_θ(s)` weights (one batched value-net pass per train state). |
| `agricola/agents/nn/policy_model.py` | `NormalizedPolicyModel` (input-norm + masked softmax; `head_name` persisted in meta). Imports `NET_REGISTRY`, `EncodingVersionMismatch`, `ConfigurableMLP` from `model.py`. |
| `agricola/agents/nn/policy_training.py` | `train_policy(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)`. Weighted masked-CE, top-1/top-3 (+winners) eval, early-stop on val CE. `--init-from` accepts a value *or* policy checkpoint (trunk transplant). Artifacts: `config.json`, `policy_norm_stats.json`, `train_log.jsonl`, `best.{pt,meta.json}`, `test_metrics.json`, `train_curves.png`. |
| `agricola/agents/nn/policy_pointer_dataset.py` | `PointerNormStats` (norm over `[state ; cand]`); `AgricolaPointerDataset` (ragged: state stored once per snapshot, flat candidates sliced by offsets); `pointer_collate` (flatten a batch → `(state, cand, segment, chosen_flat, weight)`, no padding); `_pointer_rows(games, head)`; `build_pointer_datasets[_from_games](..., head=...)`. Reuses `_seed_split` + `_compute_awr_weights`. |
| `agricola/agents/nn/policy_pointer_model.py` | `NormalizedPointerModel` (scores `[state ; cand]` rows; `score_flat` for the segment batch, `candidate_probs` for inference) + `segment_log_softmax` (per-segment normalize via `scatter_reduce` amax + `index_add_`). Persists `model_kind="policy_pointer"` + `candidate_dim`. |
| `agricola/agents/nn/policy_pointer_training.py` | `train_pointer(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)`. Weighted **segment-CE**, within-frontier top-1/top-3 (+winners), early-stop on val CE. Mirrors `train_policy` artifacts (`pointer_norm_stats.json`). |
| `agricola/agents/nn/policy.py` | `policy_prior` (fixed heads) + `pointer_prior` (pointer heads) + `NO_PRIOR`. **`make_policy_fn(models)`** / **`load_policy_fn(checkpoints)`** — the full `policy_fn(state, legal) -> {action: prior}` MCTS consumes: dispatches by decision type (fixed head / pointer head / `build_stop` learned-P(stop) for multi-shot rooms&stables / cell-priority uniform / full-legal uniform). The PUCT consumer surface. |
| `scripts/nn/train_policy.py` | Thin CLI over `train_policy` (the fixed heads). `--head` ∈ `HEADS`, `--loss-weight {unweighted,awr}`, `--value-ckpt`, `--awr-clip`, `--init-from`, and **`--legality {restricted,full}`** (use `full` for the fencing / build_stop heads). |
| `scripts/nn/train_policy_pointer.py` | Thin argparse → `train_pointer` (`--head {animal_frontier,harvest_feed}`, `--loss-weight {unweighted,awr}`, …). Default `--run-dir` = the three hidden-info runs (all valid for pointer heads). |
| `scripts/nn/build_combined_policy.py` | The two assembled policy functions: `build("unweighted")` / `build("awr")` (9 head checkpoints each, via `load_policy_fn`) + a `__main__` sanity check. `UNWEIGHTED_SET`/`AWR_SET` manifests. |
| `tests/test_nn_policy.py` | Fixed-head extraction/mask/AWR/model/persistence/`policy_prior`/`make_policy_fn` dispatch; **pointer head**: `enumerate`/food/target-position vs the engine frontier, segment-softmax, collate, dataset build, `pointer_prior`, `make_policy_fn` routing, and a `train_pointer` smoke. |

The meta sidecar carries `"model_kind": "policy"` + `"head": <name>`, so policy checkpoints are
machine-distinguishable from value checkpoints and from each other; `model.head_name` lets
`policy_prior` auto-select the right head.

### Doc/registry sync (done at implementation time)
`agricola/agents/nn/__init__.py` docstring (new submodules, not re-exported); `nn_models/REGISTRY.md`
(new **"Policy models"** section — top-1/top-3 columns, not MAE); CLAUDE.md (§2.3 wording +
Documentation Files table + directory tree); FIRST_NN.md (§1 phase-c row + §13.3 pointer here);
FILE_DESCRIPTIONS.md; TEST_DESCRIPTIONS.md.

### Build sequence (dependency-clean; each step independently testable)
1. `policy_dataset.py` (+ extraction/weight/split tests) → 2. `policy_model.py` (+ model tests) →
3. `policy_training.py` + `scripts/nn/train_policy.py` (+ smoke test) → 4. `policy.py` (+ prior/agent
tests) → 5. docs/registry/`__init__` → 6. train the **two** models (`unweighted` + `awr`); add
registry rows.

### Verification
```bash
python -m pytest tests/test_nn_policy.py -v
python -m pytest tests/test_nn_model.py tests/test_nn_dataset.py tests/test_nn_agent.py -q  # value pipeline undisturbed
# smoke train (tiny):
python scripts/nn/train_policy.py --run-dir data/nn_training/runs/standard_bimodal_5k \
    --hidden-dims 16,16 --max-epochs 3 --out-dir nn_models/policy_smoke --loss-weight none
```

---

## 13. Open decisions

All resolved during the build:

1. **Weighting** — AWR (`A = R − V_θ(s)`, champion baseline `nn_models/best`, `β = std(A)`,
   `w_max = 6`, single-perspective `V_θ`).
2. **Warm-start** — `--init-from` built (accepts a value *or* policy checkpoint); the trunk is
   warm-started from the `unweighted` placement model by default.
3. **Data scope** — `hidden_info_v2_10k` (10k games regenerated under the fixed `restricted.py`).
4. **Gameplay sanity eval** — deferred (accuracy-only v1); PUCT lift is measured in the PUCT session.

---

## 14. Status

**Implemented — full decision-type coverage.** The factored-policy infra (`policy_heads.py` +
head-driven dataset / model / training / `policy_prior` / CLI) and the **pointer-head** infra
(`policy_pointer_*` + segment collate / scorer / segment-CE) are built and tested
(`tests/test_nn_policy.py`). Trained heads (each `unweighted` + `awr`; metrics in
`nn_models/REGISTRY.md`):

- **Fixed heads** — `placement` (25), `choose_subaction` (8), `commit_build_major` (14),
  `commit_sow` (104), `commit_bake` (6), `fencing` (110), and `build_stop` (2).
- **Pointer heads** — `animal_frontier` (CommitBreed + CommitAccommodate) and `harvest_feed`
  (CommitConvert + CommitHarvestConversion), trained on all three hidden-info runs.

The **`make_policy_fn(models)` combiner** (`policy.py`, and `load_policy_fn` to load from disk) is the
full `policy_fn` MCTS consumes: it works over the *full* legal set and dispatches by decision type —
fixed head / pointer head / `build_stop` (learned P(stop) for multi-shot rooms&stables) /
uniform-over-cell-priority (plow + first-build cells) / uniform-over-full-legal (the remainder).
`scripts/nn/build_combined_policy.py` assembles the **two end-to-end policy functions**: `build("unweighted")`
and `build("awr")` (9 head checkpoints each). Both load and drive PUCT end-to-end.

**Notable finding:** the `fencing` head is spatially blind (top-1 ~28%) — the encoder has no per-cell
features. Spatial encoding is fencing's bottleneck (§11).

**Next:** **PUCT consumption / eval** — measure whether these priors actually improve search vs.
uniform / UCT and tune `c_puct` (the real validation; accuracy ≠ strength). Then a spatial encoder
for fencing/cell heads, and eventually self-play visit-count (π) targets.
