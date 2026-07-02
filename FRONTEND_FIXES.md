# Frontend fixes for the AgricolaBot Web UI

The web UI's backend (`play_web.py`) is sound — it lifts the round-log logic
from `play.py`, surfaces all the right fields in the wire format, and already
runs through a few terminal-UI fixes via shared helpers.

The remaining gaps live in the **frontend** (`static/app.js`,
`static/style.css`, `templates/index.html`). Each item below states the
underlying problem (the same one the terminal UI hit at some point during
iteration), what data the backend already exposes, and the specific frontend
change needed.

Items are ordered by **certainty that the fix is needed**, highest first.
Items 1–4 are almost certainly missing; 5–7 are common omissions; 8–10 may
already be handled. Apply in order, checking first to see if the fix is already
present or otherwise unnecessary.

> **Status: items 1–10 are all landed.** They are kept below as the
> problem/solution record. The genuinely-open items are **11–13** at the
> bottom (carried over from the archived web-UI plan's open questions).

---

## 1. PlaceWorker menu ordering must match the action board  *(very high certainty)*

**Problem.** `legal_actions(state)` returns PlaceWorker entries in whatever
order the legality module computes them — which does **not** match the
visual order of spaces on the action board (Forest, Clay Pit, Reed Bank,
…). The result: menu row #1 is `day_laborer` while Forest is the top-left
card on the board. Players have to scan the menu to find the action they
want to take.

**Backend support.** The wire format includes:

- `state.board.spaces` — array of all spaces with `id`, `category`
  (`"permanent"` or `"stage"`), `stage` (1–6 or `null`), `round_revealed`
  (0 for permanent, 1–14 for stage cards).
- `state.legal_actions[i]` for each PlaceWorker has `type: "PlaceWorker"`
  and `params: { space: <id> }`.

The backend does *not* sort. Sorting is the frontend's job.

**Required change.** In the action-menu renderer (or wherever PlaceWorker
options are surfaced), sort PlaceWorker actions using this key, matching
`play.py`'s `_placeworker_sort_key`:

```js
const PERMANENT_DISPLAY_ORDER = [
    "forest", "clay_pit", "reed_bank", "fishing", "meeting_place",
    "grain_seeds", "farmland", "day_laborer", "side_job", "farm_expansion",
];

function placeworkerSortKey(action, board) {
    const sid = action.params.space;
    const i = PERMANENT_DISPLAY_ORDER.indexOf(sid);
    if (i >= 0) return [0, i];
    const space = board.spaces.find(s => s.id === sid);
    return [1, space ? space.round_revealed : 999, sid];
}

// When rendering the menu:
const placeworkers = state.legal_actions.filter(a => a.type === "PlaceWorker");
placeworkers.sort((a, b) => {
    const ka = placeworkerSortKey(a, state.board);
    const kb = placeworkerSortKey(b, state.board);
    return ka[0] - kb[0] || ka[1] - kb[1] || ka[2].localeCompare?.(kb[2] ?? "") || 0;
});
```

**Files.** `static/app.js`.

---

## 2. Farmyard boundary fences must be visually distinct  *(very high certainty)*

**Problem.** The 3×5 farmyard has an outer rectangular boundary. The
boundary edges *can* hold player-placed fences (and those fences count
toward the player's 15-fence supply and toward enclosing pastures along
the edge). If the renderer draws the farmyard outline as a single fixed
rectangle, the player cannot tell whether they've placed fences on the
boundary or not.

**Backend support.** `state.players[i].farmyard` includes raw 2D bool
arrays — no boundary-vs-internal distinction is encoded; the frontend
must derive it from indices:

- `h_fences[4][5]` (horizontal edges):
  - row 0 = top boundary of farmyard
  - rows 1–2 = internal edges between farm rows
  - row 3 = bottom boundary
- `v_fences[3][6]` (vertical edges):
  - col 0 = left boundary
  - cols 1–4 = internal edges between farm cols
  - col 5 = right boundary

**Required change.** In the SVG farmyard renderer, draw each edge with one
of three styles based on the bool value AND whether the edge is a
boundary:

| Case | When | Style |
|---|---|---|
| **Player fence** | bool is `true` (any location) | Solid dark line, thick (e.g. `stroke="#222" stroke-width="3"`) |
| **Unfenced boundary** | bool is `false` AND edge is at h-row 0/3 or v-col 0/5 | Dashed lighter line (e.g. `stroke="#888" stroke-dasharray="3 2" stroke-width="1"`) — communicates "edge exists but no player fence" |
| **Unfenced interior** | bool is `false` AND edge is internal | Don't draw, OR very subtle 1px light grey |

This is the SVG equivalent of the terminal UI's `---` / `···` / `   ` and
`|` / `:` / ` ` distinction.

**Files.** `static/app.js` (farmyard SVG renderer). Stroke styles can be
inline attributes or CSS classes — your choice.

---

## 3. Round-log carryover entries must be visually distinguishable  *(high certainty)*

**Problem.** When a round ends while the AI was acting, the AI's tail
moves carry into the next round's log so the player can see what happened
in the gap. Once the player makes a move in the new round, these
carryover lines drop out (the backend already handles this). But while
they're visible, the player needs to be able to tell at a glance which
log lines are "leftover from previous round" vs "this round." Otherwise
two identical-looking moves (e.g., "P1 meeting_place" appearing as both
the AI's last round-1 move and their first round-2 move) are confusing.

**Backend support.** Each entry in `state.round_log` has:

```
{
    round: <int>,           // round the turn happened in
    decider: <int>,
    is_carryover: <bool>,   // true iff round != current_round
    text: "<inline turn description>",
    in_progress: <bool?>    // present only for the in-progress buffer
}
```

**Required change.** When rendering each log entry:

- Apply a CSS class (e.g. `log-entry log-entry--carryover`) when
  `is_carryover === true`.
- Prefix the text with `(R<round>) ` so the carryover round is explicit.

```js
function renderLogEntry(entry) {
    const cls = entry.is_carryover
        ? "log-entry log-entry--carryover"
        : (entry.in_progress
            ? "log-entry log-entry--in-progress"
            : "log-entry");
    const prefix = entry.is_carryover ? `(R${entry.round}) ` : "";
    return `<div class="${cls}">${prefix}P${entry.decider} ${escapeHtml(entry.text)}</div>`;
}
```

CSS:

```css
.log-entry--carryover { color: #777; font-style: italic; }
.log-entry--in-progress { font-style: italic; opacity: 0.85; }
```

**Files.** `static/app.js`, `static/style.css`.

---

## 4. Pending breadcrumb must show frame-relevant details  *(high certainty)*

**Problem.** When the engine reaches `HARVEST_FEED`, it pre-debits all
available food (per the "Cannot withhold food tokens" rule) and stores
the remainder as `pending.food_owed` on the `PendingHarvestFeed` frame.
The visible food count in the player panel goes to 0, but the player
still owes food. Without surfacing `food_owed`, the player has no way to
tell how much they need to convert (and how much will become begging
markers). This bug is **silent in the player panel and only visible on
the pending frame**.

The same shape applies to other pendings: `pastures_built`/`fences_built`
on `PendingBuildFences`, `gained` on market pendings, `cost` on
`PendingRenovate` / `PendingBuildStables` / `PendingBuildRooms`,
`num_built`/`max_builds` on multi-shot pendings.

**Backend support.** `state.pending_stack[i]` includes:

```
{ type: "PendingHarvestFeed", player_idx: 0,
  details_text: "food_owed=4, conversion_done=False" }
```

`details_text` is computed server-side via `_pending_detail` (lifted from
`play.py`). It returns useful summary fields per pending type and is
empty for pendings without notable state.

**Required change.** In the pending breadcrumb renderer, display
`details_text` after the type-name chain — especially for the topmost
pending, since that's the active decision context.

```js
function renderPending(stack) {
    if (!stack.length) return "";
    const breadcrumb = stack
        .map(f => f.type.replace(/^Pending/, ""))
        .join(" > ");
    const top = stack[stack.length - 1];
    const detail = top.details_text || "";
    const detailHtml = detail ? ` <span class="pending-detail">(${escapeHtml(detail)})</span>` : "";
    return `<div class="pending-line">Pending: ${escapeHtml(breadcrumb)}${detailHtml}</div>`;
}
```

CSS: make the detail text slightly muted but readable
(`color: #555; font-size: 0.95em;`).

**Files.** `static/app.js`, `static/style.css`.

---

## 5. In-progress turn must appear in the log  *(medium-high certainty)*

**Problem.** When the player is mid-turn (e.g., they've chosen
`ChooseSubAction(sow)` and are now picking a `CommitSow`), the round log
should already show the in-progress sequence so they can see what
they've committed in this turn so far. Without this, the log only
updates after the *next* turn starts.

**Backend support.** `RoundLog.to_wire` appends a final entry with
`in_progress: true` if the turn buffer is non-empty:

```
{ round, decider, is_carryover: false, text, in_progress: true }
```

**Required change.** Already partly handled by the example in item 3
(the `log-entry--in-progress` class). Make sure:

- The in-progress entry is rendered (don't filter it out).
- Its style differs from completed turns (italics / muted opacity / etc.).

**Files.** `static/app.js`, `static/style.css`.

---

## 6. Active decider visually highlighted  *(medium certainty)*

**Problem.** In 2-human mode, and during harvest in 1-human mode, the
decider can switch between players. Without a strong visual indicator
of "you're the active decider," it's easy to start clicking on the wrong
player's panel.

**Backend support.** Each player has `is_decider: bool`, and the top
level has `state.decider: <int>`. The currently-controlling worker
placement is `state.players[i].is_current`.

**Required change.** Apply a class to the decider's panel:

```js
const cls = player.is_decider ? "player player--decider" : "player";
```

```css
.player--decider {
    box-shadow: 0 0 8px #4D8030;
    border: 2px solid #4D8030;
}
.player:not(.player--decider) {
    opacity: 0.75;
}
```

Optionally also highlight the corresponding farmyard for cell-clickable
sub-actions.

**Files.** `static/app.js`, `static/style.css`.

---

## 7. Large-option Commit actions need a non-button UI  *(medium certainty)*

**Problem.** `CommitBuildPasture` can have 100+ legal options at any one
state. Rendering each as a button in the decision panel is unusable.
`CommitPlow`, `CommitBuildStable`, `CommitBuildRoom`, and (less often)
`CommitConvert` can also balloon.

**Backend support.** Backend serializes every legal action; no
threshold. The `ui_hint` field on each legal action suggests the
intended treatment:

| `ui_hint` | Backend's intent |
|---|---|
| `space` | PlaceWorker — click an action-space card |
| `cell` | Single-cell click on the decider's farmyard (Plow / BuildStable / BuildRoom) |
| `cell_set` | Multi-cell click + confirm (BuildPasture) |
| `major` | Click a major improvement card |
| `numeric` | Small numeric-frontier (Sow / Bake / Accommodate / Breed / Convert / HarvestConversion) — render as a list of buttons; usually small (≤ 10) |
| `button` | Generic button (ChooseSubAction, FireTrigger, Renovate) |
| `stop` | Stop button |

**Required change.** If the frontend currently renders all actions as
flat buttons, it will be unusable for cell-set actions. Either:

- **(a) Implement `cell` / `cell_set` properly** — let the player click
  farmyard cells; gather selection; submit the matching legal action.
  This is the `ui_hint` affordance path (CLAUDE.md → Web UI & online deployment). Best UX.
- **(b) Fallback: terminal-style class-and-prompt** — if there are >8
  options of one Commit type, collapse them under a "Pick a
  CommitBuildPasture (N options)" button that opens a sub-list /
  searchable picker. Less elegant but functional.

If neither is in place, picking a pasture in non-trivial states is
currently impossible.

**Files.** `static/app.js` — the cell-click handlers and the decision-
panel renderer. `static/style.css` for selection highlights.

---

## 8. Resources and animals must be labeled  *(lower certainty)*

**Problem.** If the frontend just stringifies `state.players[i].resources`
({wood: 2, clay: 1, ...}), the player sees a hard-to-scan blob. They
need labels (or eventually icons) per value.

**Backend support.** Each player has `resources` and `animals` as labeled
objects:

```
resources: { wood, clay, reed, stone, food, grain, veg }
animals:   { sheep, boar, cattle }
```

**Required change.** Render each value with its label in the player
panel. Without art icons, use text:

```html
<div class="resource">Wood: 2</div>
<div class="resource">Clay: 1</div>
...
```

Or a grid:

```
+---------+---------+---------+---------+
|  Wood 2 | Clay  1 | Reed  0 | Stone 0 |
+---------+---------+---------+---------+
|  Food 3 | Grain 0 | Veg   0 |         |
+---------+---------+---------+---------+
```

This is likely already done; verify and adjust if cramped.

**Files.** `static/app.js`, `templates/index.html`, `static/style.css`.

---

## 9. Action board ordering / grouping  *(lower certainty)*

**Problem.** If the frontend iterates `state.board.spaces` in dict order,
the layout may not group permanent vs stage cards cleanly. The terminal
UI groups: permanent (in `PERMANENT_DISPLAY_ORDER`), then stage 1
(by reveal round), then stage 2, …

**Backend support.** `state.board.spaces[i]` has `category` (`"permanent"` /
`"stage"`), `stage` (1–6 or null), `round_revealed`.

**Required change.** Group the spaces in the board renderer:

```js
const permanent = state.board.spaces
    .filter(s => s.category === "permanent")
    .filter(s => s.id !== "lessons")          // never legal in Family game
    .sort((a, b) => PERMANENT_DISPLAY_ORDER.indexOf(a.id) - PERMANENT_DISPLAY_ORDER.indexOf(b.id));

const stageGroups = {};
for (const s of state.board.spaces) {
    if (s.category !== "stage" || !s.is_revealed) continue;
    (stageGroups[s.stage] ??= []).push(s);
}
for (const arr of Object.values(stageGroups)) {
    arr.sort((a, b) => a.round_revealed - b.round_revealed);
}
```

Render as labeled sections: "Permanent", "Stage 1", "Stage 2", ….

**Files.** `static/app.js`.

---

## 10. Unrevealed stage cards must be hidden or dimmed  *(lower certainty)*

**Problem.** Future stage cards should
either be hidden or dimmed. If they're rendered as normal, the player
sees future cards that aren't yet in play (low-priority but noisy).

**Backend support.** Each space has `is_revealed: bool`.

**Required change.** In the board renderer:

- If `s.is_revealed === false`, either skip it entirely or render with
  reduced opacity and no accumulation/worker info.

```js
if (!s.is_revealed) {
    return `<div class="space space--hidden">${`(round ${s.round_revealed})`}</div>`;
}
```

```css
.space--hidden { opacity: 0.3; }
```

**Files.** `static/app.js`, `static/style.css`.

---

## 11. House material visualization on room cells  *(open, low priority)*

**Problem.** Room cells all render in the same wood color regardless of the
player's actual house material. BoardGameArena recolors rooms by material
(wood → clay → stone), which makes a renovated house legible at a glance.

**Backend support.** `state.players[i].house_material` ("wood" / "clay" /
"stone") is already in the wire format.

**Required change.** Color ROOM cells per `house_material` (a `--room-clay` /
`--room-stone` palette alongside the existing `--room-wood`). One-line change
in the farmyard cell renderer + a couple of CSS vars.

**Files.** `static/app.js`, `static/style.css`.

---

## 12. Newborn meeples shown distinctly  *(open, low priority)*

**Problem.** A space holding a parent + newborn worker currently shows a single
token with a count (e.g. "x2"). Two stacked/offset tokens would read more
clearly as "two people here."

**Backend support.** `state.board.spaces[i].workers` is `[p0_count, p1_count]`;
the newborn is already included in the count.

**Required change.** When a count is >1, render stacked/offset tokens instead of
a single token with a badge. Purely cosmetic.

**Files.** `static/app.js`, `static/style.css`.

---

## 13. Mid-game full-score breakdown modal  *(open, low priority)*

**Problem.** The player panel shows the rolling interim total, but there is no
way to see the full per-category `ScoreBreakdown` mid-game (only the game-over
modal shows it).

**Backend support.** The game-over modal already renders a `ScoreBreakdown`
table; the same breakdown can be computed for the live state server-side.

**Required change.** A "Full score" button that opens the breakdown modal for
the current state (reuse the game-over modal's table renderer).

**Files.** `play_web.py` (expose the interim breakdown if not already), `static/app.js`, `static/style.css`.

---

## Notes for the implementer

- The backend (`play_web.py`) was written carefully and shouldn't need
  changes for any of these. If something on this list seems to require a
  backend change, double-check the wire format first — the data is almost
  certainly already there.
- All visual changes can be guided by `play.py`'s rendering decisions for
  the terminal UI. Specifically, look at:
  - `_placeworker_sort_key` in `play.py` (item 1)
  - `render_farmyard` in `play.py` (item 2)
  - `RoundLog.render_lines` and the `(R<round>)` prefix logic (item 3)
  - `_pending_detail` and `render_pending` in `play.py` (item 4)
- These fixes are independent. You can apply 1, 2, 3, 4 in any order, then
  smoke-test, then tackle 5–10 piecemeal.
