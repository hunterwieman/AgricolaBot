# AgricolaBot — Cleanup Changes

Small, targeted improvements that don't warrant a full TASK_*.md file. Each entry describes the motivation, the files affected, and the exact changes required.

---

## Table of Contents

- [5/8/2026 Cleanup 1 — Move `house_material` from `Cell` to `PlayerState`](#cleanup-1)
- [5/8/2026 Cleanup 2 — Rename `accumulated_goods` to `accumulated_amount`](#cleanup-2)
- [5/8/2026 Cleanup 3 — Remove `next_starting_player` from `GameState`](#cleanup-3)
- [6/1/2026 Cleanup 4 — Extract `breeding_food_gained`; stop re-enumerating the frontier in `_execute_breed`](#cleanup-4)

---

<a name="cleanup-1"></a>
## 5/8/2026 Cleanup 1 — Move `house_material` from `Cell` to `PlayerState`

**Motivation:**
`house_material` is currently stored on every `Cell` with `cell_type == ROOM`. But Agricola's rules require the entire house to be one material — a mixed-material house is physically impossible. Storing the material per-cell allows that impossible state to be represented and requires workarounds (e.g. reading the material from an arbitrary room cell) wherever the material is needed. Moving it to `PlayerState` as a single field makes the invariant explicit in the data structure.

**Files affected:**

- `agricola/state.py` — remove `house_material: Optional[HouseMaterial]` from `Cell`; add `house_material: HouseMaterial = HouseMaterial.WOOD` to `PlayerState`
- `agricola/setup.py` — remove `house_material=HouseMaterial.WOOD` from `Cell(...)` construction in `_make_farmyard`; add `house_material=HouseMaterial.WOOD` to `_make_player`
- `agricola/scoring.py` — replace per-cell `house_material` reads with `ps.house_material`
- `agricola/constants.py` — no change (enums unchanged)
- `TASK_4b_i.md` — update `_can_build_room` and `_can_renovate` pseudocode to read `p.house_material` instead of reading from a cell
- `ARCHITECTURE.md` — update `Cell` dataclass spec to remove `house_material`; update `PlayerState` spec to add it
- `tests/test_state.py` — update any assertions that check `cell.house_material` to instead check `player.house_material`
- `tests/test_scoring.py` — update any state construction that sets `house_material` on cells

**No new tests required** — existing tests cover the same invariants, just reading from the new location.

---

<a name="cleanup-2"></a>
## 5/8/2026 Cleanup 2 — Rename `accumulated_goods` to `accumulated_amount`

**Motivation:**
`accumulated_goods` is an ambiguous name — "goods" could refer to any game resource. `accumulated_amount` more clearly communicates that this is a scalar count, distinct from the `accumulated: Resources` field on the same dataclass. The two fields are:
- `accumulated: Resources` — building-resource spaces; stores a `Resources` object
- `accumulated_amount: int` — food/animal spaces; stores a plain integer count

**Files affected:**

- `agricola/state.py` — rename field on `ActionSpaceState`
- `agricola/setup.py` — update field name in `_make_action_spaces`
- `agricola/legality.py` — update all reads of `accumulated_goods`
- `agricola/resolution.py` — update all reads and writes of `accumulated_goods`
- `tests/test_legality_atomic.py` — update helper and assertions
- `tests/test_resolution_atomic.py` — update helper and assertions
- `TASK_4b_i.md` — update per-space legality descriptions that reference `accumulated_goods`
- `ARCHITECTURE.md` — update `ActionSpaceState` field spec
- `SESSION_HISTORY.md` — update references in Change 1 outcome notes

---

<a name="cleanup-3"></a>
## 5/8/2026 Cleanup 3 — Remove `next_starting_player` from `GameState`

**Motivation:**
`next_starting_player` was added to stage the starting player token change when Meeting Place is taken mid-round, so that `starting_player` would not be updated until the next round began. However, `starting_player` is only read at the start of each round to determine turn order — it is never read mid-round. The current round's turn alternation is driven entirely by `current_player` and `people_home`, not by `starting_player`. So updating `starting_player` immediately when Meeting Place is taken is safe and correct. `next_starting_player` is redundant.

**Files affected:**

- `agricola/state.py` — remove `next_starting_player` from `GameState`
- `agricola/setup.py` — remove `next_starting_player=starting_player` from `GameState(...)` construction
- `agricola/resolution.py` — in `_resolve_meeting_place`, replace `dataclasses.replace(state, next_starting_player=ap)` with `dataclasses.replace(state, starting_player=ap)`
- `tests/test_resolution_atomic.py` — update `test_meeting_place_resolution` and any other tests that assert on `next_starting_player`; assert on `starting_player` instead
- `README.md` — update `GameState` field description
- `ARCHITECTURE.md` — update `GameState` dataclass spec
- `SESSION_HISTORY.md` — update Task 4a-i entry which describes adding this field
- `IMPLEMENTATION_CHOICES.md` — no entry exists for this field; none needed

---

<a name="cleanup-4"></a>
## 6/1/2026 Cleanup 4 — Extract `breeding_food_gained`; stop re-enumerating the frontier in `_execute_breed`

**Motivation:**
`_execute_breed` (the `CommitBreed` resolver) needed the food gained by the chosen post-breed configuration, but the only place that knew the breeding food formula was `breeding_frontier`. To respect "the formula has a single source of truth," `_execute_breed` re-called `breeding_frontier(p, rates_3)` and linearly scanned its output for the entry matching the chosen `(sheep, boar, cattle)`, reading that entry's `food_gained`. This recomputed the entire Pareto frontier — `can_accommodate` enumeration plus an O(n²) dominance pass — purely to look up a value the formula could produce directly from `(pre_animals, post_animals, rates)`, all of which were already in hand.

This also made `_execute_breed` the odd one out among the three harvest/animal resolvers: its siblings `_execute_accommodate` (animal markets) and `_execute_convert` (harvest feeding) already compute food via a direct inline formula with no frontier scan.

The fix preserves the single-source-of-truth invariant by extracting the formula into a small helper, `breeding_food_gained(pre, post, rates)`, that **both** `breeding_frontier` and `_execute_breed` call. The frontier still owns the *enumeration*; the new helper owns the *formula*. `breeding_frontier` is unchanged in behavior (it now calls the helper per frontier point instead of inlining the arithmetic), and `_execute_breed` computes the food in O(1) instead of re-enumerating.

The previous frontier scan doubled as a defensive assertion (`CommitBreed not in breeding_frontier`). Dropping it is consistent with the engine's "`step` does not verify legality" principle (CLAUDE.md / ENGINE_IMPLEMENTATION.md): callers ensure `action in legal_actions(state)`, and the two sibling resolvers already omit any such check. The value computed is identical for every legal commit, since the helper *is* the formula the frontier tabulated.

**Files affected:**

- `agricola/helpers.py` — add `breeding_food_gained(pre, post, rates) -> int`; rewrite `breeding_frontier`'s per-point food computation to call it (removing the inlined formula + the now-unused `sR, bR, cR = rates` unpack)
- `agricola/resolution.py` — in `_execute_breed`, replace the `breeding_frontier` re-enumeration + scan + assertion with a single `breeding_food_gained(p.animals, chosen, rates_3)` call; swap the `breeding_frontier` import for `breeding_food_gained`; update the docstring
- `ENGINE_IMPLEMENTATION.md` — §4 Harvest `HARVEST_BREED` paragraph: note that the formula lives in the shared `breeding_food_gained` helper (the single source of truth) and that `_execute_breed` applies it directly rather than re-enumerating

**No new tests required** — the change is behavior-preserving for all legal commits; the existing `test_harvest_breed.py` / `test_harvest_integration.py` / `test_helpers.py` suites cover the breeding food values and continue to pass (full suite: 918 passed).
