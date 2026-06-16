# MCTS_IMPLEMENTATION.md

The single, comprehensive reference for AgricolaBot's **Monte Carlo Tree Search (MCTS) agent**.
Everything the search does lives in one module — **`agricola/agents/mcts.py`** — and this document
explains all of it: the algorithm in the abstract, then the concrete classes, functions, and code
that implement it, including UCT, PUCT, chance nodes (the hidden round-card reveal), and the Fencing
macro machinery.

It is written to stand alone. You should not need to read `design_docs/MCTS_DESIGN.md` or `design_docs/POLICY_PUCT_DESIGN.md`
to understand the code — those are the *historical* design records (written before the code
crystallized, and to plan specific pieces), kept for provenance and rationale, but **this** is the
file to read to understand what the search actually does today. Where the implementation diverged from
those specs, this doc follows the code and flags the divergence (§13).

**Two deliberate black boxes.** MCTS consumes a **value evaluator** (the leaf value) and, optionally,
a **policy** (the PUCT prior) through narrow function interfaces. Their internals — whether they are
the V3 heuristic or a neural network — are out of scope here; this doc specifies only the *contracts*
(§6, §5.3). For those internals see `design_docs/V3_DESIGN.md` (heuristic), `design_docs/FIRST_NN.md` (value net), and
`design_docs/POLICY_HEAD.md` (policy net).

Contents:
1. Overview of the algorithm — including the UCT vs PUCT subsection (§1.4)
2. The three objects: `MCTSNode`, `MCTSSearch`, `MCTSAgent`
3. The DAG: transposition table, edges, decider assignment, re-rooting
4. One simulation, step by step (`_simulate`) + the cost cheat-sheet
5. Selection in detail — UCT, PUCT, and the policy black box
6. Leaf evaluation (`evaluate_leaf`) — the value black box
7. Legality and action pruning
8. Chance nodes (the hidden round-card reveal)
9. Fencing (the macro machinery, FLATTEN, SEQUENCE_PRIOR)
10. The played move (`_select_action_with_temperature`)
11. Tree reuse, the three sharing modes, and running it
12. Configuration reference
13. Invariants, edge cases, and design-vs-code notes
14. Speedups — how the performance work fits the search (NN leaf, hashing, encoder)

It assumes familiarity with the engine's two-function API (`legal_actions(state)`, `step(state,
action)`), the frozen-`GameState` model, the pending-decision stack, and the **decider rule** — all in
`CLAUDE.md → Phase 1` and `ENGINE_IMPLEMENTATION.md`. The single most load-bearing engine concept here
is `decider_of(state)`, restated in §1.6.

---

## 1. Overview of the algorithm

### 1.1 What a search produces

MCTS turns a fixed compute budget into one move. Given the current `GameState`, the agent runs
`sims_per_move` independent **simulations** (default 500), each of which descends a search tree, adds
one node, evaluates it, and folds the result back up the path it took. The simulations accumulate
**visit counts** and **value estimates** on the tree's nodes. After the budget is spent, the agent
plays a move drawn from the root's visit counts (§10). No simulation plays the game to its end — each
one bottoms out in a cheap *value estimate* of a single **leaf**: the node where that simulation stops
descending and is scored — a node is a "leaf" only until a later simulation expands past it (§1.3).

The whole agent is three objects (§2):

- **`MCTSNode`** — one game state's node in the tree (statistics + child edges).
- **`MCTSSearch`** — owns the tree (the transposition table) and all *search-level* configuration:
  the legality function, the leaf evaluator, the optional policy, fencing mode, RNG.
- **`MCTSAgent`** — the caller-facing `agent(state) -> Action` object; owns *agent-level* knobs
  (`sims_per_move`, `c_uct`, `fpu_offset`, the action-selection temperature) and the per-move loop.

### 1.2 The four phases of one simulation

Each simulation is the classic MCTS loop, implemented in `MCTSAgent._simulate` (§4):

1. **SELECT.** Starting at the root, choose a child by the selection rule (UCT or PUCT,
   §1.4) and descend, recording every node visited into a local `path` list. Chance nodes are
   *routed through* (§1.7), and forced (single-legal-action) nodes are *stepped through* (§4) — both
   transparently, within the same simulation. 
2. **EXPAND.** When selection picks an action whose child node does not yet exist, create it via
   `step(state, action)` and the transposition table. Usually one new node per simulation — but a
   forced chain stepped through, or a reveal routed through, can add several in one simulation (§4).
3. **EVALUATE.** Compute the new leaf's value with the leaf evaluator — *not* a rollout to game end
   (§1.3), and exactly once per simulation. The value is always expressed in **player 0's reference
   frame**.
4. **BACKPROPAGATE.** Walk the recorded `path` and add the leaf value (sign-flipped per node, §1.6) into
   each node's `value_sum`, incrementing each node's `visits`.

The cost asymmetry that makes this scale: the expensive operations — `step`, legal-action enumeration,
`GameState` hashing, leaf evaluation — are paid **at most once per node** (at creation / first touch).
Re-visiting an existing node on a later simulation costs only dict lookups and arithmetic. See the cost
cheat-sheet in §4.

### 1.3 Leaf evaluation instead of rollouts (the value black box)

Classical MCTS estimates a leaf by *rolling out* — playing random/greedy moves to game end and using
the terminal score. AgricolaBot does **not** do this. Instead, each newly expanded leaf is scored
directly by a **value evaluator**: a function `evaluator_fn(state, player_idx, config) -> float` that
returns a one-player quality estimate. The leaf's value is the expected **margin** between the two players
(P0 − P1), estimated by `MCTSSearch.evaluate_leaf` (§6).

Rollouts cost milliseconds (a 50-decision greedy playout); leaf evaluation costs tens of microseconds.
At 500 sims/move that is the difference between seconds and tens of milliseconds per move. The trade is
that values reflect the evaluator's snapshot judgment rather than realized outcomes — accepted, because
averaging many cheap evaluations over a tree is more useful than a few expensive playouts.

The evaluator is a **black box** to the search. The default is the differential V3 heuristic
(`evaluate_hubris_v3_differential`); a trained value network plugs into the exact same
`(state, player_idx, config) -> float` slot. Its internals are out of scope (§6 specifies only the
contract and the one scaling knob, `leaf_value_scale`).

### 1.4 Selection rules — UCT and PUCT

Selection is the heart of MCTS: at each node, which child do we descend into? AgricolaBot implements
**two** rules, chosen by whether a policy is supplied. `policy_fn is None` → **UCT**; `policy_fn` set →
**PUCT**. They are introduced here and implemented in §5.

**UCT (Upper Confidence bounds applied to Trees).** No action prior. The score of a child is its mean
value plus an exploration bonus that shrinks as the child is visited more:

```
UCB(child) = Q(child) + c_uct · √( ln(N_parent + 1) / N(child) )
```

`Q(child)` is the child's mean value (in the parent's frame, §1.6); `N` is a visit count; `c_uct`
(default `1.4 ≈ √2`) trades exploration against exploitation. The implementation expands every
unvisited child once (in random order) before it begins discriminating by UCB, and carries a
**First-Play-Urgency (FPU)** term for any residual unvisited child (§5.1).

**PUCT (Polynomial UCT, the AlphaZero variant).** Adds a learned prior `P(s,a)` so search concentrates
on actions the policy thinks are promising:

```
U(s,a) = Q(s,a) + c_puct · P(s,a) · √( Σ_b N(s,b) ) / ( 1 + N(s,a) )
```

The prior *orders* exploration: a high-prior action is tried early and often; a low-prior action may
**never** be visited at low simulation budgets — and that non-visiting *is* the point. It lets the
search operate over a wider, less hand-pruned legal set and **soft-prune** it via the prior instead of
hard rules (§5.2, §7). Unvisited children take an FPU-reduced placeholder value `Q(parent) − fpu_offset`;
the prior carries the exploration. `c_puct` reuses the `c_uct` field (the agent runs one mode at a time).

Both rules share the same machinery around them — the DAG, sign-flipping, forced-move step-through,
chance routing, backprop — and `policy_fn=None` is the toggle. The policy itself is a **black box**
(§5.3): MCTS sees it only as `policy_fn(state, legal_actions) -> {action: prior}`.

> A consequence worth stating up front: PUCT requires `FenceMode.FLATTEN` (plain per-pasture fence
> actions), because the UCT-only `FenceMode.MACRO` fencing uses MCTS-internal pseudo-actions a policy
> cannot attach priors to. The constructor enforces this (§9).

### 1.5 The search DAG and the transposition table

Two different action orderings often reach the *same* `GameState` (action-commutativity within and
across turns). Rather than duplicate them, the search keys nodes by state in a **transposition table**
(`MCTSSearch.transpositions: dict[GameState, MCTSNode]`), so each unique state has exactly one node and
its statistics aggregate over all paths that reach it. The tree is therefore a **DAG** (directed acyclic graph) — a node can have
multiple parents. `GameState` is already hashable, so this is a dict lookup — and that hash is **cached**
(it was the search's #1 self-time before; §14).

Backprop is nonetheless **path-only**: a simulation walks back up exactly the path it descended (the
local `path` list), not every parent of every node it touched. A shared node still accumulates correctly
because each path that reaches it adds into the same `value_sum` as it is explored (§1.6, §4). `node.parents`
is maintained (for future full-DAG variants and `re_root`) but is *not* read during backprop.

### 1.6 Whose value? — the decider and two-player sign-flipping

The one engine concept this code leans on hardest is the **decider**:

> `decider_of(state)` (`agricola/agents/base.py`) returns the player whose decision is awaited:
> the top pending frame's `player_idx` if the stack is non-empty, else `state.current_player`. It
> returns **`None`** at a round-card reveal (a `PendingReveal` whose `player_idx` is `None`) — nature's
> move, which signals a **chance node** (§1.7).

Every node caches its decider in the `decider` field — `decider_of(state)` for a real decision, and the
frame label `0` for a chance node (whose `decider_of` is `None`; see below). Leaf values are always
computed in **P0's frame** (a fixed reference). During backprop, each node stores the value in **its own decider's** frame:
P0 nodes add `+value`, P1 nodes add `−value`. This is the canonical zero-sum convention — it makes every
node's `mean_q` read "how good is this state for the player about to move," which is exactly what the
selection rule needs. When a parent reads a child whose decider differs, it flips the sign (§5).

*Worked example.* A simulation descends `root` (P0 to move) → `child` (P1 to move) → a leaf the evaluator
scores at **+5** in P0's frame (P0 is ahead). Backprop walks that path: the leaf and `root` are P0-frame
nodes, so each adds `+5` to its `value_sum`; `child` is a P1-frame node, so it adds `−5` (the very same
position is "−5" seen from P1). Later, when `root` ranks its children by UCB, it reads `child`'s mean — a
P1-frame number — and flips it back to `+` before comparing. Storing each node in its own frame and
flipping on read are two faces of the one rule: every `mean_q` answers "how good for the player about to
move *here*."

A chance node is given the frame label `decider = 0` (not a real player) so this same `+value` / sign-flip
math works unchanged; its "nature" meaning is carried by a separate `is_chance` flag (§1.7, §8).

### 1.7 Chance nodes — nature's hidden round-card reveal

Agricola reveals one stage card at the start of rounds 2–14, in an order shuffled at setup and **hidden**
from both players (it lives in the `Environment`, never in `GameState`). The engine models a reveal as an
explicit *nature* step: a `PendingReveal` frame with `player_idx = None`. MCTS must not condition on the
hidden future, so a reveal state becomes a **chance node** (`MCTSNode.is_chance == True`):

- It is **never selected by UCB/PUCT** and **never leaf-evaluated**. Its value *is* the expectation over
  its reveal outcomes; evaluating it directly would be meaningless.
- Instead the search **routes through** it by **deterministic round-robin** over the ≤3 candidate
  `RevealCard`s (reconstructed from public state — which spaces are still unrevealed and the current
  stage; no `Environment` is read). Round-robin keeps the visit mix over outcomes exactly uniform, so the
  chance node's plain `value_sum / visits` converges to the true uniform reveal expectation with no
  weighted estimator (§8).
- It is on the simulation `path` (it accumulates visits/value), but a simulation always descends *past*
  it to a real post-reveal decision (or terminal) node and evaluates there.

Why plain chance nodes (and not determinization / ISMCTS — Information Set MCTS)? Because the hidden order is symmetric (neither
player knows it), exogenous (nature's shuffle, not a function of any private choice), revealed identically
to both, and uniform over outcomes — under those conditions the information set is observer-independent and
ISMCTS collapses onto ordinary MCTS with chance nodes. So plain chance nodes are exactly correct and the
cheapest tool. Round 1's reveal (a wider draw) is dealt at game setup and never reaches the search.

### 1.8 Fencing — why it gets special treatment

Building fences is a *multi-shot path*: the player commits one pasture at a time
(`CommitBuildPasture(cells=…)`, then optionally another, then `Stop`). A single worker placement can thus
spawn a deep sub-tree, and the strategic unit is the *final layout*, not each individual commit. Two
strategies exist, selected by `FenceMode`:

- **`MACRO`** (UCT default): collapse a whole fence layout into a single MCTS-internal
  `MacroFencingAction` child. For each fencing-trigger point the search pre-generates one *greedy* layout
  (played by the heuristic) plus several *random* layouts, dedups them by endpoint state, and offers them
  as a handful of children — so UCT discriminates among whole layouts instead of drowning in per-commit
  depth. When the agent picks a macro at the root it **commits** to that layout's action sequence and
  replays it across subsequent calls without re-searching (§9).
- **`FLATTEN`** (PUCT default): no macros — each `CommitBuildPasture` is a plain in-tree action, in the
  engine-native action space the policy is trained on. A deeper tree, made tolerable by the prior.
- **`SEQUENCE_PRIOR`**: a planned hybrid; **not implemented** (the constructor raises).

Fencing is the only sub-action chain that gets this treatment; all other chains (Cultivation, Grain
Utilization, Major Improvement, the harvest frames, …) are searched in-tree as ordinary nodes, kept
shallow by the legality wrapper (§7) and the forced-move step-through (§4).

### 1.9 From simulations to a played move

After the simulation budget is spent, `MCTSAgent` does **not** play the PUCT/UCB-best child. It plays a
move sampled from the **root's visit-count distribution**, softmaxed at temperature `T = 0.2` (close to
argmax, with occasional second choices for game-record diversity) — the AlphaZero "search with the
selection rule, play by visit counts" split (§10). The tree is **reused** across moves (re-rooted to the
new state), and several **sharing modes** support self-play (§11).

---

## 2. The three objects

### 2.1 `MCTSNode`

One node per unique `GameState`. Declared `@dataclass(eq=False)` so it keeps Python's **identity**
equality/hash (two nodes are equal iff they are the same object) — exactly the "one node per state"
semantics the transposition table enforces, and what lets nodes be used as keys in identity-based sets
(e.g. `re_root`'s reachability walk).

```python
@dataclass(eq=False)
class MCTSNode:
    state: GameState
    decider: int                       # decider_of(state); 0 (frame label) for chance nodes
    search: "MCTSSearch"               # back-ref for config access
    parents: list["MCTSNode"] = field(default_factory=list)           # DAG in-edges (small in-degree, identity eq)
    children: dict[Action, "MCTSNode"] = field(default_factory=dict)  # action -> child, populated lazily during EXPAND
    action_from_parent: Optional[Action] = None                       # one incoming edge; debugging only
    visits: int = 0
    value_sum: float = 0.0             # cumulative value in THIS node's decider frame
    macro_sequences: dict[MacroFencingAction, list[Action]] = field(default_factory=dict)  # set iff node generated macros
    is_chance: bool = False            # True iff decider_of(state) is None (a reveal)
    chance_counts: dict[Action, int] = field(default_factory=dict)    # per-outcome round-robin counter (NOT child.visits)
    _legal_actions: Optional[list[Action]] = None   # per-node legal-action cache (lazy)
    _unvisited_actions: Optional[set] = None        # UCT's not-yet-expanded set (lazy)
    _action_priors: Optional[dict] = None           # PUCT prior P(s,·); lazy, multi-option only
```

Key field notes:

- **`value_sum` is frame-relative.** Stored in this node's decider's perspective (§1.6); `mean_q`
  returns `value_sum / visits` directly (0.0 when unvisited).
- **`_legal_actions` is the hot cache.** Computed once per node by `_compute_legal_actions` and read on
  every descent — direct field access (~10 ns), the primary mechanism for `legal_actions` reuse in the
  search. (MCTS does **not** use the engine's separate `legal_actions_cache()`; per-node caching covers
  the whole hot path.) At a terminal node both caches are empty.
- **`_unvisited_actions`** drives the UCT expansion sweep (a `set`, items discarded as expanded). PUCT
  does not use it.
- **`_action_priors`** is the PUCT prior over `_legal_actions`, filled lazily by `_ensure_priors` on the
  first *selection* from a multi-option node — `None` for never-selected nodes, chance nodes, singletons,
  and all UCT runs (§5.2, §5.3).
- **`chance_counts`** is the per-outcome counter used *instead of* `child.visits` for round-robin routing,
  because a post-reveal child shared by another DAG path inflates `child.visits` and would skew routing
  away from uniform (§8).
- **Mutability:** everything except `state` (a frozen `GameState`) is mutated in place. `MCTSNode` is the
  one mutable object in the search.

The node also exposes small helpers: `mean_q` (property), `is_terminal()`
(`state.phase == Phase.BEFORE_SCORING`), `has_legal_actions()`, `has_unvisited()`,
`_compute_legal_actions()` (§7), and `_ensure_priors()` (§5.3).

### 2.2 `MCTSSearch`

Owns the tree and all search-level configuration. One `MCTSSearch` = one tree.

```python
class MCTSSearch:
    def __init__(self, *,
        legal_actions_fn=None,       # default: mode-aware — full legal_actions under PUCT, strict-restricted under UCT (§7/§12)
        evaluator_config=None,       # 3rd arg to evaluator_fn (V3 config, or the NN model itself); default DEFAULT_CONFIG_V3
        evaluator_fn=None,           # (state, player_idx, config) -> float; MUST return a P0-frame margin; default evaluate_hubris_v3_differential
        heuristic=None,              # plays GREEDY fence macros; default = EvaluatorAgent bound to evaluator_fn (V3 by default)
        n_random_fencing=4,          # random fence macros per trigger (in addition to 1 greedy)
        rng_seed=0,
        leaf_value_scale=1.0,        # divide leaf value before backprop (calibrate c_uct across evaluators)
        policy_fn=None,              # None => UCT; set => PUCT
        macro_policy_fn=None,        # optional fence-chain SAMPLER (NOT the PUCT prior); MACRO mode only (§9.1)
        fence_mode=None,             # default FenceMode.MACRO
    ): ...
```

Resolved fields: `transpositions` (the table), `root`, `rng` (a `numpy` Generator used for all
tree-internal randomness — macro sampling, selection tiebreaks, chance tiebreaks), and the resolved
`evaluator_fn` / `evaluator_config` / `legal_actions_fn` / `heuristic`. The defaults wire a fully-V3
search; the dependencies on `agricola.agents.heuristic` are **lazily imported** (`_lazy_*` shims at the
bottom of the module) so a bare `import agricola.agents.mcts` stays cheap.

Two constructor **invariants** are enforced immediately:

```python
if self.policy_fn is not None and self.fence_mode is FenceMode.MACRO:
    raise ValueError("PUCT (policy_fn set) cannot use FenceMode.MACRO; use FenceMode.FLATTEN.")
if self.fence_mode is FenceMode.SEQUENCE_PRIOR:
    raise NotImplementedError("FenceMode.SEQUENCE_PRIOR is not implemented yet ...")
```

Its methods are grouped into transposition-table maintenance (`find_or_create_node`, `add_edge`,
`re_root` — §3), leaf evaluation (`evaluate_leaf` — §6), and the fence-macro machinery (`expand_macros`
and helpers — §9).

### 2.3 `MCTSAgent`

The caller-facing object implementing the `Agent` protocol (`__call__(state) -> Action`). It holds the
*agent-level* knobs and the per-move loop:

```python
class MCTSAgent:
    def __init__(self, search, *,
        sims_per_move=500, c_uct=1.4, fpu_offset=0.0,
        action_selection_temperature=0.2, rng_seed=0,
        cap_total_sims=True,         # default True: cap TOTAL root visits (incl. inherited) vs run that many fresh sims (§11.1)
    ):
        self.search = search
        ...
        self.rng = np.random.default_rng(rng_seed)   # ONLY for top-level action selection
        self._pending_macro_actions: list[Action] = []  # the committed-macro replay queue
```

Note the **RNG split**: the agent's `self.rng` is used *only* for the top-level played-move sampling
(`_select_action_with_temperature`); all tree-internal randomness uses `search.rng`. Keeping them
separate makes the played move and the tree exploration independently reproducible. `__call__` is the
entry point (§4 / §10); `_simulate` runs one simulation; the rest are selection and routing helpers.

### 2.4 `MacroFencingAction` and `FenceMode`

```python
@dataclass(frozen=True)
class MacroFencingAction:
    label: str          # "greedy", "random_0", "random_1", ...

class FenceMode(Enum):
    MACRO = "macro"             # UCT-only: collapse a layout into one macro child
    FLATTEN = "flatten"         # PUCT default: per-pasture CommitBuildPasture in-tree
    SEQUENCE_PRIOR = "sequence_prior"   # planned; raises NotImplementedError
```

`MacroFencingAction` is an **MCTS-internal pseudo-action** — it lives in `mcts.py`, never in `actions.py`,
and the engine never sees one. It is a key in `node.children` and `node.macro_sequences`; the agent
translates it back into a real engine-action sequence at play time (§9). Its `label` is its identity
(frozen dataclass, field-based eq), which is why each parent has at most one `"greedy"` plus
`"random_0..k"` — labels are unique per parent.

`uniform_policy(state, legal_actions) -> {action: 1/n}` is also defined here: a trivial `policy_fn` that
exercises the PUCT machinery before a trained policy exists (§5.3).

---

## 3. The DAG: transposition table, edges, decider assignment, re-rooting

### 3.1 `find_or_create_node` — the single node factory

Every node is born here, and the transposition table is the single source of truth: at most one node per
state.

```python
def find_or_create_node(self, state, *, parent=None, action_from_parent=None):
    existing = self.transpositions.get(state)
    if existing is not None:
        if parent is not None:
            self.add_edge(parent, existing, action_from_parent)   # new DAG in-edge
        return existing
    d = decider_of(state)
    is_chance = d is None
    node = MCTSNode(
        state=state,
        decider=0 if is_chance else d,   # frame label when chance; real player otherwise
        is_chance=is_chance,
        search=self,
        action_from_parent=action_from_parent,
    )
    self.transpositions[state] = node
    if parent is not None:
        self.add_edge(parent, node, action_from_parent)
    return node
```

This is where **`decider` and `is_chance` are assigned** (§1.6/§1.7): a `None` decider means a reveal, so
`is_chance=True` and `decider` is set to the P0 frame label `0`. A returned existing node just gets the new
parent edge wired (the DAG case). Hashing `state` is the ~tens-of-microseconds cost; an already-present
state is a cheap dict hit.

### 3.2 `add_edge` — the one place edges are created

```python
def add_edge(self, parent, child, action):
    if action is not None:
        parent.children[action] = child
    if parent not in child.parents:
        child.parents.append(parent)   # identity 'in' check (eq=False)
```

The single choke point that keeps `parents` deduplicated and `children` consistent.

### 3.3 `re_root` — tree reuse between moves

At the start of each real (non-macro-replay) move, the agent designates the current state's node as the
new root and prunes everything no longer reachable:

```python
def re_root(self, new_root):
    if new_root is self.root:
        return
    reachable_ids = set()
    queue = [new_root]
    while queue:
        node = queue.pop()
        if id(node) in reachable_ids:
            continue
        reachable_ids.add(id(node))
        queue.extend(node.children.values())
    self.transpositions = {s: n for s, n in self.transpositions.items()
                           if id(n) in reachable_ids}
    self.root = new_root
```

Statistics from the prior search that fall under the new root are **kept** (tree reuse — a node visited
1000× last move starts the next move with those 1000 visits); everything else is dropped so the table
doesn't grow without bound. The walk follows `children` (including macro and chance children).

---

## 4. One simulation, step by step (`_simulate`)

`MCTSAgent._simulate(root)` is the loop in §1.2 made concrete. Here is the full body, then the walk-through.

```python
def _simulate(self, root):
    path = [root]
    node = root

    # ---------- SELECT + EXPAND ----------
    while True:
        if node.is_terminal():
            break

        if node.is_chance:
            action = self._chance_route(node)            # round-robin pick + counter bump
            child = node.children.get(action)
            is_new = child is None
            if is_new:
                child = self.search.find_or_create_node(
                    step(node.state, action), parent=node, action_from_parent=action)
            path.append(child)
            node = child
            if is_new:
                break          # fresh post-reveal decision node = leaf
            continue           # existing outcome -> keep descending

        # ---- decision node ----
        if node._legal_actions is None:
            node._compute_legal_actions()
        if not node._legal_actions:
            break              # defensive: no legal actions at a non-terminal node

        if self.search.policy_fn is not None:
            child, is_new = self._puct_select_child(node)
        else:
            child, is_new = self._uct_select_child(node)
        path.append(child)
        node = child
        if is_new:
            if node.is_chance:
                continue       # route through the reveal next iteration
            if not node.is_terminal():
                if node._legal_actions is None:
                    node._compute_legal_actions()
                if len(node._legal_actions) == 1:
                    continue   # FORCED move: step through in this same sim
            break              # multi-option decision or terminal -> evaluate
        # existing child -> keep descending

    # ---------- EVALUATE ----------
    leaf_value_p0 = self.search.evaluate_leaf(node.state)

    # ---------- BACKPROP ----------
    for n in path:
        if n.decider == 0:
            n.value_sum += leaf_value_p0
        else:
            n.value_sum -= leaf_value_p0
        n.visits += 1
```

**The descent.** Each loop iteration handles `node`:

- **Terminal** (`phase == BEFORE_SCORING`) → stop; this leaf is evaluated (a terminal margin, §6).
- **Chance** → `_chance_route` picks one reveal outcome (§8). A *newly created* outcome becomes the leaf
  (`break`); an *existing* outcome is descended into (`continue`). Either way the chance node is on the
  `path` but is never itself the evaluation target.
- **Decision** → ensure `_legal_actions`, then dispatch to PUCT or UCT selection (§5), which returns
  `(child, is_new)`. The child is appended and becomes `node`.

**Forced-move step-through (§1.2, the `is_new` block).** When selection creates a fresh non-terminal child
that has exactly **one** legal action, the simulation does *not* evaluate it — it `continue`s and steps
through, so the value lands at the next genuine (multi-option or terminal) decision. Two payoffs:

1. The evaluator is only ever queried at *real* decisions and terminals — the same distribution a value
   network is trained on (it never sees a singleton mid-action state).
2. A whole forced chain is traversed in **one** simulation rather than one-node-per-sim.

The forced node still becomes a tree node (DAG-friendly) and gets its Q filled by backprop of the
downstream value, which is correct because the move is forced (`V*(forced) = V*(child)`). This mirrors how
a forced (single-candidate) reveal is already stepped through by the chance path, so players' forced moves
and nature's forced reveals behave alike. It applies to **both UCT and PUCT** — which is the one reason UCT
here is *not* byte-identical to a pre-step-through engine (§13).

**EVALUATE.** `node` at this point is guaranteed *not* to be a chance node (the descent only breaks at a
decision/terminal leaf). `evaluate_leaf` returns the value in P0's frame (§6).

**BACKPROP.** Walk the recorded `path` (not `node.parents`, §1.5) and fold the P0-frame value into each
node's frame: `+value` for P0 nodes (and chance nodes, `decider == 0`), `−value` for P1 nodes. Increment
each node's `visits`. The freshly created leaf is on the path, so its visit count starts at 1.

### Cost cheat-sheet

> **These numbers are guesses, not measurements.** They are order-of-magnitude estimates carried over
> from the design notes (design_docs/MCTS_DESIGN.md §5.0), never profiled fresh — and the design doc itself flagged
> them as coarse. The fence-macro row especially is unverified and may be well off. **Trust the *ratios*
> (descent ≪ expansion ≈ leaf-eval ≪ fence-macro), not the absolute figures.** They are also the
> *V3-heuristic-leaf* shape; the **production NN-leaf PUCT** workload looks different (no fence-macro row
> under FLATTEN, the hash row now cached, the leaf split into encode + NN forward). For real measurements
> and how the landed optimizations remap this table, see **§14** and the current production profile in
> `PROFILING.md`.

The loop mixes sub-microsecond bookkeeping with a few genuinely expensive calls (V3 heuristic leaf; an NN
leaf shifts the EVALUATE row):

| Operation | Cost | When |
|---|---|---|
| `node.children[action]` dict lookup, UCB/PUCT arithmetic per child, `path.append` | sub-µs | every descent step |
| `node._legal_actions` field read (after cache filled) | ~10 ns | every descent step |
| `step(state, action)` (engine transition) | ~10 µs | once per new node |
| `find_or_create_node` (hashes `GameState`) | ~~26 µs when hashed~~ now cheap — hash is cached (§14) | once per new node |
| `_compute_legal_actions` (`strict_restricted_legal_actions`) | ~30 µs | once per node, lazy on first touch |
| `evaluate_leaf` (V3 heuristic margin) | ~50–100 µs | once per simulation, at the leaf |
| fence-macro generation (1 greedy + ≤4 random chains) | ~tens–hundreds of ms | once per node exposing a fence trigger (§9) |

**Per-simulation total ≈ 100–200 µs** (dominated by expansion + leaf eval; the descent is cheap because it
is all dict lookups and arithmetic). At 500 sims/move that is ~50–100 ms per move, plus the one-time
per-node `_compute_legal_actions`. The expensive operations are paid **once per node**, never per visit —
that is what makes the search scale. (Fence-macro generation is the exception: it is heavy and paid once at
each fence-trigger parent; §9.)

---

## 5. Selection in detail

The descent dispatches on `self.search.policy_fn`: `None` → UCT (`_uct_select_child`), else PUCT
(`_puct_select_child`). Both return `(child, is_new)`: `is_new=True` means a fresh leaf was just
materialized (the caller stops and evaluates it, modulo the forced-move step-through); `is_new=False`
means we descended into an existing child and keep going.

### 5.1 UCT (`_uct_select_child` + `_select_via_ucb`)

UCT is a two-phase rule: **expand every child once (random order), then discriminate by UCB.**

```python
def _uct_select_child(self, node):
    if node._unvisited_actions:                       # phase 1: expansion sweep
        action = self._pick_unvisited_action(node)    # uniform-random over the set
        node._unvisited_actions.discard(action)
        if isinstance(action, MacroFencingAction):
            child = node.children[action]             # macro children pre-created (§9)
            self.search.add_edge(node, child, action) # re-register if reached via another parent
        else:
            child = self.search.find_or_create_node(
                step(node.state, action), parent=node, action_from_parent=action)
        return child, True
    action = self._select_via_ucb(node)               # phase 2: UCB over all children
    return node.children[action], False
```

So while a node has any unexpanded action, each simulation expands one (chosen uniformly at random — the
"random ordering among tied unvisited children" that avoids the systematic bias of `legal_actions` output
order). Only once all children exist does `_select_via_ucb` rank them:

```python
def _select_via_ucb(self, parent):
    parent_mean_q = parent.mean_q if parent.visits > 0 else 0.0
    log_term = math.log(parent.visits + 1)
    best_score, best_actions = -inf, []
    for action, child in parent.children.items():
        if child.visits == 0:                          # FPU (see note below)
            score = parent_mean_q - self.fpu_offset + self.c_uct * math.sqrt(log_term)
        else:
            child_q = child.value_sum / child.visits
            if child.decider != parent.decider:        # frame conversion (§1.6)
                child_q = -child_q
            score = child_q + self.c_uct * math.sqrt(log_term / child.visits)
        # argmax with random tiebreak via search.rng
        ...
```

The exploration term `c_uct·√(ln(N_parent+1)/N_child)` shrinks as a child is visited, so a child whose
mean roughly matches the parent's eventually yields to a less-visited sibling — the classic
exploration/exploitation cycle. A child whose mean is much higher keeps winning (exploitation); much lower,
it is quickly abandoned. Tiebreaks (e.g. equal scores) are broken randomly with `search.rng` for
determinism per search seed.

**FPU note (design-vs-code, §13).** `design_docs/MCTS_DESIGN.md` motivates FPU as the way to *avoid* the full
expand-every-child sweep. The shipped UCT path does **not** avoid it — it sweeps all unvisited children
first (the `_unvisited_actions` phase), so by the time `_select_via_ucb` runs, every child already has
`visits ≥ 1` and the `child.visits == 0` FPU branch is effectively a **defensive guard** (it and the
`parent.visits > 0` fallback are dead in steady state, since reaching `_select_via_ucb` requires having
expanded all children). `fpu_offset` therefore has little effect in UCT; it is meaningful in **PUCT**,
where unvisited children are scored *without* a prior sweep (§5.2). This is an honest discrepancy from the
design doc, not a bug — the UCT control behaves as "sweep then UCB."

### 5.2 PUCT (`_puct_select_child` + `_select_via_puct`)

PUCT has **no** expansion sweep: it scores *all* legal actions — created or not — in one pass, and a
selected-but-uncreated child is materialized on the spot (that is the expansion). Low-prior actions can go
forever unvisited; that is the soft-prune.

```python
def _puct_select_child(self, node):
    action = self._select_via_puct(node)
    child = node.children.get(action)
    is_new = child is None
    if is_new:
        child = self.search.find_or_create_node(
            step(node.state, action), parent=node, action_from_parent=action)
    return child, is_new
```

```python
def _select_via_puct(self, parent):
    if len(parent._legal_actions) == 1:
        return parent._legal_actions[0]      # forced move: no prior needed (singleton short-circuit)
    parent._ensure_priors()                  # lazily compute P(s,·) on first selection (§5.3)
    priors = parent._action_priors or {}
    parent_q = parent.mean_q if parent.visits > 0 else 0.0
    sqrt_total = math.sqrt(max(parent.visits, 1))      # √ΣN ≈ parent.visits
    best_score, best_actions = -inf, []
    for action in parent._legal_actions:
        child = parent.children.get(action)
        prior = priors.get(action, 0.0)
        if child is None or child.visits == 0:
            q = parent_q - self.fpu_offset   # FPU reduction; prior carries exploration
            n = 0
        else:
            q = child.value_sum / child.visits
            if child.decider != parent.decider:
                q = -q                       # frame conversion (§1.6)
            n = child.visits
        score = q + self.c_uct * prior * sqrt_total / (1 + n)
        # argmax with random tiebreak via search.rng
        ...
```

This is canonical AlphaZero PUCT: `U(s,a) = Q(s,a) + c_puct·P(s,a)·√ΣN/(1+N(s,a))`. Notes:

- **`c_uct` is reused as `c_puct`** (one mode runs at a time). It must be calibrated against the
  **`leaf_value_scale`-normalized** Q spread — an uncalibrated constant produces confidently-wrong search.
  Pass the value net's measured value scale as `leaf_value_scale` so a single `c_uct` is comparable across
  evaluators of different magnitude (§6, §12).
- **Singletons short-circuit** before any prior is computed, which (with `_ensure_priors`'s own guards)
  means the policy forward pass fires only on genuine multi-option nodes.
- **No `MacroFencingAction` handling** — PUCT runs only under `FLATTEN`/`SEQUENCE_PRIOR`, where fencing is
  plain per-pasture actions (the constructor forbids PUCT + `MACRO`).

### 5.3 The policy prior as a black box (`policy_fn`, `_ensure_priors`)

MCTS sees the policy through exactly one contract:

```
policy_fn(state, legal_actions) -> {action: prior}     # priors over the legal set
```

The dict is keyed by the engine `Action` objects passed in (frozen → hashable; they match exactly). All
head structure, masking, score-the-set scoring, dispatch by decision type, and renormalization live
**inside** `policy_fn`; `mcts.py` never inspects it. Untrained decision types fall back to uniform inside
the policy, so a partial policy works with zero search changes. There is **no** default policy — the
`MCTSSearch` default is `policy_fn=None`, which selects UCT. `uniform_policy` (defined in this module) is a
provided placeholder you pass *explicitly* to exercise the PUCT machinery before a trained policy
exists; it is not wired in automatically. A *trained* `policy_fn` comes from the behavioral-cloning combiner
— `agricola.agents.nn.policy.load_policy_fn(checkpoints)`, or the convenience wrapper
`scripts/nn/build_combined_policy.build(variant)` with `variant ∈ {"unweighted", "awr"}` (plain
cross-entropy heads vs advantage-weighted heads). Both return the same `policy_fn(state, legal) -> {action:
prior}` contract; the head structure behind them is the design_docs/POLICY_HEAD.md black box.

The prior is computed **lazily**, on the first selection from a multi-option node:

```python
def _ensure_priors(self):
    if (self._action_priors is None
            and self.search.policy_fn is not None
            and not self.is_chance):
        if self._legal_actions is None:
            self._compute_legal_actions()
        self._action_priors = self.search.policy_fn(self.state, self._legal_actions)
```

This split — `_compute_legal_actions` (enumeration, always) separate from `_ensure_priors` (the policy
forward pass, lazy) — matters because the descent enumerates legal actions *early* (to run the forced-move
check). Bundling the prior into enumeration would compute the policy on every new node, including the
singletons we step through and the frontier leaves we never expand. With separate value/policy nets that
keeps the policy forward pass strictly off those nodes. A future *shared* value+policy trunk would instead
populate the prior at leaf-eval time, paired with the value in one trunk pass; the interface is built so
that change is additive (it is not implemented today).

Two performance/correctness notes on `policy_fn`, both in §14: the policy heads must run in **`eval()`
mode** (the combiner `make_policy_fn` now ensures this — un-eval'd heads gave *nondeterministic* priors),
and the encoder memo lets the policy's per-state encode be **shared with the value leaf** at decider-0 nodes.

#### 5.3.1 Optional uniform-mix of the prior (`prior_uniform_mix`)

The policy prior can optionally be **blended with a uniform distribution** before PUCT consumes it:

```
prior'(s, a) = (1 − w)·policy(s, a) + w·(1/k)      over the k legal actions a at state s
```

with `w = prior_uniform_mix ∈ [0, 1]` (`w = 0` is pure policy — the default). The blend guarantees
**every** legal action a non-zero prior, so PUCT will eventually try moves the policy scored ≈0. Without
it, a sharply-peaked policy can make the search pour almost all of its visits onto the top 2–3 actions and
never explore the rest — the failure mode that motivated this knob (a 800-sim search putting 799 visits on
one child).

This is implemented in the **C++ production search** (the web-UI / data-gen path), *not* in the Python
`mcts.py` reference engine:

- `MCTSSearch::set_prior_uniform_mix(double)` (`cpp/include/agricola/mcts.hpp`) sets the member
  `prior_uniform_mix_` (default `0.0`).
- `ensure_priors` (`cpp/src/mcts.cpp`) applies the blend over `node->legal` right after `policy()` fills
  `node->priors` — an action the policy omitted (prior 0) becomes `w·(1/k)`.

Two consumers set it, both via the `selfplay` binary's `--prior-mix` / `--prior-mix-p0|-p1` flags:

- **The web-UI "Show analysis" overlay** mixes at `w = 0.05` so the read-out covers ~all of the human's
  options, not just the 2–3 the policy peaks on (`play_web.py` `analyze` → `selfplay --analyze`).
- **The opponent bot** can optionally mix (a per-game New-Game input, default `0.0`) for a wider, less
  deterministic game (`_CppMctsAgent(prior_mix=…)` → `selfplay --move`). A 400-game self-play test
  (200 + 200 seat-flipped) at `w = 0.05` vs `w = 0` found the mix **not stronger** (≈46% — neutral to
  slightly weaker), so it is left **off by default** for the bot and used mainly to broaden analysis
  coverage.

The mix is a pure post-processing step on the prior; selection formula, FPU, chance routing, and backprop
are untouched. It is *not* Dirichlet root noise — it is deterministic, applied at **every** node (not just
the root), and mixes toward exact-uniform rather than a sampled noise vector.

### 5.4 What the two rules share

Both selection rules sit inside the same `_simulate` machinery: the DAG / transposition table, the P0-frame
leaf value with per-node sign-flip (§1.6), the forced-move step-through (§4), chance routing (§8), path-only
backprop, the `search.rng` tiebreaks, and the visit-count played move (§10). The *only* code difference is
which `_*_select_child` runs — chosen by `policy_fn is None`.

---

## 6. Leaf evaluation (`evaluate_leaf`) — the value black box

Every simulation ends in one call to `MCTSSearch.evaluate_leaf(state)`, which returns the leaf value in
**P0's reference frame** (a margin), divided by `leaf_value_scale`:

```python
def evaluate_leaf(self, state):
    if state.phase == Phase.BEFORE_SCORING:                                      # terminal
        return (score(state, 0)[0] - score(state, 1)[0]) / self.leaf_value_scale # EXACT score margin
    return self.evaluator_fn(state, 0, self.evaluator_config) / self.leaf_value_scale  # evaluator's P0-frame margin
```

The contract with the **value black box** is `evaluator_fn(state, player_idx, config) -> float`, and it
**must already return a P0-frame margin** (own − opponent) — the leaf calls it **once** and never
differences it itself. The default is `evaluate_hubris_v3_differential` with `config = evaluator_config`.
Crucially, `config` is just the third argument threaded into `evaluator_fn` — so a value network is wired by
passing the **model itself as `evaluator_config`** and an adapter as `evaluator_fn` (the production pattern
in `scripts/nn/play_match.py`: `evaluator_config=model, evaluator_fn=nn_evaluator_differential`). Three
things to understand:

- **Terminal states use the exact score, not the evaluator.** At `BEFORE_SCORING`, `evaluate_leaf` returns
  the true game margin `score(s, 0) − score(s, 1)` directly, **independent of `evaluator_fn`**. The outcome
  is freely computable at game-end, so the search never asks the evaluator to *guess* it — which also means a
  value net can't mis-predict the terminal (an NN leaf whose descent reaches a terminal endpoint still gets
  the exact score here). The `evaluator_fn` path is taken only mid-game.
- **The evaluator returns a margin from one call.** Mid-game the leaf is `evaluator_fn(state, 0)` — a single
  call, no in-leaf subtraction. The default `evaluate_hubris_v3_differential` is the V3 evaluator wrapped to
  return `e(s,0) − e(s,1)` (a P0-frame margin, antisymmetric by construction); an NN leaf passes
  `nn_evaluator_differential` (2-pass, lower variance) or `nn_evaluator` (1-pass, faster), both already
  P0-frame margins. (The old `leaf_differential` flag — which made the leaf difference a *single-player*
  evaluator itself — was **removed**; the evaluator now owns the margin convention. See §13.)
- **`leaf_value_scale`** (default `1.0`, a no-op for V3) divides every leaf value before backprop, so leaf
  values feed UCB/PUCT on a unit-ish scale and one `c_uct` is comparable across evaluators of different
  magnitude. For an NN leaf, pass the model's measured value scale (`getattr(model, "value_scale", 1.0)`).

`evaluate_leaf` is **never** called on a chance node (§8) — the descent always passes through reveals to a
real decision/terminal node.

**Performance.** An NN leaf's cost is encode + forward, both heavily optimized — and there is one thing the
search depends on the *caller* for: the model must be in **`eval()` mode** (`evaluate_leaf` does not eval it;
a TRAIN-mode model fires dropout → noisy leaf values). See §14.

---

## 7. Legality and action pruning

Every legality consultation in the search routes through `self.search.legal_actions_fn`, whose default is
**mode-aware** (§12): the engine's full unrestricted `legal_actions` under PUCT, a **strict-restricted**
wrapper (RNG-bound) under UCT. `_compute_legal_actions` builds the per-node cache:

```python
def _compute_legal_actions(self):
    if self.is_terminal():
        self._legal_actions = []
        self._unvisited_actions = set()
        return
    from tests.test_utils import filter_implemented
    raw = filter_implemented(self.search.legal_actions_fn(self.state))
    if self.search.fence_mode is FenceMode.MACRO:
        self._legal_actions = self.search.expand_macros(self, raw)   # macro-collapse fencing (§9)
    else:
        self._legal_actions = raw                                    # FLATTEN: plain per-pasture actions
    self._unvisited_actions = set(self._legal_actions)
```

Two filters stack here:

**`filter_implemented`** (from `tests/test_utils.py`) drops `PlaceWorker` targets the engine cannot yet
resolve — today only `lessons` (no card system). It is the same filter the agent base and the random driver
use; it widens automatically as new spaces land. (It lives under `tests/` and is imported lazily inside the
hot methods — a quirk worth knowing, §13.)

**The legality wrapper.** The default is **mode-aware** (§12): under UCT it is
`strict_restricted_legal_actions`; under PUCT it is the engine's **full, unrestricted** `legal_actions`
(the policy is the sole prune — see the §7 closing paragraph). The strict wrapper layers four
MCTS-specific collapses on top of the regular `restricted_legal_actions` wrapper. Both are pure functions over the
engine's unrestricted `legal_actions(state)` (the engine is never modified), both are inert at empty-stack
worker-placement decisions, and both route every filter through a `_safe_narrow` guard so a filter can never
empty a non-empty action set (the always-≥1 invariant). The regular wrapper applies strategic priors
(cell-priority lists for rooms/stables/plow, a first-pasture opener requiring cell (0,4), a hard 5-room cap,
and a minimum-begging filter at harvest feed). Strict adds, keyed on the top pending frame:

- **Cultivation sow-max** (`PendingSow` from Cultivation): keep only the `CommitSow` maximizing grain+veg.
- **Grain-Utilization veggie rule** (`PendingSow` from Grain Utilization): the player chooses grain; veg is
  auto-maxed to `min(veg_in_supply, empty_fields − grain)`.
- **Fencing patterns** (`PendingBuildFences`): 9 hand-curated `(pastures, wood) → allowed layouts` rules
  that collapse the per-pasture commit set to specific openers/extensions.
- **Harvest-feed cap** (`PendingHarvestFeed`): if >7 `CommitConvert` options exist, keep the top-5 by a
  value-function ranking plus 2 random samples (crafts and other actions always kept). This is the one
  filter needing an RNG and a ranker — which is why `MCTSSearch` builds its wrapper via
  `make_strict_restricted_legal_actions(config=…, rng=self.rng)` so the cap's samples are deterministic per
  search seed. The ranker is injectable (`evaluator=`), defaulting to V3 (next paragraph).

The cap's ranker is a value function injected via `make_strict_restricted_legal_actions(evaluator=…)` — a
callable `(state, player_idx) -> float`. If omitted, the wrapper builds the **default V3 ranker** from
`config` (the original behavior). Two consequences:

- `MCTSSearch`'s *default* legality wrapper passes only `config=self.evaluator_config` (no `evaluator=`),
  so its feed cap ranks with **V3**. Fine for a V3 search — but if `evaluator_config` is an NN **model**
  (the §6 NN wiring), that default would try to use the model *as* a V3 config and fail. So with an NN leaf
  you must still pass an **explicit** `legal_actions_fn`.
- The clean way is `make_strict_restricted_legal_actions(evaluator=<nn ranker>)`, which ranks the feed cap
  with the **same value function as the leaf** — V3-free for an NN agent. `scripts/play_mcts_match.py` does
  exactly this under `--leaf nn`. (Passing `config=DEFAULT_CONFIG_V3` instead keeps a valid V3-ranked cap,
  but reintroduces a small V3 component into an otherwise-NN search.)

The net effect (under UCT) is a small branching factor at sub-action chains, so in-tree search of
non-fencing chains stays cheap. **PUCT instead takes the engine's *full, unrestricted* `legal_actions`**
(the mode-aware default when `policy_fn` is set, §12) and soft-prunes **entirely via the prior** — this is
`make_policy_fn`'s contract that "the prune lives entirely in the policy," so a wrapper here would
double-prune and hide actions the prior is meant to weigh. (The strict collapses also turn lossy once cards
exist, so dropping them under PUCT is the right call regardless.)

---

## 8. Chance nodes (the hidden round-card reveal)

A chance node is created automatically: `find_or_create_node` sets `is_chance=True` whenever
`decider_of(state) is None` (a `PendingReveal`, §1.7), and labels it `decider=0`. Everything else about
chance handling is the routing in `_simulate`'s chance branch (§4) plus `_chance_route`:

```python
def _chance_route(self, node):
    if node._legal_actions is None:
        node._compute_legal_actions()
    candidates = node._legal_actions                 # the ≤3 RevealCard actions
    counts = node.chance_counts
    min_count = min(counts.get(a, 0) for a in candidates)
    least = [a for a in candidates if counts.get(a, 0) == min_count]
    action = least[0] if len(least) == 1 else least[int(self.search.rng.integers(len(least)))]
    counts[action] = counts.get(action, 0) + 1
    return action
```

The mechanics and the *why* behind each choice:

- **The candidates are public.** `_compute_legal_actions` → `legal_actions` → the engine's reveal
  enumerator returns the ≤3 `RevealCard`s consistent with public state (which spaces are unrevealed, the
  current stage). No `Environment`/hidden order is read. The legality wrappers pass reveal frames through
  untouched.
- **Round-robin, not UCB.** Routing always picks the **least-routed** outcome (RNG tiebreak), so the
  outcome mix stays exactly uniform. Nature is not an adversary to exploit, and uniform coverage means the
  chance node's plain `value_sum / visits` converges to the true uniform reveal expectation
  `Σ (1/k) V(child)` — no weighted estimator needed.
- **`chance_counts`, not `child.visits`.** A post-reveal child can be shared by another DAG path, which
  inflates its `child.visits`; routing on that would skew away from uniform. The per-node `chance_counts`
  counts only routes *through this chance node*.
- **Never evaluated, always passed through.** Both ways a chance node is reached — SELECT descending into an
  existing one, or EXPAND creating one from a round-ending action — route *through* it (§4: the chance
  branch, and the `if node.is_chance: continue` after expansion). A new post-reveal child is the leaf; an
  existing one is descended into.
- **Backprop is unchanged.** The chance node sits on `path` with `decider=0`, so it accumulates
  `+leaf_value_p0` (a P0-frame value), and any P1 parent reading it applies the standard `child.decider !=
  parent.decider` sign-flip. The `is_chance` flag — not `decider` — is the only thing that makes a chance
  node behave differently, and it gates *routing*, never the backprop/UCB math.

A forced (single-candidate) reveal is routed through exactly like a forced player move is stepped through —
the unification noted in §4.

---

## 9. Fencing

Fencing is the search's most involved subsystem because a fence layout is a *path* of per-pasture commits,
not one action (§1.8). The handling is selected by `MCTSSearch.fence_mode`.

### 9.1 `MACRO` mode — collapse a layout into one child (UCT)

In `MACRO` mode, `_compute_legal_actions` routes the raw actions through `expand_macros`, which replaces
each fencing **trigger** with a handful of `MacroFencingAction` children — one per distinct *endpoint
layout*.

**The two trigger points** (`_find_fencing_triggers`):

1. `PlaceWorker("fencing")` at an empty stack — the worker-placement entry to the Fencing space.
2. `ChooseSubAction("build_fences")` while `PendingFarmRedevelopment` is on top — Farm Redevelopment's
   optional fencing step.

(Spec note: `design_docs/MCTS_DESIGN.md` calls trigger 2 `"fences"`; the engine actually emits `"build_fences"`, and
the code follows the engine — §13.)

**`expand_macros`** replaces each trigger with its generated macros, creates the macro **child nodes
eagerly** (so they are wired before MCTS visits them), and records each macro's full engine-action sequence
on the parent's `macro_sequences`:

```python
def expand_macros(self, parent_node, raw_actions):
    triggers = self._find_fencing_triggers(parent_node.state, raw_actions)
    if not triggers:
        return raw_actions
    other_actions = [a for a in raw_actions if a not in triggers]
    macro_actions = []
    for trigger_action in triggers:
        for label, sequence, endpoint_state in self._generate_fencing_macros(
                parent_node.state, trigger_action):
            macro_action = MacroFencingAction(label=label)
            parent_node.macro_sequences[macro_action] = sequence   # parent-keyed!
            self.find_or_create_node(endpoint_state, parent=parent_node,
                                     action_from_parent=macro_action)
            macro_actions.append(macro_action)
    return other_actions + macro_actions
```

Sequences are stored **on the generating parent**, not the endpoint node, so two parents whose macros happen
to converge on the same endpoint state each retain their own action sequence.

**`_generate_fencing_macros`** produces up to `1 + n_random_fencing` distinct macros (default 1 greedy + 4
random), **deduplicated by endpoint state** within this parent. Each macro is built in three phases, with the
chain-body predicate being "`PendingBuildFences` (PBF) is on top of the stack":

1. **Entry** (`_enter_pbf`). Apply the trigger, then auto-step through any singleton decisions of the decider
   until PBF is on top. Trigger 1 pushes a `PendingFencing` *wrapper* and reaches PBF via a singleton
   `ChooseSubAction("build_fences")`; trigger 2 pushes PBF directly (`direct_pbf`), so no entry singletons.
   If PBF can't be reached (decider handoff, game end, or an unexpected multi-option — none expected in
   normal play), the attempt bails: a *random* attempt is dropped, while the *greedy* attempt still records
   its current (body-less) endpoint, guaranteeing at least one macro exists.
2. **Chain body** (`_run_pbf_body`). While PBF is on top, pick one action per step — the **greedy** macro
   uses `self.heuristic`, a turn-lookahead `EvaluatorAgent` bound to the search's *own* `evaluator_fn` (so
   greedy fences are played with the same value function as the leaf — V3 by default, the NN under an NN
   leaf, never a hardcoded V3); **random** macros pick uniformly over `legal_actions_fn`. The loop exits
   when PBF pops (its `Stop`), the game ends, or the decider hands off. **Optionally**, if a
   `macro_policy_fn` is set on the search, *every* attempt instead **samples** its next fence action from
   that policy (`_sample_fence_action`, proportional to the prior, with a uniform fallback when the policy
   puts no mass on the legal set) rather than running the greedy value-net rollout — one head-forward per
   step instead of N value-forwards. This is a knob **distinct from** the PUCT `policy_fn`: it only *seeds*
   the candidate macros that plain UCB then chooses among (selection stays UCB, not PUCT).
3. **Exit / wrapper drain** (`_drain_wrapper`). For trigger 1 only, auto-step through the outer
   `PendingFencing`'s remaining singletons (its mandatory `Stop`) so the recorded macro ends with control
   fully handed off — no leftover singleton for MCTS to burn a simulation on. Trigger 2 does **not** drain:
   after PBF pops, control is back at `PendingFarmRedevelopment`, where the next choices are legitimate
   MCTS-managed decisions.

The greedy macro is attempt 0 (label `"greedy"`); random macros are attempts 1.. (labels `"random_0"`,
`"random_1"`, … in *added* order), bounded by `max_attempts = max(1, n_random_fencing)*3 + 1` so a state
with few distinct layouts doesn't loop forever. (Under a `macro_policy_fn` there is no greedy rollout —
every attempt samples the policy, and the labels are `"policy_0"`, `"policy_1"`, ….) If a chain runs all the
way to game end, the endpoint is terminal and `evaluate_leaf` handles it with no special case.

The entry/body/exit decomposition (and the `direct_pbf` distinction between the two triggers) is detail that
the design doc only sketches; the code is authoritative here.

### 9.2 The agent's macro commitment (replay queue)

Macros are meaningful only if, having searched among whole layouts, the agent actually *plays* the chosen
layout. `MCTSAgent.__call__` handles this with the `_pending_macro_actions` queue:

```python
def __call__(self, state):
    if self._pending_macro_actions:                 # mid-macro: replay, no search, no re-root
        return self._pending_macro_actions.pop(0)
    root = self.search.find_or_create_node(state)
    self.search.re_root(root)
    while root.visits < self.sims_per_move:         # cap_total_sims default; `for _ in range(sims)` if False (§11.1)
        self._simulate(root)
    action = self._select_action_with_temperature(root)
    if isinstance(action, MacroFencingAction):
        sequence = root.macro_sequences[action]     # parent-keyed lookup
        self._pending_macro_actions.extend(sequence[1:])   # queue the chain commits + Stop
        return sequence[0]                          # return the trigger action now
    return action
```

When search selects a macro at the root, the agent returns the trigger action and **queues the rest of the
layout's engine actions**. Subsequent calls during the chain pop straight from the queue — **no MCTS, no
re-root** — until the layout is fully played, after which normal search resumes at whatever state follows.
Macros are only "committed" when chosen *at the root*; inside the tree a `MacroFencingAction` is just an edge
to its endpoint state, scored like any other child.

### 9.3 `FLATTEN` (PUCT) and `SEQUENCE_PRIOR`

Under **`FLATTEN`**, `_compute_legal_actions` skips `expand_macros` entirely — each `CommitBuildPasture` is a
plain in-tree action in the engine-native action space, which is what a policy trains on and attaches priors
to. The tree is deeper (the cost macros were avoiding), but the prior keeps the search focused. This is the
required mode for PUCT (the constructor rejects PUCT + `MACRO`). **`SEQUENCE_PRIOR`** is a planned hybrid
that would keep a shallow tree by abstracting fencing into policy-sampled endpoint layouts while recovering
per-step training targets; it is **not implemented** and the constructor raises `NotImplementedError`.

---

## 10. The played move (`_select_action_with_temperature`)

After the budget is spent, the agent plays a move sampled from the **root's visit-count distribution** — not
the UCB/PUCT-best child. This is the AlphaZero "search with the selection rule, play by visit counts" split:
visit counts are the search-improved policy.

```python
def _select_action_with_temperature(self, root):
    items = list(root.children.items())
    if not items:
        raise RuntimeError(...)                      # no children: a real bug, surface it
    if self.temperature <= 0.0:                      # argmax with random tiebreak (agent RNG)
        best = max(c.visits for _, c in items)
        ties = [a for a, c in items if c.visits == best]
        return ties[int(self.rng.integers(len(ties)))]
    scaled = [(a, c.visits ** (1.0 / self.temperature)) for a, c in items]
    total = sum(s for _, s in scaled)
    if total == 0.0:                                 # all children 0 visits: defensive uniform fallback
        return items[int(self.rng.integers(len(items)))][0]
    probs = [s / total for _, s in scaled]
    idx = int(self.rng.choice(len(items), p=probs))
    return items[idx][0]
```

`probs[a] ∝ visits[a]^(1/T)`. The default `T = 0.2` is close to argmax (the most-visited child almost always
wins) but occasionally takes a strong second choice — useful for generating diverse self-play game records.
`T → 0` is exact argmax; `T = 1` samples proportional to visits. Sampling here uses the **agent** RNG
(`self.rng`), keeping the played move reproducible independently of the tree's internal randomness (§2.3).

The two guards are defensive. The empty-`items` `RuntimeError` fires only if the root somehow has no
children (a real bug worth surfacing). The `total == 0.0` (all-children-zero-visits) branch is effectively
unreachable in normal use: the constructor asserts `sims_per_move >= 1`, and a single simulation always
expands and backprops at least one child, giving it `visits >= 1`. (The mcts.py source comment cites
`sims_per_move == 0` as a trigger; that path is closed by the assert.)

`root_visit_distribution(root) -> {action: child.visits}` exposes the same counts for PUCT debugging now and
as the AlphaZero policy target (π) later.

---

## 11. Tree reuse, the three sharing modes, and running it

### 11.1 Tree reuse

Each real move begins with `find_or_create_node(state)` + `re_root` (§3.3), so simulations from earlier
moves that fall under the new root are **retained**. Across a 2-player game an agent with its own tree
re-roots roughly every 2 plies; a shared agent re-roots every ply. Macro replay (§9.2) skips re-rooting
entirely until the chain drains.

**`cap_total_sims` (default True).** Because tree reuse means a re-rooted node arrives with *inherited*
visits from the previous search, the default caps the **total** root visit count: the loop is
`while root.visits < sims_per_move: _simulate(root)`, so the effective per-decision budget is constant
regardless of how much was inherited (each `_simulate` adds exactly one root visit, so it always
terminates; if the inherited count already meets the cap, zero fresh sims run). With `cap_total_sims=False`
(the legacy behavior) the loop is instead `for _ in range(sims_per_move): _simulate(root)` — `sims_per_move`
*fresh* sims on top of whatever was inherited, so the effective budget varies move to move. Capping removes
the tree-reuse confound (a peaked PUCT tree inherits more effective sims at re-rooted nodes than a flatter
UCT tree); it is policy-agnostic (identical for UCT and PUCT) and is also the mode the search-tournament
driver (`archive/scripts/run_search_tournament.py`, since retired — see CLAUDE.md §2.3) and the web UI's
MCTS seat use.

### 11.2 The three sharing modes

`MCTSSearch` owns the tree, `MCTSAgent` owns the move loop — the split enables three configurations:

1. **Separate trees (default).** Each `MCTSAgent` gets its own `MCTSSearch`. Used for matches vs other agent
   types (heuristic, random, a different MCTS config).
2. **Shared tree via shared agent.** Pass the *same* `MCTSAgent` instance to both seats in `play_game`. Both
   seats share one tree and one agent config — roughly doubling effective sims for symmetric self-play.
3. **Shared tree via shared `MCTSSearch`.** Construct one `MCTSSearch`, pass it to multiple `MCTSAgent`s.
   Trees are shared but each seat can carry different agent-level config (`c_uct`, `temperature`,
   `sims_per_move`).

### 11.3 Running it via `play_game`

MCTS is an ordinary `Agent`, driven by the standard `play_game(initial, agents, dealer)` loop. The crucial
seam is the **dealer**: `play_game` queries `agents[d]` when `decider_of(state)` is a player, and the
`dealer` when it is `None` (the round-card reveal). In a real game the dealer is `env.resolve` from
`setup_env`, so both seats face one consistent (hidden) reveal order while the *agents* never see a nature
node. (MCTS's *internal* chance nodes, §8, are entirely separate: they model the reveal *inside the search
tree*; the real reveal between rounds is the dealer's job.)

The example below is illustrative (imports/names abbreviated). A plain UCT + V3 search vs the heuristic:

```python
from agricola.setup import setup_env
from agricola.agents.mcts import MCTSSearch, MCTSAgent
from agricola.agents.base import play_game

initial, env = setup_env(seed=0)
p0 = MCTSAgent(MCTSSearch(rng_seed=0), sims_per_move=500, c_uct=1.4)   # UCT, all-V3 defaults
p1 = HubrisHeuristicV3(seed=1, lookahead="turn")
final, trace = play_game(initial, (p0, p1), env.resolve)
```

For PUCT, supply a `policy_fn` and switch fencing to `FLATTEN` (and typically the regular legality wrapper).
The prior can be `uniform_policy` (the placeholder), or a trained combiner from
`build_combined_policy.build("unweighted")` / `build("awr")` (§5.3) — and `policy_fn=None` is just UCT.
The leaf evaluator below is the production NN wiring — note the model is passed *as `evaluator_config`*, the
adapter is `nn_evaluator_differential` (which already returns a P0-frame margin, so the leaf calls it once,
§6), and the **explicit** strict legality wrapper is built with `evaluator=` the NN ranker so its
harvest-feed cap ranks with the NN, not a hardcoded V3 (§7). Swap `legal_actions_fn` to
`restricted_legal_actions` to run PUCT over regular legality:

```python
search = MCTSSearch(
    rng_seed=0,
    # legal_actions_fn omitted → PUCT's mode-aware default: full, unrestricted legal_actions,
    # so the policy prior is the sole prune (§7/§12). (Pass an explicit strict wrapper for UCT.)
    evaluator_config=model,                  # the NN model rides in the config slot
    evaluator_fn=nn_evaluator_differential,  # already a P0-frame margin -> leaf calls it once (§6)
    leaf_value_scale=getattr(model, "value_scale", 1.0),
    policy_fn=build("unweighted"),           # build()/load_policy_fn per §5.3; or uniform_policy / None(=UCT)
    fence_mode=FenceMode.FLATTEN,            # required when policy_fn is set
)
agent = MCTSAgent(search, sims_per_move=500, c_uct=calibrated_c_puct, fpu_offset=0.25)
```

(`build` is a helper in the `scripts/nn/build_combined_policy.py` *script*, not an importable package — the
CLI loads it via `importlib`; `agricola.agents.nn.policy.load_policy_fn(checkpoints)` is the importable
library equivalent. See §5.3.)

`scripts/play_mcts_match.py` is the CLI that wires all of this and parallelizes matches. Its `--policy` flag
selects the prior: **`uct`** (no prior → UCT), `uniform` (the placeholder), or `combined:unweighted` /
`combined:awr` (the trained combiner, which it builds via `build_combined_policy.build(...)`). Note the
naming: `--policy uct` is the "no policy" value (it was renamed *from* `none` to avoid colliding with the
`unweighted`/`awr` *loss-variant* names — the BC loss weighting `--loss-weight unweighted|awr`, the
`build("unweighted"|"awr")` argument, and the `policy_*_unweighted` / `policy_*_awr` checkpoints, where
`unweighted` was itself the old `none`). `--fence-mode` and `--legality` round out the search config.
`scripts/nn/play_match.py` wires the NN value *leaf* the same way (model-as-`evaluator_config`,
`nn_evaluator_differential`, `model.value_scale` → `leaf_value_scale`), though it still ranks the strict
feed cap with V3 rather than injecting the NN ranker as `play_mcts_match.py` does. Both scripts construct
agents *in-process per worker* — an `MCTSSearch` holds nodes that back-reference it, so its transposition
table is not cleanly pickleable across processes.

---

## 12. Configuration reference

**Search-level (`MCTSSearch`):**

| Parameter | Default | Meaning |
|---|---|---|
| `legal_actions_fn` | **mode-aware**: PUCT → full unrestricted `legal_actions`; UCT → strict-restricted (RNG-bound, leaf-evaluator feed-cap) | Legality wrapper for every consultation (§7). Under PUCT the default enumerates the **full** set and lets the prior do all the pruning (`make_policy_fn`'s contract); under UCT it stays strict (no prior to soft-prune). Override with an explicit callable either way. |
| `evaluator_fn` | `evaluate_hubris_v3_differential` | The value black box `(state, player, config) -> float`; **must return a P0-frame margin** (§6). |
| `evaluator_config` | `DEFAULT_CONFIG_V3` | Third arg threaded into `evaluator_fn` (so it **carries the NN model** in the NN wiring, §6) and, for the *default* legality wrapper, the V3 config for the harvest-feed cap (§7). |
| `heuristic` | turn-lookahead `EvaluatorAgent` bound to `evaluator_fn` (V3 by default) | Plays the **greedy** fence macro with the *same* value function as the leaf — the NN under an NN leaf, not a hardcoded V3 (§9). |
| `n_random_fencing` | `4` | Random fence macros per trigger, in addition to 1 greedy (`MACRO` only). |
| `leaf_value_scale` | `1.0` | Divide leaf value before backprop; set to the NN's value scale for `c_uct` comparability (§6). |
| `policy_fn` | `None` | `None` → UCT; set → PUCT (§5). Requires `FenceMode.FLATTEN`. |
| `macro_policy_fn` | `None` | Optional fence-chain **sampler** (distinct from the PUCT `policy_fn`): when set, greedy macro-fencing is replaced by sampling chains from `(state, legal) -> {a: p}` — cheaper than the value-net greedy rollout; selection stays pure UCB. `MACRO` mode only (§9.1). |
| `fence_mode` | `FenceMode.MACRO` | `MACRO` (UCT) / `FLATTEN` (PUCT) / `SEQUENCE_PRIOR` (raises) (§9). |
| `rng_seed` | `0` | Seeds `search.rng` (macro sampling, all selection/chance tiebreaks). |

**Agent-level (`MCTSAgent`):**

| Parameter | Default | Meaning |
|---|---|---|
| `sims_per_move` | `500` | Simulations per real move (must be ≥ 1). |
| `c_uct` | `1.4` | Exploration constant; reused as `c_puct` in PUCT — **calibrate against `leaf_value_scale`**. |
| `fpu_offset` | `0.0` | FPU reduction for unvisited children; meaningful in PUCT, near-inert in UCT (§5.1). |
| `action_selection_temperature` | `0.2` | Visit-count softmax temperature for the played move (§10). |
| `cap_total_sims` | `True` | Cap *total* root visits (inherited + fresh) at `sims_per_move` instead of running that many fresh sims; equalizes the per-decision budget under tree reuse (§11.1). Set `False` for the legacy "always run `sims_per_move` *fresh* sims" behavior. On a fresh tree (move 1) the two are identical. |
| `rng_seed` | `0` | Seeds `self.rng` (top-level played-move sampling only). |

**Recommended PUCT / production (self-play data-gen) config.** With the mode-aware
defaults above, a production PUCT setup is mostly "set `policy_fn` + `fence_mode`, take
the rest of the defaults":

- `policy_fn` = the combined BC heads (`scripts/nn/build_combined_policy.build("unweighted")`
  or `"awr"`); `fence_mode = FenceMode.FLATTEN` (required whenever a policy is set).
- `evaluator_fn = nn_evaluator` (single-pass), `evaluator_config = <the NN model>`,
  `leaf_value_scale = model.value_scale` (§6).
- `legal_actions_fn` — **leave default** (full, no restriction; the policy is the sole
  prune). `cap_total_sims` — **leave default** (`True`).
- Tune `c_uct` / `sims_per_move`; set `action_selection_temperature` for the desired
  self-play exploration (this shapes the π target).
- **The caller must `eval()` the value model** (§6, §14); `make_policy_fn` already
  `eval()`s the policy heads. Run under `python -O` with `torch.set_num_threads(1)` per
  worker; `opt_config` caches are on by default (§14 / `SPEEDUPS.md`).

---

## 13. Invariants, edge cases, and design-vs-code notes

**Invariants the search relies on:**

- **One node per state.** Enforced by the transposition table via `find_or_create_node`; `MCTSNode` is
  identity-equal (`eq=False`) so it can key identity sets.
- **`decider` / `is_chance` are set at creation** from `decider_of(state)`; `decider=0` is a *frame label*
  for chance nodes, not a player.
- **Leaf values are P0-frame**, sign-flipped per node at backprop; chance nodes (`decider=0`) accumulate
  `+value` and parents flip as needed — so the routing flag `is_chance`, never `decider`, is what makes a
  chance node special.
- **Legality never empties a non-empty set** (`_safe_narrow` in the wrappers), so a non-terminal node always
  has ≥ 1 legal action. The `if not node._legal_actions: break` in `_simulate` is a defensive guard.
- **Backprop is path-only** (the `path` list), never `node.parents` — correct in a DAG because the
  simulation descended through exactly one parent at each step.

**Edge cases handled:**

- A fence chain that plays to game end → terminal endpoint node; `evaluate_leaf` handles it.
- An *empty* root child set raises `RuntimeError` (a real bug, surfaced loudly). The all-children-zero-visits
  uniform fallback in `_select_action_with_temperature` is defensive and effectively unreachable, since
  `sims_per_move >= 1` is asserted and one sim always gives a child `visits >= 1` (§10).
- A forced (single-candidate) reveal is routed through like any forced move; a node with one legal action is
  stepped through, not evaluated (§4).

**Design-vs-code notes (where this doc follows the code):**

- **`leaf_differential` was removed.** The leaf no longer differences a single-player evaluator; the
  `evaluator_fn` itself must return a P0-frame margin (the default is now `evaluate_hubris_v3_differential`),
  and terminal leaves use the exact `score()` margin regardless of evaluator (§6). The old flag's two
  use-cases — single-player scorers, and the already-differential NN — both collapse into "the evaluator
  owns the margin convention." Older design records (`design_docs/MCTS_DESIGN.md`, `design_docs/POLICY_PUCT_DESIGN.md`) and the C-era
  experiment logs still mention the flag.
- **Forced-move step-through makes UCT *not* byte-identical** to a pre-step-through engine. This is
  intentional (V queried only at real decisions/terminals) and applies to both modes.
- **FPU in UCT is largely a defensive guard.** The UCT path expands all unvisited children first, so
  `_select_via_ucb`'s `child.visits == 0` branch and `parent.visits > 0` fallback are dead in steady state;
  `fpu_offset` matters in PUCT, not UCT (§5.1). (`design_docs/MCTS_DESIGN.md` frames FPU as avoiding the sweep — the
  code does not.)
- **Trigger-2 action name is `"build_fences"`**, not `"fences"` as the design doc reads (§9.1); the engine
  emits `"build_fences"`.
- **`filter_implemented` is imported from `tests/test_utils.py`** (lazily, inside the hot methods) — a
  test-module dependency in production code, kept because that filter is the shared definition of
  "implemented" across the agent layer.
- **Heuristic dependencies are lazy-imported** (`_lazy_*` shims) so `import agricola.agents.mcts` stays
  cheap and avoids agent-module load-order coupling.

---

## 14. Speedups — how the performance work fits the search

The performance optimizations are catalogued in **`SPEEDUPS.md`** (each one's what / why / where) and
measured in **`PROFILING.md`** (the current *production* profile — an NN value leaf + multi-head policy
PUCT, the workload that matters for data generation). This section maps that work onto the search concepts
above, so you know which optimization touches which part of the algorithm. They are all behavior-preserving
(the policy-eval fix in point 3 is the one correctness change), so none of them alter *what the search
computes* — only how fast.

**The production leaf is a neural net, not V3.** Everything below assumes the data-gen configuration: an NN
value leaf (§6) + a trained `policy_fn` (§5.3), PUCT with `FenceMode.FLATTEN`. Its cost shape differs
completely from the V3-heuristic-leaf assumptions in the cost cheat-sheet (§4) — use PROFILING.md, not the
cheat-sheet, for real numbers.

1. **The transposition-table hash (§1.5, §3.1).** Keying nodes by `GameState` makes hashing a hot path —
   `find_or_create_node` hashes every state it looks up or inserts, and a frozen `GameState`'s default hash
   recurses through the whole nested tree. It was the **#1 self-time** until cached (`SPEEDUPS.md` S5): each
   state dataclass memoizes its hash, and because `step` shares most of a state's sub-objects *by reference*
   (the engine's `fast_replace`), a child state's hash reuses its parents' cached sub-hashes. The
   cheat-sheet's "~26 µs when hashed" row (§4) is now obsolete.

2. **The value black box (§6) — encode + forward.** An NN leaf's cost is encoding the state plus the
   forward pass. The encoder is heavily optimized (`SPEEDUPS.md` S10–S13: a `stop_is_legal` short-circuit,
   an index-writer rewrite, a swap-aware per-state memo, a device-query cache). The forward pass itself is
   near the CPU floor, but the search **depends on the caller** for one thing: the model must be in
   **`eval()` mode**. `evaluate_leaf` only *calls* `evaluator_fn`; it does not eval the model. A TRAIN-mode
   value net fires dropout on every leaf → noisy leaf values. `scripts/play_mcts_match.py` and `NNAgent`
   eval before search; a new caller must too.

3. **The policy black box (§5.3) — eval mode + a shared encode.** Same eval-mode requirement, but here it
   was a real **bug**: the policy heads loaded in TRAIN mode, so `policy_fn` returned **nondeterministic
   priors** (same state → priors differing ~0.05 per call). Fixed in `make_policy_fn`, which now `eval()`s
   the heads at assembly (`SPEEDUPS.md` "Inference eval()"). And the lazy-prior design this doc emphasizes
   (§5.3) compounds with the encoder memo: `_ensure_priors` computes each node's prior **once**, and the
   per-state memo (S12) lets the policy's perspective-0 encode **reuse the value leaf's encode** at decider-0
   nodes (deriving perspective-1 by a cheap block-swap), so the two black boxes share encoding work.

4. **The per-node legality cache (§7).** `_compute_legal_actions` runs the legality wrapper **once per
   unique node**; every later selection reads the cached `_legal_actions` field — the search-level
   memoization §7 already describes. That is why the wrapper's cost is paid per node, not per visit. (PUCT
   takes the full, unrestricted `legal_actions` and soft-prunes entirely via the prior, §7/§12.)

5. **What is NOT a cost in the production path.** Two things the cheat-sheet (§4) and older profiles flag as
   expensive do **not** apply to NN-leaf PUCT: **fence-macro generation** (§9) is MACRO-mode only — FLATTEN
   never runs it — and the **pasture-decomposition BFS** (`compute_pastures_from_arrays`), the #1 self-time
   in the old V3-leaf MACRO profile, is cold here (FLATTEN PUCT barely builds fences). See `SPEEDUPS.md` S9.

**Headline (PROFILING.md).** Together these landed a **~2× per-move speedup** on the production workload,
whose wall splits roughly **half NN inference / half engine+search**; the engine half is *diffuse* (no
single hotspot left after the hash cache). The next lever, if more is needed, is **leaf-batching** of the NN
forwards (a `_simulate`-level change), not further micro-optimization — `SPEEDUPS.md` Part 2.

---

*Companion docs: `ENGINE_IMPLEMENTATION.md` (the `step`/`legal_actions`/pending-stack/decider machinery this
search drives), `RULES.md` (game rules), and `nn_models/REGISTRY.md` (which value/policy checkpoints exist).
`design_docs/MCTS_DESIGN.md` and `design_docs/POLICY_PUCT_DESIGN.md` are the historical design records — superseded by this file for
understanding the code, retained for rationale and provenance.*
