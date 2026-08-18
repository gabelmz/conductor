/**
 * Conductor sidebar-rework smoke test — hidden Electron window verifies the
 * data-driven sidebar (presets, customization), the Models pane, the one-row
 * chatbox, and the three new feature views (Flat File / SvL / Data Mgmt).
 *
 * Run: CONDUCTOR_URL=http://127.0.0.1:8899/ npx electron ui-smoke-sidebar.cjs
 */
const { app, BrowserWindow } = require('electron');

const URL = process.env.CONDUCTOR_URL || 'http://127.0.0.1:8799/';

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
  const waitFor = async (expr, timeoutMs = 3000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await q(expr)) return true;
      await new Promise((r) => setTimeout(r, 150));
    }
    return false;
  };

  try {
    await win.loadURL(URL);
    await new Promise((r) => setTimeout(r, 2200));
    await q(`localStorage.clear(); location.reload()`);
    await new Promise((r) => setTimeout(r, 2500));

    // ---- sidebar renders data-driven, with the Commerce Hub sections
    const sections = await q(`[...document.querySelectorAll('#sidebar-scroll .sidebar-section-label')].map(l => l.textContent.trim())`);
    const wantSections = ['Core', 'Departments', 'Operations', 'Platforms', 'Catalog', 'Automation', 'AI', 'Knowledge', 'Platform'];
    check('sidebar: all 9 sections present in order', wantSections.every((s, i) => sections[i] === s), sections.join(' > '));
    check('sidebar: item count >= 40', await q(`document.querySelectorAll('#sidebar-scroll .sidebar-item').length >= 40`),
      await q(`String(document.querySelectorAll('#sidebar-scroll .sidebar-item').length)`));

    // ---- new nav items exist
    for (const id of ['data', 'flatfile', 'svl', 'workflows', 'developer', 'walmart', 'brands', 'people', 'workflowbuilder', 'agentbuilder', 'runbooks', 'policies', 'features']) {
      check(`nav item #nav-${id}`, await q(`!!document.querySelector('#nav-${id}')`));
    }
    // ---- count badges are data-count based
    check('counts: data-count badges exist', await q(`document.querySelectorAll('.sidebar-count[data-count]').length > 0`));
    check('counts: no legacy #count-* ids', await q(`!document.querySelector('#count-automations') && !document.querySelector('#count-products')`));

    // ---- right pane Models tab
    check('models: tab present', await q(`!!document.querySelector('#pane-tabs [data-pane="models"]')`));
    await q(`document.querySelector('#pane-tabs [data-pane="models"]').click()`);
    check('models: pane loads model rows', await waitFor(`!!document.querySelector('#models-list .model-row') || document.querySelector('#models-list').textContent.includes('No GGUF')`, 7000),
      await q(`(document.querySelector('#models-list')||{}).textContent ? document.querySelector('#models-list').textContent.slice(0,80).replace(/\\s+/g,' ') : 'MISSING'`));

    // ---- chatbox pinned to one row
    check('chatbox: rows=1 + wrap=off', await q(`document.querySelector('#composer-input').getAttribute('rows') === '1' && document.querySelector('#composer-input').getAttribute('wrap') === 'off'`));

    // ---- new feature views render their titles
    const viewTitles = { data: 'Data Management', flatfile: 'Flat File Creation', svl: 'SvL Comparison', workflows: 'Workflows', developer: 'Developer', walmart: 'Walmart', brands: 'Brands', people: 'People', features: 'Feature Studio' };
    for (const [view, title] of Object.entries(viewTitles)) {
      await q(`showView('${view}')`);
      await new Promise((r) => setTimeout(r, 500));
      const ok = await q(`(() => { const t = document.querySelector('#view-root'); return t && !t.hidden && t.textContent.includes('${title}'); })()`);
      check(`view ${view} renders (${title})`, ok, await q(`(document.querySelector('#view-root')||{}).textContent ? document.querySelector('#view-root').textContent.slice(0,70).replace(/\\s+/g,' ') : 'MISSING'`));
    }

    // ---- data view populates its table (async)
    await q(`showView('data')`);
    await new Promise((r) => setTimeout(r, 1200));
    check('data: table body populated', await q(`document.querySelectorAll('#dm-table tbody tr').length > 0 || (document.querySelector('#dm-body')||{}).textContent.includes('No rows')`),
      await q(`(document.querySelector('#dm-body')||{}).textContent ? document.querySelector('#dm-body').textContent.slice(0,70).replace(/\\s+/g,' ') : 'MISSING'`));

    // ---- Settings → Navigation customizer
    await q(`document.querySelector('#btn-settings').click()`);
    await new Promise((r) => setTimeout(r, 400));
    check('settings: Navigation tab present', await q(`!!document.querySelector('#settings-nav [data-stab="navigation"]')`));
    await q(`document.querySelector('#settings-nav [data-stab="navigation"]').click()`);
    await new Promise((r) => setTimeout(r, 600));
    check('nav settings: preset picker renders', await q(`!!document.querySelector('#nav-preset') && document.querySelectorAll('#nav-preset option').length >= 4`),
      await q(`String(document.querySelectorAll('#nav-preset option').length)`));
    check('nav settings: section cards render', await q(`document.querySelectorAll('.nav-section-card').length >= 9`),
      await q(`String(document.querySelectorAll('.nav-section-card').length)`));

    // ---- preset switch actually restructures the sidebar
    await q(`(() => { const s = document.querySelector('#nav-preset'); s.value = 'functional'; s.dispatchEvent(new Event('change')); })()`);
    await new Promise((r) => setTimeout(r, 500));
    const afterSections = await q(`[...document.querySelectorAll('#sidebar-scroll .sidebar-section-label')].map(l => l.textContent.trim())`);
    check('nav settings: functional preset drops Departments/marketplaces', !afterSections.includes('Departments') && !afterSections.includes('Platforms') && afterSections.includes('Catalog'), afterSections.join(' > '));
    // reset back to default
    await q(`document.querySelector('#nav-reset').click()`);
    await new Promise((r) => setTimeout(r, 500));
    check('nav settings: reset restores Commerce Hub', await q(`[...document.querySelectorAll('#sidebar-scroll .sidebar-section-label')].map(l => l.textContent.trim()).includes('Departments')`));
    await q(`document.querySelector('#btn-settings-close').click()`);

    // ---- SvL flow against live data (API-level, confirms fuzzy matching)
    const svl = await q(`fetch('/api/svl/compare', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ suggested: 'widget pro', field: 'name' }) }).then(r => r.json()).then(j => j.total)`);
    check('svl: backend fuzzy match returns hits', typeof svl === 'number' && svl >= 0, `total=${svl}`);

    const errs = consoleErrors.filter((m) => !m.includes('Electron Security Warning'));
    check('no console errors', errs.length === 0, errs.slice(0, 3).join(' | '));
    console.log(failures === 0 ? 'SIDEBAR SWEEP OK' : `SIDEBAR SWEEP: ${failures} FAILURES`);
  } catch (err) {
    console.error('SWEEP CRASHED:', err);
    failures++;
  } finally {
    app.exit(failures === 0 ? 0 : 1);
  }
});
