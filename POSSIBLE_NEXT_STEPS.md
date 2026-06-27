# Possible Next Steps

Last updated 2026-06-27. This is a planning document, not a commitment. Items are lettered within each section; letters are stable so SESSION_HISTORY.md cross-references stay valid.

---

## 1. Implementation Fixes

### A. At-any-time food conversions for card costs

Cards with a food cost (and other costs payable from convertible goods) need the engine to expose at-any-time grain/veg/animal → food conversions at the point the cost is charged, rather than only at harvest feeding. The Pareto-frontier approach that already governs harvest feeding is the natural model.

### B. Scythe Worker optional effect audit

Scythe Worker's bonus grain-from-field is currently mandatory; it should be optional (the card grants a sub-action, not a forced effect). Once fixed, do a full pass over all implemented cards and check for the same class of error: effects worded as grants that are implemented as forced.

### C. Full correctness audit of the first card batch

Systematically verify every implemented card (Consultant, Priest, Stable Architect, Market Stall) against the card text in `agricola/cards/data/`. Check cost, trigger timing, effect, VP, and any edge cases (e.g. Priest's "exactly 2 rooms" branch, Market Stall circulation).

### D. Oven purchase implementation review

Decide whether `PendingClayOven` / `PendingStoneOven` are the right abstraction or whether the oven purchase flow should be collapsed into the generic `CommitBuildMajor` path. The current design adds two pending types for a relatively narrow use case; review whether eliminating them simplifies the stack without losing anything.

### E. Trigger/hook system — Milestone 2

The next major infrastructure step per `CARD_IMPLEMENTATION_PLAN.md`: implement the three firing kinds (automatic, triggered, mandatory-with-choice), the coarse `before_/after_action_space` lifecycle hooks keyed by `PENDING_ID`, and scoped used-sets. This is the prerequisite for the vast majority of remaining cards; nothing that reacts to another player's action or to entering/leaving a space can land before this.

### F. CardStore — per-card persistent state

`CardStore` was deferred within Milestone 1 (pending a concrete consumer). It lands when the first card that needs it does — likely Tutor or Moldboard Plow. Implement at that point rather than speculatively.

### G. Deferred Milestone-1 cards

Four cards from `CARD_IMPLEMENTATION_PLAN.md` were explicitly deferred: Mini Pasture, Organic Farmer, Shepherd's Crook, Acorns Basket. Revisit each when its blocking mechanism (CardStore, trigger system, or cost-modifier extension) is available.

---

## 2. Additional Game Features / Variants

### A. Draft mode

Replace the random hand deal with a pick-and-pass draft (standard Agricola setup for competitive play). Each player sees N cards, keeps one, passes the rest. Requires a new setup phase and UI affordances; the engine's private-hand model already supports it structurally.

### B. More cards

Ongoing implementation of the ~59-card tractable base-game subset (and eventually the expansion cards), gated on the trigger/hook system (1E) and CardStore (1F) as they land.

### C. 4-player variant

A real undertaking: player-alternation already uses modular arithmetic, but `setup`, the action board, and the starting-player model all assume 2 players. Listed here as a long-term possibility, not near-term scope.

### D. Game replay viewer

A UI mode that replays a downloaded trace (the existing `.json` trace format) move-by-move in the browser, with the full board state shown at each step. Useful for post-game analysis and debugging without running the server.

---

## 3. Starting the AI Pipeline (Card Game)

### A. Port the card game engine to C++

Extend the C++ twin (`cpp/`) — today a faithful *Family-only* engine — to support the full card game, so card-game self-play can run at C++ speed (~4× Python) the way Family self-play already does. The differential-test harness (`tests/test_cpp_*.py`) keeps the port honest; follow the same staged-build + green-gate discipline as the Family port.

**When to do this, and the cost it locks in.** This is a *throughput* lever, not a correctness prerequisite: the card game can self-play in pure Python first (slower), and only needs the C++ port once data generation is the bottleneck — exactly the order the Family pipeline followed. The reason not to rush it is the maintenance economics. Today, card changes are "free" against C++: the engine is Family-only, so card-only state and logic never reach it and the gates stay green without a re-port (which is why all of this session's card work touched no C++). The moment cards live in C++, that reverses — *every* future change to card rules, legality, scoring, the encoder, or the state shape must be re-ported to keep the gates green (the same invariant the Family engine already carries). So port when the card system is **stable enough** that paying the ongoing two-engine tax is worth the self-play speed — not mid-development while cards are still churning.

**What the C++ twin has vs. needs.** The Family engine, MCTS, NN inference, canonical serialization, and hash are all in place, and the before/after host *scaffolding* from the recent refactors already exists (the pending frames carry `phase`, the enumerators have before/after branches). But the card machinery is stubbed: the trigger/auto firing is empty ("none in Family"), `FireTrigger` throws, the card-only host (`PendingActionSpace`) is never produced, and there is no `GameMode`, no hands, no card registries, no card catalog. The differential corpus is Family-only (built from `setup_env(seed)` with no card pool).

**Staged plan** (each stage gated green before the next, mirroring the Family port):

1. **Extend the differential harness to card states first.** Build the safety net before the thing it guards: teach the corpus generators to deal card-mode games (`setup_env(seed, card_pool=…)`) and play random card games, and assert C++ matches Python over *card* states. This is the gate every later stage leans on; without it the port is unverified.
2. **State-model + serialization parity.** Add the card-only state to the C++ `GameState`/`PlayerState` (game mode, private hands, played-card sets, the scoped used-sets, `CardStore`, `future_rewards`) and the card-only pending frames (play-occupation/minor, the atomic action-space host, card-choice, the phase hooks), plus their canonical (de)serialization and hashing. The canonical JSON is the cross-language contract, so this stage is "C++ can round-trip any card state byte-for-byte." (Card-only fields are default-skipped today so Family JSON is unaffected; card states emit them and C++ must read/write them in declaration order.)
3. **Setup with a card pool.** Mirror `setup_env`'s hand-dealing exactly — same seeded RNG, same non-overlapping 7+7 deal — so an identical (seed, pool) yields a byte-identical starting state on both sides.
4. **The firing infrastructure.** Un-stub the host model: the card registries (triggers / automatic effects / mandatory-with-choice), `apply_auto_effects`, the before/after firing at push / flip / the work-complete boundary, the action-space host (`should_host_space` + the atomic-host Proceed lifecycle), and the start-of-round / harvest-field phase hooks. This is the engine *machinery*, separate from any specific card; it can be smoke-gated with a single synthetic card before the catalog lands.
5. **The card catalog — the bulk of the work.** Reimplement each implemented card's cost / prerequisite / on-play / trigger / automatic effect in C++, ported in batches by category to match the Python build order, with the card-mode differential gate run per batch. C++ needs an analog of Python's import-time self-registration (a card registry populated at startup). This stage scales with the card count and must track the Python catalog as it grows.
6. **Mode-branched legality / resolution + card-play actions.** Port the card-mode deltas in `legal_actions`/`step` (mode-branched placement; the Lessons / Meeting Place / Major-Minor / House-Redevelopment / Basic-Wish play-card paths; the play-card commits; surfacing eligible triggers), then run the full card-mode random-game differential to green.

**Scope boundary.** 3A is *engine* parity only — `step`, `legal_actions`, `scoring`, canonical, and hash over card states. It deliberately stops short of the NN: the card *encoding* (3C) and ISMCTS for hidden hands (3E) sit above the engine and are tracked separately. Hidden information doesn't complicate the engine differential itself, since the gates compare full ground-truth `GameState`s, not per-player observations — determinization is an agent-layer concern, not part of this port.

### B. Augment the non-card AI to play with cards

Before training a card-game NN, a playable card-game agent is needed to generate data. The most practical bootstrap is probably the existing joint-trunk bot for the non-card decisions plus a simple heuristic (or random) for card-play choices. Assess how much card quality matters for data diversity.

### C. Card encoding for the NN

The existing ~170-feature encoder has no card representation. Decide how to encode private hands and played cards: one-hot over the full card vocabulary, a bag-of-features summary, or a learned card embedding. The choice shapes the NN architecture and the encoder registry (`EncoderSpec` in `encoder.py`).

### D. Training pipeline for the card game

Once a card-game agent and encoder exist, adapt the self-play loop — data generation, joint shared-trunk training, C++ export, evaluation — to the card game. The Family pipeline is the template; the main additions are the card encoding and ISMCTS (3E) for hidden-hand play.

### E. ISMCTS for hidden hand information

The Family game has no hidden state (the round-card order is symmetric). The card game does: each player's hand is private. The current MCTS assumes perfect information and cannot handle this correctly. Information Set MCTS (ISMCTS) — which samples from the opponent's possible hands at each node — is the standard approach and a prerequisite for a principled card-game agent.

### F. Card-game heuristic for data bootstrapping

AlphaZero-style self-play needs *some* agent to generate the initial training corpus. For the Family game the heuristic ensemble served this role. For the card game, decide whether to write a lightweight card-play heuristic (evaluate each playable card by its expected effect) or rely on the non-card bot + random card plays and accept noisier initial data.

---

## Other

### A. Web UI fix punch list

`FRONTEND_FIXES.md` contains a prioritized list of known frontend gaps in `static/app.js` / `static/style.css` / `templates/index.html`. None are blocking, but several affect usability (e.g. display issues in the card-play UI). Work through them opportunistically when the backend is stable.

### B. NN leaf-batching

The single largest remaining MCTS speedup per `SPEEDUPS.md` Part 2: batch multiple leaf evaluations into one NN forward pass instead of one per leaf. Deferred until sim budgets grow large enough that NN forward-pass cost is the dominant MCTS cost again.
