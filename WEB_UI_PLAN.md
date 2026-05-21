# Web UI plan — `play_web.py`

A browser-based UI for the AgricolaBot engine, modeled after Boardgamearena's
Agricola interface. Lives parallel to the existing terminal `play.py` driver;
neither replaces nor modifies the engine.

This document is the design spec for a fresh session to implement. It is
written so the next session can read it once and build without re-deriving
decisions.

---

## 1. Goal and non-goals

**Goal.** A browser-based driver that:

- Renders the full game state in one screen (action board, two farmyards, two
  player panels, round log, decision menu).
- Updates continuously via WebSocket — no scrolling text. Every `step()` pushes
  a new state to the browser; the page re-renders in place.
- Supports 1 or 2 human players (random agent fills the second seat in
  1-human mode), matching `play.py` CLI semantics.
- Is *clickable* — placements happen by clicking action-space cards;
  sub-actions happen by clicking farmyard cells, buttons, or input boxes
  appropriate to the action type.

**Non-goals (MVP).**

- No sprite art / themed tile graphics. Plain SVG rectangles with colors and
  text labels are enough. Polish can swap in images later without changing the
  data layer.
- No animations on state change. Simple "re-render the whole frame on each
  state push" is fine.
- No multiplayer over a network (separate browsers on separate machines). One
  game per server, played hot-seat or solo-vs-AI. Future work could add
  multi-game support and authentication.
- No reconnect logic. If the WebSocket drops, the user refreshes.
- No persistence. State lives in process memory; restarting the server starts
  a new game.

---

## 2. Architecture

```
                   ┌────────────────────────────┐
                   │  Browser (Chrome / Firefox)│
                   │   index.html + style.css   │
                   │           + app.js         │
                   └────────────┬───────────────┘
                                │
                  HTTP (POST)   │  WebSocket
                                │  (state push)
                                ▼
                   ┌────────────────────────────┐
                   │  play_web.py (FastAPI)     │
                   │  - holds GameState         │
                   │  - holds humans set        │
                   │  - holds RNG for random ag │
                   │  - broadcasts on each step │
                   └────────────┬───────────────┘
                                │
                                ▼
                   ┌────────────────────────────┐
                   │  agricola.* (engine, pure) │
                   │  - step / legal_actions    │
                   │  - score / setup           │
                   └────────────────────────────┘
```

- Backend is a thin loop just like `play.py`: get legal actions, dispatch
  human (await client) or AI (random choice), call `step()`, broadcast.
- Frontend is stateless beyond pending UI input (e.g. partial pasture
  selection); the canonical state always lives on the server.

---

## 3. File layout

```
play_web.py                    # FastAPI app + game loop + WebSocket
static/
    style.css                  # palette + grid layout + cell styling
    app.js                     # render + click handlers + WS subscription
templates/
    index.html                 # single-page layout
```

No build step. Plain JS (no React/Vue/etc.). One HTML file, one CSS file, one
JS file — easy to read end-to-end. If JS grows past ~600 LOC, split into
modules later.

Run: `python play_web.py [--seed N] [--players 1|2] [--human-seat 0|1]`.
The server prints a URL like `http://127.0.0.1:8000` and opens a browser
(use `webbrowser.open` from stdlib).

---

## 4. Backend API

### HTTP

- **`GET /`** — serves `templates/index.html`.
- **`GET /static/*`** — static asset serving via `StaticFiles`.
- **`GET /api/state`** — returns current state JSON (defined in §6). Used by
  the client on initial load; thereafter the WS push is the canonical update
  channel.
- **`POST /api/step`** — body `{"action_index": int}`. The server applies
  `step(state, legal_actions(state)[i])`, drives the AI seats until the next
  human decision (same loop logic as `play.py`), and broadcasts the resulting
  state. Returns `{"ok": true}` or 400 with an error message if the index is
  illegal.
- **`POST /api/reset`** — body `{"seed": int, "players": 1|2, "human_seat": 0|1}`.
  Resets the in-memory game. Useful for restarting without killing the
  server.

### WebSocket

- **`/api/ws`** — clients connect after page load. Every `step()` (whether
  triggered by a human via POST or by an AI driving forward) pushes the new
  state JSON to all connected clients.

State JSON is the single source of truth. Frontend just renders whatever
arrives. No client-side game logic.

### Concurrency model

- One global `GameState` and one `asyncio.Lock` guard the loop.
- POST handler acquires the lock, applies the action, runs the AI loop until
  a human is the next decider (or game over), broadcasts, releases the lock.
- AI rollouts happen synchronously inside the lock — they're fast.
- Background broadcaster isn't needed; broadcasting happens inline.

---

## 5. Frontend layout

Three columns, BGA-inspired:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Round 5 / 14    Phase: WORK    SP: P0    Deciding: P1                   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ACTION BOARD          │  YOUR BOARD (P0)           │  OPPONENT (P1)     │
│  (left ~30%)           │  (middle ~40%)             │  (right ~30%)      │
│                        │                            │                    │
│  Permanent spaces      │  Farmyard 3x5              │  Farmyard 3x5      │
│  Stage 1 spaces        │  (SVG, clickable cells)    │  (SVG, view-only   │
│  Stage 2 spaces        │                            │   for the decider) │
│  ...                   │  Resources / animals       │                    │
│                        │  Majors / minors           │  Resources etc.    │
│                        │                            │                    │
├──────────────────────────────────────────────────────────────────────────┤
│  DECISION PANEL                                                          │
│  Pending: Grain Utilization > Bake Bread  (triggers_resolved: {})        │
│  Decider: P0                                                             │
│                                                                          │
│  [ CommitBake(1) — +2 food ]  [ CommitBake(2) — +4 food ]  [ Stop ]      │
├──────────────────────────────────────────────────────────────────────────┤
│  ROUND LOG (current round only, collapsible)                             │
│  P0 PlaceWorker(forest) — Forest                                         │
│  P1 PlaceWorker(grain_utilization) → ChooseSubAction(sow) → ...          │
└──────────────────────────────────────────────────────────────────────────┘
```

Decision panel is **contextual**: its content depends on the current legal
actions (see §8). Always present even if only `Stop` is legal.

Active decider is visually highlighted (e.g., green glow on their farmyard
panel border).

---

## 6. State JSON schema

The full state pushed over `/api/ws` and returned by `/api/state`:

```json
{
  "round_number": 5,
  "phase": "WORK",
  "starting_player": 0,
  "current_player": 1,
  "decider": 1,
  "harvest_note": "harvest next round",
  "game_over": false,

  "players": [
    {
      "idx": 0,
      "is_sp": true,
      "is_decider": false,
      "house_material": "wood",
      "people_total": 3,
      "people_home": 1,
      "newborns": 0,
      "begging_markers": 0,
      "interim_score": 4,

      "resources": {"wood": 2, "clay": 1, "reed": 0, "stone": 0, "food": 3, "grain": 0, "veg": 0},
      "animals":   {"sheep": 0, "boar": 0, "cattle": 0},

      "fences_in_supply": 15,
      "stables_in_supply": 4,

      "majors": [{"idx": 5, "name": "Clay Oven"}, ...],
      "minors": ["potter_ceramics", ...],

      "farmyard": {
        "cells": [
          [{"type": "EMPTY"}, {"type": "EMPTY"}, ..., {"type": "FIELD", "grain": 2, "veg": 0}],
          [...],
          [{"type": "ROOM"}, {"type": "ROOM"}, ..., {"type": "STABLE"}, ...]
        ],
        "h_fences": [[true, false, ...], ...],            // 4 rows x 5 cols
        "v_fences": [[false, true, ...], ...],            // 3 rows x 6 cols
        "pastures": [
          {"cells": [[1, 3], [2, 3]], "capacity": 8, "fenced_stables": 1}
        ]
      }
    },
    { "idx": 1, ... }
  ],

  "board": {
    "spaces": [
      {
        "id": "forest",
        "name": "Forest",
        "category": "permanent",        // or "stage"
        "stage": null,                  // 1-6 for stage cards, null for permanent
        "round_revealed": 0,            // 0 = always; else round 1-14
        "is_revealed": true,
        "workers": [1, 0],              // P0 has 1, P1 has 0
        "accumulation_text": "3 wood"   // pre-formatted; "" if none
      },
      ...
    ],
    "major_owners": [null, null, null, 0, null, 1, null, null, null, null]
  },

  "pending_stack": [
    {
      "type": "PendingGrainUtilization",
      "player_idx": 0,
      "details_text": "sow_chosen=true, bake_chosen=false"
    },
    {
      "type": "PendingBakeBread",
      "player_idx": 0,
      "details_text": "triggers_resolved=set()"
    }
  ],

  "legal_actions": [
    {
      "index": 0,
      "type": "CommitBake",
      "display": "CommitBake(grain=1) — +2 food",
      "params": {"grain": 1},
      "ui_hint": "button"          // see §8
    },
    {
      "index": 1,
      "type": "CommitBuildPasture",
      "display": "CommitBuildPasture(cells={(0,3),(0,4)})",
      "params": {"cells": [[0, 3], [0, 4]]},
      "ui_hint": "cell_set"
    },
    ...
  ],

  "round_log": [
    {"round": 4, "decider": 1, "is_carryover": false,
     "text": "P1 PlaceWorker(meeting_place) → CommitConvert(...)"},
    ...
  ]
}
```

All formatting (names, accumulation text, display strings) is done on the
**server**, in `play_web.py`. The client just renders strings. This means the
existing `_fmt_*` helpers from `play.py` can be lifted into a shared module
(suggested location: `webui/format.py` or just re-imported from a refactored
`play.py`).

`ui_hint` on each legal action tells the frontend how to render the affordance
for that action (see §8).

---

## 7. Action dispatch

Frontend sends an action by `index` into the `legal_actions` array:

```js
fetch('/api/step', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({action_index: 5})
});
```

Server looks up `actions[5]` from the *current* `legal_actions(state)` and
applies it. Race window: if the client computed the index against a slightly
stale state, the server's recomputed `legal_actions` may differ. Two
mitigations:

1. **State version token.** Include `state.version` (monotonic counter) in
   each pushed state and require it in `POST /api/step`. Reject mismatched
   versions with 409; client refetches.
2. **Optimistic locking.** Skip the version token and just accept the race —
   the AsyncIO lock serializes all step()s, and in single-human-player
   sessions there are no concurrent submissions.

**Pick (2) for MVP.** If two browser tabs are open, behavior is undefined —
fine for now.

---

## 8. UI hints per action type

Each legal action carries a `ui_hint` that tells the frontend how to surface
it. The decision panel iterates over hints and renders affordances grouped
by hint type.

| `ui_hint`           | Action types                                      | Frontend treatment |
|---|---|---|
| `space`             | `PlaceWorker`                                     | Highlight the matching action-space card with a "Place worker here" affordance; click → POST. |
| `button`            | `ChooseSubAction`, `CommitBake`, `Stop`, `FireTrigger`, `CommitRenovate` | Render as a labeled button in the decision panel. Click → POST. |
| `cell`              | `CommitPlow`, `CommitBuildStable`, `CommitBuildRoom` | Highlight the legal cells on the decider's farmyard. Click → POST. |
| `cell_set`          | `CommitBuildPasture`                              | Multi-select cells; show "Confirm pasture" button when the partial selection matches a legal set. (Server pre-computes the legal cell-sets; client only allows clicking cells that appear in at least one option, then matches on confirm.) |
| `numeric`           | `CommitSow`, `CommitBake` (with multiple options), `CommitAccommodate`, `CommitBreed`, `CommitConvert`, `CommitHarvestConversion` | Render the full legal list as a list of buttons or a small grid (since Pareto frontiers are small). |
| `major`             | `CommitBuildMajor`                                | Highlight the matching major-improvement card in the supply board; click → POST. (For Cooking Hearth's return-fireplace option, show a second small menu.) |

For MVP, simplest path: render all non-`space` / non-`cell` / non-`cell_set`
actions as plain buttons in the decision panel. Add cell-clicking and
multi-select polish as second pass.

---

## 9. CSS palette and styling

Goal: looks like Agricola (greens and earth tones), not generic Bootstrap.

- Background: warm green `#7FA854`
- Action-board cards: light cream `#F4E9D0` with brown border
- Farmyard background: light green `#A8C97A`
- Cell types:
  - EMPTY: same as farmyard bg
  - ROOM: brown `#8B6F47` (wood) → terracotta `#C77042` (clay) → grey `#7F7F7F` (stone)
  - FIELD: tilled brown `#A87447`; show grain/veg count as text
  - STABLE: light wood `#C9A875` with a roof icon (text "⌂" or similar)
- Fence: solid black line `2px` where player-placed
- Boundary (no player fence): dashed light grey
- Pasture overlay: faint green tint over the enclosed cells

Active decider's farmyard: green glow border `box-shadow: 0 0 8px #4D8030`.
Opponent's farmyard: 60% opacity to de-emphasize.

Worker tokens on action-space cards: small colored circles (P0 red, P1 blue).

Detailed CSS is straightforward; this section establishes the palette. The
implementation session can use any pleasant green/brown variation that
matches the spirit.

---

## 10. MVP scope

Must-have (MVP):

1. Backend serves state, accepts POST, broadcasts via WS.
2. Initial page loads and shows a fresh game.
3. Action-space cards render with names, accumulation text, worker tokens.
4. Both farmyards render with cells, fences, pastures, crops.
5. Player panels render with resources, animals, people, score, supply
   counts, owned majors.
6. Pending breadcrumb + key fields visible at top of decision panel.
7. Round log visible at bottom; updates live.
8. **All legal actions clickable as plain buttons** in the decision panel
   (no cell-clicking yet). Enough to play through a whole game.
9. AI agent plays automatically between human prompts.
10. Game-over screen with full `ScoreBreakdown` table and winner.

Stretch (post-MVP, in order of value):

1. **PlaceWorker** as a click on the matching action-space card (instead of
   a button in the decision panel).
2. **Cell-click** for `CommitPlow`, `CommitBuildStable`, `CommitBuildRoom`.
3. **Multi-cell select** for `CommitBuildPasture`.
4. **Major-card click** for `CommitBuildMajor`.
5. **Live preview** during multi-cell selection (e.g., fence-cost preview,
   pasture-capacity preview).
6. Per-player WebSocket gating so each browser tab only acts as one player
   (real multiplayer over network).
7. Sprite art and tile graphics.

---

## 11. Implementation order

The recommended build order for the fresh session:

1. **`play_web.py` skeleton** (~50 LOC): FastAPI app, mount `/static`, serve
   `index.html`, define routes returning stubs, register a single WS endpoint.
2. **Game state singleton + reset endpoint** (~30 LOC): in-process `GameState`
   variable, lock, `reset` to call `setup(seed)`.
3. **State serializer** (~150 LOC): `state_to_json(state) -> dict`. Lift
   formatting helpers from `play.py` (`_fmt_resources`, `_fmt_animals`,
   `_fmt_accumulation`, `MAJOR_NAMES`, `SPACE_DISPLAY_NAMES`,
   `_pending_detail`). Optional: refactor `play.py` to expose these as
   module-level helpers.
4. **Step endpoint + driver loop** (~50 LOC): apply action by index, then run
   AI seats until the next human decision (mirror of `play.py`'s main loop).
   Broadcast.
5. **index.html layout** (~80 LOC): static skeleton with placeholder divs for
   each panel.
6. **app.js: WebSocket subscription + render** (~200 LOC):
   - Connect to `/api/ws` on load.
   - On message, parse state JSON; re-render every panel by replacing
     `innerHTML`.
   - Render action-space cards from `state.board.spaces`.
   - Render farmyards from `state.players[i].farmyard` as SVG.
   - Render player panels from `state.players[i]`.
   - Render decision panel from `state.legal_actions`: all as buttons for
     MVP.
   - Render round log from `state.round_log`.
7. **app.js: click handlers** (~50 LOC): button click → POST
   `/api/step` with action_index.
8. **style.css** (~150 LOC): palette and layout.
9. **Smoke-test a full game** end-to-end. Fix rendering edge cases (harvest
   feed / breed pendings, fence rendering, accumulation spaces).
10. **Game-over rendering** (~30 LOC): show `ScoreBreakdown` once
    `state.game_over` flips true.

Total MVP estimate: ~700–900 LOC across `play_web.py` (~250), `index.html`
(~80), `app.js` (~300), `style.css` (~200). One focused session.

---

## 12. Open questions for the implementation session

These are decisions to make when the code is in front of you; not blocking.

1. **Auto-open browser?** Use `webbrowser.open(url)` on server start, or
   print the URL and let the user click? Default: auto-open in dev mode,
   print-only with `--no-browser`.

2. **Hot-reload?** Use `uvicorn --reload` during development. Production
   command is `python play_web.py`.

3. **Major-improvement card rendering.** Where do the 10 major cards live on
   the main board? Suggested: a small sidebar between the action board and
   the farmyards, with each card showing owner (player color) or "supply"
   if unowned.

4. **House material visualization on rooms.** BGA shows the material via
   tile color. Suggested: room cells colored per `house_material` field.

5. **Newborn meeples on action spaces.** Currently shown via `workers: (2,
   0)` (parent + newborn). UI shows count via a "x2" badge next to the
   token. Or two tokens stacked. Either works.

6. **Pasture overlay rendering.** A subtle green wash over enclosed cells,
   or just the fence outlines? Suggested: fence outlines + a small
   `cap=N | NfS` label inside the pasture's bounding region.

7. **2-human "privacy"?** None — Agricola is fully open-information. Both
   players' state always visible. (Same as the terminal UI.)

8. **Round log scope.** Current-round + AI carryover from previous round
   (same logic as `play.py` `RoundLog`). Lift the `RoundLog` class onto the
   server; the JSON payload is just the rendered string per turn.

9. **Slash-command parity.** Should the web UI expose `/score`, `/state`,
   `/board` equivalents? Suggested: a "Full Score" button (interim score
   breakdown modal). Other commands are unnecessary in the web UI since the
   full state is always visible.

10. **Mobile?** Out of scope; assume desktop-class screen ≥ 1280px wide.
    Could be added by responsive CSS later.

---

## 13. How the implementation session should start

1. Read this doc end-to-end.
2. Read `play.py` for reference — most rendering helpers are reusable, and
   the main loop is the template for `play_web.py`'s driver.
3. Skim `agricola/state.py`, `agricola/pending.py`, `agricola/actions.py`
   for the data shapes the JSON serializer needs to handle.
4. Decide whether to factor shared helpers into a `web/format.py` module or
   import directly from `play.py` (or copy). Suggested: copy for MVP; factor
   later if duplication grows.
5. Build per §11 in order. Smoke-test against the full game using the same
   approach as `play.py`'s `play(seed, humans=set())` (drive both seats with
   random agent until game over).
6. Commit when MVP plays a full game end-to-end.

---

## 14. What this doc does *not* commit to

- No promise about exact CSS shades, grid pixel sizes, or font choices.
- No promise about which JS framework features to use (the spec says plain
  JS, but if the implementer wants to introduce a tiny templating helper or
  use `<template>` elements, that's fine — same MVP scope, same data flow).
- No promise about animations, sound, or polish features beyond §10
  must-haves.

These get decided during implementation. The doc is the architectural
backbone; the rest is taste and iteration.
