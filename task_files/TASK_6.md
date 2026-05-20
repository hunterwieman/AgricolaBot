# Task 6 — Fencing, Build Fences, and Farm Redevelopment

The first half of fencing landed in `TASK_6_pre.md`: `agricola/fences.py` ships four universes of candidate pasture shapes (`UNIVERSE_FULL` / `UNIVERSE_FAMILY` / `UNIVERSE_EXTENDED` / `UNIVERSE_RESTRICTED`) as bitmap tuples + matching frozensets. This task picks up from there:

- Extends `fences.py` with per-shape *edge metadata* (boundary fence-edges, adjacency cells, the cell-set as a frozenset) — pure additions to the existing universes.
- Adds the **Build Fences sub-action** as a reusable engine primitive: `PendingBuildFences` (multi-shot, called from any of several entry points) and `CommitBuildPasture(cells)`.
- Wires up the **Fencing action space** end-to-end: `PendingFencing` (a thin parent that hosts space-specific trigger events) → `PendingBuildFences` → multi-shot `CommitBuildPasture` commits → `Stop` → `Stop`.
- Wires up the **Farm Redevelopment action space** end-to-end: `PendingFarmRedevelopment` (parent) → mandatory `PendingRenovate` → optional `PendingBuildFences` → `Stop`. Reuses the renovate sub-action machinery from House Redevelopment (TASK_5C) and the Build Fences machinery from this task.
- Adds a runtime active-universe selector — `UNIVERSE_RESTRICTED` is the default — with a per-call kwarg for swapping.

After this task, `step()` no longer raises `NotImplementedError` for `PlaceWorker(space="fencing")` *or* `PlaceWorker(space="farm_redevelopment")`. Every non-atomic action space implemented today has a working resolution path; only the harvest phases and rounds 5–14 remain as engine-level unimplemented pieces.

See **`FENCE_IDEAS.md`** for the broader design rationale, especially Section 3 (fixed-list enumeration with bitmaps), Section 4 (unified pasture-commit design), and Section 6 (open sub-questions). See **`TASK_6_pre.md`** for the universe construction this task consumes. The Farm Redevelopment structure mirrors House Redevelopment from **`TASK_5C.md` §3.6**, swapping the optional "improvement" branch for an optional "build_fences" branch.

---

## Scope

| Component | Status |
|---|---|
| `agricola/fences.py` — edge bitmap conventions, `PastureCandidate` dataclass, per-shape metadata helpers, four `UNIVERSE_*_ENTRIES` parallel tuples, four `UNIVERSE_*_SMALLEST_ENTRIES` fast-path tuples, `ENTRIES_BY_BM` lookup dict, fence-array packing helpers, `compute_new_fence_edges` shared helper, 1×1-at-(0, 0) addition to RESTRICTED + EXTENDED | extended |
| `agricola/pending.py` — `PendingFencing`, `PendingBuildFences`, `PendingFarmRedevelopment`, all added to `PendingDecision` | extended |
| `agricola/actions.py` — `CommitBuildPasture(cells)`, added to `Action` | extended |
| `agricola/legality.py` — `ACTIVE_FENCE_UNIVERSE_ENTRIES` / `ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES` / `ACTIVE_FENCE_UNIVERSE_SET` module constants, `_can_fence` predicate, `_any_legal_pasture_commit` + `_is_legal_for_can_fence` helpers, `_can_farm_redevelopment` predicate, `_enumerate_pending_fencing` + `_enumerate_pending_build_fences` + `_enumerate_pending_farm_redevelopment` enumerators, five registrations | extended |
| `agricola/resolution.py` — `_initiate_fencing`, `_choose_subaction_fencing`, `_initiate_farm_redevelopment`, `_choose_subaction_farm_redevelopment`, `_execute_build_pasture`, four registrations | extended |
| `agricola/engine.py` — drop `fencing` *and* `farm_redevelopment` from the `NotImplementedError` branch (eliminating the branch entirely), register `CommitBuildPasture` in `COMMIT_SUBACTION_HANDLERS` (with `auto_pop=False`) | extended |
| `tests/test_fencing.py` — engine-level integration tests for the Fencing flow | new |
| `tests/test_farm_redevelopment.py` — engine-level integration tests for the Farm Redevelopment flow | new |
| `tests/test_fences.py` — additions for `PastureCandidate` shape, edge-bitmap correctness, adjacency-bitmap correctness | extended |
| CLAUDE.md — status table, `fences.py` description, per-file descriptions for `pending.py` / `legality.py` / `resolution.py`, document the 4th sub-action cost-handling bucket | updated |

**Out of scope** (deferred to future tasks):

- Free-fence accounting fields on `PendingBuildFences`.
- Cost-modifier extension registry for cards that change per-edge cost.
- `after_build_fences` / `after_fencing` / `after_farm_redevelopment` trigger event mechanics.
- Card support that pushes `PendingBuildFences` from out-of-band effects.

---

## Motivation

Build Fences is the single most complex player decision in Agricola. The architecture chosen in `FENCE_IDEAS.md` decomposes it into a *reusable sub-action* (`PendingBuildFences`) that any number of parent pendings or card effects can push, with each commit naming one pasture cell-set via `CommitBuildPasture`. The sub-action is multi-shot — a single Build Fences action may build several pastures, each commit re-evaluating legality against the post-prior-commit state.

The action representation is load-bearing for AI training: the policy network will learn over `CommitBuildPasture` actions; MCTS branches on them. Pinning this surface decisively now — with a curated `UNIVERSE_RESTRICTED` default plus a per-call swap — lets training proceed without representational migrations later.

`PendingFencing` is a thin parent above `PendingBuildFences`. Without cards it carries one boolean (`build_fences_chosen`) used by `Stop`-legality. With cards, it hosts the space-specific `before_fencing` trigger event — distinct from `before_build_fences`, which fires at the sub-action layer (and will also fire when Build Fences is reached via Farm Redevelopment or card effects). Including the parent now keeps the architectural pattern uniform with other non-atomic spaces (Farmland, Side Job, Cultivation, …) that each have a parent + sub-action(s).

---

# Part 1 — Edge metadata in `fences.py`

## 1.1 Edge bitmap encoding

Two bit-indexed edge spaces:

| Space | Width | Indexing |
|---|---|---|
| Horizontal edges | 20 bits | `horizontal_fences[r][c]` → bit `r * NUM_COLS + c`. `r ∈ {0, 1, 2, 3}`, `c ∈ {0, 1, 2, 3, 4}`. |
| Vertical edges | 18 bits | `vertical_fences[r][c]` → bit `r * (NUM_COLS + 1) + c`. `r ∈ {0, 1, 2}`, `c ∈ {0, 1, 2, 3, 4, 5}`. |

These match the shapes of `Farmyard.horizontal_fences` (4×5) and `Farmyard.vertical_fences` (3×6).

For each cell `(r, c)`:

| Direction | Edge | Bit index |
|---|---|---|
| Top edge of cell | `horizontal_fences[r][c]` | `r * NUM_COLS + c` |
| Bottom edge of cell | `horizontal_fences[r + 1][c]` | `(r + 1) * NUM_COLS + c` |
| Left edge of cell | `vertical_fences[r][c]` | `r * (NUM_COLS + 1) + c` |
| Right edge of cell | `vertical_fences[r][c + 1]` | `r * (NUM_COLS + 1) + (c + 1)` |

These four formulas are used both at universe-build time (to compute each entry's boundary edges) and at runtime (to pack the live `Farmyard` fence arrays into bitmaps for the per-call legality check).

## 1.2 `PastureCandidate` dataclass

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PastureCandidate:
    cells_bm:        int                              # 15-bit cell-set bitmap
    h_boundary_bm:   int                              # 20-bit horizontal-edge boundary
    v_boundary_bm:   int                              # 18-bit vertical-edge boundary
    adjacency_bm:    int                              # 15-bit; cells one step outside cells_bm, in-grid
    cells:           frozenset[tuple[int, int]]       # for CommitBuildPasture construction
```

The other four fields are pure functions of `cells_bm`. Precomputed once at module import.

## 1.3 Metadata helpers

```python
def _boundary_h_bm(cells_bm: int) -> int:
    """Bitmap of horizontal fence-edges on the boundary of `cells_bm`.

    For each in-set cell, contribute its top edge if the cell above
    is out-of-set (or off-grid), and its bottom edge if the cell below
    is out-of-set (or off-grid).
    """
    bm = 0
    for idx in range(NUM_CELLS):
        if not (cells_bm & (1 << idx)):
            continue
        r, c = divmod(idx, NUM_COLS)
        # Top edge
        if r == 0 or not (cells_bm & (1 << ((r - 1) * NUM_COLS + c))):
            bm |= 1 << (r * NUM_COLS + c)
        # Bottom edge
        if r == NUM_ROWS - 1 or not (cells_bm & (1 << ((r + 1) * NUM_COLS + c))):
            bm |= 1 << ((r + 1) * NUM_COLS + c)
    return bm


def _boundary_v_bm(cells_bm: int) -> int:
    """Bitmap of vertical fence-edges on the boundary of `cells_bm`."""
    bm = 0
    for idx in range(NUM_CELLS):
        if not (cells_bm & (1 << idx)):
            continue
        r, c = divmod(idx, NUM_COLS)
        # Left edge
        if c == 0 or not (cells_bm & (1 << (r * NUM_COLS + (c - 1)))):
            bm |= 1 << (r * (NUM_COLS + 1) + c)
        # Right edge
        if c == NUM_COLS - 1 or not (cells_bm & (1 << (r * NUM_COLS + (c + 1)))):
            bm |= 1 << (r * (NUM_COLS + 1) + (c + 1))
    return bm


def _adjacency_bm(cells_bm: int) -> int:
    """In-grid orthogonal neighbors of `cells_bm` not themselves in `cells_bm`."""
    adj = 0
    b = cells_bm
    while b:
        idx = (b & -b).bit_length() - 1
        adj |= NEIGHBOR_BM[idx]
        b &= b - 1
    return adj & ~cells_bm
```

## 1.4 Parallel `UNIVERSE_*_ENTRIES` tuples

Each existing `UNIVERSE_*` bitmap tuple gets a parallel `_ENTRIES` companion — same order, one `PastureCandidate` per bitmap:

```python
def _make_entries(universe_bms: tuple[int, ...]) -> tuple[PastureCandidate, ...]:
    return tuple(
        PastureCandidate(
            cells_bm=bm,
            h_boundary_bm=_boundary_h_bm(bm),
            v_boundary_bm=_boundary_v_bm(bm),
            adjacency_bm=_adjacency_bm(bm),
            cells=frozenset(_cells_of(bm)),
        )
        for bm in universe_bms
    )


UNIVERSE_FULL_ENTRIES:       tuple[PastureCandidate, ...] = _make_entries(UNIVERSE_FULL)
UNIVERSE_FAMILY_ENTRIES:     tuple[PastureCandidate, ...] = _make_entries(UNIVERSE_FAMILY)
UNIVERSE_EXTENDED_ENTRIES:   tuple[PastureCandidate, ...] = _make_entries(UNIVERSE_EXTENDED)
UNIVERSE_RESTRICTED_ENTRIES: tuple[PastureCandidate, ...] = _make_entries(UNIVERSE_RESTRICTED)


# Fast-path tuples: precomputed 1×1-only subset of each universe, in the same
# lex-on-cells order. Used by _any_legal_pasture_commit (Part 4.3) to walk
# the cheap candidates first and short-circuit on the first legal one.
def _filter_singletons(entries: tuple[PastureCandidate, ...]) -> tuple[PastureCandidate, ...]:
    return tuple(e for e in entries if e.cells_bm.bit_count() == 1)

UNIVERSE_FULL_SMALLEST_ENTRIES:       tuple[PastureCandidate, ...] = _filter_singletons(UNIVERSE_FULL_ENTRIES)
UNIVERSE_FAMILY_SMALLEST_ENTRIES:     tuple[PastureCandidate, ...] = _filter_singletons(UNIVERSE_FAMILY_ENTRIES)
UNIVERSE_EXTENDED_SMALLEST_ENTRIES:   tuple[PastureCandidate, ...] = _filter_singletons(UNIVERSE_EXTENDED_ENTRIES)
UNIVERSE_RESTRICTED_SMALLEST_ENTRIES: tuple[PastureCandidate, ...] = _filter_singletons(UNIVERSE_RESTRICTED_ENTRIES)


# Bitmap-keyed lookup. Used by the effect function (which receives `commit.cells`
# and needs the entry's boundary metadata) and by the cost helper. Keyed off
# UNIVERSE_FULL, which by the containment chain RESTRICTED ⊆ EXTENDED ⊆ FAMILY
# ⊆ FULL covers every bitmap that can appear in any universe.
ENTRIES_BY_BM: dict[int, PastureCandidate] = {
    e.cells_bm: e for e in UNIVERSE_FULL_ENTRIES
}
```

The existing `UNIVERSE_*` and `UNIVERSE_*_SET` constants stay unchanged. The `_SET` frozensets are still used for canonicalization complement-membership lookup at enumerator-time. `ENTRIES_BY_BM` is used off the hot path (one lookup per `CommitBuildPasture` effect-time call); the enumerator iterates `*_ENTRIES` tuples directly without going through this dict. The `*_SMALLEST_ENTRIES` tuples are precomputed at module import for the hot-path fast iteration in `_any_legal_pasture_commit`.

## 1.5 Fence-array packing helpers

The runtime farmyard stores fences as nested tuples-of-tuples-of-bool. The enumerator needs bitmap form. Two helpers:

```python
def pack_fences_h(horizontal_fences: tuple) -> int:
    """Pack `Farmyard.horizontal_fences` (shape (4, 5)) into a 20-bit bitmap."""
    bm = 0
    for r in range(NUM_ROWS + 1):
        for c in range(NUM_COLS):
            if horizontal_fences[r][c]:
                bm |= 1 << (r * NUM_COLS + c)
    return bm


def pack_fences_v(vertical_fences: tuple) -> int:
    """Pack `Farmyard.vertical_fences` (shape (3, 6)) into an 18-bit bitmap."""
    bm = 0
    for r in range(NUM_ROWS):
        for c in range(NUM_COLS + 1):
            if vertical_fences[r][c]:
                bm |= 1 << (r * (NUM_COLS + 1) + c)
    return bm
```

Exposed as module-level functions (not underscored) — they're consumed by `legality.py` and `resolution.py`.

## 1.6 Reverse helpers (bitmap → fence-array updates)

The effect function needs to flip specific bits in the fence arrays back into the nested-tuple structure. Provide two helpers symmetric to the packers:

```python
def apply_fence_edges_h(
    horizontal_fences: tuple, new_h_bm: int,
) -> tuple:
    """Return a new 4×5 horizontal_fences tuple-of-tuples with `new_h_bm`'s bits set to True."""
    ...   # straightforward double-loop


def apply_fence_edges_v(
    vertical_fences: tuple, new_v_bm: int,
) -> tuple:
    """Return a new 3×6 vertical_fences tuple-of-tuples with `new_v_bm`'s bits set to True."""
    ...
```

## 1.7 Shared cost helper `compute_new_fence_edges`

Computes the new-fence-edge deltas and total wood cost for a candidate cell-set, given the player's current fence state. Lives in `fences.py` (not `legality.py`) because it operates over `Farmyard` duck-typing and bitmap operations only — no engine-state dependencies — and is consumed by both the enumerator (for affordability filtering) and the effect function (for the debit).

```python
def compute_new_fence_edges(
    farmyard, cells_bm: int,
) -> tuple[int, int, int]:
    """Return (h_new_bm, v_new_bm, wood_cost) for placing `cells_bm`'s
    boundary on top of the player's current fence state.

    wood_cost = popcount(h_new) + popcount(v_new) (default rule, 1 wood per edge).
    Card-driven cost modifiers will adjust this helper when the first such
    card lands — see Part 12.
    """
    entry = ENTRIES_BY_BM[cells_bm]
    h_fences_bm = pack_fences_h(farmyard.horizontal_fences)
    v_fences_bm = pack_fences_v(farmyard.vertical_fences)
    h_new = entry.h_boundary_bm & ~h_fences_bm
    v_new = entry.v_boundary_bm & ~v_fences_bm
    return h_new, v_new, h_new.bit_count() + v_new.bit_count()
```

`farmyard` is duck-typed (only `.horizontal_fences` and `.vertical_fences` are read), matching the convention used elsewhere in `fences.py` and `pasture.py`. Both `agricola/legality.py` and `agricola/resolution.py` import this helper from `fences.py`.

## 1.8 1×1-at-(0, 0) addition to RESTRICTED and EXTENDED

Both `enumerate_universe_restricted` and `enumerate_universe_extended` currently emit 1×1 shapes only on `PASTURE_CELLS` (cols 1-4). Cell `(0, 0)` is enclosable (it's in `ENCLOSABLE_CELLS = ALL_CELLS - STARTING_ROOMS`) but its 1×1 is excluded — likely an artifact of the strategist preferring to keep col 0 free for future room expansion northward from the starting rooms.

This excludes a corner case from the `_any_legal_pasture_commit` fast path (Part 4.3): if the only enclosable-and-adjacent cell available for a 1×1 happens to be `(0, 0)`, no fast-path 1×1 in RESTRICTED matches, and the optimization's claim — *"if any commit is legal, some 1×1 is legal in the active universe"* — fails for that state.

The fix is a one-character change in `enumerate_universe_restricted` and `enumerate_universe_extended`. The category-1 enumeration switches from `PASTURE_CELLS` to `ENCLOSABLE_CELLS` for the 1×1 case:

```python
# Before (in both enumerators):
shapes.update(_enum_rects(1, 1, PASTURE_CELLS))

# After:
shapes.update(_enum_rects(1, 1, ENCLOSABLE_CELLS))
```

Adds exactly the 1×1 at `(0, 0)` (the only ENCLOSABLE cell not in PASTURE_CELLS). This is consistent with the existing treatment of `(0, 0)` in category 16 (5-cell 2×2+1, where `(0, 0)` is already permitted as the "+1" extra cell).

The new entry's size impact:
- RESTRICTED: 108 → 109.
- EXTENDED: 192 → 193.

Test-file updates for the pinned size counts in `tests/test_fences.py` are noted in Part 8.

---

# Part 2 — Pending dataclasses in `pending.py`

## 2.1 `PendingFencing` (parent)

```python
@dataclass(frozen=True)
class PendingFencing:
    PENDING_ID:    ClassVar[str] = "fencing"
    TRIGGER_EVENT: ClassVar[str] = "before_fencing"
    player_idx:           int
    initiated_by_id:      str
    build_fences_chosen:  bool = False
    triggers_resolved:    frozenset = frozenset()
```

Pushed by `_initiate_fencing` from `PlaceWorker(space="fencing")` with `initiated_by_id="space:fencing"`. The only sub-action is `build_fences`; `build_fences_chosen` gates `Stop`-legality (illegal until the sub-action has been entered).

`TRIGGER_EVENT` is included for forward-compat with cards that fire on the Fencing space specifically — no consumer in this task. `triggers_resolved` likewise.

## 2.2 `PendingBuildFences` (sub-action, multi-shot)

```python
@dataclass(frozen=True)
class PendingBuildFences:
    PENDING_ID:    ClassVar[str] = "build_fences"
    TRIGGER_EVENT: ClassVar[str] = "before_build_fences"
    player_idx:           int
    initiated_by_id:      str
    pastures_built:       int = 0
    fences_built:         int = 0
    subdivision_started:  bool = False
    triggers_resolved:    frozenset = frozenset()
```

Pushed by `_choose_subaction_fencing` (and later by Farm Redevelopment's choose handler, and by card effects). The three state fields are all updated per `CommitBuildPasture`:

- `pastures_built` increments by 1 per commit. `Stop`-legality on this pending requires `pastures_built >= 1`.
- `fences_built` increments by the number of new fence-edges placed in that commit. Carries forward to satisfy card patterns like *"each time you build a number of fences equal to or greater than the current round, get 1 vegetable"*.
- `subdivision_started` flips to `True` the first time a *subdivision* commit lands (a commit whose cells are entirely within an existing pasture). Implements the builds-before-subdivisions ordering rule (see 2.3 below).

`auto_pop=False` for the matching `CommitBuildPasture` handler (multi-shot pattern).

## 2.3 Design choice: builds-before-subdivisions ordering rule

Within one Build Fences action, **all new-pasture builds must precede any subdivisions**. Once a subdivision commit has landed (`subdivision_started=True`), the enumerator no longer offers new-pasture build candidates for the remainder of the action.

**Rule.** A new-pasture commit (cells entirely in unenclosed area) is legal only when `pending.subdivision_started == False`. A subdivision commit (cells entirely within an existing pasture) is legal regardless of `subdivision_started`, and flips it to `True` if it was `False`.

**Why.** Multi-commit Fencing actions have path-level redundancy: build-then-subdivide reaches the same end state as subdivide-then-build, and (without an ordering rule) MCTS expands both as distinct subtrees. For K new-pasture builds + L subdivisions in one action, the unconstrained inflation is `(K+L)!` orderings vs `K! × L!` with the rule — ratio `C(K+L, K)`. Across a game with 1-2 Fencing actions of 2-3 commits each, the cumulative game-tree-width factor is plausibly 4-36×. The rule cuts that inflation at the action-space level, compounding multiplicatively with caching / DAG-MCTS mitigations at the search layer (FENCE_IDEAS Section 5).

**Direction matters: builds first, not subdivisions first.** The reverse direction (subdivisions before builds) would break reachability under curated universes. Consider an end state reachable only via "build P, then subdivide P naming Q1 (Q2 falls out as by-product)", where Q2 isn't in the active universe. Subdivisions-before-builds would block this path: P doesn't exist in the subdivision phase, and after building P the subdivision phase is over. The chosen direction (builds first, then subdivisions) preserves reachability — the same path lands cleanly as "build P (phase 1), then subdivide P naming Q1 (phase 2)."

**Cost.** One bool field on `PendingBuildFences`; one branch in the enumerator; one line in the effect function. The policy network must condition on `subdivision_started` to predict legality correctly, but the rule is deterministic and the smaller per-state action set is plausibly a net positive for credit assignment.

## 2.4 `PendingFarmRedevelopment` (parent)

```python
@dataclass(frozen=True)
class PendingFarmRedevelopment:
    PENDING_ID:    ClassVar[str] = "farm_redevelopment"
    TRIGGER_EVENT: ClassVar[str] = "before_farm_redevelopment"
    player_idx:           int
    initiated_by_id:      str
    renovate_chosen:      bool = False
    build_fences_chosen:  bool = False
    triggers_resolved:    frozenset = frozenset()
```

Pushed by `_initiate_farm_redevelopment` from `PlaceWorker(space="farm_redevelopment")` with `initiated_by_id="space:farm_redevelopment"`. The space's two-step structure mirrors House Redevelopment (TASK_5C §3.6):

- **Renovate is mandatory.** `Stop`-legality on this pending requires `renovate_chosen=True`.
- **Build Fences is optional** (`"renovate **then** Build Fences"`) — offered as an additional sub-action only after the renovate step has been entered, and only when at least one legal pasture commit exists in the post-renovate state.

`renovate_chosen` and `build_fences_chosen` follow the choose-time flag-setting convention (set when the corresponding `ChooseSubAction` fires).

`TRIGGER_EVENT="before_farm_redevelopment"` is included for forward-compat with cards that fire on the Farm Redevelopment space specifically — no consumer in this task. `triggers_resolved` likewise.

Reuses:
- `PendingRenovate` from `pending.py` (TASK_5C §2.4) for the renovate step — same `CommitRenovate`, `_execute_renovate`, and cost-on-pending mechanics as House Redevelopment.
- `PendingBuildFences` from §2.2 above for the build_fences step — same multi-shot pattern, same `CommitBuildPasture` commits, same `subdivision_started` ordering rule. The pending is pushed with `initiated_by_id="farm_redevelopment"` (the parent's `PENDING_ID`, no prefix) — distinct from the Fencing space's path which pushes with `initiated_by_id="fencing"`. Provenance lets future cards gate on entry point.

## 2.5 Union update

```python
PendingDecision = (
    PendingGrainUtilization | PendingSow | PendingBakeBread
    | PendingFarmland | PendingCultivation | PendingPlow
    | PendingSideJob | PendingBuildStables | PendingBuildRooms
    | PendingSheepMarket | PendingPigMarket | PendingCattleMarket
    | PendingMajorMinorImprovement | PendingBuildMajor
    | PendingHouseRedevelopment | PendingRenovate
    | PendingClayOven | PendingStoneOven
    | PendingFarmExpansion
    | PendingFencing | PendingBuildFences            # ← new (§2.1, §2.2)
    | PendingFarmRedevelopment                       # ← new (§2.4)
)
```

---

# Part 3 — `CommitBuildPasture` in `actions.py`

```python
@dataclass(frozen=True)
class CommitBuildPasture(CommitSubAction):
    cells: frozenset                                  # frozenset[tuple[int, int]]
```

Single field. `frozenset` gives content-based equality and hashing, so two `CommitBuildPasture` objects naming the same cell-set compare equal regardless of construction order. By convention, callers iterating `cells` for display or logging sort by `(row, col)` lexicographic order; this is implicit in tests and trace dumps.

The cost paid by the commit is NOT a field on the commit object. It's a pure function of `(state, commit.cells)` computed by a shared helper (`compute_new_fence_edges` in `fences.py` — see Part 1.7). This is a new sub-action cost-handling pattern — the **4th cost-handling bucket**, documented in CLAUDE.md updates (Part 9):

> *Bucket 4 — Pure-function-of-state-and-commit cost.* Cost is neither fixed at push time (bucket 2) nor looked up in a const table (bucket 3). It is computed at execute time as a deterministic function of `(state, commit_parameters)`. Both the enumerator (for affordability filtering) and the effect function (for the debit) call the same helper. Fencing is the canonical example: `cost = wood-per-new-fence-edge × popcount(boundary & ~current_fences)`.

*Note re TASK_5C §2 preview:* TASK_5C anticipated `PendingBuildFences` carrying a `cost: Resources` field to match the bucket-2 convention from `PendingBuildStable` / `PendingRenovate`. We deviated to bucket 4 because we're implementing Build Fences as a multi-step process where each commit names one pasture cell-set; a single push-time cost on the pending doesn't fit that shape. Card support will adjust the helper's behavior slightly — the exact mechanism is deferred to whenever the first such card lands (see Part 12).

`Action` union updated:

```python
Action = (
    PlaceWorker | ChooseSubAction | Stop | FireTrigger
    | CommitSow | CommitBake | CommitPlow
    | CommitBuildStable | CommitBuildRoom | CommitBuildMajor
    | CommitRenovate | CommitAccommodate
    | CommitBuildPasture                              # ← new
)
```

---

# Part 4 — Legality in `legality.py`

## 4.1 Active-universe constants

Three module-level constants set the default for `legal_actions`. All three can be reassigned at runtime; all three can be overridden per-call via enumerator kwargs. They must point at the same universe (entries / smallest-entries / set are aligned by construction in `fences.py`).

```python
from agricola.fences import (
    UNIVERSE_RESTRICTED_ENTRIES,
    UNIVERSE_RESTRICTED_SMALLEST_ENTRIES,
    UNIVERSE_RESTRICTED_SET,
)

ACTIVE_FENCE_UNIVERSE_ENTRIES:          tuple     = UNIVERSE_RESTRICTED_ENTRIES
ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES: tuple     = UNIVERSE_RESTRICTED_SMALLEST_ENTRIES
ACTIVE_FENCE_UNIVERSE_SET:              frozenset = UNIVERSE_RESTRICTED_SET
```

Three constants so the SMALLEST tuple stays in sync with the matched ENTRIES tuple. To switch globally: reassign all three at once (e.g., a small `set_active_fence_universe(name)` helper or experiment setup). To switch for one call: pass the `entries=` / `smallest_entries=` / `universe_set=` kwargs to the enumerator.

## 4.2 Shared cost helper

`compute_new_fence_edges(farmyard, cells_bm)` lives in `agricola/fences.py` — see Part 1.7. Both the per-entry legality predicate (used by the enumerator and by `_can_fence` via `_any_legal_pasture_commit`) and the effect function call it. Imported here as:

```python
from agricola.fences import compute_new_fence_edges
```

## 4.3 `_can_fence` predicate

```python
def _can_fence(state: GameState, p: PlayerState) -> bool:
    """True iff `p` could legally start a Build Fences action (Fencing space)."""
    if not _is_available(state, "fencing"):
        return False
    # Cheap pre-checks: wood and supply.
    if p.resources.wood < 1:
        return False
    if fences_in_supply(p.farmyard) < 1:
        return False
    # Final check: at least one universe entry is legal for this player.
    # Reuses the enumerator's per-entry logic via a generator-style early return.
    return _any_legal_pasture_commit(state, p)
```

`_any_legal_pasture_commit` is an internal helper called from `_can_fence`. It returns `True` on the first legal entry it finds (early-exit; no list build). It iterates the precomputed `smallest_entries` tuple first, then falls back to the full `entries` tuple — capitalizing on the "if any commit is legal, some 1×1 commit is legal" property (per the design conversation: any legal larger shape contains a cell whose 1×1 is itself enclosable, adjacent, and at most as expensive as the larger shape; the (0, 0)-1×1 addition in Part 1.8 ensures every enclosable cell has a 1×1 candidate in the active universe).

```python
def _any_legal_pasture_commit(
    state: GameState, p: PlayerState,
    *,
    entries:          tuple     = ACTIVE_FENCE_UNIVERSE_ENTRIES,
    smallest_entries: tuple     = ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES,
    universe_set:     frozenset = ACTIVE_FENCE_UNIVERSE_SET,
) -> bool:
    # Fast path: precomputed 1×1 tuple (~13 entries under RESTRICTED).
    for entry in smallest_entries:
        if _is_legal_for_can_fence(state, p, entry, universe_set):
            return True
    # Slow path: full universe minus 1×1's (already checked above).
    for entry in entries:
        if entry.cells_bm.bit_count() == 1:
            continue
        if _is_legal_for_can_fence(state, p, entry, universe_set):
            return True
    return False
```

`smallest_entries` is a precomputed tuple (one of the four `UNIVERSE_*_SMALLEST_ENTRIES`) so the fast pass touches only the ~10–13 1×1 candidates rather than scanning the full ~109–1518-entry universe with a popcount filter. The three kwargs (`entries`, `smallest_entries`, `universe_set`) must point at the same universe; that's the cost of the precomputation choice. For globally swapping universe, reassign all three module constants together (or use a small helper); for per-call swapping in tests, pass all three kwargs.

`_is_legal_for_can_fence(state, p, entry, universe_set)` is the per-entry legality predicate, factored out of the main enumerator's loop body for reuse here. It applies the same chain (enclosable, subdivision-or-new-pasture, ordering rule, adjacency, affordability, fences-in-supply, ≥1 new edge, canonicalization) but returns a bool rather than appending to a list.

## 4.4 `_enumerate_pending_fencing`

```python
def _enumerate_pending_fencing(
    state: GameState, pending: PendingFencing,
) -> list[Action]:
    actions: list[Action] = []
    if not pending.build_fences_chosen:
        # Forced single-option choose; the engine surfaces it as an explicit
        # decision per the no-auto-singleton principle.
        actions.append(ChooseSubAction(name="build_fences"))
    else:
        actions.append(Stop())
    # Eligible card triggers at `before_fencing` would be appended here when
    # card support is added; no consumers today.
    return actions
```

## 4.5 `_enumerate_pending_build_fences`

The core enumerator. Implements the unified candidate rule from `FENCE_IDEAS.md` Section 4.

```python
def _enumerate_pending_build_fences(
    state: GameState,
    pending: PendingBuildFences,
    *,
    entries: tuple = ACTIVE_FENCE_UNIVERSE_ENTRIES,
    universe_set: frozenset = ACTIVE_FENCE_UNIVERSE_SET,
) -> list[Action]:
    p = state.players[pending.player_idx]
    farmyard = p.farmyard

    # Per-call state bitmaps (once each).
    enclosable_bm = _enclosable_cells_bm(farmyard)        # empty or stable cells
    pasture_bms = tuple(_cells_bm_of_pasture(P) for P in farmyard.pastures)
    existing_pasture_cells_bm = 0
    for P_bm in pasture_bms:
        existing_pasture_cells_bm |= P_bm
    h_fences_bm = pack_fences_h(farmyard.horizontal_fences)
    v_fences_bm = pack_fences_v(farmyard.vertical_fences)
    wood = p.resources.wood
    fences_left = fences_in_supply(farmyard)
    has_existing_pastures = bool(pasture_bms)

    actions: list[Action] = []

    for entry in entries:
        bm = entry.cells_bm

        # 1. Enclosable cells only.
        if bm & ~enclosable_bm:
            continue

        # 2. Subdivision vs new-pasture: candidate must be entirely within one
        #    existing pasture, or entirely in unenclosed area.
        is_subdivision = False
        parent_bm = 0
        if bm & existing_pasture_cells_bm:
            # Some cells are in an existing pasture; verify all cells are in
            # the SAME pasture.
            for P_bm in pasture_bms:
                if (bm & P_bm) == bm:
                    is_subdivision = True
                    parent_bm = P_bm
                    break
            if not is_subdivision:
                continue                                   # straddles multiple
        # else: bm is entirely unenclosed; new-pasture case.

        # 2b. Builds-before-subdivisions ordering rule (see 2.3). Once a
        #     subdivision has landed in this action, new-pasture commits are
        #     no longer legal.
        if (not is_subdivision) and pending.subdivision_started:
            continue

        # 3. Adjacency: subdivision is fine (within), new-pasture must touch
        #    an existing pasture, OR there are no existing pastures yet.
        if not is_subdivision and has_existing_pastures:
            if not (entry.adjacency_bm & existing_pasture_cells_bm):
                continue

        # 4. Affordability + fences-in-supply + at-least-one-new-fence.
        #    The "≥1 new edge" guard also rejects candidates that exactly
        #    re-state an existing pasture (zero new edges placed).
        h_new = entry.h_boundary_bm & ~h_fences_bm
        v_new = entry.v_boundary_bm & ~v_fences_bm
        new_count = h_new.bit_count() + v_new.bit_count()
        if new_count < 1:                                  # would place no fence
            continue
        if new_count > wood:
            continue
        if new_count > fences_left:
            continue

        # 5. Subdivision canonicalization: if the complement-within-parent is
        #    also in the universe, emit only the lex-smaller-min-cell side.
        if is_subdivision:
            complement_bm = parent_bm & ~bm
            if complement_bm in universe_set:
                lo_self = (bm & -bm).bit_length()
                lo_comp = (complement_bm & -complement_bm).bit_length()
                if lo_comp < lo_self:
                    continue                               # complement is canonical
            # Either complement not in universe, or self is canonical.

        actions.append(CommitBuildPasture(cells=entry.cells))

    # Stop is legal once at least one pasture has been built; otherwise no exit.
    if pending.pastures_built >= 1:
        actions.append(Stop())

    # before_build_fences trigger appender goes here when cards land.

    return actions
```

Helper additions in this file:

```python
def _enclosable_cells_bm(farmyard) -> int:
    """Bitmap of cells that can be enclosed by fences (EMPTY or STABLE)."""
    bm = 0
    for r in range(NUM_ROWS):
        for c in range(NUM_COLS):
            ct = farmyard.grid[r][c].cell_type
            if ct == CellType.EMPTY or ct == CellType.STABLE:
                bm |= 1 << (r * NUM_COLS + c)
    return bm


def _cells_bm_of_pasture(pasture) -> int:
    """Cell-set of a `Pasture` as a bitmap."""
    bm = 0
    for (r, c) in pasture.cells:
        bm |= 1 << (r * NUM_COLS + c)
    return bm
```

## 4.6 `_can_farm_redevelopment` predicate

```python
def _can_farm_redevelopment(state: GameState, p: PlayerState) -> bool:
    """True iff `p` could legally start a Farm Redevelopment action."""
    if not _is_available(state, "farm_redevelopment"):
        return False
    # Renovate is mandatory; Build Fences is optional. So affordability of
    # the renovate step is the only "must be possible" precondition.
    return _can_renovate(p)
```

Reuses `_can_renovate` from `legality.py` (TASK_5C §3.6 dependency). A STONE house fails `_can_renovate` (no further material to renovate to); WOOD and CLAY houses succeed if they have the matching cost (clay/stone × num_rooms + 1 reed).

The Build Fences leg is *optional*, so its feasibility does not gate placement legality. Once the player commits the worker, they get the renovate; whether or not they can subsequently build fences is decided inside the enumerator at the post-renovate state.

## 4.7 `_enumerate_pending_farm_redevelopment`

Mirrors `_enumerate_pending_house_redevelopment` (TASK_5C §3.6), with the optional second step swapped from "improvement" to "build_fences":

```python
def _enumerate_pending_farm_redevelopment(
    state: GameState, pending: PendingFarmRedevelopment,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.renovate_chosen and _can_renovate(p):
        actions.append(ChooseSubAction(name="renovate"))
    if (pending.renovate_chosen
            and not pending.build_fences_chosen
            and _any_legal_pasture_commit(state, p)):
        actions.append(ChooseSubAction(name="build_fences"))
    if pending.renovate_chosen:
        actions.append(Stop())
    return actions
```

`Stop` becomes legal as soon as the renovate step has been entered (`renovate_chosen=True`), whether or not the player goes on to take the optional Build Fences. It is illegal before renovate — renovate is mandatory.

The `_any_legal_pasture_commit` gate on the `build_fences` sub-action is what reuses the fast-path optimization from §4.3: only offer Build Fences when some pasture commit is actually legal in the current state.

## 4.8 Registrations

```python
NON_ATOMIC_LEGALITY["fencing"]            = _can_fence
NON_ATOMIC_LEGALITY["farm_redevelopment"] = _can_farm_redevelopment

PENDING_ENUMERATORS[PendingFencing]            = _enumerate_pending_fencing
PENDING_ENUMERATORS[PendingBuildFences]        = _enumerate_pending_build_fences
PENDING_ENUMERATORS[PendingFarmRedevelopment]  = _enumerate_pending_farm_redevelopment
```

---

# Part 5 — Resolution in `resolution.py`

## 5.1 `_initiate_fencing`

```python
def _initiate_fencing(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingFencing(
        player_idx=ap, initiated_by_id="space:fencing",
    ))
```

Registered in `NONATOMIC_HANDLERS`.

## 5.2 `_choose_subaction_fencing`

Follows the choose-time flag-setting convention:

```python
def _choose_subaction_fencing(state: GameState, action: ChooseSubAction) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFencing)
    assert action.name == "build_fences"
    state = replace_top(state, dataclasses.replace(top, build_fences_chosen=True))
    return push(state, PendingBuildFences(
        player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
    ))
```

Registered in `CHOOSE_SUBACTION_HANDLERS` keyed by `PendingFencing`.

## 5.3 `_execute_build_pasture`

```python
def _execute_build_pasture(
    state: GameState, player_idx: int, commit: CommitBuildPasture,
) -> GameState:
    p = state.players[player_idx]
    farmyard = p.farmyard

    # 1. Pack cells to bitmap.
    cells_bm = sum(1 << (r * NUM_COLS + c) for (r, c) in commit.cells)

    # 2. Determine new-pasture vs subdivision (for the ordering rule). Use
    #    the BEFORE-commit farmyard: a commit is a subdivision iff any of
    #    its cells overlaps an existing pasture pre-commit.
    existing_pasture_cells_bm = 0
    for P in farmyard.pastures:
        for (r, c) in P.cells:
            existing_pasture_cells_bm |= 1 << (r * NUM_COLS + c)
    is_subdivision = bool(cells_bm & existing_pasture_cells_bm)

    # 3. Compute new-edge deltas + cost.
    h_new, v_new, wood_cost = compute_new_fence_edges(farmyard, cells_bm)

    # 4. Apply fence-array updates.
    new_h = apply_fence_edges_h(farmyard.horizontal_fences, h_new)
    new_v = apply_fence_edges_v(farmyard.vertical_fences, v_new)

    # 5. Recompute pasture decomposition. After this task there are TWO
    #    distinct effect functions that recompute pastures: _execute_build_stable
    #    (shared by Side Job's and Farm Expansion's build_stables sub-action)
    #    and this function (shared by Fencing's and Farm Redev's build_fences
    #    sub-action). Same caller-discipline rule applies to both.
    new_pastures = compute_pastures_from_arrays(farmyard.grid, new_h, new_v)
    new_farmyard = dataclasses.replace(
        farmyard, horizontal_fences=new_h, vertical_fences=new_v,
        pastures=new_pastures,
    )

    # 6. Debit wood.
    new_resources = p.resources - Resources(wood=wood_cost)

    # 7. Update player.
    new_player = dataclasses.replace(
        p, farmyard=new_farmyard, resources=new_resources,
    )
    state = _update_player(state, player_idx, new_player)

    # 8. Bump pending counters + ordering-rule flag (no auto-pop; Stop pops).
    top = state.pending_stack[-1]
    new_top = dataclasses.replace(
        top,
        pastures_built=top.pastures_built + 1,
        fences_built=top.fences_built + wood_cost,
        subdivision_started=top.subdivision_started or is_subdivision,
    )
    return replace_top(state, new_top)
```

Note: the function is registered with `auto_pop=False` in `COMMIT_SUBACTION_HANDLERS` (in `engine.py`), so the dispatcher does not pop after this function returns — `replace_top` keeps `PendingBuildFences` on top with updated counters.

## 5.4 `_initiate_farm_redevelopment`

```python
def _initiate_farm_redevelopment(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingFarmRedevelopment(
        player_idx=ap, initiated_by_id="space:farm_redevelopment",
    ))
```

Registered in `NONATOMIC_HANDLERS`.

## 5.5 `_choose_subaction_farm_redevelopment`

Mirrors `_choose_subaction_house_redevelopment` (TASK_5C §3.6) with the optional branch swapped to `build_fences`. The renovate branch carries the same cost-computation logic — `clay × num_rooms + 1 reed` for WOOD→CLAY, `stone × num_rooms + 1 reed` for CLAY→STONE — stored on `PendingRenovate.cost` per the bucket-2 cost-handling convention.

```python
def _choose_subaction_farm_redevelopment(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    p = state.players[p_idx]
    if action.name == "renovate":
        num_rooms = sum(
            1 for r in range(3) for c in range(5)
            if p.farmyard.grid[r][c].cell_type == CellType.ROOM
        )
        if p.house_material == HouseMaterial.WOOD:
            cost = Resources(clay=num_rooms, reed=1)
        else:  # CLAY (STONE filtered out by _can_renovate at the parent enumerator)
            cost = Resources(stone=num_rooms, reed=1)
        state = replace_top(state, dataclasses.replace(top, renovate_chosen=True))
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID, cost=cost,
        ))
    if action.name == "build_fences":
        state = replace_top(state, dataclasses.replace(top, build_fences_chosen=True))
        return push(state, PendingBuildFences(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

Registered in `CHOOSE_SUBACTION_HANDLERS` keyed by `PendingFarmRedevelopment`.

**No new effect function.** Both branches push pendings whose effect functions already exist:
- `PendingRenovate` → `_execute_renovate` (TASK_5C §2.4).
- `PendingBuildFences` → `_execute_build_pasture` (§5.3 above).

`Stop` continues to use the generic `_apply_stop` to pop the parent once renovate has been entered.

## 5.6 Registrations

```python
NONATOMIC_HANDLERS["fencing"]            = _initiate_fencing
NONATOMIC_HANDLERS["farm_redevelopment"] = _initiate_farm_redevelopment

CHOOSE_SUBACTION_HANDLERS[PendingFencing]           = _choose_subaction_fencing
CHOOSE_SUBACTION_HANDLERS[PendingFarmRedevelopment] = _choose_subaction_farm_redevelopment
```

---

# Part 6 — Engine wiring in `engine.py`

## 6.1 Drop the `NotImplementedError` for `fencing` and `farm_redevelopment`

In `_apply_place_worker`, the current branch:

```python
if action.space in ("farm_redevelopment", "fencing"):
    raise NotImplementedError(...)
```

is removed entirely. Both spaces now have registered `NONATOMIC_HANDLERS` entries (`_initiate_fencing` and `_initiate_farm_redevelopment`), and dispatch proceeds through the standard non-atomic path. After this task, every action space in `legal_placements`'s output has a working initiate path.

## 6.2 `COMMIT_SUBACTION_HANDLERS` entry

```python
COMMIT_SUBACTION_HANDLERS[CommitBuildPasture] = (
    PendingBuildFences, _execute_build_pasture, False,
)
```

`auto_pop=False` — the effect function leaves `PendingBuildFences` on top for further commits or for `Stop`.

`Stop` continues to use the generic `_apply_stop` in `engine.py` (pops the top of the stack); no new handling.

---

# Part 7 — Tests in `tests/test_fencing.py` (new file)

Engine-level integration tests under the default (RESTRICTED) universe unless a test explicitly swaps. Tests use the `factories.py` + `test_utils.py` scaffolding.

| # | Test |
|---|---|
| 1 | **Single-pasture basic walk:** wood + supply available, no existing pastures. `PlaceWorker("fencing") → ChooseSubAction("build_fences") → CommitBuildPasture(cells={(0, 1)}) → Stop → Stop`. End state: farmyard has one 1×1 pasture; 4 wood debited; 4 fences placed; both pendings popped. |
| 2 | **Multi-pasture in one action:** build pasture A, then build pasture B adjacent to A — both commits land in one Build Fences invocation. |
| 3 | **Subdivision:** start with a 2×1 pasture, build a 1×1 subdivision that splits it. End state: two 1×1 pastures, 1 new fence placed. |
| 4 | **Subdivision canonicalization:** in a 2×1 pasture, both halves are valid subdivisions but only the lex-smaller side appears in `legal_actions`. |
| 5 | **First-pasture-anywhere rule:** with no existing pastures, every shape in RESTRICTED that fits the player's enclosable cells is enumerated, regardless of adjacency. |
| 6 | **Adjacency rule for subsequent new pastures:** with one existing pasture, candidates not orthogonally touching it (and not subdivisions) are excluded. |
| 7 | **Enclosable filter:** cells with rooms or fields are excluded; any universe entry overlapping a non-enclosable cell is filtered. |
| 8 | **Wood affordability binding:** with only 2 wood, only shapes needing ≤ 2 new edges appear. |
| 9 | **Fences-in-supply binding:** with only 2 fences left in supply, only shapes needing ≤ 2 new edges appear. |
| 10 | **Re-state-existing rejection:** in a state with an existing pasture P, `CommitBuildPasture(cells=P.cells)` is filtered (would place 0 new fences). |
| 11 | **Stop legality on `PendingBuildFences`:** illegal at `pastures_built == 0`; legal at `pastures_built >= 1`. |
| 12 | **Stop legality on `PendingFencing`:** illegal at `build_fences_chosen == False`; legal at `build_fences_chosen == True`. |
| 13 | **Counter updates:** `pastures_built` and `fences_built` increment correctly across multiple commits. |
| 13b | **Ordering rule — new pasture then subdivision is legal:** with one existing pasture P + room for a new pasture A, commit A first then subdivide P. Both commits succeed; `subdivision_started` flips to `True` only on the second commit. |
| 13c | **Ordering rule — subdivision then new pasture is blocked:** with the same setup, subdivide P first; verify that subsequent new-pasture commits no longer appear in `legal_actions` (only further subdivisions of existing pastures, plus `Stop`, are offered). |
| 13d | **Ordering rule — `subdivision_started` flag semantics:** `subdivision_started` starts `False`; flips to `True` exactly when a commit is a subdivision (any cell overlaps an existing pasture pre-commit); stays `True` once set. |
| 14 | **Stack invariants:** `ChooseSubAction` sets `build_fences_chosen=True` and pushes `PendingBuildFences`; `CommitBuildPasture` does NOT pop (`auto_pop=False`); `Stop` pops; both pendings carry correct `initiated_by_id` provenance (`"space:fencing"` on parent, `"fencing"` on child). |
| 15 | **`_can_fence` predicate:** True in baseline. False when (a) 0 wood, (b) 0 fences in supply, (c) all enclosable cells unreachable (e.g., farmyard with rooms + fields filling every cell). |
| 16 | **Universe swappability via kwarg:** prepare a state where a shape in `UNIVERSE_EXTENDED \ UNIVERSE_RESTRICTED` is the player's only choice. Verify `_enumerate_pending_build_fences` returns empty under RESTRICTED but non-empty under EXTENDED when passed `entries=UNIVERSE_EXTENDED_ENTRIES, universe_set=UNIVERSE_EXTENDED_SET`. Same kwarg swap for `_any_legal_pasture_commit` includes `smallest_entries=UNIVERSE_EXTENDED_SMALLEST_ENTRIES`. |
| 17 | **Universe swappability via module constants:** monkey-patch all three of `legality.ACTIVE_FENCE_UNIVERSE_ENTRIES`, `legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES`, and `legality.ACTIVE_FENCE_UNIVERSE_SET` to the EXTENDED references in concert; verify the no-kwarg enumerator and `_any_legal_pasture_commit` calls now produce the EXTENDED legality set. Restore all three after. |
| 18 | **Pasture cache recompute:** verify `new_farmyard.pastures` reflects the new pasture(s) after each commit (uses `compute_pastures_from_arrays`, not a stale cache). |
| 19 | **Random-agent end-to-end smoke:** the test reads the *current* `IMPLEMENTED_NON_ATOMIC_SPACES` set (which grows across the implementation order — Fencing added in step 7, Farm Redevelopment added in step 10) and runs `random_agent_play` for several seeds. Final state of the set is "both spaces included"; the test passes at both intermediate points. Verify no errors and that `BEFORE_SCORING` is reached. |

---

# Part 7B — Tests in `tests/test_farm_redevelopment.py` (new file)

Engine-level integration tests for the Farm Redevelopment flow. Mirrors `tests/test_house_redevelopment.py` (TASK_5C §3.6 dependency), with the optional second step swapped from improvement to build_fences. Tests use the `factories.py` + `test_utils.py` scaffolding.

| # | Test |
|---|---|
| 1 | **Renovate-only walk:** WOOD-house player with 2 clay + 1 reed. `PlaceWorker("farm_redevelopment") → ChooseSubAction("renovate") → CommitRenovate → Stop`. End state: house material is CLAY; 2 clay + 1 reed debited; both pendings popped. |
| 2 | **Renovate-then-build-fences walk:** WOOD-house player with 2 clay + 1 reed + enough wood + 1 enclosable PASTURE cell. Full sequence including a `CommitBuildPasture` and two `Stop`s pops the chain cleanly. End state: CLAY house + one new pasture. |
| 3 | **Build Fences step requires `renovate_chosen` first:** before renovating, `ChooseSubAction("build_fences")` is not in `legal_actions(state)`; only `ChooseSubAction("renovate")` is. |
| 4 | **Stop legality:** illegal before `renovate_chosen=True`; legal after the renovate commit (regardless of whether Build Fences is taken). |
| 5a | **Material progression — WOOD → CLAY:** WOOD-house player with affordable cost completes Farm Redevelopment; ends with CLAY house. |
| 5b | **Material progression — CLAY → STONE:** CLAY-house player with affordable cost completes Farm Redevelopment; ends with STONE house. |
| 5c | **Material progression — STONE blocked:** STONE-house player cannot start Farm Redevelopment; `_can_farm_redevelopment` returns False because `_can_renovate` returns False on STONE. |
| 6 | **Renovation cost on pending:** `PendingRenovate.cost == Resources(clay=num_rooms, reed=1)` for WOOD→CLAY; `Resources(stone=num_rooms, reed=1)` for CLAY→STONE. Computed by `_choose_subaction_farm_redevelopment` and stored on the pending; `_execute_renovate` (TASK_5C §2.4) debits via `p.resources - pending.cost`. |
| 7 | **Inner `PendingBuildFences.initiated_by_id`:** when reached via Farm Redevelopment, equals `"farm_redevelopment"` (not `"fencing"` and not `"space:farm_redevelopment"`) — verifies provenance distinct from the Fencing-space entry. |
| 8 | **Build Fences engine reuses cleanly:** after the renovate commit, the player commits multiple pastures, exercises the `subdivision_started` ordering rule, and ends with two `Stop`s. Compare the resulting `farmyard.grid`, `farmyard.horizontal_fences`, `farmyard.vertical_fences`, `farmyard.pastures`, and `resources` against the same Build Fences sequence reached via the Fencing space starting from an otherwise-equivalent state — assert equality on those fields specifically (the pending-stack history and the `house_material` will of course differ). |
| 9 | **`_can_farm_redevelopment` predicate:** True when WOOD/CLAY house + affordability. False when (a) STONE house, (b) missing reed, (c) missing clay/stone, (d) space already occupied / not yet revealed. |
| 10 | **Build Fences optional, gated on legality:** when post-renovate state has no legal pasture commit (e.g., player has 0 wood after paying renovate), the `build_fences` sub-action is NOT in `legal_actions` — only `Stop`. |
| 11 | **Stack invariants:** parent's `renovate_chosen` set at choose-time (not commit-time); parent's `build_fences_chosen` set at choose-time; both inner pendings pop on their respective commits/stops; parent pops only via Stop. Provenance: parent `initiated_by_id="space:farm_redevelopment"`, inner `PendingRenovate.initiated_by_id="farm_redevelopment"`, inner `PendingBuildFences.initiated_by_id="farm_redevelopment"`. |

---

# Part 8 — Additions to `tests/test_fences.py`

| # | Test |
|---|---|
| 1 | `PastureCandidate` is a frozen dataclass with the five fields, each typed correctly. |
| 2 | `_boundary_h_bm` on a 1×1 at `(0, 1)`: yields bits for `horizontal_fences[0][1]` and `horizontal_fences[1][1]` only. |
| 3 | `_boundary_v_bm` on a 1×1 at `(0, 1)`: yields bits for `vertical_fences[0][1]` and `vertical_fences[0][2]` only. |
| 4 | `_adjacency_bm` on a 1×1 at `(1, 2)`: yields exactly the four orthogonal neighbors. Corner cells yield only their in-grid neighbors (2 for corners, 3 for edge cells). |
| 5 | `_boundary_h_bm` + `_boundary_v_bm` on a 2×2 at PASTURE-cells: 4 horizontal + 4 vertical = 8 boundary edges, matching the expected bitmaps. |
| 6 | `_boundary_h_bm` + `_boundary_v_bm` on the full 3×4 PASTURE: all perimeter edges; no internal edges. |
| 7 | `_boundary_h_bm` + `_boundary_v_bm` on a narrow 1×3 horizontal strip in row 1: 6 horizontal + 4 vertical = 10. |
| 8 | `UNIVERSE_*_ENTRIES` is parallel to `UNIVERSE_*`: same length, same order, `e.cells_bm == bm` for each pair. |
| 9 | `ENTRIES_BY_BM[bm].cells_bm == bm` for every `bm` in `UNIVERSE_FULL`. |
| 10 | `ENTRIES_BY_BM` is a superset (by key) of every other `UNIVERSE_*_SET`. |
| 11 | `pack_fences_h` + `apply_fence_edges_h` round-trip on a representative fence array. |
| 12 | `pack_fences_v` + `apply_fence_edges_v` round-trip on a representative fence array. |
| 13 | `apply_fence_edges_h` is purely additive: starting from a fence array, `apply_fence_edges_h(arr, new_bm)` yields an array equal to the union of `arr` and `new_bm`'s bits. |
| 14 | **Size pins updated for the 1×1-at-(0, 0) addition:** `len(UNIVERSE_RESTRICTED) == 109` (was 108), `len(UNIVERSE_EXTENDED) == 193` (was 192). `UNIVERSE_FAMILY` and `UNIVERSE_FULL` sizes unchanged. The existing 4 pinned-size tests in `tests/test_fences.py` (from TASK_6_pre Part 9) are updated to the new values. |
| 15 | **1×1 at (0, 0) is present in every universe:** `_bm({(0, 0)}) in UNIVERSE_RESTRICTED_SET`, in `_SET`s for EXTENDED, FAMILY, FULL. |
| 16 | **Containment chain still holds after the addition:** `UNIVERSE_RESTRICTED_SET ⊆ UNIVERSE_EXTENDED_SET ⊆ UNIVERSE_FAMILY_SET ⊆ UNIVERSE_FULL_SET`. (The existing containment-chain test from TASK_6_pre keeps passing — the addition lands in all four.) |
| 17 | **`UNIVERSE_*_SMALLEST_ENTRIES` correctness:** for each of FULL / FAMILY / EXTENDED / RESTRICTED, every entry in `UNIVERSE_X_SMALLEST_ENTRIES` has `cells_bm.bit_count() == 1`, every entry's `cells_bm` is in `UNIVERSE_X_SET`, and the SMALLEST tuple length equals the count of popcount-1 entries in `UNIVERSE_X_ENTRIES`. After the (0, 0) addition, RESTRICTED's smallest count should match the count of 1×1 entries on `ENCLOSABLE_CELLS` (13). |

---

# Part 9 — Documentation updates

## CLAUDE.md

- **Status table:** add four rows.
  - "Fencing non-atomic resolution (Build Fences sub-action + Fencing entry point)" → Complete → TASK_6.md.
  - "Farm Redevelopment non-atomic resolution (renovate-then-optional-Build-Fences)" → Complete → TASK_6.md.
  - "Edge metadata on `agricola/fences.py` (`PastureCandidate`, parallel `*_ENTRIES`, `ENTRIES_BY_BM`)" → Complete → TASK_6.md.
  - "Sub-action cost handling: 4th bucket (pure-function-of-state-and-commit)" → Documented → TASK_6.md.
- **"Not yet implemented" section:** drop `fencing` *and* `farm_redevelopment`. Every action space in `legal_placements`'s output now has a working resolution path. The remaining engine-level gaps are harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED), rounds 5–14, and cards-other-than-Potter-Ceramics.
- **`agricola/fences.py` description:** add the edge-bitmap conventions, `PastureCandidate`, `_boundary_h_bm` / `_boundary_v_bm` / `_adjacency_bm`, parallel `UNIVERSE_*_ENTRIES`, four `UNIVERSE_*_SMALLEST_ENTRIES` fast-path tuples, `ENTRIES_BY_BM`, `pack_fences_h` / `pack_fences_v` / `apply_fence_edges_h` / `apply_fence_edges_v`, `compute_new_fence_edges`. Note the 1×1-at-(0, 0) addition to RESTRICTED + EXTENDED (Part 1.8) and the new sizes (RESTRICTED=109, EXTENDED=193).
- **`agricola/pending.py` description:** add `PendingFencing`, `PendingBuildFences`, and `PendingFarmRedevelopment` entries. Include the parent-vs-sub-action distinction, the counter semantics on `PendingBuildFences` (`pastures_built`, `fences_built`), the `subdivision_started` flag implementing the builds-before-subdivisions ordering rule (cross-reference Part 2.3), and the renovate-then-optional-build-fences structure of `PendingFarmRedevelopment` mirroring `PendingHouseRedevelopment` (TASK_5C §2 / §3.6).
- **`agricola/legality.py` description:** add `ACTIVE_FENCE_UNIVERSE_ENTRIES` / `ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES` / `ACTIVE_FENCE_UNIVERSE_SET` (three constants that must stay in sync), `_can_fence`, `_any_legal_pasture_commit` (with a precomputed 1×1 fast-path tuple), `_is_legal_for_can_fence`, `_can_farm_redevelopment`, `_enumerate_pending_fencing`, `_enumerate_pending_build_fences`, `_enumerate_pending_farm_redevelopment`, and the helpers `_enclosable_cells_bm` / `_cells_bm_of_pasture`. Note the universe-swap mechanisms (module constants + per-call kwargs). `compute_new_fence_edges` lives in `fences.py` (not legality.py) since it's a pure utility over `Farmyard` and bitmap operations.
- **`agricola/resolution.py` description:** add `_initiate_fencing`, `_choose_subaction_fencing`, `_execute_build_pasture`, `_initiate_farm_redevelopment`, `_choose_subaction_farm_redevelopment`. Note that Farm Redevelopment introduces *no new effect functions* — both its branches reuse existing effects (`_execute_renovate` from TASK_5C, `_execute_build_pasture` from §5.3 of this task). Reframe the pasture-cache-recompute list around effect functions: **two distinct effect functions** recompute pastures — `_execute_build_stable` (used by Side Job's and Farm Expansion's `build_stables` sub-action) and the new `_execute_build_pasture` (used by Fencing's and Farm Redev's `build_fences` sub-action). Four parent-pending entry points; two effect functions. Note that `_execute_build_pasture` is the only one that derives the subdivision/build distinction at execute time (for the ordering-rule flag).
- **`Farmyard` description:** update the pasture-cache caller-discipline note — instead of listing four "resolvers," list the two effect functions (`_execute_build_stable` and `_execute_build_pasture`) that construct `Farmyard` with explicit `pastures=compute_pastures_from_arrays(...)`.
- **Sub-action cost handling section (Additional Design Principles):** add a fourth bucket entry:
  > *Bucket 4 — pure-function-of-state-and-commit cost.* Cost is neither caller-parameterizable on the pending (bucket 2) nor a const-table lookup keyed on commit parameters (bucket 3). It is computed at execute time by a shared helper as a deterministic function of `(state, commit_parameters)`. Both the enumerator (for affordability filtering) and the effect function (for the debit) call the same helper. Fencing is the canonical example: cost = 1 wood × popcount(boundary & ~current_fences). The commit object stays the minimal source of truth for *action identity*; the helper stays the single source of truth for the *cost formula*. When cards modify cost later, only the helper changes — commit objects never lie about cost.

## `CHANGES.md`

No entry. This task does not cross-cut the codebase in the sense that warrants a CHANGES.md entry — it is the implementation of one new action space + one new reusable sub-action.

---

# Part 10 — Order of work

1. **Edge metadata in `fences.py`.** Add `PastureCandidate`, the three boundary/adjacency helpers, the four `UNIVERSE_*_ENTRIES` tuples, the four `UNIVERSE_*_SMALLEST_ENTRIES` fast-path tuples, `ENTRIES_BY_BM`, the 1×1-at-(0, 0) addition (Part 1.8), `pack_fences_h/v` + `apply_fence_edges_h/v`, and `compute_new_fence_edges` (Part 1.7). Run new `tests/test_fences.py` cases (Part 8). Land before any pending / commit work.
2. **Pending dataclasses.** Add `PendingFencing`, `PendingBuildFences`, and `PendingFarmRedevelopment` to `pending.py`, update `PendingDecision` union. No tests yet (engine wiring needed).
3. **Commit action.** Add `CommitBuildPasture` to `actions.py`, update `Action` union.
4. **Fencing-side legality.** Add the three active-universe constants, `_can_fence`, `_any_legal_pasture_commit` (with precomputed 1×1 fast-path), `_is_legal_for_can_fence`, `_enumerate_pending_fencing`, `_enumerate_pending_build_fences`, and the helpers `_enclosable_cells_bm` and `_cells_bm_of_pasture`. Import `compute_new_fence_edges` from `fences.py`. Register in `NON_ATOMIC_LEGALITY` and `PENDING_ENUMERATORS`.
5. **Fencing-side resolution.** Add `_initiate_fencing`, `_choose_subaction_fencing`, `_execute_build_pasture`. Register in `NONATOMIC_HANDLERS`, `CHOOSE_SUBACTION_HANDLERS`, and `COMMIT_SUBACTION_HANDLERS` (with `auto_pop=False`).
6. **Engine.** Drop `fencing` *and* `farm_redevelopment` from the `NotImplementedError` branch (eliminating it).
7. **Fencing tests.** Update `tests/test_utils.py` to include `"fencing"` in `IMPLEMENTED_NON_ATOMIC_SPACES`. Add all 19 tests in `tests/test_fencing.py` (Part 7). Write incrementally, running each test as it lands.
8. **Farm Redevelopment legality.** Add `_can_farm_redevelopment` and `_enumerate_pending_farm_redevelopment`. Register in `NON_ATOMIC_LEGALITY` and `PENDING_ENUMERATORS`.
9. **Farm Redevelopment resolution.** Add `_initiate_farm_redevelopment` and `_choose_subaction_farm_redevelopment`. Register in `NONATOMIC_HANDLERS` and `CHOOSE_SUBACTION_HANDLERS`. No new effect functions (both branches reuse `_execute_renovate` from TASK_5C and `_execute_build_pasture` from step 5).
10. **Farm Redevelopment tests.** Add `"farm_redevelopment"` to `IMPLEMENTED_NON_ATOMIC_SPACES`. Add all 11 tests in `tests/test_farm_redevelopment.py` (Part 7B).
11. **CLAUDE.md updates.** Per Part 9.

The total test count should land at the existing 426 + Part 8 additions (~16) + Part 7 (~22 with the 13b/13c/13d additions) + Part 7B (~11) = ~475 tests.

---

# Part 11 — Acceptance criteria

1. All existing tests pass.
2. All new tests pass (Parts 7, 7B, and 8).
3. `step()` no longer raises `NotImplementedError` for `PlaceWorker(space="fencing")` *or* `PlaceWorker(space="farm_redevelopment")`. The `NotImplementedError` branch in `_apply_place_worker` is removed entirely.
4. The random-agent end-to-end smoke (test 19 in Part 7) runs to `BEFORE_SCORING` for at least 10 distinct seeds without errors, with `IMPLEMENTED_NON_ATOMIC_SPACES` including both new spaces.
5. After a fresh import: `legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_RESTRICTED_ENTRIES`, `legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES is UNIVERSE_RESTRICTED_SMALLEST_ENTRIES`, `legality.ACTIVE_FENCE_UNIVERSE_SET is UNIVERSE_RESTRICTED_SET`.
6. Universe swap mechanisms both work: per-call kwarg (test 16) and module constant rebind (test 17).
7. Builds-before-subdivisions ordering rule active: after any subdivision commit, no new-pasture commits appear in `legal_actions` for the remainder of that Build Fences action (tests 13b/13c/13d in Part 7).
8. RESTRICTED size = 109; EXTENDED size = 193. The 1×1 at (0, 0) is in all four universes' `_SET`s.
9. Farm Redevelopment reaches Build Fences cleanly via the renovate-then-build-fences path: inner `PendingBuildFences.initiated_by_id == "farm_redevelopment"` (test 7 in Part 7B) — provenance distinct from the Fencing-space path.
10. CLAUDE.md status table reflects the completed work; the "Not yet implemented" list shrinks to harvest + rounds 5–14 + cards-other-than-Potter-Ceramics (Farm Redevelopment and Fencing both drop off).

---

# Part 12 — Open questions deferred

- **`after_build_fences`, `after_fencing`, and `after_farm_redevelopment` trigger events.** Section 9 of `FENCE_IDEAS.md` flags this as an open problem. The codebase has precedent for `before_X` events; `after_X` requires either a resolve-on-pop hook (proposed and deferred in design conversation), an explicit `ApplyAfterTriggers` action, or overloading `Stop` semantics. Decide when the first `after_*` card lands.
- **Free-fence accounting field on `PendingBuildFences`.** Per the principle of not adding fields purely to anticipate cards. Add when a card needs it.
- **Cost-modifier extension registry.** Bucket 4's helper (`compute_new_fence_edges`) is currently fixed at 1 wood per edge. When the first card modifies per-edge cost (material substitution, free-perimeter, etc.), the helper grows an extension registry (analogous to `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` / `BAKING_SPEC_EXTENSIONS`).
- **Universe-restriction researcher tooling.** The two swap mechanisms ship the *capability* for experiments. The actual research interface — a `restrict_to(predicate)` wrapper around an `_ENTRIES` tuple, or a dedicated experiment-config layer — is downstream of MCTS training and not built here.
- **Canonicalization tiebreaker revisit.** Lex-smallest min-cell is the default for subdivision canonicalization. If self-play training shows the policy struggling in subdivision-heavy positions, revisit the tiebreaker (alternatives: smaller side by cell count, side with more stables, etc.).
