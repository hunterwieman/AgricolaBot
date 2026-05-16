# Task 4a-i — State Additions + Atomic-Space Legality

This task extends the existing state dataclasses with fields needed for action resolution, updates `setup` to initialize them, adds a `PlaceWorker` action type, and implements a legality function that returns all currently-legal atomic placements.

## Scope

**In scope**
- Add missing fields to `GameState`, `BoardState`, `PlayerState`, and `ActionSpaceState`.
- Update `setup` to initialize all new fields.
- Add `PlaceWorker` action type in `agricola/actions.py`.
- Add per-atomic-space legality functions and a top-level `legal_atomic_placements(state)` in `agricola/legality.py`.
- Tests for legality across all atomic spaces and edge cases.

**Out of scope**
- Resolution handlers (Task 4a-ii).
- Non-atomic spaces (Tasks 4b onwards).
- The work-phase loop, prep phase, returning home, harvest.
- `legal_actions` for non-atomic placements or sub-decisions.

---

## First step: audit

Before adding anything, read `agricola/state.py` and `agricola/setup.py`. For each field listed below, check whether it already exists and note its name. Do not duplicate fields that exist; adopt the existing name.

Fields to check:
- Whose turn it is during the work phase → already exists as `GameState.current_player`
- Who holds the starting player token → already exists as `GameState.starting_player`
- Round number → already exists as `GameState.round_number`
- Total family members → already exists as `PlayerState.people_total`
- Workers available to place this round → already exists as `PlayerState.people_home`
- Accumulated goods on a space → already exists as `ActionSpaceState.accumulated_goods` *(subsequently renamed to `accumulated_amount` and `accumulated: Resources` added alongside it — see CLEANUP.md Cleanup 2 and CHANGES.md Change 1)*
- Who occupies a space → currently `ActionSpaceState.occupied_by: Optional[int]` — **replace this** (see below)
- When a space is revealed → already exists as `ActionSpaceState.round_revealed`

---

## State-shape additions

### `ActionSpaceState` — replace `occupied_by` with `workers`

Remove the existing field:
```python
occupied_by: Optional[int]  # None, 0, or 1
```

Replace with:
```python
workers: tuple  # tuple[int, int] — (player_0_count, player_1_count)
```

A length-2 tuple storing how many workers each player has on this space. An empty space has `workers = (0, 0)`. One worker from player 0 is `(1, 0)`. Two workers from player 0 (parent + newborn on a Wish space) is `(2, 0)`. One worker from each player is `(1, 1)`.

Deriving occupancy: `sum(space_state.workers) > 0` means occupied. `space_state.workers[p]` gives player `p`'s worker count directly.

The cross-cutting unoccupied check used in legality is: `state.board.action_spaces[space].workers == (0, 0)`. *(Note: the legality table below incorrectly writes `== ()` — the correct empty value is `(0, 0)`.)*

> **Note (see IMPLEMENTATION_CHOICES.md #1):** This encoding hardcodes 2 players, which matches the rest of the codebase. It may need to be revisited when cards that allow multi-player co-occupancy are introduced, if arrival order or slot identity becomes relevant.

Update `setup` to initialize every action space with `workers=(0, 0)`.

### `PlayerState` — add `newborns`

```python
newborns: int = 0  # workers born this round; used only for harvest feeding cost (1 food vs 2)
```

`newborns` is included in `people_total` immediately when a Wish for Children action is resolved. It is reset to 0 at the end of each harvest. It is never subtracted from `people_total` — it is only a feeding modifier.

Setup initial value: `newborns = 0`.

### `GameState` — add `next_starting_player`

> **Subsequently removed.** This field was added as specified here and then removed as redundant. `starting_player` is only ever read at the start of a round, so updating it immediately when Meeting Place is taken is safe. See CLEANUP.md Cleanup 3.

```python
next_starting_player: int  # 0 or 1 — who becomes starting player at the start of the next round
```

`starting_player` records who holds the token for the *current* round and is used to determine turn order at the start of each round. `next_starting_player` records who will hold it *next* round. It is updated immediately when the Meeting Place action is resolved (the taking player sets `next_starting_player` to themselves). At the start of each new round, `starting_player` is set to `next_starting_player`.

This separation is necessary because Meeting Place can be taken mid-round, before the current round's turn order is complete.

Setup initial value: `next_starting_player = starting_player`.

### `constants.py` additions

Add two convenience sets. These are referenced in setup and in legality logic.

```python
# Spaces that accumulate goods each round (used in setup and prep phase logic):
ACCUMULATION_SPACES = frozenset(ACCUMULATION_RATES.keys())

# Permanent spaces (always available from round 1, round_revealed == 0):
# Note: "lessons" exists on the board but is never legal in the Family game.
PERMANENT_ACTION_SPACES_SET = frozenset(PERMANENT_ACTION_SPACES)
```

`ACCUMULATION_SPACES` is derived directly from the existing `ACCUMULATION_RATES` dict so there is no duplication. *(Note: `ACCUMULATION_RATES` was subsequently split into `BUILDING_ACCUMULATION_RATES` and `FOOD_ANIMAL_ACCUMULATION_RATES`; `ACCUMULATION_SPACES` is derived as the union of both. See CHANGES.md Change 1.)*

---

## Action type

Add `agricola/actions.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaceWorker:
    """Place the active player's worker on an action space.

    For atomic spaces this is the entire action.
    For non-atomic spaces this initiates a chain of pending sub-decisions
    (added in later tasks).
    """
    space: str  # action space ID string, e.g. "forest"


# Action union will grow in later tasks. For now:
Action = PlaceWorker
```

---

## Legality

Add `agricola/legality.py`:

### Cross-cutting preconditions

Every atomic-space predicate checks two conditions:
1. The space is unoccupied: `state.board.action_spaces[space].workers == ()` *(typo — should be `(0, 0)`)*
2. The space is currently revealed: `state.board.action_spaces[space].round_revealed <= state.round_number`

Condition 2 handles stage cards automatically — if the space's `round_revealed` is greater than the current round, the cross-cutting check fails and no per-space logic is needed.

### Per-space legality

Throughout, `ap = state.current_player` and `p = state.players[ap]`.

`num_rooms(p)` counts cells in `p.farmyard.grid` where `cell_type == CellType.ROOM`. Derive locally — do not add it as a stored field.

| Space | Additional preconditions beyond cross-cutting |
|---|---|
| `"day_laborer"` | (none) |
| `"fishing"` | `state.board.action_spaces["fishing"].accumulated_amount > 0` *(field renamed from `accumulated_goods` — see CLEANUP.md Cleanup 2)* |
| `"forest"` | `bool(state.board.action_spaces["forest"].accumulated)` *(field changed from `accumulated_goods: int` to `accumulated: Resources` — see CHANGES.md Change 1)* |
| `"clay_pit"` | `bool(state.board.action_spaces["clay_pit"].accumulated)` *(same)* |
| `"reed_bank"` | `bool(state.board.action_spaces["reed_bank"].accumulated)` *(same)* |
| `"grain_seeds"` | (none) |
| `"meeting_place"` | (none — legal even when accumulation is 0, because taking SP token is itself an effect) |
| `"western_quarry"` | `bool(state.board.action_spaces["western_quarry"].accumulated)` *(field changed from `accumulated_goods: int` to `accumulated: Resources` — see CHANGES.md Change 1)* |
| `"vegetable_seeds"` | (none) |
| `"eastern_quarry"` | `bool(state.board.action_spaces["eastern_quarry"].accumulated)` *(same)* |
| `"basic_wish_for_children"` | `p.people_total < 5` and `p.people_total < num_rooms(p)` |
| `"urgent_wish_for_children"` | `p.people_total < 5` |

### Implementation pattern

```python
def legal_atomic_placements(state: GameState) -> list[PlaceWorker]:
    """Return all legal PlaceWorker actions for atomic spaces.

    Returns an empty list if the active player has no workers to place.
    Does not include non-atomic spaces (farm_expansion, farmland, etc.) —
    those are added in later tasks.
    """
    if state.players[state.current_player].people_home < 1:
        return []
    return [
        PlaceWorker(space=s)
        for s, predicate in ATOMIC_LEGALITY.items()
        if predicate(state)
    ]
```

`ATOMIC_LEGALITY` is a dict mapping each atomic space ID string to a per-space predicate function. The cross-cutting checks (unoccupied, revealed) are factored into a shared helper called by each predicate, not repeated inline.

### Atomic spaces in scope for this task

The atomic spaces — those where placing a worker is the entire action, with no sub-decisions — are:

`"day_laborer"`, `"fishing"`, `"forest"`, `"clay_pit"`, `"reed_bank"`, `"grain_seeds"`, `"meeting_place"`, `"western_quarry"`, `"vegetable_seeds"`, `"eastern_quarry"`, `"basic_wish_for_children"`, `"urgent_wish_for_children"`

The following spaces are **non-atomic** and are excluded from `legal_atomic_placements` (handled in later tasks):
`"farm_expansion"`, `"farmland"`, `"fencing"`, `"side_job"`, `"major_improvement"`, `"house_redevelopment"`, `"grain_utilization"`, `"sheep_market"`, `"pig_market"`, `"cattle_market"`, `"cultivation"`, `"farm_redevelopment"`, `"lessons"`

---

## Tests

Add `tests/test_legality_atomic.py`. Pattern: construct a state via `setup(seed=0)` plus `dataclasses.replace`, call `legal_atomic_placements`, assert the returned list.

All expected values must be derived by hand from the rules. Do not derive expected values by running `legal_atomic_placements` itself.

### Per-space legal-when-conditions-met
- `test_day_laborer_legal_at_setup`
- `test_fishing_legal_with_accumulation`
- `test_forest_legal_with_accumulation`
- `test_clay_pit_legal_with_accumulation`
- `test_reed_bank_legal_with_accumulation`
- `test_grain_seeds_legal_at_setup`
- `test_meeting_place_legal_at_setup`
- `test_meeting_place_legal_with_zero_accumulation` — explicitly verify that zero accumulated food does not block this space
- `test_western_quarry_legal_when_revealed_with_accumulation` — manually set `revealed` and `accumulated_goods` via `dataclasses.replace`
- `test_vegetable_seeds_legal_when_revealed`
- `test_eastern_quarry_legal_when_revealed_with_accumulation`
- `test_basic_wish_legal_when_revealed_with_room` — player has more rooms than people
- `test_urgent_wish_legal_when_revealed`

### Per-space illegal-when-conditions-fail
- `test_fishing_illegal_with_zero_accumulation`
- `test_forest_illegal_with_zero_accumulation`
- `test_clay_pit_illegal_with_zero_accumulation`
- `test_reed_bank_illegal_with_zero_accumulation`
- `test_western_quarry_illegal_with_zero_accumulation`
- `test_eastern_quarry_illegal_with_zero_accumulation`
- `test_basic_wish_illegal_at_max_family` — `people_total == 5`
- `test_basic_wish_illegal_without_room` — `people_total == num_rooms(p)` (no spare room)
- `test_urgent_wish_illegal_at_max_family` — `people_total == 5`

### Cross-cutting
- `test_occupied_space_illegal` — manually set `workers = (1, 0)` on Day Laborer; verify it is absent from results
- `test_unrevealed_stage_space_illegal` — at setup (round 1), `"western_quarry"` has `round_revealed > 1`; verify it is absent from results even when `accumulated_goods > 0`
- `test_no_workers_returns_empty` — set `people_home = 0` on the active player via `dataclasses.replace`; verify result is `[]`
- `test_setup_legal_set` — at fresh setup, the legal atomic placements are exactly `{"day_laborer", "grain_seeds", "meeting_place", "forest", "clay_pit", "reed_bank", "fishing"}`. Reasoning: `setup` pre-loads round-1 accumulation onto all accumulation spaces (forest gets 3 wood, clay_pit 1 clay, reed_bank 1 reed, fishing 1 food), so those spaces are immediately legal. Day Laborer, Grain Seeds, and Meeting Place have no accumulation precondition. All other stage-0 spaces (Farm Expansion, Farmland, Side Job) are non-atomic and excluded from this function. Do not derive the expected set by running the function — verify it against `setup.py` directly.

### Per-player current_player handling
- `test_current_player_determines_legality` — set `current_player = 1`, give player 1 `people_total == num_rooms` (blocking Basic Wish) but player 0 has a spare room; verify Basic Wish is absent from results (we are checking player 1's legality). Requires Basic Wish to be revealed via `dataclasses.replace`.

---

## Acceptance criteria

- All listed tests pass.
- All existing 53 tests still pass.
- No fields duplicated; existing fields are reused under their existing names.
- `ActionSpaceState.occupied_by` is replaced by `workers: tuple`; all existing references updated.
- Setup correctly initializes all new fields.
- Audit findings noted in commit message before new code is written.
