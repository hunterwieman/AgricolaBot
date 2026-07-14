// AgricolaBot Web UI — vanilla JS, single-channel request/response.
//
// There is NO server push. Every state-changing request (place a worker, a
// sub-action, undo, confirm, a toggle, new game) returns the full resulting
// GameState in its HTTP response, and the page renders from that. This single
// source of truth is what makes the UI immune to the out-of-order / stale
// rendering bugs a second (push) channel caused.

(function () {
  'use strict';

  // ---------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------

  let currentState = null;
  // Selection state for multi-cell pasture build. Reset on every state push.
  // Stored as Set<"r,c">.
  let cellSelection = new Set();
  // Set of card_ids that have a legal "play card" action (ui_hint:"card") in
  // the current state — used to highlight the matching card in the hand panel.
  // Recomputed in render() from the current legal actions.
  let currentPlayableCardIds = new Set();

  // ---- Draft modal selection state ----
  // Which card ids are currently selected in the draft picker (null = nothing).
  // Reset when a new pool is shown (different player / round).
  let _draftSelOcc = null;  // card_id string or null
  let _draftSelMin = null;  // card_id string or null

  // ---- "Show analysis" overlay state (frontend-only; does NOT POST) ----
  // When on, each human decision triggers a background /api/analyze call; the
  // returned per-move {visits, q} are overlaid on the board spaces and the
  // sub-action buttons. Read-only — never blocks the human's move.
  let analysisOn = false;
  // Keyed by actionKey(type, params) -> {visits, q}.
  let analysisByKey = new Map();
  // What the analysis q values mean — the value head's training target, from
  // /api/analyze's `value_target`: "margin" (q is points of expected score
  // diff), "outcome" (q is expected win/draw/loss value in [-1,1]), or "mix"
  // (q is the RAW unitless margin/outcome blend the mix-leaf bot backs up).
  // Labels the badge so the number is never shown without its unit.
  let analysisUnit = 'margin';
  // Monotonic generation counter: each adopted state bumps it. An in-flight
  // /api/analyze response is discarded if a newer state has arrived since it
  // was launched (so stale analysis never overwrites the current overlay).
  let analysisGen = 0;
  // Exploration constant for the analysis search (sent to /api/analyze).
  // Default 1.0 = the value the bot plays at. Higher explores wider, lower
  // searches deeper. Tunable in the analysis control row; persisted.
  let analysisCuct = parseFloat(localStorage.getItem('agricola.analysisCuct')) || 1.0;
  // Which value head the analysis evaluates with — independent of how the bot
  // plays: "margin" (points of expected score diff), "outcome" (win/draw/loss
  // in [-1,1]), or "mix" (the α-blend of the two). Default "mix" = the
  // deployed bot's leaf. Tunable in the analysis control row; persisted.
  let analysisLeafMode = localStorage.getItem('agricola.analysisLeafMode') || 'mix';
  // Blend weight α for the "mix" leaf (α·margin + (1−α)·outcome). Default 0.9
  // = the deployed bot's value. Only used when analysisLeafMode === 'mix'.
  let analysisMixAlpha = parseFloat(localStorage.getItem('agricola.analysisMixAlpha'));
  if (!(analysisMixAlpha >= 0 && analysisMixAlpha <= 1)) analysisMixAlpha = 0.9;
  // Search budget (sims/move) for the analysis search, independent of the
  // game's bot budget. null until first set — on first use it inherits the
  // current game's sims (see ensureAnalysisSims); thereafter persisted.
  let analysisSims = (() => {
    const v = parseInt(localStorage.getItem('agricola.analysisSims'), 10);
    return (Number.isFinite(v) && v >= 1) ? v : null;
  })();

  // Render whatever the server just returned. The server is authoritative; a
  // response always carries the current state, so we simply adopt it. There is
  // no client-side versioning or "is this newer?" check — requests are
  // serialized (one in flight at a time, see `inputLocked`), so responses
  // can't arrive out of order, and the latest response is the truth.
  function applyState(state) {
    if (!state) return;
    checkSessionContinuity(state);
    setConnState(true);
    currentState = state;
    cellSelection = new Set();  // a server step happened → drop partial selection
    // A new state invalidates any in-flight / displayed analysis: bump the
    // generation (so a late /api/analyze response is discarded) and clear the
    // overlay. If analysis is on and it's a human's turn, kick off a fresh
    // background fetch (NOT awaited — must not block render or clicking).
    analysisGen++;
    analysisByKey.clear();
    if (analysisOn && isHumanTurn(state)) {
      fetchAnalysis(analysisGen);
    }
    render(currentState);
  }

  // Detect that the game we were playing is gone. The server stamps each Session
  // with a random `session_id`; a user "New game" reuses the same Session (stable
  // id), but a server restart/redeploy (in-memory state, no datastore) or an
  // eviction builds a NEW Session with a NEW id. We remember the last id in
  // localStorage; when an incoming state carries a different one, the prior game
  // was lost and the server handed us a fresh board — tell the user instead of
  // silently jumping them to a different round-1 game.
  function checkSessionContinuity(state) {
    const id = state && state.session_id;
    if (!id) return;  // older server without the field — nothing to compare
    let prev = null;
    try { prev = localStorage.getItem('agricola.sessionId'); } catch (e) { /* private mode */ }
    try { localStorage.setItem('agricola.sessionId', id); } catch (e) { /* ignore */ }
    if (prev && prev !== id) showSessionResetBanner();
  }

  function showSessionResetBanner() {
    const banner = document.getElementById('session-banner');
    if (banner) banner.classList.remove('hidden');
  }

  // Is the current decider a human seat? (Used to gate the analysis fetch.)
  function isHumanTurn(state) {
    if (!state || state.game_over || state.decider == null) return false;
    return state.seats && state.seats[state.decider] === 'human';
  }

  // Canonical key for an action — the SAME on both sides of the lookup (when
  // storing a /api/analyze child and when matching a legal action / button).
  // Sorting the keys makes it order-independent. The C++ analyze params match
  // the frontend legal_action params field-for-field (PlaceWorker → {space},
  // ChooseSubAction → {name}, the Commit* family → their numeric/idx fields).
  function actionKey(type, params) {
    params = params || {};
    return type + '|' + JSON.stringify(params, Object.keys(params).sort());
  }

  // Format an analysis badge: the value head's unit descriptor ("margin" /
  // "outcome" / "mix"), then the signed q (good-for-the-human), then the visit
  // count N. For margin/outcome q is in the head's natural units (the backend
  // multiplies the normalized Q by value_scale); margin reads in points (1
  // decimal), outcome lives in [-1,1] (2 decimals). For "mix" q is the RAW
  // tree Q — a unitless margin/outcome blend (NOT scaled), shown to 2 decimals.
  // e.g. "margin +1.2 · 80", "outcome +0.31 · 80", or "mix +0.34 · 80".
  function analysisBadgeText(info) {
    const dp = analysisUnit === 'margin' ? 1 : 2;
    const q = info.q >= 0 ? `+${info.q.toFixed(dp)}` : info.q.toFixed(dp);
    return `${analysisUnit} ${q} · ${info.visits}`;
  }

  // Background fetch of the AI's per-move analysis for the current human
  // decision. Read-only: does NOT go through inputLocked (it must never block
  // a move). If a newer state has been adopted since this call was launched
  // (gen mismatch), the response is discarded. Errors are ignored silently.
  async function fetchAnalysis(gen) {
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          c_uct: analysisCuct,
          sims: ensureAnalysisSims(),
          leaf_mode: analysisLeafMode,
          mix_alpha: analysisMixAlpha,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (gen !== analysisGen) return;  // a newer state arrived — discard
      if (!data || !data.ok || !Array.isArray(data.children)) return;
      analysisUnit = (data.value_target === 'outcome' || data.value_target === 'mix')
        ? data.value_target : 'margin';
      const map = new Map();
      for (const child of data.children) {
        map.set(actionKey(child.type, child.params),
                { visits: child.visits, q: child.q });
      }
      analysisByKey = map;
      if (currentState) render(currentState);
    } catch (err) {
      // Read-only background call; ignore failures.
    }
  }

  // The single serialization guard for EVERY state-changing request — moves,
  // sub-actions, undo, confirm, AI-step, toggles, and new game. Only one
  // request is in flight at a time, so the server processes them in a defined
  // order and their responses can't arrive out of order. A click while one is in
  // flight is dropped. While set, we mark the body so CSS shows a "click
  // registered" wait cursor.
  let inputLocked = false;
  function setInputLocked(locked) {
    inputLocked = locked;
    document.body.classList.toggle('is-submitting', locked);
  }

  // Fast mode: when enabled, the SERVER auto-applies any human-singleton
  // decision in the same lock-held window where it already auto-applies AI
  // moves. These two toggle flags are SERVER-AUTHORITATIVE: render() syncs
  // them (and the checkboxes) from each state payload's fast_mode /
  // confirm_mode. The handlers just POST the desired value and render the
  // response. (They default off each page load.)
  let fastMode = false;
  // Confirm-turn mode: when on, the SERVER pauses after each completed human
  // turn (state.awaiting_confirm) so the player can Confirm (let the AI reply)
  // or Undo. Forced/singleton turns are not paused.
  let confirmMode = false;

  // Connection indicator. There is no push channel: the page is driven purely
  // by request/response (every action and toggle returns the full resulting
  // state). So "online" just reflects whether the last request succeeded.
  function setConnState(connected) {
    const el = document.getElementById('connection-state');
    if (!el) return;
    el.textContent = connected ? 'online' : 'offline';
    el.className = connected ? 'conn-connected' : 'conn-disconnected';
  }

  // ---------------------------------------------------------------------
  // Action submission
  // ---------------------------------------------------------------------

  async function submitAction(actionIndex) {
    if (inputLocked) return;  // block rapid re-entry during the request round-trip
    setInputLocked(true);
    try {
      const res = await fetch('/api/step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_index: actionIndex }),
      });
      const data = await res.json().catch(() => ({}));
      // The response carries the full resulting state (including the bot's
      // reply, or the unchanged board if the click was already stale). We just
      // render it — single source of truth, self-healing by construction.
      applyState(data.state);
      if (!data.ok) console.warn('step rejected:', data.error);
    } catch (err) {
      setConnState(false);
      console.error('step request failed', err);
    } finally {
      setInputLocked(false);
    }
  }

  // Rewind the in-progress human turn to its start. The response carries the
  // reverted state.
  async function undoTurn() {
    if (inputLocked) return;
    setInputLocked(true);
    try {
      const res = await fetch('/api/undo_turn', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      applyState(data.state);
      if (!data.ok) console.warn('undo_turn rejected:', data.error);
    } catch (err) {
      setConnState(false);
      console.error('undo_turn request failed', err);
    } finally {
      setInputLocked(false);
    }
  }

  // Commit a paused (awaiting-confirm) turn, releasing the AI to reply. The
  // response carries the post-reply state.
  async function confirmTurn() {
    if (inputLocked) return;
    setInputLocked(true);
    try {
      const res = await fetch('/api/confirm_turn', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      applyState(data.state);
      if (!data.ok) console.warn('confirm_turn rejected:', data.error);
    } catch (err) {
      setConnState(false);
      console.error('confirm_turn request failed', err);
    } finally {
      setInputLocked(false);
    }
  }

  // Apply one AI move. Used in AI-vs-AI mode (manual step-through) and as
  // the bound action for the "Advance" button / Enter-key shortcut. In
  // human-vs-AI mode the backend already fast-forwards AI moves after a
  // human action, so this is rarely needed there.
  async function stepAI() {
    if (inputLocked) return;  // serialize with every other state-changing request
    setInputLocked(true);
    try {
      const res = await fetch('/api/step_ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const data = await res.json().catch(() => ({}));
      applyState(data.state);
      if (!data.ok) console.warn('step_ai rejected:', data.error);
    } catch (err) {
      setConnState(false);
      console.error('step_ai request failed', err);
    } finally {
      setInputLocked(false);
    }
  }

  // Friendly seat-type labels for the per-player header tag. The backend
  // seat values map to a short display string (the New-game dialog itself
  // is now a fixed human-vs-MCTS setup, so no label→backend direction is
  // needed).
  const BACKEND_TO_LABEL = {
    'human': 'human',
    'random': 'random',
    'simple': 'simple',
    'hubris': 'v1',
    'hubris_v1': 'v1 (default)',
    'hubris_v2': 'v2',
    'hubris_v3': 'v3',
    'mcts': 'mcts',
    'nn': 'nn',
  };

  function backendToLabel(backend) {
    return BACKEND_TO_LABEL[backend] || backend;
  }

  // Step 1 of a new game: show the mode-select overlay. The user picks the
  // variant (Family vs Cards) via the two buttons, which call startGame().
  function resetGame() {
    const modal = document.getElementById('mode-select-modal');
    if (modal) modal.classList.remove('hidden');
  }

  // Hide the mode-select overlay (after a choice is made, or — for the very
  // first load — if the user dismisses it without picking).
  function hideModeSelect() {
    const modal = document.getElementById('mode-select-modal');
    if (modal) modal.classList.add('hidden');
  }

  // -----------------------------------------------------------------------
  // Hand-picker modal — Cards mode, vs non-human opponent.
  // -----------------------------------------------------------------------

  const HAND_LIMIT = 7;
  let _handPickerResolve = null;
  let _handPickerSelOccs = new Set();
  let _handPickerSelMins = new Set();

  function _updateHandPickerCounts() {
    const occEl = document.getElementById('hand-picker-occ-count');
    const minEl = document.getElementById('hand-picker-min-count');
    if (occEl) {
      occEl.textContent = `${_handPickerSelOccs.size} / ${HAND_LIMIT}`;
      occEl.classList.toggle('at-limit', _handPickerSelOccs.size >= HAND_LIMIT);
    }
    if (minEl) {
      minEl.textContent = `${_handPickerSelMins.size} / ${HAND_LIMIT}`;
      minEl.classList.toggle('at-limit', _handPickerSelMins.size >= HAND_LIMIT);
    }
  }

  function _togglePickerCard(id, kind, cardEl) {
    const sel = kind === 'occ' ? _handPickerSelOccs : _handPickerSelMins;
    if (sel.has(id)) {
      sel.delete(id);
      cardEl.classList.remove('selected');
    } else if (sel.size < HAND_LIMIT) {
      sel.add(id);
      cardEl.classList.add('selected');
    }
    _updateHandPickerCounts();
  }

  function _makePickerCard(card, kind) {
    const div = document.createElement('div');
    div.className = 'picker-card';
    div.dataset.id = card.id;

    const name = document.createElement('div');
    name.className = 'picker-card-name';
    name.textContent = card.name || card.id;
    if (card.vps) {
      const vpBadge = document.createElement('span');
      vpBadge.className = 'hand-card-vps';
      vpBadge.title = 'printed victory points';
      vpBadge.textContent = ` ${card.vps} pt${card.vps === 1 ? '' : 's'}`;
      name.appendChild(vpBadge);
    }
    div.appendChild(name);

    if (card.cost && card.cost !== '—') {
      const cost = document.createElement('div');
      cost.className = 'picker-card-cost';
      cost.textContent = `Cost: ${card.cost}`;
      div.appendChild(cost);
    }
    if (card.prereq) {
      const prereq = document.createElement('div');
      prereq.className = 'picker-card-prereq';
      prereq.textContent = `Needs: ${card.prereq}`;
      div.appendChild(prereq);
    }
    if (card.text) {
      const text = document.createElement('div');
      text.className = 'picker-card-text';
      text.textContent = card.text;
      div.appendChild(text);
    }
    if (card.deck) {
      div.appendChild(el('div', { class: 'hand-card-deck' }, card.deck));
    }

    div.addEventListener('click', () => _togglePickerCard(card.id, kind, div));
    return div;
  }

  function _renderHandPickerCards(cardsList) {
    const occsEl = document.getElementById('hand-picker-occs');
    const minsEl = document.getElementById('hand-picker-mins');
    if (!occsEl || !minsEl) return;
    occsEl.innerHTML = '';
    minsEl.innerHTML = '';
    for (const c of cardsList.occupations || []) {
      occsEl.appendChild(_makePickerCard(c, 'occ'));
    }
    for (const c of cardsList.minors || []) {
      minsEl.appendChild(_makePickerCard(c, 'min'));
    }
  }

  function _closeHandPicker(result) {
    const modal = document.getElementById('hand-picker-modal');
    if (modal) modal.classList.add('hidden');
    if (_handPickerResolve) {
      _handPickerResolve(result);
      _handPickerResolve = null;
    }
  }

  // Shows the hand-picker modal and returns a Promise that resolves with
  // {occupations:[...ids], minors:[...ids]} on "Start game" / "Fully random",
  // or null on "Cancel".
  async function showHandPicker() {
    _handPickerSelOccs.clear();
    _handPickerSelMins.clear();
    _updateHandPickerCounts();

    let cardsList;
    try {
      const res = await fetch('/api/cards_list');
      cardsList = await res.json();
    } catch (e) {
      console.warn('hand-picker: failed to fetch cards_list', e);
      return { occupations: [], minors: [] };  // fall back to fully random
    }

    _renderHandPickerCards(cardsList);

    const modal = document.getElementById('hand-picker-modal');
    if (modal) modal.classList.remove('hidden');

    return new Promise((resolve) => {
      _handPickerResolve = resolve;
    });
  }

  // Step 2 of a new game: the variant has been chosen. Gather the
  // mode-specific prompts and POST /api/reset.
  //   'family' → human-vs-MCTS: seed + sims/move + opponent prior-mix.
  //   'cards'  → human-vs-(random|human): seed + opponent type, NO bot knobs
  //              (the trained MCTS bot is Family-only).
  async function startGame(mode) {
    hideModeSelect();

    const seedStr = prompt(
      'Seed for new game? (blank = random)', String(Date.now() & 0xffff));
    if (seedStr === null) return;
    const seedTrim = seedStr.trim();
    const seed = seedTrim === ''
      ? (Date.now() & 0xffff)
      : (parseInt(seedTrim, 10) || 0);

    let body;
    if (mode === 'cards') {
      // Opponent type: "random" (default) or "human" (hot-seat). No MCTS bot
      // for the card game yet, so no sims/mix knobs.
      const oppStr = prompt(
        'Opponent for the card game?\n' +
        '  random = a random-move bot (default)\n' +
        '  human  = play both seats yourself (hot-seat)',
        'random');
      if (oppStr === null) return;
      const opp = oppStr.trim().toLowerCase() === 'human' ? 'human' : 'random';

      // Hand setup: three options. "Choose your hand" only available vs non-human.
      const handOptStr = prompt(
        'Hand setup?\n' +
        '  draft  = competitive draft — pick one card at a time (default)\n' +
        '  random = fully random deal\n' +
        (opp !== 'human' ? '  choose = pick your own hand\n' : '') +
        '\n(hit Enter for draft)',
        'draft');
      if (handOptStr === null) return;
      const handOpt = handOptStr.trim().toLowerCase() || 'draft';

      let hand_mode, custom_hand = null;
      if (handOpt === 'choose' && opp !== 'human') {
        hand_mode = 'choose';
        const picked = await showHandPicker();
        if (picked === null) return;  // user cancelled the picker
        if (picked.occupations.length || picked.minors.length) {
          custom_hand = picked;
        }
      } else if (handOpt === 'random') {
        hand_mode = 'random';
      } else {
        hand_mode = 'draft';
      }

      body = { seed, seats: ['human', opp], game_mode: 'cards', hand_mode, custom_hand };
    } else {
      // Family game — the existing human-vs-MCTS setup.
      // Sims/move: default to the current game's value, else the last choice,
      // else 800. Persisted so it sticks across games.
      const simsDefault = (currentState && currentState.mcts_sims)
        || parseInt(localStorage.getItem('agricola.mctsSims'), 10)
        || 800;
      const simsStr = prompt(
        'AI strength — MCTS sims per move?\n' +
        '  higher = stronger but slower\n' +
        '  800 = default,  ~1500+ = strong,  300 = quick',
        String(simsDefault));
      if (simsStr === null) return;
      const simsTrim = simsStr.trim();
      const mctsSims = simsTrim === '' ? simsDefault : Math.max(1, parseInt(simsTrim, 10) || simsDefault);
      localStorage.setItem('agricola.mctsSims', String(mctsSims));

      // Opponent's prior-uniform mix for this game (0 = standard/strongest bot).
      const mixDefault = (currentState && currentState.opponent_mix)
        || parseFloat(localStorage.getItem('agricola.opponentMix'))
        || 0;
      const mixStr = prompt(
        'Opponent mix? (uniform mix into the bot\'s prior)\n' +
        '  0 = standard bot (default),  ~0.05 = a bit more varied / slightly weaker',
        String(mixDefault));
      if (mixStr === null) return;
      const mixTrim = mixStr.trim();
      const opponentMix = mixTrim === '' ? mixDefault : Math.max(0, parseFloat(mixTrim) || 0);
      localStorage.setItem('agricola.opponentMix', String(opponentMix));

      body = {
        seed, seats: ['human', 'mcts'], game_mode: 'family',
        mcts_sims: mctsSims, opponent_mix: opponentMix,
      };
    }

    if (inputLocked) return;  // a request is in flight — serialize
    setInputLocked(true);
    try {
      const res = await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      applyState(data.state);  // render the fresh game from the response
      if (!data.ok) console.warn('reset rejected:', data.error);
    } catch (err) {
      setConnState(false);
      console.error('reset failed', err);
    } finally {
      setInputLocked(false);
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

  // A toggle is a state-changing request, so it serializes through inputLocked
  // like every action — one request in flight at a time keeps responses in
  // order. `desired` is the checkbox's new value. On success the response
  // carries the server-authoritative flag, which render() reflects back onto
  // the checkbox; if a request is already in flight, we ignore the toggle and
  // snap the checkbox back to current truth.
  async function postToggle(endpoint, desired, current, checkboxId, errLabel) {
    const cb = document.getElementById(checkboxId);
    if (inputLocked) {
      if (cb) cb.checked = current;  // busy — revert; truth unchanged
      return;
    }
    setInputLocked(true);
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !!desired }),
      });
      const data = await res.json().catch(() => ({}));
      applyState(data.state);  // render() syncs the flag + checkbox from state
      if (!data.ok) console.warn(errLabel + ' rejected:', data.error);
    } catch (err) {
      setConnState(false);
      if (cb) cb.checked = current;  // revert on failure
      console.error(errLabel + ' failed', err);
    } finally {
      setInputLocked(false);
    }
  }

  function setFastMode(v) {
    return postToggle('/api/fast_mode', v, fastMode, 'fast-mode-toggle', 'fast_mode toggle');
  }

  function setConfirmTurn(v) {
    return postToggle('/api/confirm_mode', v, confirmMode, 'confirm-turn-toggle', 'confirm_mode toggle');
  }

  // "Show analysis" toggle. Frontend-only — does NOT POST. When turned on
  // during the human's turn, kick off a background analysis immediately; when
  // off, clear the overlay and re-render.
  function setAnalysis(v) {
    analysisOn = !!v;
    updateAnalysisControls();
    if (analysisOn) {
      analysisGen++;
      analysisByKey.clear();
      if (currentState && isHumanTurn(currentState)) fetchAnalysis(analysisGen);
    } else {
      analysisByKey.clear();
      if (currentState) render(currentState);
    }
  }

  // The analysis sims budget, lazily initialised to the current game's bot
  // sims on first use (so analysis matches the game's strength out of the box),
  // then sticky. Persists once concretely set.
  function ensureAnalysisSims() {
    if (analysisSims == null) {
      const fromGame = currentState && currentState.mcts_sims;
      analysisSims = (Number.isFinite(fromGame) && fromGame >= 1) ? fromGame : 800;
      localStorage.setItem('agricola.analysisSims', String(analysisSims));
    }
    return analysisSims;
  }

  // Re-run analysis after a control changes: invalidate any in-flight result
  // (it carries the old params), clear the overlay, re-render, and refetch.
  function rerunAnalysis() {
    if (!(analysisOn && currentState && isHumanTurn(currentState))) return;
    analysisGen++;
    analysisByKey.clear();
    render(currentState);
    fetchAnalysis(analysisGen);
  }

  // Tune the analysis exploration constant (c_uct). Persisted; re-runs if on.
  function setAnalysisCuct(v) {
    const n = parseFloat(v);
    if (!(n > 0)) return;  // ignore invalid / non-positive
    analysisCuct = n;
    localStorage.setItem('agricola.analysisCuct', String(n));
    rerunAnalysis();
  }

  // Tune the analysis search budget (sims/move). Persisted; re-runs if on.
  function setAnalysisSims(v) {
    const n = parseInt(v, 10);
    if (!(n >= 1)) return;
    analysisSims = n;
    localStorage.setItem('agricola.analysisSims', String(n));
    rerunAnalysis();
  }

  // Choose which value head analysis evaluates with. Persisted; re-runs if on.
  // Shows/hides the mix-α stepper (only meaningful for the mix leaf).
  function setAnalysisLeafMode(mode) {
    if (mode !== 'margin' && mode !== 'outcome' && mode !== 'mix') return;
    analysisLeafMode = mode;
    localStorage.setItem('agricola.analysisLeafMode', mode);
    updateAnalysisControls();
    rerunAnalysis();
  }

  // Tune the mix-leaf blend weight α. Persisted; re-runs if on.
  function setAnalysisMixAlpha(v) {
    const n = parseFloat(v);
    if (!(n >= 0 && n <= 1)) return;
    analysisMixAlpha = n;
    localStorage.setItem('agricola.analysisMixAlpha', String(n));
    rerunAnalysis();
  }

  // Reflect analysis state onto the control row: show the row only when
  // analysis is on, and the α stepper only when the mix leaf is selected.
  // Also keeps the segmented-control active button + input values in sync.
  function updateAnalysisControls() {
    const row = document.getElementById('analysis-controls');
    if (row) row.classList.toggle('hidden', !analysisOn);
    // When the row is shown, make sure the sims field displays a concrete value
    // (lazily inherited from the current game on first open).
    if (analysisOn) {
      const simsInput = document.getElementById('analysis-sims');
      if (simsInput) simsInput.value = String(ensureAnalysisSims());
    }
    const alphaWrap = document.getElementById('analysis-alpha-wrap');
    if (alphaWrap) alphaWrap.classList.toggle('hidden', analysisLeafMode !== 'mix');
    document.querySelectorAll('#analysis-mode-group button[data-mode]').forEach((b) => {
      b.classList.toggle('active', b.getAttribute('data-mode') === analysisLeafMode);
    });
  }

  // Reflect a server-owned toggle flag onto its local mirror var + checkbox.
  function syncToggle(key, state, checkboxId, setLocal) {
    if (typeof state[key] !== 'boolean') return;
    setLocal(state[key]);
    const cb = document.getElementById(checkboxId);
    if (cb) cb.checked = state[key];
  }

  function render(state) {
    // The server owns these toggle flags; reflect whatever it reports onto the
    // local mirrors and the checkboxes. ("Show analysis" is frontend-only and
    // is NOT server-synced — its checkbox is wired directly to setAnalysis.)
    syncToggle('confirm_mode', state, 'confirm-turn-toggle', (v) => { confirmMode = v; });
    syncToggle('fast_mode', state, 'fast-mode-toggle', (v) => { fastMode = v; });

    // Recompute which hand cards are playable this turn (for the hand-panel
    // highlight). Empty outside cards mode / when no card-play action is legal.
    currentPlayableCardIds = new Set();
    for (const a of state.legal_actions || []) {
      if (a.ui_hint === 'card' && a.params && a.params.card_id != null) {
        currentPlayableCardIds.add(a.params.card_id);
      }
    }

    // Cards mode has no trained bot, so the analysis overlay is meaningless —
    // hide its toggle (and, defensively, force it off + collapse its control
    // row). Fast mode / Confirm turns stay available.
    const cardsMode = state.game_mode === 'cards';
    const analysisLabel = document.getElementById('analysis-toggle-label');
    if (analysisLabel) analysisLabel.classList.toggle('hidden', cardsMode);
    if (cardsMode && analysisOn) {
      analysisOn = false;
      const cb = document.getElementById('analysis-toggle');
      if (cb) cb.checked = false;
      analysisByKey.clear();
      updateAnalysisControls();
    }

    renderHeader(state);
    renderTurnControls(state);
    renderActionBoard(state);
    renderMajorBoard(state);
    renderPlayerPanel(state, 0);
    renderPlayerPanel(state, 1);
    renderDecisionPanel(state);
    renderRoundLog(state);
    renderGameOver(state);
    renderDraftModal(state);
    renderDraftHandoff(state);
  }

  // -------- turn controls (Confirm / Undo), rendered ABOVE the boards --------

  function renderTurnControls(state) {
    const tc = document.getElementById('turn-controls');
    if (!tc) return;
    tc.innerHTML = '';
    if (state.game_over) return;
    if (state.awaiting_confirm) {
      // The human's turn is complete; wait for an explicit Confirm/Undo.
      const bar = el('div', { class: 'confirm-bar' });
      bar.appendChild(el('button',
        { class: 'confirm-btn', onclick: () => confirmTurn() }, 'Confirm turn'));
      bar.appendChild(el('button',
        { class: 'undo-btn', onclick: () => undoTurn() }, 'Undo turn'));
      bar.appendChild(el('span', { class: 'confirm-hint' },
        'Confirm your turn or undo it.'));
      tc.appendChild(bar);
    } else if (state.can_undo) {
      // Mid-turn: let the human reset the in-progress turn.
      const bar = el('div', { class: 'undo-bar' });
      bar.appendChild(el('button',
        { class: 'action-btn small undo', onclick: () => undoTurn() }, 'Undo turn'));
      tc.appendChild(bar);
    }
  }

  // -------- header --------

  function renderHeader(state) {
    const isDraft = state.phase === 'DRAFT';
    document.getElementById('round-label').textContent =
      isDraft ? 'Draft' : `Round ${state.round_number}/14`;
    document.getElementById('phase-label').textContent =
      isDraft ? 'Picking cards' : `Phase ${state.phase}`;
    document.getElementById('sp-label').textContent =
      `SP P${state.starting_player}`;
    document.getElementById('decider-label').textContent =
      state.game_over ? 'Game over' : `Deciding: P${state.decider}`;
    document.getElementById('harvest-note').textContent =
      state.harvest_note || '';
  }

  // -------- action board --------

  // Both 'side_job' and 'lessons' occupy the same conceptual slot: the Family
  // game shows Side Job, the card game shows Lessons. The backend omits whichever
  // is inert for the current mode, so only one of the pair is ever rendered.
  const PERMANENT_ORDER = [
    'forest', 'clay_pit', 'reed_bank', 'fishing', 'meeting_place',
    'grain_seeds', 'farmland', 'day_laborer', 'side_job', 'lessons', 'farm_expansion',
  ];

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
      // "Show analysis" overlay: the AI's visit count + value for placing a
      // worker here, looked up by the canonical action key. Only present for
      // moves the search actually considered (PUCT concentrates, so unvisited
      // moves are omitted by design).
      const analysis = (analysisOn && legal)
        ? analysisByKey.get(actionKey('PlaceWorker', { space: sid }))
        : undefined;
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
        sp.effect_text
          ? el('span', { class: 'space-effect' }, sp.effect_text)
          : null,
      );
      const right = el('div', { class: 'space-right' });
      if (analysis) {
        right.appendChild(el(
          'span',
          { class: 'analysis-badge', title: "AI value (Q, human's frame) · visit count" },
          analysisBadgeText(analysis),
        ));
      }
      const workers = el('div', { class: 'space-workers' });
      for (let p = 0; p < 2; p++) {
        if (sp.workers[p] > 0) {
          const token = el('span',
            { class: `worker-token p${p}` },
            sp.workers[p] > 1 ? `${sp.workers[p]}` : '');
          workers.appendChild(token);
        }
      }
      right.appendChild(workers);
      card.appendChild(left);
      card.appendChild(right);
      if (legal) {
        card.addEventListener('click', () => submitAction(legal.index));
      }
      container.appendChild(card);
    };

    emitGroup('permanent');
    for (const sid of PERMANENT_ORDER) emitSpace(sid);

    // Stage spaces grouped by stage (1–6), and WITHIN each stage in the order
    // they were revealed (round_revealed). Across stages this is also reveal
    // order, since stages reveal in round order. Empty stages are skipped, so
    // a stage header appears only once its first card is revealed.
    for (let stage = 1; stage <= 6; stage++) {
      const stageSpaces = state.board.spaces
        .filter((s) => s.stage === stage && s.is_revealed)
        .sort((a, b) => (a.round_revealed || 0) - (b.round_revealed || 0));
      if (!stageSpaces.length) continue;
      emitGroup(`stage ${stage}`);
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

  // "Owed" line: per-future-round goods/benefits, e.g. "Owed: R5 1 food  ·
  // R6 1 food". Round labels render in normal weight; the goods text is bold,
  // matching the summary convention. Spans both summary columns (see CSS).
  function buildOwedLine(owed) {
    const div = el('div', { class: 'summary-owed' });
    div.appendChild(el('span', { class: 'label' }, 'Owed: '));
    owed.forEach((entry, i) => {
      if (i > 0) div.appendChild(el('span', { class: 'sep' }, '  ·  '));
      div.appendChild(document.createTextNode(`R${entry.round} `));
      div.appendChild(el('span', { class: 'val' }, entry.text));
    });
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
    const handEl = document.getElementById(`p${idx}-hand`);
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
    // Forward-looking: goods/benefits this player is owed at the start of future
    // rounds (the Well's per-round food, etc.). Public info, so shown for both
    // seats; only present when something is actually scheduled.
    if (p.owed_future && p.owed_future.length) {
      summaryEl.appendChild(buildOwedLine(p.owed_future));
    }

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

    // Improvements. Majors stay a compact name line; played occupations and
    // minor improvements are a PUBLIC tableau (shown for BOTH players) rendered
    // as cards with their effect text, so a played card never just vanishes.
    impEl.innerHTML = '';
    const majorsLine = p.majors.length
      ? p.majors.map((m) => `${m.idx}:${m.name}`).join(', ')
      : '—';
    impEl.appendChild(el('div', { class: 'improv-list' },
      el('div', { class: 'row' },
        el('span', { class: 'label' }, 'Majors: '),
        el('span', {}, majorsLine)),
    ));
    const playedGroup = (label, cards) => {
      if (!cards || !cards.length) return;
      impEl.appendChild(el('div', { class: 'card-hand-group-label' }, label));
      const row = el('div', { class: 'card-hand' });
      for (const c of cards) row.appendChild(renderPlayedCard(c));
      impEl.appendChild(row);
    };
    playedGroup('Occupations', p.played_occupations);
    playedGroup('Minors', p.played_minors);

    // Hand (cards mode only). Rendered face-up for a human seat (server sends
    // the full `hand`), face-down for a hidden opponent (only `hand_counts`).
    renderHand(handEl, state, p);
  }

  // Render a player's hand container. Empty in Family mode; in Cards mode
  // either the revealed cards (grouped Occupations / Minors) or face-down
  // placeholders sized from hand_counts.
  function renderHand(handEl, state, p) {
    if (!handEl) return;
    handEl.innerHTML = '';
    if (state.game_mode !== 'cards') return;  // Family game — no hand UI

    handEl.appendChild(el('div', { class: 'card-hand-section' }, 'Hand'));

    if (Array.isArray(p.hand)) {
      // Revealed (this is a human seat). Group by type.
      const occ = p.hand.filter((c) => c.type === 'occupation');
      const min = p.hand.filter((c) => c.type === 'minor');
      const group = (label, cards) => {
        if (!cards.length) return;
        handEl.appendChild(el('div', { class: 'card-hand-group-label' }, label));
        const row = el('div', { class: 'card-hand' });
        for (const c of cards) row.appendChild(renderHandCard(c));
        handEl.appendChild(row);
      };
      group('Occupations', occ);
      group('Minors', min);
      if (!p.hand.length) {
        handEl.appendChild(el('div', { class: 'card-hand-empty' }, '(empty)'));
      }
    } else {
      // Hidden opponent — only counts are known.
      const hc = p.hand_counts || { occupations: 0, minors: 0 };
      const total = (hc.occupations || 0) + (hc.minors || 0);
      handEl.appendChild(el('div', { class: 'card-hand-group-label' },
        `Hidden: ${hc.occupations || 0} occ / ${hc.minors || 0} min`));
      const row = el('div', { class: 'card-hand' });
      for (let i = 0; i < total; i++) {
        row.appendChild(el('div', { class: 'hand-card facedown' }));
      }
      handEl.appendChild(row);
    }
  }

  // A single face-up hand card: bold name, optional cost (minors), text.
  // Highlighted (.playable) when a card-play action for it is legal this turn.
  function renderHandCard(c) {
    const playable = currentPlayableCardIds.has(c.id);
    const cls = 'hand-card' + (playable ? ' playable' : '');
    const card = el('div', { class: cls, title: c.text || '' });
    card.appendChild(cardNameRow(c));
    if (c.cost) {
      card.appendChild(el('div', { class: 'hand-card-cost' }, c.cost));
    }
    if (c.prereq) {
      card.appendChild(el('div', { class: 'hand-card-prereq' }, `Needs: ${c.prereq}`));
    }
    if (c.text) {
      card.appendChild(el('div', { class: 'hand-card-text' }, c.text));
    }
    if (c.deck) {
      card.appendChild(el('div', { class: 'hand-card-deck' }, c.deck));
    }
    return card;
  }

  // Card name row: the name, plus a printed-VP badge ("N pt(s)") when the card
  // scores victory points, so point-scoring cards advertise their points.
  function cardNameRow(c) {
    const row = el('div', { class: 'hand-card-name' }, c.name || c.id);
    if (c.vps) {
      row.appendChild(el('span', { class: 'hand-card-vps',
        title: 'printed victory points' }, `${c.vps} pt${c.vps === 1 ? '' : 's'}`));
    }
    // Live "+X vp" emblem for cards whose bonus points are only knowable from
    // game history (Big Country, Mantelpiece, Tutor, …). Same look as the printed
    // badge, distinguished by the "+" prefix. Appended AFTER the printed badge so
    // (both float:right) it sits to the LEFT of it — e.g. Mantelpiece shows
    // "+X vp" then "-3 pts".
    if (c.bonus_vps != null) {
      const n = c.bonus_vps;
      row.appendChild(el('span', { class: 'hand-card-vps',
        title: 'bonus victory points earned so far' },
        `+${n} pt${n === 1 ? '' : 's'}`));
    }
    return row;
  }

  // A single PLAYED card in a player's public tableau: bold name + effect text
  // (also as a hover tooltip). No cost / no playable highlight — it's already
  // played and visible to both players.
  function renderPlayedCard(c) {
    const card = el('div', { class: 'hand-card played-card', title: c.text || '' });
    card.appendChild(cardNameRow(c));
    // Live per-card state for resource/counter cards (Interim Storage goods held,
    // Moldboard Plow plows left) — info the player can't read off the board.
    if (c.state_text) {
      card.appendChild(el('div', { class: 'hand-card-state' }, c.state_text));
    }
    if (c.prereq) {
      card.appendChild(el('div', { class: 'hand-card-prereq' }, `Needs: ${c.prereq}`));
    }
    if (c.text) {
      card.appendChild(el('div', { class: 'hand-card-text' }, c.text));
    }
    if (c.deck) {
      card.appendChild(el('div', { class: 'hand-card-deck' }, c.deck));
    }
    return card;
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

    // Confirm-turn pause: the human's turn is complete; the Confirm / Undo
    // controls are rendered above the boards (renderTurnControls). Point the
    // user there and render no action buttons.
    if (state.awaiting_confirm) {
      banner.textContent = 'Your turn is complete — Confirm or Undo it above the boards to continue.';
      menu.appendChild(el('div', { class: 'muted' },
        'Use the Confirm / Undo buttons above.'));
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

    // (Mid-turn Undo is rendered above the boards by renderTurnControls.)

    // Draft phase: the full-screen #draft-modal handles picking (renderDraftModal).
    // Nothing needed here — the modal overlays the boards and this panel.
    if (state.phase === 'DRAFT') {
      menu.appendChild(el('div', { class: 'muted' }, 'Draft in progress — see the picker above.'));
      return;
    }

    // Card-play actions (ui_hint:"card") are pulled out and rendered as their
    // own group below — identified by ui_hint, not a fixed action type.
    const cardActions = (state.legal_actions || []).filter((a) => a.ui_hint === 'card');

    // Group the remaining actions by type so the menu reads cleanly.
    const groups = new Map();
    for (const a of state.legal_actions) {
      if (a.ui_hint === 'card') continue;  // handled separately
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
      'Proceed',
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

    // Card-play actions first — a dedicated button group at the top of the
    // menu. Each is an .action-btn (with .card-action) that POSTs its index
    // like any other action.
    if (cardActions.length) {
      menu.appendChild(el('div', { class: 'action-group-header' },
        `Play card (${cardActions.length})`));
      for (const a of cardActions) {
        menu.appendChild(el('button',
          { class: 'action-btn card-action',
            onclick: () => submitAction(a.index) },
          a.display));
        anyButtons = true;
      }
    }

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
          { class: 'action-btn' + (key === 'Stop' || key === 'Proceed' ? ' stop' : ''),
            onclick: () => submitAction(a.index) },
          a.display);
        // "Show analysis" overlay on the sub-action button (ChooseSubAction /
        // Commit* / Stop), keyed by the canonical action key.
        const info = analysisOn
          ? analysisByKey.get(actionKey(a.type, a.params))
          : undefined;
        if (info) {
          btn.appendChild(el('span',
            { class: 'analysis-badge btn-badge',
              title: "AI value (Q, human's frame) · visit count" },
            ' ' + analysisBadgeText(info)));
        }
        menu.appendChild(btn);
        anyButtons = true;
      }
    }

    // Catch-all: render any action type NOT named in ORDER above (and not a
    // ui_hint:"card" play, handled separately) as plain buttons — so a new or
    // uncommon action type (CommitCardChoice, CommitFamilyGrowth, …) is never
    // SILENTLY DROPPED from the menu. (ORDER controls placement/styling for the
    // common types; this guarantees completeness for the rest.)
    for (const [key, opts] of groups) {
      if (ORDER.includes(key)) continue;
      menu.appendChild(el('div', { class: 'action-group-header' },
        `${key} (${opts.length})`));
      for (const a of opts) {
        menu.appendChild(el('button',
          { class: 'action-btn', onclick: () => submitAction(a.index) },
          a.display));
        anyButtons = true;
      }
    }

    if (!anyButtons) {
      menu.appendChild(el('div', {}, '(no legal actions)'));
    }
  }

  // -------- draft handoff overlay --------

  // -------- draft card picker modal --------

  function renderDraftModal(state) {
    const modal = document.getElementById('draft-modal');
    if (!modal) return;

    // Show only when: draft phase, no handoff pending, human is deciding.
    const show = state.phase === 'DRAFT'
      && !state.draft_handoff
      && !state.game_over
      && !isAiDecider(state);
    modal.classList.toggle('hidden', !show);
    if (!show) return;

    const info = state.draft_info || {};
    const p = info.picking_player != null ? info.picking_player : state.decider;
    const cardType = info.card_type || 'occupation';
    const round = info.round;
    const total = info.total_rounds || 7;

    const titleEl = document.getElementById('draft-modal-title');
    if (titleEl) titleEl.textContent = `P${p} — Draft Round ${round} of ${total}`;
    const subEl = document.getElementById('draft-modal-sub');
    if (subEl) subEl.textContent = 'Select one occupation and one minor improvement, then confirm.';

    const occPool = info.occ_pool || [];
    const minPool = info.min_pool || [];

    // Reset stale selections (pool changed — new player or new round).
    const occIds = new Set(occPool.map((c) => c.card_id));
    const minIds = new Set(minPool.map((c) => c.card_id));
    if (_draftSelOcc && !occIds.has(_draftSelOcc)) _draftSelOcc = null;
    if (_draftSelMin && !minIds.has(_draftSelMin)) _draftSelMin = null;

    // Render occupation column.
    const occEl = document.getElementById('draft-occ-cards');
    if (occEl) {
      occEl.innerHTML = '';
      if (cardType === 'minor') {
        // Occupation already picked this round — show placeholder.
        occEl.appendChild(el('div', { class: 'draft-already-picked' },
          'Occupation already chosen this round.'));
      } else {
        for (const c of occPool) occEl.appendChild(_makeDraftCard(c, 'occ'));
      }
    }

    // Render minor column.
    const minEl = document.getElementById('draft-min-cards');
    if (minEl) {
      minEl.innerHTML = '';
      for (const c of minPool) minEl.appendChild(_makeDraftCard(c, 'min'));
    }

    // Render "picks so far" section.
    const pickedOccs = info.picked_occs || [];
    const pickedMins = info.picked_mins || [];
    const pickedSection = document.getElementById('draft-picked-section');
    if (pickedSection) {
      const hasPicks = pickedOccs.length > 0 || pickedMins.length > 0;
      pickedSection.classList.toggle('hidden', !hasPicks);
      const occPickedEl = document.getElementById('draft-picked-occs');
      const minPickedEl = document.getElementById('draft-picked-mins');
      if (occPickedEl) {
        occPickedEl.innerHTML = '';
        for (const c of pickedOccs) occPickedEl.appendChild(_makePickedCard(c));
      }
      if (minPickedEl) {
        minPickedEl.innerHTML = '';
        for (const c of pickedMins) minPickedEl.appendChild(_makePickedCard(c));
      }
    }

    // Update badges + confirm button.
    _updateDraftUI(cardType);

    // Wire confirm button (replace onclick each render to avoid stale closure).
    const confirmBtn = document.getElementById('draft-confirm-btn');
    if (confirmBtn) {
      confirmBtn.onclick = () => confirmDraftPicks(cardType);
    }
  }

  // Build one selectable card element for the draft modal.
  function _makeDraftCard(c, kind) {
    const div = document.createElement('div');
    div.className = 'picker-card';
    const sel = kind === 'occ' ? _draftSelOcc : _draftSelMin;
    if (c.card_id === sel) div.classList.add('selected');

    // Name row with optional VP badge.
    const nameRow = document.createElement('div');
    nameRow.className = 'picker-card-name';
    nameRow.textContent = c.name || c.card_id;
    if (c.vps) {
      const vpBadge = document.createElement('span');
      vpBadge.className = 'hand-card-vps';
      vpBadge.title = 'printed victory points';
      vpBadge.textContent = ` ${c.vps} pt${c.vps === 1 ? '' : 's'}`;
      nameRow.appendChild(vpBadge);
    }
    div.appendChild(nameRow);

    if (c.cost && c.cost !== '—') {
      div.appendChild(el('div', { class: 'picker-card-cost' }, `Cost: ${c.cost}`));
    }
    if (c.prereq) {
      div.appendChild(el('div', { class: 'picker-card-prereq' }, `Needs: ${c.prereq}`));
    }
    if (c.text) {
      div.appendChild(el('div', { class: 'picker-card-text' }, c.text));
    }
    if (c.deck) {
      div.appendChild(el('div', { class: 'hand-card-deck' }, c.deck));
    }

    div.addEventListener('click', () => {
      if (kind === 'occ') {
        // Radio-style: deselect the previous occ card.
        const prev = document.querySelector('#draft-occ-cards .picker-card.selected');
        if (prev) prev.classList.remove('selected');
        _draftSelOcc = (_draftSelOcc === c.card_id) ? null : c.card_id;
        if (_draftSelOcc) div.classList.add('selected');
      } else {
        const prev = document.querySelector('#draft-min-cards .picker-card.selected');
        if (prev) prev.classList.remove('selected');
        _draftSelMin = (_draftSelMin === c.card_id) ? null : c.card_id;
        if (_draftSelMin) div.classList.add('selected');
      }
      _updateDraftUI(currentState?.draft_info?.card_type || 'occupation');
    });

    return div;
  }

  // Read-only version of the draft card — same visual, no click handler.
  function _makePickedCard(c) {
    const div = document.createElement('div');
    div.className = 'picker-card picker-card-readonly';

    const nameRow = document.createElement('div');
    nameRow.className = 'picker-card-name';
    nameRow.textContent = c.name || c.card_id;
    if (c.vps) {
      const vpBadge = document.createElement('span');
      vpBadge.className = 'hand-card-vps';
      vpBadge.title = 'victory points';
      vpBadge.textContent = ` ${c.vps} pt${c.vps === 1 ? '' : 's'}`;
      nameRow.appendChild(vpBadge);
    }
    div.appendChild(nameRow);

    if (c.cost && c.cost !== '—') {
      div.appendChild(el('div', { class: 'picker-card-cost' }, `Cost: ${c.cost}`));
    }
    if (c.prereq) {
      div.appendChild(el('div', { class: 'picker-card-prereq' }, `Needs: ${c.prereq}`));
    }
    if (c.text) {
      div.appendChild(el('div', { class: 'picker-card-text' }, c.text));
    }
    if (c.deck) {
      div.appendChild(el('div', { class: 'hand-card-deck' }, c.deck));
    }

    return div;
  }

  // Update the selection badges and confirm button enabled state.
  function _updateDraftUI(cardType) {
    const isMinorOnly = cardType === 'minor';
    const occOk = isMinorOnly || !!_draftSelOcc;
    const minOk = !!_draftSelMin;

    const occBadge = document.getElementById('draft-occ-badge');
    if (occBadge) {
      if (isMinorOnly) {
        occBadge.textContent = '✓ picked';
        occBadge.className = 'draft-sel-badge draft-sel-ok';
      } else if (_draftSelOcc) {
        occBadge.textContent = '✓ chosen';
        occBadge.className = 'draft-sel-badge draft-sel-ok';
      } else {
        occBadge.textContent = 'none chosen';
        occBadge.className = 'draft-sel-badge draft-sel-none';
      }
    }
    const minBadge = document.getElementById('draft-min-badge');
    if (minBadge) {
      if (_draftSelMin) {
        minBadge.textContent = '✓ chosen';
        minBadge.className = 'draft-sel-badge draft-sel-ok';
      } else {
        minBadge.textContent = 'none chosen';
        minBadge.className = 'draft-sel-badge draft-sel-none';
      }
    }

    const btn = document.getElementById('draft-confirm-btn');
    if (btn) btn.disabled = !(occOk && minOk);
  }

  // Submit the draft picks: occ first (if occupation round), then auto-submit minor.
  async function confirmDraftPicks(cardType) {
    if (inputLocked) return;
    const isMinorOnly = cardType === 'minor';
    if (!isMinorOnly && !_draftSelOcc) return;
    if (!_draftSelMin) return;

    const selOcc = _draftSelOcc;
    const selMin = _draftSelMin;
    _draftSelOcc = null;
    _draftSelMin = null;

    // Hide the draft modal immediately — don't wait for the server.
    document.getElementById('draft-modal')?.classList.add('hidden');

    setInputLocked(true);
    // Track the best-known state so the finally block always re-renders
    // (which re-shows the modal if the draft is still in progress).
    let finalState = currentState;
    try {
      if (!isMinorOnly) {
        // Step 1: pick the occupation.
        const occAct = (finalState.legal_actions || []).find(
          (a) => a.ui_hint === 'draft_card' && a.params?.card_id === selOcc
        );
        if (!occAct) return;
        const r1 = await fetch('/api/step', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_index: occAct.index }),
        });
        const d1 = await r1.json();
        if (d1.state) finalState = d1.state;
        if (!d1.ok) return;
      }

      // Step 2: auto-submit the pre-selected minor.
      const minAct = (finalState.legal_actions || []).find(
        (a) => a.ui_hint === 'draft_card' && a.params?.card_id === selMin
      );
      if (!minAct) return;
      const r2 = await fetch('/api/step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_index: minAct.index }),
      });
      const d2 = await r2.json();
      if (d2.state) finalState = d2.state;
    } finally {
      setInputLocked(false);
      applyState(finalState);  // always re-render; modal re-appears if draft still active
    }
  }

  // -------- draft handoff overlay --------

  function renderDraftHandoff(state) {
    const modal = document.getElementById('draft-handoff-modal');
    if (!modal) return;
    const show = !!(state.draft_handoff);
    modal.classList.toggle('hidden', !show);
    if (!show) return;

    const info = state.draft_info || {};
    const p = info.picking_player != null ? info.picking_player : state.decider;
    const cardType = info.card_type || 'card';
    const round = info.round;
    const total = info.total_rounds || 7;

    const title = document.getElementById('draft-handoff-title');
    if (title) title.textContent = `P${p}'s turn to pick`;
    const infoEl = document.getElementById('draft-handoff-info');
    if (infoEl) {
      const roundStr = round != null ? ` (round ${round} of ${total})` : '';
      infoEl.textContent = `Pass the device to P${p} to choose their cards${roundStr}.`;
    }

    const btn = document.getElementById('draft-handoff-ready');
    if (btn) {
      btn.onclick = async () => {
        modal.classList.add('hidden');
        try {
          const resp = await fetch('/api/draft_handoff_ack', { method: 'POST' });
          const data = await resp.json();
          if (data.ok) applyState(data.state);
        } catch (_) {}
      };
    }
  }

  function renderPendingBreadcrumb(container, state) {
    container.innerHTML = '';
    if (!state.pending_stack.length) {
      container.textContent = state.phase === 'DRAFT'
        ? 'Draft — choose a card from your pool.'
        : 'No pending — choose a worker placement.';
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
  // Bedtime overlay — name-gated (Rob/Robert/Dad), shown 11 PM–5 AM Eastern.
  // Frontend-only: it covers the screen and blocks play, but never touches
  // game state, so at 5 AM the overlay lifts and the game resumes exactly
  // where it was. One pool screen is chosen at random on each entry into the
  // window (including each reload while inside it). Farm inspection ('f') is
  // intentionally left out of the pool.
  // ---------------------------------------------------------------------
  const BT_POOL = ['c', 'd', 'n', 's'];
  let bedtimeActive = false;

  function btEasternMinutes() {
    // Minutes-since-midnight in America/New_York (tracks EST/EDT). -1 if the
    // timezone is unavailable, so we never trigger on a bad clock read.
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }).formatToParts(new Date());
      const o = {};
      parts.forEach((p) => { o[p.type] = p.value; });
      const h = parseInt(o.hour, 10) % 24;
      return h * 60 + parseInt(o.minute, 10) + parseInt(o.second, 10) / 60;
    } catch (e) { return -1; }
  }
  function btInWindow(m) { return m >= 0 && (m >= 23 * 60 || m < 5 * 60); }  // 11 PM–5 AM
  // Names that trigger the overlay (case-insensitive).
  function btNameGated() {
    let name = '';
    try { name = (localStorage.getItem('agricola.playerName') || '').trim().toLowerCase(); } catch (e) {}
    return name === 'rob' || name === 'robert' || name === 'dad';
  }
  function btNorm(m) { return ((m % 1440) + 1440) % 1440; }
  function btFmtClock(m) {
    m = btNorm(m);
    const h = Math.floor(m / 60), mm = Math.floor(m % 60);
    const ap = h < 12 ? 'AM' : 'PM';
    let h12 = h % 12; if (h12 === 0) h12 = 12;
    return h12 + ':' + (mm < 10 ? '0' : '') + mm + ' ' + ap;
  }
  function btFmtHM(m) {
    m = btNorm(m);
    let h = Math.floor(m / 60) % 12; if (h === 0) h = 12;
    const mm = Math.floor(m % 60);
    return h + ':' + (mm < 10 ? '0' : '') + mm;
  }
  function btRenderClock() {
    const m = btEasternMinutes();
    if (m < 0) return;
    document.querySelectorAll('#bedtime-overlay [data-bt-clock]').forEach((el) => {
      el.textContent = el.getAttribute('data-bt-clock') === 'hm' ? btFmtHM(m) : btFmtClock(m);
    });
    document.querySelectorAll('#bedtime-overlay [data-bt-daypart]').forEach((el) => {
      el.textContent = btNorm(m) < 720 ? 'in the morning' : 'at night';
    });
  }
  function btShow(which) {
    const ov = document.getElementById('bedtime-overlay');
    if (!ov) return;
    ov.querySelectorAll('.bt-screen').forEach((s) => {
      s.classList.toggle('active', s.getAttribute('data-bt') === which);
    });
    btRenderClock();
    ov.classList.add('active');
    ov.setAttribute('aria-hidden', 'false');
    bedtimeActive = true;
  }
  function btHide() {
    const ov = document.getElementById('bedtime-overlay');
    if (ov) { ov.classList.remove('active'); ov.setAttribute('aria-hidden', 'true'); }
    bedtimeActive = false;
  }
  function btCheck() {
    const inWin = btNameGated() && btInWindow(btEasternMinutes());
    if (inWin && !bedtimeActive) {
      btShow(BT_POOL[Math.floor(Math.random() * BT_POOL.length)]);
    } else if (!inWin && bedtimeActive) {
      btHide();
    } else if (bedtimeActive) {
      btRenderClock();  // keep the live clock/daypart fresh while shown
    }
  }
  // One-time first-name prompt (stored in localStorage), then run `done`.
  function btEnsureName(done) {
    let name = '';
    try { name = (localStorage.getItem('agricola.playerName') || '').trim(); } catch (e) {}
    const modal = document.getElementById('name-prompt-modal');
    const form = document.getElementById('name-prompt-form');
    const input = document.getElementById('name-prompt-input');
    if (name || !modal || !form) { if (done) done(); return; }
    modal.classList.remove('hidden');
    if (input) input.focus();
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = (input && input.value || '').trim();
      try { localStorage.setItem('agricola.playerName', v); } catch (err) {}
      modal.classList.add('hidden');
      if (done) done();
    }, { once: true });
  }

  // ---------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', () => {
    // "New game" opens the mode-select overlay (step 1 of the new-game flow).
    document.getElementById('reset-btn').addEventListener('click', resetGame);
    // Dismiss the "server restarted" banner.
    const banDismiss = document.getElementById('session-banner-dismiss');
    if (banDismiss) banDismiss.addEventListener('click', () => {
      document.getElementById('session-banner').classList.add('hidden');
    });
    // Mode-select overlay buttons → step 2 (startGame) for each variant.
    const familyBtn = document.getElementById('mode-select-family');
    if (familyBtn) familyBtn.addEventListener('click', () => startGame('family'));
    const cardsBtn = document.getElementById('mode-select-cards');
    if (cardsBtn) cardsBtn.addEventListener('click', () => startGame('cards'));
    // Hand-picker modal buttons.
    const hpStart = document.getElementById('hand-picker-start');
    if (hpStart) hpStart.addEventListener('click', () => {
      _closeHandPicker({
        occupations: Array.from(_handPickerSelOccs),
        minors: Array.from(_handPickerSelMins),
      });
    });
    const hpSkip = document.getElementById('hand-picker-skip');
    if (hpSkip) hpSkip.addEventListener('click', () => {
      _closeHandPicker({ occupations: [], minors: [] });
    });
    const hpClear = document.getElementById('hand-picker-clear');
    if (hpClear) hpClear.addEventListener('click', () => {
      _handPickerSelOccs.clear();
      _handPickerSelMins.clear();
      document.querySelectorAll('#hand-picker-modal .picker-card.selected')
        .forEach((c) => c.classList.remove('selected'));
      _updateHandPickerCounts();
    });
    const hpCancel = document.getElementById('hand-picker-cancel');
    if (hpCancel) hpCancel.addEventListener('click', () => _closeHandPicker(null));
    // Download-trace button: navigate to /api/trace, which is served with a
    // Content-Disposition: attachment header so the browser saves it as
    // `agricola-trace-seed<seed>.json` instead of rendering it inline.
    document.getElementById('download-trace-btn').addEventListener('click', () => {
      window.location.href = '/api/trace';
    });
    document.getElementById('game-over-close').addEventListener('click', () => {
      document.getElementById('game-over-modal').classList.add('hidden');
    });
    // Toggle wiring. The flags are server-authoritative and default off each
    // load; render() syncs the checkboxes from each state payload, so we only
    // wire the change handlers here.
    const fastCb = document.getElementById('fast-mode-toggle');
    if (fastCb) fastCb.addEventListener('change', (e) => setFastMode(e.target.checked));
    const analysisCb = document.getElementById('analysis-toggle');
    if (analysisCb) analysisCb.addEventListener('change', (e) => setAnalysis(e.target.checked));
    // Analysis control row: model (margin/outcome/mix) + sims + c_uct + α.
    document.querySelectorAll('#analysis-mode-group button[data-mode]').forEach((b) => {
      b.addEventListener('click', () => setAnalysisLeafMode(b.getAttribute('data-mode')));
    });
    const simsInput = document.getElementById('analysis-sims');
    if (simsInput) {
      if (analysisSims != null) simsInput.value = String(analysisSims);
      simsInput.addEventListener('change', (e) => setAnalysisSims(e.target.value));
    }
    const cuctInput = document.getElementById('analysis-cuct');
    if (cuctInput) {
      cuctInput.value = String(analysisCuct);  // reflect persisted value
      cuctInput.addEventListener('change', (e) => setAnalysisCuct(e.target.value));
    }
    const alphaInput = document.getElementById('analysis-alpha');
    if (alphaInput) {
      alphaInput.value = String(analysisMixAlpha);
      alphaInput.addEventListener('change', (e) => setAnalysisMixAlpha(e.target.value));
    }
    updateAnalysisControls();  // initial visibility (analysis off → row hidden)
    const confirmCb = document.getElementById('confirm-turn-toggle');
    if (confirmCb) confirmCb.addEventListener('change', (e) => setConfirmTurn(e.target.checked));
    // Global Enter-key handler: when an AI is on the clock, Enter advances
    // one move. Ignored when focus is in a text input (so it doesn't fight
    // the seed prompt or future form inputs). Also ignored on the game-over
    // modal (no AI moves to take).
    document.addEventListener('keydown', (e) => {
      if (bedtimeActive) return;  // bedtime overlay blocks all play
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
    // Bedtime overlay: ask the first name once, then gate on Rob + the Eastern
    // 11 PM–5 AM window. Checked now (covers reloads at/after 11 PM) and every
    // 30 s (covers the clock crossing 11 PM while the page is already open, and
    // lifts the overlay at 5 AM).
    btEnsureName(btCheck);
    setInterval(btCheck, 30000);

    // Load the initial state. From here on, every render comes from an action
    // or toggle response — there is no push channel. The server pre-creates a
    // default Family game; after the first render we pop up the mode-select
    // overlay so the very first thing the user sees is the variant choice
    // (picking one just resets the pre-created game).
    fetch('/api/state').then((r) => r.json()).then((s) => {
      applyState(s);
      resetGame();  // show the mode-select overlay on first load
    }).catch((err) => {
      setConnState(false);
      console.error('initial state fetch failed', err);
    });
  });
})();
