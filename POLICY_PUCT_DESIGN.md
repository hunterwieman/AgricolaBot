# Policy Head + PUCT — Design

Design spec for AgricolaBot's **policy head** and **PUCT** search (Phase 2.3 (c)→(d): the policy
half of the AlphaZero-style agent). The goal: a learned policy prior that guides MCTS via PUCT,
bootstrapped by behavioral cloning of the heuristic-ensemble data we already have, and built so the
eventual self-play improvement loop is additive rather than a rewrite.

> **For new sessions:** read FIRST_NN.md (the value net this composes with — same `encode_state`,
> same checkpoint conventions), MCTS_DESIGN.md (the search this modifies), HIDDEN_INFO_DESIGN.md
> (the chance-node mechanism PUCT must leave intact), and CLAUDE.md Phase 2.2/2.3.

---

## 1. Goals, non-goals, scope

### Goals
- A **policy network** producing a prior `P(s, a)` over the agent's legal actions, drop-in to MCTS.
- **PUCT** selection in `agricola/agents/mcts.py`, replacing vanilla UCT's exploration term with a
  policy-weighted one, so a strong prior soft-prunes the (wider) regular-legality action set.
- **Bootstrap by behavioral cloning** (BC) of the existing heuristic-ensemble data (`chosen_action`
  per snapshot), then a path to AlphaZero-style policy *improvement* from MCTS visit counts.
- Build it so the value net (current champion `M_82k_warmM62k`) supplies the **leaf value** and the
  new policy net supplies the **prior** — separate nets in v1, with a clean path to a shared trunk.

### Non-goals (this phase)
- No requirement to train all heads at once. v1 is **placement only**; other decision-point types
  fall back to a uniform prior and light up incrementally.
- No self-play data-generation loop yet (phase d). The BC data already exists.
- No shared value+policy trunk yet — but the interface is designed not to foreclose it (§9).
- No 4-player, no cards.

### Phasing
| Phase | What | Status |
|---|---|---|
| c0 | PUCT machinery in mcts.py, validated against a **uniform** prior | **landed** (`FenceMode`, `policy_fn`, `_select_via_puct`; `tests/test_puct.py`) |
| c1 | **Placement** fixed-width head (BC), wired as the prior; eval vs controls | next |
| c2 | Broader heads (sub-actions, major, the score-the-set frontiers) | after c1 |
| c3 | **Fence-sequence prior** (`SEQUENCE_PRIOR`, §8) | optional upgrade |
| d | Self-play loop: visit-count π targets, Dirichlet noise, iteration | future |

The c0 search work and the policy-training work are **independent tracks** that meet only at the
§3.4 interface contract; neither blocks the other.

---

## 2. Strategic context

MCTS today is vanilla UCT + FPU + DAG-with-transpositions + a learned value leaf (FIRST_NN). With
the value NN as leaf evaluator, MCTS already *lifts* strength over the NN's 1-turn lookahead
(FIRST_NN C3/C8). The natural next lever is a **policy prior**: PUCT focuses simulations on
plausible actions, which is what makes search productive at the project's modest sim budgets
(200–1500) and is the precondition for the AlphaZero self-play loop.

A second motivation is **legality**. MCTS currently searches under `strict_restricted_legal_actions`
(hand-tuned hard prunes: sow-max, 9 fence patterns, harvest-feed cap). We move the *policy* to the
**regular** `restricted_legal_actions` set and let the prior do the pruning *softly* — recoverably,
and without the strict collapses that become lossy once cards are added (CLAUDE.md Foundations).

---

## 3. Settled design decisions

### 3.1 Regular legality + soft-prune-via-prior
The policy operates over **regular `restricted_legal_actions`** (not strict). Rationale: it matches
the BC data (generated under regular), keeps every strategically-meaningful option legal, and lets
PUCT's prior soft-prune what strict hard-pruned. Strict + renormalize-the-prior-over-the-subset
remains a *technically valid control* (a distribution restricted to a subset is still a
distribution), but it re-introduces hard pruning and is not the default.

**Risk to watch:** switching strict→regular only widens the action set at **fencing** (5–40 per-pasture
commits vs strict's 9 curated patterns) and **sow** (3–8 vs strict's collapse); every other decision
point is the same width under both wrappers (strict builds *on top of* the regular filters, and its
harvest-feed cap is a no-op once `_filter_min_begging` has already narrowed feed to ~1–5). The deeper
concern is absolute, not wrapper-specific: at low sims any wide node (placement ≤24, fencing ≤40, the
breed/market frontiers) is prior-dominated — unvisited children rely entirely on the prior — so the
branching-reduction benefit is *conditional on prior quality*. The `UCT + regular` control (§10) is
what reveals whether regular's extra fencing/sow breadth hurts before the prior is good.

### 3.2 AlphaZero PUCT + restated FPU
Adopt canonical AlphaZero PUCT at decision nodes:

```
U(s,a) = Q(s,a) + c_puct · P(s,a) · √(Σ_b N(s,b)) / (1 + N(s,a))
```

(The Leela/MuZero log-scaled `c_puct` matters only at 10k+ sims — not used.) Two consequences vs the
current UCT code:
- **Remove "force-visit every unvisited child first."** Today the search visits all unvisited
  children (random order) before exploiting. Under PUCT the prior *orders* exploration of unvisited
  children; low-prior children may never be visited at low sims — that non-visiting **is** the
  soft-pruning. Critical under wide regular-legality nodes.
- **`fpu_offset` becomes the Q-placeholder** for unvisited children: `Q(unvisited) = Q(parent) −
  fpu_offset` (FPU reduction). The prior carries the exploration ordering.

**`c_puct` calibration:** `Q` is normalized by the existing `leaf_value_scale` (FIRST_NN C15), so
`c_puct` must be commensurate with the *normalized* Q spread — calibrate against it, or reproduce
the C15 mis-scaled-constant failure (a confidently-wrong result from an uncalibrated constant).

### 3.3 Chance nodes are orthogonal
The hidden-info refactor models the round-card reveal as a **chance node** (`decider_of → None`,
routed by deterministic round-robin over ≤3 public `RevealCard`s, never leaf-evaluated, carrying a
P0 frame label). A policy has **no role** at a chance node — nature isn't choosing. PUCT changes only
**decision-node** selection; the chance-node path is untouched (HIDDEN_INFO_DESIGN.md §8).

### 3.4 The policy as a black box
MCTS sees the policy only through one contract:

```
policy_fn(state, legal_actions) -> {action: prior}     # normalized over legal_actions
```

All head structure — dispatch by decision-point type, fixed-width masking, score-the-set scoring,
renormalization — lives **inside** `policy_fn`. mcts.py never inspects heads. **Untrained
decision-point types fall back to uniform**, so the placement-only v1 works immediately and heads
light up with zero mcts.py changes. The returned dict is keyed by the engine `Action` objects (frozen
→ hashable; they match exactly the `legal_actions` passed in) and stored once per node (§7).

### 3.5 Leaf flow: enumerate → step through forced moves → value; prior stays lazy
At a newly reached node the search **enumerates legal actions before evaluating the value** — it must,
to make the next two decisions:

- **Forced moves are stepped through.** A non-terminal node with exactly one legal action is *not*
  evaluated; the search steps to the forced child in the **same simulation** and continues, evaluating
  V only at the next multi-option decision or terminal. The forced node stays in the tree (DAG-friendly,
  so transposing branches still share it); its Q is filled by backprop of the downstream value, which
  is correct because the move is forced (`V*(forced) = V*(child)`). Two payoffs: V queries stay
  **in-distribution** (the value net is trained on real decisions and terminals, never on singleton
  mid-action states), and a forced chain is traversed in **one** simulation, not one-per-node. This
  applies to **both UCT and PUCT** — so UCT is no longer byte-identical to the pre-PUCT engine, an
  intentional change — and it mirrors how a forced (1-candidate) reveal is already stepped through by
  the chance-routing path (§3.3). Players' forced moves and nature's forced reveals now behave alike.

- **The prior stays lazy.** Enumerating early would, if the prior were bundled in, compute the policy
  on *every* new node — including the singletons we step through and the never-expanded frontier
  leaves. So legal-action enumeration (`_compute_legal_actions`) is **split** from prior computation
  (`_ensure_priors`, run on the first *selection* from a node, and skipped for singletons). With
  **separate** value/policy nets (v1) this keeps the policy forward pass off those nodes — strictly
  optimal for separate nets.

- **Q is backprop-only.** `visits`/`value_sum` are updated solely at backprop (path-only), never on the
  forward descent; a stepped-through node, being on the path, gets `visits=1` and `value_sum=±V(downstream)`
  on its creating sim's backprop (fields start at `0`).

The enumerate-before-value ordering is also what lets a **shared value+policy net** later produce both
in one pass at the leaf (§9.1): the policy head needs the legal-action set, which is now computed before
the value. (See §9 for that evolution, where `evaluate_leaf` returns `(value, trunk_vec)` and the policy
consumes the cached trunk.)

---

## 4. The policy representation (decision-point taxonomy → heads)

Grounded in the `legality.py` enumerators + the **regular** `restricted_legal_actions` wrapper. The
policy is **factored**: dispatch on the pending-stack top (the same dispatch `legal_actions` does) to
exactly one head, then map that head's output to a prior over the legal set.

Two structural facts shape the head set:
1. Under regular restriction, **plow/stable/room collapse to ~1 cell** (`_filter_cell_priority`) and
   **renovate is a singleton** — so they're usually singleton-skipped and need no real head.
2. **Placement dominates** the non-singleton decisions an agent actually faces, and several
   ChooseSubAction parents narrow to 1–2 via ordering filters. So **placement is the v1 priority.**

### 4.1 Head assignments

| Head class | Decision points | Action type(s) | Set under regular | v1 |
|---|---|---|---|---|
| **Fixed-width + mask** | Worker placement | `PlaceWorker(space)` | ≤24 placeable (25 `SPACE_INDEX` − `lessons`); head indexes the vocabulary, masks to legal | **trained** |
| Fixed-width + mask | 11 ChooseSubAction parents (FarmExpansion, GrainUtil, Cultivation, SideJob, House/FarmRedev, Fencing, Major/Minor, Clay/Stone Oven, Farmland) | `ChooseSubAction(name)` + `Stop` | ≤3 (often 1–2 after ordering) | uniform |
| Fixed-width + mask | Build Major | `CommitBuildMajor(idx, return_fireplace)` | ≤14 (10 majors + ≤4 Cooking-Hearth fireplace-return variants) | uniform |
| (singleton) | Plow / Stable / Room / Renovate | cell commits, `CommitRenovate` | →1 (cell-priority for plow/stable/room; renovate mandatory-first); singleton-skipped | n/a |
| **Score-the-set** | Sow | `CommitSow(grain, veg)` | 3–8 tuples | uniform |
| Score-the-set | Bake | `CommitBake(grain)` + `FireTrigger` | 5–15, **heterogeneous** | uniform |
| Score-the-set | Harvest **feed** | `CommitConvert(...)` + `CommitHarvestConversion(use)` | 1–5 after min-begging, **heterogeneous** | uniform |
| Score-the-set | Harvest **breed** | `CommitBreed(s,b,c)` | 3–12 Pareto | uniform |
| Score-the-set | Sheep / Pig / Cattle markets | `CommitAccommodate(s,b,c)` | 1 when all animals fit (singleton-skipped); 2–8 only under overflow | uniform |
| Score-the-set | Build Fences | `CommitBuildPasture(cells)` | 5–40 of the 109-universe | uniform |
| (nature) | Card reveal | `RevealCard` | chance node — **no prior** | n/a |

### 4.2 Fixed-width + mask
A fixed index per action in a global vocabulary, masked to the legal subset at inference (gather logits
for the legal actions, mask the rest, softmax). BC target = the chosen action's index. The
vocabularies:
- **Placement:** the 24 placeable spaces in `SPACE_INDEX` order (the 25 entries minus `lessons`).
- **ChooseSubAction:** the **5** names that are ever a *real* (non-singleton) choice — `sow`,
  `bake_bread`, `build_stables`, `improvement`, `build_fences`. (Side Job's `build_stable` is unified
  into `build_stables` — see §12.) Excluded because they are always singleton-skipped (auto-applied,
  never a recorded choice): **`renovate`** and **`build_major`** (each the sole option at its space —
  renovation is mandatory-first; the family game has no minor path, so the real major decision is
  `CommitBuildMajor`, a separate head), and **`build_rooms`** / **`plow`** (the `rooms-before-stables` /
  `plow-before-sow` ordering filters always offer them alone — confirmed **0** examples across the
  policy-session data; they'd only be real choices under unrestricted legality).
- **Major:** the enumerated `CommitBuildMajor(idx, return_fireplace)` variants (≤14).

This is the bulk of the heads and all of v1 (placement only).

### 4.3 Score-the-set (pointer)
For the parameterized / Pareto decision points (feed, breed, markets, sow, bake, fences) there is no
fixed vocabulary — the legal set is state-dependent tuples. Score each legal action by a small
feature vector `φ(a)` (action-type + its parameters: animal deltas, grain/veg counts, pasture cells,
craft toggle), `logit(a) = g(h_state, φ(a))`, softmax over the legal set. `φ` design is **TBD** and
is the main open piece of the broader-heads work (c2). Heterogeneous nodes (bake = bakes + triggers;
feed = converts + craft toggles) score both action kinds with the same `g` over their `φ`.

### 4.4 Stop and mixed nodes
`Stop` is a fixed-width logit appended to any head whose decision point can end (multi-shot pendings,
parents). Mixed nodes concatenate the relevant heads' logits and softmax over the union.

---

## 5. Policy network architecture

- **Input:** the existing `encode_state(state, player_idx) -> np.ndarray` (170 features,
  `ENCODING_VERSION = 2`), called with `player_idx = decider`. The policy reuses it verbatim — no new
  state encoder.
- **Trunk → heads:** an MLP trunk (reuse `ConfigurableMLP`, which is documented as composable as a
  sub-encoder) feeding the per-decision-point heads of §4. Fixed-width heads are linear projections to
  their index space; score-the-set heads are a shared `g(h, φ(a))` scorer.
- **Separate from the value net in v1** (the user is training it standalone). The §3.4 black box hides
  this from MCTS. A **shared trunk** (value + policy heads on one trunk) is the natural later move; the
  interface in §9 is designed for it.
- **Perspective:** encode from the **decider's** frame (`encode_state(state, decider)`), matching how
  the prior is consumed at a decision node.

---

## 6. Behavioral-cloning training

- **Targets:** every `DecisionSnapshot` already stores `(state, chosen_action, decider_idx)` — the BC
  target. No schema change, no new data generation. ~65–82k games of regular-restricted snapshots
  (FIRST_NN §6 / the run dirs).
- **Target extraction:** map `chosen_action` → (decision-point type, head, index-or-φ-target) via the
  §4 mapping; cross-entropy per head. v1 trains only the placement head (filter snapshots to
  empty-stack placement decisions).
- **Temperature filtering:** the data has a bimodal `T` (95% uniform[0.3,1.0] + 5% `T=4`). The `T=4`
  tail (near-random) and the high-`T` games are **noisy imitation targets** — filter them out or
  down-weight by `T`. The per-game `p0/p1_temperature` is stored, so this is a dataset filter. **TBD:**
  hard cutoff vs weighting.
- **Infra reuse:** the encoder, dataset builder (`build_datasets`), training loop, and checkpoint
  conventions from `agricola/agents/nn/` carry over; add a policy loss/head and a per-head target
  expander. The encoded-vector cache (FIRST_NN §10.5) applies unchanged (encoding is target-agnostic).
- **Eval-of-the-head (not gameplay):** per-head top-1 / top-k accuracy vs the held-out ensemble
  choices — a cheap sanity metric. Gameplay is the real metric (§10).

---

## 7. PUCT in `agricola/agents/mcts.py` — the change plan

The tree, transposition table, backprop, chance routing, macro machinery, and `evaluate_leaf` are
**untouched**. PUCT is a localized, additive change; UCT stays runnable as a control (it's just
`policy_fn is None`).

1. **`MCTSNode`** (after line 123): add `_action_priors: Optional[dict[Action, float]] = None` —
   `P(s,·)` over `_legal_actions`, set once at expansion, `None` for never-expanded / chance nodes.
2. **`_compute_legal_actions`** (enumerate only): run `expand_macros` only when `fence_mode ==
   FenceMode.MACRO` (skipped for `FLATTEN`). The prior is **not** computed here — it's split into
   **`_ensure_priors`** (run lazily on the first *selection* from a node, skipped for chance nodes and
   singletons), so enumerating early for the step-through doesn't drag an eager `policy_fn` call onto
   every new node (§3.5).
3. **`MCTSSearch.__init__`** (line 191): add `policy_fn=None` and `fence_mode=FenceMode.MACRO`.
   `policy_fn=None` reproduces UCT **byte-identical**; `FenceMode.MACRO` preserves today's macro
   behavior (see §8 for the enum + toggle rationale).
4. **`_simulate` decision block**: dispatch — `policy_fn is None` → `_uct_select_child` (existing UCT
   logic), else `_puct_select_child`. **Forced-move step-through:** a newly created non-terminal
   `len(legal)==1` child is enumerated and `continue`d through in the same sim (not `break`+evaluated),
   so V lands at the downstream real decision (§3.5). Chance routing / terminal / backprop unchanged.
5. **`_select_via_puct` + `_puct_select_child`** (beside `_select_via_ucb`): score over **all**
   `_legal_actions` (uncreated children compete via prior + FPU, materialized on selection); drop the
   random-unvisited phase; FPU reduction via `fpu_offset`; AlphaZero PUCT term. **Singleton
   short-circuit:** `len(_legal_actions)==1` returns that action with no prior, so `_ensure_priors`
   fires only for genuine multi-option nodes.
6. **`MCTSAgent`** (line 656): reuse `c_uct` as the exploration constant (`= c_puct` in PUCT mode),
   documented and **calibrated against `leaf_value_scale`** (§3.2).
7. **(optional, for D)** `root_visit_distribution(root) -> {action: visits}` accessor — PUCT
   debugging now, π-targets later. A few lines; visit counts are already tracked, just not surfaced.

**Unchanged:** `find_or_create_node`, `add_edge`, `re_root`, `evaluate_leaf`, `_chance_route`, the
chance branch, backprop, `_select_action_with_temperature` (the agent's *played* move is still the
**visit-count** softmax at root, not PUCT scores — the AlphaZero "search with PUCT, play by visits"
split). `_select_via_ucb` / `_pick_unvisited_action` / `_unvisited_actions` stay, used by the UCT path.

**Caller wiring** (outside mcts.py): `scripts/play_mcts_match.py` gains `--policy <checkpoint>` (builds
the `policy_fn`: load net, dispatch, renormalize), `--fence-mode {macro,flatten,sequence_prior}`, and the legality-wrapper
choice (regular for PUCT). The §10 controls are then flag combinations over the same code.

---

## 8. Fencing

Fencing is a multi-shot *path* of `CommitBuildPasture` commits, which is why MCTS currently collapses
it into `MacroFencingAction`. The three modes are *mutually exclusive*, so they are one
`fence_mode: FenceMode` enum (not a `use_macros` bool):

- **`MACRO` (constructor default).** Today's behavior — `expand_macros` collapses a fence layout into
  greedy + random `MacroFencingAction` children. Kept for the UCT baseline; **not combined with PUCT**
  (macros are MCTS-internal, not engine actions, so they're awkward to attach policy targets to — the
  old "mode 2," dropped *as a PUCT option*).
- **`FLATTEN` (v1 PUCT default).** `expand_macros` is bypassed; each `CommitBuildPasture` is a plain
  tree action under regular legality, in the engine-native action space the policy trains on. Cost: a
  deeper tree (the thing macros avoided), tolerable under a prior.
- **`SEQUENCE_PRIOR` (later, c3).** Keep a shallow main tree by abstracting fencing into endpoint
  *layouts* generated from the policy, and recover per-step training targets:
  - Sample macro chains from the per-step fencing policy at node creation → an empirical prior over
    final layouts; use it as the PUCT prior over the (endpoint) children.
  - PUCT improves it → search-improved endpoint visits `N_search(L)`.
  - Store per-endpoint **edge counts** `n(s, a, L)` (a sufficient statistic — sequences sharing edges
    merge; the endpoint keying `L` is irreducible) and reconstruct per-step targets:

  ```
  1. π_improved(L) = N_search(L) / Σ_L′ N_search(L′)        # search-improved endpoint distribution
  2. C_L           = Σ_a n(s0, a, L)                        # samples reaching endpoint L (= its Stop-count)
  3. mass(s, a)    = Σ_L [π_improved(L) / C_L] · n(s, a, L) # reweight prior-sampled edges by improved endpoints
  4. π_target(·|s) = normalize_a mass(s, a)                # per-step target at every partial state s
  ```

  Faithful at every partial state; within-layout ordering is inherited from the prior (benign — layout
  value is order-invariant). `n(s,a)` marginalized over `L` cannot recover step 3's endpoint
  reweighting — that is why the keying on `L` is irreducible. Inject sampler noise so that
  strong-but-low-prior layouts are still discovered.

`SEQUENCE_PRIOR` trades search efficiency (shallow tree) against reconstruction bookkeeping +
sampler-bounded discovery; `FLATTEN` trades a deeper tree for direct per-step targets and free PUCT
discovery. **v1 = `FLATTEN`**; `SEQUENCE_PRIOR` is the principled upgrade, measured *against* `FLATTEN`.

**Toggle design (for multiple independent features).** Mutually-exclusive variants — like the three
fence modes — belong in *one enum*, not a pile of bools. Genuinely *independent* on/off features
(`leaf_differential`, a future Dirichlet-root-noise flag, …) stay as separate params, or move into a
small `SearchConfig` dataclass (mirroring `opt_config.py`) once they proliferate. And UCT-vs-PUCT is
*not* a flag at all — it's implied by whether `policy_fn` is set.

---

## 9. Forward-compat: shared trunk & the self-play loop

### 9.1 Shared value+policy trunk
When value and policy share a trunk, the §3.4 black box becomes too coarse (it hides the trunk →
recomputes it). The interface tightens to:

```
evaluate_leaf(state) -> (value, trunk_vec)          # stash trunk_vec on node._trunk
policy_from_trunk(trunk_vec, legal_actions) -> {action: prior}
```

One trunk pass per node, value head at leaf-eval, policy head at expansion from the cached vector —
strictly better than eager-combine (it also skips the policy head on dead leaves), and additive to the
v1 code (one extra return + one node field + one model output). `ConfigurableMLP`'s composability
already anticipates exposing the trunk. **Caveat:** the value is a differential (`e(s,0) − e(s,1)`, two
perspectives); cache the **decider-perspective** trunk and make the shared net's forward convention
consume perspectives consistently. **Not built in v1**; the v1 interface is chosen so it doesn't
foreclose this.

### 9.2 Self-play policy improvement (phase d) — prerequisites
- **Root visit-count accessor** (§7, item 7) — the π target source.
- **`DATA_VERSION` bump + recording hook:** add a `policy_target` (visit distribution) field to
  `DecisionSnapshot` (changes the pickled shape → bump `DATA_VERSION`) and have `play_recording_game`
  run MCTS and store the root visit distribution. BC needs none of this (it reuses `chosen_action`).
- **Dirichlet root noise** for self-play exploration.
- The iteration loop (self-play → train → gate → repeat), reusing the FIRST_NN promotion/registry
  conventions.

---

## 10. Evaluation

PUCT needs **both** a value leaf and a policy prior. v1: value leaf = champion `M_82k_warmM62k`
(`nn_models/best`), policy prior = the new placement head (uniform elsewhere).

**Controls (to attribute effects, matched sims):**
- `UCT + strict` — the existing baseline (current champion search config).
- `UCT + regular` — isolates the cost of the legality switch from the prior benefit.
- `PUCT + regular` with the **prior ladder**: uniform → (optional) value-derived → trained placement
  head. Uniform vs trained isolates whether the prior does real work.

**Protocol:** head-to-head via `scripts/play_mcts_match.py`, P0/P1 symmetric single-seat over many
seeds (CLAUDE.md: don't seat-swap). Pin sim budgets (e.g. 200 / 500 / 1500) and the success criterion
**before** running (e.g. *PUCT+regular+placement beats UCT+strict head-to-head at equal sims*).
Cheap secondary signal: placement-head top-1 accuracy vs the ensemble.

**Expected hazard:** at low sims with regular's wider branching, a weak/uniform prior may underperform
strict's hard prune — the `UCT + regular` control will show this, and is *why* we measure before
trusting "PUCT reduces branching."

---

## 11. Open questions

- **`φ(a)` design** for the score-the-set heads (feed/breed/markets/sow/bake/fences) — the main c2
  design piece.
- **Temperature handling** for BC targets — hard cutoff vs `T`-weighting.
- **`c_puct` / `fpu_offset` values** under normalized Q — needs a small calibration sweep.
- **`FLATTEN` vs `SEQUENCE_PRIOR` fencing** long-term — settled empirically once both exist (`FLATTEN` is the baseline).
- **Separate vs shared trunk** timing — v1 separate; when does the shared trunk pay off enough to build?
- **Uniform vs value-derived fallback** for untrained decision-point types in c1.

---

## 12. Pre-implementation edits

**Unify the Side Job stable sub-action name `build_stable` → `build_stables`.** This collapses the
ChooseSubAction vocabulary (§4.2 — `build_stable` folds into `build_stables`), one slot for "build
stable(s)" instead of two. It is a *deliberate reversal* of the SESSION_HISTORY.md decision that kept
the names split per each space's rule text ("Build 1 stable" vs "build stables") — we prefer one
internally-consistent name over rule-text fidelity for the policy head. Edit sites (the *only*
occurrences of the quoted `"build_stable"` string; the function names `_can_build_stable` /
`_execute_build_stable` are unrelated and stay):
- `agricola/legality.py:1177` — `ChooseSubAction(name="build_stable")` → `"build_stables"`
- `agricola/resolution.py:465` — `if action.name == "build_stable":` → `"build_stables"`
- `tests/test_side_job.py` (5 occurrences) — `ChooseSubAction(name="build_stable")` → `"build_stables"`
- `SESSION_HISTORY.md` — add a note recording the reversal (leave the original entries as the
  historical record; the frozen `task_files/*` are not touched).

**Status: applied** to the working tree (uncommitted) — `legality.py` + `resolution.py` + `test_side_job.py`
renamed, the two SESSION_HISTORY entries carry reversal notes, and `test_side_job.py` plus a 249-test
engine/agent sweep pass green.

No other engine touch-ups are gated before the §7 PUCT work — the visit-count accessor and the
`fence_mode` enum are part of *that* implementation, not pre-edits.

---

## 13. Status

Design complete; **c0 — the PUCT machinery — is implemented and tested**: the `FenceMode` enum,
`policy_fn` injection, `_action_priors` + lazy `_ensure_priors`, `_select_via_puct` /
`_puct_select_child`, the `_simulate` dispatch with **forced-move step-through** (§3.5), `uniform_policy`,
and `root_visit_distribution` in `agricola/agents/mcts.py`. The step-through applies to **both UCT and
PUCT**, so UCT is no longer byte-identical to the pre-PUCT engine (intentional). `tests/test_puct.py`
(incl. the step-through invariant, for both modes) and the rest of the engine/agent suite are green.
The decision-point taxonomy (§4) is grounded in the
`legality.py` enumerators and the regular `restricted_legal_actions` wrapper. The mcts.py change plan
(§7) is grounded in a full read of the current code. v1 = c0 (PUCT machinery, uniform prior) + c1
(placement head) is the first end-to-end slice; the search track (c0) and the policy-training track
are independent and can proceed in parallel, meeting only at the §3.4 interface contract.
