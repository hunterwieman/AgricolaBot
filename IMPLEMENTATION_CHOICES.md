# AgricolaBot — Implementation Choices to Revisit When Introducing Cards

This document records implementation decisions that were made for the 2-player Family game and may need to be revised when occupation cards, minor improvement cards, or specific major improvements with unusual effects are introduced.

> **Status (Phase 3 — cards).** Every item below has been revisited against the actual in-scope card set. The live resolution of each — decided / decide-as-we-build / deferred-to-expansion / not-card-gated / to-revisit — is recorded in **`design_docs/cards/CARD_SYSTEM_DESIGN.md` §14**, which folds this whole list. Treat §14 as the current status; this file remains the original problem statements.

---

## 1. Action space workers encoded as `tuple[int, int]` (count per player)

**Current choice (`ActionSpaceState.workers`):**
Each action space stores its occupants as a length-2 tuple of counts: `(player_0_count, player_1_count)`. An empty space is `(0, 0)`. One worker from player 0 is `(1, 0)`. Two workers from player 0 (parent + newborn on a Wish space) is `(2, 0)`. One worker from each player is `(1, 1)`.

**Why this works for the Family game:**
The count tuple is the most convenient encoding for the operations performed most often — checking occupancy (`sum(workers) > 0`) and reading a player's count (`workers[p]`). It is slightly cheaper to store and compare than a flat list of indices. The 2-player assumption is already baked into the rest of the codebase.

**What might need to change:**
Certain occupation and minor improvement cards allow a second player to place a worker on an already-occupied space, or allow workers to piggyback on another player's placement. If the rules for those cards require knowing *which slot* or *in what order* workers arrived, the count tuple is insufficient. A richer structure (e.g. a list of `(player_idx, arrival_order)` pairs) may be needed. Also, extending beyond 2 players would require changing the tuple length.

**File:** `agricola/state.py` — `ActionSpaceState.workers`

---

## 2. Animal locations not tracked

**Current choice (`PlayerState.animals`):**
Animals are stored as totals only (`Animals(sheep, boar, cattle)`). Where on the farm each animal physically lives is not stored — it is only checked at the point of gaining animals (via `can_accommodate` / `pareto_frontier`).

**Why this works for the Family game:**
No Family game card requires knowing which pasture a specific animal is in. Capacity is the only constraint that matters.

**What might need to change:**
A small number of occupation and minor improvement cards in the full game reference specific animal locations (e.g. "the animal in your house" or "animals in a specific pasture"). If any such card is introduced, explicit location tracking will be needed.

**File:** `agricola/state.py` — `PlayerState.animals`; `agricola/helpers.py` — `extract_slots`, `can_accommodate`, `pareto_frontier`

---

## 3. Action space IDs are plain strings

**Current choice (`constants.py`, `BoardState.action_spaces`):**
Action spaces are identified by plain strings (`"forest"`, `"clay_pit"`, etc.) used as dictionary keys throughout the codebase.

**Why this works now:**
Simple and consistent throughout all existing code. No migration cost.

**What might need to change:**
As the codebase grows with legality functions, resolution handlers, and eventually card effects that reference specific spaces, the string approach loses typo safety and IDE support. Migrating to an `ActionSpaceId` enum at a natural boundary (e.g. before implementing the full step function) would improve robustness.

**Files:** `agricola/constants.py`, `agricola/state.py`, `agricola/setup.py`, and all future legality/resolution files.

---

## 4. `future_resources` covers all 7 goods but not animals or actions

**Current choice (`PlayerState.future_resources`):**
`tuple[Resources, ...]` of length 14, one entry per round. Each entry is a full `Resources` object covering all 7 goods (food, wood, clay, reed, stone, grain, veg). This handles the Well and any future card that promises building resources, food, or crops at future rounds.

**History:** Originally `future_food: tuple[int, ...]` (Family-game-only — Well promises food). Generalized in Task 5 to `future_resources: tuple[Resources, ...]`.

**What might still need to change:**
- Future animal promises (e.g. "1 pig at round 5"): no field supports this today.
- Future *actions* (e.g. "a free plow at round 5"): no field supports this today.

When cards introducing these arrive, the cleanest migration is a `FutureRewards` dataclass wrapping `Resources + Animals + Actions`. Migration cost is low — one field rename + a few callsite updates.

**File:** `agricola/state.py` — `PlayerState.future_resources`

---

## 5. `people_total` includes newborns immediately

**Current choice:**
When a newborn is placed via a Wish for Children action, they are added to `people_total` immediately. A separate `newborns` counter tracks how many were born this round solely to apply the reduced feeding cost (1 food instead of 2) at harvest.

**Why this works:**
Matches the rules: newborns count as family members from the moment they are born, even though they cannot act until the following round.

**What might need to change:**
Certain occupation cards modify feeding costs or interact with newborn status in non-standard ways. The `newborns` counter may need to be richer (e.g. tracking birth round rather than just a count) if such cards are introduced.

**File:** `agricola/state.py` — `PlayerState.people_total`, `PlayerState.newborns`

---

## 6. `_apply_worker_placement` is private to `resolution.py`

**Current choice:**
The cross-cutting placement bookkeeping helper (`_apply_worker_placement`) is kept private to `agricola/resolution.py`. It increments `workers[ap]` on the space and decrements `people_home` on the active player.

**Why this works now:**
Task 4a-ii only requires atomic-space resolution. All 12 handlers live in `resolution.py` and can call the private helper directly. No other module currently needs this function.

**What might need to change:**
Non-atomic resolution handlers (Task 4b onwards — Farmland, Farm Expansion, Fencing, etc.) will need the same worker-placement bookkeeping. At that point, decide whether to:
- Move `_apply_worker_placement` to `agricola/helpers.py` as a shared utility, or
- Keep it private in `resolution.py` and delegate from non-atomic handlers.

Do not move it prematurely. Revisit at Task 4b design time.

**File:** `agricola/resolution.py` — `_apply_worker_placement`

---

## 8. `_can_build_room` hardcodes room cost as action-independent

**Current choice (`legality.py` — `_can_build_room`):**
The helper checks whether the player can afford one room at the standard cost (5 material + 2 reed), which is the only cost in the Family game.

**What might need to change:**
Certain occupation cards in the full game reduce room-building costs (e.g. building at 4 material instead of 5). If such cards are introduced, `_can_build_room` would need to accept a cost override or consult the player's active card effects rather than hardcoding 5.

**File:** `agricola/legality.py` — `_can_build_room`

---

## 9. `people_home < 1` check assumes one worker per turn

**Current choice (`legality.py` — `legal_placements`):**
The function returns an empty list immediately if `people_home < 1`. This correctly reflects the Family game rule that each player places exactly one worker per turn.

**What might need to change:**
The Adoptive Parents card and a small number of other occupation cards allow a player to place a worker on a space that is already occupied, or to take an extra placement under specific conditions. If such cards are introduced, the simple `people_home < 1` guard may need to be replaced with a richer check that accounts for card-granted extra placements.

**File:** `agricola/legality.py` — `legal_placements`

---

## 10. Card-extension pattern for legality helpers

**Current choice (`legality.py` — `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`):**
Legality helpers that a card may broaden are structured as `base_check(state, p) or any(ext(state, p) for ext in <HELPER>_EXTENSIONS)`. Each `<HELPER>_EXTENSIONS` is a module-level list populated by card modules at import time via a `register_<helper>_extension(fn)` wrapper. The pattern is intentionally similar to the trigger registry but distinct: triggers fire at specific points during action resolution; legality extensions widen the set of states in which the action is legal in the first place.

**Currently implemented:** `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` (with `register_bake_bread_extension(fn)`). Potter Ceramics' module registers an extension that broadens `_can_bake_bread` to accept clay-and-Potter-and-baker as a valid baking precondition.

**What might still need to change:**
Helpers expected to receive extensions: all the `_can_*` predicates in `agricola/legality.py` (`_can_sow`, `_can_plow`, `_can_renovate`, `_can_afford_room`, `_can_afford_major`, etc.). Each needs its own `*_EXTENSIONS` list and `register_*_extension` wrapper when the first card needs to broaden it. Helpers that probably won't: `_is_available`, `_has_room_placement`, `_has_stable_placement` (cards modify costs, not geometric placement).

**File:** `agricola/legality.py`, with card modules in `agricola/cards/` registering at import time.

---

## 11. Compound card interactions — known unhandled case

**Current choice:**
The card-extension pattern above (item 10) handles single-card eligibility broadening cleanly. Potter Ceramics' `_can_bake_bread_extension` says "yes, you can bake if you have clay + a baker + Potter Ceramics" — the predicate is satisfiable from the literal current state.

**What does NOT work:** *compound* interactions where one card's effect enables another card's eligibility. Canonical example: **Pan Baker** ("each time you use the Grain Utilization action space, you get 2 clay and 1 wood") combined with Potter Ceramics. A player owning both with 0 clay and 0 grain can actually bake — Pan Baker fires on placement, providing clay, which Potter Ceramics then converts to grain. But `_can_bake_bread` reads literal current state (0 clay), so it returns False, and `_legal_grain_utilization` reports the placement as illegal.

**What needs to change for compound interactions:**
The legality system needs to apply "on placement" card effects speculatively before checking sub-action predicates. The trigger registry already supports arbitrary event names (e.g., `"on_take_space:grain_utilization"` for Pan-Baker-like cards), so the registration side is fine. The missing piece is the legality-side machinery: when checking `PlaceWorker(space)` legality, apply all owned cards' on-placement transformations to a hypothetical state, then ask the existing sub-action predicates against the hypothetical. If any reachable hypothetical state has a legal sub-action commit path, the placement is legal.

**Out of scope for Task 5.** Flagged here, in ENGINE_IMPLEMENTATION.md §6 (card-trigger machinery & deferred design questions), and in TASK_5.md's "Known limitation: compound card interactions" for whoever implements the broader card system.

**File:** `agricola/legality.py` (legality predicates); `agricola/cards/` (per-card registration).

---

## 12. `triggers_resolved` is scoped to a pending frame's lifetime

**Current choice (`PendingBakeBread.triggers_resolved`):**
The `triggers_resolved: frozenset[str]` field lives on the pending frame, not on `PlayerState`. When the frame pops, the set goes with it. The next instance of the same trigger event (e.g., the next Bake Bread action) creates a fresh pending with an empty `triggers_resolved`.

**Why this is the right scoping:**
Triggers like Potter Ceramics fire *once per event instance* (per Bake Bread action), not once per game. Putting the resolved-set on `PlayerState` would mean once-per-game semantics, which doesn't match the card text.

**What might need to change:**
Per-card budgets that DO span multiple events (once-per-round, once-per-game, once-per-harvest) need separate state on `PlayerState` or `BoardState`. The pending stack is for *active* decisions, not per-game scoreboards. When such cards arrive, they'll need their own tracking field (e.g., `PlayerState.card_state: dict[str, Any]` or per-card-specific fields). The pending-frame scoping doesn't change.

**File:** `agricola/pending.py` — `PendingBakeBread.triggers_resolved` (and future pendings carrying the same field).

---

## 13. Sub-phase decomposition deferred for phase resolvers

**Current choice (`engine.py` — `_resolve_return_home`, `_complete_preparation`):**
Each phase resolver does its entire phase's mechanical work in a single function call. This works for Task 5 because nothing during these phases requires an agent decision.

**What might need to change:**
Once cards introduce triggers during RETURN_HOME / PREPARATION (e.g., occupations with "at the start of each round" effects), some triggers will require agent input. A resolver that's "in the middle of doing its work" can't simply terminate and re-enter cleanly — if `_complete_preparation` ran its refill, then encountered a trigger needing agent input, and returned partway through, the next call would re-run the refill (accumulating goods twice).

The forward-compatible fix is to split each phase into **sub-phases**, each a separate `Phase` enum value (e.g., `Phase.RETURN_HOME_TRIGGER_PRE`, `Phase.RETURN_HOME_MECHANICAL`, `Phase.RETURN_HOME_TRIGGER_POST`, similar for `PREPARATION`). Each sub-phase does exactly one piece of work and transitions to the next. The engine never re-enters a completed sub-phase because sub-phase identity advances after each step.

Don't add these now — they would clutter Task 5 without serving any purpose. Plan when cards arrive: split as needed, update `_advance_until_decision` to handle the new phases.

**File:** `agricola/engine.py` — `_resolve_return_home`, `_complete_preparation`; `agricola/constants.py` — `Phase`.

---

## 14. Hidden-information handling tuned for the symmetric (Family) case

The round-card reveal is modelled as an explicit nature/chance step (see `HIDDEN_INFO_DESIGN.md`). Several choices are correct for the 2-player Family game — where the only hidden information is the symmetric, exogenous, uniformly-shuffled reveal order — but may need revisiting once cards introduce **asymmetric** private hands:

- **Explicit chance nodes, not ISMCTS / determinization.** Symmetric + exogenous + uniform hidden info means an information set is observer-independent, so chance nodes are exact and cheap. Private hands break that symmetry; the asymmetric future needs determinization / ISMCTS keyed on `observe(state, env, i)`. **File:** `agricola/agents/mcts.py`.
- **`observe(state, env, i)` is the identity today.** The seam exists (common-knowledge `GameState` + hidden-ground-truth `Environment`) but `observe` is trivial because both players see the same public state. With private hands it becomes a real per-player projection. **File:** `agricola/environment.py`.
- **Round 1 is pre-dealt in `setup_env`.** Round 1's reveal is resolved at construction (returning a round-1 WORK state), the lone reveal resolved outside the game loop. When cards add a pre-round-1 draft, the start point moves to the draft node and `setup_env` stops pre-resolving. **File:** `agricola/setup.py`.
- **`decider = None` is the nature sentinel.** `decider_of -> int | None`; `None` is not a valid index, so a missed guard fails loudly. Generalizes to any future nature event (draft, draw). **File:** `agricola/agents/base.py`.
- **MCTS chance routing uses a per-node `chance_counts` counter, not `child.visits`** (a shared post-reveal child inflates `child.visits` under the transposition DAG). **File:** `agricola/agents/mcts.py`.
