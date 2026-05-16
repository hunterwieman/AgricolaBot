# AgricolaBot — Cleanup Changes

Small, targeted improvements that don't warrant a full TASK_*.md file. Each entry describes the motivation, the files affected, and the exact changes required.

---

## Table of Contents

- [5/8/2026 Cleanup 1 — Move `house_material` from `Cell` to `PlayerState`](#cleanup-1)
- [5/8/2026 Cleanup 2 — Rename `accumulated_goods` to `accumulated_amount`](#cleanup-2)
- [5/8/2026 Cleanup 3 — Remove `next_starting_player` from `GameState`](#cleanup-3)

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
