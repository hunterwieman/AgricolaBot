# AgricolaBot — Strategy Reference

This document captures the high-level AI strategy and key algorithm decisions
made in the design sessions. Read alongside RULES.md (complete rules reference),
ARCHITECTURE.md (code architecture), and SESSION_HISTORY.md (implementation history).

> **For MCTS specifics:** see `MCTS_DESIGN.md` for the comprehensive design
> spec of the MCTS phase (vanilla UCT, FPU, DAG with transpositions,
> leaf-evaluation, macro-enumeration for Fencing, strict-restrictions wrapper,
> shared/separate tree modes). This document covers the higher-level
> "why MCTS, why AlphaZero-style" rationale; `MCTS_DESIGN.md` covers the
> concrete implementation decisions.

---

## Project Phases

### Phase 1: Game Engine (current)
Build a fast, deterministic Python implementation of 2-player Family Agricola.
No AI yet. Milestone: two random agents play a complete game and produce a
final score.

Key decisions:
- **Family game first**, add cards in Phase 3. Validates the full pipeline
  before card complexity is introduced.
- **Pure Python + NumPy** for the engine. PyTorch only for neural networks
  (Phase 4+). Migrate engine hot-loops to JAX only if self-play is provably
  bottlenecked — don't pay JAX's learning curve upfront.
- **Immutable frozen dataclasses** throughout (see ARCHITECTURE.md architecture).
- **Hierarchical action space** (not flat masked). Each worker placement is
  followed by sequential sub-decisions, each with a small action space.
- **Completability masking**: an action space is only offered if the agent can
  complete at least one valid plan on it. Sub-decisions are offered only if the
  partial plan remains completable.

### Phase 2: Baseline Agents
Random agent + strong heuristic agent encoding top-player intuition.
Without baselines, there is no way to tell if learned agents are good.

Key decision:
- **Soft pruning, not hard constraints.** Expert heuristics (e.g. "always plow
  before sow on Cultivation", canonical stable placement progressions) are
  encoded as *priors* over actions, not as rules that remove actions. The agent
  can override a prior if the value function strongly disagrees. Hard pruning
  caps the agent's ceiling at the heuristic; soft pruning does not.
- **Symmetry breaks are hard-pruned** (e.g. canonical cell ordering for
  interchangeable plow targets). These have no strategic content.

### Phase 3: Card System + Full Game Engine
Add occupations, minor improvements, and major improvement effects.

Key decisions:
- **Card effect DSL**: hybrid approach. ~30–50 effect primitives cover 90% of
  cards as structured data (YAML). Python escape hatches handle the weird 10%.
  Pure-imperative (each card as a Python function) is too hard to analyse;
  pure-data (every effect as YAML) is too constrained for complex cards.
- **Card representation for the network**: hybrid embedding.
  `card_vector = MLP(generic_features) + embedding_table[card_id]`
  Generic features handle rare cards and generalize across decks; the learned
  residual captures card-specific nuance for frequently-seen cards. A single
  linear layer is often sufficient for the feature encoder — MLP adds capacity
  only if ablations show it helps.
- **Deck support order**: E-deck (Basic) first, then I (Interactive),
  K (Complex). Each deck adds ~180 cards.
- **Undo option for card interactions**: card effects can trigger chains of
  sub-decisions that are hard to validate upfront. An undo mechanism for the
  full-game step function is acceptable complexity — deferred to Phase 3.

### Phase 4: Imitation Learning
Train a policy network to predict human moves on scraped game data.
This bootstraps the agent above the cold-start phase that pure RL struggles
through in a game with Agricola's large action space.

Key decisions:
- **Behavior cloning** (supervised learning on state→action pairs) is the
  starting algorithm. DAgger or inverse RL are unnecessary complexity at this
  stage.
- **Data sources**: BoardGameArena (better structure) and Boîte à Jeux
  (scrapeable). Tens of thousands of games is probably enough to bootstrap.
- **Imitation learning before self-play**, not instead of it. The goal is to
  skip the "incompetent flailing" phase, then let self-play improve beyond
  human-level.

### Phase 5: Self-Play RL
Refine policy and value networks via self-play. The main AI research phase.

Key decisions:
- **AlphaZero-style** (MCTS + neural net) is the target. Vanilla AlphaZero
  assumes perfect information and determinism; Agricola has neither.
  Required adaptations:
  - *Hidden information* (opponents' hands): determinization. At search time,
    sample plausible opponent hands from a learned belief distribution, run
    MCTS treating those as known, average outcomes. ISMCTS is more principled
    but the gains over good determinization are modest in this game shape.
  - *Stochasticity* (card draws, stage-card ordering): sampled MCTS rollouts.
  - *Multi-player*: self-play initially, then league play if mode collapse
    (agent over-optimizes against itself and develops exploitable blind spots).
- **PUCT formula** handles soft priors naturally — low-prior actions get less
  search but aren't eliminated. Expert heuristics from Phase 2 feed in as the
  initial policy prior.
- **Tree reuse across moves**: after the agent plays action A, the subtree
  rooted at "after A" is reused as the new root. Immutable state makes this
  free — no deep-copying required.
- **Training data collection**: sequences of (state, action, reward) are
  appended to a replay buffer. Immutable states are appended by reference; no
  copying per-turn.

### Phase 6: Evaluation + Training Tool Features
Measure strength and expose analysis capabilities.

- Strength metrics: vs fixed baselines, Elo-style vs previous versions,
  vs the human player (ground truth).
- Analysis features (cheap once the model is trained): move evaluation,
  position win probability over time, "what if I'd done X", mistake
  identification. These are derived from the trained policy/value heads —
  not separate models.

### Phase 7: Iteration + Scaling
Add more decks, re-train, scale compute, compare versions.

---

## Key Algorithm Decisions (summary)

| Decision | Choice | Rationale |
|---|---|---|
| Action space structure | Hierarchical, sequential sub-decisions | Flat enumeration is intractable for fence/sow/room combinations |
| Action validity | Completability masking | Matches game rules; agent never gets stuck |
| Expert knowledge | Soft priors (not hard constraints) | Hard pruning caps the ceiling |
| Card representation | Hybrid: features + learned residual | Features generalize to rare/new cards; residual captures specifics |
| IL algorithm | Behavior cloning | Sufficient for bootstrapping; avoid DAgger complexity |
| RL algorithm | AlphaZero-style MCTS | Dominant approach for perfect-ish info board games |
| Hidden info | Determinization + learned belief distribution | Practical; ISMCTS gains modest for this game |
| Multi-player | Self-play first, league if needed | Start simple |
| Fence action space | Canonical (config, position) pairs | ~50–150 valid options; tractable |
| Animal accommodation | Pareto frontier over (sheep, boar, cattle) | Exact feasibility given one-type-per-pasture constraint |
| Engine language | Python + NumPy | JAX migration only if self-play provably bottlenecked |
| Neural net framework | PyTorch | Prior experience; vast tutorial ecosystem |

---

## Open Design Questions

These are unresolved decisions that will need to be addressed in upcoming tasks.

**`pending_decision` field in `GameState`** (Task 4)
Multi-step actions (fencing, sow, room-building) require tracking where in a
sequence of sub-decisions the agent currently is. `GameState` needs a
`pending_decision` field to represent this. The exact structure — what
information it carries, how it interacts with `legal_actions`, and how the
step function resolves it — is the central design question for Task 4.

**Fence canonicalisation** (Task 4)
`legal_actions` must enumerate valid fence placements. The approach is
canonical (configuration, position) pairs yielding ~50–150 valid options after
masking, but the exact representation of a "fence action" and the algorithm
for generating the canonical list have not been designed yet.

**Animal location tracking**
Currently animals are stored as totals only in `Animals`. A small number of
full-game cards reference specific animal locations (which pasture an animal
is in). Acceptable for Family game; revisit when adding cards in Phase 3.

**Lessons action space**
Exists in the state and board but is never a legal action in Family game (no
occupation cards). Becomes legal in Phase 3. No action needed now.

**Immutable state + structural sharing.** Every state transition via
`dataclasses.replace()` produces a new State pointing to shared sub-objects.
MCTS branches share unchanged sub-trees for free. No deep-copying required for
rollouts or tree reuse.

**Environment wrapping a pure-functional core.** The outer loop uses a Gym-style
Environment class (`reset()`, `step()`, `legal_actions()`). Internally, game
logic is pure functions (`_step(state, action) -> state`). MCTS uses the pure
functions directly, bypassing the Environment wrapper.

**Derived data, not cached data.** Pastures, animal capacity, cooking rates,
fences-in-supply, stables-in-supply: all derived on demand from ground-truth
state. Caching is added only where profiling shows it is a real bottleneck.

**Pareto frontier for animal decisions.** When an agent gains animals or enters
the breeding phase, it chooses a final (sheep, boar, cattle) configuration from
the Pareto frontier: non-dominated achievable total animal counts given farm
capacity and inventory bounds. Food generated is computed deterministically from
the frontier point and the player's cooking improvement rates.
