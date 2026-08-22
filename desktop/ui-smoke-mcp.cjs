/** Conductor MCP & Sync Hub smoke test. */
const { app, BrowserWindow } = require('electron');
const URL = process.env.CONDUCTOR_URL || 'http://127.0.0.1:8899/';

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 1440, height: 1000 });
  const q = (expr) => win.webContents.executeJavaScript(expr);
  let failures = 0;
  const errors = [];
  win.webContents.on('console-message', (_e, level, message) => { if (level >= 3) errors.push(message); });
  const check = (label, ok, detail = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ' — ' + detail : ''}`); if (!ok) failures++; };
  const waitFor = async (expr, ms = 10000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) { if (await q(expr)) return true; await new Promise(r => setTimeout(r, 150)); }
    return false;
  };
  try {
    await win.loadURL(URL);
    check('sync nav present', await waitFor(`!!document.querySelector('#nav-mcpsync')`));
    await q(`showView('mcpsync')`);
    check('sync hub rendered', await waitFor(`!!document.querySelector('#mcp-sync-view')`));
    check('Asana MCP loaded', await waitFor(`document.querySelectorAll('[data-testid="mcp-server-card"]').length === 1`, 15000));
    check('Supabase config form', await q(`!!document.querySelector('#supabase-config-form')`));
    check('product push/pull', await q(`!!document.querySelector('#sync-products-push') && !!document.querySelector('#sync-products-pull')`));
    check('Asana push/pull', await q(`!!document.querySelector('#sync-asana-push') && !!document.querySelector('#sync-asana-pull')`));
    const visibleSecret = await q(`document.body.innerText.includes('ASANA_ACCESS_TOKEN') || document.body.innerText.includes('service_role')`);
    check('no credential material rendered', !visibleSecret);
    const realErrors = errors.filter(e => !e.includes('Electron Security Warning'));
    check('no console errors', realErrors.length === 0, realErrors.slice(0, 2).join(' | '));
    console.log(failures ? `MCP SYNC SWEEP: ${failures} FAILURES` : 'MCP SYNC SWEEP OK');
  } catch (error) { console.error(error); failures++; }
  finally { app.exit(failures ? 1 : 0); }
});
