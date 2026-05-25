"""MCTS agent for AgricolaBot.

Implements the design specified in **MCTS_DESIGN.md**. Brief summary:

- **Vanilla UCT** with **First-Play Urgency (FPU)** for unvisited children.
  No PUCT prior — the chain-initiating-action prior problem makes
  evaluator-derived priors mis-rank fencing/redev. Upgrade path is open
  (see §10.4).
- **DAG with transposition table** keyed on `GameState.__hash__`.
- **Path-only backprop** along the path built up by SELECT. `node.parents`
  is maintained for future DAG-full-backprop variants but is not read at
  backprop time.
- **Leaf evaluation via `evaluate_hubris_v3`** (no rollouts). Each sim
  pays one heuristic call at the freshly-expanded leaf.
- **Macro-fencing for both fencing trigger points** (worker placement +
  Farm Redev's fencing step). For each parent that exposes a fencing
  trigger, generate 1 greedy chain (heuristic-driven) + up to N random
  chains (uniform over `strict_restricted_legal_actions`), dedup by
  endpoint state, surface them as `MacroFencingAction` children. When MCTS
  picks a macro at the root, the agent commits to that macro's full action
  sequence and replays it across subsequent calls without re-running MCTS.
- **Strict-restricted legality** throughout (`strict_restricted_legal_actions`,
  with per-search RNG so the harvest-feed cap's random samples are
  deterministic per search instance).

See **MCTS_DESIGN.md §4-5** for data-structure and algorithm details.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from agricola.actions import Action, ChooseSubAction, PlaceWorker
from agricola.agents.base import decider_of
from agricola.constants import Phase
from agricola.engine import step
from agricola.pending import PendingBuildFences, PendingFarmRedevelopment
from agricola.state import GameState

# Lazy-imported to avoid coupling agent module load order (heuristic.py
# pulls in the full evaluator + score module). See `_lazy_*` helpers below.


# ---------------------------------------------------------------------------
# MacroFencingAction — MCTS-internal action type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MacroFencingAction:
    """MCTS-internal action representing a complete fencing chain.

    Stored in `MCTSNode.children` dicts as a key; never reaches the engine.
    The agent translates this into the actual engine action sequence via
    the parent's `macro_sequences[macro_action]` lookup. Lives in this
    module (NOT `actions.py`) — purely MCTS scaffolding.

    `label` distinguishes macros generated from the same parent ("greedy",
    "random_0", "random_1", ...). Two MacroFencingActions with the same
    label compare equal, which is what the dedup-at-generation pattern
    expects (each parent has exactly one greedy + N randoms).
    """
    label: str


# ---------------------------------------------------------------------------
# MCTSNode
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class MCTSNode:
    """One node in the MCTS DAG.

    `@dataclass(eq=False)` keeps Python's default object-identity `__eq__`
    and `__hash__`. Two MCTSNodes are equal iff they are the same object —
    which matches the "one node per unique state" invariant enforced by the
    transposition table. Identity equality also lets us use nodes as keys
    in identity-based sets (e.g., `re_root`'s reachability traversal).

    Field semantics:

    - `state`: the GameState this node represents (immutable, hashable).
    - `decider`: cached `decider_of(state)`. Used for UCB sign-flip and
      backprop frame conversion.
    - `parents`: list of parent MCTSNodes in the DAG. List (not set)
      because in-degree is small (1-3 typical) and identity-equality means
      a set would need custom hashing.
    - `children`: action → child MCTSNode. Populated lazily during EXPAND.
    - `action_from_parent`: one of possibly several incoming edges; used
      for debugging only.
    - `search`: back-reference to the owning `MCTSSearch` for config access
      (legal_actions_fn, evaluator, n_random_fencing).
    - `visits`, `value_sum`: running statistics. `value_sum` is stored in
      THIS node's decider's frame; `mean_q` reports it directly.
    - `macro_sequences`: populated only if this node generated macro
      children (see `MCTSSearch.expand_macros`). Keyed by MacroFencingAction;
      value is the full engine-action sequence including the leading
      trigger action.
    - `_legal_actions` / `_unvisited_actions`: per-node cache, lazy. The
      primary mechanism for `legal_actions` reuse during MCTS — direct
      field access (~10ns) on every UCT descent.
    """
    state: GameState
    decider: int
    search: "MCTSSearch"
    parents: list["MCTSNode"] = field(default_factory=list)
    children: dict[Action, "MCTSNode"] = field(default_factory=dict)
    action_from_parent: Optional[Action] = None
    visits: int = 0
    value_sum: float = 0.0
    macro_sequences: dict[MacroFencingAction, list[Action]] = field(default_factory=dict)
    _legal_actions: Optional[list[Action]] = None
    _unvisited_actions: Optional[set] = None

    @property
    def mean_q(self) -> float:
        return self.value_sum / self.visits if self.visits > 0 else 0.0

    def is_terminal(self) -> bool:
        return self.state.phase == Phase.BEFORE_SCORING

    def has_legal_actions(self) -> bool:
        if self._legal_actions is None:
            self._compute_legal_actions()
        return bool(self._legal_actions)

    def has_unvisited(self) -> bool:
        if self._unvisited_actions is None:
            self._compute_legal_actions()
        return bool(self._unvisited_actions)

    def _compute_legal_actions(self) -> None:
        """Populate the per-node legal-action cache (lazy).

        At a terminal node, both caches are empty. Otherwise, the raw legal
        actions are filtered through the search's `legal_actions_fn`
        (typically `strict_restricted_legal_actions`), then fencing
        triggers are replaced with macro-action stand-ins via
        `search.expand_macros`. Macro expansion creates the macro CHILD
        nodes immediately as a side effect.
        """
        if self.is_terminal():
            self._legal_actions = []
            self._unvisited_actions = set()
            return
        # Lazy import to avoid loading test scaffolding at module level.
        from tests.test_utils import filter_implemented
        raw = filter_implemented(self.search.legal_actions_fn(self.state))
        self._legal_actions = self.search.expand_macros(self, raw)
        self._unvisited_actions = set(self._legal_actions)


# ---------------------------------------------------------------------------
# MCTSSearch — owns the transposition table + search-level config
# ---------------------------------------------------------------------------

class MCTSSearch:
    """The MCTS DAG and its search-level configuration.

    One MCTSSearch instance manages one tree. Two `MCTSAgent`s sharing the
    same MCTSSearch share the tree (used for shared-tree self-play). An
    MCTSAgent with its own MCTSSearch maintains an independent tree
    (used for matches vs other agent types).

    Configuration on the search (not the agent):
      - `legal_actions_fn`: every legality consultation routes through this.
        Default is a strict-restricted callable bound to this search's RNG.
      - `evaluator_config`: HeuristicConfigV3 used for leaf evaluation AND
        by the harvest-feed cap's V3 ranking.
      - `n_random_fencing`: how many random macros to generate per fencing
        trigger (in addition to the 1 greedy). Default 4.
      - `rng`: numpy Generator. Used by `expand_macros` (random chain
        sampling) and dedup tiebreaks.
      - `heuristic`: a `HubrisHeuristicV3` instance used to play the
        greedy macro-fencing chain. Constructed once at init.

    Agent-level configuration (sims_per_move, c_uct, fpu_offset,
    action-selection temperature) lives on `MCTSAgent`, not here.
    """

    def __init__(
        self,
        *,
        legal_actions_fn=None,
        evaluator_config=None,
        n_random_fencing: int = 4,
        rng_seed: int = 0,
    ):
        self.transpositions: dict[GameState, MCTSNode] = {}
        self.root: Optional[MCTSNode] = None
        self.n_random_fencing = int(n_random_fencing)
        self.rng = np.random.default_rng(rng_seed)

        # Resolve evaluator config (DEFAULT_CONFIG_V3 if not specified).
        if evaluator_config is None:
            evaluator_config = _lazy_default_config_v3()
        self.evaluator_config = evaluator_config

        # Resolve legality function. Default: a strict wrapper bound to this
        # search's RNG so the harvest-feed cap's random samples are
        # deterministic per search instance (rather than sharing the
        # module-level default RNG across all MCTSSearch instances).
        if legal_actions_fn is None:
            legal_actions_fn = _lazy_make_strict_legal(
                config=self.evaluator_config, rng=self.rng,
            )
        self.legal_actions_fn = legal_actions_fn

        # Heuristic agent used to play greedy macro-fencing chains.
        # Constructed once; reused. Uses the same legal_actions_fn so its
        # internal lookahead sees the same action-pruning the tree does.
        HubrisHeuristicV3 = _lazy_hubris_v3_class()
        self.heuristic = HubrisHeuristicV3(
            config=self.evaluator_config,
            seed=rng_seed,
            lookahead="turn",
            legal_actions_fn=self.legal_actions_fn,
        )

    # ---- Transposition table maintenance ---------------------------------

    def find_or_create_node(
        self,
        state: GameState,
        *,
        parent: Optional[MCTSNode] = None,
        action_from_parent: Optional[Action] = None,
    ) -> MCTSNode:
        """Look up or create the MCTSNode for `state`.

        If a node for this state already exists, return it and (if `parent`
        is supplied) link the new parent → child edge. The transposition
        table is the single source of truth: every state has at most one
        node.
        """
        existing = self.transpositions.get(state)
        if existing is not None:
            if parent is not None:
                self.add_edge(parent, existing, action_from_parent)
            return existing
        node = MCTSNode(
            state=state,
            decider=decider_of(state),
            search=self,
            action_from_parent=action_from_parent,
        )
        self.transpositions[state] = node
        if parent is not None:
            self.add_edge(parent, node, action_from_parent)
        return node

    def add_edge(
        self, parent: MCTSNode, child: MCTSNode, action: Optional[Action],
    ) -> None:
        """Single choke point for DAG edge creation.

        Sets `parent.children[action] = child` and appends to
        `child.parents` if the parent isn't already there. List membership
        uses identity equality (MCTSNode is `eq=False`).
        """
        if action is not None:
            parent.children[action] = child
        if parent not in child.parents:
            child.parents.append(parent)

    def re_root(self, new_root: MCTSNode) -> None:
        """Designate `new_root` as the new search root and prune the table.

        Walks the live subtree from `new_root`, drops every transposition
        entry not reachable from there. Idempotent if `new_root` is already
        the current root.
        """
        if new_root is self.root:
            return
        reachable_ids: set[int] = set()
        queue = [new_root]
        while queue:
            node = queue.pop()
            nid = id(node)
            if nid in reachable_ids:
                continue
            reachable_ids.add(nid)
            queue.extend(node.children.values())
        self.transpositions = {
            s: n for s, n in self.transpositions.items()
            if id(n) in reachable_ids
        }
        self.root = new_root

    # ---- Leaf evaluation -------------------------------------------------

    def evaluate_leaf(self, state: GameState) -> float:
        """Leaf value in P0's reference frame.

        At terminal states (`Phase.BEFORE_SCORING`), `evaluate_hubris_v3`
        already returns the margin (`own − opponent`) via
        `_terminal_margin_value`. Return it directly. Subtracting at
        terminal would double the value (since at terminal e1 = -e0).

        Mid-game, `evaluate_hubris_v3(state, p)` returns player p's
        heuristic quality (one-player value). Subtract to get a margin
        in P0's frame.
        """
        evaluate_hubris_v3 = _lazy_evaluate_hubris_v3()
        if state.phase == Phase.BEFORE_SCORING:
            return evaluate_hubris_v3(state, 0, self.evaluator_config)
        return (
            evaluate_hubris_v3(state, 0, self.evaluator_config)
            - evaluate_hubris_v3(state, 1, self.evaluator_config)
        )

    # ---- Macro-fencing ---------------------------------------------------

    def expand_macros(
        self, parent_node: MCTSNode, raw_actions: list[Action],
    ) -> list[Action]:
        """Replace fencing-trigger actions in `raw_actions` with macros.

        For each fencing trigger present in the input action list, generate
        up to `1 + n_random_fencing` distinct MacroFencingAction children
        (deduplicated by endpoint state). Side effects: (a) creates the
        macro child nodes via `find_or_create_node` so they're wired up
        before MCTS visits them, and (b) writes each macro's full engine-
        action sequence to `parent_node.macro_sequences`.

        Returns the modified action list with trigger actions replaced by
        their macros. Non-fencing actions are preserved unchanged.

        Per MCTS_DESIGN §3.6, two trigger points are handled uniformly:
          1. `PlaceWorker("fencing")` at empty stack.
          2. `ChooseSubAction("fences")` at `PendingFarmRedevelopment`.
        """
        triggers = self._find_fencing_triggers(parent_node.state, raw_actions)
        if not triggers:
            return raw_actions
        other_actions = [a for a in raw_actions if a not in triggers]
        macro_actions: list[Action] = []
        for trigger_action in triggers:
            macros = self._generate_fencing_macros(
                parent_node.state, trigger_action,
            )
            for label, sequence, endpoint_state in macros:
                macro_action = MacroFencingAction(label=label)
                parent_node.macro_sequences[macro_action] = sequence
                self.find_or_create_node(
                    endpoint_state,
                    parent=parent_node,
                    action_from_parent=macro_action,
                )
                macro_actions.append(macro_action)
        return other_actions + macro_actions

    def _find_fencing_triggers(
        self, state: GameState, raw_actions: list[Action],
    ) -> list[Action]:
        """Return actions in `raw_actions` that initiate a fencing chain.

        Two trigger points:
          1. `PlaceWorker("fencing")` at empty stack — the worker-placement
             entry to the Fencing space.
          2. `ChooseSubAction("build_fences")` at `PendingFarmRedevelopment`
             — the optional second step of Farm Redev.

        (Spec note: MCTS_DESIGN §3.6 reads `"fences"` for trigger 2; the
        engine actually emits `"build_fences"` per
        `_choose_subaction_farm_redevelopment`. We follow the engine.)
        """
        triggers: list[Action] = []
        farm_redev_on_top = (
            state.pending_stack
            and isinstance(state.pending_stack[-1], PendingFarmRedevelopment)
        )
        for a in raw_actions:
            if isinstance(a, PlaceWorker) and a.space == "fencing":
                triggers.append(a)
            elif (
                isinstance(a, ChooseSubAction)
                and a.name == "build_fences"
                and farm_redev_on_top
            ):
                triggers.append(a)
        return triggers

    def _generate_fencing_macros(
        self, parent_state: GameState, trigger_action: Action,
    ):
        """Generate up to `1 + n_random_fencing` distinct macros for one
        trigger. Returns a list of `(label, sequence, endpoint_state)`.

        Macros are dedup'd by endpoint state WITHIN THIS PARENT. The
        greedy macro is always added first (label='greedy'). Random macros
        are sampled via uniform random over `strict_restricted_legal_actions`
        on each step of the chain; their labels are 'random_0', 'random_1',
        ... in the order they are added (NOT the order they were attempted).

        Three phases per macro:

          1. **Entry**: apply the trigger action; if the trigger pushed a
             wrapper pending (PendingFencing for trigger 1) instead of
             PendingBuildFences directly, auto-step through any singleton
             decisions of the decider until PBF is on top.
             - Trigger 1 (PlaceWorker(fencing)): trigger pushes PendingFencing;
               ChooseSubAction("build_fences") is a singleton that lands us
               in PBF.
             - Trigger 2 (ChooseSubAction("build_fences") at PendingFarmRedev):
               trigger pushes PBF directly; no entry singletons needed.

          2. **Chain body**: while PBF is on top, pick one action per step
             via the policy (greedy = heuristic; random = uniform random
             over `legal_actions_fn`). Loop exits when PBF pops (its Stop).

          3. **Exit / wrapper drain**: if the trigger pushed a wrapper
             pending (trigger 1 only), auto-step through any remaining
             singleton decisions of the decider so the wrapper's Stop is
             part of the recorded macro. For trigger 2 we don't drain —
             control returns to PendingFarmRedev, and the agent's next
             non-fencing decision belongs to normal MCTS.

        The "PendingBuildFences on top" predicate (`_pbf_on_top`) is the
        chain-body termination condition, matching MCTS_DESIGN §5.4 exactly.
        Wrapper-pending handling is split into the entry/exit phases so
        the body predicate stays simple.
        """
        from tests.test_utils import filter_implemented

        state_after_trigger = step(parent_state, trigger_action)
        decider = decider_of(parent_state)
        # If the trigger landed us directly in PBF, no wrapper to drain on
        # exit. Otherwise the entry phase auto-singletons us into PBF and
        # the exit phase auto-singletons out of the wrapper.
        direct_pbf = self._pbf_on_top(state_after_trigger)

        # Endpoint-state -> (label, sequence) — dedup choke point.
        macros: dict[GameState, tuple[str, list[Action]]] = {}

        target = 1 + self.n_random_fencing
        max_attempts = max(1, self.n_random_fencing) * 3 + 1
        # attempt 0 = greedy; attempts 1+ = random samples.
        for attempt in range(max_attempts):
            if attempt > 0 and len(macros) >= target:
                break
            greedy = (attempt == 0)

            state = state_after_trigger
            seq: list[Action] = [trigger_action]

            # 1. Entry phase
            if not direct_pbf:
                state, seq, entered = self._enter_pbf(state, seq, decider)
                if not entered:
                    # Couldn't reach PBF (decider handed off, or a
                    # multi-option non-PBF decision appeared). Abandon
                    # this attempt — record the endpoint without body.
                    if greedy:
                        macros[state] = ("greedy", seq)
                    continue

            # 2. Chain body
            state, seq = self._run_pbf_body(state, seq, decider, greedy=greedy)

            # 3. Exit phase: drain wrapper singletons only if the trigger
            # pushed a wrapper.
            if not direct_pbf:
                state, seq = self._drain_wrapper(state, seq, decider)

            if state in macros:
                continue
            label = "greedy" if greedy else f"random_{len(macros) - 1}"
            macros[state] = (label, seq)

        return [
            (label, seq, end_state)
            for end_state, (label, seq) in macros.items()
        ]

    def _pbf_on_top(self, state: GameState) -> bool:
        """True iff `PendingBuildFences` is the top of the pending stack.
        This is the chain-body termination predicate per MCTS_DESIGN §5.4.
        """
        return bool(
            state.pending_stack
            and isinstance(state.pending_stack[-1], PendingBuildFences)
        )

    def _enter_pbf(self, state, seq, decider):
        """Auto-step through singleton decisions until PBF is on top.

        Returns `(state, seq, entered)`. `entered` is True if PBF is on
        top at exit; False if we bailed (decider handed off, game ended,
        or a multi-option non-PBF decision appeared — none of which should
        happen in normal play for either supported trigger).
        """
        from tests.test_utils import filter_implemented
        while True:
            if state.phase == Phase.BEFORE_SCORING:
                return state, seq, False
            if decider_of(state) != decider:
                return state, seq, False
            if self._pbf_on_top(state):
                return state, seq, True
            acts = filter_implemented(self.legal_actions_fn(state))
            if len(acts) != 1:
                # Multi-option pre-PBF decision — surprising; bail.
                return state, seq, False
            seq.append(acts[0])
            state = step(state, acts[0])

    def _run_pbf_body(self, state, seq, decider, *, greedy):
        """Play one action per step while PBF is on top.

        Greedy policy uses `self.heuristic`; random policy uses uniform
        random over `legal_actions_fn`. Loop exits when PBF is no longer
        on top (Stop applied), the game ends, or the decider hands off.
        """
        from tests.test_utils import filter_implemented
        while (
            state.phase != Phase.BEFORE_SCORING
            and decider_of(state) == decider
            and self._pbf_on_top(state)
        ):
            if greedy:
                a = self.heuristic(state)
            else:
                acts = filter_implemented(self.legal_actions_fn(state))
                if not acts:
                    break
                a = acts[int(self.rng.integers(len(acts)))]
            seq.append(a)
            state = step(state, a)
        return state, seq

    def _drain_wrapper(self, state, seq, decider):
        """Auto-step through singletons after PBF pops.

        Used by trigger 1 (PlaceWorker) only — drains the outer
        PendingFencing's mandatory Stop singleton so the macro's recorded
        sequence ends with control fully handed off (rather than leaving
        a singleton Stop for MCTS to burn sims on).

        Trigger 2 does NOT call this: after PBF pops we're back at
        PendingFarmRedev, where the agent's next decisions (renovate-vs-
        stop, etc.) are legitimate MCTS-managed choices, not deterministic
        wrapper drains.
        """
        from tests.test_utils import filter_implemented
        while (
            state.phase != Phase.BEFORE_SCORING
            and decider_of(state) == decider
            and state.pending_stack
        ):
            acts = filter_implemented(self.legal_actions_fn(state))
            if len(acts) != 1:
                break
            seq.append(acts[0])
            state = step(state, acts[0])
        return state, seq


# ---------------------------------------------------------------------------
# MCTSAgent — the Agent-protocol-compliant caller-facing object
# ---------------------------------------------------------------------------

class MCTSAgent:
    """MCTS agent implementing the Agent protocol.

    Three usage patterns (see MCTS_DESIGN §3.10, §6):

    1. **Separate trees**: each MCTSAgent gets its own MCTSSearch. Used
       for matches vs other agent types (heuristic, random, or different
       MCTS configurations).

    2. **Shared tree via shared agent**: pass the same MCTSAgent instance
       to both slots in `play_game`. Both seats use the same tree AND the
       same agent-level config. Used for symmetric self-play.

    3. **Shared tree via shared MCTSSearch**: construct one MCTSSearch and
       pass it to multiple MCTSAgent instances. Trees share; agent-level
       config (c_uct, temperature, sims_per_move) can differ per seat.
    """

    def __init__(
        self,
        search: MCTSSearch,
        *,
        sims_per_move: int = 500,
        c_uct: float = 1.4,
        fpu_offset: float = 0.0,
        action_selection_temperature: float = 0.2,
        rng_seed: int = 0,
    ):
        assert sims_per_move >= 1, "sims_per_move must be at least 1"
        self.search = search
        self.sims_per_move = int(sims_per_move)
        self.c_uct = float(c_uct)
        self.fpu_offset = float(fpu_offset)
        self.temperature = float(action_selection_temperature)
        # Agent-level RNG. Used for top-level action selection (softmax
        # sampling) only. Tree-internal randomness (macro generation,
        # expansion tiebreaks) uses the search's RNG — clear separation.
        self.rng = np.random.default_rng(rng_seed)
        self._pending_macro_actions: list[Action] = []

    # ---- The Agent protocol ---------------------------------------------

    def __call__(self, state: GameState) -> Action:
        # Mid-macro: just pop the next queued engine action. No MCTS, no
        # re-root — the tree stays as-is until the macro chain completes.
        if self._pending_macro_actions:
            return self._pending_macro_actions.pop(0)

        root = self.search.find_or_create_node(state)
        self.search.re_root(root)

        for _ in range(self.sims_per_move):
            self._simulate(root)

        action = self._select_action_with_temperature(root)

        if isinstance(action, MacroFencingAction):
            # Look up the sequence on THIS parent (root.macro_sequences).
            # Parent-keyed storage: two parents whose macros converge on
            # the same endpoint each retain their own sequence.
            sequence = root.macro_sequences[action]
            # sequence[0] is the trigger action (returned now).
            # sequence[1:] are the chain commits + Stop (queued).
            self._pending_macro_actions.extend(sequence[1:])
            return sequence[0]

        return action

    # ---- One simulation --------------------------------------------------

    def _simulate(self, root: MCTSNode) -> None:
        """Run one MCTS simulation rooted at `root`. See MCTS_DESIGN §5.1."""
        path: list[MCTSNode] = [root]
        node = root

        # ---------- SELECT ----------
        # Descend through fully-expanded nodes via UCB. Stop when we hit a
        # terminal, a node with unvisited children, or (defensively) a
        # node with no legal actions.
        while True:
            if node.is_terminal():
                break
            # Force cache populate so we can check unvisited cheaply.
            if node._legal_actions is None:
                node._compute_legal_actions()
            if not node._legal_actions:
                # Defensive: no legal actions at a non-terminal node.
                # Shouldn't happen with strict-restricted (which never
                # empties a non-empty input set), but degenerate states
                # are handled gracefully.
                break
            if node._unvisited_actions:
                # Has unvisited children → stop here and EXPAND below.
                break
            action = self._select_via_ucb(node)
            node = node.children[action]
            path.append(node)

        # ---------- EXPAND ----------
        if not node.is_terminal() and node._unvisited_actions:
            action = self._pick_unvisited_action(node)
            node._unvisited_actions.discard(action)
            if isinstance(action, MacroFencingAction):
                # Macro children were pre-created during expand_macros.
                child = node.children[action]
                # Even though pre-created, we still need to register parent
                # linkage if this descent path arrived at `node` via a
                # different parent. add_edge dedups parents.
                self.search.add_edge(node, child, action)
            else:
                child_state = step(node.state, action)
                child = self.search.find_or_create_node(
                    child_state, parent=node, action_from_parent=action,
                )
            path.append(child)
            node = child

        # ---------- EVALUATE ----------
        leaf_value_p0 = self.search.evaluate_leaf(node.state)

        # ---------- BACKPROP ----------
        # Along the path built up by SELECT — NOT via node.parents. In a
        # DAG, this descent went through exactly one parent at each step;
        # the path records that choice. Other paths to the same node
        # accumulate into the same node.value_sum as they're explored.
        for n in path:
            if n.decider == 0:
                n.value_sum += leaf_value_p0
            else:
                n.value_sum -= leaf_value_p0
            n.visits += 1

    # ---- UCB selection ---------------------------------------------------

    def _select_via_ucb(self, parent: MCTSNode) -> Action:
        """Return the action whose child has the highest UCB.

        Random tiebreak on equal UCBs (rare but possible at FPU-tied
        unvisited children when parent.visits == 0). Uses the search's RNG
        for the tiebreak so MCTS runs are deterministic per search seed.
        """
        parent_mean_q = parent.mean_q if parent.visits > 0 else 0.0
        log_term = math.log(parent.visits + 1)
        best_score = -float("inf")
        best_actions: list[Action] = []
        for action, child in parent.children.items():
            if child.visits == 0:
                # FPU: virtual visit count = 1, virtual Q = parent.mean_q.
                # Apply fpu_offset (default 0 — try small negatives to bias
                # toward exploitation).
                score = parent_mean_q - self.fpu_offset + self.c_uct * math.sqrt(log_term)
            else:
                child_q = child.value_sum / child.visits
                # Sign-flip if child decider differs from parent decider.
                if child.decider != parent.decider:
                    child_q = -child_q
                score = child_q + self.c_uct * math.sqrt(log_term / child.visits)
            if score > best_score:
                best_score = score
                best_actions = [action]
            elif score == best_score:
                best_actions.append(action)
        if len(best_actions) == 1:
            return best_actions[0]
        return best_actions[int(self.search.rng.integers(len(best_actions)))]

    def _pick_unvisited_action(self, node: MCTSNode) -> Action:
        """Pick a uniformly-random unvisited action from `node`."""
        unvisited = list(node._unvisited_actions)
        return unvisited[int(self.search.rng.integers(len(unvisited)))]

    # ---- Action selection at the top -------------------------------------

    def _select_action_with_temperature(self, root: MCTSNode) -> Action:
        """Pick the next engine-facing action from root's visit counts.

        Softmax over visit counts with temperature: `probs[a] ∝ counts[a]^(1/T)`.
        T → 0 approaches argmax; T = 1 samples proportional to counts. Default
        T = 0.2: close to argmax but allows occasional second-place picks for
        diverse game records.

        Defensive: if all root children have zero visits (sims_per_move ==
        0, or some degenerate state), fall back to uniform-random over
        children.
        """
        items = list(root.children.items())
        if not items:
            raise RuntimeError(
                f"MCTSAgent has no children to choose from at the root. "
                f"phase={root.state.phase}, decider={root.decider}, "
                f"sims_per_move={self.sims_per_move}"
            )
        if self.temperature <= 0.0:
            best = max(c.visits for _, c in items)
            ties = [a for a, c in items if c.visits == best]
            return ties[int(self.rng.integers(len(ties)))]
        scaled = [(a, c.visits ** (1.0 / self.temperature)) for a, c in items]
        total = sum(s for _, s in scaled)
        if total == 0.0:
            # All visits zero — uniform random fallback.
            return items[int(self.rng.integers(len(items)))][0]
        probs = [s / total for _, s in scaled]
        idx = int(self.rng.choice(len(items), p=probs))
        return items[idx][0]


# ---------------------------------------------------------------------------
# Lazy-import shims
# ---------------------------------------------------------------------------
#
# Importing `agricola.agents.heuristic` (or `agricola.agents.restricted`'s
# strict factory) at module load time would force evaluator + score-module
# loads. Defer until first use so a bare `import agricola.agents.mcts`
# stays cheap. Cached via global module-level slots.

_DEFAULT_CONFIG_V3 = None
_EVALUATE_HUBRIS_V3 = None
_HUBRIS_V3_CLASS = None


def _lazy_default_config_v3():
    global _DEFAULT_CONFIG_V3
    if _DEFAULT_CONFIG_V3 is None:
        from agricola.agents.heuristic import DEFAULT_CONFIG_V3
        _DEFAULT_CONFIG_V3 = DEFAULT_CONFIG_V3
    return _DEFAULT_CONFIG_V3


def _lazy_evaluate_hubris_v3():
    global _EVALUATE_HUBRIS_V3
    if _EVALUATE_HUBRIS_V3 is None:
        from agricola.agents.heuristic import evaluate_hubris_v3
        _EVALUATE_HUBRIS_V3 = evaluate_hubris_v3
    return _EVALUATE_HUBRIS_V3


def _lazy_hubris_v3_class():
    global _HUBRIS_V3_CLASS
    if _HUBRIS_V3_CLASS is None:
        from agricola.agents.heuristic import HubrisHeuristicV3
        _HUBRIS_V3_CLASS = HubrisHeuristicV3
    return _HUBRIS_V3_CLASS


def _lazy_make_strict_legal(*, config, rng):
    from agricola.agents.restricted import make_strict_restricted_legal_actions
    return make_strict_restricted_legal_actions(config=config, rng=rng)
