/**
 * Conductor — Electron main process.
 *
 * Boots the FastAPI backend (venv python + uvicorn) on a free port,
 * opens a native BrowserWindow loading the Hermes-style UI, and wires
 * the titlebar controls (min/max/close) over IPC.
 */
const { app, BrowserWindow, ipcMain, shell, dialog, safeStorage } = require('electron');
const { spawn, spawnSync } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');

// ---------------------------------------------------------------------------
// Locate the backend venv python relative to the packaged app
// ---------------------------------------------------------------------------
function findBackend() {
  const here = __dirname; // inside app.asar
  // Packaged layout: <app>/resources/app.asar  +  backend/ + .venv/ next to it
  const resources = path.dirname(here);
  const appRoot = path.dirname(resources); // the unpacked dir
  const devRoot = path.join(__dirname, '..'); // dev layout: desktop/ + backend/

  const candidates = [
    // packaged: <root>/venv/Scripts/python.exe
    path.join(appRoot, 'venv', 'Scripts', 'python.exe'),
    path.join(appRoot, '.venv', 'Scripts', 'python.exe'),
    // dev: compliance-agent/.venv/Scripts/python.exe
    path.join(devRoot, '.venv', 'Scripts', 'python.exe'),
    path.join(devRoot, 'venv', 'Scripts', 'python.exe'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return { python: c, appRoot: fs.existsSync(path.join(appRoot, 'backend')) ? appRoot : devRoot };
  }
  return null;
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

let backendProc = null;
let backendPort = 8790;
let win = null;
let autoUpdater = null; // electron-updater instance, module scope so IPC can reach it
let downloadedVersion = null; // version of a fully-downloaded update, persisted for renderer reconciliation

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadStatus(msg) {
  try { win?.webContents.send('load:status', msg); } catch { /* window gone */ }
}

// Kill the backend AND its whole process tree so nothing keeps running after
// the window closes. On Windows `child.kill()` only terminates the direct
// python process; the backend can spawn its own children (e.g. the local
// llama.cpp server, or a uvicorn reloader) which would otherwise be orphaned
// and leave their ports bound forever.
function killBackend() {
  const proc = backendProc;
  backendProc = null;
  if (!proc || proc.killed) return;
  const pid = proc.pid;
  if (process.platform === 'win32' && pid) {
    try {
      // /T kills the tree, /F forces (no graceful-dialog hang), windowsHide
      // stops a console window flashing at shutdown.
      spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      return;
    } catch { /* fall through to a plain kill */ }
  }
  try { proc.kill(); } catch { /* already gone */ }
}

async function startBackend() {
  const backend = findBackend();
  if (!backend) {
    dialog.showErrorBox('Conductor', 'Could not locate the backend Python environment.\nRun the app from the project folder or reinstall.');
    app.quit();
    return null;
  }
  backendPort = await findFreePort();

  const env = { ...process.env };
  const cwd = backend.appRoot;
  // Backend logs go to <appRoot>/data/backend.log — keep the Electron console silent.
  const dataDir = path.join(backend.appRoot, 'data');
  fs.mkdirSync(dataDir, { recursive: true });
  const logStream = fs.createWriteStream(path.join(dataDir, 'backend.log'), { flags: 'a' });
  // Keep the last chunk of log lines in memory so a failed boot is diagnosable.
  const logTail = [];
  const capture = (d) => { logStream.write(d); logTail.push(String(d)); if (logTail.length > 60) logTail.shift(); };
  // Make sure the app can find backend/ modules
  backendProc = spawn(backend.python, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(backendPort), '--no-access-log', '--log-level', 'warning'], {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  const child = backendProc;
  child.stdout.on('data', capture);
  child.stderr.on('data', capture);
  child.on('exit', (code) => {
    logStream.write(`[backend] exited code=${code}\n`);
    if (backendProc === child) backendProc = null;
  });

  // Wait for the backend to answer /api/health. First launch of the portable
  // extracts ~100MB and antivirus scans it, so be generous (90s) and tell the
  // user what's happening instead of looking hung.
  loadStatus('Starting backend…');
  const startedAt = Date.now();
  const deadline = startedAt + 90000;
  let stage = 0;
  while (Date.now() < deadline) {
    if (backendProc.exitCode !== null) break; // died — fail fast, log below
    try {
      const res = await fetch(`http://127.0.0.1:${backendPort}/api/health`);
      if (res.ok) return backendPort;
    } catch { /* not up yet */ }
    const elapsed = Date.now() - startedAt;
    if (stage === 0 && elapsed > 8000) { stage = 1; loadStatus('Backend is still warming up…'); }
    else if (stage === 1 && elapsed > 25000) { stage = 2; loadStatus('First launch can take a bit — files are being unpacked and scanned. Hang tight…'); }
    else if (stage === 2 && elapsed > 60000) { stage = 3; loadStatus('Almost there — starting the Python server…'); }
    await sleep(300);
  }
  const tail = logTail.join('').trim().split('\n').slice(-12).join('\n');
  const detail = backendProc.exitCode !== null
    ? `Backend process exited with code ${backendProc.exitCode}.${tail ? '\nLast log lines:\n' + tail : ''}`
    : `Backend did not answer /api/health on port ${backendPort} within 90s.${tail ? '\nLast log lines:\n' + tail : ''}`;
  throw new Error(detail);
}

const LOADING_HTML = `<!doctype html><html><head><meta charset="utf-8"><title>Conductor</title><style>
  html,body{margin:0;height:100%;background:#0B0B0F;color:#D6D6E0;font-family:Inter,system-ui,sans-serif;display:grid;place-items:center;user-select:none}
  .wrap{display:flex;flex-direction:column;align-items:center;gap:1.1rem}
  .logo{width:3.5rem;height:3.5rem;border-radius:1rem;display:grid;place-items:center;color:#fff;
    background:linear-gradient(135deg,#5E4EC7 0%,#1B63D9 100%);box-shadow:0 10px 40px -10px rgba(94,78,199,.7)}
  .logo svg{width:1.9rem;height:1.9rem}
  h1{margin:0;font-size:1.15rem;font-weight:650;letter-spacing:-.01em;color:#F5F5FA}
  .dots{display:inline-flex;gap:.35rem}
  .dots span{width:.42rem;height:.42rem;border-radius:50%;background:#5E4EC7;animation:b 1s infinite ease-in-out}
  .dots span:nth-child(2){animation-delay:.15s}.dots span:nth-child(3){animation-delay:.3s}
  @keyframes b{0%,80%,100%{opacity:.25;transform:scale(.85)}40%{opacity:1;transform:scale(1)}}
  .status{font-size:.72rem;color:#9A9AA8;min-height:1rem}
  .err{color:#E5484D;max-width:24rem;text-align:center;font-size:.75rem;line-height:1.5}
</style></head><body><div class="wrap">
  <div class="logo"><svg viewBox="0 0 16 16" fill="none"><path d="M8 1.2 13.6 4v4.4c0 3.3-2.2 5.6-5.6 6.6-3.4-1-5.6-3.3-5.6-6.6V4L8 1.2Z" fill="currentColor" opacity=".9"/><path d="M4.2 8h2M8.2 5.6 8.2 10.4M6.2 8h4" stroke="#0D2F86" stroke-width="1.4" stroke-linecap="round"/></svg></div>
  <h1>Conductor</h1>
  <div class="dots"><span></span><span></span><span></span></div>
  <div class="status" id="status">Starting backend…</div>
  <div class="err" id="err" hidden></div>
</div><script>
  if (window.desktop) {
    window.desktop.onLoadStatus((msg) => { document.getElementById('status').textContent = msg; });
    window.desktop.onLoadError((msg) => { document.getElementById('status').hidden = true; document.getElementById('err').hidden = false; document.getElementById('err').textContent = msg; });
  }
</script></body></html>`;

function createWindow() {
  win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 940,
    minHeight: 600,
    title: 'Conductor',
    backgroundColor: '#0B0B0F',
    frame: false, // the HTML titlebar IS the window frame (baked in)
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true, // LAW parity: renderer runs sandboxed (default-deny plugin boundary)
    },
  });
  // Instant paint: loading screen first, real UI once the backend answers.
  win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(LOADING_HTML));
  win.on('closed', () => { win = null; });
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// --- window controls -------------------------------------------------------
ipcMain.on('win:minimize', () => win?.minimize());
ipcMain.on('win:maximize', () => {
  if (!win) return;
  if (win.isMaximized()) win.unmaximize(); else win.maximize();
});
ipcMain.on('win:close', () => win?.close());
ipcMain.handle('win:is-maximized', () => win?.isMaximized() ?? false);
ipcMain.on('win:open-external', (_e, url) => { if (typeof url === 'string') shell.openExternal(url); });
ipcMain.on('win:toggle-maximize', () => {
  if (!win) return;
  if (win.isMaximized()) win.unmaximize(); else win.maximize();
});

// --- provider keys (LAW port: OS-keychain via safeStorage) ----------------
// The backend stores {value: base64, encrypted: bool} in data/provider-keys.json;
// the main process owns encryption (DPAPI/Keychain) so plaintext never reaches
// disk. Set: encrypt here, return ciphertext for the backend to persist.
// Get: read the backend's key file, decrypt, return plaintext per-request.
function backendDataDir() {
  // Same resolution as findBackend(): packaged appRoot = dirname(resources),
  // dev appRoot = the repo root (backend/ lives there).
  const here = __dirname; // .../resources/app.asar in packaged; .../conductor/desktop in dev
  const resources = path.dirname(here);
  const appRoot = path.dirname(resources);
  const devRoot = path.join(__dirname, '..');
  const root = fs.existsSync(path.join(appRoot, 'backend')) ? appRoot
    : fs.existsSync(path.join(devRoot, 'backend')) ? devRoot
    : fs.existsSync(path.join(resources, 'backend')) ? resources : appRoot;
  return path.join(root, 'data');
}

function readKeyFile() {
  try {
    const raw = fs.readFileSync(path.join(backendDataDir(), 'provider-keys.json'), 'utf-8');
    return JSON.parse(raw) || {};
  } catch { return {}; }
}

ipcMain.handle('keys:set', (_e, providerId, apiKey) => {
  const key = String(apiKey ?? '');
  let encrypted = false;
  let value = Buffer.from(key, 'utf-8').toString('base64');
  try {
    if (safeStorage.isEncryptionAvailable()) {
      value = safeStorage.encryptString(key).toString('base64');
      encrypted = true;
    }
  } catch { /* fall back to plain base64 (LAW's documented fallback) */ }
  return { encrypted, value };
});

ipcMain.handle('keys:get', (_e, providerId) => {
  const entry = readKeyFile()[String(providerId)];
  if (!entry) return null;
  try {
    const raw = Buffer.from(entry.value, 'base64');
    if (!entry.encrypted) return raw.toString('utf-8');
    return safeStorage.decryptString(raw);
  } catch { return null; } // written on another machine/user — report "no key"
});

ipcMain.handle('keys:has', (_e, providerId) => Boolean(readKeyFile()[String(providerId)]));

// ---------------------------------------------------------------------------
// Auto-update (electron-updater → GitHub Releases, repo: gabelmz/conductor)
// ---------------------------------------------------------------------------
function readUpdateToken() {
  // Prefer an env token; fall back to an optional bundled `gh-token` file
  // (a read-only token) shipped next to the app resources for private repos.
  if (process.env.CONDUCTOR_GH_TOKEN) return process.env.CONDUCTOR_GH_TOKEN.trim();
  try {
    const t = fs.readFileSync(path.join(process.resourcesPath, 'gh-token'), 'utf8').trim();
    return t || null;
  } catch { return null; }
}

function setupAutoUpdater() {
  if (!app.isPackaged) return; // dev / smoke runs never check for updates
  try { autoUpdater = require('electron-updater').autoUpdater; } catch { return; }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  // Forward every updater event to the renderer (About → Software update) so
  // the UI can reflect check/download/error state live.
  const emit = (event, data) => {
    try { win?.webContents.send('updates:event', { event, ...(data || {}) }); } catch { /* window gone */ }
  };

  autoUpdater.on('checking-for-update', () => emit('checking-for-update'));
  autoUpdater.on('update-available', (info) => emit('update-available', { version: info && info.version }));
  autoUpdater.on('update-not-available', (info) => emit('update-not-available', { version: info && info.version }));
  autoUpdater.on('download-progress', (p) => emit('download-progress', {
    percent: Math.round(p.percent || 0), transferred: p.transferred, total: p.total,
  }));
  autoUpdater.on('update-downloaded', (info) => {
    downloadedVersion = (info && info.version) || null;
    emit('update-downloaded', { version: info && info.version });
    if (!win) return;
    dialog.showMessageBox(win, {
      type: 'info',
      title: 'Update ready',
      message: `Conductor ${info.version} is ready to install.`,
      detail: 'Restart now to apply the update.',
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => { if (response === 0) autoUpdater.quitAndInstall(); });
  });
  autoUpdater.on('error', (err) => emit('error', { message: String((err && err.message) || err) }));

  const token = readUpdateToken();
  try {
    autoUpdater.setFeedURL({
      provider: 'github', owner: 'gabelmz', repo: 'conductor', private: true,
      ...(token ? { token } : {}),
    });
  } catch { /* keep electron-builder publish defaults */ }
  autoUpdater.checkForUpdatesAndNotify().catch(() => {});
}

// --- updates IPC (About → Software update) ---------------------------------
ipcMain.handle('updates:info', () => ({
  version: app.getVersion(),
  isPackaged: app.isPackaged,
  enabled: !!autoUpdater,
  downloaded: downloadedVersion,
}));

ipcMain.handle('updates:check', async () => {
  if (!autoUpdater) return { available: false, reason: 'updates-disabled', downloaded: downloadedVersion };
  try {
    const res = await autoUpdater.checkForUpdates();
    const info = res && res.updateInfo ? res.updateInfo : null;
    return { available: !!info, version: info ? info.version : null, downloaded: downloadedVersion };
  } catch (err) {
    return { available: false, error: String((err && err.message) || err), downloaded: downloadedVersion };
  }
});

ipcMain.handle('updates:install', () => {
  if (!autoUpdater) return { ok: false, error: 'updates-disabled' };
  autoUpdater.quitAndInstall();
  return { ok: true };
});

app.whenReady().then(async () => {
  createWindow(); // instant paint with loading screen
  setupAutoUpdater();
  try {
    await startBackend();
    win?.loadURL(`http://127.0.0.1:${backendPort}/`);
  } catch (err) {
    // First boot after a fresh extraction can be slow (AV scan, disk cache
    // cold) or hit a transient lock — give it one clean retry before failing.
    try {
      loadStatus('Retrying backend startup…');
      killBackend();
      await sleep(600);
      await startBackend();
      win?.loadURL(`http://127.0.0.1:${backendPort}/`);
    } catch (err2) {
      if (win) {
        win.webContents.send('load:error', `Backend failed to start:\n${err2.message}`);
        await sleep(6000);
      }
      dialog.showErrorBox('Conductor', `Failed to start backend:\n${err2.message}`);
      app.quit();
    }
  }
});

app.on('window-all-closed', () => {
  killBackend(); // belt-and-braces: free the port/process even if quit is blocked
  app.quit();
});

app.on('before-quit', () => {
  killBackend();
});
