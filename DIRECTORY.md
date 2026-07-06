# DIRECTORY.md

The **full annotated map of the repository**: the documentation index (every doc with a
paragraph-length abstract) and the annotated directory tree (every file with its role, key
functions/flags, and cross-references). Spun out of CLAUDE.md verbatim (2026-07-02) so sessions
pay for this reference on demand instead of in every context window; CLAUDE.md keeps a slim
one-line-per-entry version of both.

**Maintenance contract:** what previously applied to CLAUDE.md's tables applies here — when a
file or doc is added, renamed, or changes role, update its entry in this file (and the slim
CLAUDE.md line if it appears there). Scripts' CLI flags and per-file deep detail belong HERE,
not in CLAUDE.md.

---

## Documentation Files

### Repo root — the live references & operational docs

Everything at the root is either LIVE (kept current as the project moves) or an operational
guide; frozen design records live under `design_docs/` below.

| Doc | Contents |
|---|---|
| `CLAUDE.md` | The auto-read orientation file for every session: Foundations, the three phases, the two cross-cutting infrastructure sections, status & boundaries, and slim one-line versions of this file's doc index + directory tree. Orientation + pointers only; reference detail lives here and in the per-domain reference docs. |
| `DIRECTORY.md` | This file — the full annotated repo map (doc abstracts + per-file tree entries incl. script CLI flags), read on demand. |
| `RULES.md` | Complete rules reference for the 2-player game. Treats the full card game (occupations + minor improvements) as the default and documents the cardless **Family** game and the 3–4 player game as variants in their own sections. Covers setup/draft, primitive sub-actions, action spaces, major improvements, the card system, harvest, and scoring. (Pure game rules — no engine/project references.) |
| `ENGINE_IMPLEMENTATION.md` | Deep-mechanics reference companion to Phase 1 (the game engine): dispatch tables, the full pending-stack provenance scheme and invariants, sub-action cost handling, the Fencing / animal-accommodation / Harvest subsystems, and the coding conventions. Read alongside Phase 1 when doing engine surgery. |
| `CARD_ENGINE_IMPLEMENTATION.md` | **The reference-of-record for the card system as built** (Phase 3) — the deep-mechanics companion to `ENGINE_IMPLEMENTATION.md` for everything the card game adds, and the ONE doc a card-implementation session reads first. §0 the goal (a working card game) + the Family/C++ lockstep invariant and its two compliance routes (additive O(1)-skipped seams by default; Family-shape change + C++ re-port when the design warrants); §1 the live Status section (updated per batch — the maintenance contract); §2 hosts & firing (the four host kinds, event derivation, the three firing kinds, enforce-first, the firing-seam map); §3 every `register_*` registry; §4 card state & the card-only pending frames (the state-placement rule, CardStore, hands/ISMCTS, canonical default-skip); §5 the cost-modifier chokepoint + the build-fence deferred tally (the one mode branch) + food payment + capacity mods; §5b the harvest timing windows (the ladder + virtual walk, the take-occasion manifest + counting/scoping doctrine, take-modifiers, skips, feeding income, the breed-frame events); §6 rulings & idioms; §7 the implementation process; §8 deliberate boundaries (end-of-turn, Grocer, C++-is-card-free); §9 the card-doc map. The design records (CARD_SYSTEM_DESIGN, COST_MODIFIER_DESIGN, FOOD_PAYMENT_DESIGN, the refactor docs) keep rationale; this describes the code. |
| `CARD_AUTHORING_GUIDE.md` | **The practical how-to for implementing more cards — read this first when adding cards.** A pitfall-focused framework: how to read a card (exact text from `agricola/cards/data/` → classify timing / firing kind / primitives → map to a template), the firing machinery (host before/after lifecycle, event names, the three firing kinds with their `register_*` signatures + the eligibility-signature difference), the special mechanisms (deferred goods/effects, conditional latch, CardStore, scoring, opponent hooks, play-variant choice), a template catalog (which existing card module to copy per shape), a worked example (Cottager), the hard set to defer-and-ask about, and a per-card discipline checklist. Heavily emphasizes the obscure rulings a coding agent misses ("each time you use" = *before*; "end of turn" ≠ end of the action's effects/triggers; granted sub-actions are optional; optionality lives at the parent host; atomic spaces must be explicitly hosted to be hookable) and the **cardinal rule: when a card doesn't clearly fit the machinery, DEFER it and ASK the user** (who understands the rules/interactions far better than a coding agent). Complements `CARD_ENGINE_IMPLEMENTATION.md` (the machinery reference + live status). |
| `CARD_IMPLEMENTATION_PROGRESS.md` | **LIVE per-card ledger** — every catalog card's mechanics classification against the taxonomy (two independent passes + a high-effort adjudication of disagreements; legend at the top) and implementation status. The per-card location; the machinery reference never carries per-card entries. |
| `CARD_DEFERRED_PLANS.md` | **LIVE decision surface for deferred cards**: the defer clusters (grouped by blocker), concrete shared-infrastructure build proposals that would unblock whole clusters at once, and the open user questions — including the dated harvest-window rulings (19 numbered). Where a deferring session records its cluster + proposal (CARD_ENGINE_IMPLEMENTATION.md §7). |
| `HARVEST_HANDOFF.md` | The harvest-window arc's session-reasoning record (2026-07-03 → 05): every ruling's derivation with the counterexamples that shaped it (the one-event field phase, the virtual walk, claim-aware folds, the skip rulings, Shepherd's Whistle's frontier), the bug stories (the Slurry counting bug, the fold collision), the §8b meta-patterns of how the user rules, and §12 — the remaining-work list with per-item cautions. Read before resuming any harvest-arc work; the ruling RECORDS in CARD_DEFERRED_PLANS.md / HARVEST_WINDOWS_DESIGN.md outrank it if they disagree. |
| `MCTS_IMPLEMENTATION.md` | **The** comprehensive, self-contained reference for the MCTS agent (`agricola/agents/mcts.py`) — read this to understand the search code. An algorithm overview (the four-phase loop, leaf-evaluation, the UCT-vs-PUCT subsection, the DAG/transposition table, sign-flipping, chance nodes, fencing), then the concrete implementation: `MCTSNode` / `MCTSSearch` / `MCTSAgent`, `_simulate` line-by-line + cost cheat-sheet, UCT (`_uct_select_child` / `_select_via_ucb` + FPU) and PUCT (`_puct_select_child` / `_select_via_puct` / `_ensure_priors`), `evaluate_leaf`, the strict/regular legality wrappers, the chance-node routing (`_chance_route` / `chance_counts`), a full Fencing section (`expand_macros` / the entry-body-exit macro generation / the agent's replay queue / `FenceMode`), the played move (`_select_action_with_temperature`), config reference, and an invariants / edge-cases / design-vs-code notes section. Treats the value evaluator and policy as black boxes (only their `(state, player, config) -> float` / `(state, legal) -> {action: prior}` contracts). |
| `SHARED_TRUNK.md` | Design + implementation + results record for the **joint shared-trunk value+policy model** (Phase 2.3, Stage B): one `170→256→256→128` trunk feeding a value head + 7 fixed + 2 pointer policy heads, trained jointly on the 41k self-play data with **soft-π** (cross-entropy against the visit distribution) policy + margin value. Covers `SharedTrunkModel` (`shared_model.py`), the one-pass cached `shared_dataset.py` (+ §3 **"the two memory lessons"** — the per-pickle-chunking *encode* peak AND the streamed-path / direct-to-split *finalize* peak that OOM'd at 57k; **load-bearing, untested, read before refactoring the builder**), the joint trainer (`shared_training.py`: per-head balance, value-MSE early-stop), the `make_joint_fns` inference adapter (`shared_policy.py`: **one trunk forward per node** via an embedding memo, so `mcts.py` is unchanged), the **C++ joint inference** (`shared_trunk_v1` manifest, mode toggle in `NNInference`, embedding cache, two-net `--match` mode), the value-capacity sweep that set the trunk size (256×2; MAE was a backwards predictor), and the eval (joint beats previous-best at 800-sim PUCT — C++ 99%). Read before touching the joint model. |
| `nn_models/REGISTRY.md` | Authoritative index of every trained NN checkpoint under `nn_models/`. Per-model row: id, `ENCODING_VERSION`, `DATA_VERSION`, training data source, architecture / regularization, train size, test MAE, current Status (active / superseded / incompatible). The checkpoint files themselves (`config.json`, `best.meta.json`, `test_metrics.json`) own the underlying numbers; this file is the catalog that ties them together and records which model is the current default. **Every training run must update this file** as part of its completion — see template at the bottom. |
| `CPP_ENGINE_PLAN.md` | Design + staged-build + results record for the **C++ self-play engine** (CLAUDE.md → The C++ twin engine): a faithful native reimplementation of the self-play inner loop (engine + MCTS + hand-rolled NN inference) that runs ~4× faster than Python, validated against the Python oracle by the `tests/test_cpp_*.py` differential harness. Covers the architecture (traces, the canonical-JSON contract, the differential-testing methodology), the 7 stages with their equivalence gates (§8.1 status ledger), the JSON-hot-path profiling finding + the two optimization passes, the data-gen pipeline (`generate_selfplay_data_cpp.py`), and the maintenance invariant (Python is the oracle; keep the C++ gates green). All C++ lives under `cpp/`. **Kept at the repo root because it doubles as the C++ manual**: the port workflow + gate-writing methodology (§3), the C++ data model / NN / MCTS internals (§5–§7), the repo layout + build (§9, with `cpp/README.md`), and the card-port path (§12) are what porting sessions actually consult; §8 is the frozen staged-build ledger. |
| `FRONTIER_OPT_DESIGN.md` | Design + implementation record for the frontier/accommodation optimizations that speed up the Pareto/accommodation helpers in MCTS. Toggleable via `agricola/opt_config.py` (`PARETO_OPT_LEVEL` 0–3 + `FENCE_SCAN_CACHE`), now default-on. Covers the algorithmic rewrites (rate-descending `food_payment`, max-corner), the projection-keyed caches (exact / Φ farm-shape / feeding clip), the correctness invariants + proofs (Appendix A), the cross-level equivalence testing strategy (§8.1) and benchmarking methodology (§8.2), and the landed-status/phasing. **Implemented and kept at the repo root**: the caches are default-on production behavior, and this is the live reference for their projection-key correctness contract (§2.1) and the cross-level equivalence test pattern — consulted whenever a card broadens what a cached helper reads (ENGINE_IMPLEMENTATION.md §5). |
| `SPEEDUPS.md` | Performance catalog in two parts: **Part 1 Implemented** (every optimization in the code, with what/why/where — `fast_replace`, cached `__hash__`, the `opt_config` frontier/fence caches, the NN inference encoder S10–S13, etc.) and **Part 2 Potential next steps** (sketched candidates + *measured no-gos* like jit.trace and the encoding-keyed cache). Stable `S1`–`Sn` identifiers; deep detail for the big ones lives in `FRONTIER_OPT_DESIGN.md` / `CHANGES.md`. (Renamed from `POSSIBLE_SPEEDUPS.md`.) Sibling to POSSIBLE_NEXT_STEPS.md, scoped to performance. |
| `PROFILING.md` | Profiling findings. Foregrounds the **current production profile** — NN value-leaf + multi-head policy PUCT, i.e. where time goes in the code today (cost attribution, the ~2× session result, the diffuse-engine-remainder finding) — plus **measurement caveats** (laptop wall noise → min-of-N/pair-by-seed; cProfile over-attributes high-call tiny functions; the eval-mode requirement). Older random-play (Workloads A/B/C, R1–R6) and V3-leaf MCTS profiles are kept under **Archived profiles**. Re-run the current profile via `scripts/profile_mcts_nn.py`. |
| `NN_TRAINING_SPEEDUP.md` | Diagnosis + benchmark record for the NN value-training speedup. The *prescriptive* half (changes A batched-indexing + B large-batch `--fast-loader`) is **landed and validated** (see `REGISTRY.md`: bs=8192 fast-loader holds champion-recipe quality) — the code in `training.py` is now the source of truth, and the operational guidance lives in CLAUDE.md → the self-play & training workflow (§2.4). Kept for its **unique content**: (1) §1–§2 the empirical *why* — training is overhead/optimizer-step-bound not compute-bound, with the per-step cost breakdown and the batch-size sweep (CPU flat past ~4096, MPS best at ~8192); (2) §4–§6 the **MPS (`--device mps`) path**, which was never implemented/validated — the only record of its recommended invocation, 8 GB-RAM/`--data-on-device` risks, non-determinism caveats, and nightly-PyTorch op-gap warnings, should the M1 GPU ever be tried. |
| `DEPLOY.md` | Beginner-friendly step-by-step guide to deploying the web UI online on **Fly.io** as a single always-on container (CLAUDE.md → Web UI & online deployment): install `flyctl`, create + deploy the app, logs, regions, rough cost, and the in-memory-game-state caveat (a redeploy drops in-progress games). The deploy artifacts it drives are `Dockerfile` / `.dockerignore` / `fly.toml` / `deploy.sh` at the repo root. |
| `deploy.sh` | One-command Fly.io deploy of the web UI with the *current* champion (CLAUDE.md → Web UI & online deployment): resolves the `nn_models/cpp_export_best` symlink (Docker `COPY` can't follow it) into the concrete export dir, passes it to the `Dockerfile` as the `EXPORT_DIR` build-arg, and runs `fly deploy` (extra args forwarded). Promoting a champion = re-point the symlink, then `./deploy.sh`. |
| `CLOUD_RUNBOOK.md` | Operator guide for running the self-play / training / eval loop **off the M1 on Google Cloud (GCP)** (CLAUDE.md → the self-play & training workflow (§2.4)): project / $50-budget / bucket (`gs://agricola-selfplay-…`) setup, the ARM-native C++ binary build on a T2A instance, launching generation / joint-training / evaluation / the α-sweep, durable upload + VM self-teardown, and the two IAM gotchas (self-delete needs `--scopes=cloud-platform` *and* the SA's `compute.instanceAdmin.v1` role; bucket writes need `storage.objectAdmin`). The path that produced the 40k corpus behind `joint_outcome_44k`. |
| `FRONTEND_FIXES.md` | Punch-list of web-UI *frontend* gaps (`static/app.js`, `static/style.css`, `templates/index.html`), ordered by certainty the fix is needed; each item states the problem, the backend data already exposed, and the specific frontend change. |
| `SESSION_HISTORY.md` | Full record of what was built each session, including design decisions made and bugs caught. |
| `CHANGES.md` | Significant cross-cutting refactors that touched many files at once (Resources extraction; two-track pasture cache model; dispatch refactor + pending provenance; harvest phases; `BoardState.action_spaces` canonical-tuple refactor; engine performance pass with `fast_replace` + `legal_actions_cache()`; HubrisHeuristicV3 architecture + iterative tuning pipeline). |
| `CLEANUP.md` | Three small targeted field-level fixes (house material location, field rename, field removal). |
| `IMPLEMENTATION_CHOICES.md` | Fine-grained design decisions that worked well for the Family game but may need revisiting when cards are added. |
| `POSSIBLE_NEXT_STEPS.md` | Living planning doc — directions the project could take next, organized by scope and effort. Updated as the project progresses. |
| `SESSION_INTRODUCTION.md` | Standard prompt to give a new coding agent at the start of a session. |
| `README.md` | Human-facing project README (the GitHub landing page): project summary, status overview, the playable-agent table, and future work. Overlaps this file's intro but targets a general reader rather than a coding session. |
| `FILE_DESCRIPTIONS.md` | Detailed per-file descriptions for every `agricola/*.py` and the test-infrastructure files (`tests/factories.py`, `tests/test_utils.py`). |
| `TEST_DESCRIPTIONS.md` | Per-file coverage descriptions for each `tests/test_*.py`. |

### `design_docs/` — design records

Docs that were load-bearing while their feature was designed/built and are read in special cases
now (rationale questions, provenance, an open problem's analysis). One line each — **each doc's
own header banner is its abstract**, stating status and where the as-built truth lives.

**`design_docs/` (agent-phase records):**
- `FIRST_NN.md` — design spec for the first NN value function (encoding, target, data pipeline).
- `POLICY_HEAD.md` — the behavioral-cloning policy heads: the v1 placement spec + the record of all nine heads (§11/§14); the spatially-blind-`fencing` finding.
- `POLICY_PUCT_DESIGN.md` — the combined policy+PUCT design spec; the implemented halves live in `MCTS_IMPLEMENTATION.md` / `POLICY_HEAD.md`.
- `MCTS_DESIGN.md` — the original UCT-era search design spec; superseded by `MCTS_IMPLEMENTATION.md`.
- `HIDDEN_INFO_DESIGN.md` — the hidden-information refactor (reveal-as-nature-step, the Environment split, chance nodes) + the ISMCTS/determinization direction for the card-game agent.

**`design_docs/cards/` (card design + batch records; the `*_HANDOFF.md` files here are gitignored session scratch):**
- `CARD_SYSTEM_DESIGN.md` — the conceptual card-system design record: terminology (§0), firing-architecture rationale, open questions (§13), **the Grocer conversion-reachability analysis (§15)**.
- `CARD_IMPLEMENTATION_PLAN.md` — FROZEN plan + ledger for the first tractable subset (per-category canonical code, decisions log, the Firewood/end-of-turn note).
- `COST_MODIFIER_DESIGN.md` — the cost-pipeline design + red-team (worked frontier traces, attacks A1–A7, resolved forks, the §9 build-fence slice).
- `FOOD_PAYMENT_DESIGN.md` — the food-payment design record (the raise-only decision, banking arithmetic, red-team).
- `HARVEST_WINDOWS_DESIGN.md` — the harvest timing-window design of record (the ladder, the during-window classes, FEED/BREED, card-fields, anytime converters; **§12 = the as-built code map**); as-built truth in CARD_ENGINE_IMPLEMENTATION.md §5b, session reasoning in root-level `HARVEST_HANDOFF.md`.
- `HARVEST_CARDS_REVIEW.md` — the 130-card verbatim harvest census, grouped by window (2026-07-03 snapshot; impl markers dated).
- `CARD_ENGINE_DOC_CAPTURE.md` — the harvest-arc doc-integration checklist, FOLDED into CARD_ENGINE_IMPLEMENTATION.md 2026-07-05 (kept as record).
- `SPACE_HOST_REFACTOR.md` / `SUBACTION_HOOK_REFACTOR.md` — the LANDED host-lifecycle refactor records (design + staging).
- `PAY_FOOD_PLOW_CARDS.md` — build guide for the pay-food→plow card cluster (the Ox Goad shape).
- `POST_COMPACTION_DETOUR.md` — the enforce-first correctness detour + the plow-stranding guards (deck-D session record).
- `CARD_BATCH_TRIAGE.md` / `CARD_BATCH_AB_SUMMARY.md` / `CARD_TRIAGE_CDE.md` — per-batch triage specs + outcomes (decks A/B; C + partial D).
- `ROOM_CARDS.md` / `STABLE_CARDS.md` — catalog analyses of room-/stable-touching cards.
- `ARTIFEX_CATEGORIZATION.md` / `BUBULCUS_CATEGORIZATION.md` — unreviewed per-deck mechanic hypotheses (triage inputs, not rulings).

**`design_docs/game_engine/` (Phase-1 records):**
- `ARCHITECTURE.md` — the original architecture spec + rules reference (field names may diverge from current code; annotated).
- `FENCE_IDEAS.md` — Task-6 fencing design alternatives.
- `INCREMENTAL_PASTURE_DESIGN.md` — NOT-STARTED sketch for incremental pasture decomposition (SPEEDUPS.md S9 option 2).
- `TASK_2.md` … `TASK_7.md` — frozen per-task implementation specs, cross-referenced from `SESSION_HISTORY.md`.

**`design_docs/heuristic_models/` (the retired heuristic phase — §2.1):**
- `V3_DESIGN.md` — the V3 evaluator design reference; `V3_TRAINING_PIPELINE.md` — the CMA-ES tuning-pipeline guide; `HUBRIS_V1_NOTES.md` — the V1 evaluator reference; `HEURISTIC_TUNING_PLAN.md` — the V1-era tuning plan (partially superseded).

### `archive/`

Archived (in `archive/`, fully superseded by current docs):

| File | Description |
|---|---|
| `archive/TESTS.md` | Pre-`TEST_DESCRIPTIONS.md` per-test reference. Superseded by `TEST_DESCRIPTIONS.md`. |

---

## Directory Structure

```
AgricolaBot/
    play.py                         # Top-level entry point — terminal-based human play UI. Wraps the engine in an interactive REPL with rendered farmyard / action-board / score-card output and action-selection prompts.

    play_web.py                     # Top-level entry point — browser-based human play UI (CLAUDE.md → Web UI & online deployment). Dual-mode: a New-Game landing choice picks **Family** (human-vs-bot, cardless) or **Cards (beta)** (human-vs-random / human-vs-human, all implemented cards dealt as random non-overlapping 7+7 hands via `setup_env(seed, card_pool=...)`). The session carries `game_mode`; the payload carries it top-level. Card hands serialize under hidden-info rules (`state_to_json`'s `_reveal_hand`: face-up only for a human seat; in pass-and-play only the active player's hand, else face-down count). Card metadata (name/effect/structured minor cost) is built once into `_CARD_META` from `agricola/cards/data/*.json` (joined by slugified name); card-play actions get a `card` ui_hint + named-button display (`_web_action_display`). Stdlib `ThreadingHTTPServer`; every endpoint is a single request/response returning the full authoritative state (`session.snapshot()`); shares formatting helpers with `play.py`. Multi-tenant: a cookie-keyed `SessionRegistry` gives each browser its own game, with an `AGRICOLA_MAX_CONCURRENT_AI` semaphore capping concurrent MCTS searches. The Family `mcts` seat delegates to the C++ `selfplay --move` binary (`_CppMctsAgent`) with the joint model when `cpp/build/selfplay` + `nn_models/cpp_export_best` are present, else falls back to Python MCTS; it plays the **mix leaf** (`_CPP_LEAF_MODE="mix"` / `_CPP_MIX_ALPHA=0.9`, passed through `selfplay --move`'s `--leaf-mode` / `--mix-alpha`; §2.3). Per-game New-Game inputs (Family): seed, sims/move (default 800), opponent prior-mix (default 0); Cards: seed + opponent type. Analysis/MCTS UI is disabled in Cards mode (no trained card bot). Toggles: Fast mode, Confirm turns (undo/confirm), Show analysis (`/api/analyze` → `selfplay --analyze`, async, cancel-on-move, prior-mix 0.05; decoupled from the bot — a control row sends per-request `leaf_mode`/`mix_alpha`/`sims`/`c_uct`, so the human can analyze with the margin/outcome/mix head, any α, any budget, any exploration, changeable mid-game; the overlay denormalizes the tree Q by the analysis leaf's `value_target` — margin points / outcome `[−1,1]` / raw `mix`). `--seats`, `--nn-model` (default `nn_models/best`), `--mcts-sims`, `--host`/`--port`/`--no-browser`. The Download-trace button writes the in-progress game's action log to `agricola-trace-seed<N>.json` for post-hoc debugging/replay.

    play_random_game.py             # Top-level entry point — random-vs-random driver. Plays one full game, prints the scoreboard with per-category breakdown and tiebreaker. `--trace` flag adds a per-round narrative (worker placements, sub-actions, harvest sub-phases).

    play_heuristic_game.py          # Top-level entry point — any-vs-any heuristic-agent driver. `--p0`/`--p1` pick from {random, simple, hubris, hubris_v1, hubris_v2}; `--temperature` for softmax sampling; `--lookahead` toggles the action/turn lookahead horizon. Same scoreboard output as `play_random_game.py`.

    Dockerfile                      # Web-UI deploy image (CLAUDE.md → Web UI & online deployment / DEPLOY.md). Multi-stage: compiles the C++ `selfplay` binary for Linux, then a slim Python layer (stdlib server + numpy) that copies the resolved `cpp_export_best` champion into `nn_models/cpp_export_best/`. Serves `play_web.py` on port 8000.

    .dockerignore                   # Trims the Docker build context (skips tests/data/docs/cpp build artifacts) — but RE-INCLUDES `tests/__init__.py` + `tests/test_utils.py`, which `agricola/agents/base.py` imports at runtime.

    fly.toml                        # Fly.io app config (DEPLOY.md): single always-on machine (`min_machines_running=1`, `auto_stop_machines=false`) so the in-memory game state survives between requests; 2 shared vCPUs / 1 GB RAM; `AGRICOLA_MAX_CONCURRENT_AI=2`.

    DEPLOY.md                       # Beginner-friendly Fly.io deploy walkthrough for the web UI (install flyctl → create → deploy → logs → regions → cost). See CLAUDE.md → Web UI & online deployment.

    deploy.sh                       # One-command Fly.io deploy of the web UI with the current champion (CLAUDE.md → Web UI & online deployment): resolves the `nn_models/cpp_export_best` symlink into the concrete export dir and passes it to the Dockerfile as the `EXPORT_DIR` build-arg (Docker COPY can't follow the symlink), then runs `fly deploy` (extra args forwarded). Promote = re-point the symlink, then `./deploy.sh`.

    CLOUD_RUNBOOK.md                # Operator guide for running the self-play / training / eval loop off the M1 on GCP (CLAUDE.md → the self-play & training workflow (§2.4)): project / budget / bucket setup, the ARM-native C++ build on a T2A instance, launching each loop step, durable upload + VM self-teardown, and the IAM gotchas (self-delete needs `--scopes=cloud-platform` + `compute.instanceAdmin.v1`; bucket writes need `storage.objectAdmin`). Produced the 40k corpus behind `joint_outcome_44k`.

    templates/                      # Web UI assets served by `play_web.py` — the HTML shell.

        index.html                  # Single-page shell `play_web.py` serves; loads `static/app.js` + `static/style.css` and hosts the board DOM the JS populates from the JSON wire format. See CLAUDE.md → Web UI & online deployment.

    static/                         # Web UI assets served by `play_web.py` — frontend JS + CSS.

        app.js                      # The browser frontend (~1.2k lines): fetches game state from `play_web.py`, renders the farmyard / action board / scoreboard, and dispatches the player's chosen action back to the backend. Also hosts the New-Game **mode-select** overlay (Family / Cards), per-player **hand** rendering for Cards mode (face-up `hand` cards grouped by type, or face-down placeholders from `hand_counts`), the `card` ui_hint card-play buttons, and hides the analysis/MCTS controls in Cards mode. The target of FRONTEND_FIXES.md.

        style.css                   # Web UI styling: board layout, farmyard grid, action-space tiles, scoreboard.

    agricola/                       # Game engine package.

        __init__.py                 # Empty package marker.

        constants.py                # Named enums (Phase — incl. the card game's DRAFT — GameMode, HouseMaterial, CellType) plus lookup tables: action-space accumulation rates, MAJOR_IMPROVEMENT_COSTS, ROOM_COSTS, BAKING_IMPROVEMENT_SPECS, FIREPLACE/COOKING_HEARTH_INDICES, BAKING_IMPROVEMENTS. SPACE_IDS / SPACE_INDEX (canonical 25-entry ordering of all action spaces) index BoardState.action_spaces. stage_of_round(round) / STAGE_OF_ROUND map each round to its stage (used by the reveal enumerator to pick the candidate stage cards).

        resources.py                # Resources (wood/clay/reed/stone/food/grain/veg) and Animals (sheep/boar/cattle) frozen dataclasses with __add__/__sub__/__bool__ operators. Extracted from state.py to avoid circular imports with constants.py.

        pasture.py                  # Pasture dataclass (cells, num_stables, precomputed capacity) + compute_pastures_from_arrays BFS that flood-fills from outside the grid to find enclosed connected components. Independent of state.py via duck typing.

        replace.py                  # fast_replace(obj, **changes) — a drop-in faster equivalent of dataclasses.replace, ~20% faster per call (timeit-measured). Used at every state-mutation site in engine.py / resolution.py / pending.py / cards/. See CHANGES.md Change 9.

        opt_config.py               # Runtime toggles for the frontier/accommodation optimizations: PARETO_OPT_LEVEL (0–3, cumulative) and FENCE_SCAN_CACHE (bool). Now default-ON (level 3 + cache); PARETO_OPT_LEVEL=0 + FENCE_SCAN_CACHE=False is the no-op baseline. helpers.py / legality.py read them to dispatch to optimized (caching / algorithmic) paths. See FRONTIER_OPT_DESIGN.md.

        environment.py              # The Environment frozen dataclass — the hidden ground truth + nature policy for one game. Holds the per-game stage-card reveal order (NOT in GameState); exposes resolve(state) (the driver-facing nature seam) and reveal_action(state) -> RevealCard. The dealer in real games; agents and MCTS never see it. (The once-sketched observe(state, env, i) projection was never built, and private hands ended up on PlayerState, not here — CARD_ENGINE_IMPLEMENTATION.md §4.) See HIDDEN_INFO_DESIGN.md §3.4 / §3.6.

        state.py                    # All frozen state dataclasses: Cell, Farmyard (with cached pastures), ActionSpaceState (with revealed: bool common-knowledge flag), PlayerState (incl. `fences_in_supply: int = 15` — the stored fence-supply pile (location 4), distinct from "buildable"; maintained in BOTH modes (decremented per fence build, so it equals 15−built in Family) and NOT a skip-field, so it IS serialized in Family and the C++ PlayerState mirrors it — the one C++ touch of the fence cost slice; COST_MODIFIER_DESIGN.md §9.7), BoardState, GameState — plus get_space / with_space free-function helpers for keyed access to BoardState.action_spaces (a canonical-ordered tuple). The hidden reveal order is NOT on BoardState — it lives in the Environment. The top-level GameState snapshot — every transition produces a new one via fast_replace — is fully hashable, and each hot state dataclass caches its `__hash__` (lazily, pickle-stripped) for the MCTS transposition table (SPEEDUPS.md S5).

        canonical.py                # Canonical, deterministic GameState↔JSON (`dumps`/`loads`) — the shared serialization CONTRACT the C++ engine must reproduce byte-for-byte (CLAUDE.md → The C++ twin engine, CPP_ENGINE_PLAN.md §3.1). Tag-driven generic dataclass walker (drift-proof); test/interop scaffolding only, not on any production path. Hosts _DEFAULT_SKIP_FIELDS — the card-only fields omitted at their defaults, which is what keeps the Family JSON byte-identical (CARD_ENGINE_IMPLEMENTATION.md §4).

        cost.py                     # Cost-resolution data types + the Pareto-min over payments (COST_MODIFIER_DESIGN.md): PaymentOption = Resources | ReturnImprovement, CostCtx (action_kind + base + modifier discriminators incl. reserved_animals), pareto_min_over_goods. Dependency-light so actions/legality/resolution all import it without cycles; the chokepoint itself (effective_payments/can_pay) lives in legality.py. See CARD_ENGINE_IMPLEMENTATION.md §5.

        setup.py                    # setup_env(seed, *, card_pool=None, draft=False) -> (GameState, Environment) — the full constructor. card_pool=None → the Family game (byte-identical RNG path); card_pool=CardPool(occupations, minors) → GameMode.CARDS with 7+7 hands dealt (draft=True instead deals four draft pools and returns a Phase.DRAFT state driven via CommitDraftPick). Builds the per-stage shuffled reveal order into the Environment, pre-deals round 1, returns the round-1 WORK state. setup(seed) = setup_env(seed)[0]. All randomness (starting player, hands/pools, card shuffle) resolves here via a seeded NumPy RNG; the engine is fully deterministic afterward.

        helpers.py                  # Pure derived-quantity functions (fences_built (board fence count) + buildable_fences (stored supply pile + on-card pools = pieces still placeable — replacing the old derived fences_in_supply), stables_in_supply, cooking_rates 4-tuple, enclosed_cells) and the Pareto frontier helpers (extract_slots — which folds in the card capacity modifiers, CARD_ENGINE_IMPLEMENTATION.md §5.4 — can_accommodate, pareto_frontier, breeding_frontier, food_payment_frontier, harvest_feed_frontier).

        actions.py                  # All Action dataclasses (PlaceWorker, ChooseSubAction, the full Commit* family — incl. the card game's CommitPlayOccupation/CommitPlayMinor/CommitCardChoice/CommitChooseCost/CommitFoodPayment/CommitFamilyGrowth and the wide commits carrying an explicit PaymentOption — FireTrigger (+ variant), Stop, Proceed (the host work-complete flip), RevealCard, CommitDraftPick) plus the CommitSubAction marker base used by the generic commit dispatcher. RevealCard and CommitDraftPick are top-level transitions, not CommitSubActions.

        pending.py                  # All Pending* frozen dataclasses (sub-action + parent + wrapper variants, plus the PendingReveal nature/phase frame with player_idx=None), the PendingDecision union alias, the ACTION_SPACE_/SUBACTION_PENDING_IDS event-routing buckets, and the three pure stack ops (push, pop, replace_top). Every host frame carries phase ("before"/"after") + triggers_resolved. The card game adds its own frames (play/choice/food-payment/draft/phase hosts + PendingGrantedBuildFences + FenceRestrictions) and default-skip fields on the Family frames (PendingBuildFences' deferred tally; PendingPlow's stranding/multi-shot grant fields) — the full census: CARD_ENGINE_IMPLEMENTATION.md §4.

        legality.py                 # Top-level legal_actions (stack-state dispatch) + legal_placements (mode-dispatched: FAMILY_GAME_LEGALITY vs CARD_GAME_LEGALITY) + per-space placement predicates + shared helpers (_can_bake_bread, _can_build_stable, …) + per-pending sub-action enumerators (incl. _enumerate_pending_reveal, the ≤3 candidate RevealCards for the round being entered, derived purely from public state). Also home to the card seams: the cost-modifier chokepoint effective_payments/can_pay, the food-affordability gates (_payable/_liquidatable_to/_payable_occupation), trigger_event (event derivation) + _eligible_fire_triggers, and the *_EXTENSIONS registries (bake-bread, occupancy-override, renovate-target, baking-spec). See CARD_ENGINE_IMPLEMENTATION.md §2/§3/§5.

        resolution.py               # Atomic _resolve_<space> handlers, non-atomic _initiate_<space> + _choose_subaction_<space> handlers, sub-action _execute_<sub_action> effect functions (incl. the card-play executors _execute_play_occupation/_execute_play_minor and the food-payment _execute_food_payment/_resume), _enter_after_phase (the uniform "after-window opens" seam that fires after-automatic effects), and the function-pointer dispatch tables (ATOMIC_HANDLERS, NONATOMIC_HANDLERS, CHOOSE_SUBACTION_HANDLERS).

        scoring.py                  # score(state, player_idx) -> (total, ScoreBreakdown) and tiebreaker — end-game evaluation across all categories (fields, pastures, animals, rooms, people, majors, craft bonuses, begging penalties) plus the card scoring seams: SCORING_TERMS/register_scoring (per-card bonus terms), SCORING_GROUPS/register_scoring_group (mutually-exclusive groups, best owned member only), and each kept minor's printed vps.

        engine.py                   # The transition engine: step + _apply_action dispatch (incl. the RevealCard / Proceed / CommitDraftPick branches) + _advance_until_decision (incl. the Delegating-host auto-advance + the DRAFT walk) + phase resolvers (_resolve_return_home, the two-state PREPARATION reveal walk — push PendingReveal then _complete_preparation — _resolve_harvest_field, _initiate_harvest_feed, _initiate_harvest_breed) + the COMMIT_SUBACTION_HANDLERS metadata table for generic commit dispatch. Also the card firing seams: _apply_proceed, _fire_subaction_before_auto, _apply_fire_trigger (record-before-apply), _clear (scoped used-sets), _fire_ready_one_shots (the conditional-latch sweep), _collect_future_rewards + _fire_preparation_hook / _fire_harvest_field_hook (CARD_ENGINE_IMPLEMENTATION.md §2).

        fences.py                   # Four layered pasture-shape universes (FULL=1518 / FAMILY=762 / EXTENDED=193 / RESTRICTED=109) with PastureCandidate edge-metadata entries, fence-array pack/apply helpers, and the compute_new_fence_edges cost helper. Standalone module, no engine dependencies.

        fence_universe.py           # Experimental tooling for swapping the active fence universe: the active_universe(spec) context manager (named universes or explicit triples), restrict_to(predicate, base=...) builder for derived universes, NAMED_UNIVERSES registry, and current_universe() accessor.

        cards/                      # Card framework (registries + shared helpers) + one module per implemented card (~290 modules, all imported in cards/__init__.py). NOTE: this tree lists only the framework modules + a few exemplar cards; the per-card set is deliberately non-exhaustive here (ledger: CARD_IMPLEMENTATION_PROGRESS.md; machinery: CARD_ENGINE_IMPLEMENTATION.md §3).

            __init__.py             # Imports every card module (~290) + the framework modules so their register_*() calls fire at load time, populating all the registries of CARD_ENGINE_IMPLEMENTATION.md §3. Wire new cards here at integration, never mid-batch.

            triggers.py             # The firing registries: TRIGGERS/CARDS (optional + mandatory-with-choice triggers, register()), AUTO_EFFECTS (register_auto + apply_auto_effects, any_player routing), the hosting indexes (OWN_/ANY_PLAYER_HOOK_CARDS + should_host_space; HARVEST_FIELD_CARDS; START_OF_ROUND_CARDS + should_host_preparation), CONDITIONAL_ONE_SHOTS (the level-triggered latch), CARD_CHOICE_RESOLVERS, PLAY_VARIANT_TRIGGERS. See CARD_ENGINE_IMPLEMENTATION.md §2–§3.

            specs.py                # The play-card registries: OccupationSpec / OCCUPATIONS + register_occupation; MinorSpec / MINORS + register_minor + prereq_met (cost, "/"-alternative alt_costs, scaling cost_fn, occupation-count + custom prereqs, passing_left circulation, printed vps, on_play). Plus PLAY_OCCUPATION_VARIANTS (pay-on-play choices, Roof Ballaster), OCCUPATION_FOOD_SOURCES (Paper Maker's gate simulation), FOOD_PAYMENT_RESUMES (post-food-payment grant continuations).

            cost_mods.py            # Cost-modifier registries + fold accessors read by the effective_payments chokepoint in legality.py (COST_MODIFIER_DESIGN.md): register_formula / register_reduction / register_conversion / register_base_route (the three modifier kinds + non-resource routes) and, for fences, the three free-fence registries FREE_FENCE_SEEDS (per-action budget — free_fence_budget_for), FREE_FENCE_EDGES (per-edge positional — positional_free_edge_count), FREE_FENCE_POOLS (persistent on-card pool — free_fence_pool_remaining / spend_fence_pools). Ownership-gated; all registries empty (no-op) in the Family game.

            consultant.py           # Occupation (B102): on play, +3 clay (2-player branch).
            priest.py               # Occupation (A125): on play, if clay house with exactly 2 rooms, +3 clay/2 reed/2 stone.
            stable_architect.py     # Occupation (A98): scoring term (+1 VP per unfenced stable) via register_scoring; no-op on play.
            market_stall.py         # Minor (B8, passing): cost 1 grain, on play +1 veg, then circulate to the opponent.

            rammed_clay.py          # Minor (A16): on-play +1 clay + a build_fence CONVERSION (clay substitutes for wood 1:1, unlimited).
            briar_hedge.py          # Minor (E16): the first POSITIONAL per-edge free-fence card — board-perimeter fence edges cost no wood, ungated; prereq 1 animal of each type.
            field_fences.py         # Minor (C16): GRANTS an OPTIONAL Build Fences action (via the PendingGrantedBuildFences wrapper) with a grant-scoped positional discount (edges next to a field tile are free); cost 2 food.
            ash_trees.py            # Minor (E74): on play moves up to 5 fences from the supply pile onto the card (a persistent CardStore free-fence POOL), spent free when building (the third free-fence source); prereq 2 planted (sown) fields.
            hunting_trophy.py       # Minor (D82, 1 VP): 1-boar cost with an on-play cook-for-food bonus (cooking_rates), a +3 free-fence seed on Farm Redevelopment, and a "1 building resource of your choice less" conversion on improvements built via House Redevelopment (gated on a PendingHouseRedevelopment frame on the stack).
            mini_pasture.py         # Minor (B2): the first RESTRICTED grant — on play, MANDATORY-fence a free NEW 1×1 enclosure (FenceRestrictions exact_size=1 / forbid_subdivision / max_pastures=1; build_fences_action=False); unplayable unless such a 1×1 is buildable (its prereq); cost 2 food.

            potter_ceramics.py      # "Exchange 1 clay for 1 grain before each Bake Bread action, at most once per action." Historically the single forward-compat card that validated the trigger machinery; now an ordinary dealable minor among the ~290.

            harvest_conversions.py  # HARVEST_CONVERSIONS registry + HarvestConversionSpec dataclass + register_harvest_conversion(). Three built-in entries: joinery (1 wood -> 2 food), pottery (1 clay -> 2 food), basketmaker (1 reed -> 3 food); card entries add side_effect_fn (VP banking) and multi-variant once-per-harvest via prefix-matched harvest_conversions_used. Scope: printed feeding-phase conversions ONLY (other timings live on the window ladder — harvest_windows.py).

            harvest_windows.py      # The harvest timing-window system (CARD_ENGINE_IMPLEMENTATION.md §5b; design of record HARVEST_WINDOWS_DESIGN.md): the 15-id ladder (HARVEST_WINDOWS — simple-window ids double as trigger/auto event strings; field_phase/feeding/breeding are sentinels) + the virtual walk decode (walk_position — the FIELD band repeated per player, ruling 3); the hosting index (register_harvest_window_hook); skips (register_harvest_skip); take-modifiers (register_take_modifier — auto/choice/replace kinds, TakeFold, claim-aware order-sorted folds); the payload-bearing occasion registries (register_harvest_occasion_auto/_trigger + maybe_host_occasion_triggers); breeding-outcome autos (register_breeding_outcome_auto); feeding-requirement folds (register_feeding_requirement). Consumed by engine._advance_harvest / _field_phase_step.

            capacity_mods.py        # Animal-capacity modifier registries read by helpers.extract_slots: HOUSE_CAPACITY_MODS (flexible house slots — max-fold, Family default 1 = the pet; Animal Tamer) and PASTURE_CAPACITY_MODS (flat per-pasture bonus — sum-fold, default 0; Drinking Trough). CARD_ENGINE_IMPLEMENTATION.md §5.4.

            schedules.py            # Deferred-goods/effects helpers for "place on future round spaces" cards: schedule_resources (goods → future_resources), schedule_effect (round-start grant hooks → future_rewards; Handplow), schedule_animals (animals → future_rewards, auto-accommodated at round start; Acorns Basket).

            display.py              # UI-only CardStore surfacing for the web UI (the engine never reads it): live banked-VP emblems for history-derived scoring cards + state badges (Interim Storage's held goods, Moldboard Plow's uses left).

        agents/                     # Agent implementations: random + heuristics. Built atop the engine's pure `step` / `legal_actions` interface.

            __init__.py             # Re-exports Agent / HeuristicAgent / RandomAgent / SimpleHeuristic / HubrisHeuristic[V1,V2,V3] / HubrisHeuristicV1Differential / HubrisHeuristicV3Differential / HeuristicConfig / HeuristicConfigV3 / DEFAULT_CONFIG / DEFAULT_CONFIG_V3 / CONFIG_V1_T2 / evaluator functions (+ differential variants + `compose_evaluators`, `make_differential_evaluator`, `r1_force_forest_bonus`) / play_game / restricted_legal_actions / strict_restricted_legal_actions / make_strict_restricted_legal_actions / MCTSAgent / MCTSSearch / MCTSNode / MacroFencingAction + priority constants.

            base.py                 # `Agent` Protocol, decider_of helper (-> int | None; None = nature's round-card reveal, routed to the dealer), RandomAgent, generic HeuristicAgent (1-turn or 1-action lookahead, singleton-skip always on, softmax-with-temperature action selection; its `_eval` helper averages the evaluator over the ≤3 reveal outcomes at a nature node rather than evaluating the between-rounds state), play_game(initial, agents, dealer) game-driver (the dealer — typically env.resolve — resolves reveals; agents never see a nature node). Both agent classes accept a `legal_actions_fn` kwarg (default = unrestricted `legal_actions`) threaded through every legality consultation.

            heuristic.py            # All heuristic agent code. HeuristicConfig + evaluate_simple/evaluate_hubris_v1/_v2 + SimpleHeuristic / HubrisHeuristicV1 / V2 (V1-era). CONFIG_V1_T2 (round-2-tuned V1 constant). HeuristicConfigV3 + evaluate_hubris_v3 + HubrisHeuristicV3 (current main heuristic). Opt-in V3 config fields default 0: `wood_flat_bonus`, `temperature`, `r1_force_forest_bonus`. `compose_evaluators(*evaluators)` sums callables additively. Standalone `r1_force_forest_bonus(state, p, cfg)` helper available alongside the config field. Differential wrappers: `make_differential_evaluator(base)`, `evaluate_hubris_v3_differential`, `evaluate_hubris_v1_differential`, `HubrisHeuristicV3Differential`, `HubrisHeuristicV1Differential`. All V1 helpers (family-future, empty-room, location bonuses, SP, renovation, major-override, food/begging) are shared duck-typed across V1/V3 configs. Subclasses forward the `legal_actions_fn` kwarg to the base. See V3_DESIGN.md and HUBRIS_V1_NOTES.md.

            restricted.py           # Action-pruning wrappers over `legal_actions(state)`. Exports `restricted_legal_actions(state)` (regular: ordering / cell-priority / room-cap / first-pasture / min-begging), `strict_restricted_legal_actions(state)` (strict MCTS variant adding Cultivation sow-max, Grain-Util veggie auto-max, 9 fencing patterns, harvest-feed cap of top-5-V3 + 2 random), and `make_strict_restricted_legal_actions(*, config, rng)` factory for injected RNG/config. Priority constants (STABLE_PRIORITY, ROOM_PRIORITY, PLOW_PRIORITY, FIRST_PASTURE_REQUIRED_CELLS, MAX_TOTAL_ROOMS). Every filter routes through `_safe_narrow` so neither wrapper empties a non-empty input. See CHANGES.md Change 11 (regular wrapper) and MCTS_DESIGN.md §7 (strict additions).

            mcts.py                 # MCTS agent. `MCTSNode` (identity equality, lazy `_legal_actions` cache, `macro_sequences` on fencing-trigger parents, `is_chance` + `chance_counts` for round-card reveal nodes), `MCTSSearch` (transposition table + per-search RNG + cached HubrisHeuristicV3 for greedy macros), `MCTSAgent` (vanilla UCT with FPU, path-only backprop, softmax action selection at T=0.2). **Optional PUCT** (POLICY_PUCT_DESIGN.md): pass `policy_fn(state, legal_actions) -> {action: prior}` + `fence_mode=FenceMode.FLATTEN` to `MCTSSearch`, and `_select_via_puct` replaces UCB with AlphaZero `Q + c·P·√ΣN/(1+n)` over all legal actions (`policy_fn=None` selects UCT, PUCT otherwise); priors are computed lazily (`_ensure_priors`, split from `_compute_legal_actions`). Both modes **step through forced (singleton) moves** before evaluating the leaf (so V is queried at real decisions, not mid-action singletons; UCT is therefore no longer byte-identical to the pre-PUCT engine). `uniform_policy` is the c0 placeholder prior, `root_visit_distribution(root)` exposes the root π. `FenceMode`: MACRO (UCT macros) / FLATTEN (per-pasture commits, required for PUCT) / SEQUENCE_PRIOR (c3, not yet implemented). Hidden reveals are explicit chance nodes: `_chance_route` round-robins over the ≤3 candidate RevealCards (reconstructed from public state — no Environment), they are never leaf-evaluated, and carry a P0 frame label (decider=0) so backprop/UCB are unchanged. Macro-fencing for both trigger points (PlaceWorker("fencing") + ChooseSubAction("build_fences") at PendingFarmRedev), with explicit entry/exit phases handling the outer PendingFencing wrapper. Tree reuse via `re_root(new_root)` (prunes transpositions to live subtree). `MacroFencingAction` is the MCTS-internal action type; the engine never sees it. See MCTS_DESIGN.md §4-5.

            nn/                     # NN value-function infrastructure (subpackage). Schema, recording, and encoder are torch-free so data-generation scripts don't pay the import cost; dataset / model / training / agent import torch and must be imported explicitly (not re-exported from `__init__.py`). See FIRST_NN.md §11.1 for the file-by-file rationale.

                __init__.py         # Re-exports the torch-free public surface (`DATA_VERSION`, `ENCODING_VERSION`, `ENCODED_DIM`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `compute_winner`, `load_game_records`, `play_recording_game`, `encode_state`, `feature_names`) so external code can `from agricola.agents.nn import X` regardless of internal layout. Torch-using submodules (`dataset`, `model`, `training`, `agent`) require explicit imports.

                schema.py           # On-disk dataset schema. `DATA_VERSION` constant (currently **3**) + hard-fail load check (`DataVersionMismatch`). Frozen dataclasses: `DecisionSnapshot` (state + chosen_action + decider_idx, plus optional `visit_distribution` — the search's raw root visit counts π — and `root_value` — the P0-frame root value estimate; both default None and are populated ONLY by MCTS self-play recording, the v2→v3 bump), `GameRecord` (game-level metadata + final scores + winner + terminal_state + decisions tuple). `load_game_records(path)` loader + `compute_winner(s0, s1, tb0, tb1)` helper.

                recording.py        # `play_recording_game(initial_state, p0_agent, p1_agent, *, metadata, legal_actions_fn=restricted_legal_actions)` — plays one full game, captures every non-singleton state as a `DecisionSnapshot` (state recorded BEFORE the agent call so the snapshot matches what the agent saw), then captures terminal state + final scores + tiebreakers + winner into a complete `GameRecord`. Deterministic given pre-seeded agents.

                selfplay_recording.py # MCTS self-play recording driver (`DATA_VERSION` 3) — the self-play sibling of `recording.py`. `RootCapturingMCTSAgent` (an `MCTSAgent` subclass that stashes the searched root via `_select_action_with_temperature`, no edit to `mcts.py`) + `play_selfplay_recording_game(initial_state, agent, *, dealer, …)`: plays one SHARED-tree game (a single agent drives both seats), steps through forced (singleton) moves uninvoked, and records each non-singleton decision's state + chosen_action + root visit distribution π + P0-frame `root_value` into a v3 `GameRecord`. Torch-free at module level (the NN leaf rides in via the passed agent).

                trace_replay.py     # C++↔Python interop (CLAUDE.md → The C++ twin engine): the game-trace serde + the replay adapter. `game_to_trace` (writer) / `replay_trace(trace) -> GameRecord` (reads a C++-emitted `agricola-cpp-trace-v1` trace, replays it through the engine, rebuilds a v3 `GameRecord` with π + root_value) / action↔`params` serde for all 17 action types (closes the web-UI `RevealCard.card` drop). Lets C++-generated self-play feed the unchanged training pipeline. See CPP_ENGINE_PLAN.md §2.

                encoder.py          # Input-vector encoder. `ENCODING_VERSION` + `ENCODED_DIM=170`. `encode_state(state, player_idx) -> np.ndarray` (float32) translates a `GameState` into the flat ~170-feature vector specified in FIRST_NN.md §4: own-player block (54) + opponent block (54) + shared/board (54) + mid-action singletons (8). Numpy-only — the training pipeline converts at the model boundary via `torch.from_numpy(arr)`. `feature_names()` returns the parallel string list for debugging / per-feature analysis. The MCTS-inference hot path goes through `encode_for_inference` (a swap-aware per-state memo) + `swap_perspective`, layered over an index-writer rewrite of `encode_state` (byte-identical to the original; the `(name,value)` `_assemble` is kept as the golden-test oracle + `feature_names` source). See SPEEDUPS.md S10–S13. ALSO hosts the **candidate encoder** (`encode_state_candidate`, 178 features, tag `cand_feat178_v1`: running-score + turns-to-feeding + renovate/grow bits, begging removed) + `begging_margin` + the **`EncoderSpec` registry** (`ENCODERS` / `ENCODER_V2` / `ENCODER_CANDIDATE`) — the forward-compatible encoder-by-tag dispatch the joint path threads (mirrored in C++ `encoder_for_tag`).

                dataset.py          # PyTorch dataset builders. `build_datasets(run_dirs, ...)` / `build_datasets_from_games(games, ...)` load `GameRecord`s, split games by index into train/val/test, expand each game's non-singleton snapshots + terminal state into `_ExampleDescriptor`s (state-keyed, dual-perspective on the same key), encode in numpy, fit `NormStats` (per-feature input mean/std + scalar target-margin std) on the training split only, and return three `AgricolaValueDataset`s + the fit `NormStats`. Imports torch. Not re-exported from `__init__.py`.

                model.py            # PyTorch model + normalization wrapper. `ConfigurableMLP` (configurable input_dim / hidden_dims / activation / dropout / norm; composable as a sub-encoder via `output_dim`), `NormalizedValueModel(net, stats)` (wraps a net with fixed input/output normalization buffers; `forward` returns normalized output, `predict_margin` returns raw margin units), `NET_REGISTRY` (name → factory), `EncodingVersionMismatch`. `save(path)` / `load(path)` checkpoint helpers preserve the `NormStats` + the model state in one file. `model_device(model)` caches the (constant CPU) inference device — the eager `next(model.parameters()).device` walked the module tree on every forward (SPEEDUPS.md S13). Imports torch.

                training.py         # Training-loop library. `train(run_dirs, out_dir, ...)` programmatic entry runs the full pipeline (load → split → fit norm → AdamW + early-stop on val MSE → checkpoint + curves + calibration plot + metadata JSON). Smaller helpers (`train_one_epoch`, `evaluate`, `setup_seeds`, `make_run_id`, `current_git_sha`, `print_header`, `print_epoch_line`, `save_curves_plot`, `save_calibration_plot`) factored out so future training experiments can compose differently. `l2sp` (L2-SP anchor `λ·‖θ−θ₀‖²` toward the `init_from` warm-start weights — a trust region; requires a warm-start) and `save_all_epochs` (write `epoch_NNN.pt` each epoch for gameplay-based checkpoint selection) added for the FIRST_NN C20 self-play fine-tunes. Library — the CLI wrapper lives at `scripts/nn/train_first.py`. Imports torch.

                agent.py            # `NNAgent(model, *, differential=True, ...)` — `HeuristicAgent` subclass using an NN-backed evaluator. Two evaluators: `nn_evaluator` (single forward pass), `nn_evaluator_differential` (batched 2-input forward; exactly antisymmetric `V_diff(s, 0) = -V_diff(s, 1)` by construction). `model.eval()` set at construction; queries run under `@torch.no_grad()`. Drop-in replacement for `HubrisHeuristicV3` in `play_game` / `play_match.py`. Imports torch.

                policy_heads.py     # `DecisionHead` spec + the `HEADS` registry — 7 fixed-vocab heads (placement / choose_subaction / commit_build_major / commit_sow / commit_bake / fencing / build_stop; owns/vocab/target_index/legal_mask). ALSO the `PointerHead` spec + `POINTER_HEADS` registry (`animal_frontier`, `harvest_feed`) for variable-cardinality Pareto frontiers — owns/candidate_dim/enumerate_candidates (re-derives the engine frontier with a small action-delta per candidate). `fencing` (110: 109 RESTRICTED shapes + Stop) is spatially blind; `build_stop` (2-way) learns P(stop) for multi-shot rooms/stables. The factored policy: dataset/model/training/prior are head-driven, so adding a head is a new spec here, not new modules. Torch-free. See POLICY_HEAD.md.

                policy_dataset.py   # Policy-head dataset (behavioral cloning). `PolicyNormStats` (input-norm only), `AgricolaPolicyDataset`, `_decision_rows(games, head)` (head-driven single-perspective extraction), `build_policy_datasets[_from_games](..., head=...)`. Streams worker pickles (memory-bounded). For the `awr` loss variant, computes advantage weights `clip(exp((R−V_θ(s))/β), 0, w_max)` from a value-net baseline. Imports torch.

                policy_model.py     # `NormalizedPolicyModel` — input-normalized classifier (`head.num_classes` logits) with masked softmax (illegal classes → prob 0; all-illegal guard). Persistence mirrors `NormalizedValueModel` (meta sidecar carries `model_kind="policy"` + the `head` name; ENCODING_VERSION hard-checked). Imports torch.

                policy_training.py  # `train_policy(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)` — weighted masked cross-entropy, top-1/top-3 (+winners-subset) metrics, early-stop on val CE. `--init-from` warm-starts the trunk from a value OR policy checkpoint (shape-tolerant transplant; head layer stays fresh). CLI: scripts/nn/train_policy.py. Imports torch.

                policy_pointer_dataset.py # Pointer-head dataset (BC over ragged frontiers). `PointerNormStats` (norm over `[state ; cand]`), `AgricolaPointerDataset` (state stored once per snapshot, flat candidates sliced by offsets), `pointer_collate` (flatten a batch → state/cand/segment/chosen_flat/weight; no padding), `_pointer_rows`, `build_pointer_datasets[_from_games]`. Reuses `_seed_split` + `_compute_awr_weights`. Imports torch.

                policy_pointer_model.py # `NormalizedPointerModel` — per-candidate scorer over `[state ; cand]` rows (`score_flat` for the segment batch, `candidate_probs` for inference) + `segment_log_softmax` (per-segment normalize via scatter_reduce-amax + index_add_). Persists `model_kind="policy_pointer"` + candidate_dim. Imports torch.

                policy_pointer_training.py # `train_pointer(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)` — weighted SEGMENT cross-entropy, within-frontier top-1/top-3 (+winners), early-stop on val CE. Mirrors train_policy artifacts (pointer_norm_stats.json). CLI: scripts/nn/train_policy_pointer.py. Imports torch.

                policy.py           # `policy_prior` (fixed heads) + `pointer_prior` (pointer heads) + `NO_PRIOR`, and `make_policy_fn(models)` / `load_policy_fn(checkpoints)` — the full `policy_fn(state, legal) -> {action: prior}` MCTS/PUCT consumes. Works over the FULL legal set, dispatching by decision type: fixed head / pointer head / `build_stop` (learned P(stop) + cell-priority build cell for multi-shot rooms&stables) / uniform over the cell-priority-filtered set (plow + first-build cells — no encoder signal) / uniform over full legal (the rest). The prune lives entirely in the policy. `make_policy_fn` puts the loaded heads in `eval()` mode — `load()` leaves them in TRAIN mode, which made PUCT priors nondeterministic (dropout active); see SPEEDUPS.md. Imports torch.

                shared_model.py     # `SharedTrunkModel` (Phase 2.3 Stage B, SHARED_TRUNK.md): the joint value+policy net — one `170 → trunk → E` trunk (+ embed_norm) feeding a **margin** value head, a co-trained **outcome** value head (`E→1`, regresses `sign(margin)`; §2.3), + 7 fixed + 2 pointer heads, all reusing `ConfigurableMLP`. Pointer heads score `[embedding ; candidate]` (trunk run once, candidate concatenated). The outcome head loads optionally (backward-compatible with pre-outcome checkpoints). Architecture-agnostic (every width a ctor arg); preserves `predict_margin`/`value_scale` (+ `predict_outcome`/`outcome_scale`); `config_dict()` + `NET_REGISTRY`. Imports torch.

                shared_dataset.py   # One-pass, **per-pickle-chunk-cached** joint dataset (`build_shared_datasets`): reads each run dir's pickles once → value rows (both perspectives + terminal, margin) + fixed-head rows (mask + soft-π) + pointer-head rows (candidates + soft-π), consistent split. Writes `shared_<encoder.tag>_chunks/` (encode peak = one pickle — the memory fix; the per-dir-accumulation version OOM'd). **Finalize is also memory-load-bearing**: `_finalize_payloads` streams chunk *paths* lazily from disk (never loads a whole run dir) and builds the value tensor **directly into its per-split arrays** (never a combined `value__X` — that doubled when mask-sliced and OOM'd at 57k); see SHARED_TRUNK.md §3 before refactoring. Takes an `encoder: EncoderSpec` (default v2; candidate re-encodes the same raw games to its own cache + begging-strips the value target). The per-pickle encode is **parallel** (`n_workers` → a `multiprocessing.Pool`, byte-identical to serial) and **truly resumable** (completeness = all chunks present under the matching roster, so a kill mid-encode just fills the gaps). Reuses the existing dataset classes. Imports torch.

                shared_training.py  # Joint trainer (`train_shared`; CLI scripts/nn/train_shared.py): interleaves per-task batches through the shared trunk — **soft-π** CE (fixed + segment for pointer) + margin MSE + (with `--train-outcome`, default ON) the **outcome** head's `sign(margin)` MSE co-trained in the value-task batch off the same embedding, **per-head gradient balancing** (equal-frequency sampling), `_CyclicTensor` fast-loader, early-stop on **value val-MSE** + `--save-all-epochs` (pick by play). Imports torch.

                shared_policy.py    # `make_joint_fns(model, *, leaf_mode, margin_scale, outcome_scale) -> (value_fn, policy_fn)` — the MCTS adapter for `SharedTrunkModel`. **One trunk forward per node**: margin, outcome, and policy all read off ONE memoized embedding (value sign-flipped to P0), so `mcts.py` is unchanged. `leaf_mode` ∈ margin / outcome / mix selects the value leaf (margin default; mix = the 50-50 normalized-Q average, §2.3 — the tunable-α blend lives in the C++ search). `policy_fn` mirrors `make_policy_fn`'s dispatch off the shared embedding; terminal short-circuit. Imports torch.

    tests/                          # pytest test suite — per-file coverage descriptions in TEST_DESCRIPTIONS.md.

        __init__.py                 # Empty package marker.

        conftest.py                 # Shared pytest fixtures. Autouse `_reset_opt_config` snapshots/restores `agricola.opt_config` flags and clears the frontier/fence lru_caches between tests, so the cross-level tests that flip `PARETO_OPT_LEVEL` / `FENCE_SCAN_CACHE` never leak state.

        factories.py                # Prefabricated-state helpers (with_resources, with_animals, with_majors, with_grid, with_pending_stack, etc.) for composing test states — including states unreachable through gameplay. Project-wide convention for test setup.

        test_utils.py               # Test infrastructure (not a test file): run_actions for scripted multi-action walks, random_agent_play driver, and the IMPLEMENTED_NON_ATOMIC_SPACES / filter_implemented action filter (forward-compat as new action types land).

        test_state.py
        test_helpers.py
        test_scoring.py
        test_legality_atomic.py
        test_legality_non_atomic.py
        test_resolution_atomic.py
        test_engine.py
        test_reveal.py
        test_grain_utilization.py
        test_potter_ceramics.py
        test_bake_bread.py
        test_farmland.py
        test_cultivation.py
        test_side_job.py
        test_animal_markets.py
        test_major_improvement.py
        test_house_redevelopment.py
        test_farm_expansion.py
        test_fences.py
        test_fencing.py
        test_farm_redevelopment.py
        test_harvest_field.py
        test_harvest_feed.py
        test_harvest_breed.py
        test_harvest_integration.py
        test_replace.py
        test_agents_heuristic.py
        test_restricted_actions.py
        test_mcts.py
        test_frontier_opt.py
        test_nn_records.py
        test_nn_encoder.py
        test_nn_dataset.py
        test_nn_model.py
        test_train_first_nn.py
        test_nn_agent.py
        test_nn_policy.py
        test_generate_nn_training_data.py
        test_validate_nn_dataset.py
        test_cpp_canonical.py           # C++-port differential gates (CLAUDE.md → The C++ twin engine / CPP_ENGINE_PLAN.md):
        test_cpp_trace_replay.py        #   canonical serde, trace replay, state model + flood-fill,
        test_cpp_state.py               #   legality, step/scoring, encoder, NN value+policy, MCTS,
        test_cpp_legality.py            #   and the C++ self-play data-gen pipeline — each asserting
        test_cpp_step.py                #   the C++ engine matches the Python oracle. Skip if cpp/ unbuilt.
        test_cpp_binding.py
        test_cpp_nn.py                  #   (incl. `test_cpp_outcome_matches_python`: C++ outcome head ≤1e-4, §2.3)
        test_cpp_mcts.py
        test_cpp_selfplay.py
        test_cpp_selfplay_pipeline.py
        test_subaction_hook_lifecycle.py
        test_space_host_lifecycle.py
        test_space_host_hooks.py
        test_subaction_hooks.py

    scripts/                        # Out-of-tree utilities — profiling, benchmarking, tuning. Re-runnable; not imported by `agricola/` or `tests/`. Used to produce / update PROFILING.md and the tuned-config JSONs in `tuned_configs/`.

        profile_engine.py           # Three-workload runner (A: random from setup; B: random from wealthy prefab; C: micro-bench across 9 prefab states) with cProfile + wall-clock.

        card_text.py                # Card-text lookup CLI (CARD_AUTHORING_GUIDE.md §1 step 1). `python scripts/card_text.py "<name or slug>" [...]` searches `agricola/cards/data/revised_*.json` by name/slug and prints each card's VERBATIM text + cost/prereq/vps/passing + deck/number/category, and marks whether it is already IMPLEMENTED (slug registered in OCCUPATIONS/MINORS). Use it to honor the rule "read a card's exact text before reasoning about or implementing it" (never paraphrase). `--exact` for full-name match.

        verify_web_sync.py          # Web-UI regression harness (CLAUDE.md → Web UI & online deployment). HTTP-drives a live `play_web.py` server and asserts the client-rendered state == the server's authoritative state across the move (farmland→plow), undo, confirm-turns, new-game, and opponent-mix flows. Prints "RESULT: ALL CHECKS PASSED". Guards the single-channel request/response invariant.

        profile_states.py           # 9 prefab `GameState` factories covering early/mid/late game; the round-14 state alone makes every non-`lessons` space legal (the coverage requirement for Workload C).

        count_replaces.py           # Monkey-patch counter for `dataclasses.replace` / `fast_replace` call shapes.

        bench_replace.py            # `timeit`-based microbenchmark comparing stdlib replace vs `fast_replace`.

        bench_shared_tree.py        # Benchmark: MCTS-vs-MCTS per-game wall time, shared tree (one `MCTSAgent`/`MCTSSearch` driving both seats — MCTS_IMPLEMENTATION.md §11.2 mode 2) vs separate trees (one per seat), at a fixed sim budget. Production NN-leaf PUCT config (value net + combined policy, FLATTEN, full legality); model + policy loaded and warmed up in the pool initializer (untimed) so only `play_game` is measured, `torch.set_num_threads(1)` per worker. Measured a ~1.4–1.6× shared-tree speedup at 500 sims (shared re-rooted nodes inherit the opponent's visits, so `cap_total_sims` runs fewer fresh sims).

        profile_frontier_helpers.py # Frontier/accommodation optimization profiler (FRONTIER_OPT_DESIGN.md §8.2). `--mode microbench` times each Pareto/feeding helper per-call over the 9 prefab states at a given `--level`; `--mode collision` wraps the helpers during one MCTS game and reports the projection-collision hit rate a perfect cache would achieve (the Phase-2/3 gate). Runnable independent of whether the optimizations are enabled.

        profile_mcts_nn.py          # THE production MCTS profiler — NN value leaf + 9-head combined policy PUCT (FLATTEN), the data-gen workload (every other profiler is V3-leaf). Direct cost attribution (wraps value/policy/encode/step/legality timers — no PUCT-vs-UCT confound), `--cprofile` function breakdown, `--wall-only --repeats N` for paired (e.g. git-stash) A/B, `--single-pass` vs differential leaf. Produces the PROFILING.md "Production MCTS-NN PUCT" numbers.

        bench_stop_is_legal.py      # Microbench + equivalence gate for the encoder's `stop_is_legal` guard (SPEEDUPS.md S10): captures the states encode is called on during a production PUCT run, times 3 ways to compute the bit (full legal_actions / empty-stack guard / direct predicate), and asserts they agree byte-for-byte.

        bench_encoding_collisions.py # Measures the encoding-collision rate (SPEEDUPS.md, the encoding-keyed-cache no-go): hooks the inference encoder during a PUCT game and reports distinct encodings vs distinct GameStates — the EXTRA forwards an encoding-keyed NN-output cache would save over a GameState-keyed one (~0.9%, hence no-go).

        proto_jit_trace.py          # PROTOTYPE measuring `jit.trace`+`freeze` on the NN forwards (SPEEDUPS.md, no-go): swaps each model's inner net for a traced+frozen graph, checks numerical exactness vs eager, and times eager-vs-traced end-to-end (interleaved min-of-N). Found ~6–10% — not worth the integration.

        play_match.py               # Match-runner library + CLI. `play_match(p0_factory, p1_factory, seeds)` returns `MatchResult` (win/draw/loss counts, score sums, per-game records). Used by `tune_heuristic.py` and as a standalone head-to-head tool (CLI: `--p0 hubris_v3 --p1 hubris --n 100`). Per-seat `--p0-restricted` / `--p1-restricted` flags wrap each seat's agent in `restricted_legal_actions` independently.

        tune_heuristic.py           # CMA-ES tuner for one TUNABLE category at a time. Supports V1 and V3 configs via `--category` + `--arch`-derived dispatch. Save/resume via pickle (`.cma.pkl` per generation). x0 fallback prevents chain-forward regression. Auto-updates `tuned_configs/<arch>_best.json` when holdout improves (`--no-promote` disables; comparison metric is `holdout.regression.avg_margin` with min-n=30 + same-baseline gate). Parallel across `--jobs` cores; per-baseline diagnostic also parallelized. `--restricted` / `--no-restricted` (default ON), `--fitness {margin,sublinear,truncated,win_rate}` + `--fitness-k`, `--rotate-seeds` / `--rotate-start`, `--validation-pool` / `--validation-pool-start`, `--candidate-r1-force-forest` all recorded in the output JSON. `gen_best_x` persisted in history alongside `session_best_x`. See V3_TRAINING_PIPELINE.md.

        run_iterative_v3.py         # Orchestrator chaining V3 category tunings as block-coordinate descent. Per pass: fields_crops → food → resources → pastures_animals. On passes 2+, each category resumes its previous CMA-ES state. Supports `--start-step N` and `--initial-pickles "cat:path,..."` for resuming partial iterations. `--restricted` / `--no-restricted` (default ON) is forwarded to every tune_heuristic.py subprocess so candidate and baseline both consult `restricted_legal_actions`.

        play_mcts_match.py          # MCTS-vs-opponent match driver. `--opponent {hubris_v3, random, mcts}`, `--v3-config <json>` for the V3 evaluator's tuned config, per-MCTS knobs (`--sims`, `--c-uct`, `--n-random-fencing`, `--fpu-offset`, `--temperature`), `--mcts-as-p1` to swap seats. `--jobs N` (default `cpu_count()`) parallelizes via `multiprocessing.Pool`; workers construct agents in-process (avoids pickling `MCTSSearch` transposition tables — they hold node back-refs to the search). Streams per-game lines as games complete (running win tally + ETA, `flush=True`). Heuristic opponent uses the same strict-restricted legality as MCTS. For best throughput pick `--n` as a multiple of `--jobs` (a 10-seed run on 8 cores wastes 6 cores on the trailing batch of 2). When a `--leaf-ckpt` / `--opp-leaf-ckpt` points at a **joint `SharedTrunkModel`**, that seat is built via `make_joint_fns` (value + policy off the one shared trunk, overriding `--policy`) — so this is the single Python match driver for both separate-net and joint models. (For the fast, torch-free C++ match use `scripts/nn/run_cpp_match.py`.)

        mcts_sweep.py               # MCTS hyperparameter-sweep driver (Python/torch path). Runs a series of match configs in sequence by shelling out to `play_mcts_match` — default sweeps `c_uct ∈ {0.7,1.0,1.4,2.0,2.8}` vs `hubris_v3` — writing a per-config `<label>_cuct_<v>.log` plus a `<label>_summary.json` and a final ranked table with 95% CI on each config's margin. Joint-model-ready by inheritance: a `--leaf-ckpt` pointing at a joint `SharedTrunkModel` is auto-wired by `play_mcts_match` via `make_joint_fns`. The torch-path counterpart to the C++ self-sweep `scripts/nn/run_cpp_sweep.py`; this one sweeps vs a fixed opponent, the C++ one self-plays a model against itself.

        nn/                         # NN-specific scripts (subdirectory to keep NN tooling separate from general utilities). All are re-runnable CLIs; the underlying libraries live in `agricola/agents/nn/`.

            generate_training_data.py # NN training-data batch generator. Plays many games between agents drawn from an approved-config ensemble (default: 8 configs from `tuned_configs/DATA_GEN_ENSEMBLE.md`); writes `GameRecord`s to per-worker pickle files under `data/nn_training/runs/<run_id>/games/`. Multiprocessing pool, deterministic plan computation from (n_games, base_seed, approved_configs), balanced contiguous worker slicing, atomic per-game pickle writes, resume-on-existing (loads existing pickle + skips completed game_idxs), bimodal per-agent T draws (95% uniform [0.3, 1.0] + 5% T=4 — independently per agent). Config dispatch: `"random"` / `"t2"` sentinels + JSON paths + `nn:<checkpoint>` for NN seats. Per-game errors caught, logged in metadata.json's `errored_games`, run continues. CLI `--n-games / --n-workers / --out-dir (resume if exists) / --base-seed / --approved-configs / --config-weights / --restricted`, plus `--p0-fixed-config` (pin seat 0 to one config; `--approved-configs`/`--config-weights` then sample P1 only — the asymmetric hard-mining scheme behind `e14_hardmix_1k`, FIRST_NN C21). See FIRST_NN.md §6.

            generate_selfplay_data.py # MCTS self-play training-data generator (`DATA_VERSION` 3) — the self-play sibling of `generate_training_data.py`. Plays N SHARED-tree MCTS-vs-MCTS games (NN value leaf `nn_models/best` + combined behavioral-cloning policy; PUCT / FLATTEN / full legality) via `play_selfplay_recording_game`, recording π + `root_value`. CHUNKED STREAMING writes (`worker_NN_cNNN.pkl` flushed every `--chunk-size` games then buffer dropped → bounded per-worker RAM + O(n) writes, vs the heuristic generator's O(n²) full-list rewrite); resumable (scans existing chunks for completed game_idxs); fresh tree per game (shared only between the two seats). Reuses `generate_training_data.py`'s `partition_plan` / `_write_pickle_atomic` / run-id scaffold + a live progress monitor with ETA. CLI: `--n-games / --out-dir (resume if exists) / --n-workers / --base-seed / --sims / --c-uct / --temperature / --chunk-size / --leaf-ckpt / --policy {unweighted,awr}`.

            generate_selfplay_data_cpp.py # C++ self-play data-gen driver (CLAUDE.md → The C++ twin engine) — the C++-backed analog of `generate_selfplay_data.py`, producing the IDENTICAL `GameRecord` run-dir format so training consumes it unchanged. Runs the `cpp/build/selfplay --mcts` binary across a `multiprocessing` worker pool (default **batch** mode: one process per worker plays its whole slice via `--game-idxs`, loading NN weights once; `--per-game-process` is the one-process-per-game baseline), then `replay_trace`s each trace → `GameRecord` → chunked pickles. Reuses `generate_training_data.py`'s `partition_plan` / `_write_pickle_atomic` / run-id; resume + error-logging + overwrite-guard + `generation_mode` in metadata. ~4× faster than the Python generator. See CPP_ENGINE_PLAN.md.
            export_torchscript.py   # (Superseded by export_weights.py.) Exports the value net + 9 policy heads to TorchScript `.ts` for the original libtorch-based C++ inference. Kept for provenance; the C++ engine no longer uses libtorch.
            export_weights.py       # Exports the trained value net + 9 policy heads to raw float32 blobs + `weights_manifest.json` under `nn_models/cpp_export/`, consumed by the C++ hand-rolled MLP inference (CLAUDE.md → The C++ twin engine). For a joint model also writes the **outcome** head blob + `outcome_scale` (§2.3) and the leaf's `value_target` descriptor. Run after training, before C++ data-gen. See CPP_ENGINE_PLAN.md §6 / "Optimization pass #2".

            validate_dataset.py     # Post-generation invariant checker per FIRST_NN.md §6.6. Loads all (or `--sample-size N` random subset of) records from a run dir's worker pickles; runs invariants: `data_version` matches, `chosen_action ∈ legal_actions(state)`, non-singleton snapshots, `state.phase != BEFORE_SCORING`, non-empty `decisions`, `decider_idx == decider_of(state)`, `terminal_state.phase == BEFORE_SCORING`, stored-vs-recomputed final scores. Continues past individual failures to report all issues. Failure summary groups by check type + locates offending game_idx + snapshot. Exit codes 0/1/2 (pass / fail / invalid run dir).

            train_first.py          # Thin CLI wrapper over `agricola.agents.nn.training.train(...)` — argparse for hyperparameters (run-dir, hidden_dims, lr, batch_size, max_epochs, early-stop patience, `--init-from` warm-start, `--l2sp <λ>` L2-SP anchor, `--save-all-epochs`, …) and dispatches into the library. Output: best-model checkpoint + training-curve plot + calibration plot + metadata JSON in the configured out-dir.

            eval_vs_ensemble.py     # RETIRED (§2.1 — the heuristic ensemble no longer discriminates; evaluation is checkpoint-vs-checkpoint via run_cpp_match.py). Was the early uncontaminated strength yardstick: parallel single-seat evaluation of a checkpoint vs the 8-config data-gen ensemble.

            retention_eval.py       # Post-hoc retention sweep (FIRST_NN C20): encode a fixed held-out slice of a BROAD-distribution run dir once (`--probe-dir`/`--probe-games`), then compute raw-margin MAE for any list of checkpoints (`--sweep` globs, e.g. every epoch of a fine-tune) with a `--baseline` model as the reference line. `predict_margin` denormalizes per-model so MAE-in-points is comparable across checkpoints with different NormStats. The instrument that exposes self-play forgetting that a fine-tune's own val split cannot — though MAE≠strength, so it diagnoses, it doesn't gate.

            train_policy.py         # Thin CLI over `agricola.agents.nn.policy_training.train_policy` (`--head` ∈ HEADS = {placement,choose_subaction,commit_build_major,commit_sow,commit_bake,fencing,build_stop}, `--loss-weight {unweighted,awr}`, `--value-ckpt`, `--awr-clip`, `--init-from`, `--legality {restricted,full}` — use `full` for fencing/build_stop). Trains one fixed head; writes best.{pt,meta.json} + config + policy_norm_stats + train_log + test_metrics + curves under the out-dir, mirroring train_first.py. See POLICY_HEAD.md.

            train_policy_pointer.py # Thin CLI over `agricola.agents.nn.policy_pointer_training.train_pointer` (`--head {animal_frontier,harvest_feed}`, `--loss-weight {unweighted,awr}`, `--value-ckpt`, `--awr-clip`, `--init-from`). Default `--run-dir` = the three hidden-info runs (a pointer head enumerates the full engine frontier, so it can train on all the hidden-info runs — not just hidden_info_v2_10k). See POLICY_HEAD.md.

            build_combined_policy.py # Assembles the two end-to-end policy functions MCTS/PUCT consumes: `build("unweighted")` / `build("awr")` (9 head checkpoints each, via `load_policy_fn`), with `UNWEIGHTED_SET`/`AWR_SET` manifests and a `__main__` that sanity-checks both load + produce priors. See POLICY_HEAD.md / nn_models/REGISTRY.md.

            train_shared.py         # Thin CLI over `agricola.agents.nn.shared_training.train_shared` — trains the joint shared-trunk value+policy model (Stage B, SHARED_TRUNK.md). Flags: `--trunk-hidden-dims`, `--embedding-dim`, per-head dims, `--batch-size` (default 2048), `--init-from` (warm trunk), `--hard-targets` (else soft-π), `--train-outcome` (default ON — co-train the outcome head, §2.3), `--no-fast-loader`, `--save-all-epochs`. Imports torch.


            run_cpp_match.py        # Parallel driver for the C++ two-net match: runs `cpp/build/selfplay --match --model-dir-p0 A --model-dir-p1 B` across a worker pool over a seed range. Workers stream per-game `GAME` lines back to the PARENT via a shared queue; the parent prints one clean running-tally stream to **stdout** (like `play_mcts_match.py`) — so a parallel run is one clean log. Per the logging convention, the launcher redirects to `eval_out/<label>.log`. Each model is encoder-self-describing (its manifest `encoder_tag` → the C++ registry picks v2 / candidate). `--leaf-mode-p0` / `--leaf-mode-p1` (+ `--mix-alpha`) pick each seat's value-leaf mode (margin / outcome / mix, §2.3). Memory-light (C++ hand-rolled inference, no torch) — the fast, OOM-safe way to run an 800-sim match. See SHARED_TRUNK.md / CPP_ENGINE_PLAN.md.

            run_cpp_sweep.py        # Parallel C++ self-sweep — one model vs itself, mapping how strength varies with `c_uct` and `sims` (and, with `--sweep-alpha`, the mix-leaf `α` — each seat draws its own per game, for the mix-α sweep). Each game EACH seat independently draws its swept params inside the binary from a per-game RNG (reproducible, reported back in each `GAME` line); a worker pool runs `cpp/build/selfplay` in batch `--game-idxs` mode (NN weights loaded once per process) and STREAMS each finished game to the parent via a shared queue, growing an `--out-csv` incrementally. Mirrors `run_cpp_match.py`'s live-queue shape; memory-light (no torch). The C++ hyperparameter-sweep counterpart to the Python `scripts/mcts_sweep.py` (which sweeps vs a fixed opponent); encoder-self-describing via the model manifest, so joint-model-ready. See CPP_ENGINE_PLAN.md.

            analyze_alpha_sweep.py  # Kernel-regression analysis of a mix-α self-sweep (§2.3). Reads one or more `run_cpp_sweep.py --sweep-alpha` CSVs (cols incl. `alpha0,alpha1,winner`), pools BOTH seats into `(α, result∈{1,0.5,0})` points, and fits a Gaussian Nadaraya-Watson kernel regression of win-prob on α — the curve whose peak is the best fixed α (found ≈0.9, margin-heavy). `--series "label=csv" …`, `--out-png`.

            replay_traces.py        # Replay a run dir's existing C++ self-play traces (`<run-dir>/traces/trace_<i>.json`) into `GameRecord` chunks under `games/` — the REPLAY half of `generate_selfplay_data_cpp.py` only, generating nothing and overwriting no traces. For salvaging a gen run interrupted after traces were written but before replay. Resumable (skips game_idxs already in `games/`), writes the `worker_*.pkl` format training consumes.

    tuned_configs/                  # Persistent artifacts from tuning runs. Each completed run writes `<timestamp>.json` (best config, history, holdout), `<timestamp>.log` (human-readable progress mirror), and `<timestamp>.cma.pkl` (full CMA-ES state for resume). `v1_best.json` and `v3_best.json` are auto-maintained pointers to the strongest config per architecture. The 8-config data-gen ensemble (alphas_gen_1, alphas_gen_7, panel_gen16, panel_gen_25, panel_gen47, panel_gen47_wood020, panel_wood_r1 + t2) plus `panel_gen16_temp05.json` (panel-only diversity baseline) live here as named JSONs alongside the timestamped run outputs. `DATA_GEN_ENSEMBLE.md` describes the ensemble. See V3_TRAINING_PIPELINE.md.

    data/nn_training/runs/          # NN training-data datasets (gitignored — regenerable from the deterministic plan). Each generation invocation produces one run directory `<run_id>/` containing `games/worker_NN.pkl` (one per worker, holding `list[GameRecord]`) plus `metadata.json` (run-level metadata: code SHA, host, approved configs, T distribution, restricted flag, base_seed, planned/completed/errored game counts, data_version). See FIRST_NN.md §6.3.

    nn_models/                      # Trained NN checkpoints. Each completed `train_first.py` run produces one subdirectory (`<timestamp>-<suffix>/`) containing `best.pt` (state_dict + NormStats buffers), `best.meta.json` (architecture config + encoding_version), `config.json` (full run configuration for reproducibility), `norm_stats.json` (separate JSON copy of NormStats), `train_log.jsonl` (per-epoch metrics), `train_curves.png`, `calibration.png` (test-split predicted-vs-actual), and `test_metrics.json` (final test MSE/MAE). Top-level `REGISTRY.md` is the authoritative catalog of every checkpoint here — **must be updated as part of every training run** (see CLAUDE.md §2.3). `cpp_export/` (gitignored) holds the raw float32 weight blobs + `weights_manifest.json` exported by `scripts/nn/export_weights.py` for the C++ engine's hand-rolled inference.

    cpp/                            # The C++ self-play engine (CLAUDE.md → The C++ twin engine) — a faithful native reimplementation of the self-play inner loop (engine + MCTS + hand-rolled NN inference), ~4× faster than Python single-thread, validated against the Python oracle by the `tests/test_cpp_*.py` differential harness. Builds via CMake (`cpp/README.md`) into a pybind module (`agricola_cpp`, the differential-test surface) + a standalone `selfplay` binary (production data-gen). **No libtorch dependency.** The per-file layout, the staged build, and the §8.1 status ledger are in `CPP_ENGINE_PLAN.md` §9.1 (not duplicated here). `cpp/build/` is gitignored; `cpp/third_party/` vendors `nlohmann/json`.

    design_docs/                    # Frozen design records, grouped to keep the top level tidy: agent-phase (Phase 2.2/2.3) records at the top of the folder; card records under cards/; the original engine (Phase 1) task specs under game_engine/; the heuristic-agent (Phase 2.1) docs under heuristic_models/. One-line-per-doc index in the Documentation Files section above.

        cards/                      # Card design + batch records (Phase 3): CARD_SYSTEM_DESIGN, CARD_IMPLEMENTATION_PLAN (FROZEN), COST_MODIFIER_DESIGN, FOOD_PAYMENT_DESIGN, the two host-refactor records, per-batch triage/summary docs, catalog analyses, the categorization hypotheses. Per-doc one-liners in the Documentation Files section above; the as-built truth is CARD_ENGINE_IMPLEMENTATION.md. (*_HANDOFF.md files here are gitignored session scratch.)

        heuristic_models/           # Heuristic-agent (Phase 2.1) design + tuning docs.

            HUBRIS_V1_NOTES.md      # Design reference for HubrisHeuristic V1: per-term function/motivation/shape/magnitude for every component of `evaluate_hubris_v1`, the V1-vs-V2 finding with worked example, deferred alternatives (renovation bonus, newborn discount), known limitations and failure modes. Read before modifying V1.

            HEURISTIC_TUNING_PLAN.md # V1-era plan for self-play tuning. Thread A (tuning harness) implemented and run; Threads B/C partially superseded by V3. See V3_TRAINING_PIPELINE.md for the current pipeline.

            V3_DESIGN.md            # Comprehensive design reference for HubrisHeuristicV3 — three combination styles, per-category specs, the three-component resource pattern, V1 carry-overs. Read before modifying V3.

            V3_TRAINING_PIPELINE.md # Operational guide for the V3 tuning pipeline: CMA-ES basics, `scripts/tune_heuristic.py` semantics, the `scripts/run_iterative_v3.py` orchestrator (block-coordinate descent), `v3_best.json` convention, current training state.

        MCTS_DESIGN.md              # Historical design record for the MCTS phase (Phase 2.2), superseded by `MCTS_IMPLEMENTATION.md` for understanding the code; kept for rationale/provenance.

        HIDDEN_INFO_DESIGN.md       # Design + implementation reference for the hidden-information refactor: the round-card reveal as a nature/chance step, the public-state / Environment / observe split, the MCTS chance-node handling.

        FIRST_NN.md                 # Design spec for the first NN value function (Phase 2.3): goals, design principles, input encoding (~170 features), supervision target, the fully-specified data-generation pipeline, schema versioning. Read before working on the NN.

        POLICY_PUCT_DESIGN.md       # Historical design record for the policy head + PUCT phase (the search half now implemented and documented in `MCTS_IMPLEMENTATION.md`, the policy half in `POLICY_HEAD.md`).

        POLICY_HEAD.md              # Implementation + design record for the supervised behavioral-cloning policy heads (Phase 2.3 (c)): the factored `DecisionHead`, the `HEADS` registry, the two loss variants, the pointer heads, the `make_policy_fn` combiner. Read before adding a policy head.

        game_engine/                # Original engine (Phase 1) task specs and design artifacts — frozen at the time their task landed; referenced from SESSION_HISTORY.md / CHANGES.md as the design-rationale anchors. Not auto-read; consult when a session-history entry points here.

            ARCHITECTURE.md         # Original full architecture spec + game rules reference + original dataclass definitions. Inline `> Note:` annotations flag known divergences from current code.

            FENCE_IDEAS.md          # Design conversation artifact from Task 6 — broader Fencing design-space alternatives considered before the bitmap-fixed-universe approach.

            INCREMENTAL_PASTURE_DESIGN.md # NOT-STARTED sketch for incrementally updating the cached pasture decomposition (SPEEDUPS.md S9 option 2); gated on the S9 memoization landing first.

            TASK_2.md               # Pastures, slots, accommodation, Pareto frontier.

            TASK_3.md               # Cooking rates, modified pareto_frontier, breeding_frontier.

            TASK_4a_i.md            # State additions + atomic-space legality.

            TASK_4a_ii.md           # Atomic-space resolution.

            TASK_4a_iii.md          # Pasture cache scaffolding.

            TASK_4b_i.md            # Non-atomic legality (initial pass).

            TASK_5.md               # The `step` function + pending stack + Grain Utilization + Potter Ceramics.

            TASK_5B_DISPATCH_CLEANUP.md # Dispatch refactor + pending provenance.

            TASK_5C.md              # Eight non-atomic spaces + convention shifts.

            TASK_5D.md              # Farm Expansion + multi-shot sub-action pendings.

            TASK_6_pre.md           # Fencing universe enumeration.

            TASK_6.md               # Fencing + Build Fences + Farm Redevelopment.

            TASK_7.md               # Harvest phases + rounds 5–14.

    archive/                        # Fully superseded docs + retired scripts kept for historical reference. Not load-bearing.

        TESTS.md                    # Pre-TEST_DESCRIPTIONS.md per-test reference (170-test snapshot). Superseded.

        SWEEP_HANDOFF.md            # Retired handoff for the UCT c_uct-sweep plan (UCT-MACRO archetype, NN leaf). Bypassed by the joint shared-trunk pivot; kept for provenance.

        scripts/                    # Retired one-off / superseded scripts. Not on any current path; kept for provenance. Two groups: (a) separate-net + UCT-MACRO-archetype search drivers the joint-model pivot retired — `run_search_tournament.py` (+ its `analyze_tournament.py` Bradley-Terry analyzer), `eval_search_vs_ensemble.py`, `run_nn_search_matrix.py` (all fail-fast on a joint model; superseded by `scripts/nn/eval_vs_ensemble.py` + the C++ `run_cpp_match.py`/`run_cpp_sweep.py`); (b) V3-heuristic-leaf one-off instrumentation whose findings are already in the design docs — `measure_mcts_tree.py`, `measure_v3_prior_distribution.py`, `measure_exhaustive_leaves.py`, `run_exhaustive_vs_greedy_match.py`. Plus older V1/refactor artifacts (`play_mcts_v1_vs_*.py`, `port_pre_refactor_v3.py`, `_validate_fast_loader.py`).
```

For deeper per-file details, see **`FILE_DESCRIPTIONS.md`** (every `agricola/*.py` + the test-infrastructure files). For test-file coverage, see **`TEST_DESCRIPTIONS.md`**.
