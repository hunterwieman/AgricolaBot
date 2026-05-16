# Possible Next Steps after Task 5C

A sketch of directions the project could take next, organized by scope and effort. Originally written 2026-05-13 after Task 5; updated 2026-05-15 after Task 5C. 315 tests passing. Non-atomic resolution is complete for 9 of 12 spaces; only Farm Expansion, Farm Redevelopment, and Fencing remain unresolved (and Fencing has no legality predicate yet).

This is a planning document, not a commitment. The actual next task should be chosen based on what's most useful and what fits the available time.

---

## Immediate / one-task scope (one task's worth)

After Task 5C the only remaining single-space resolvers are the three deferred non-atomic spaces. Each is a clean one-task scope.

### A. Implement Farm Expansion

"Build rooms (5 mat + 2 reed each) and/or build stables (2 wood each)." Reuses `PendingBuildStable` from Task 5C; introduces a new `PendingBuildRoom` carrying `cost: Resources` per the bucket-2 sub-action cost convention (see CLAUDE.md "Sub-action cost handling"). The room cost varies with house material, so push-time cost computation in the choose handler is the natural fit.

The action is and/or with multi-build (multiple rooms or stables in one action), so the parent pending mirrors Side Job in shape but with two genuinely multi-shot sub-actions. Within-action adjacency chaining for rooms ("a room just built counts immediately for the next room placed in the same action") is the main new wrinkle.

Probably the simplest of the three remaining spaces.

### B. Implement Fencing — legality and resolution together

Fencing has no legality predicate today (Task 4 deferred it) and no resolution. Both pieces land in one task because the resolution can't be tested without legality and vice versa.

The core design problem is enumerating valid fence configurations. The rules: a Build Fences action must place at least one fence; every placed fence must be connected to other fences at both ends; the resulting fences must enclose one or more pastures; only empty or stable cells may be enclosed (rooms and fields can't); first pasture anywhere, subsequent pastures must be orthogonally adjacent to an existing pasture. The legality enumerator must produce the list of *valid resulting fence-array pairs* given the current state.

`PendingBuildFences` should carry `cost: Resources` (bucket-2 convention) since fence count varies per commit. This is the first sub-action whose commit payload is a richer-than-scalar shape (a fence configuration), so the `CommitBuildFences` dataclass design is itself a small design conversation.

### C. Implement Farm Redevelopment

"Renovate, then build fences." Reuses `PendingRenovate` from Task 5C and `PendingBuildFences` from §B above. The structural pattern mirrors House Redevelopment (renovate-then-optional-improvement); the second step is mandatory-fence instead of optional-improvement. Best done after §B since it depends on the fence machinery.

---

## Multi-task scope (a few tasks)

### D. Finish the three deferred non-atomic resolvers

§A + §B + §C above. At completion every Family-game worker placement resolves (no `NotImplementedError` paths remain in `step()`). The natural order is Farm Expansion → Fencing → Farm Redevelopment, since the latter two share infrastructure.

Approximate effort: 3 tasks. Largely pattern-application work for Farm Expansion; the fence-enumeration design in Fencing is the only piece that's not pure application of the post-5C patterns.

### E. Implement the harvest

HARVEST_FIELD (mechanical, no decisions), HARVEST_FEED (multi-decision; uses `pareto_frontier`-like enumeration), HARVEST_BREED (uses `breeding_frontier` from helpers).

The decision points in HARVEST_FEED — which goods to convert, how to feed, whether to beg — are the first real "strategic choice" decisions the engine surfaces beyond worker placement. After 5C, animals can land on the farm (via the three markets), so the harvest is no longer blocked on prior work; this is now the natural next big-design task.

Implementing the harvest also requires extending the round loop to rounds 5–14 (the engine currently halts in `BEFORE_SCORING` after round 4's RETURN_HOME). Probably a 2–3 task arc: the three phases land first; the round-loop extension and the round 4/7/9/11/13/14 harvest-trigger logic land alongside.

Recommended sequencing within the multi-task scope: D first (to retire the last `NotImplementedError` placements), then E.

---

## Compound-card prerequisite work (one task)

### F. Build speculative-legality machinery for compound card interactions

The Pan-Baker-plus-Potter-Ceramics example flagged in `IMPLEMENTATION_CHOICES.md` item 11. Required before any card with an on-placement effect can be implemented (e.g., a card that grants resources when you take a specific space, which then enables a downstream Bake Bread trigger).

Concretely: when checking `PlaceWorker(space)` legality, the legality system needs to apply all owned cards' on-placement transformations to a hypothetical state, then ask the existing sub-action predicates against that hypothetical. The trigger registry already supports arbitrary event names; the missing piece is the legality-side speculative application.

Probably worth doing before adding many more cards. Without F, the card system can only handle cards of the Potter Ceramics shape (purely-during-resolution triggers, no on-placement effects).

**Related open questions** documented in CLAUDE.md "Card implementation status", likely addressed alongside F when card work begins in earnest:

- **Atomic-space trigger hosting: phase tracking.** When atomic spaces convert to push trigger-host pendings (so cards like Cottager and Hardware Store can attach to Day Laborer, etc.), what state tracks "primary effect applied yet?" — generic `primary_effect_applied: bool` vs. a `phase: Literal["before", "after"]` field.
- **Atomic-space trigger hosting: phase-transition mechanism.** How to flip the phase bit AND apply the primary effect between the before and after trigger phases — explicit transition action, overloaded `Stop`, or nested pendings.

(The earlier "PENDING_ID vs initiated_by_id redundancy" question was resolved by Task 5C's `"space:"` / `"card:"` prefix scheme.)

---

## Phase transitions (further out)

### G. Phase 2 baseline — a heuristic agent

The random agent is in place via `tests/test_utils.py::random_agent_play`. A hand-written heuristic agent that knows simple Agricola strategy (prioritize food + family growth + field-and-pasture balance) would give a non-trivial baseline to compare against. Useful for sanity-checking the engine and for benchmarking when self-play RL begins.

Probably waits until Phase 1 is complete (all non-atomic + harvest + full 14 rounds).

### H. Engine performance pass

Profile `step` / `legal_actions` / `_advance_until_decision`. Identify hot paths. Decide on any caching (e.g., cached `legal_actions` per state hash). Probably premature until MCTS rollouts actually run.

### I. Tooling

A simple text/CLI driver that plays a game and prints turn-by-turn state. More useful now that 9 non-atomic spaces resolve — a random-agent playthrough now exercises a substantial fraction of the engine. Tiny scope: an `if __name__ == "__main__"` block in a small driver script, or a `scripts/play_one_game.py` file. Could be done at any time; useful adjunct to harvest work in particular (HARVEST_FEED decisions are easier to debug with a turn-by-turn printer).

---

## Small housekeeping

### J. Documentation cleanup

- CLAUDE.md's Documentation Files table is missing entries for `POSSIBLE_NEXT_STEPS.md` (this file), `TASK_5B_DISPATCH_CLEANUP.md`, and `TASK_5C.md`. Worth adding.
- File-naming for related task clusters has settled de facto on the sub-letter convention (`TASK_5`, `TASK_5B`, `TASK_5C`). No further action needed.

### K. Minor refactor opportunities

None urgent; flagging for visibility:

- `agricola/resolution.py` is 796 lines after Task 5C and now holds seven `_execute_*` sub-action effect functions (sow, bake, plow, build_stable, build_major, renovate, accommodate). The split into `sub_actions.py` is closer to worthwhile than it was after Task 5. Defer until the file passes ~1000 lines or until another batch of sub-actions lands (Farm Expansion's BuildRoom, Fencing's BuildFences).
- `agricola/legality.py` is 974 lines (up from 653 after Task 5). Placement-legality, per-pending enumerators, and the card extension registries are all here. A split is now plausible — e.g., `legality_placements.py` + `legality_pending.py` + `card_extensions.py`. Worth considering during the next time the file gains substantive new code (Fencing legality is the obvious trigger — it will add nontrivial fence-configuration enumeration).

---

## Strategic framing — three possible paths

**Path 1: Breadth-first engine completion.** Tackle D (the three remaining non-atomic resolvers) → E (harvest + rounds 5–14). The engine becomes feature-complete for the Family game. After this point, agent work (Phase 2) becomes the natural next phase.

Approximate effort: 3 tasks for D, 2–3 tasks for E. End state: a Family game playable from setup to scoring by random or heuristic agents.

**Path 2: Card-first expansion.** Implement F (speculative legality), then add cards of various shapes (on-placement effects, conditional triggers, end-game scoring effects). Tests the card framework deeply on the existing 9 non-atomic spaces and 12 atomic spaces.

Approximate effort: 1 task for F, then ongoing as cards are added. End state: a robust card framework with several validated card patterns, but the engine still can't play to game end (no harvest, no rounds 5–14).

**Path 3: Mixed.** Alternate one of D's remaining spaces with documentation / tooling improvements (I, J). Slowest gameplay progress but lowest risk of design churn — each step is small and well-understood.

---

## My take (advisory, not prescriptive)

If you want the most concrete and useful single next task: **A (Farm Expansion)** as a warm-up — it's the simplest of the three remaining non-atomic spaces and unblocks no other work, so it's a low-risk pattern-application exercise. After that, **B (Fencing)** is the most interesting design problem left in the non-atomic space — fence-configuration enumeration is genuinely new.

If you want the highest-impact direction: **E (harvest)** is where the engine starts to feel like a real game rather than a placement simulator. After 5C, animals can land on the farm, so the harvest is no longer blocked. Comparable in scope to Task 5 itself, but with most of the architecture work already done.

If you want to make broader card development possible: **F (compound legality)** unlocks all the upstream-effect cards (Pan Baker class) that the current architecture can't handle. Worth doing before too many more cards land.
