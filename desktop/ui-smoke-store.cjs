/**
 * Conductor store smoke test — verifies the centralized per-datatype data store
 * (frontend/store.js) actually keeps every page consistent after a mutation.
 *
 * Run: CONDUCTOR_URL=http://127.0.0.1:8899/ npx electron ui-smoke-store.cjs
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
  const waitFor = async (expr, timeoutMs = 4000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await q(expr)) return true;
      await new Promise((r) => setTimeout(r, 150));
    }
    return false;
  };

  const SKU = 'SMOKE-' + Date.now();
  try {
    await win.loadURL(URL);
    await new Promise((r) => setTimeout(r, 2500));

    // ---- store layer is wired
    check('store: ConductorStore defined', await q(`typeof window.ConductorStore !== 'undefined'`));
    check('store: ConductorData defined', await q(`typeof window.ConductorData !== 'undefined'`));
    check('store: products + checks preloaded at boot',
      await q(`window.ConductorStore && window.ConductorStore.peek('products') !== null && window.ConductorStore.peek('checks') !== null`));

    // ---- Products & Compliance render the SAME cached set (no "Loading…")
    await q(`showView('products')`);
    await new Promise((r) => setTimeout(r, 600));
    const prodRows = await q(`document.querySelectorAll('#products-body table tbody tr').length`);
    check('products: table renders from store', prodRows > 0, `rows=${prodRows}`);

    await q(`showView('checks')`);
    await new Promise((r) => setTimeout(r, 600));
    const chkRows = await q(`document.querySelectorAll('#checks-body table tbody tr').length`);
    check('checks: table renders from store', chkRows > 0, `rows=${chkRows}`);

    // ---- the fix: a Bulk Import of a product must appear WITHOUT a reload
    const imp = await q(`fetch('/api/import', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ target:'products', mode:'auto', data: 'sku,name,category\\n${SKU},Smoke Widget,general' }) }).then(r => r.json())`);
    check('bulk import: product accepted', imp && (imp.created === 1), JSON.stringify(imp));
    await q(`invalidateWarm()`);   // what bulkimport.js now does after a successful import
    await q(`showView('products')`);
    await new Promise((r) => setTimeout(r, 600));
    const seesNew = await q(`[...document.querySelectorAll('#products-body table tbody tr td.mono')].some(td => td.textContent.trim() === '${SKU}')`);
    check('products: newly imported SKU visible (no reload)', seesNew);

    // ---- and it is in the shared store, not just the view
    const inStore = await q(`(window.ConductorStore.peek('products')||[]).some(p => p.sku === '${SKU}')`);
    check('store: imported SKU in shared products set', inStore);

    // ---- People view reads through the store too (no crash, empty-state ok)
    await q(`showView('people')`);
    await new Promise((r) => setTimeout(r, 600));
    const peopleBody = await q(`!!document.querySelector('#people-body') && !document.querySelector('#people-body').textContent.includes('Loading')`);
    check('people: view renders from store (no loading)', peopleBody);

    // ---- cleanup
    await q(`fetch('/api/products?limit=500').then(r => r.json()).then(list => { const p = list.find(x => x.sku === '${SKU}'); return p ? fetch('/api/products/' + p.id, { method:'DELETE' }).then(() => 'deleted') : 'none'; })`);
    await q(`invalidateWarm()`);

    const errs = consoleErrors.filter((m) => !m.includes('Electron Security Warning'));
    check('no console errors', errs.length === 0, errs.slice(0, 3).join(' | '));
    console.log(failures === 0 ? 'STORE SWEEP OK' : `STORE SWEEP: ${failures} FAILURES`);
  } catch (err) {
    console.error('STORE SWEEP CRASHED:', err);
    failures++;
  } finally {
    app.exit(failures === 0 ? 0 : 1);
  }
});
