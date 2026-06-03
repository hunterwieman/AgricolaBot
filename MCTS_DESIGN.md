# MCTS Design — AgricolaBot

This document specifies the design for the Monte Carlo Tree Search (MCTS) agent for AgricolaBot. It is the working spec for a new implementation phase that follows the heuristic-agent phase documented in `V3_DESIGN.md` and `V3_TRAINING_PIPELINE.md`.

It captures both the architectural decisions and their rationales so a new coding session can pick up the work without reading the design-conversation history.

> **For new sessions:** read this doc plus `CLAUDE.md` (project status), `V3_DESIGN.md` (heuristic evaluator that MCTS uses for leaf values), and `agricola/agents/restricted.py` (action-pruning infrastructure MCTS leans on).

---

## 1. Goals and positioning

### 1.1 Phase context

The project's roadmap (see CLAUDE.md "Project Goal"):

1. Game engine — complete
2. Baseline agents — random + heuristic complete (V1, V2, V3)
3. Card system — deferred
4. Imitation learning — deferred
5. Self-play RL — MCTS is the entry point here
6. Evaluation tooling

This doc covers the **MCTS scaffolding for phase 5**. The MCTS agent uses `HubrisHeuristicV3` (V3_DESIGN.md) as its leaf value function and operates on action sequences via `strict_restricted_legal_actions` (a new strict-mode wrapper added as a prerequisite).

### 1.2 Strategic motivation — escape the heuristic paradigm

The current `HubrisHeuristicV3` plus tuning pipeline is approaching its ceiling. Each successive tuning round produces smaller gains; the most recent (iter4 alphas re-tune) showed mild overfitting and parameter reversals — classic saturation signals. The fundamental limit is not the tuning algorithm but the **evaluator paradigm**: V3 is a hand-designed feature combination, and its expressiveness is bounded by what we thought to encode. Combinatorial choices that depend on multi-step planning, opponent modeling, or non-decomposable strategic patterns are systematically outside its reach. More tuning produces diminishing returns; no amount of CMA-ES on V3's coefficients can give it the kind of understanding a learned model could.

MCTS is the bridge out of this paradigm in two senses:

1. **Immediate**: MCTS adds multi-turn planning and opponent modeling on top of the existing evaluator. Even with the same V3 leaf values, search-based decisions are strictly more expressive than 1-step lookahead. The strength gain comes from BETTER USE of the evaluator, not a different evaluator.

2. **Future-enabling**: MCTS-vs-MCTS shared-tree self-play produces structured training data — state → visit-count distributions and state → MCTS-derived value estimates — which is exactly what a learned policy/value network would train on. This is project phase 5 per CLAUDE.md (AlphaZero-style self-play RL). Even an MCTS that only modestly beats V3 is valuable because the data it produces is much richer than what the heuristic can generate on its own.

So MCTS isn't just an incremental agent improvement — it's the infrastructure that unblocks the next major phase of the project.

### 1.3 Empirical context

A separate experiment (this session) showed **exhaustive deterministic sub-tree search performs WORSE than greedy** (margin −4.49 over 800 games — see V3_DESIGN.md §8.9) due to evaluator-bias amplification: when you max over an imperfect evaluator, you systematically pick the states it overrates. MCTS sidesteps this via AVERAGING statistics over many sims rather than maximizing one evaluator score — the bias has less leverage on Q estimates that aggregate across many leaf evaluations.

This both motivates MCTS over deeper deterministic search AND argues against trying to "fix" the heuristic via more deterministic-search tools.

### 1.4 Operational goals

The MCTS agent must support two top-level use cases:

1. **MCTS vs MCTS with shared tree** for self-play. Both seats use the same MCTSAgent instance; sims contribute to one tree shared across both players.
2. **MCTS vs other agent** (e.g., MCTS vs `HubrisHeuristicV3`) with the MCTS agent maintaining its own tree.

Both must work end-to-end via the existing `play_game(initial, agents)` driver in `agricola/agents/base.py`.

---

## 2. Glossary

- **MCTS**: Monte Carlo Tree Search. Iteratively builds a tree of game states, choosing which subtree to expand by balancing exploitation (high mean value) against exploration (low visit count).
- **UCT**: Upper Confidence Bound applied to Trees. The selection formula `Q + c · √(ln N_parent / N_child)`. "Vanilla UCT" = UCT without an action prior.
- **PUCT**: Polynomial UCT (AlphaZero variant). Adds a prior `π(a|s)` to the selection formula. **Not used in this design**.
- **FPU**: First-Play Urgency. A default value (typically `parent.mean_q − offset`) assigned to unvisited children in place of UCT's `+∞`. Avoids forcing "sweep every child once" before discrimination.
- **Rollout / Simulation**: in classical MCTS, playing from a leaf to game-end and using the terminal reward. **Not used in this design** — we use leaf-evaluation instead.
- **Leaf evaluation**: compute the leaf's value directly via the heuristic, no game-end rollout. Per-sim cost: one heuristic call.
- **DAG-MCTS / Transposition table**: identify equivalent states (via `GameState.__hash__`) and reuse statistics across paths. Tree becomes a DAG.
- **Macro-action**: a pre-computed action sequence representing one full sub-action chain. Used for Fencing only. (Note: CommitConvert at harvest uses a separate ranking-cap mechanism — §7.4 — not a macro.)
- **Decider**: player whose decision is awaited at a state. Computed via `decider_of(state)` from `agricola/agents/base.py` — either `state.current_player` (empty pending stack) or `state.pending_stack[-1].player_idx`.
- **Nature decider (`decider_of` returns `None`)**: at a round-card reveal state the pending stack's top is a `PendingReveal` whose `player_idx` is `None`, so `decider_of(state)` returns `None` — no player decides; nature does. This is the signal that a node is a chance node.
- **Chance node**: the MCTSNode for a reveal state (`decider_of(state) is None` — nature decides which round card is revealed). A chance node is *routed through* by deterministic round-robin over its reveal outcomes — never UCB-selected and never leaf-evaluated. Its value *is* the expectation over its outcome children; the search reaches that expectation by averaging the values backed up through it across many sims.
- **Determinization / ISMCTS**: hidden-information techniques that either sample a concrete world (determinization) or maintain observer-specific information sets (ISMCTS). **Not used here.** Agricola's hidden round-card order is symmetric (neither player knows it), exogenous (nature's shuffle, not a function of any private choice), revealed identically to both players, and uniform over outcomes. Under those conditions an information set is observer-independent and ISMCTS collapses onto ordinary MCTS with explicit chance nodes — so plain chance nodes are exactly correct and the cheapest tool (see §3.15 and HIDDEN_INFO_DESIGN.md §2).

---

## 3. Architecture decisions

Each subsection: the decision, brief rationale, and what it implies.

### 3.1 Vanilla UCT (not PUCT)

**Decision:** selection uses `Q(s,a) + c · √(ln N_parent / N_child)`. No prior.

**Rationale:** simpler MVP. PUCT requires a meaningful prior over actions, and our best candidate (heuristic-derived softmax) has known problems for chain-initiating actions like PlaceWorker(fencing) — V3 doesn't see post-chain effects so its prior would mis-rank those. Vanilla UCT sidesteps the prior-quality question entirely. Can be upgraded to PUCT in a later iteration.

**Default `c` = 1.4** (= √2, the classical UCB1 constant). Tunable empirically.

### 3.2 FPU instead of +∞ for unvisited

**Decision:** when computing UCB at a node, unvisited children get a finite UCB:

```
UCB(unvisited) = parent.mean_q + c · √(ln(parent.visits + 1) / 1)
```

This is "treat unvisited as if visited once with Q = parent.mean_q." The exploration term has denominator 1 (the virtual visit count), so unvisited children get the LARGEST exploration bonus — they're aggressively explored — but the bonus is finite and grows with `N_parent` rather than being a constant +∞.

**Rationale:** vanilla UCT with +∞ for unvisited forces a complete "sweep all children" pass at every node before any discrimination. For high-branching nodes (e.g., `PendingHarvestFeed` with N up to 19, or `PendingBuildMajor` with 11), this consumes a meaningful fraction of the budget on mandatory exploration.

The naive FPU formulation (just `UCB(unvisited) = parent.mean_q - offset`) is broken for vanilla UCT: visited children's UCB is `child.mean_q + c · √(ln N_parent / N_child)`, which strictly exceeds `parent.mean_q` whenever exploration > 0 AND `child.mean_q ≈ parent.mean_q` (the typical case). Unvisited children would never be explored after the first sim. The corrected formulation above gives unvisited children an explicit exploration bonus matching what they'd get if they had been visited exactly once. This is sometimes called "Bayesian UCT" or "FPU with first-visit virtual count."

**Edge case:** if `parent.visits == 0` (e.g., very first sim at root), `parent.mean_q` is undefined. Treat it as 0.0 in that case. The first sim picks uniformly at random among children (since all unvisited UCBs are equal at 0).

### 3.3 Random ordering when expanding among tied-UCB children

**Decision:** when multiple unvisited children compete (both at FPU default, or both at +∞), tiebreak randomly rather than by deterministic `legal_actions` output order.

**Rationale:** deterministic ordering creates systematic bias — whichever action happens to come first in `legal_actions` gets sampled first at every node. Random ordering averages this out across many sims.

### 3.4 DAG with transposition table (from the start)

**Decision:** maintain a `transpositions: dict[GameState, MCTSNode]` mapping unique states to their nodes. When expanding a child, look up the child state in the table; if present, link to existing node (multiple parents pointing at one node).

**Rationale:** `GameState` is already hashable (per CLAUDE.md "Engine performance pass — Change 9"). Two different action sequences can reach the same state (action-ordering commutativity within and across turns). Tree-only MCTS would create separate nodes for equivalent states, wasting visits. The DAG variant deduplicates immediately and accumulates statistics per unique state.

### 3.5 Path-only backpropagation on DAG

**Decision:** during backprop, walk only the path descended in this simulation. Don't propagate to other parents of touched nodes.

**How the path is tracked:** the SELECT phase builds a local `path: list[MCTSNode]` as it descends, appending the chosen child at each step. Backprop iterates over THIS list. It does NOT read `node.parents` — that field is reserved for future variants (full-DAG backprop, debugging tools). In a DAG where a node has multiple parents, the simulation descended through exactly one of them; `path` knows which.

**Rationale:** full DAG backprop (propagating to all parents of every node on the path) is asymptotically more sample-efficient but significantly more complex. Path-only backprop is the standard simplification — when other paths to a node are descended later, they pick up the cached statistics naturally. Information propagates lazily but isn't lost.

### 3.6 Chain handling: macro-enumeration for Fencing, in-tree for others

**Decision:**

- **Fencing**: at every node where a fencing-initiating action is legal, replace that action with up to `1 + n_random_fencing` distinct macro-actions:
  - 1 greedy macro: heuristic plays the fencing chain to completion
  - Up to `n_random_fencing` random macros (default 4): uniform random over `strict_restricted_legal_actions` plays the fencing chain to completion
  - Dedup by post-chain state hash; if fewer distinct paths exist (e.g., strict restrictions narrow the space), use however many we got
- **Two trigger points** are both handled by the same macro-generation code (see §5.4 for the implementation):
  1. `PlaceWorker(fencing)` at empty stack (worker-placement Fencing)
  2. `ChooseSubAction("fences")` at `PendingFarmRedevelopment` (Farm Redevelopment's fencing portion)
- **All other non-atomic chains** (Cultivation, Grain Utilization, Major Improvement, etc.): standard MCTS in-tree. Each sub-action decision is its own MCTS node.

**Rationale:** the heuristic plays Fencing weakly (the strategic depth of pasture configuration choice exceeds V3's evaluator). Macro-enumeration generates multiple distinct fencing options as separate tree children, letting UCT discriminate among them rather than locking in heuristic-only fencing play. The same logic applies to both fencing trigger points — Farm Redev's fencing portion has the same evaluator weakness.

For other chains: under strict restrictions (see §3.7) they collapse to ≤5 decision points. FPU keeps the first-visit sweep cost manageable. In-tree allows MCTS to discover better sub-action sequences than the heuristic alone would pick.

**A new Action subclass** `MacroFencingAction(label: str)` is introduced as an MCTS-internal action type. The engine never sees these — the agent translates them into real engine actions via the parent's `macro_sequences` dict (keyed by MacroFencingAction).

```python
@dataclass(frozen=True)
class MacroFencingAction(Action):
    """MCTS-internal action representing a complete fencing chain.
    Stored in MCTSNode.children dicts as a key; never reaches the engine.
    The agent translates this into the actual engine action sequence via
    the parent's macro_sequences[macro_action] lookup. Lives in
    agricola/agents/mcts.py (NOT actions.py) — purely MCTS scaffolding."""
    label: str  # e.g., "greedy", "random_0", "random_1", ...
```

### 3.7 Strict restrictions applied throughout

**Decision:** all MCTS legality queries go through `strict_restricted_legal_actions(state)`, a new function added as a prerequisite to MCTS. It wraps the existing `restricted_legal_actions` with four additional filters:

- Cultivation sow-max (§7.1)
- Grain-Utilization veggie rule (§7.2)
- Fencing patterns (§7.3)
- Harvest-feed cap (§7.4)

**Also added to `restricted_legal_actions` (regular, not strict):** drop `CommitHarvestConversion(use=False)` — declining a craft is redundant; the player can skip a craft by going directly to `CommitConvert`. See §7.0.

**Rationale:** strict restrictions collapse trivially-suboptimal action choices into single canonical options. This reduces MCTS branching factor at sub-action chains where the strategic choice is small. The "if a filter would empty the action set, fall back" behavior preserves correctness — strict restrictions never strand the engine.

The use=False filter goes in the REGULAR restricted (not strict) because dropping a strictly-redundant action is a correctness-preserving simplification, not a strategic heuristic. Other agents (HubrisHeuristicV3, etc.) benefit too.

### 3.8 Leaf evaluation (no rollouts)

**Decision:** MCTS does NOT play out from leaves to game end. Each simulation:
1. Selects a path through the tree via UCT
2. Expands one new child at the leaf
3. **Evaluates the new child's state via the heuristic** (one heuristic call)
4. Backpropagates that value up the path

**Rationale:** speed. Rollouts to game end cost ~5-50ms each (greedy heuristic rollout of a 50-decision game). At 500 sims/move that's 2.5-25 seconds per move. Leaf evaluation costs ~50us per leaf — 25ms per 500 sims. ~100-1000x speedup.

The trade is real: rollouts produce values rooted in actual game outcomes; leaf evaluation produces values from the heuristic's snapshot judgment. We accept this — V3 is a reasonable approximation of expected value, and many cheap sims beats few expensive sims in practice.

### 3.9 Leaf value: heuristic margin

**Decision:** at each newly-expanded leaf, compute the leaf's value as:

```python
value_p0 = evaluate_hubris_v3(leaf_state, 0, config) - evaluate_hubris_v3(leaf_state, 1, config)
```

This is the score margin from P0's perspective. Then sign-flip during backprop (see §5.3).

**Rationale:** matches the actual game payoff (margin between players, not absolute score). Already-existing `_terminal_margin_value(state, player_idx)` in `agricola/agents/heuristic.py` implements this for terminal states (`Phase.BEFORE_SCORING`). MCTS leaves use the equivalent formulation for non-terminal states.

Note: the terminal-margin convention (`own_score − opponent_score`) was added across all four evaluators (`evaluate_simple`, `evaluate_hubris_v1/v2/v3`) in a recent session edit. See `_terminal_margin_value` in `agricola/agents/heuristic.py`.

### 3.10 Tree reuse across moves + shared trees

**Decision:** the MCTSAgent maintains its tree across calls (re-rooting when the engine state matches a tree node). For self-play with identical agents, both seats can share one tree by passing the same MCTSAgent instance to both slots in `play_game`.

**Modes:**

- **Separate trees** (default): each MCTSAgent instance maintains its own tree. Re-roots on its own calls (every 2 plies in a 2-player game). Used for MCTS-vs-other-agent matchups.
- **Shared tree** (self-play optimization): pass the same MCTSAgent instance to both `agents` slots in `play_game`. The agent re-roots on every ply (each call alternates between P0 and P1 contexts). All sims contribute to one tree.

**Rationale:** tree reuse across the agent's own calls is standard MCTS — sims from one move's search persist into the next. Shared trees in self-play roughly double effective sims (both sides contribute to one tree). Toggleable based on opponent identity.

### 3.11 Macro-fencing commitment (stateful agent)

**Decision:** when MCTS picks a macro-fencing child at the root, the agent **commits** to that macro's full action sequence. Subsequent agent calls within the same fencing chain return the next pre-recorded macro action without re-running MCTS.

**Rationale:** macro-fencing is meaningful only if the agent commits to the path MCTS chose. Re-running MCTS at sub-action decisions would re-introduce the in-tree chain expansion this design avoids. The commitment is per-chain: once Stop pops PendingBuildFences, normal MCTS resumes for the next decision (whichever player and whatever pending state — opponent's turn after worker-placement Fencing, or back to PendingFarmRedev after Farm Redev's fencing portion).

**Implementation:**

- Each **parent** that generates macros stores them on a `macro_sequences: dict[MacroFencingAction, list[Action]]` field — keyed by macro action label, value is the full engine-action sequence (including leading trigger action). Sequences are parent-specific (stored on the generator, not the endpoint), so two parents whose macros converge on the same endpoint state each retain their own sequence.
- MCTSAgent maintains `_pending_macro_actions: list[Action]`. On each `__call__`, if non-empty, pop and return the next action without running MCTS.
- When MCTS runs and picks a `MacroFencingAction` from the root: look up `root.macro_sequences[action]`, return `sequence[0]` (the trigger action), queue `sequence[1:]` in `_pending_macro_actions`.
- If two distinct macros from the SAME parent happen to produce the same endpoint state (greedy + random converging, or two randoms converging), they're dedup'd at generation time via the macros-dict-keyed-by-endpoint — only one MacroFencingAction is created. The retained one is whichever was generated first. Both sequences are valid from this parent.

### 3.12 Action selection: softmax over visits with T=0.2

**Decision:** after running MCTS sims, pick the next action by softmax over visit counts with temperature T=0.2.

```python
counts = {a: child.visits for a, child in root.children.items()}
probs = softmax({a: math.log(c) for a, c in counts.items()}, temperature=0.2)
action = sample(probs)
```

Actually slightly cleaner: `probs[a] = counts[a]^(1/T) / sum_a counts[a]^(1/T)`. At T → 0 this approaches argmax. At T = 1 it samples proportional to visit counts.

**Rationale:** T=0.2 is close to argmax (most-visited typically wins) but allows occasional second-place picks. Adds small variability useful for diverse game records.

### 3.13 Budget: 500 simulations per move

**Default**: 500 sims per call. Tunable.

**Rationale:** modest budget for first iteration.

Per-sim cost is roughly bounded by leaf evaluation (~50-100us) plus expansion overhead (~40us when a new node is created), giving ballpark ~100-200us per sim. See §5.0 for the per-operation breakdown.

**Wall time and memory will be measured in Phase 4 validation.** Estimates here are coarse — the actual numbers depend on tree shape, transposition hit rate, and how often macro-fencing triggers. We'll revise the budget if profiling reveals very different actual costs.

### 3.14 Single-process, no parallelism

**Decision:** the MVP runs MCTS single-threaded. Tree manipulation is straightforward without locks.

**Rationale:** simpler. Parallel MCTS (virtual loss, root parallelism, leaf parallelism) is a significant code complication. Defer until profiling shows MCTS is the bottleneck.

### 3.15 Chance nodes for hidden round-card reveals

**Decision:** the hidden round-card order is modeled with **explicit chance nodes**. A reveal state — where the engine's top pending frame is a `PendingReveal` with `player_idx = None`, so `decider_of(state)` is `None` — becomes a chance node (`MCTSNode.is_chance == True`). The chance node's reveal outcomes are routed by **deterministic round-robin** over the ≤3 in-search candidates; the chance node is **never UCB-selected** and **never leaf-evaluated** (the leaf is always a decision or terminal node descended to *past* the reveal).

**Why chance nodes, not ISMCTS / determinization.** The hidden order is symmetric (neither player knows it), exogenous (nature's shuffle, not a function of any private choice), revealed identically to both players, and uniform over outcomes. Under those conditions the information set is observer-independent and ISMCTS collapses onto ordinary MCTS with chance nodes — so plain chance nodes are exactly correct and the cheapest tool. The in-search fan-out is tiny (≤3; round 1's k=4 reveal is dealer-resolved at game start and never reaches search) and the reveal distribution is exactly uniform, so chance nodes are cheap *and* bias-free (no strategy fusion). See HIDDEN_INFO_DESIGN.md §2.

**Round-robin, never UCB.** Routing picks the least-routed outcome (RNG tiebreak), keeping the visit mix over outcomes exactly uniform — so the chance node's plain `value_sum / visits` converges to the uniform reveal expectation `Σ (1/k) V(child)` with no weighted estimator. UCB is never run at a chance node: nature is not an adversary to exploit, and round-robin guarantees coverage of all ≤3 outcomes plus variance reduction at low visit counts.

**Never the leaf.** A chance node's value *is* the expectation over its outcome children, so evaluating it directly would be meaningless; we always descend to a post-reveal decision child and evaluate there (which also keeps an NN leaf evaluator in-distribution). Both ways a chance node is reached — SELECT descending into an existing one, or EXPAND creating one from a round-ending action — route *through* it rather than evaluating it (see §5.6).

**Frame convention: `decider = 0`, meaning carried by `is_chance`.** A chance node's `decider` field is set to `0` — a P0 value-frame label, **not** a real player. `evaluate_leaf` already returns P0-frame values, so a chance node accumulates `+leaf_p0` and its decision-node parent reads it with the standard `child.decider != parent.decider` sign-flip (which flips iff the parent is P1, correct for a P0-frame value). This keeps the backprop loop and the UCB read **unchanged** — the only thing that distinguishes a chance node is the `is_chance` flag, which gates routing, not `decider`.

**No hidden state read.** The reveal candidates are reconstructed from public state (the unrevealed action spaces and the current stage), and the distribution is uniform — so MCTS reads no hidden `Environment` ground truth. The chance node fans out over *which card could be revealed*, exactly the common-knowledge information set.

---

## 4. Data structures

### 4.1 MCTSNode

```python
@dataclass(eq=False)
class MCTSNode:
    state: GameState
    decider: int   # 0 or 1, from decider_of(state)
    parents: list["MCTSNode"]  # for DAG (multi-parent); list, not set
    children: dict[Action, "MCTSNode"]
    action_from_parent: Action | None  # one of possibly many; for debugging
    
    # Back-reference to the search this node belongs to. Set at creation
    # by find_or_create_node. Lets the node access search-level config
    # (legal_actions_fn, evaluator, n_random_fencing) without each node
    # duplicating these.
    search: "MCTSSearch"
    
    visits: int = 0
    value_sum: float = 0.0  # cumulative reward from decider's perspective
    
    # Chance-node (round-card reveal) state. `is_chance` is True iff this node
    # is a nature decision (decider_of(state) is None). For a chance node,
    # `decider` is set to 0 as a P0 value-frame label (NOT a real player), so
    # the backprop / UCB sign-flip math is unchanged; `is_chance` carries the
    # "nature" meaning and gates routing. See §3.15 / §5.6.
    is_chance: bool = False
    # Per-outcome round-robin counter, keyed by RevealCard action. Bumped on
    # each route through this chance node. Used INSTEAD of child.visits because
    # a post-reveal child shared by another DAG path inflates child.visits,
    # which would skew routing away from uniform. See §5.6.
    chance_counts: dict[Action, int] = field(default_factory=dict)
    
    # Populated only if this node generated macros (via _compute_legal_actions
    # → expand_macros). Maps MacroFencingAction → full engine-action sequence
    # to play (INCLUDING the leading trigger action). Sequences are parent-
    # specific (stored on the generator, not the endpoint). See §3.6 / §5.4.
    macro_sequences: dict[MacroFencingAction, list[Action]] = field(default_factory=dict)
    
    # Cached for performance, lazy-populated.
    _legal_actions: list[Action] | None = None
    _unvisited_actions: set[Action] | None = None
    
    @property
    def mean_q(self) -> float:
        return self.value_sum / self.visits if self.visits > 0 else 0.0
    
    def is_terminal(self) -> bool:
        return self.state.phase == Phase.BEFORE_SCORING
    
    def has_all_children_visited(self) -> bool:
        if self._unvisited_actions is None:
            self._compute_legal_actions()
        return len(self._unvisited_actions) == 0
    
    def _compute_legal_actions(self):
        if self.is_terminal():
            self._legal_actions = []
            self._unvisited_actions = set()
            return
        raw = filter_implemented(self.search.legal_actions_fn(self.state))
        # Macro-fencing expansion: replace fencing-trigger actions with macros.
        # Side effect: populates self.macro_sequences and self.children
        # (the macro children).
        self._legal_actions = self.search.expand_macros(self.state, raw)
        self._unvisited_actions = set(self._legal_actions)
```

**Hash semantics:** `@dataclass(eq=False)` skips the auto-generated field-based `__eq__`/`__hash__`. Python falls back to default object identity (`is`) for equality and `id`-based hashing. Two MCTSNodes are equal iff they're the same object — which is exactly the semantics we want (one node per unique state, enforced by the transposition table). This makes nodes safely usable in identity-keyed sets/dicts (used in `re_root`'s reachability traversal).

We use `list[MCTSNode]` for `parents` (not `set`) to avoid needing custom hash semantics for set membership — small in-degree (typically 1-3) makes the linear `in` check trivial. The `add_edge` helper (§5.5) is the single choke point that enforces parents-list dedup.

**Search reference:** the back-reference to `MCTSSearch` lets the node call `self.search.legal_actions_fn(self.state)`, `self.search.expand_macros(...)`, and `self.search.evaluate_leaf(self.state)` without each node duplicating config. The search holds the configurable parameters (rollout policy, leaf evaluator, n_random_fencing, etc.); nodes hold per-state tree state.

**Mutation safety:** mutation of `children`, `visits`, `value_sum`, `parents`, `_unvisited_actions` is fine — MCTSNode is mutable by design. Only `state` (a frozen GameState) is immutable.

**`legal_actions` caching strategy.** The `_legal_actions` field on MCTSNode is the **per-node cache**: computed once on first access (via `_compute_legal_actions`), reused on every subsequent visit to this node. This is the primary mechanism for `legal_actions` reuse during MCTS — direct field access (~10ns), no dict lookup.

The engine also exposes `legal_actions_cache()` (a context manager that memoizes `legal_actions(state)` keyed by `id(state)`, see CLAUDE.md "Engine performance pass — Change 9"). **MCTS does not use it.** Per-node caching covers the hot path completely — every UCT descent reads `node._legal_actions` directly, never recomputing. The engine-level cache exists for other callers (the heuristic agent during macro-fencing chain generation, ad-hoc tests, etc.) and is independent of MCTS's per-node caching.

### 4.2 MCTSSearch

```python
class MCTSSearch:
    """Holds the transposition table AND search-level configuration:
    legal_actions_fn, leaf evaluator, n_random_fencing, RNG. Nodes hold
    a back-reference to their search for config access."""
    
    def __init__(
        self,
        legal_actions_fn = strict_restricted_legal_actions,
        evaluator_config: HeuristicConfigV3 = None,
        n_random_fencing: int = 4,
        rng_seed: int = 0,
    ):
        self.transpositions: dict[GameState, MCTSNode] = {}
        self.root: MCTSNode | None = None  # set by re_root on first agent call
        self.legal_actions_fn = legal_actions_fn
        self.evaluator_config = evaluator_config or load_v3_best()
        self.n_random_fencing = n_random_fencing
        self.rng = np.random.default_rng(rng_seed)
        # Heuristic agent used for greedy macro-fencing chain generation.
        # Constructed once; reused across all macro generations.
        self.heuristic = HubrisHeuristicV3(
            config=self.evaluator_config,
            seed=rng_seed,
            lookahead="turn",
            legal_actions_fn=self.legal_actions_fn,
        )
    
    # Required imports (the implementation file will need):
    #   from agricola.agents.heuristic import (
    #       HubrisHeuristicV3, HeuristicConfigV3, evaluate_hubris_v3,
    #   )
    #   from agricola.agents.restricted import strict_restricted_legal_actions
    #   import numpy as np
    # `load_v3_best` is a shorthand here for whatever pattern loads
    # tuned_configs/v3_best.json into a HeuristicConfigV3 (see existing
    # pattern in scripts/tune_heuristic.py's _resolve_config).
    
    def find_or_create_node(self, state, parent=None, action_from_parent=None):
        # See §5.5
        ...
    
    def evaluate_leaf(self, state) -> float:
        """Compute leaf value in P0's frame, always via `evaluate_hubris_v3`.
        
        Terminal (Phase.BEFORE_SCORING): `evaluate_hubris_v3(state, 0)`
        already returns the margin (per `_terminal_margin_value` inside
        the evaluator). Return it directly. Computing `e0 - e1` at
        terminal would double the value (since at terminal e1 = -e0).
        
        Mid-game: `evaluate_hubris_v3(state, p)` returns player p's
        heuristic quality (one-player value, NOT a margin). Subtract to
        get a margin in P0's frame.
        """
        if state.phase == Phase.BEFORE_SCORING:
            return evaluate_hubris_v3(state, 0, self.evaluator_config)
        return (evaluate_hubris_v3(state, 0, self.evaluator_config)
                - evaluate_hubris_v3(state, 1, self.evaluator_config))
    
    def expand_macros(self, parent_state, raw_actions):
        """Detect fencing triggers in raw_actions and replace each with
        MacroFencingAction children. Handles both trigger points (PlaceWorker
        and Farm Redev's ChooseSubAction). See §5.4 for full implementation."""
        ...
    
    def _find_fencing_triggers(self, state, raw_actions):
        """Return all actions in raw_actions that initiate a fencing chain.
        See §5.4."""
        ...
    
    def _generate_fencing_macros(self, parent_state, trigger_action):
        """Generate up to (1 + n_random_fencing) distinct macros for one
        trigger. Dedup by endpoint state. See §5.4."""
        ...
    
    def _chain_ended_for_fencing(self, state, decider):
        """Chain ends when PendingBuildFences is no longer the top of the
        stack. See §5.4."""
        ...
    
    def add_edge(self, parent, child, action):
        """Single choke point for DAG edge creation. See §5.5."""
        ...
    
    def re_root(self, new_root):
        """See §5.5."""
        ...
```

### 4.3 MCTSAgent

```python
class MCTSAgent:
    """MCTS agent implementing the Agent protocol from agricola/agents/base.py.
    
    The constructor requires a pre-built MCTSSearch. Three usage patterns:
    
    1. Separate trees: each MCTSAgent has its own MCTSSearch
       (`MCTSAgent(search=MCTSSearch(...))`). Used for matches against other
       agent types (heuristic, random, or a different MCTS configuration).
    
    2. Shared tree via shared agent: pass the same MCTSAgent instance to
       both `agents` slots in play_game. Both seats use the same tree AND
       the same agent-level config (sims_per_move, c_uct, etc.).
    
    3. Shared tree via shared MCTSSearch: pass one MCTSSearch to multiple
       MCTSAgent constructors. They share the tree state but can differ in
       agent-level parameters.
    """
    
    def __init__(
        self,
        search: MCTSSearch,
        sims_per_move: int = 500,
        c_uct: float = 1.4,
        fpu_offset: float = 0.0,
        action_selection_temperature: float = 0.2,
        rng_seed: int = 0,
    ):
        """The agent takes a fully-constructed MCTSSearch. Search-level
        config (legal_actions_fn, n_random_fencing, evaluator_config) lives
        on the search; agent-level config (sims_per_move, c_uct, fpu_offset,
        temperature, action-RNG) lives here.
        
        For sharing: construct one MCTSSearch and pass it to multiple
        MCTSAgent instances. They share the tree but can differ in
        agent-level config.
        
        For the simple case: `MCTSAgent(search=MCTSSearch())` works."""
        assert sims_per_move >= 1, "sims_per_move must be at least 1"
        self.search = search
        self.sims_per_move = sims_per_move
        self.c_uct = c_uct
        self.fpu_offset = fpu_offset
        self.temperature = action_selection_temperature
        # Agent-level RNG: for action selection (softmax sampling at top
        # level). Tree-internal randomness (macro generation, expansion
        # tiebreaks) uses self.search.rng for clear separation.
        self.rng = np.random.default_rng(rng_seed)
        
        # Pending macro-fencing action queue (see §3.11)
        self._pending_macro_actions: list[Action] = []
    
    def __call__(self, state: GameState) -> Action:
        # If currently playing out a committed macro, return the next queued
        # action. No MCTS, no re-root — the tree stays untouched until the
        # macro chain completes.
        if self._pending_macro_actions:
            return self._pending_macro_actions.pop(0)
        
        # Normal MCTS path: find/create root node for current state, re-root.
        root = self.search.find_or_create_node(state)
        self.search.re_root(root)
        
        # Run sims
        for _ in range(self.sims_per_move):
            self._simulate(root)
        
        # Pick action via softmax over visit counts
        action = self._select_action_with_temperature(root)
        
        # If MCTS chose a macro, queue the macro's remaining actions and
        # return the first one (PlaceWorker(fencing) or ChooseSubAction("fences")).
        if isinstance(action, MacroFencingAction):
            # Look up the sequence on THIS PARENT (root.macro_sequences),
            # not on the endpoint child. Parent-keyed storage ensures the
            # sequence was generated FROM this parent state.
            sequence = root.macro_sequences[action]
            # sequence[0] is the trigger action (returned now)
            # sequence[1:] are the chain commits + Stop (queued for subsequent calls)
            for queued in sequence[1:]:
                self._pending_macro_actions.append(queued)
            return sequence[0]
        
        return action
    
    def _simulate(self, root):
        ...  # see §5.1
    
    def _select_action_with_temperature(self, root):
        counts = [(a, child.visits) for a, child in root.children.items()]
        if self.temperature <= 0:
            # Argmax with random tiebreak via self.rng
            best = max(c for _, c in counts)
            ties = [a for a, c in counts if c == best]
            return ties[self.rng.integers(len(ties))]
        scaled = [(a, c ** (1 / self.temperature)) for a, c in counts]
        z = sum(s for _, s in scaled)
        probs = [s / z for _, s in scaled]
        idx = self.rng.choice(len(counts), p=probs)
        return counts[idx][0]
```

No `_replay_macro` indirection needed — the macro's full action sequence (including the leading trigger action) is stored on `root.macro_sequences[macro_action]` when the macro was generated (see §5.4). The agent just looks it up.

This works because we generate macros eagerly at the parent's `_compute_legal_actions` time and store the full action sequence on the parent's `macro_sequences` dict. By the time MCTS picks a macro at action-selection time, the sequence is already there.

---

## 5. Algorithm details

### 5.0 Operation costs (cost cheat-sheet)

The MCTS code mixes very cheap operations (dict lookups, arithmetic) with very expensive ones (engine `step`, `legal_actions` enumeration, GameState hashing, heuristic evaluation). Knowing the cost of each makes the per-simulation flow easier to reason about. Approximate costs (Agricola scale):

| Operation | Cost | When it's called |
|---|---|---|
| `dict[K]` lookup where K is a small frozen dataclass (Action) | ~sub-microsecond | Every UCT descent step: `node.children[action]` |
| `set` membership / `set.discard()` for Action elements | ~sub-microsecond | Tracking `_unvisited_actions` |
| Arithmetic (UCB formula per child) | ~tens of nanoseconds | Every UCT descent step |
| `len(node.children)` / list iteration over N children | ~few microseconds for N ≈ 14 | UCT descent: comparing all children |
| `node._legal_actions` field access (after cache populated) | ~10 nanoseconds | Every UCT descent step at every node |
| `id(state)` and `dict[int]` lookup | ~70 nanoseconds | (NOT used in MCTS — engine-level only, see §4.1) |
| `step(state, action)` (engine state transition) | ~10 microseconds | Once per new node created (expansion) |
| `find_or_create_node(state)` — hashes GameState + dict lookup | ~26 microseconds when state is hashed; ~10ns if state already in cache | Once per new node created (expansion) |
| `_compute_legal_actions(state)` — calls `strict_restricted_legal_actions` | ~30 microseconds | **Once per node**, lazy on first access |
| `search.evaluate_leaf(state)` — heuristic evaluation (margin) | ~50-100 microseconds | Once per sim, at the leaf |
| Macro-fencing generation (1 greedy + ≤4 random chain rollouts) | ~50-300 milliseconds (see §5.4 for breakdown) | Once per node whose `_legal_actions` contains a fencing trigger |

**Key insight:** the costly operations (`step`, `legal_actions`, GameState hashing, leaf evaluation) are paid at most **once per node**, not per visit. Repeated visits to an existing node only pay dict lookups and arithmetic. This is what makes MCTS scale: tree construction is paid once, traversal is cheap.

The path-building during SELECT is just a sequence of dict lookups, one per descent step — pure cheap work.

### 5.1 Per-simulation flow (one sim)

```
def simulate(search, root_node):
    # ---------------- 1. SELECT + EXPAND ----------------
    # Descend until we reach the node to EVALUATE: a freshly-created decision
    # leaf or a terminal node. Build `path` as we go — this local list is what
    # backprop will iterate over. CHANCE nodes (round-card reveals) are
    # transparent: routed through by round-robin, never expanded-as-leaf,
    # never evaluated (§5.6).
    #
    # COST: per descent step is ~sub-microsecond (set check / UCB arithmetic
    # over ~14 children / dict lookup / list append). Total descent cost for K
    # nodes: ~K × few-microseconds. No engine step / legal_actions / hashing
    # during descent of existing nodes.
    path = [root_node]
    node = root_node
    while True:
        if node.is_terminal():
            break
        if node.is_chance:
            # Route round-robin to one reveal outcome (created on first route).
            # A freshly-created outcome is the new leaf; an existing one we
            # keep descending into. The chance node is on the path (gets
            # visits / value) but is never the eval target. See §5.6.
            action = chance_route(node)              # round-robin pick + counter bump
            child = node.children.get(action)
            is_new = child is None
            if is_new:
                child = search.find_or_create_node(
                    step(node.state, action), parent=node, action_from_parent=action,
                )
            path.append(child)
            node = child
            if is_new:
                break          # fresh post-reveal decision node = leaf
            continue           # existing outcome → keep descending
        # ---- decision node ----
        if not node.has_all_children_visited():
            # EXPAND one unvisited action at this node.
            action = pick_unvisited_action(node)         # random pick from set, sub-us
            node._unvisited_actions.discard(action)      # set discard, sub-us
            if isinstance(action, MacroFencingAction):
                # Macro children are pre-created at parent's
                # _compute_legal_actions time (eager generation, §5.4). Just
                # look it up. COST: dict lookup, sub-us.
                child = node.children[action]
            else:
                # Normal action: step (~10us) + transposition lookup (~26us).
                child_state = step(node.state, action)          # ~10us
                child = search.find_or_create_node(             # ~26us GameState hash
                    child_state, parent=node, action_from_parent=action,
                )
            path.append(child)                            # sub-us
            node = child
            if node.is_chance:
                continue       # expanded into a chance node → route through it
            break              # decision / terminal leaf for evaluation
        # Fully expanded → UCB descend one step and loop.
        action = select_via_ucb(node)      # arithmetic over N children, sub-us
        node = node.children[action]        # dict lookup, sub-us
        path.append(node)                   # list append, sub-us
    
    # ---------------- 3. EVALUATE ----------------
    # Heuristic evaluation of the leaf state. `node` is never a chance node
    # here — the descent breaks only at a decision / terminal leaf. Returns
    # the value in P0's perspective. See MCTSSearch.evaluate_leaf (§4.2) —
    # terminal uses
    # raw score margin (score(P0) - score(P1)); mid-game uses heuristic
    # margin (evaluate_hubris_v3(state, 0) - evaluate_hubris_v3(state, 1)).
    #
    # COST: ~50-100us. Dominant per-sim cost when expanding a non-fencing
    # action; expansion + leaf eval together are ~75-150us, dwarfing the
    # ~few-us descent.
    leaf_value_p0 = search.evaluate_leaf(node.state)
    
    # ---------------- 4. BACKPROPAGATE ----------------
    # Iterate the path built up by SELECT (NOT node.parents — see §5.3).
    # Sign-flip per node's decider so value_sum stays in decider's frame.
    #
    # COST: ~K × sub-us additions. Trivial.
    for n in path:
        if n.decider == 0:
            n.value_sum += leaf_value_p0     # arithmetic, sub-us
        else:
            n.value_sum += -leaf_value_p0
        n.visits += 1                         # increment, sub-us
```

Note: `path` includes the freshly-expanded leaf so its visit count starts at 1.

**Per-sim cost summary:**

- Descent through K existing nodes: ~K × few-us = sub-millisecond for typical K=5-15
- Expansion (one new node): ~10us step + ~26us hash + sub-us bookkeeping = ~40us
- Leaf eval: ~50-100us
- Backprop: ~K × sub-us = trivial
- **Total per sim: ~100-200us** (dominated by expansion + leaf eval; descent is cheap because it's all dict lookups and arithmetic)

For 500 sims/move: ~50-100ms per move. Plus the ONE-TIME cost of `_compute_legal_actions` on each newly-touched node (~30us each, amortized once per node ever — paid the first time that node is descended INTO during a future sim, not at creation).

### 5.2 UCB formula with FPU

```python
def ucb(child, parent, c=1.4):
    """UCB1 from parent's decider's perspective. Uses FPU for unvisited
    children: treat as if visited once with Q = parent.mean_q."""
    parent_decider = parent.decider
    
    # Parent's mean Q (from parent_decider's perspective). Treat as 0 if
    # parent hasn't been evaluated yet (very first sim at fresh root).
    parent_mean_q = (parent.value_sum / parent.visits) if parent.visits > 0 else 0.0
    
    if child.visits == 0:
        # FPU: virtual visit count = 1, virtual Q = parent.mean_q.
        # Exploration term uses parent.visits + 1 to handle parent.visits == 0.
        return parent_mean_q + c * math.sqrt(math.log(parent.visits + 1) / 1)
    
    # Convert child's stored Q (from child.decider's perspective) to parent's frame
    child_q_from_child_frame = child.value_sum / child.visits
    if child.decider == parent_decider:
        child_q_from_parent_frame = child_q_from_child_frame
    else:
        child_q_from_parent_frame = -child_q_from_child_frame
    
    exploration = c * math.sqrt(math.log(parent.visits + 1) / child.visits)
    return child_q_from_parent_frame + exploration
```

Note `select_via_ucb` picks `argmax_a ucb(child=children[a], parent=parent)`.

**Why this works:** an unvisited child's UCB is `parent_mean_q + c·√(ln(N_p+1))`. A visited child's UCB is `child_mean_q + c·√(ln(N_p+1) / N_child)`. As `N_child` grows, the visited's exploration term shrinks. As long as `child_mean_q ≈ parent_mean_q` (typical), the visited child's UCB eventually drops below the unvisited child's UCB, and another unvisited child gets explored. So MCTS naturally cycles through children rather than getting stuck on one.

If a visited child has `child_mean_q >> parent_mean_q` (it's a great move), it keeps winning despite its shrinking exploration — exploitation. If `child_mean_q << parent_mean_q` (it's a bad move), visited's UCB drops below unvisited's quickly, and we move on. The behavior is the classical exploration-exploitation balance.

### 5.3 Sign-flip backpropagation

The leaf value is computed in **P0's perspective** (always — fixed reference frame). During backprop, each node's `value_sum` is updated in **that node's decider's perspective**:

```python
def backpropagate(path, leaf_value_p0):
    """`path` is the list built up by SELECT during descent (see §5.1).
    It records the exact sequence of nodes this simulation traversed —
    which is well-defined even in a DAG where nodes have multiple parents.
    `node.parents` is NOT consulted here."""
    for node in path:
        if node.decider == 0:
            node.value_sum += leaf_value_p0
        else:
            node.value_sum += -leaf_value_p0
        node.visits += 1
```

This is the canonical two-player zero-sum MCTS pattern. Generalizes naturally to N-player or general-sum games by replacing the +/- with `leaf_value_vector[node.decider]`.

**DAG illustration.** Suppose state X is reached via two paths in the tree: parent_B → X and parent_C → X. `X.parents = [parent_B, parent_C]`. When simulation 17 descends `[root, parent_B, X]`, backprop updates X, parent_B, and root. When simulation 18 descends `[root, parent_C, X]`, backprop updates X (again — accumulating into the same `value_sum`), parent_C, and root. X's statistics correctly aggregate across both paths' simulations; parent_B and parent_C each see only the sims that went through them. This is the right semantics for DAG-MCTS with path-only backprop.

### 5.4 Macro-fencing expansion

Triggered from `_compute_legal_actions` on the parent node. When raw legal actions contain a fencing-initiating action (either `PlaceWorker(fencing)` or `ChooseSubAction("fences")` at `PendingFarmRedevelopment`), replace each trigger with up to `1 + n_random_fencing` distinct macro-actions. Side effect: create the macro child nodes immediately via `find_or_create_node` so they're wired up before MCTS visits them.

```python
class MCTSSearch:
    def expand_macros(self, parent_state, raw_actions):
        """Detect fencing triggers in raw_actions and replace each with
        up to (1 + n_random_fencing) distinct MacroFencingAction children.
        Returns the modified action list. Side effects: creates macro
        child nodes via find_or_create_node AND stores each macro's
        action sequence on parent_node.macro_sequences (parent-keyed)."""
        triggers = self._find_fencing_triggers(parent_state, raw_actions)
        if not triggers:
            return raw_actions
        
        other_actions = [a for a in raw_actions if a not in triggers]
        parent_node = self.transpositions[parent_state]
        macro_actions = []
        
        for trigger_action in triggers:
            macros = self._generate_fencing_macros(parent_state, trigger_action)
            for label, sequence, endpoint_state in macros:
                macro_action = MacroFencingAction(label=label)
                # Store the sequence on THIS parent (not on the endpoint).
                # Two parents whose macros converge on the same endpoint each
                # keep their own sequence.
                parent_node.macro_sequences[macro_action] = sequence
                self.find_or_create_node(
                    endpoint_state,
                    parent=parent_node,
                    action_from_parent=macro_action,
                )
                macro_actions.append(macro_action)
        
        return other_actions + macro_actions
    
    def _find_fencing_triggers(self, state, raw_actions):
        """Return all actions in raw_actions that initiate a fencing chain."""
        triggers = []
        for a in raw_actions:
            # Trigger 1: PlaceWorker on the Fencing space
            if isinstance(a, PlaceWorker) and a.space == "fencing":
                triggers.append(a)
            # Trigger 2: ChooseSubAction("fences") at PendingFarmRedevelopment
            elif (isinstance(a, ChooseSubAction)
                  and a.name == "fences"
                  and state.pending_stack
                  and isinstance(state.pending_stack[-1], PendingFarmRedevelopment)):
                triggers.append(a)
        return triggers
    
    def _generate_fencing_macros(self, parent_state, trigger_action):
        """Generate up to (1 + n_random_fencing) distinct macros for one
        trigger. Returns list of (label, sequence, endpoint_state). Dedup
        by endpoint state within this parent — fewer distinct endpoints
        means fewer macros."""
        state_after = step(parent_state, trigger_action)
        decider = decider_of(parent_state)
        
        macros = {}  # dict[GameState, tuple[label, sequence]]
        
        # 1. Greedy macro: heuristic plays chain to completion
        greedy_state = state_after
        greedy_seq = [trigger_action]
        while not self._chain_ended_for_fencing(greedy_state, decider):
            a = self.heuristic(greedy_state)
            greedy_seq.append(a)
            greedy_state = step(greedy_state, a)
        macros[greedy_state] = ("greedy", greedy_seq)
        
        # 2. Random macros: uniform random over strict_restricted_legal_actions
        attempts = 0
        max_attempts = self.n_random_fencing * 3
        while (len(macros) < 1 + self.n_random_fencing
               and attempts < max_attempts):
            attempts += 1
            r_state = state_after
            r_seq = [trigger_action]
            while not self._chain_ended_for_fencing(r_state, decider):
                actions = filter_implemented(self.legal_actions_fn(r_state))
                a = actions[self.rng.integers(len(actions))]
                r_seq.append(a)
                r_state = step(r_state, a)
            if r_state not in macros:                   # ← O(1) dedup check
                macros[r_state] = (f"random_{len(macros) - 1}", r_seq)
            # If r_state is already in macros, count the attempt but don't store
        
        return [(label, seq, end) for end, (label, seq) in macros.items()]
    
    def _chain_ended_for_fencing(self, state, decider):
        """A fencing chain ends when PendingBuildFences is no longer the
        top of the stack (it was popped by Stop). Game-end and decider-
        handoff are also checked defensively."""
        if state.phase == Phase.BEFORE_SCORING:
            return True
        if decider_of(state) != decider:
            return True
        if not state.pending_stack:
            return True
        return not isinstance(state.pending_stack[-1], PendingBuildFences)
```

**Terminal endpoint edge case**: if the chain plays all the way to game-end (extreme: late-round-14 with Stop triggering scoring), `_chain_ended_for_fencing` returns True at `state.phase == BEFORE_SCORING`. The endpoint state IS terminal, the node is created with terminal status, and `evaluate_leaf` handles the terminal case correctly. No special handling needed.

**Generalization to both triggers.** The `_chain_ended_for_fencing` check is "top of stack is no longer PendingBuildFences." This works for both trigger points without any special-casing:

- **PlaceWorker(fencing)**: after trigger, stack = `[PendingBuildFences]`. After Stop, stack = `[]` → top check (empty stack) ends chain.
- **ChooseSubAction("fences") in Farm Redev**: after trigger, stack = `[PendingFarmRedev, PendingBuildFences]`. After Stop on the inner pending, stack = `[PendingFarmRedev]` → top is now PendingFarmRedev, not PendingBuildFences → chain ends. MCTS resumes normal in-tree search at whatever's left in Farm Redev (which might be a renovate-vs-stop decision, or a singleton Stop if renovate was already done).

**Storage of distinct macros (handling fewer than N).** The macros dict in `_generate_fencing_macros` is keyed by endpoint `GameState`. Every random rollout's endpoint is checked: `if r_state not in macros` adds, else discards. The dict size is the count of distinct macros found from THIS PARENT. Loop exits when we have `1 + n_random_fencing` distinct or hit `max_attempts = 3 × n_random_fencing` without finding more. If only 1 macro emerges (all paths converge from this parent), fencing becomes effectively atomic with one child — UCT has no fork to discriminate but the algorithm doesn't error.

**Sequences stored per-parent, not per-endpoint.** Each parent that generates macros writes them to its own `macro_sequences` dict (keyed by MacroFencingAction). The endpoint MCTSNode has no sequence field. This avoids the cross-parent ambiguity where two parents whose macros converge on the same endpoint would overwrite each other's stored sequence (rare but possible if parents differ only in fencing-affected state).

**Cost.** Per parent: 1 greedy chain rollout (heuristic-driven) + up to `3 × n_random_fencing` random chain attempts. Heuristic rollouts are ~5-50ms each; random rollouts are cheaper per step but variable in chain length. Total ~50-300ms per parent's first `_compute_legal_actions` call. Cached via transposition table — generated once per unique parent state.

**No regeneration on transposition hit.** When a parent state is found in the transposition table, its `_legal_actions` cache is already populated (or will be lazy-populated on first access). Macros are NOT re-generated on revisit.

### 5.5 Transposition table maintenance

```python
class MCTSSearch:
    def __init__(self, ...):
        self.transpositions: dict[GameState, MCTSNode] = {}
        # ... other config (see §4.2)
    
    def find_or_create_node(self, state, parent=None, action_from_parent=None):
        existing = self.transpositions.get(state)
        if existing is not None:
            # Already in DAG — link parent if new
            if parent is not None:
                self.add_edge(parent, existing, action_from_parent)
            return existing
        # New node. A reveal state has decider_of(state) is None (nature);
        # flag it as a chance node and label its frame as P0 (decider=0) so
        # the backprop / UCB sign-flip math is unchanged. See §3.15 / §5.6.
        d = decider_of(state)
        is_chance = d is None
        node = MCTSNode(
            state=state,
            decider=0 if is_chance else d,   # frame label when is_chance; real player otherwise
            is_chance=is_chance,
            parents=[],
            children={},
            action_from_parent=action_from_parent,
            search=self,
            # macro_sequences starts empty; populated only if this node
            # later generates macros via _compute_legal_actions → expand_macros.
        )
        self.transpositions[state] = node
        if parent is not None:
            self.add_edge(parent, node, action_from_parent)
        return node
    
    def add_edge(self, parent: MCTSNode, child: MCTSNode, action) -> None:
        """Single choke point for DAG edge creation. Maintains parents-list
        dedup invariant: each parent appears at most once in child.parents."""
        parent.children[action] = child
        if parent not in child.parents:  # list `in` uses identity eq (eq=False)
            child.parents.append(parent)
```

**Re-rooting** is how we preserve work across moves. Conceptually: when the agent is called at a new game state, navigate to that state's existing node in the tree (if any), designate it as the new root, and discard everything not reachable from it.

**Walkthrough.** Suppose at the previous call the agent was at state S0 with `search.root = node_S0` and built out a tree below S0 with 500 sims. The agent picked A0, the opponent picked B0, and now the engine state is S2. The agent's next call:

1. `find_or_create_node(S2)` — returns the existing node for S2 (it was created during the previous search when sims descended through S2's predecessor).
2. `re_root(S2_node)` — set this as the new root. Sims that previously descended through S2 still have their statistics intact.
3. Prune the transposition table to drop entries for states no longer reachable from S2.

Without re-rooting, every agent call would start from a fresh tree, throwing away all the search work that already covered the current state. With re-rooting, the agent typically inherits a meaningful chunk of the previous search's tree (often 30-70% of nodes, depending on the depth of the chosen actions).

```python
def re_root(self, new_root):
    if new_root is self.root:
        return  # no-op
    # Walk live subtree from new_root, collect reachable node ids
    reachable_ids = set()
    queue = [new_root]
    while queue:
        node = queue.pop()
        if id(node) in reachable_ids:
            continue
        reachable_ids.add(id(node))
        queue.extend(node.children.values())
    # Prune
    self.transpositions = {
        s: n for s, n in self.transpositions.items() if id(n) in reachable_ids
    }
    self.root = new_root
```

Uses `id(node)` for the reachability set (identity-based, sub-us per check) since MCTSNode has identity equality via `@dataclass(eq=False)`.

Optional optimization for later: lazy pruning (only prune when table grows beyond a threshold).

### 5.6 Chance-node routing

A reveal state — where `decider_of(state) is None` because the top pending frame is a `PendingReveal` with `player_idx = None` — is a chance node (§3.15). Chance nodes are **transparent** to the descent: always routed through, never expanded-as-leaf, never evaluated. The `_simulate` loop (§5.1) handles them in its SELECT+EXPAND phase; this section gives the routing detail.

**Where a chance node is entered.** Two places:

1. **SELECT** descends into an already-existing chance node (top of the `while` loop).
2. **EXPAND** of a decision node's round-ending action *creates* a chance node — handled by the `if node.is_chance: continue` immediately after expansion, so the next loop iteration routes through it rather than evaluating it.

**`_chance_route(node)`** picks one reveal outcome by deterministic round-robin:

```python
def chance_route(node):
    # node._legal_actions are the RevealCard outcomes (≤3 in search).
    if node._legal_actions is None:
        node._compute_legal_actions()
    candidates = node._legal_actions
    counts = node.chance_counts
    min_count = min(counts.get(a, 0) for a in candidates)
    least = [a for a in candidates if counts.get(a, 0) == min_count]
    action = least[0] if len(least) == 1 else least[rng.integers(len(least))]
    counts[action] = counts.get(action, 0) + 1   # bump THIS node's counter
    return action
```

The first k routes create the k outcome children (each a leaf the first time it is created); later routes balance the visit mix and descend into existing outcomes.

**Why `chance_counts`, not `child.visits`.** Round-robin reads a per-node counter `chance_counts[outcome]`, not `child.visits`. Under the transposition DAG a post-reveal child can have other parents, so `child.visits` is inflated by sims that never came through this chance node — using it would skew the routing away from uniform. The per-node counter records only this node's own routing, so the outcome mix stays exactly uniform regardless of sharing (≤3 ints per chance node). Because the mix is uniform, the chance node's plain `value_sum / visits` converges to the uniform reveal expectation `Σ (1/k) V(child)` — no weighted estimator needed.

**Backprop and frame.** A chance node is on the path and receives `visits` / `value_sum` like any node; with `decider = 0` it accumulates P0-frame leaf values, and its parent reads it through the unchanged sign-flip (§5.3). No special-casing in the backprop loop.

**Re-root across a real reveal.** After the real game reveals the true card (resolved by the dealer, not the agent), the agent's next call is at the post-reveal decision state. `find_or_create_node` returns that state's node (created during search if a sim routed through that outcome; fresh otherwise) and `re_root` (§5.5) prunes the transposition table to its live subtree — the chance node becomes an ancestor of the new root and is dropped along with the counterfactual outcome subtrees, by the existing reachability walk. **No new code.** Tree-reuse benefit across the boundary exists only if search reached past it; shared-tree self-play is unaffected (the chance node is just another shared node). `MCTSAgent.__call__` is only ever invoked at decision states — the driver routes reveals to the dealer — which a defensive `decider_of(state) is not None` assert documents.

---

## 6. Integration with engine

### 6.1 Agent protocol compliance

`MCTSAgent.__call__(state) -> Action` satisfies the `Agent` protocol in `agricola/agents/base.py`. No engine changes needed.

### 6.2 `decider_of(state)` usage

Used in three places:

1. At node creation, to record `node.decider`.
2. In UCB calculation, to determine sign-flip when comparing parent and child.
3. In chain-ended check during macro-fencing generation, to detect handoff.

The engine's pending stack handles the alternating-decider pattern automatically. No special-casing needed for non-atomic chains or harvest sub-phases.

### 6.3 `strict_restricted_legal_actions(state)` usage

All legality queries inside MCTS go through this function (not the unrestricted `legal_actions`). Includes:

1. `MCTSNode._compute_legal_actions` for tree expansion.
2. Macro-fencing's random-rollout legal action sampling.
3. (Heuristic's internal legality, when called as the macro-fencing greedy policy or as the leaf evaluator's setup — already handled by the heuristic's own `legal_actions_fn` parameter.)

### 6.4 Self-play with shared tree

```python
# Self-play, both seats share one MCTSAgent
agent = MCTSAgent(search=MCTSSearch(), sims_per_move=500)
state = setup(seed=0)
final, trace = play_game(state, agents=(agent, agent))
```

Because both `agents[0]` and `agents[1]` point at the same `MCTSAgent`, the agent's `self.search` accumulates state across both seats' calls. The agent's `_pending_macro_actions` is also shared — only one seat can be mid-macro at a time, which is fine since seats alternate.

### 6.5 MCTS vs other agent (separate trees)

```python
mcts_agent = MCTSAgent(search=MCTSSearch(evaluator_config=v3_best_cfg), sims_per_move=500)
heuristic_agent = HubrisHeuristicV3(config=v3_best_cfg, seed=1, lookahead="turn")
state = setup(seed=0)
final, trace = play_game(state, agents=(mcts_agent, heuristic_agent))
```

`mcts_agent` maintains its own tree. Re-roots on its own calls. Doesn't see the heuristic's internal state.

### 6.6 Two MCTSAgents with separate trees

```python
# Comparing two MCTS configurations
mcts_a = MCTSAgent(search=MCTSSearch(), c_uct=1.0)
mcts_b = MCTSAgent(search=MCTSSearch(), c_uct=2.0)
final, trace = play_game(state, agents=(mcts_a, mcts_b))
```

Each agent has its own `MCTSSearch`. No tree sharing. Each agent independently re-roots on its own calls.

---

## 7. Strict-restrictions specification

These restrictions are added on top of the existing `restricted_legal_actions` (which already applies plow-before-sow, rooms-before-stables, room cap, etc. — see CLAUDE.md status row "`restricted_legal_actions` wrapper"). The strict version applies additional filters.

**Fallback rule** (applies to all filters): if applying a filter would result in an empty action set, the filter is skipped for that decision (lift restriction, fall back to less-restricted set). Implementation: `if narrowed: actions = narrowed`.

### 7.0 `restricted_legal_actions` addition: drop `use=False` craft conversions

This filter lives in `restricted_legal_actions` (regular, not strict) — it's a correctness-preserving simplification that benefits all agents, not just MCTS.

**Applies at**: any state where `CommitHarvestConversion` actions appear in the raw legal set (in practice, only at `PendingHarvestFeed`).

**Rule**: drop any `CommitHarvestConversion` action where `use == False`.

```python
def _filter_drop_use_false(state, actions):
    return [a for a in actions
            if not (isinstance(a, CommitHarvestConversion) and a.use is False)]
```

**Rationale**: explicitly declining a craft is redundant. The player can achieve the same outcome by skipping the craft and going directly to `CommitConvert` (which terminates `PendingHarvestFeed` without using the undecided crafts). Removing the redundant action saves MCTS from spending visits on a no-op decision.

**Verified safety**:
- `CommitConvert` is always legal at `PendingHarvestFeed` regardless of which crafts are undecided, so the player can always finish the harvest.
- `harvest_conversions_used` is reset in `_resolve_harvest_field` each harvest, so not adding the craft to it (by going straight to `CommitConvert`) has no cross-harvest effect.

### 7.1 Cultivation sow-max

**Applies at**: `PendingSow` whose `initiated_by_id == "cultivation"` (i.e., the PendingSow was pushed by Cultivation, not by Grain Utilization).

**Rule**: keep only the `CommitSow(grain, veg)` action that maximizes `grain + veg`. On ties for max total, prefer the option with more `grain` (grain priority).

**Rationale**: when cultivating, sowing fewer fields than maximum is almost always suboptimal — you're wasting one of the cultivation action's two atomic effects.

### 7.2 Grain-Utilization veggie rule

**Applies at**: `PendingSow` whose `initiated_by_id == "grain_utilization"`.

**Rule**: for each candidate `CommitSow(grain_sown, veg_sown)`, require that `veg_sown == min(veggies_in_supply, empty_plowed_fields − grain_sown)`. The player gets to choose how much grain to sow; veggie sown amount is auto-determined as the maximum possible given the grain choice.

Equivalently: never leave a plowed field empty if you have a veggie that could go there. Exception: sowing grain on a field counts as "filling" it (grain has priority over veg in that sense — you can choose to sow grain instead of leaving room for veg).

**Rationale**: leaving an empty plowed field while holding veggies wastes a sowing opportunity. The veggie can't be eaten directly and doesn't accumulate; planting it now extracts more value than holding.

### 7.3 Fencing patterns (9 rules)

**Applies at**: `PendingBuildFences`. The player's wood count and current pasture configuration determine the applicable rule (if any).

**Wood counts are EXACT** — not lower bounds. A rule for "wood = 10" applies only when wood is exactly 10. Multiple rules can be relevant in principle but the specific (wood, pasture-state) preconditions are mostly disjoint.

Each rule lists allowed actions. `Stop()` is "allowed" only if it would be legal already (the engine permits Stop iff `num_built >= 1` for the current Fencing action — see CLAUDE.md "Multi-shot sub-action pendings").

| # | Precondition | Allowed actions |
|---|---|---|
| 1 | No pastures + wood ∈ {7, 8, 9} | `CommitBuildPasture(cells={(0, 4)})` |
| 2 | No pastures + wood = 10 | `CommitBuildPasture(cells={(0,3),(0,4),(1,3),(1,4)})` OR `CommitBuildPasture(cells={(0,3),(0,4),(1,3),(1,4),(2,3),(2,4)})` |
| 3 | No pastures + wood = 13 | `CommitBuildPasture(cells={(0,3),(0,4),(1,3),(1,4),(2,3),(2,4)})` |
| 4 | No pastures + wood = 15 | `CommitBuildPasture(cells={(0,3),(0,4),(1,2),(1,3),(1,4),(2,2),(2,3),(2,4)})` OR `CommitBuildPasture(cells={(0,3),(0,4),(1,3),(1,4),(2,3),(2,4)})` |
| 5 | Existing pastures = {1x1 on (0,4)} + wood = 3 | `CommitBuildPasture(cells={(0,3)})` OR `Stop` |
| 6 | Existing pastures = {1x1 on (0,4)} + wood = 5 | `CommitBuildPasture(cells={(1,4),(2,4)})` OR `Stop` |
| 7 | Existing pastures = {2x2 at top-right ((0,3),(0,4),(1,3),(1,4))} + wood = 2 | `CommitBuildPasture(cells={(0,3),(0,4)})` (subdivision creating 1x2 inside the 2x2) |
| 8 | Existing pastures cover exactly {(0,3), (0,4)} (regardless of how split) + wood = 4 | `CommitBuildPasture(cells={(1,3),(1,4)})` OR `Stop` |
| 9 | Existing pastures cover exactly {(0,3), (0,4)} (regardless of how split) + wood = 6 | `CommitBuildPasture(cells={(1,3),(1,4),(2,3),(2,4)})` OR `Stop` |

**Wood-arithmetic verification** (cross-check):

- Rule 1: 1x1 at (0,4) perimeter = 4 fences. 7-4=3, 8-4=4, 9-4=5 remaining.
- Rule 2: 2x2 at top-right perimeter = 8; 3x2 at top-right perimeter = 10. Both consistent with 10 wood available.
- Rule 3: 3x2 uses exactly 10 wood; 3 remaining.
- Rule 4: 8-cell L (cells listed) perimeter = 12; 3x2 perimeter = 10. Consistent with 15 wood.
- Rule 5: 1x1 at (0,3) adjacent to existing (0,4); shares 1 edge → 3 new = 3 wood.
- Rule 6: 2x1 at ((1,4),(2,4)) adjacent to existing (0,4); shares 1 edge → 5 new = 5 wood.
- Rule 7: 1x2 subdivision inside 2x2 → 2 internal fence edges = 2 wood.
- Rule 8: 2x1 at ((1,3),(1,4)) adjacent to existing top row → shares 2 edges → 4 new = 4 wood.
- Rule 9: 2x2 at bottom-right adjacent to existing top row → shares 2 edges → 6 new = 6 wood.

**Edge cases:**

- **Multiple rules matching.** Could happen if the wood-count preconditions overlap (e.g., a hypothetical "no pastures + wood = 10" and "no pastures + wood ∈ {7-9, 10}" — but the current rules don't overlap). If a state happens to match multiple rules, the filter's allowed-action set is the union of all matching rules' allowed actions.

- **Pasture identity vs cell-set semantics.** Rule 7 vs rules 8/9 differ in which sense of "has X pasture(s)" they use:

  - **Rule 7** ("Has 2x2 at top-right + wood = 2 → build 1x2 subdivision") implicitly requires the 2x2 to be a SINGLE pasture occupying those 4 cells (since the action it allows is a subdivision of that pasture). Check: `any(past.cells == frozenset({(0,3),(0,4),(1,3),(1,4)}) for past in p.farmyard.pastures)`. If the four cells are split across multiple pastures, the rule does NOT apply.
  
  - **Rules 8 and 9** ("Existing pastures cover exactly {(0,3),(0,4)} + wood = 4 or 6") are cell-set agnostic — they apply whether those cells form one 1x2 pasture or two separate 1x1 pastures. Check: `union(past.cells for past in p.farmyard.pastures) == frozenset({(0,3), (0,4)})`.
  
  These two semantics are deliberate and reflect the strategic intent of each rule.

- **"No pastures" condition** means `len(p.farmyard.pastures) == 0`. Used by rules 1-4.

- **Stop legality.** When a rule's allowed actions include `Stop`, Stop is filterable only if it would already be legal at this PendingBuildFences. Per CLAUDE.md "Multi-shot sub-action pendings," Stop is legal iff `num_built >= 1` for the current Fencing action. If `num_built == 0`, Stop isn't a valid candidate even if a rule lists it as allowed — the filter just drops Stop from the allowed set, keeping the build action.

### 7.4 Harvest-feed cap

**Applies at**: `PendingHarvestFeed`.

**Goal**: limit MCTS branching at the harvest-feed decision while preserving (a) all craft-conversion options and (b) a representative sample of feeding configurations ranked by heuristic preference plus a couple of random samples for exploration.

**Rule**:

1. Partition legal actions into three sets:
   - `crafts`: all `CommitHarvestConversion` actions (always all `use=True` after §7.0)
   - `commits`: all `CommitConvert` actions
   - `other`: anything else (shouldn't appear at PendingHarvestFeed in normal flow, but defensive)

2. If `len(commits) <= 7`: no cap needed. Return `crafts + other + commits` unchanged.

3. Otherwise: rank `commits` by `evaluate_hubris_v3(step(state, a), decider, config)` descending. Keep:
   - The top 5 by V3 score
   - Plus 2 random samples drawn uniformly without replacement from the remaining (i.e., from `commits[5:]`)
   - RNG source: `search.rng` (deterministic given the search seed)

4. Return `crafts + other + top_5 + random_2`.

**Pseudocode:**

```python
def _filter_strict_harvest_feed_cap(state, actions, search):
    if not state.pending_stack:
        return actions
    if not isinstance(state.pending_stack[-1], PendingHarvestFeed):
        return actions
    
    crafts, commits, other = [], [], []
    for a in actions:
        if isinstance(a, CommitHarvestConversion):
            crafts.append(a)
        elif isinstance(a, CommitConvert):
            commits.append(a)
        else:
            other.append(a)
    
    if len(commits) <= 7:
        return crafts + other + commits  # no cap; return everything
    
    decider = decider_of(state)
    cfg = search.evaluator_config
    
    def score(a):
        return evaluate_hubris_v3(step(state, a), decider, cfg)
    
    commits_ranked = sorted(commits, key=score, reverse=True)
    top_5 = commits_ranked[:5]
    rest = commits_ranked[5:]
    
    n_random = min(2, len(rest))
    if n_random > 0:
        idxs = search.rng.choice(len(rest), size=n_random, replace=False)
        random_2 = [rest[i] for i in idxs]
    else:
        random_2 = []
    
    return crafts + other + top_5 + random_2
```

**Branching factor (worst case):**

| Crafts | Commits in legal | Total after cap |
|---|---|---|
| 0 | ≤7 | ≤7 |
| 0 | 19 (worst case from V3_TRAINING_PIPELINE measurement) | 7 (5 top + 2 random) |
| 1 | ≤7 | ≤8 |
| 1 | 19 | 8 |
| 2 | 19 | 9 |
| 3 (max in Family game) | 19 | 10 |

So worst-case branching at PendingHarvestFeed is **10**. With FPU instead of +∞ for unvisited children, MCTS handles this comfortably without forced first-visit sweep cost.

**Rationale**:

- Crafts are always kept because (a) the user designated them as strategically important to evaluate, (b) there are few of them (typically 0-3), so keeping them adds minimal branching cost. Sub-sampling crafts could miss a strategically important one if its post-use state happens to rank below V3's top 5 CommitConverts.
- Top 5 commits captures the heuristic's preference (V3's evaluator already encodes most of the "don't eat last crop / don't break breeding" heuristics via its grain/veg value curves and breeding-pair values).
- 2 random samples preserve some exploration of non-V3-preferred CommitConverts. Without these, MCTS would never discover cases where V3 misranks.

**V3 ranking cost**: ~1.1ms per PendingHarvestFeed node (~19 commits × (10us step + 50us eval) = ~19 × 60us). Paid once per node via `_legal_actions` cache. Per game: 6 harvests × 2 players = 12 nodes × ~1-2ms = ~12-24ms total. Negligible.

**Determinism**: `search.rng` is seeded at construction. Same seed → same random samples across runs. Reproducible matches.

**Reaches transposition table cleanly**: when MCTS visits a post-craft-use state (PendingHarvestFeed with one fewer craft), this is a NEW state hashed in transpositions. Its filtered legal actions are computed fresh (with one fewer craft and possibly different CommitConvert variants due to changed resources). DAG dedup works: two paths reaching the same post-craft-use state share the node.

**Why we don't sub-sample crafts**: there are at most 3 crafts in the Family game (joinery, pottery, basketmaker), bounded by card additions in future. The 3 crafts contribute at most 3 extra branches — well within FPU's tolerance. Sub-sampling crafts saves nothing meaningful and risks dropping a strategically important option.

**Interactions with other handling**:

- **Macro-fencing**: doesn't interact. Different pending type.
- **CommitHarvestConversion's effect**: when MCTS picks a craft-use action and descends to the post-use state, that state is also a PendingHarvestFeed (with reduced crafts and possibly changed CommitConvert variants). The cap re-applies recursively.
- **Re-rooting**: the cap is recomputed lazily on each node's first `_compute_legal_actions` call. Re-rooting doesn't affect previously-cached caps; new nodes get fresh caps.
- **Phase 4 tuning**: K=5 top + 2 random are starting points. If MCTS makes obviously-bad harvest decisions in validation, can adjust K or replace with rule-based priority filter (Pattern Z from earlier discussion).

---

## 7.5. Implementation notes / spec deviations (post-landing)

Phases 1-3 of §8 landed in a single session. This section documents three points where the implementation diverges from the spec text above; each is a faithful realization of the spec's *intent* with a small correction to a detail the spec got wrong or under-specified.

### 7.5.1 Engine action name: `"build_fences"` (not `"fences"`)

§3.6 and §5.4 refer to trigger 2 as `ChooseSubAction("fences")` at `PendingFarmRedevelopment`. The engine actually emits `ChooseSubAction(name="build_fences")` (see `_choose_subaction_farm_redevelopment` in `agricola/resolution.py:618`). The implementation in `agricola/agents/mcts.py:_find_fencing_triggers` follows the engine, not the spec text.

### 7.5.2 `PendingFencing` wrapper between trigger 1 and `PendingBuildFences`

The spec's pseudocode in §5.4 (`_chain_ended_for_fencing`) reads:

```python
if not state.pending_stack:
    return True
return not isinstance(state.pending_stack[-1], PendingBuildFences)
```

This assumes that after `PlaceWorker("fencing")` the top of the pending stack is `PendingBuildFences`. The engine actually pushes `PendingFencing` (the *wrapper* pending hosting the `before_fencing` trigger event) first; `PendingBuildFences` is pushed only after the agent plays the singleton `ChooseSubAction("build_fences")` at `PendingFencing`. A literal "PBF on top" predicate applied immediately after the trigger would terminate the chain instantly, producing 1-action macros.

**Resolution:** preserve `_pbf_on_top(state)` as the chain-body termination predicate (matching the spec's intent) by splitting macro generation into three explicit phases in `_generate_fencing_macros`:

1. **Entry** (`_enter_pbf`): auto-step through any singleton decisions of the decider until `PendingBuildFences` is on top. For trigger 1, this plays the singleton `ChooseSubAction("build_fences")` at `PendingFencing` and lands us at PBF on top. For trigger 2, the trigger landed us at PBF directly (`direct_pbf=True`) and the entry phase is skipped.
2. **Chain body** (`_run_pbf_body`): the literal loop the spec describes — `while _pbf_on_top(state): pick action, apply`.
3. **Exit / wrapper drain** (`_drain_wrapper`): for trigger 1 only, auto-step through any remaining singleton decisions of the decider so the outer `Stop(PendingFencing)` is recorded as part of the macro. For trigger 2 we don't drain — after PBF pops we're back at `PendingFarmRedev`, where the agent's next non-fencing decision (renovate-vs-stop, etc.) belongs to normal MCTS.

The "PBF on top" predicate is exactly what runs in the body loop; wrapper handling moved to the explicit entry/exit phases.

### 7.5.3 Per-search RNG threading via `make_strict_restricted_legal_actions(...)`

§4.2 shows `MCTSSearch.__init__` defaulting `legal_actions_fn` to the module-level `strict_restricted_legal_actions` callable. That callable uses a single module-level RNG for its harvest-feed cap's random samples — meaning two `MCTSSearch` instances would share RNG state, breaking per-instance determinism.

**Resolution:** when no `legal_actions_fn` is passed, `MCTSSearch` constructs its own strict wrapper via `make_strict_restricted_legal_actions(config=self.evaluator_config, rng=self.rng)`. Each search instance gets its own seeded RNG threaded through the harvest-feed cap. The module-level `strict_restricted_legal_actions` callable still exists and works (uses a seed-0 default RNG) — it's just not the default for MCTS.

---

## 8. Implementation phases

The full MVP fits in ~1-2 focused sessions. Each phase below is sized at hours, not days. **Phases 1-3 are complete** (status notes inline below); Phase 4 is ongoing as of this writing.

### Phase 1 ✅: `strict_restricted_legal_actions` + `restricted_legal_actions` use=False filter

**Files modified:**
- `agricola/agents/restricted.py` — added the `use=False` filter to `restricted_legal_actions`; added `strict_restricted_legal_actions` with four filter functions (Cultivation sow-max, Grain-Util veggie, Fencing patterns, Harvest-feed cap) + `make_strict_restricted_legal_actions(*, config, rng)` factory + fencing rule helpers
- `tests/test_restricted_actions.py` — added 28 new tests (23 regular + 28 strict → 51 total). Tests cover each filter in isolation plus cross-cutting invariants (subset of unrestricted, always-≥1, randomized full-game walk).

**Code volume actual:** ~280 LOC added to restricted.py, 28 tests added.

**Acceptance:** ✅ all 51 tests pass; ✅ each strict filter fires when expected, doesn't fire when not, falls back when empty; ✅ verified end-to-end on prefab states across the 9 fencing rules.

### Phase 2 ✅: MCTS scaffolding

**Files added:**
- `agricola/agents/mcts.py` — `MCTSNode`, `MCTSSearch`, `MCTSAgent`, `MacroFencingAction` classes
- `tests/test_mcts.py` — 24 tests

**Code volume actual:** ~450 LOC in mcts.py, 24 tests.

**Acceptance:** ✅ `MCTSAgent` implements Agent protocol; ✅ 1-game vs `RandomAgent` completes; ✅ 1-game vs `HubrisHeuristicV3` completes; ✅ `root.visits == sims_per_move`; ✅ FPU visits every root child within budget (`test_fpu_visits_all_root_children_when_budget_permits`); ✅ shared-tree self-play completes.

### Phase 3 ✅: Game integration and validation infrastructure

**Files added/modified:**
- `scripts/play_mcts_match.py` — MCTS-vs-opponent driver with `--jobs N` parallel runner and per-game streaming progress (running win tally + ETA)
- `agricola/agents/__init__.py` — added exports: `MCTSAgent`, `MCTSSearch`, `MCTSNode`, `MacroFencingAction`, `strict_restricted_legal_actions`, `make_strict_restricted_legal_actions`

**Acceptance:** ✅ 16-game match @ 500 sims completed in 9.7 min wall (8 cores); ✅ MCTS does not crash on any seed; ✅ shared-tree self-play works; ✅ separate-tree match works.

### Phase 4 (in progress): Validation and tuning

This is the empirical phase — runs and analysis rather than coding.

**Results so far:**
- **16 games @ 500 sims, jobs=8** (`v3_best.json` opponent): MCTS 11-0-5, avg margin **+2.12** (target was "+3"; within the n=16 CI). Wall 9.7 min.
- (Larger validation runs ongoing.)

**Remaining activities:**
- **Validation 1:** ≥50-game match MCTS-vs-V3-greedy to tighten the CI on the +2.12 estimate. If margin ≤0 or negative, debug (FPU formulation? sim count? evaluator bias dominating?).
- **Validation 2:** Scaling check — sims_per_move at 200/500/1000. Does play strength scale with sims?
- **Validation 3:** Shared-tree self-play vs separate-tree comparison. Does sharing improve play strength per unit compute?
- **Tuning:** `c_uct` ∈ {1.0, 1.4, 2.0}, optionally `n_random_fencing` ∈ {2, 4, 8}.
- **Profile** the actual per-sim cost — verify §5.0 estimates (observed ~36s/game at 500 sims on 8 cores ≈ ~70-100 ms/move per core, within the design's 50-100 ms/move range).
- **Optional:** implement DAG full-backprop, parallelism (intra-game), or PUCT prior IF validation reveals specific need.

---

## 9. File map

| Path | Status | Purpose |
|---|---|---|
| `agricola/agents/mcts.py` | new | MCTSAgent, MCTSSearch, MCTSNode classes |
| `agricola/agents/restricted.py` | existing, add to | `strict_restricted_legal_actions` and four strict filter functions (cultivation sow-max, grain-util veggie, fencing patterns, harvest-feed cap) plus the use=False filter in `restricted_legal_actions` |
| `agricola/agents/heuristic.py` | existing, no changes needed | `evaluate_hubris_v3`, `_terminal_margin_value` (already in place) |
| `agricola/agents/base.py` | existing, no changes needed | `Agent` protocol, `decider_of`, `play_game` |
| `agricola/agents/__init__.py` | add exports | Re-export MCTSAgent etc. |
| `tests/test_restricted_actions.py` | existing, add to | Tests for strict filters |
| `tests/test_mcts.py` | new | Tests for MCTS components and end-to-end |
| `scripts/play_mcts_match.py` | new | Match driver |
| `MCTS_DESIGN.md` | new (this file) | Design spec |

---

## 10. Open questions / future work

### 10.1 Sims budget vs leaf-eval quality

Default `sims_per_move = 500` is a guess. Profile and tune. If MCTS-with-leaf-eval is too noisy (bias from V3 evaluator dominates), could switch to short rollouts (e.g., 5-10 move rollouts before evaluating) as a fallback. The MVP doesn't use rollouts at all — pure leaf evaluation.

### 10.2 Macro-fencing path count

Default `n_random_fencing = 4` is a guess. The dedup loop already terminates early when paths converge (capped at `max_attempts = 3 × n_random_fencing` total tries), so over-shooting wastes some compute but doesn't break correctness. If we observe most attempts converging on the greedy endpoint (most randoms hit the same state), we could lower `n_random_fencing` to 2-3 to skip the wasted attempts. If too few unique paths emerge after dedup, that's the natural ceiling — accept it.

### 10.3 FPU offset tuning

Default `fpu_offset = 0.0` (unvisited children's default Q = parent's mean). Could try small negatives (-0.1, -0.2) to make unvisited children slightly less attractive, which would shift balance toward exploitation. Tune empirically.

### 10.4 PUCT with priors (future iteration)

Once vanilla UCT MCTS is working, the natural next step is PUCT with a heuristic-derived prior. The prior would be softmax over evaluator scores (with possible ε-mix for exploration). This addresses the chain-initiating-action prior problem identified during design (`evaluate_hubris_v3(post-PlaceWorker(fencing))` underestimates fencing because V3 doesn't see post-chain state). The fix discussed: use heuristic POLICY scores (greedy descent through chain) as the prior, not raw evaluator scores. Defer until vanilla UCT is validated.

### 10.5 Macro-action commitment semantics

Currently the agent commits to its chosen macro-fencing path and plays it deterministically. An alternative: at each sub-action decision within the chain, re-run MCTS (with the in-tree chain) to potentially refine the macro choice. More expressive but loses macro-fencing's structural simplicity. Defer; consider if specific game outcomes show the agent locked into a bad macro mid-chain.

### 10.6 Transposition pruning policy

Current design: prune transposition table on each re-root. Acceptable for correctness; possibly wasteful. Alternative: lazy pruning when table exceeds N entries. Not a concern for MVP at 500 sims/move (table won't grow large).

### 10.7 Parallelism

Single-threaded MVP. AlphaZero-style root-parallel or virtual-loss-leaf-parallel adds complexity. Defer until profiling shows MCTS is the bottleneck and a 4-8x speedup would matter.

### 10.8 PendingHarvestFeed cap tuning

Addressed by §7.4 (harvest-feed cap: keep all crafts, cap CommitConvert at top-5-by-V3 + 2 random). Worst-case branching at PendingHarvestFeed is ~10. Open for Phase 4 tuning:

- The 5 + 2 split is a guess. Could try 7 + 0 (pure heuristic ranking) or 3 + 4 (more exploration). Tune empirically.
- If MCTS makes systematically bad harvest decisions, escalate to rule-based priority filter (Pattern Z from design discussion: don't eat last crop, don't break breeding, etc.).

### 10.9 Leaf-value scale mismatch (terminal vs mid-game)

`evaluate_leaf` returns the raw score margin at terminal states (range typically ~[-30, +30]) and the heuristic margin at mid-game states (`evaluate_hubris_v3(state, 0) - evaluate_hubris_v3(state, 1)`, range depends on V3 tuning — roughly comparable to score margin but not exactly). The two are on slightly different scales.

This affects MCTS only when comparing Q values across nodes whose leaves came from different evaluators (mostly nodes near round 14 where terminal states appear). Mid-tree comparisons are all between mid-game leaves (same scale) so are unaffected.

If empirical validation shows this matters (Phase 4), options:
- Calibrate the heuristic to match score margin scale (a separate heuristic-tuning task)
- Normalize Q values at leaves to a common scale
- Use mid-game heuristic only (don't special-case terminal)

For MVP, accept the mismatch. The principled choice is to use the actual game outcome at terminal states (raw score margin) rather than the heuristic's prediction.

### 10.10 Learned value function

The natural endpoint: replace `evaluate_hubris_v3` with a trained neural value network. AlphaZero uses self-play games as training data. This is project phase 5 per CLAUDE.md — defer until MCTS infrastructure works end-to-end.

---

## 11. Logging and debugging metrics

The MCTSSearch should expose a `stats` dict (populated per-call or per-game) for diagnostics during tuning. Useful metrics:

| Metric | Purpose |
|---|---|
| `tree_size` (nodes in transposition table) | Memory / growth tracking |
| `transposition_hit_rate` (fraction of expansions that reused an existing node) | DAG effectiveness — high rate means lots of recombination |
| `avg_depth_reached` per call | Did MCTS go deep, or stay near root? |
| `max_depth_reached` per call | Worst case |
| `avg_unvisited_at_call_end` per call | If high, MCTS is exploring too widely |
| `macro_fencing_duplicate_rate` | Fraction of macro generations producing <5 distinct paths |
| `time_per_phase` (select / expand / eval / backprop) | Where compute goes |
| `macro_chain_length_p50_p95` | How big are the macro chains? |
| `fpu_fired_fraction` | How often does FPU determine selection vs visited UCB? |
| `restriction_fallback_count` | How often do strict-restriction filters fall back to less-restricted? |

A `MCTSAgent.last_stats: dict` populated after each `__call__` lets the driver dump stats per-move. Aggregate across games for trend analysis.

These aren't required for correctness; they're vital for tuning. Implementation in Phase 4 or whenever profiling becomes the question.

## 12. Edge cases

Things the implementation must handle gracefully:

1. **Game ends during macro-fencing generation.** A random rollout might trigger `Phase.BEFORE_SCORING` (e.g., the player has 0 workers after this fencing chain and the opponent also has 0). The `chain_ended` check handles this: terminal phase counts as chain-end. The macro's endpoint is then a terminal state, evaluated via `_terminal_margin_value` at leaf-eval time.

2. **`strict_restricted_legal_actions` returns empty.** Should never happen by design — every filter has a fallback to less-restricted. But defensive `assert actions` in MCTSNode._compute_legal_actions catches implementation bugs early.

3. **Re-rooting finds no matching child.** If the engine state at the agent's next call doesn't match any child of the current root (e.g., something unexpected happened, or there's a bug, or the agent's tree hasn't been initialized yet), fall back gracefully: discard the current tree and start fresh from the new state. Implementation: `find_or_create_node(state)` always works regardless of prior tree state.

4. **Pending macro queue + control transfer.** In shared-tree self-play, P0 might commit to a macro mid-call. The agent plays it out across multiple calls. When P0's chain completes (Stop), control hands to P1. The agent's `_pending_macro_actions` should be empty at this point. If P1 then picks a macro at their move, the queue refills. Sanity check: when the agent is called and `_pending_macro_actions` is non-empty, the action it returns should be legal at the current state — if not, that's a bug (macro replay went off the rails).

5. **Macro action replay mismatch.** If the engine's state at a mid-macro call doesn't match what the macro expected (e.g., a previously-recorded action is no longer legal for some reason — shouldn't happen but defensively), the macro replay should detect this and fall back to running MCTS normally.

6. **Empty action set at re-rooted state.** If `legal_actions(new_root.state) == []` (terminal), the agent shouldn't be called at this state in the first place (the engine ends the game). Defensive: return early with a clear error.

7. **Sim budget exhausted with no children expanded.** Edge case: if the root has many children and the sim count is very small, MCTS might not even expand all root children. The action-selection step picks among the expanded children (using softmax over visits). If only one is expanded, it wins by default. This is intended behavior but worth verifying via stats.

8. **Transposition table memory growth.** Over a long game, the transposition table grows. Re-rooting prunes it, but only the live subtree. If the live subtree is very large (e.g., late-game with many branches), memory could climb. Phase 4 should profile and add lazy pruning if needed.

---

## 13. Quick reference

### Running MCTS vs heuristic (separate trees)

```python
from agricola.agents.mcts import MCTSAgent, MCTSSearch
from agricola.agents.heuristic import HubrisHeuristicV3, HeuristicConfigV3
from agricola.agents.restricted import strict_restricted_legal_actions
from agricola.setup import setup
from agricola.agents.base import play_game
import json

with open("tuned_configs/v3_best.json") as f:
    cfg = HeuristicConfigV3(**json.load(f)["best_config"])

mcts = MCTSAgent(
    search=MCTSSearch(legal_actions_fn=strict_restricted_legal_actions,
                      evaluator_config=cfg, rng_seed=0),
    sims_per_move=500,
)
heur = HubrisHeuristicV3(config=cfg, seed=1, lookahead="turn",
                          legal_actions_fn=strict_restricted_legal_actions)
final, _ = play_game(setup(seed=42), agents=(mcts, heur))
```

### Running MCTS vs MCTS with shared tree

```python
# Pass the SAME MCTSAgent to both seats. Both calls share `self.search`.
agent = MCTSAgent(search=MCTSSearch(evaluator_config=cfg), sims_per_move=500)
final, _ = play_game(setup(seed=42), agents=(agent, agent))
```

### Running MCTS vs MCTS with shared tree but different agent config

```python
# Same search (shared tree), different agent-level configs.
shared_search = MCTSSearch(evaluator_config=cfg)
agent_a = MCTSAgent(search=shared_search, sims_per_move=500, c_uct=1.0)
agent_b = MCTSAgent(search=shared_search, sims_per_move=500, c_uct=2.0)
final, _ = play_game(setup(seed=42), agents=(agent_a, agent_b))
```

### Running MCTS vs MCTS with separate trees

```python
# Each agent owns its own MCTSSearch — independent trees.
agent_a = MCTSAgent(search=MCTSSearch(evaluator_config=cfg), c_uct=1.0)
agent_b = MCTSAgent(search=MCTSSearch(evaluator_config=cfg), c_uct=2.0)
final, _ = play_game(setup(seed=42), agents=(agent_a, agent_b))
```

### Running with toggleable strict restrictions

```python
from agricola.agents.restricted import restricted_legal_actions, strict_restricted_legal_actions

# With strict restrictions (default for MCTSSearch)
search_strict = MCTSSearch(legal_actions_fn=strict_restricted_legal_actions, ...)

# With normal restrictions (for comparison)
search_normal = MCTSSearch(legal_actions_fn=restricted_legal_actions, ...)

agent = MCTSAgent(search=search_strict, sims_per_move=500)
```
