"""MCTS agent for AgricolaBot.

Implements the design specified in **MCTS_DESIGN.md**. Brief summary:

- **Vanilla UCT** with **First-Play Urgency (FPU)** for unvisited children,
  or **PUCT** when a `policy_fn` is supplied to `MCTSSearch` — AlphaZero
  prior-weighted selection. PUCT requires FLATTEN fencing (see `FenceMode`
  and POLICY_PUCT_DESIGN.md); `policy_fn=None` selects UCT, PUCT otherwise.
  Both **step through forced (singleton) moves** before evaluating the leaf,
  so V is queried at real decisions, not forced mid-action states.
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
from enum import Enum
from typing import Optional

import numpy as np

from agricola.actions import Action, ChooseSubAction, PlaceWorker
from agricola.agents.base import EvaluatorAgent, decider_of
from agricola.constants import Phase
from agricola.engine import step
from agricola.pending import PendingBuildFences, PendingFarmRedevelopment
from agricola.scoring import score
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
# FenceMode + uniform policy (PUCT support)
# ---------------------------------------------------------------------------

class FenceMode(Enum):
    """How fencing is handled in the search tree.

    - ``MACRO``: collapse a fence layout into greedy + random
      ``MacroFencingAction`` children (today's UCT behavior). **UCT-only** —
      macros aren't engine actions, so a policy can't attach priors to them.
    - ``FLATTEN``: bypass macros; each ``CommitBuildPasture`` is a plain tree
      action (deeper tree, engine-native action space). The v1 PUCT mode.
    - ``SEQUENCE_PRIOR``: policy-sampled fence-layout abstraction (c3; not yet
      implemented). See POLICY_PUCT_DESIGN.md §8.
    """
    MACRO = "macro"
    FLATTEN = "flatten"
    SEQUENCE_PRIOR = "sequence_prior"


def uniform_policy(state: GameState, legal_actions: list[Action]) -> dict[Action, float]:
    """A uniform ``policy_fn`` for PUCT: equal prior over all legal actions.

    The c0 placeholder prior — exercises the PUCT machinery before a trained
    policy exists. Returns ``{}`` for an empty action set.
    """
    n = len(legal_actions)
    if n == 0:
        return {}
    p = 1.0 / n
    return {a: p for a in legal_actions}


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
    # Chance-node (round-card reveal) state. `is_chance` is True iff this node is
    # a nature decision (decider_of(state) is None); for chance nodes `decider`
    # is set to 0 as a P0 value-frame label (NOT a real player), so the backprop
    # / UCB sign-flip math is unchanged. `chance_counts` is the per-outcome
    # round-robin counter — NOT child.visits, which a shared DAG child inflates.
    # See HIDDEN_INFO_DESIGN.md §8.
    is_chance: bool = False
    chance_counts: dict[Action, int] = field(default_factory=dict)
    _legal_actions: Optional[list[Action]] = None
    _unvisited_actions: Optional[set] = None
    # PUCT: per-action prior P(s,·) over `_legal_actions`, set lazily by
    # `_ensure_priors` on the first selection from a multi-option node (NOT at
    # expansion / in `_compute_legal_actions`). None for never-selected nodes,
    # chance nodes, singletons (forced moves short-circuit before priors), and
    # all UCT runs.
    _action_priors: Optional[dict] = None

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
        # Macro-collapse fencing only in MACRO mode (UCT). FLATTEN / SEQUENCE_PRIOR
        # leave fencing as plain per-pasture CommitBuildPasture actions.
        if self.search.fence_mode is FenceMode.MACRO:
            self._legal_actions = self.search.expand_macros(self, raw)
        else:
            self._legal_actions = raw
        self._unvisited_actions = set(self._legal_actions)

    def _ensure_priors(self) -> None:
        """Compute the PUCT prior P(s,·) over `_legal_actions`, once and lazily,
        at the first selection from this node (NOT at leaf creation). Skipped for
        chance nodes and when no policy is set; never reached for a forced
        (singleton) node (`_select_via_puct` short-circuits those). A future
        shared value+policy net would populate this at leaf-eval time instead,
        paired with the value in one forward pass (POLICY_PUCT_DESIGN.md §9.1).
        """
        if (self._action_priors is None
                and self.search.policy_fn is not None
                and not self.is_chance):
            if self._legal_actions is None:
                self._compute_legal_actions()
            self._action_priors = self.search.policy_fn(self.state, self._legal_actions)


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
        evaluator_fn=None,
        heuristic=None,
        n_random_fencing: int = 4,
        rng_seed: int = 0,
        leaf_value_scale: float = 1.0,
        policy_fn=None,
        macro_policy_fn=None,
        fence_mode=None,
    ):
        """Build an MCTSSearch.

        Defaults configure a fully-V3 search (V3 leaf evaluator + V3
        heuristic for greedy macros + V3-aware strict-restricted legality).
        Override `evaluator_fn` + `heuristic` to use a different leaf
        evaluator / different heuristic for macros (e.g., V1 for
        head-to-head experiments).

        - `evaluator_config`: dataclass holding the evaluator's tunable
          parameters. Used to construct the default `heuristic` AND
          passed through to `evaluator_fn(state, player_idx, config)`.
          Defaults to `DEFAULT_CONFIG_V3` when neither this nor
          `heuristic` is supplied.
        - `evaluator_fn`: callable `(state, player_idx, config) -> float`
          used at MCTS leaves. It must already return a P0-frame *margin*
          (own − opponent); the leaf calls it once, never differencing
          itself. Defaults to the differential V3 evaluator
          (`evaluate_hubris_v3_differential`). For an NN leaf pass
          `nn_evaluator_differential` (2-pass, lower variance) or
          `nn_evaluator` (1-pass, faster) — both already P0-frame margins.
        - `heuristic`: a pre-constructed heuristic agent used to play
          the greedy macro-fencing chain. Defaults to a
          `HubrisHeuristicV3(config=evaluator_config, ...)`. Pass an
          arbitrary agent to use a different policy for macros.
        - `legal_actions_fn`: every legality consultation routes through
          this. Defaults to a strict-restricted wrapper bound to this
          search's RNG using `evaluator_config` for the harvest-feed cap's
          ranking. NB: the wrapper's cap uses V3 internally regardless of
          what evaluator_fn you supply — the cap is a legality concern,
          not an evaluation one.
        - `leaf_value_scale`: divide every leaf value by this before
          backprop, so leaf values feed UCB on a unit-ish scale. Defaults
          to 1.0 (no-op — correct for V3, whose values are already on the
          c_uct-calibrated margin scale). For an NN leaf evaluator, pass
          the model's measured `value_scale` (std of its leaf differential)
          so a single `c_uct` is comparable across value heads of
          different magnitude. See FIRST_NN.md Experiment P2.
        """
        self.transpositions: dict[GameState, MCTSNode] = {}
        self.root: Optional[MCTSNode] = None
        self.leaf_value_scale = float(leaf_value_scale)
        self.n_random_fencing = int(n_random_fencing)
        self.rng = np.random.default_rng(rng_seed)

        # Resolve evaluator config (DEFAULT_CONFIG_V3 if not specified).
        if evaluator_config is None:
            evaluator_config = _lazy_default_config_v3()
        self.evaluator_config = evaluator_config

        # Resolve evaluator function. Default: the DIFFERENTIAL V3 evaluator,
        # so the leaf gets a P0-frame margin from a single call (the leaf never
        # differences itself). NN callers pass nn_evaluator[_differential].
        if evaluator_fn is None:
            evaluator_fn = _lazy_default_evaluator()
        self.evaluator_fn = evaluator_fn

        # Resolve legality function. Default: a strict wrapper bound to this
        # search's RNG so the harvest-feed cap's random samples are
        # deterministic per search instance (rather than sharing the
        # module-level default RNG across all MCTSSearch instances).
        if legal_actions_fn is None:
            # Rank the strict feeding cap with the search's OWN value function
            # (the leaf evaluator), not a hardcoded V3 — same fix the greedy
            # macro agent already gets below, so an NN-leaf search built via
            # the default path is uniformly non-V3 (and doesn't crash trying to
            # read V3 settings off an NN model). `config` is still passed but is
            # ignored by the wrapper whenever `evaluator` is set.
            def _feed_eval(s, p):
                return self.evaluator_fn(s, p, self.evaluator_config)
            legal_actions_fn = _lazy_make_strict_legal(
                config=self.evaluator_config, rng=self.rng, evaluator=_feed_eval,
            )
        self.legal_actions_fn = legal_actions_fn

        # Agent used to play greedy macro-fencing chains. Constructed once;
        # reused. CRITICAL: it must use the SAME value function as the leaf
        # evaluator (`evaluator_fn` + `evaluator_config`), not a hardcoded V3 —
        # otherwise an NN-leaf search would pick its greedy fences with V3, a
        # silent V3 contaminant in a nominally-NN agent. An `EvaluatorAgent`
        # bound to (evaluator_fn, evaluator_config) is exactly `HubrisHeuristicV3`
        # when the evaluator is V3 (that class adds no behavior over
        # `EvaluatorAgent`) and is the NN policy when the evaluator is the NN.
        # Same legal_actions_fn so its lookahead sees the tree's action-pruning.
        if heuristic is None:
            heuristic = EvaluatorAgent(
                evaluator=self.evaluator_fn,
                config=self.evaluator_config,
                seed=rng_seed,
                lookahead="turn",
                legal_actions_fn=self.legal_actions_fn,
            )
        self.heuristic = heuristic

        # PUCT prior source. None => vanilla UCT. (Both modes step through forced
        # singleton moves before evaluating, so UCT is NOT byte-identical to the
        # pre-PUCT engine — see _simulate's forced-move step-through.)
        self.policy_fn = policy_fn
        # OPTIONAL fence-macro generator (distinct from the PUCT `policy_fn`).
        # When set (and fence_mode is MACRO), greedy macro-fencing is replaced
        # by SAMPLING fence chains from this `policy_fn(state, legal) -> {a: p}`
        # — cheap (one head-forward per step) vs the value-net greedy rollout
        # (N value-forwards per step). Selection stays pure UCB (this is NOT a
        # PUCT prior); the policy only seeds the candidate macros UCB chooses
        # among. See `_run_pbf_body` / `_sample_fence_action`.
        self.macro_policy_fn = macro_policy_fn
        # Fencing handling (FenceMode). Default MACRO = today's UCT behavior.
        self.fence_mode = fence_mode if fence_mode is not None else FenceMode.MACRO
        # Invariant: MACRO fencing is UCT-only — macros are MCTS-internal, not
        # engine actions, so a policy can't attach priors to them. PUCT must use
        # FLATTEN (or SEQUENCE_PRIOR, once implemented).
        if self.policy_fn is not None and self.fence_mode is FenceMode.MACRO:
            raise ValueError(
                "PUCT (policy_fn set) cannot use FenceMode.MACRO; use FenceMode.FLATTEN."
            )
        if self.fence_mode is FenceMode.SEQUENCE_PRIOR:
            raise NotImplementedError(
                "FenceMode.SEQUENCE_PRIOR is not implemented yet "
                "(POLICY_PUCT_DESIGN.md §8, c3)."
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
        d = decider_of(state)
        is_chance = d is None
        node = MCTSNode(
            state=state,
            decider=0 if is_chance else d,   # frame label when is_chance; real player otherwise
            is_chance=is_chance,
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
        """Leaf value in P0's reference frame (a margin), divided by
        `leaf_value_scale`.

        - **Terminal** (`Phase.BEFORE_SCORING`): the EXACT game margin
          `score(P0) − score(P1)`, evaluator-independent. The true outcome is
          freely computable at game-end, so we never ask the evaluator to
          guess it (and this sidesteps any terminal quirk of a differenced
          evaluator).
        - **Mid-game**: `evaluator_fn(state, 0)` — the evaluator already
          returns a P0-frame margin (single call, no differencing here). See
          the constructor's `evaluator_fn` note.
        """
        if state.phase == Phase.BEFORE_SCORING:
            return (score(state, 0)[0] - score(state, 1)[0]) / self.leaf_value_scale
        return self.evaluator_fn(state, 0, self.evaluator_config) / self.leaf_value_scale

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
        # Default: attempt 0 = greedy (value-net rollout); attempts 1+ = random.
        # When a macro_policy_fn is set, EVERY attempt samples the policy
        # instead (no greedy rollout) — the cheap path. See _run_pbf_body.
        use_policy = self.macro_policy_fn is not None
        for attempt in range(max_attempts):
            if attempt > 0 and len(macros) >= target:
                break
            greedy = (attempt == 0) and not use_policy

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
            if use_policy:
                label = f"policy_{len(macros)}"
            else:
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

        Three policies, in priority order:
          - `macro_policy_fn` set → SAMPLE the next fence action from the
            policy (proportional to its prior; `_sample_fence_action`). The
            cheap path: one head-forward per step. `greedy` is forced False
            by the caller in this mode.
          - `greedy` → `self.heuristic` (the value-net rollout — expensive).
          - else → uniform random over `legal_actions_fn`.
        Loop exits when PBF is no longer on top (Stop applied), the game ends,
        or the decider hands off.
        """
        from tests.test_utils import filter_implemented
        while (
            state.phase != Phase.BEFORE_SCORING
            and decider_of(state) == decider
            and self._pbf_on_top(state)
        ):
            if self.macro_policy_fn is not None:
                a = self._sample_fence_action(state)
                if a is None:
                    break
            elif greedy:
                a = self.heuristic(state)
            else:
                acts = filter_implemented(self.legal_actions_fn(state))
                if not acts:
                    break
                a = acts[int(self.rng.integers(len(acts)))]
            seq.append(a)
            state = step(state, a)
        return state, seq

    def _sample_fence_action(self, state) -> Optional[Action]:
        """Sample one fence-chain action from `macro_policy_fn` at `state`.

        Samples proportionally to the policy prior (search RNG) over the
        legal set, so repeated calls yield DIVERSE chains (the point of
        generating several macros). Falls back to uniform over the legal set
        if the policy puts no mass on any legal action (e.g. a vocab gap in
        the spatially-blind fencing head). Returns None only if there are no
        legal actions.
        """
        from tests.test_utils import filter_implemented
        legal = filter_implemented(self.legal_actions_fn(state))
        if not legal:
            return None
        if len(legal) == 1:
            return legal[0]
        prior = self.macro_policy_fn(state, legal)
        weights = [max(0.0, float(prior.get(a, 0.0))) for a in legal]
        total = sum(weights)
        if total <= 0.0:
            return legal[int(self.rng.integers(len(legal)))]
        r = float(self.rng.random()) * total
        acc = 0.0
        for a, w in zip(legal, weights):
            acc += w
            if r <= acc:
                return a
        return legal[-1]

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
        cap_total_sims: bool = False,
    ):
        assert sims_per_move >= 1, "sims_per_move must be at least 1"
        self.search = search
        self.sims_per_move = int(sims_per_move)
        # When True, `sims_per_move` is a cap on the *total* root visit count
        # (inherited-via-tree-reuse + fresh) rather than the count of fresh
        # sims run this move. Equalizes the effective search budget per
        # decision across moves regardless of how much the re-rooted node
        # inherited — removes the tree-reuse "effective-sim accumulation"
        # confound when comparing UCT vs PUCT (peaked PUCT trees inherit more).
        # Applies identically to UCT and PUCT (the loop is policy-agnostic).
        self.cap_total_sims = bool(cap_total_sims)
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

        if self.cap_total_sims:
            # Cap TOTAL root visits (inherited + fresh) at sims_per_move. Each
            # _simulate increments root.visits by exactly 1, so this always
            # terminates; if the re-rooted node already inherited >= the cap we
            # run zero fresh sims and act on the inherited tree.
            while root.visits < self.sims_per_move:
                self._simulate(root)
        else:
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

        # ---------- SELECT + EXPAND ----------
        # Descend until we reach the node to evaluate: a freshly-created
        # decision leaf, a terminal, or (defensively) a dead-end. CHANCE nodes
        # (round-card reveals) are transparent — routed through by round-robin,
        # never expanded-as-leaf, never evaluated. See HIDDEN_INFO_DESIGN.md §8.2.
        while True:
            if node.is_terminal():
                break

            if node.is_chance:
                # Route round-robin to one reveal outcome (created on first
                # route). A freshly-created outcome is the new leaf; an existing
                # one we keep descending into. The chance node itself is on the
                # path (gets visits/value) but is never the eval target.
                action = self._chance_route(node)
                child = node.children.get(action)
                is_new = child is None
                if is_new:
                    child = self.search.find_or_create_node(
                        step(node.state, action), parent=node,
                        action_from_parent=action,
                    )
                path.append(child)
                node = child
                if is_new:
                    break          # new post-reveal decision node = leaf
                continue           # existing outcome → keep descending

            # ---- decision node ----
            if node._legal_actions is None:
                node._compute_legal_actions()
            if not node._legal_actions:
                # Defensive: no legal actions at a non-terminal node. Shouldn't
                # happen with restricted legality (never empties a non-empty set).
                break
            # PUCT (policy_fn set) vs vanilla UCT. Both return (child, is_new).
            if self.search.policy_fn is not None:
                child, is_new = self._puct_select_child(node)
            else:
                child, is_new = self._uct_select_child(node)
            path.append(child)
            node = child
            if is_new:
                if node.is_chance:
                    continue       # route through the reveal (handled next iter)
                if not node.is_terminal():
                    # Enumerate legal actions BEFORE the leaf value is evaluated:
                    # lets the forced-move check below fire, and lets a future
                    # shared value+policy net produce both in one pass at the leaf.
                    if node._legal_actions is None:
                        node._compute_legal_actions()
                    if len(node._legal_actions) == 1:
                        # Forced (singleton) decision: step through it in this
                        # same sim. V is evaluated at the downstream real decision
                        # (in-distribution), and backprop fills this node's Q.
                        # Mirrors how chance nodes already route through.
                        continue
                break              # multi-option decision or terminal → evaluate
            # Existing child (is_new=False) → keep descending (loop).

        # ---------- EVALUATE ----------
        # `node` is never a chance node here (the descent breaks only at a
        # decision/terminal leaf).
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

    # ---- PUCT selection (policy-prior-guided) ----------------------------

    def _uct_select_child(self, node: MCTSNode) -> tuple[MCTSNode, bool]:
        """UCT child selection: expand one unvisited action, else UCB-descend.

        Returns (child, is_new). is_new=True iff we just expanded a fresh leaf
        (caller stops descending and evaluates it); is_new=False means we
        descended into an already-visited child and should keep going.
        """
        if node._unvisited_actions:
            action = self._pick_unvisited_action(node)
            node._unvisited_actions.discard(action)
            if isinstance(action, MacroFencingAction):
                # Macro children were pre-created during expand_macros;
                # re-register the edge in case we arrived via another parent.
                child = node.children[action]
                self.search.add_edge(node, child, action)
            else:
                child = self.search.find_or_create_node(
                    step(node.state, action), parent=node,
                    action_from_parent=action,
                )
            return child, True
        action = self._select_via_ucb(node)
        return node.children[action], False

    def _puct_select_child(self, node: MCTSNode) -> tuple[MCTSNode, bool]:
        """PUCT child selection over ALL legal actions (created or not).

        A selected-but-not-yet-created child is materialized here (that's
        expansion), so the tree still grows ~one node per simulation. PUCT runs
        only under FLATTEN/SEQUENCE_PRIOR (no macros), so there is no
        MacroFencingAction handling.
        """
        action = self._select_via_puct(node)
        child = node.children.get(action)
        is_new = child is None
        if is_new:
            child = self.search.find_or_create_node(
                step(node.state, action), parent=node,
                action_from_parent=action,
            )
        return child, is_new

    def _select_via_puct(self, parent: MCTSNode) -> Action:
        """Return the action maximizing the AlphaZero PUCT score.

            U(s,a) = Q(s,a) + c_puct * P(s,a) * sqrt(ΣN) / (1 + N(s,a))

        Ranges over ALL of `parent._legal_actions` — uncreated / 0-visit
        children compete via their prior and the FPU-reduced parent Q, so a
        strong prior orders exploration and low-prior actions may never be
        visited (the soft-pruning). `c_uct` is reused as c_puct (the agent runs
        one mode at a time); calibrate it against `leaf_value_scale`-normalized
        Q. Random tiebreak via the search RNG.
        """
        if len(parent._legal_actions) == 1:
            return parent._legal_actions[0]   # forced move — no prior needed
        parent._ensure_priors()
        priors = parent._action_priors or {}
        parent_q = parent.mean_q if parent.visits > 0 else 0.0
        sqrt_total = math.sqrt(max(parent.visits, 1))   # ΣN ≈ parent.visits
        best_score = -float("inf")
        best_actions: list[Action] = []
        for action in parent._legal_actions:
            child = parent.children.get(action)
            prior = priors.get(action, 0.0)
            if child is None or child.visits == 0:
                q = parent_q - self.fpu_offset          # FPU reduction
                n = 0
            else:
                q = child.value_sum / child.visits
                if child.decider != parent.decider:
                    q = -q
                n = child.visits
            score = q + self.c_uct * prior * sqrt_total / (1 + n)
            if score > best_score:
                best_score = score
                best_actions = [action]
            elif score == best_score:
                best_actions.append(action)
        if len(best_actions) == 1:
            return best_actions[0]
        return best_actions[int(self.search.rng.integers(len(best_actions)))]

    def root_visit_distribution(self, root: MCTSNode) -> dict:
        """The root's per-action visit counts `{action: child.visits}`.

        The search-improved policy at the root — for PUCT debugging now and the
        AlphaZero policy target (π) later. In the DAG `child.visits` is the
        global count; at the root that is the played-move distribution.
        """
        return {a: c.visits for a, c in root.children.items()}

    def _pick_unvisited_action(self, node: MCTSNode) -> Action:
        """Pick a uniformly-random unvisited action from `node`."""
        unvisited = list(node._unvisited_actions)
        return unvisited[int(self.search.rng.integers(len(unvisited)))]

    def _chance_route(self, node: MCTSNode) -> Action:
        """Pick a reveal outcome at a chance node by round-robin and bump its
        per-node counter.

        Round-robin (least-routed outcome, RNG tiebreak) keeps the outcome mix
        uniform, so the chance node's averaged value converges to the true
        (uniform) reveal expectation. Uses `node.chance_counts`, NOT child.visits
        — a post-reveal child shared by another DAG path inflates child.visits
        and would skew routing. See HIDDEN_INFO_DESIGN.md §8.
        """
        if node._legal_actions is None:
            node._compute_legal_actions()
        candidates = node._legal_actions          # the RevealCards
        counts = node.chance_counts
        min_count = min(counts.get(a, 0) for a in candidates)
        least = [a for a in candidates if counts.get(a, 0) == min_count]
        action = (least[0] if len(least) == 1
                  else least[int(self.search.rng.integers(len(least)))])
        counts[action] = counts.get(action, 0) + 1
        return action

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
_DEFAULT_EVALUATOR = None


def _lazy_default_config_v3():
    global _DEFAULT_CONFIG_V3
    if _DEFAULT_CONFIG_V3 is None:
        from agricola.agents.heuristic import DEFAULT_CONFIG_V3
        _DEFAULT_CONFIG_V3 = DEFAULT_CONFIG_V3
    return _DEFAULT_CONFIG_V3


def _lazy_default_evaluator():
    """The default leaf evaluator: the DIFFERENTIAL V3 evaluator, which returns
    a P0-frame margin `e(s,0) − e(s,1)` from one call (the leaf no longer
    differences itself). At terminal `evaluate_leaf` uses the exact score
    margin instead, so this wrapper's terminal-doubling never reaches the leaf."""
    global _DEFAULT_EVALUATOR
    if _DEFAULT_EVALUATOR is None:
        from agricola.agents.heuristic import evaluate_hubris_v3_differential
        _DEFAULT_EVALUATOR = evaluate_hubris_v3_differential
    return _DEFAULT_EVALUATOR


def _lazy_make_strict_legal(*, config, rng, evaluator=None):
    from agricola.agents.restricted import make_strict_restricted_legal_actions
    return make_strict_restricted_legal_actions(
        config=config, rng=rng, evaluator=evaluator)
