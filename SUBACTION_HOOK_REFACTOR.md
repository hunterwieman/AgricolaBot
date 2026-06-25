# SUBACTION_HOOK_REFACTOR.md

**Status: design doc for a NOT-YET-STARTED refactor. Python-side spec is below; the
implementing session is expected to discover the full blast radius from the method
in §7 and re-green every gate (including the C++ differential).**

Companion reading before you start: `CARD_IMPLEMENTATION_PLAN.md` §II.1–II.2 (the
firing model + the action-space hook), and the two precedents this refactor
generalizes — the **animal markets** (commit `feat(cards): non-auto-pop animal
markets…`) and the **multi-sub after-trigger** model (commit `feat(cards):
multi-sub action-space after-triggers…`). This refactor applies the *markets*
pattern to the remaining commit-terminated sub-actions.

---

## 1. Goal

Make **every commit-terminated sub-action a uniform before/after host**, like
`PendingActionSpace` and the animal-market frames: it does **not** auto-pop on
commit, it carries a `phase` ("before"|"after") and a `triggers_resolved` set, and
its lifecycle is

```
push (phase="before")
  → fire before_<id> automatic effects + surface before_<id> triggers
  → CommitX: apply the effect, flip phase="after"   (NO auto-pop)
  → surface after_<id> triggers
  → Stop: fire after_<id> automatic effects, then pop
```

This is the end-state that lets *any* sub-action host before- and after-triggers
the same way an action space does — which the card system needs broadly, and which
the auto-pop sub-actions currently make impossible (a card's after-trigger has no
frame to be surfaced on once the commit has popped).

The immediate consumers are **Category 5** cards that hook sub-action events:
- **after-trigger grants** (need a frame to surface on): **Mining Hammer**
  (`after_renovate`, grant a free stable), **Bread Paddle** (`after_play_occupation`,
  grant a bake).
- **after-auto effects** (do *not* strictly need this refactor — see §6): Dutch
  Windmill (`after_bake_bread`), Roughcaster / Junk Room (`after_build_*`), Wall
  Builder (`after_build_room`, Cat 8).

We are doing the **full uniform refactor** (not just the two grant cards) so the
sub-action layer has one shape, per the maintainer's decision: consistency over
minimizing the Family-trace delta.

---

## 2. Scope — exactly which frames change

**In scope** — the sub-action frames that **auto-pop today** (`auto_pop=True` in
`COMMIT_SUBACTION_HANDLERS`, plus `PendingBuildMajor` whose effect pops):

| Frame | Commit | today |
|---|---|---|
| `PendingSow` | `CommitSow` | auto_pop=True |
| `PendingBakeBread` | `CommitBake` | auto_pop=True (already has `triggers_resolved`, before_bake_bread / Potter) |
| `PendingPlow` | `CommitPlow` | auto_pop=True |
| `PendingRenovate` | `CommitRenovate` | auto_pop=True |
| `PendingFamilyGrowth` | `CommitFamilyGrowth` | auto_pop=True |
| `PendingPlayOccupation` | `CommitPlayOccupation` | auto_pop=True |
| `PendingPlayMinor` | `CommitPlayMinor` | auto_pop=True |
| `PendingBuildMajor` | `CommitBuildMajor` | auto_pop=False; effect pops OR pushes an oven (**special — §5**) |

**Out of scope — already non-auto-pop, leave as-is:**
- The **multi-shot** builders `PendingBuildStables` / `PendingBuildRooms` /
  `PendingBuildFences`. These are *Stop-terminated* (build-loop, then `Stop`), so
  they already have the right termination. If/when a card hooks their after-event,
  use the **derived `after_started`** approach (the multi-sub-space pattern:
  `legality._after_action_space_fired` analog) — **no** `phase` field. Not needed
  by any in-scope card; defer.
- The **harvest** frames `PendingHarvestFeed` / `PendingHarvestBreed` (their
  commits are already `auto_pop=False`). No card hooks them; leave alone.
- The **animal markets** and `PendingActionSpace` — already done.

> Why the split: a frame's terminator dictates its mechanism. **Commit-terminated**
> frames (one mandatory commit, then nothing) need an explicit `phase` flip to have
> an "after" to surface on — they can't derive "committed" from any existing field.
> **Stop-terminated** frames already persist until `Stop`, so they surface
> after-triggers at the Stop-gate and derive `after_started` from
> `triggers_resolved` (no field). This refactor is only about the commit-terminated
> set.

---

## 3. Per-frame changes (Python)

For each in-scope frame (`pending.py`):
- **Add** `phase: str = "before"`.
- **Ensure** `triggers_resolved: frozenset = frozenset()` is present (Sow, Plow
  already lack it? check each — `PendingSow`, `PendingFamilyGrowth`,
  `PendingPlayOccupation`, `PendingPlayMinor` need it added; `PendingBakeBread`,
  `PendingPlow`, `PendingRenovate`, `PendingBuildMajor` already have it).
- **Keep** all sub-action-specific fields unchanged (e.g. `PendingPlayOccupation.cost`,
  `PendingPlayMinor` has none, `PendingBuildMajor`'s — none beyond triggers).
- **Drop** the per-frame `TRIGGER_EVENT` ClassVar where present (the event is
  derived — see §4); confirm nothing still reads it (`_enumerate_pending_bake_bread`
  reads `type(pending).TRIGGER_EVENT` today — migrate it to the derived form).
- These frames are **NOT** action-space hosts, so do **NOT** add their `PENDING_ID`
  to `ACTION_SPACE_PENDING_IDS` (that bucket is for the coarse `action_space` event;
  sub-actions route to `before_/after_<PENDING_ID>` — e.g. `before_bake_bread`,
  `after_renovate`).

`PENDING_ID`s are already the sub-action ids: `sow`, `bake_bread`, `plow`,
`renovate`, `family_growth`, `play_occupation`, `play_minor`, `build_major`. The
derived events are `before_/after_<that>`.

---

## 4. Engine / dispatch changes

**(a) `COMMIT_SUBACTION_HANDLERS` (engine.py).** The in-scope commits stop
auto-popping. The clean shape (mirror `_execute_accommodate`): set `auto_pop=False`
and have each `_execute_<x>` end by flipping its own frame to `phase="after"`
instead of popping:

```python
state = _update_player(...)          # or whatever the effect does
# pivot to after-phase; do NOT pop. The trailing Stop pops (engine._apply_stop).
return replace_top(state, fast_replace(state.pending_stack[-1], phase="after"))
```

(Alternatively, give the dispatcher a `flip_after` flag that performs the flip
generically for the single-commit effects, and let the push-cases — §5 — manage
their own. Pick whichever reads cleaner; `_execute_accommodate` is the worked
reference for the explicit-in-the-effect style.)

**(b) Enumerators (legality.py), one per in-scope frame.** Generalize from the
single-`Stop`/single-commit shape to:

```python
def _enumerate_pending_<x>(state, pending):
    if pending.phase == "before":
        actions = _eligible_fire_triggers(state, pending, f"before_{PENDING_ID}")
        actions += [the CommitX option(s)]          # exactly today's commit options
        return actions
    # after-phase
    actions = _eligible_fire_triggers(state, pending, f"after_{PENDING_ID}")
    actions.append(Stop())
    return actions
```

- `_eligible_fire_triggers` already exists (it ownership-checks + filters
  `triggers_resolved`). The `before_` lookup preserves Potter on `before_bake_bread`
  (migrate `_enumerate_pending_bake_bread`'s `TRIGGER_EVENT` read to this).
- The commit option(s) in the before-phase are *exactly* what the enumerator emits
  today (e.g. `_enumerate_pending_bake_bread`'s `CommitBake(grain=n)` list,
  `_enumerate_pending_plow`'s per-cell `CommitPlow`, etc.).
- With no eligible trigger, before-phase = `[CommitX…]` and after-phase = `[Stop]`,
  both auto-skipped-as-singleton where they're singletons (so the common path is
  "agent picks the commit, then the Stop is auto-applied").

**(c) `_apply_stop` (engine.py) — fire after-auto for sub-action frames too.**
Today it fires `after_action_space` when `PENDING_ID in ACTION_SPACE_PENDING_IDS`.
Extend it to also fire `after_<PENDING_ID>` when the popped frame is an in-scope
sub-action host (i.e. it carries `phase` and is in its after-phase). Suggested:

```python
top = state.pending_stack[-1]
pid = type(top).PENDING_ID
if pid in ACTION_SPACE_PENDING_IDS:
    state = apply_auto_effects(state, "after_action_space", top.player_idx)
elif getattr(top, "phase", None) == "after":   # a refactored sub-action at its Stop
    state = apply_auto_effects(state, f"after_{pid}", top.player_idx)
return pop(state)
```

(This is the single, uniform after-auto point, matching how the action spaces fire
it. Handles Dutch Windmill / Roughcaster / Junk Room / Wall Builder.)

**(d) before-auto at push.** Wherever an in-scope frame is pushed (the
`_choose_subaction_*` handlers and the direct pushers — Lessons, the card grants,
etc.), fire `apply_auto_effects(state, f"before_{PENDING_ID}", player_idx)` right
after the push, mirroring the markets' `_initiate_*` and the atomic host. (No-op in
the Family game; needed for any future before-auto sub-action card.)

**(e) `_apply_fire_trigger`** already records-before-applying (the granted-sub-action
fix), so a trigger whose `apply_fn` pushes a primitive (Mining Hammer → push
`PendingBuildStables`; Bread Paddle → push `PendingBakeBread`) works unchanged: it
stamps `triggers_resolved` on the host, then the pushed primitive resolves and pops
back to the host (now in after-phase), which offers the remaining after-triggers +
`Stop`.

---

## 5. The `PendingBuildMajor` / free-oven special case

`CommitBuildMajor` is the one in-scope commit whose effect can **push** (a Clay/Stone
Oven purchase pushes that oven's free-`PendingBakeBread`). Sequence the flip so the
host is already in its after-phase when the free bake pops back:

- **Plain major:** build it → flip `PendingBuildMajor` to `phase="after"` → (no
  push) → after-phase offers after_build_major triggers + `Stop`.
- **Oven:** build it → flip `PendingBuildMajor` to `phase="after"` → **then** push
  the oven's free-bake pending. The free bake resolves and pops back to the
  already-"after" `PendingBuildMajor`, which then offers after-triggers + `Stop`.

So: flip first, push second. Verify `_enumerate_pending_build_major` does not offer
another `CommitBuildMajor` once `phase=="after"`.

Note the **coarse `after_build_improvement`** event (Junk Room / Roughcaster fire on
"any improvement built" = major *or* minor): that is a hand-fired event, fired by
both the build-major effect and `_execute_play_minor`, *in addition to* the
per-`PENDING_ID` `after_build_major` / `after_play_minor`. Keep it as the
`CARD_IMPLEMENTATION_PLAN.md` §Category-5 note describes; it is orthogonal to this
refactor's phase mechanics.

---

## 6. What this refactor does and does NOT unblock

- **Unblocks** the after-*trigger grants* (Mining Hammer, Bread Paddle) — the whole
  point.
- The after-*auto* effects (Dutch Windmill, Roughcaster, Junk Room, Wall Builder)
  are handled by §4(c) firing `after_<id>` at `Stop` — note they would *also* work
  with a much smaller change (fire after-auto at the commit, no phase), so if you
  ever need to descope, those are the cheap ones. We are not descoping; they ride
  the uniform model for free.
- The Category-5 / 8 card modules themselves are **follow-on work** (separate
  commits), not part of this refactor. This refactor lands the *mechanism* + keeps
  every existing test/gate green; the cards come after.

---

## 7. Blast radius — how to find everything you must fix

This refactor changes the **Family game's engine trace**: every in-scope sub-action
now ends with an extra, engine-recorded `Stop` step (a singleton the agents
auto-skip, but `step()`-scripted code does not). Find and fix the fallout by:

1. **The Family-trace `Stop`.** Every place that drives a sub-action by *scripted*
   `step(state, CommitX(...))` and then expects the turn to continue / the stack to
   be empty / the next decision to appear now has a lingering after-phase frame
   needing a trailing `step(state, Stop())`. Find them:
   - `grep -rn "CommitSow\|CommitBake\|CommitPlow\|CommitRenovate\|CommitFamilyGrowth\|CommitPlayOccupation\|CommitPlayMinor\|CommitBuildMajor" tests/`
   - Likely files: `test_grain_utilization`, `test_bake_bread`, `test_farmland`,
     `test_cultivation`, `test_side_job`, `test_major_improvement`,
     `test_house_redevelopment`, `test_farm_expansion`, `test_farm_redevelopment`,
     `test_resolution_atomic`, `test_engine`, `test_legality_non_atomic`, and the
     `tests/test_cards_*` added recently. (List is illustrative — let the failing
     suite be the source of truth.)
   - Update each to the commit→(after-phase)→`Stop` shape. Where a test asserts the
     *exact* legal-action set mid-turn, it must now expect the after-phase
     `[Stop]` (or after-triggers) between the commit and the pop.

2. **Run the full suite and follow the failures** (`pytest tests/ -n 4
   --dist worksteal`). The failures *are* the blast radius for the Python side;
   each is either (a) a missing trailing `Stop`, or (b) an assertion on a legal set
   that gained an after-phase. Do not guess the list up front — fix what fails.

3. **Singleton-skip safety (verify, don't assume).** Agents auto-skip singleton
   decisions, so `play_game`-driven paths and the recording drivers should be
   behavior-equivalent. Confirm:
   - `agents/base.py` / `agents/mcts.py` step through the new singleton `Stop`s.
   - `agents/nn/recording.py` + `selfplay_recording.py` record only *non-singleton*
     decisions, so the after-phase `Stop`s are **not** captured as decisions → the
     NN/self-play datasets are unaffected (assert this — it's load-bearing for not
     invalidating existing data semantics).
   - `agents/restricted.py` wrappers pass a singleton `[Stop]` through `_safe_narrow`.

4. **The C++ differential gates WILL fail — this is the required C++ sync.** The new
   `phase` field reaches Family states (every sub-action flips to "after" before its
   `Stop`), so it is **not** default-skippable and **must** be mirrored in C++.
   Follow the markets precedent exactly (`cpp/` — `types.hpp` add `phase` to each
   in-scope struct; `canonical.cpp` serialize + parse it; `hash.cpp` hash it;
   `engine.cpp` make each `CommitX` non-auto-pop + flip to after; `legality.cpp`
   enumerators gain the after-phase + `Stop`; `_apply_stop` fires the after event;
   the `PendingBuildMajor`/oven sequencing). Rebuild, then
   `pytest tests/test_cpp_*.py` must be green. (This doc is Python-spec; the C++
   work is mechanical mirroring — the gates define "done".)

5. **The web UI** (`play_web.py` + `static/app.js`). The Family game now surfaces an
   extra `Stop` after each sub-action; Fast-mode auto-submits singletons, but
   "Confirm turns" mode and `scripts/verify_web_sync.py` should be exercised. Check
   the `ui_hint` for the new `Stop`s renders sanely.

6. **Serialization** (`canonical.py`). Do **not** add `phase` to
   `_DEFAULT_SKIP_FIELDS` — it is a genuine Family-game value (non-default), so it
   must serialize. (Contrast the markets, which also emit it, vs. the multi-sub
   spaces' derived `after_started`, which has no field.) `triggers_resolved` newly
   added to a frame that lacked it is likewise emitted; mirror in C++.

---

## 8. Verification / definition of done

- `pytest tests/ -n 4 --dist worksteal` green (Python).
- `pytest tests/test_cpp_*.py` green (C++ differential — the Family game is
  byte-identical *between the two engines*; the format changed but both agree).
- A focused new test file asserting the new lifecycle for at least one single-commit
  sub-action (e.g. Grain Utilization: place → `ChooseSubAction("bake_bread")` →
  before-phase → `CommitBake` → after-phase `[Stop]` → `Stop` → parent) and the
  `PendingBuildMajor`/oven path.
- Spot-check that an `-O` run and a short self-play / MCTS run still work (singletons
  stepped through; no new decisions recorded).

---

## 9. Subtleties & open questions for the implementing session

1. **Effect-flips-self vs dispatcher-flips.** §4(a) — choose one style and apply it
   uniformly. The effect-flips-self style matches `_execute_accommodate`; a
   dispatcher `flip_after` flag is less per-function code but must special-case the
   push-cases (`build_major` oven, the granted-sub-action pushers). Decide and
   document.

2. **`PendingBuildMajor` oven ordering** (§5) — the flip-then-push sequence; verify
   the free bake returns to an "after" host and that no second `CommitBuildMajor` is
   offered.

3. **`_apply_stop` event derivation** (§4c) — confirm the `getattr(top,"phase")
   == "after"` discriminator is correct for *all* in-scope frames and never
   misfires for a non-host frame that happens to gain a `phase` later. Consider a
   small explicit predicate/helper instead of `getattr`.

4. **Multi-shot frames left alone** (§2) — make sure none of them are accidentally
   swept in. They keep their build-loop + `Stop`; their after-trigger surfacing (if
   ever needed) is the *derived* `after_started`, a separate change.

5. **Play-card frames** (`PendingPlayOccupation` / `PlayMinor` /
   `PendingFamilyGrowth`) — these are reached from card-mode entry points (Lessons,
   the improvement spaces, Basic Wish, Meeting Place) and from card *grants*. Verify
   the after-phase `Stop` composes correctly when these are pushed *on top of* a
   parent space-host frame (e.g. a minor played at Major/Minor Improvement): the
   sub-action's `Stop` pops back to the parent, which then runs its own
   before/after/`Stop` — two nested host lifecycles. Add a test.

6. **`before_<id>` auto/trigger surfacing on sub-actions** is now uniformly
   available; only Potter (`before_bake_bread`) uses it today. Don't build
   speculative before-paths beyond wiring the uniform shape.

7. **Sequencing.** Land this as its own focused pass (mechanism + green gates) with
   **no new cards**, then add the Category-5/8 card modules in follow-on commits.
   The differential gates are the safety net for the C++ mirror; commit the Python
   side and the C++ sync together (a red-gate interval is expected mid-work).
