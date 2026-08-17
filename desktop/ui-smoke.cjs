/**
 * Conductor UI sweep test — hidden Electron window drives the merged frontend.
 *
 * Clicks through every sidebar view and every settings tab, capturing console
 * errors along the way. Run with:
 *   npx electron ui-smoke.cjs          (backend must be up, default port 8799)
 */
const { app, BrowserWindow } = require('electron');

const URL = process.env.CONDUCTOR_URL || 'http://127.0.0.1:8799/';
const VIEWS = ['dashboard', 'processes', 'automations', 'ai', 'sops', 'integrations',
  'asana', 'events', 'requests', 'checks', 'products', 'catalog', 'agents', 'tasks', 'regs', 'variation'];
const TABS = ['appearance', 'chat', 'asana', 'layout', 'advanced', 'about'];

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 1440, height: 900 });
  const q = (expr) => win.webContents.executeJavaScript(expr);
  const consoleErrors = [];
  win.webContents.on('console-message', (e, level, message) => {
    if (level >= 3) consoleErrors.push(message.slice(0, 200));
  });
  let failures = 0;

  const check = (label, ok, detail) => {
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ' — ' + detail : ''}`);
    if (!ok) failures++;
  };
  const waitFor = async (expr, timeoutMs = 2500) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await q(expr)) return true;
      await new Promise((r) => setTimeout(r, 150));
    }
    return false;
  };

  try {
    await win.loadURL(URL);
    await new Promise((r) => setTimeout(r, 2500));
    await q(`localStorage.clear(); location.reload()`);
    await new Promise((r) => setTimeout(r, 2500));

    check('boot: chat starts clean (no preset)', await q(`!document.querySelector('.msg-agent') && !!document.querySelector('#composer-input')`));
    check('nav: Operations above Automate', await q(`(() => { const labels = [...document.querySelectorAll('.sidebar-section-label')].map((l) => l.textContent.trim()); return labels.indexOf('Operations') < labels.indexOf('Automate'); })()`),
      await q(`[...document.querySelectorAll('.sidebar-section-label')].map((l) => l.textContent.trim()).join(' > ')`));
    check('boot: sidebar counts populated', await q(`Number(document.querySelector('#count-automations').textContent) > 0`));
    check('boot: folder tree loaded', await waitFor(`document.querySelectorAll('#folder-tree .folder-row').length > 0 || document.querySelectorAll('#folder-tree .file-row').length > 0`, 4000));
    check('default theme: nous + light', await q(`document.documentElement.dataset.theme === 'nous' && document.documentElement.dataset.mode === 'light'`),
      await q(`JSON.stringify({ theme: document.documentElement.dataset.theme, mode: document.documentElement.dataset.mode })`));
    check('default edges: 4px radius', await q(`getComputedStyle(document.documentElement).getPropertyValue('--t-edges-radius').trim() === '4'`),
      await q(`getComputedStyle(document.documentElement).getPropertyValue('--t-edges-radius')`));
    check('sidebar spacing: item rhythm', await q(`(() => { const i = document.querySelector('#nav-chat'); const l = document.querySelector('.sidebar-section-gap'); const s = document.querySelector('.sidebar-search'); const cs = getComputedStyle(i); return cs.padding === '4.5px 8px' && getComputedStyle(l).marginTop === '8px' && getComputedStyle(s).marginBottom === '7px'; })()`),
      await q(`(() => { const i = getComputedStyle(document.querySelector('#nav-chat')); const l = getComputedStyle(document.querySelector('.sidebar-section-gap')); return JSON.stringify({ item: i.padding, gap: l.marginTop }); })()`));

    // ---- every sidebar view
    for (const view of VIEWS) {
      const nav = `document.querySelector('#nav-${view}')`;
      const exists = await q(`!!${nav}`);
      if (!exists) { check(`nav item ${view}`, false, 'missing nav button'); continue; }
      await q(`${nav}.click()`);
      await new Promise((r) => setTimeout(r, 700));
      const ok = await q(`(() => {
        const vr = document.querySelector('#view-root');
        if (!vr || vr.hidden) return false;
        const empty = !!vr.querySelector('.empty-state');
        const loading = !!vr.querySelector('.folder-loading');
        const title = vr.querySelector('.view-title, .msg-agent');
        return !!title || empty || loading;
      })()`);
      check(`view ${view} renders`, ok, `view-root: ${await q(`document.querySelector('#view-root') ? document.querySelector('#view-root').textContent.slice(0, 60).replace(/\\s+/g, ' ') : 'MISSING'`)}`);
    }

    // ---- statusbar-triggered views: Report Management + Attribute Guidelines
    check('statusbar: reports + guidelines icons present', await q(`!!document.querySelector('#btn-reports') && !!document.querySelector('#btn-guidelines')`));
    await q(`document.querySelector('#btn-reports').click()`);
    await new Promise((r) => setTimeout(r, 700));
    check('reports: view renders', await q(`!!document.querySelector('#view-root .view-title') && document.querySelector('#view-root .view-title').textContent.includes('Report Management')`),
      await q(`document.querySelector('#view-root').textContent.slice(0, 60).replace(/\\s+/g, ' ')`));
    await q(`document.querySelector('#btn-guidelines').click()`);
    await new Promise((r) => setTimeout(r, 700));
    check('guidelines: view renders', await q(`!!document.querySelector('#view-root .view-title') && document.querySelector('#view-root .view-title').textContent.includes('Attribute Guidelines')`),
      await q(`document.querySelector('#view-root').textContent.slice(0, 60).replace(/\\s+/g, ' ')`));

    // ---- bernie canvas: full-page environment + build + run end-to-end
    await q(`document.querySelector('#nav-bernie').click()`);
    await new Promise((r) => setTimeout(r, 800));
    check('bernie: fullscreen mode active', await q(`document.body.classList.contains('bernie-fullscreen')`));
    check('bernie: app sidebar hidden', await q(`getComputedStyle(document.querySelector('#sidebar')).display === 'none'`));
    check('bernie: canvas renders', await q(`!!document.querySelector('#bernie-canvas-inner') && !!document.querySelector('#bernie-svg') && !!document.querySelector('#bn-grid-layer')`));
    check('bernie: panels default flat', await q(`document.querySelector('#bn-left-panel').dataset.mode === 'flat' && document.querySelector('#bn-right-panel').dataset.mode === 'flat'`));
    check('bernie: theme presets present', await q(`document.querySelectorAll('#bn-theme-presets .bn-preset').length >= 16`),
      await q(`String(document.querySelectorAll('#bn-theme-presets .bn-preset').length)`));

    for (const t of ['trigger', 'text', 'script', 'flush']) {
      await q(`document.querySelector('.bn-add[data-type="${t}"]').click()`);
    }
    await new Promise((r) => setTimeout(r, 300));
    await q(`bernieAddNode('custom')`);
    check('bernie: 5 nodes added (incl. custom type)', await q(`bernieState.nodes.length === 5 && bernieState.nodes.some(n => n.type === 'custom')`),
      await q(`JSON.stringify(bernieState.nodes.map(n => n.type))`));
    await q(`(() => {
      const n = bernieState.nodes.find(x => x.type === 'text');
      n.data.text = 'hello bernie merge';
      const s = bernieState.nodes.find(x => x.type === 'script');
      s.data.script = 'return { shout: String(data && data.text ? data.text : JSON.stringify(data || {})).toUpperCase() + "!" }';
      bernieState.edges = [];
      const byType = t => bernieState.nodes.find(x => x.type === t).id;
      bernieState.edges.push({ source: byType('trigger'), target: byType('text') });
      bernieState.edges.push({ source: byType('text'), target: byType('script') });
      bernieState.edges.push({ source: byType('script'), target: byType('flush') });
      bernieRenderCanvas();
      return bernieState.edges.length;
    })()`);
    await new Promise((r) => setTimeout(r, 300));
    check('bernie: 3 edges drawn', await q(`document.querySelectorAll('#bernie-svg path.bernie-edge').length === 3`));
    await q(`document.querySelector('#bn-run').click()`);
    await new Promise((r) => setTimeout(r, 1200));
    check('bernie: wired nodes succeeded (custom stays idle)', await q(`['trigger','text','script','flush'].every(t => { const n = bernieState.nodes.find(x => x.type === t); return n && n.status === 'success'; }) && bernieState.nodes.find(x => x.type === 'custom').status === 'idle'`),
      await q(`JSON.stringify(bernieState.nodes.map(n => n.type + ':' + n.status))`));
    check('bernie: flush shows output', await q(`document.querySelector('#bernie-flush') ? document.querySelector('#bernie-flush').textContent.includes('HELLO BERNIE MERGE') : false`));
    check('bernie: output drawer opened on run', await q(`!document.querySelector('#bn-output-row').hidden`));

    // ---- theme environment: preset applies live + persists
    await q(`[...document.querySelectorAll('#bn-theme-presets .bn-preset')].find(b => b.dataset.key === 'cyberpunk').click()`);
    await new Promise((r) => setTimeout(r, 400));
    check('bernie: theme preset applies live', await q(`getComputedStyle(document.querySelector('.bernie-view')).getPropertyValue('--bn-highlight').trim() === '#ff003c'`),
      await q(`getComputedStyle(document.querySelector('.bernie-view')).getPropertyValue('--bn-highlight')`));
    check('bernie: theme persists to localStorage', await q(`JSON.parse(localStorage.getItem('conductor.bernie.theme')).highlight === '#ff003c'`));

    // ---- grid flyout: pattern switch rewrites the grid layer
    await q(`document.querySelector('#bn-grid-btn').click()`);
    await new Promise((r) => setTimeout(r, 300));
    check('bernie: grid flyout opens', await q(`!document.querySelector('#bn-grid-flyout').hidden`));
    await q(`document.querySelector('#bn-grid-flyout .bn-pattern-btn[data-pat="lines"]').click()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: grid pattern changes background', await q(`getComputedStyle(document.querySelector('#bn-grid-layer')).backgroundImage.includes('linear-gradient')`),
      await q(`getComputedStyle(document.querySelector('#bn-grid-layer')).backgroundImage.slice(0, 80)`));
    await q(`document.querySelector('#bn-grid-flyout .bn-flyout-close').click()`);

    // ---- minimap flyout: enable + render
    await q(`document.querySelector('#bn-map-btn').click()`);
    await new Promise((r) => setTimeout(r, 300));
    await q(`(() => { const c = document.querySelector('#bn-m-show'); c.checked = true; c.dispatchEvent(new Event('change')); })()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: minimap renders', await q(`!document.querySelector('#bn-minimap').hidden && document.querySelectorAll('#bn-minimap-box .bn-mm-node').length === 5`));
    await q(`document.querySelector('#bn-map-flyout .bn-flyout-close').click()`);

    // ---- zoom controls
    await q(`document.querySelector('#bn-zoom-in').click()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: zoom applies', await q(`document.querySelector('#bn-zoom-label').textContent !== '100%' && bernieView.zoom > 1`),
      await q(`document.querySelector('#bn-zoom-label').textContent`));
    await q(`document.querySelector('#bn-zoom-fit').click()`);

    // ---- select mode: click-node select + selection bar + duplicate
    await q(`(() => { bernieView.selectMode = true; document.querySelector('.bnode').dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 })); return bernieView.selected.size; })()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: select mode selects node', await q(`bernieView.selected.size === 1 && !document.querySelector('#bn-selection-bar').hidden`));
    await q(`document.querySelector('#bn-dup-sel').click()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: duplicate selected node', await q(`bernieState.nodes.length === 6`), await q(`String(bernieState.nodes.length)`));

    // ---- context menu: inspect opens modal
    await q(`document.querySelector('.bnode').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 420, clientY: 320 }))`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: context menu opens', await q(`!document.querySelector('#bn-context-menu').hidden`));
    await q(`document.querySelector('#bn-context-menu button[data-act="inspect"]').click()`);
    await new Promise((r) => setTimeout(r, 300));
    check('bernie: inspect dialog opens', await q(`!!document.querySelector('#modal-backdrop') && !document.querySelector('#modal-backdrop').hidden`),
      await q(`!!document.querySelector('#bn-inspect-close')`));
    await q(`document.querySelector('#bn-inspect-close').click()`);

    // ---- panel float/dock toggle (default flat, persists)
    await q(`document.querySelector('#bn-right-float').click()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: right panel floats', await q(`document.querySelector('#bn-right-panel').dataset.mode === 'floating'`));
    await q(`document.querySelector('#bn-right-float').click()`);
    await new Promise((r) => setTimeout(r, 200));
    check('bernie: right panel re-docks flat', await q(`document.querySelector('#bn-right-panel').dataset.mode === 'flat'`));

    // ---- save + library + exit
    await q(`document.querySelector('#bernie-name').value = 'Sweep canvas'`);
    await q(`bernieState.name = 'Sweep canvas'`);
    await q(`document.querySelector('#bn-save').click()`);
    await new Promise((r) => setTimeout(r, 900));
    check('bernie: canvas saved', await q(`bernieState.canvasId != null`));
    check('bernie: library lists canvas', await q(`document.querySelectorAll('#bn-library .bn-lib-row').length >= 1`));
    await q(`document.querySelector('#bn-exit').click()`);
    await new Promise((r) => setTimeout(r, 400));
    check('bernie: exit leaves fullscreen', await q(`!document.body.classList.contains('bernie-fullscreen')`));
    await q(`document.querySelector('#nav-bernie').click()`);
    await new Promise((r) => setTimeout(r, 600));
    check('bernie: re-entering restores fullscreen', await q(`document.body.classList.contains('bernie-fullscreen')`));

    // ---- settings tabs
    await q(`document.querySelector('#btn-settings').click()`);
    await new Promise((r) => setTimeout(r, 400));
    for (const tab of TABS) {
      const btn = `document.querySelector('#settings-nav .settings-nav-item[data-stab="${tab}"]')`;
      const exists = await q(`!!${btn}`);
      if (!exists) { check(`settings tab ${tab}`, false, 'missing nav button'); continue; }
      await q(`${btn}.click()`);
      await new Promise((r) => setTimeout(r, 500));
      const ok = await q(`(() => {
        const box = document.querySelector('#settings-content');
        return box && box.textContent.trim().length > 40;
      })()`);
      let detail = '';
      if (tab === 'appearance') {
        detail = await q(`JSON.stringify({cards: document.querySelectorAll('#theme-grid .theme-card').length, tokenGroups: document.querySelectorAll('#token-editor .token-group').length, preview: !!document.querySelector('#ui-preview'), skins: !!document.querySelector('#skins-list')})`);
      }
      if (tab === 'advanced') {
        detail = await q(`JSON.stringify({editorHasTokens: document.querySelector('#ui-json-editor') ? document.querySelector('#ui-json-editor').value.includes('background1') : false})`);
      }
      check(`settings tab ${tab}`, ok, detail);
    }
    await q(`document.querySelector('#btn-settings-close').click()`);

    // ---- appearance interaction: switch preset, token edit applies live
    await q(`document.querySelector('#btn-settings').click()`);
    await new Promise((r) => setTimeout(r, 400));
    await q(`document.querySelector('#settings-nav .settings-nav-item[data-stab="appearance"]').click()`);
    await new Promise((r) => setTimeout(r, 500));
    const presetCount = await q(`document.querySelectorAll('#theme-grid .theme-card').length`);
    check('appearance: preset cards present', presetCount >= 7, `${presetCount} cards`);
    check('appearance: solarized dune preset present', await q(`!!document.querySelector('#theme-grid .theme-card[data-theme="dune"]')`));
    check('panel style: glass off by default', await q(`!document.body.classList.contains('glass')`));
    await q(`document.querySelector('#s-glass').click()`);
    await new Promise((r) => setTimeout(r, 150));
    check('panel style: glass toggle applies body.glass', await q(`document.body.classList.contains('glass')`));
    await q(`document.querySelector('#s-glass').click()`);
    await new Promise((r) => setTimeout(r, 150));
    check('panel style: glass toggle removes body.glass', await q(`!document.body.classList.contains('glass')`));
    await q(`[...document.querySelectorAll('#theme-grid .theme-card')].find(c => c.dataset.theme !== 'custom').click()`);
    await new Promise((r) => setTimeout(r, 600));
    const themeApplied = await q(`document.documentElement.dataset.theme !== 'custom'`);
    check('appearance: preset applies live', themeApplied, `dataset.theme=${await q(`document.documentElement.dataset.theme`)}`);
    const firstColor = await q(`document.querySelector('#token-editor .swatch input[type=color]')`);
    check('appearance: token editor has color rows', !!firstColor);
    await q(`document.querySelector('#btn-settings-close').click()`);

    // ---- nav collapse states still work after merge
    await q(`document.querySelector('#btn-side-collapse').click()`);
    const railOk = await waitFor(`document.body.classList.contains('sidebar-rail') && document.querySelector('.sidebar').getBoundingClientRect().width < 60`);
    check('nav: rail', railOk, railOk ? '' : await q(`JSON.stringify({ cls: document.body.className, w: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width), inline: document.querySelector('.sidebar').getAttribute('style'), btnHidden: document.querySelector('#btn-side-collapse').hidden, stateSidebar: state.sidebar, dur: getComputedStyle(document.documentElement).getPropertyValue('--motion-dur') })`));
    // Cascade check (deterministic, no font-load dependency): rail items must keep
    // icons visible while labels are hidden. Glyph width is reported for observability
    // but not required — headless runs can fail the TTF fetch (font-display:block → 0-width).
    const railIconOk = await q(`(() => {
      const ic = document.querySelector('#nav-chat').querySelector('.codicon');
      const lbl = document.querySelector('#nav-chat').querySelectorAll('span')[1];
      return getComputedStyle(ic).display !== 'none' && getComputedStyle(lbl).display === 'none';
    })()`);
    check('nav: rail shows icons (labels hidden)', railIconOk, await q(`(() => { const ic = document.querySelector('#nav-chat').querySelector('.codicon'); return JSON.stringify({ iconDisplay: getComputedStyle(ic).display, iconW: Math.round(ic.getBoundingClientRect().width), labelDisplay: getComputedStyle(document.querySelector('#nav-chat').querySelectorAll('span')[1]).display, codiconLoaded: document.fonts.check('16px codicon') }); })()`));
    await q(`document.querySelector('#btn-side-tuck').click()`);
    check('nav: tucked', await waitFor(`document.body.classList.contains('sidebar-tucked') && getComputedStyle(document.querySelector('#side-tab')).display === 'flex'`));
    await q(`document.querySelector('#side-tab').click()`);
    check('nav: restored', await waitFor(`!document.body.classList.contains('sidebar-tucked') && !document.body.classList.contains('sidebar-rail')`));

    // ---- product round-trip via UI composer path (API-level)
    const prod = await q(`fetch('/api/products', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sku: 'SMOKE-1', name: 'Smoke Test Widget', category: 'electronics', market: 'US', attributes: { wireless: false } }) }).then(r => r.json()).then(j => j.product ? j.product.id : null)`);
    check('product round-trip (backend)', !!prod, `id=${prod}`);
    if (prod) {
      await q(`fetch('/api/products/${prod}', { method: 'DELETE' })`);
    }

    // ---- LAW ports: palette, hub, split, ingest, composer bar
    await q(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))`);
    check('palette: opens on Ctrl+K', await waitFor(`!!document.querySelector('.palette-overlay')`));
    check('palette: built-in commands listed', await q(`document.querySelectorAll('.palette-item').length >= 10`),
      await q(`String(document.querySelectorAll('.palette-item').length)`));
    await q(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`);
    check('palette: closes on Esc', await waitFor(`!document.querySelector('.palette-overlay')`));

    await waitFor(`!!document.querySelector('#nav-hub')`, 5000); // plugin page nav
    await q(`document.querySelector('#nav-hub').click()`);
    await new Promise((r) => setTimeout(r, 700));
    check('hub: Tool Hub view renders (plugin page)', await q(`!!document.querySelector('#view-root .view-title') && document.querySelector('#view-root .view-title').textContent.includes('Tool Hub')`),
      await q(`document.querySelector('#view-root') ? document.querySelector('#view-root').textContent.slice(0, 80).replace(/\\s+/g, ' ') : 'MISSING'`));
    check('hub: cards render (core-hub seeded)', await q(`document.querySelectorAll('#hub-grid .hub-card').length >= 1`));

    await q(`document.querySelector('#nav-ingest').click()`);
    await new Promise((r) => setTimeout(r, 600));
    check('ingest: Catalog Ingest view renders', await q(`!!document.querySelector('#view-root .view-title') && document.querySelector('#view-root .view-title').textContent.includes('Catalog Ingest')`));

    await q(`window.ConductorSplit.enter('dashboard')`);
    await new Promise((r) => setTimeout(r, 600));
    check('split: split-mode active (chat + dashboard)', await q(`document.body.classList.contains('split-mode') && !document.querySelector('#thread-scroll').hidden && !document.querySelector('#view-root').hidden`));
    check('split: divider present + draggable wiring', await q(`!!document.querySelector('#split-divider') && document.querySelector('#split-divider').dataset.wired === '1'`));
    await q(`window.ConductorSplit.exit()`);
    await new Promise((r) => setTimeout(r, 400));
    check('split: exit restores full view', await q(`!document.body.classList.contains('split-mode')`));

    check('composer: AI bar hidden with no keyed providers', await q(`document.querySelector('#composer-ai').hidden === true`));
    check('composer: attach button intact', await q(`!!document.querySelector('#btn-attach')`));
    const skillPop = await q(`(async () => {
      const btn = document.querySelector('#btn-skills');
      if (!btn) return false;
      btn.click();
      await new Promise((r) => setTimeout(r, 250));
      const pop = document.querySelector('#skills-popover');
      const n = pop.querySelectorAll('.skill-row').length;
      const open = !pop.hidden;
      const first = pop.querySelector('.skill-row');
      if (first) first.click();
      await new Promise((r) => setTimeout(r, 150));
      const chips = document.querySelectorAll('#chat-context .ctx-chip').length;
      btn.click();
      return open && n >= 3 && chips >= 1;
    })()`);
    check('skills: popover lists skills + toggle chip', skillPop,
      await q(`JSON.stringify({ skillRows: document.querySelectorAll('#skills-popover .skill-row').length, chips: document.querySelectorAll('#chat-context .ctx-chip').length })`));

    const errs = consoleErrors.filter((m) => !m.includes('Electron Security Warning'));
    check('no console errors', errs.length === 0, errs.slice(0, 3).join(' | '));
    console.log(failures === 0 ? 'SWEEP TEST OK' : `SWEEP TEST: ${failures} FAILURES`);
  } catch (err) {
    console.error('SWEEP CRASHED:', err);
    failures++;
  } finally {
    app.exit(failures === 0 ? 0 : 1);
  }
});
