// AgricolaBot Web UI — vanilla JS, SSE-driven.
//
// Server pushes full GameState JSON on /api/events; we re-render in place.
// Clicking any action button POSTs { action_index } to /api/step.

(function () {
  'use strict';

  // ---------------------------------------------------------------------
  // SSE subscription
  // ---------------------------------------------------------------------

  let currentState = null;
  let evtSource = null;
  // Selection state for multi-cell pasture build. Reset on every state push.
  // Stored as Set<"r,c">.
  let cellSelection = new Set();

  // Fast mode: when enabled, auto-submit whenever there is exactly one legal
  // action. Persists across reloads. Stateful guard so multiple re-renders of
  // the same server state don't multi-fire — only one auto-submit per push.
  let fastMode = localStorage.getItem('agricola.fastMode') === '1';
  let stateVersion = 0;
  let lastAutoSubmittedVersion = -1;

  function setConnState(connected) {
    const el = document.getElementById('connection-state');
    if (!el) return;
    el.textContent = connected ? 'online' : 'offline';
    el.className = connected ? 'conn-connected' : 'conn-disconnected';
  }

  function connectSSE() {
    if (evtSource) try { evtSource.close(); } catch (_) {}
    evtSource = new EventSource('/api/events');
    evtSource.addEventListener('open', () => setConnState(true));
    evtSource.addEventListener('error', () => setConnState(false));
    evtSource.addEventListener('state', (e) => {
      try {
        currentState = JSON.parse(e.data);
        cellSelection = new Set();  // server step happened → drop any partial selection
        stateVersion++;
        render(currentState);
      } catch (err) {
        console.error('failed to parse state', err);
      }
    });
  }

  // ---------------------------------------------------------------------
  // Action submission
  // ---------------------------------------------------------------------

  async function submitAction(actionIndex) {
    try {
      const res = await fetch('/api/step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_index: actionIndex }),
      });
      const data = await res.json().catch(() => ({}));
      if (!data.ok) {
        console.warn('step rejected:', data.error);
      }
    } catch (err) {
      console.error('step request failed', err);
    }
  }

  // Apply one AI move. Used in AI-vs-AI mode (manual step-through) and as
  // the bound action for the "Advance" button / Enter-key shortcut. In
  // human-vs-AI mode the backend already fast-forwards AI moves after a
  // human action, so this is rarely needed there.
  let aiStepInFlight = false;
  async function stepAI() {
    if (aiStepInFlight) return;  // single-flight: avoid stacking on rapid keypresses
    aiStepInFlight = true;
    try {
      const res = await fetch('/api/step_ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const data = await res.json().catch(() => ({}));
      if (!data.ok) {
        console.warn('step_ai rejected:', data.error);
      }
    } catch (err) {
      console.error('step_ai request failed', err);
    } finally {
      aiStepInFlight = false;
    }
  }

  // User-facing seat names shown in the New-game dialog. We expose a
  // simplified set ('v1' = current strongest V1 = backend 'hubris',
  // 'v3' = current strongest V3 = backend 'hubris_v3' loaded via
  // --v3-config). The backend understands additional types ('simple',
  // 'hubris_v1', 'hubris_v2') for CLI use but they're not surfaced here.
  const SEAT_LABELS = ['human', 'random', 'v1', 'v3'];
  const LABEL_TO_BACKEND = {
    'human': 'human',
    'random': 'random',
    'v1':     'hubris',     // V1 architecture with tuned CONFIG_V1_T2
    'v3':     'hubris_v3',  // V3 architecture (loads --v3-config if set)
  };
  const BACKEND_TO_LABEL = {
    'human': 'human',
    'random': 'random',
    'simple': 'simple',
    'hubris': 'v1',
    'hubris_v1': 'v1 (default)',
    'hubris_v2': 'v2',
    'hubris_v3': 'v3',
  };

  function backendToLabel(backend) {
    return BACKEND_TO_LABEL[backend] || backend;
  }

  async function resetGame() {
    // Three prompts to match the existing prompt-style UX (avoids building
    // a modal). For richer setup, a future change can swap in a real modal.
    const seedStr = prompt('Seed for new game?', String(Date.now() & 0xffff));
    if (seedStr === null) return;
    const seed = parseInt(seedStr, 10) || 0;
    const currentSeats = (currentState && currentState.seats) || ['human', 'random'];
    const p0Str = prompt(
      `P0 seat? (${SEAT_LABELS.join(' / ')})`,
      backendToLabel(currentSeats[0]));
    if (p0Str === null) return;
    const p1Str = prompt(
      `P1 seat? (${SEAT_LABELS.join(' / ')})`,
      backendToLabel(currentSeats[1]));
    if (p1Str === null) return;
    const p0Label = SEAT_LABELS.includes(p0Str.trim()) ? p0Str.trim() : 'human';
    const p1Label = SEAT_LABELS.includes(p1Str.trim()) ? p1Str.trim() : 'random';
    const p0 = LABEL_TO_BACKEND[p0Label];
    const p1 = LABEL_TO_BACKEND[p1Label];
    const res = await fetch('/api/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed, seats: [p0, p1] }),
    });
    const data = await res.json().catch(() => ({}));
    if (!data.ok) {
      console.warn('reset rejected:', data.error);
    }
  }

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === 'class') e.className = v;
        else if (k === 'onclick') e.addEventListener('click', v);
        else if (k === 'dataset') Object.assign(e.dataset, v);
        else if (k === 'html') e.innerHTML = v;
        else e.setAttribute(k, v);
      }
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return e;
  }

  function svgEl(tag, attrs) {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        e.setAttribute(k, String(v));
      }
    }
    return e;
  }

  function setFastMode(v) {
    fastMode = !!v;
    localStorage.setItem('agricola.fastMode', fastMode ? '1' : '0');
    const cb = document.getElementById('fast-mode-toggle');
    if (cb) cb.checked = fastMode;
    // Re-arm so toggling ON immediately fires for the current state if it's
    // a singleton. Toggling OFF is a no-op beyond persisting the preference.
    lastAutoSubmittedVersion = -1;
    if (currentState) render(currentState);
  }

  function maybeAutoSubmit(state) {
    if (!fastMode) return;
    if (state.game_over) return;
    if (state.legal_actions.length !== 1) return;
    if (lastAutoSubmittedVersion === stateVersion) return;
    lastAutoSubmittedVersion = stateVersion;
    // Defer to next tick so the DOM update completes before the next POST.
    setTimeout(() => submitAction(state.legal_actions[0].index), 0);
  }

  function render(state) {
    renderHeader(state);
    renderActionBoard(state);
    renderMajorBoard(state);
    renderPlayerPanel(state, 0);
    renderPlayerPanel(state, 1);
    renderDecisionPanel(state);
    renderRoundLog(state);
    renderGameOver(state);
    maybeAutoSubmit(state);
  }

  // -------- header --------

  function renderHeader(state) {
    document.getElementById('round-label').textContent =
      `Round ${state.round_number}/14`;
    document.getElementById('phase-label').textContent =
      `Phase ${state.phase}`;
    document.getElementById('sp-label').textContent =
      `SP P${state.starting_player}`;
    document.getElementById('decider-label').textContent =
      state.game_over ? 'Game over' : `Deciding: P${state.decider}`;
    document.getElementById('harvest-note').textContent =
      state.harvest_note || '';
  }

  // -------- action board --------

  const PERMANENT_ORDER = [
    'forest', 'clay_pit', 'reed_bank', 'fishing', 'meeting_place',
    'grain_seeds', 'farmland', 'day_laborer', 'side_job', 'farm_expansion',
  ];
  const STAGE_RANGES = {
    1: [1, 4], 2: [5, 7], 3: [8, 9], 4: [10, 11], 5: [12, 13], 6: [14, 14],
  };

  function placeWorkerActionMap(state) {
    const m = new Map();
    for (const a of state.legal_actions) {
      if (a.type === 'PlaceWorker') m.set(a.params.space, a);
    }
    return m;
  }

  // Mirror of play.py's _placeworker_sort_key — permanent spaces in their
  // display order, then stage cards by round_revealed, then space id.
  function placeworkerSortKey(action, spacesById) {
    const sid = action.params.space;
    const i = PERMANENT_ORDER.indexOf(sid);
    if (i >= 0) return [0, i, sid];
    const sp = spacesById.get(sid);
    return [1, sp ? sp.round_revealed : 999, sid];
  }

  function comparePlaceworkers(a, b, spacesById) {
    const ka = placeworkerSortKey(a, spacesById);
    const kb = placeworkerSortKey(b, spacesById);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    if (ka[1] !== kb[1]) return ka[1] - kb[1];
    return ka[2].localeCompare(kb[2]);
  }

  function renderActionBoard(state) {
    const container = document.getElementById('action-board');
    container.innerHTML = '';

    const pwMap = placeWorkerActionMap(state);
    const spacesById = new Map(state.board.spaces.map((s) => [s.id, s]));

    const emitGroup = (label) => container.appendChild(
      el('div', { class: 'space-group-label' }, label));

    const emitSpace = (sid) => {
      const sp = spacesById.get(sid);
      if (!sp || !sp.is_revealed) return;
      const legal = pwMap.get(sid);
      const occupied = (sp.workers[0] + sp.workers[1]) > 0;
      const cls = [
        'space-card',
        legal ? 'clickable' : '',
        occupied ? 'occupied' : '',
      ].filter(Boolean).join(' ');
      const card = el('div', { class: cls });
      const left = el('div', {},
        el('span', { class: 'space-name' }, sp.name),
        sp.accumulation_text
          ? el('span', { class: 'space-accum' }, ` (${sp.accumulation_text})`)
          : null,
      );
      const workers = el('div', { class: 'space-workers' });
      for (let p = 0; p < 2; p++) {
        if (sp.workers[p] > 0) {
          const token = el('span',
            { class: `worker-token p${p}` },
            sp.workers[p] > 1 ? `${sp.workers[p]}` : '');
          workers.appendChild(token);
        }
      }
      card.appendChild(left);
      card.appendChild(workers);
      if (legal) {
        card.addEventListener('click', () => submitAction(legal.index));
      }
      container.appendChild(card);
    };

    emitGroup('permanent');
    for (const sid of PERMANENT_ORDER) emitSpace(sid);

    for (let stage = 1; stage <= 6; stage++) {
      const [first] = STAGE_RANGES[stage];
      if (state.round_number < first) break;
      emitGroup(`stage ${stage}`);
      // Spaces revealed in this stage so far, sorted by round_revealed.
      const stageSpaces = state.board.spaces
        .filter((s) => s.stage === stage && s.is_revealed)
        .sort((a, b) => a.round_revealed - b.round_revealed);
      for (const s of stageSpaces) emitSpace(s.id);
    }
  }

  // -------- major improvements --------

  const MAJOR_NAMES = [
    'Fireplace(2c)', 'Fireplace(3c)',
    'CookingHearth(4c)', 'CookingHearth(5c)',
    'Well', 'ClayOven', 'StoneOven',
    'Joinery', 'Pottery', 'Basketmaker',
  ];

  function renderMajorBoard(state) {
    const container = document.getElementById('major-board');
    container.innerHTML = '';
    const owners = state.board.major_owners;
    // Map major_idx -> CommitBuildMajor actions (Cooking Hearths may have several).
    const buildActions = new Map();
    for (const a of state.legal_actions) {
      if (a.type === 'CommitBuildMajor') {
        const idx = a.params.major_idx;
        if (!buildActions.has(idx)) buildActions.set(idx, []);
        buildActions.get(idx).push(a);
      }
    }
    for (let i = 0; i < 10; i++) {
      const owner = owners[i];
      let cls = 'major-card';
      if (owner === 0) cls += ' owned-p0';
      else if (owner === 1) cls += ' owned-p1';
      else cls += ' supply';
      const card = el('div', { class: cls });
      const label = `${i}: ${MAJOR_NAMES[i]}`;
      const tag = owner === null ? 'supply' : `P${owner}`;
      card.appendChild(el('span', {}, `${label} (${tag})`));
      const opts = buildActions.get(i);
      if (opts && opts.length) {
        for (const a of opts) {
          // Show short button for each variant (esp. CookingHearth return-fp).
          const ret = a.params.return_fireplace_idx;
          const lbl = ret === null || ret === undefined ? 'buy' : `buy (return Fp${ret})`;
          const btn = el('button',
            { class: 'action-btn', onclick: () => submitAction(a.index) },
            lbl);
          btn.style.marginLeft = '4px';
          card.appendChild(btn);
        }
      }
      container.appendChild(card);
    }
  }

  // -------- player panels --------

  // Build a "Label: …" summary row by splicing alternating plain text and
  // bolded tokens. Each entry in `parts` is either a string (rendered plain)
  // or an object {bold: <value>} (rendered in .val style). The section label
  // itself stays unbolded. This lets each section pick its own layout —
  // compact "0w" tokens, name-then-value pairs, a slash-separated tail, etc.
  function buildRow(label, parts) {
    const div = el('div', { class: 'summary-section' });
    div.appendChild(el('span', { class: 'label' }, label + ': '));
    for (const p of parts) {
      if (typeof p === 'string') {
        div.appendChild(document.createTextNode(p));
      } else if (p && p.bold !== undefined) {
        div.appendChild(el('span', { class: 'val' }, String(p.bold)));
      }
    }
    return div;
  }

  function buildFooterLine(p) {
    const div = el('div', { class: 'summary-footer' });
    // House / Begging / Score on the left, Built totals on the right — all
    // separated by " | ", rendered as one continuous line.
    const parts = [
      ['House',         p.house_material],
      ['Begging',       p.begging_markers],
      ['Score',         p.interim_score],
      ['Fences Built',  `${p.fences_built}/${p.fences_total}`],
      ['Stables Built', `${p.stables_built}/${p.stables_total}`],
    ];
    parts.forEach(([label, value], i) => {
      if (i > 0) div.appendChild(el('span', { class: 'sep' }, '  |  '));
      div.appendChild(el('span', { class: 'label' }, label + ': '));
      div.appendChild(el('span', { class: 'val' }, String(value)));
    });
    return div;
  }

  function renderPlayerPanel(state, idx) {
    const p = state.players[idx];
    const headerEl = document.getElementById(`p${idx}-header`);
    const summaryEl = document.getElementById(`p${idx}-summary`);
    const farmEl = document.getElementById(`p${idx}-farmyard-container`);
    const impEl = document.getElementById(`p${idx}-improvements`);
    const colEl = document.getElementById(`col-p${idx}`);

    // Header tags
    headerEl.innerHTML = '';
    headerEl.appendChild(document.createTextNode(`P${idx}`));
    if (p.is_sp) headerEl.appendChild(el('span', { class: 'sp-tag' }, 'SP'));
    if (p.is_decider)
      headerEl.appendChild(el('span', { class: 'decider-tag' }, 'deciding'));
    // Seat-type tag (friendly label — see BACKEND_TO_LABEL above) so it's
    // visible whose brain is in this seat. The CSS dataset still uses the
    // raw backend value for any per-type styling.
    const seat = (state.seats && state.seats[idx]) || 'human';
    headerEl.appendChild(el('span', { class: 'seat-tag', dataset: { seat } },
                            backendToLabel(seat)));

    colEl.classList.toggle('active-decider', p.is_decider && !state.game_over);
    colEl.classList.toggle('dim', !p.is_decider && !state.game_over);

    // Summary grid (compact form — keeps the panel from overflowing):
    //
    //   ┌────────── Resources ─────────┬──────── Crops ─────────────┐
    //   │ Nw, Nc, Nr, Ns               │ Grain N, Veg N | Food n/d  │
    //   ├────────── Animals ───────────┼──────── People ────────────┤
    //   │ Sheep N, Boar N, Cattle N    │ Home N, Newborns N, Total N│
    //   ├───────────────────────────────────────────────────────────┤
    //   │ House: X | Begging: N | Score: N |                        │
    //   │   Fences Built: N/15 | Stables Built: N/4                 │
    //   └───────────────────────────────────────────────────────────┘
    //
    // Convention: section labels and sub-names render in normal weight; only
    // the numeric values are bold. Resources tokens fuse number+unit (e.g.
    // "5w") and bold the whole token as one. Food denominator is
    // harvest-accurate: 2*adults + 1*newborns == 2*people_total - newborns.
    const r = p.resources, a = p.animals;
    const foodDenom = 2 * p.people_total - p.newborns;
    summaryEl.innerHTML = '';
    summaryEl.appendChild(buildRow('Resources', [
      { bold: `${r.wood}w` },  ', ',
      { bold: `${r.clay}c` },  ', ',
      { bold: `${r.reed}r` },  ', ',
      { bold: `${r.stone}s` },
    ]));
    summaryEl.appendChild(buildRow('Crops', [
      'Grain ',   { bold: r.grain }, ', ',
      'Veg ',     { bold: r.veg },
      ' | Food ', { bold: `${r.food}/${foodDenom}` },
    ]));
    summaryEl.appendChild(buildRow('Animals', [
      'Sheep ',  { bold: a.sheep },  ', ',
      'Boar ',   { bold: a.boar },   ', ',
      'Cattle ', { bold: a.cattle },
    ]));
    summaryEl.appendChild(buildRow('People', [
      'Home ',     { bold: p.people_home }, ', ',
      'Newborns ', { bold: p.newborns },    ', ',
      'Total ',    { bold: p.people_total },
    ]));
    summaryEl.appendChild(buildFooterLine(p));

    // Farmyard SVG. Only the decider's farmyard is interactive, and only for
    // pendings whose legal actions are cell / cell_set hinted.
    farmEl.innerHTML = '';
    const cellActions = (p.is_decider && !state.game_over)
      ? gatherCellActions(state)
      : { single: [], cellSet: [] };
    const isInteractive = cellActions.single.length > 0 || cellActions.cellSet.length > 0;
    const clickable = isInteractive ? clickableCellsFor(cellActions, cellSelection) : new Set();
    const selectionForRender = (isInteractive && cellActions.cellSet.length)
      ? cellSelection : new Set();
    farmEl.appendChild(renderFarmyardSVG(p.farmyard, {
      clickable,
      selection: selectionForRender,
      onCellClick: (r, c) => onFarmyardCellClick(r, c, cellActions),
    }));
    if (isInteractive && cellActions.cellSet.length && cellSelection.size > 0) {
      const hint = el('div', { class: 'cell-select-hint' });
      hint.appendChild(document.createTextNode(
        `pasture selection: ${cellSelection.size} cell(s) — `));
      const exact = exactPastureMatch(cellActions);
      if (exact) {
        hint.appendChild(el('button',
          { class: 'action-btn small confirm',
            onclick: () => confirmPastureSelection(cellActions) },
          'confirm'));
        hint.appendChild(document.createTextNode(' '));
      }
      hint.appendChild(el('button',
        { class: 'action-btn small',
          onclick: () => { cellSelection = new Set(); render(currentState); } },
        'clear'));
      farmEl.appendChild(hint);
    } else if (isInteractive) {
      const hint = el('div', { class: 'cell-select-hint' });
      const what = cellActions.cellSet.length
        ? 'Click cells to build a pasture'
        : (cellActions.single.length === 1
            ? 'Click a highlighted cell'
            : 'Click any highlighted cell');
      hint.textContent = what;
      farmEl.appendChild(hint);
    }

    // Improvements
    impEl.innerHTML = '';
    const majorsLine = p.majors.length
      ? p.majors.map((m) => `${m.idx}:${m.name}`).join(', ')
      : '—';
    const minorsLine = p.minors.length ? p.minors.join(', ') : '—';
    impEl.appendChild(el('div', { class: 'improv-list' },
      el('div', { class: 'row' },
        el('span', { class: 'label' }, 'Majors: '),
        el('span', {}, majorsLine)),
      el('div', { class: 'row' },
        el('span', { class: 'label' }, 'Minors: '),
        el('span', {}, minorsLine)),
    ));
  }

  // -------- cell-selection helpers --------
  //
  // Three commit types map to a single cell on the active player's farmyard:
  //   CommitPlow, CommitBuildStable, CommitBuildRoom    (ui_hint = "cell")
  // One commit type maps to a multi-cell set:
  //   CommitBuildPasture                                (ui_hint = "cell_set")
  // At any moment only one of these types is legal (different pendings), so
  // these helpers don't need to disambiguate by both — they just check.

  function cellKey(r, c) { return r + ',' + c; }

  function actionCellSet(a) {
    return new Set(a.params.cells.map((rc) => cellKey(rc[0], rc[1])));
  }
  function isSubset(small, big) {
    for (const v of small) if (!big.has(v)) return false;
    return true;
  }
  function setsEqual(a, b) {
    if (a.size !== b.size) return false;
    return isSubset(a, b);
  }

  function gatherCellActions(state) {
    // Only the decider's farmyard is interactive.
    const out = { single: [], cellSet: [] };
    for (const a of state.legal_actions) {
      if (a.ui_hint === 'cell') out.single.push(a);
      else if (a.ui_hint === 'cell_set') out.cellSet.push(a);
    }
    return out;
  }

  function clickableCellsFor(cellActions, selection) {
    // Returns a Set<"r,c"> of cells that should be clickable right now.
    const out = new Set();
    for (const a of cellActions.single) {
      out.add(cellKey(a.params.row, a.params.col));
    }
    if (cellActions.cellSet.length) {
      // Allow toggling-off currently-selected cells; allow adding any cell that
      // would keep the selection a subset of at least one legal pasture.
      for (const v of selection) out.add(v);
      for (const a of cellActions.cellSet) {
        const cs = actionCellSet(a);
        if (!isSubset(selection, cs)) continue;  // selection already incompatible
        for (const v of cs) out.add(v);
      }
    }
    return out;
  }

  function onFarmyardCellClick(r, c, cellActions) {
    // Single-cell commit: direct submit.
    if (cellActions.single.length) {
      const match = cellActions.single.find(
        (a) => a.params.row === r && a.params.col === c);
      if (match) submitAction(match.index);
      return;
    }
    // Multi-cell pasture: toggle and possibly auto-submit.
    if (cellActions.cellSet.length) {
      const key = cellKey(r, c);
      const next = new Set(cellSelection);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
        // Only commit the add if some legal pasture still contains the new set.
        const reachable = cellActions.cellSet.some(
          (a) => isSubset(next, actionCellSet(a)));
        if (!reachable) return;
      }
      cellSelection = next;
      // Auto-submit only when no further extension is legal — otherwise the
      // user might be mid-build of a larger pasture and we'd commit too early.
      if (tryAutoSubmitPasture(cellActions)) return;
      if (currentState) render(currentState);
    }
  }

  function exactPastureMatch(cellActions) {
    return cellActions.cellSet.find(
      (a) => setsEqual(cellSelection, actionCellSet(a)));
  }

  function pastureCanExtend(cellActions) {
    return cellActions.cellSet.some((a) => {
      const cs = actionCellSet(a);
      return cs.size > cellSelection.size && isSubset(cellSelection, cs);
    });
  }

  function tryAutoSubmitPasture(cellActions) {
    const exact = exactPastureMatch(cellActions);
    if (!exact) return false;
    if (pastureCanExtend(cellActions)) return false;
    const idx = exact.index;
    cellSelection = new Set();
    submitAction(idx);
    return true;
  }

  function confirmPastureSelection(cellActions) {
    const exact = exactPastureMatch(cellActions);
    if (!exact) return;
    const idx = exact.index;
    cellSelection = new Set();
    submitAction(idx);
  }

  // -------- farmyard SVG --------

  const CELL_W = 60;
  const CELL_H = 50;
  const PAD = 10;
  const ROWS = 3, COLS = 5;

  // Crop-token colors. Yellow for grain, orange for vegetables — sized to
  // match the digit they sit next to (r=5 ≈ the 11px digit's visual height).
  const GRAIN_COLOR = '#E8C547';
  const VEG_COLOR   = '#E67E22';

  function appendCellGlyph(svg, x, y, cell) {
    const cx = x + CELL_W / 2;
    const cy = y + CELL_H / 2;
    const t = cell.type;
    if (t === 'ROOM') {
      svg.appendChild(svgEl('text', {
        x: cx, y: cy + 4, 'text-anchor': 'middle', class: 'cell-label',
      })).textContent = 'R';
      return;
    }
    if (t === 'STABLE') {
      // 3× the default cell-label size. Baseline offset scales with font-size
      // (~1/3 of em) to keep the glyph centered vertically.
      svg.appendChild(svgEl('text', {
        x: cx, y: cy + 11, 'text-anchor': 'middle',
        class: 'cell-label dark stable-glyph',
      })).textContent = '⌂';
      return;
    }
    if (t === 'FIELD') {
      const count = cell.grain > 0 ? cell.grain
                  : cell.veg   > 0 ? cell.veg
                  : 0;
      if (!count) {
        svg.appendChild(svgEl('text', {
          x: cx, y: cy + 4, 'text-anchor': 'middle', class: 'cell-label',
        })).textContent = 'F';
        return;
      }
      const color = cell.grain > 0 ? GRAIN_COLOR : VEG_COLOR;
      // Digit on the left of cell center; colored disc on the right.
      svg.appendChild(svgEl('text', {
        x: cx - 6, y: cy + 4, 'text-anchor': 'middle', class: 'cell-label',
      })).textContent = String(count);
      svg.appendChild(svgEl('circle', {
        cx: cx + 7, cy: cy, r: 5,
        fill: color, stroke: '#3A2D14', 'stroke-width': 1,
      }));
      return;
    }
  }

  function renderFarmyardSVG(farmyard, opts) {
    opts = opts || {};
    const clickable = opts.clickable || new Set();
    const selection = opts.selection || new Set();
    const onCellClick = opts.onCellClick || (() => {});
    const w = COLS * CELL_W + 2 * PAD;
    const h = ROWS * CELL_H + 2 * PAD;
    const svg = svgEl('svg', {
      class: 'farmyard-svg',
      width: w, height: h,
      viewBox: `0 0 ${w} ${h}`,
    });

    // Cells
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const cell = farmyard.cells[r][c];
        const x = PAD + c * CELL_W;
        const y = PAD + r * CELL_H;
        const t = cell.type;
        let cls = 'cell-empty';
        if (t === 'ROOM') cls = 'cell-room-wood';  // material per-player; simplify
        else if (t === 'FIELD') cls = 'cell-field';
        else if (t === 'STABLE') cls = 'cell-stable';
        svg.appendChild(svgEl('rect', {
          x, y, width: CELL_W, height: CELL_H, class: cls,
        }));
        appendCellGlyph(svg, x, y, cell);
      }
    }

    // Pasture overlay (subtle wash + capacity label).
    for (const past of farmyard.pastures) {
      for (const [r, c] of past.cells) {
        svg.appendChild(svgEl('rect', {
          x: PAD + c * CELL_W, y: PAD + r * CELL_H,
          width: CELL_W, height: CELL_H,
          class: 'pasture-overlay',
        }));
      }
      // Capacity label in upper-left of the topmost-leftmost cell.
      const [r0, c0] = past.cells[0];
      const lbl = svgEl('text', {
        x: PAD + c0 * CELL_W + 4, y: PAD + r0 * CELL_H + 11,
        'text-anchor': 'start',
        class: 'cell-label dark',
        'font-size': '10',
      });
      lbl.textContent = `cap${past.capacity}` +
        (past.fenced_stables ? `|${past.fenced_stables}fS` : '');
      svg.appendChild(lbl);
    }

    // Clickable / selected overlays. Drawn before fences so fences render on
    // top, and the overlay rect captures clicks on the cell interior.
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const key = cellKey(r, c);
        const isSelected = selection.has(key);
        const isClickable = clickable.has(key);
        if (!isSelected && !isClickable) continue;
        const rect = svgEl('rect', {
          x: PAD + c * CELL_W, y: PAD + r * CELL_H,
          width: CELL_W, height: CELL_H,
          class: 'cell-overlay' + (isSelected ? ' selected' : ' clickable'),
        });
        rect.addEventListener('click', () => onCellClick(r, c));
        svg.appendChild(rect);
      }
    }

    // Horizontal fences (4 rows x 5 cols)
    for (let r = 0; r <= ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const on = farmyard.h_fences[r][c];
        const isBoundary = (r === 0 || r === ROWS);
        const x1 = PAD + c * CELL_W;
        const x2 = x1 + CELL_W;
        const y = PAD + r * CELL_H;
        const cls = on ? 'fence-on'
          : `fence-off${isBoundary ? ' boundary' : ''}`;
        svg.appendChild(svgEl('line', {
          x1, x2, y1: y, y2: y, class: cls,
        }));
      }
    }
    // Vertical fences (3 rows x 6 cols)
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c <= COLS; c++) {
        const on = farmyard.v_fences[r][c];
        const isBoundary = (c === 0 || c === COLS);
        const y1 = PAD + r * CELL_H;
        const y2 = y1 + CELL_H;
        const x = PAD + c * CELL_W;
        const cls = on ? 'fence-on'
          : `fence-off${isBoundary ? ' boundary' : ''}`;
        svg.appendChild(svgEl('line', {
          x1: x, x2: x, y1, y2, class: cls,
        }));
      }
    }

    return svg;
  }

  // -------- decision panel --------

  function isAiDecider(state) {
    if (!state || state.game_over) return false;
    const seat = (state.seats && state.seats[state.decider]) || 'human';
    return seat !== 'human';
  }

  function renderDecisionPanel(state) {
    const breadcrumb = document.getElementById('pending-breadcrumb');
    const banner = document.getElementById('decider-banner');
    const menu = document.getElementById('action-menu');

    renderPendingBreadcrumb(breadcrumb, state);

    const deciderSeat = state.game_over
      ? null
      : (state.seats && state.seats[state.decider]) || 'human';
    if (state.game_over) {
      banner.textContent = 'Game over — see scoring below.';
    } else if (deciderSeat === 'human') {
      banner.textContent = `Decider: P${state.decider} (human)`;
    } else {
      banner.textContent = `Decider: P${state.decider} (${deciderSeat}) — press Enter or click Advance to play next move`;
    }

    menu.innerHTML = '';

    if (state.game_over) {
      menu.appendChild(el('div', {}, 'No legal actions.'));
      return;
    }

    // AI-decider mode: show an "Advance" button instead of (or in addition
    // to) the legal-actions menu. Clicking it (or pressing Enter) fires
    // /api/step_ai, which advances exactly one move. The legal-actions
    // list is still rendered below for inspection — the user can see what
    // the agent was choosing among. Clicking a legal action in AI mode
    // would be rejected by /api/step ("not a human's turn") so we hide
    // the action buttons by short-circuiting after rendering the Advance
    // bar.
    if (deciderSeat !== 'human') {
      const advanceBar = el('div', { class: 'advance-bar' });
      advanceBar.appendChild(el(
        'button',
        { class: 'advance-btn', onclick: () => stepAI() },
        `Advance (P${state.decider}: ${deciderSeat})`,
      ));
      advanceBar.appendChild(el(
        'span', { class: 'advance-hint' },
        `${state.legal_actions.length} legal action${state.legal_actions.length === 1 ? '' : 's'} available — agent will pick one.`,
      ));
      menu.appendChild(advanceBar);
      // Don't render the action buttons (would be rejected by backend).
      return;
    }

    // Group actions by type so the menu reads cleanly.
    const groups = new Map();
    for (const a of state.legal_actions) {
      const key = a.type;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(a);
    }

    // PlaceWorker → board click; CommitBuildMajor → major-board click;
    // cell / cell_set commits → farmyard click. We still surface them all
    // in the menu as an alternate path, but collapse large cell / cell_set
    // groups since the farmyard click is the intended UX.
    const ORDER = [
      'ChooseSubAction',
      'CommitPlow', 'CommitSow', 'CommitBake',
      'CommitBuildRoom', 'CommitBuildStable',
      'CommitBuildPasture',
      'CommitRenovate',
      'CommitAccommodate', 'CommitBreed',
      'CommitConvert', 'CommitHarvestConversion',
      'FireTrigger',
      'PlaceWorker',
      'CommitBuildMajor',
      'Stop',
    ];

    // Sort PlaceWorker options to match the action board order.
    if (groups.has('PlaceWorker')) {
      const spacesById = new Map(state.board.spaces.map((s) => [s.id, s]));
      groups.get('PlaceWorker').sort(
        (a, b) => comparePlaceworkers(a, b, spacesById));
    }

    // Threshold above which `cell` / `cell_set` commits are collapsed into a
    // hint pointing the user at the farmyard click affordance. Below it,
    // show buttons (small option count is fine).
    const CELL_COLLAPSE_THRESHOLD = 6;

    let anyButtons = false;
    for (const key of ORDER) {
      const opts = groups.get(key);
      if (!opts) continue;

      const hint = opts[0].ui_hint;
      const isCellGroup = hint === 'cell' || hint === 'cell_set';
      const collapse = isCellGroup && opts.length > CELL_COLLAPSE_THRESHOLD;

      menu.appendChild(el('div', { class: 'action-group-header' },
        `${key} (${opts.length})`));

      if (collapse) {
        const msg = hint === 'cell_set'
          ? `${opts.length} pasture shapes legal — click cells on the farmyard, then Confirm.`
          : `${opts.length} cells legal — click a highlighted cell on the farmyard.`;
        menu.appendChild(el('div', { class: 'cell-collapse-hint' }, msg));
        anyButtons = true;
        continue;
      }

      for (const a of opts) {
        const btn = el('button',
          { class: 'action-btn' + (key === 'Stop' ? ' stop' : ''),
            onclick: () => submitAction(a.index) },
          a.display);
        menu.appendChild(btn);
        anyButtons = true;
      }
    }

    if (!anyButtons) {
      menu.appendChild(el('div', {}, '(no legal actions)'));
    }
  }

  function renderPendingBreadcrumb(container, state) {
    container.innerHTML = '';
    if (!state.pending_stack.length) {
      container.textContent = 'No pending — choose a worker placement.';
      return;
    }
    const chain = state.pending_stack
      .map((p) => p.type.replace(/^Pending/, ''))
      .join(' > ');
    container.appendChild(document.createTextNode(`Pending: ${chain}`));
    const detail = state.pending_stack[state.pending_stack.length - 1].details_text;
    if (detail) {
      container.appendChild(document.createTextNode(' '));
      container.appendChild(el('span', { class: 'pending-detail' }, `(${detail})`));
    }
  }

  // -------- round log --------

  function renderRoundLog(state) {
    const container = document.getElementById('round-log');
    container.innerHTML = '';
    for (const e of state.round_log) {
      const classes = ['log-entry'];
      if (e.is_carryover) classes.push('carryover');
      if (e.in_progress)  classes.push('in-progress');
      const div = el('div', { class: classes.join(' ') });
      const prefix = e.is_carryover ? `(R${e.round}) ` : '';
      div.appendChild(document.createTextNode(prefix));
      div.appendChild(el('span', { class: `pidx-${e.decider}` }, `P${e.decider}`));
      div.appendChild(document.createTextNode(` ${e.text}` +
        (e.in_progress ? ' …' : '')));
      container.appendChild(div);
    }
    // Scroll to bottom on update.
    container.scrollTop = container.scrollHeight;
  }

  // -------- game over --------

  function renderGameOver(state) {
    const modal = document.getElementById('game-over-modal');
    const content = document.getElementById('game-over-content');
    if (!state.game_over || !state.scoring) {
      modal.classList.add('hidden');
      return;
    }
    const sc = state.scoring;
    const tbl = el('table');
    tbl.appendChild(el('thead', {}, el('tr', {},
      el('th', {}, ''), el('th', {}, 'P0'), el('th', {}, 'P1'))));
    const tbody = el('tbody');
    for (const r of sc.rows) {
      tbody.appendChild(el('tr', {},
        el('td', {}, r.label),
        el('td', {}, String(r.p0)),
        el('td', {}, String(r.p1))));
    }
    tbody.appendChild(el('tr', { class: 'total' },
      el('td', {}, 'TOTAL'),
      el('td', {}, String(sc.p0_total)),
      el('td', {}, String(sc.p1_total))));
    tbl.appendChild(tbody);
    content.innerHTML = '';
    content.appendChild(tbl);
    content.appendChild(el('div', { class: 'winner-note' }, sc.note));
    modal.classList.remove('hidden');
  }

  // ---------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('reset-btn').addEventListener('click', resetGame);
    // Download-trace button: navigate to /api/trace, which is served with a
    // Content-Disposition: attachment header so the browser saves it as
    // `agricola-trace-seed<seed>.json` instead of rendering it inline.
    document.getElementById('download-trace-btn').addEventListener('click', () => {
      window.location.href = '/api/trace';
    });
    document.getElementById('game-over-close').addEventListener('click', () => {
      document.getElementById('game-over-modal').classList.add('hidden');
    });
    const fastCb = document.getElementById('fast-mode-toggle');
    fastCb.checked = fastMode;
    fastCb.addEventListener('change', (e) => setFastMode(e.target.checked));
    // Global Enter-key handler: when an AI is on the clock, Enter advances
    // one move. Ignored when focus is in a text input (so it doesn't fight
    // the seed prompt or future form inputs). Also ignored on the game-over
    // modal (no AI moves to take).
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const modal = document.getElementById('game-over-modal');
      if (modal && !modal.classList.contains('hidden')) return;
      if (isAiDecider(currentState)) {
        e.preventDefault();
        stepAI();
      }
    });
    // Get initial state (fallback in case SSE is slow).
    fetch('/api/state').then((r) => r.json()).then((s) => {
      if (!currentState) {
        currentState = s;
        render(s);
      }
    }).catch(() => {});
    connectSSE();
  });
})();
