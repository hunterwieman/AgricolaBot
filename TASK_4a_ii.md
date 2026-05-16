# Task 4a-ii — Atomic-Space Resolution

This task implements resolution of `PlaceWorker` actions on atomic action spaces — those where placing a worker is the entire action, with no sub-decisions. After this task, applying a legal `PlaceWorker` to one of the 12 atomic spaces produces the correct resulting `GameState`.

## Scope

**In scope**
- A `resolve_atomic(state, action)` function in `agricola/resolution.py`.
- Per-space resolution logic for all 12 atomic spaces.
- A shared cross-cutting helper that handles worker placement bookkeeping (worker count on the space, decrementing `people_home`).
- Tests for each handler in isolation.

**Out of scope** (deferred to later tasks)
- Advancing `current_player` after a placement.
- Advancing `phase` when both players are out of workers.
- Returning home, prep phase, harvest, end-of-round logic.
- Resolution for non-atomic spaces (markets, Farmland, Major Improvement, etc.).
- Sub-decision actions (Plow, Sow, BuildStable, etc.).

A successful 4a-ii produces correct single-placement state transitions. The game does not yet *play* — there is no loop yet that alternates players or moves to the next round. That comes in the work-phase-loop task.

## Atomic spaces (same set as 4a-i)

```
"day_laborer", "fishing", "forest", "clay_pit", "reed_bank", "grain_seeds",
"meeting_place", "western_quarry", "vegetable_seeds", "eastern_quarry",
"basic_wish_for_children", "urgent_wish_for_children"
```

The non-atomic spaces and `"lessons"` are excluded — `resolve_atomic` should never be called with these.

## Audit step

Before writing any resolution code, read the current `agricola/state.py` and the 4a-i changes. Verify the following field names:
- `ActionSpaceState.workers` — `tuple[int, int]`, `(0, 0)` when empty
- `ActionSpaceState.accumulated_goods` — `int` *(subsequently renamed to `accumulated_amount` for food/animal spaces, and `accumulated: Resources` added for building-resource spaces — see CLEANUP.md Cleanup 2 and CHANGES.md Change 1)*
- `PlayerState.people_home` — `int`
- `PlayerState.newborns` — `int`
- `GameState.current_player` — `int`
- `GameState.next_starting_player` — `int` *(subsequently removed; Meeting Place resolution now sets `starting_player` directly — see CLEANUP.md Cleanup 3)*

If anything has drifted, follow the existing names.

## Resolution function

Add `agricola/resolution.py` with a top-level entry point:

```python
def resolve_atomic(state: GameState, action: PlaceWorker) -> GameState:
    """Apply an atomic-space worker placement and return the resulting state.

    Preconditions (caller's responsibility — `legal_atomic_placements` checks
    these; this function does not re-check them):
      - action.space is one of the 12 atomic spaces
      - The space is unoccupied: state.board.action_spaces[action.space].workers == (0, 0)
      - The space is revealed: round_revealed <= state.round_number
      - state.players[state.current_player].people_home >= 1
      - Per-space preconditions (room available for Basic Wish, etc.)

    Postconditions:
      - The action space's `workers` tuple reflects the new placement.
      - The active player's `people_home` is decremented by 1.
      - The space's effect is applied to the active player's resources/state
        and/or the board.
      - For accumulation spaces, `accumulated_goods` is reset to 0.
      - `current_player`, `phase`, and `round_number` are NOT advanced.
    """
```

Use a dispatch table from action-space ID strings to per-space handler functions,
mirroring the 4a-i legality pattern:

```python
def resolve_atomic(state: GameState, action: PlaceWorker) -> GameState:
    state = _apply_worker_placement(state, action.space)  # cross-cutting bookkeeping
    handler = ATOMIC_HANDLERS[action.space]
    return handler(state)

ATOMIC_HANDLERS: dict[str, Callable[[GameState], GameState]] = {
    "day_laborer":              _resolve_day_laborer,
    "fishing":                  _resolve_fishing,
    # ...
}
```

Each handler receives the state *after* `_apply_worker_placement` and returns the
state *after* the space's specific effect. Handlers do not repeat the
worker/people_home bookkeeping.

## Cross-cutting placement bookkeeping

`_apply_worker_placement(state: GameState, space_id: str) -> GameState` updates
two things and returns a new state:

1. **Action space workers:** increment `workers[current_player]` by 1. Because
   `ActionSpaceState` is a frozen dataclass and `workers` is a tuple, use
   `dataclasses.replace` to build a new `ActionSpaceState` with an updated
   workers tuple. Build the new tuple explicitly:
   ```python
   ap = state.current_player
   old_w = space_state.workers
   new_workers = (old_w[0] + (1 if ap == 0 else 0),
                  old_w[1] + (1 if ap == 1 else 0))
   ```
   Then propagate the change up through `dataclasses.replace` on the
   `ActionSpaceState`, the `action_spaces` dict, `BoardState`, and `GameState`
   in turn — the same pattern used throughout the test helpers.

2. **Active player `people_home`:** decrement by 1 via `dataclasses.replace` on
   `PlayerState`, then propagate up through the players tuple and `GameState`.

This helper handles exactly one worker. The Wish handlers add a second worker
themselves — they do not call this helper twice.

The helper does not touch `current_player`, `phase`, `next_starting_player`, or
`round_number`.

## Per-space resolution

Throughout: `ap = state.current_player`, `p = state.players[ap]`,
`space_state = state.board.action_spaces[space_id]`.

| Space | Effect |
|---|---|
| `"day_laborer"` | `p.resources.food += 2` |
| `"fishing"` | `p.resources + Resources(food=space_state.accumulated_amount)`; reset `accumulated_amount` to 0 *(field renamed from `accumulated_goods` — see CLEANUP.md Cleanup 2)* |
| `"forest"` | `p.resources + space_state.accumulated`; reset `accumulated` to `Resources()` *(field changed from `accumulated_goods: int` — see CHANGES.md Change 1)* |
| `"clay_pit"` | same pattern as `forest` |
| `"reed_bank"` | same pattern as `forest` |
| `"grain_seeds"` | `p.resources + Resources(grain=1)` |
| `"meeting_place"` | `p.resources + Resources(food=space_state.accumulated_amount)`; reset. Set `state.starting_player = ap` directly *(`next_starting_player` was removed — see CLEANUP.md Cleanup 3)* |
| `"western_quarry"` | same pattern as `forest` |
| `"vegetable_seeds"` | `p.resources + Resources(veg=1)` |
| `"eastern_quarry"` | same pattern as `forest` |
| `"basic_wish_for_children"` | Family Growth (see below) |
| `"urgent_wish_for_children"` | Family Growth (see below) |

### Accumulation space resource lookup

For the 8 accumulation spaces (fishing, forest, clay_pit, reed_bank,
meeting_place, western_quarry, eastern_quarry, pig_market/sheep_market/cattle
in later tasks), use `ACCUMULATION_RATES[space_id][0]` to determine which
resource field to credit. Do not hardcode "Forest credits wood" per handler.

Pattern for accumulation handlers:
```python
resource_field, _ = ACCUMULATION_RATES[space_id]
amount = space_state.accumulated_goods
new_resources = dataclasses.replace(
    p.resources,
    **{resource_field: getattr(p.resources, resource_field) + amount}
)
new_space = dataclasses.replace(space_state, accumulated_goods=0)
```

This keeps `ACCUMULATION_RATES` as the single source of truth for which
resource each space produces.

> **Subsequently replaced.** The `getattr`/`**kwargs` pattern above was removed in CHANGES.md Change 1. Building-resource spaces now use `p.resources + space_state.accumulated` (with `Resources.__add__`) and reset to `accumulated=Resources()`. Food/animal spaces use `p.resources + Resources(food=space_state.accumulated_amount)` and reset `accumulated_amount` to 0. `ACCUMULATION_RATES` is no longer imported in `resolution.py`.

> **Ex post note (session 3):** A subsequent design discussion concluded that
> `accumulated_goods: int` on building-resource spaces should be replaced with
> `accumulated: Resources` to support cards like the Geologist that modify what
> a space accumulates. Under the new design, `ACCUMULATION_RATES` values become
> `Resources` objects and `_resolve_accumulation` becomes `p.resources +
> space_state.accumulated` with a reset to `Resources()`. The `getattr`/`**kwargs`
> pattern is eliminated entirely. The food/animal accumulation spaces (`fishing`,
> `meeting_place`, `sheep_market`, etc.) keep a scalar `accumulated_goods: int`
> field — they are a different concept and are never modified by cards this way.
> See `CHANGES.md` Change 1 for the full implementation plan.

### Family Growth (Wish handlers)

Both Wish handlers (`"basic_wish_for_children"` and `"urgent_wish_for_children"`)
do the same thing. After `_apply_worker_placement` has already placed the parent
(workers[ap] is now 1):

1. Increment `workers[ap]` to 2 (newborn placed alongside parent on the space).
2. `p.people_total += 1`.
3. `p.newborns += 1`.

`people_home` is NOT incremented for the newborn — the newborn is placed on the
action space, not at home. At end of round, when all workers return home, the
newborn joins them and becomes an adult; that increment is handled in the
work-phase-loop task.

The Basic vs Urgent distinction is purely a legality concern (room requirement),
already handled in 4a-i. Resolution is identical for both.

## Tests

Add `tests/test_resolution_atomic.py`. Pattern: construct a state where the
target space is legal (via `setup(seed=0)` plus `dataclasses.replace` as
needed), call `resolve_atomic`, assert the resulting state.

Expected post-states must be derived by hand from the rules. Do not run
`resolve_atomic` to generate expected values for its own tests.

### Per-space happy-path tests

One test per space, verifying the full effect including that no unintended
resources changed:

- `test_day_laborer_resolution`: food up by 2; all other resources unchanged.
- `test_fishing_resolution`: food up by the pre-placement `accumulated_goods`;
  `accumulated_goods` is 0 after; no other resource changes.
- `test_forest_resolution`: wood up by accumulated; reset; no other changes.
- `test_clay_pit_resolution`: clay up by accumulated; reset.
- `test_reed_bank_resolution`: reed up by accumulated; reset.
- `test_grain_seeds_resolution`: grain up by 1; no other changes.
- `test_meeting_place_resolution`: food up by accumulated; reset;
  `starting_player == ap`. *(`next_starting_player` was removed; assert on `starting_player` directly — see CLEANUP.md Cleanup 3.)*
- `test_western_quarry_resolution`: stone up by accumulated; reset.
  Reveal the space first via `dataclasses.replace`.
- `test_vegetable_seeds_resolution`: veg up by 1. Reveal the space first.
- `test_eastern_quarry_resolution`: stone up by accumulated; reset. Reveal first.
- `test_basic_wish_resolution`: `people_total` up by 1; `newborns` up by 1;
  `workers[ap] == 2`; `people_home` down by exactly 1 (not 2). Add a spare
  room via `dataclasses.replace` so the space is legal. Reveal first.
- `test_urgent_wish_resolution`: same assertions as Basic Wish. Reveal first.

### Cross-cutting invariants

Use Day Laborer as the representative space for all of these (it is always legal
at setup and has a simple, unambiguous effect):

- `test_resolution_marks_space_occupied`: after resolution, `workers[ap] == 1`
  on Day Laborer.
- `test_resolution_decrements_people_home`: `people_home` is exactly
  `pre_home - 1` after any atomic placement.
- `test_resolution_doesnt_advance_current_player`: `current_player` is unchanged.
- `test_resolution_doesnt_advance_phase`: `phase` is unchanged.
- `test_resolution_other_player_unchanged`: `state.players[1 - ap]` is identical
  before and after (compare with `==`).
- `test_resolution_other_spaces_unchanged`: iterate over all action spaces;
  for every space other than the target, assert that `workers` and
  `accumulated_goods` are the same before and after. (Programmatic loop over
  `state.board.action_spaces`, not spot-checks.)

### Edge cases

- `test_meeting_place_zero_accumulation`: set `accumulated_amount` to 0 on
  Meeting Place before placement *(field renamed from `accumulated_goods` — see CLEANUP.md Cleanup 2)*; food is unchanged; `starting_player`
  still updates to `ap` *(`next_starting_player` removed — see CLEANUP.md Cleanup 3)*.
- `test_accumulation_zero_after_take`: after resolution of any accumulation
  space, `accumulated == Resources()` for building-resource spaces or `accumulated_amount == 0` for food/animal spaces *(field renamed/restructured — see CLEANUP.md Cleanup 2 and CHANGES.md Change 1)*. Test with Forest (always legal at setup).
- `test_resolution_returns_new_state`: call `resolve_atomic`, then assert
  `state.players[ap].resources is not new_state.players[ap].resources`. This
  verifies the function is pure and returns new objects rather than mutating
  the input. Use Day Laborer (effect changes resources, so the object is
  guaranteed to be rebuilt).

### Wish-specific

- `test_basic_wish_workers_are_two`: after resolution, `workers[ap] == 2`.
- `test_basic_wish_other_player_workers_zero`: `workers[1 - ap] == 0`.
- `test_wish_increments_newborns`: `newborns == 1` after resolution (not 0,
  not 2).

## Acceptance criteria

- All listed tests pass.
- All existing 80 tests still pass.
- `resolve_atomic` is a pure function: returns a new `GameState`; does not
  mutate input.
- `resolve_atomic` does not advance `current_player`, `phase`, or
  `round_number`.
- The dispatch table `ATOMIC_HANDLERS` contains exactly the 12 atomic space
  IDs — no more, no less.
- Accumulation handlers use `ACCUMULATION_RATES` for resource-type lookup;
  no hardcoded "Forest → wood" mappings in handler bodies.
- Audit findings (if any drift from 4a-i assumptions) noted in commit message
  before new code is written.

## Open issues to flag in `IMPLEMENTATION_CHOICES.md`

- `_apply_worker_placement` is currently private to `resolution.py`. Non-atomic
  resolution handlers (Task 4b onwards) will likely need the same bookkeeping.
  Decide at 4b design time whether to make it a shared utility in `helpers.py`
  or keep it private and duplicate/delegate. Do not move it prematurely.
- Accumulation-space handlers use `getattr`/`**kwargs` unpacking with
  `dataclasses.replace` to look up the resource field dynamically. This is
  slightly less readable than `resources.wood` but avoids drift. If this pattern
  feels wrong when reading the code, it can be replaced with a small explicit
  mapping dict (`{"wood": lambda r, n: dataclasses.replace(r, wood=n), ...}`)
  which is equally safe and more explicit.

  > **Ex post note (session 3):** The planned `accumulated: Resources` refactor
  > (see `CHANGES.md` Change 1) replaces this pattern entirely. Once implemented,
  > `_resolve_accumulation` uses `Resources.__add__` and this open issue is closed.
