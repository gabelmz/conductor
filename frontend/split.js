/* Conductor — split-pane workspace (LAW's PaneManager ported to vanilla JS).
 *
 * Conflict-resolved design (per research): an OPT-IN max-2-pane split —
 * chat always on one side, one other view on the other — layered on the
 * existing view system. OFF by default; per-view persisted in localStorage
 * key 'conductor.split' = { view: name, direction, sizes: [a,b] }.
 *
 * LAW semantics ported verbatim:
 *   - divider drag resizes only the adjacent pair (the two panes)
 *   - MIN_FRACTION clamp of 0.08 (LAW Splitter.tsx)
 *   - closing the split collapses it (no phantom divider)
 *   - improvement over LAW: sizes ARE persisted (LAW drops them on save)
 * Bernie is excluded — it owns the full window by design.
 *
 * Rendering: CSS-grid overlay on the existing layout — no DOM moves. Body
 * gets `split-mode`, .thread becomes a 3-column grid (chat | divider | view).
 */
(function () {
  const KEY = 'conductor.split';
  const MIN_FRACTION = 0.08;

  let state = load();

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY));
      if (s && s.view && Array.isArray(s.sizes) && s.sizes.length === 2) return s;
    } catch { /* */ }
    return { view: null, direction: 'horizontal', sizes: [0.55, 0.45] };
  }

  function save() { localStorage.setItem(KEY, JSON.stringify(state)); }

  function isActive() { return Boolean(state.view); }
  function activeView() { return state.view; }

  function setDirection(dir) {
    state.direction = dir === 'vertical' ? 'vertical' : 'horizontal';
    save();
    apply();
  }

  /* Called from showView when split mode is active. Returns true when the
   * navigation was consumed (view rendered into the right pane). */
  function handleNav(name) {
    if (name === 'bernie') { exit(); return false; } // Bernie takes the window
    state.view = name;
    save();
    apply();
    return true;
  }

  function enter(viewName) {
    state.view = viewName || state.view || 'dashboard';
    save();
    apply();
  }

  function exit() {
    state.view = null;
    save();
    apply();
  }

  function apply() {
    document.body.classList.toggle('split-mode', isActive());
    const viewRoot = document.getElementById('view-root');
    if (!viewRoot) return;
    if (!isActive()) return;

    const name = state.view;
    // chat pane always visible in split mode
    document.getElementById('thread-scroll').hidden = false;
    document.getElementById('composer-shell').hidden = false;
    viewRoot.hidden = false;

    const total = state.sizes[0] + state.sizes[1] || 1;
    const a = Math.max(MIN_FRACTION, Math.min(1 - MIN_FRACTION, state.sizes[0] / total));
    const b = 1 - a;
    document.body.style.setProperty('--split-a', `${(a * 100).toFixed(2)}%`);
    document.body.style.setProperty('--split-b', `${(b * 100).toFixed(2)}%`);
    document.body.style.setProperty('--split-dir', state.direction === 'vertical' ? 'column' : 'row');

    const title = document.getElementById('split-view-title');
    if (title) {
      const label = { chat: 'Chat', dashboard: 'Dashboard', processes: 'Process Discovery', automations: 'Automations', ai: 'AI Workflows', sops: 'SOPs', bernie: 'Flow Canvas', checks: 'Checks', products: 'Products', catalog: 'Catalog', agents: 'Agents', tasks: 'Tasks', regs: 'Regulations', integrations: 'Integrations', asana: 'Asana', events: 'Events', requests: 'HTTP Requests', hub: 'Tool Hub', ingest: 'Catalog Ingest' }[name] || name;
      title.textContent = label;
    }
    if (typeof renderView === 'function') renderView(name);
  }

  /* ---- divider drag (adjacent-pair resize, 8% clamp) ---- */
  function wireDivider() {
    const divider = document.getElementById('split-divider');
    if (!divider || divider.dataset.wired) return;
    divider.dataset.wired = '1';
    let dragging = false;
    divider.addEventListener('pointerdown', (e) => {
      dragging = true;
      divider.setPointerCapture(e.pointerId);
    });
    divider.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const rect = document.getElementById('thread').getBoundingClientRect();
      const frac = state.direction === 'vertical'
        ? (e.clientY - rect.top) / rect.height
        : (e.clientX - rect.left) / rect.width;
      const clamped = Math.max(MIN_FRACTION, Math.min(1 - MIN_FRACTION, frac));
      state.sizes = [clamped, 1 - clamped];
      apply();
    });
    divider.addEventListener('pointerup', () => { dragging = false; save(); });
    divider.addEventListener('pointercancel', () => { dragging = false; save(); });
  }

  function init() {
    // one-time DOM: divider element lives inside #thread (CSS grid handles layout)
    const thread = document.getElementById('thread');
    if (thread && !document.getElementById('split-divider')) {
      const divider = document.createElement('div');
      divider.id = 'split-divider';
      divider.title = 'Drag to resize · double-click to end split';
      divider.addEventListener('dblclick', exit);
      thread.appendChild(divider);
    }
    wireDivider();
    // restore active split on boot
    if (isActive()) apply();
  }

  /* ---- expose to app.js + palette ---- */
  window.ConductorSplit = {
    isActive,
    activeView,
    enter,
    exit,
    handleNav,
    setDirection,
    get state() { return state; },
    init,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
