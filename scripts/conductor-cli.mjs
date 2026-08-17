#!/usr/bin/env node
/**
 * conductor — Conductor management CLI (ported from law-cli).
 *
 * Version control, plugin management, release staging, and repo health
 * checks for the Conductor desktop app.
 *
 *   node scripts/conductor-cli.mjs health      backend health check
 *   node scripts/conductor-cli.mjs plugins     list plugins + enabled state
 *   node scripts/conductor-cli.mjs plugins --enable <id>
 *   node scripts/conductor-cli.mjs plugins --disable <id>
 *   node scripts/conductor-cli.mjs doctor      venv/deps/build pre-flight check
 *   node scripts/conductor-cli.mjs version     app + electron-builder versions
 *   node scripts/conductor-cli.mjs checksums   SHA-256 of dist artifacts
 *   node scripts/conductor-cli.mjs release     build + checksums + staging note
 */
import { createHash } from 'node:crypto';
import { execSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const DATA = join(ROOT, 'data');
const PKG = JSON.parse(readFileSync(join(ROOT, 'desktop', 'package.json'), 'utf-8'));

const HOSTED = ['anthropic', 'openai', 'grok', 'deepseek'];

function sha256(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

async function health() {
  const port = process.env.CONDUCTOR_PORT || 8799;
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/health`, { signal: AbortSignal.timeout(5000) });
    const body = await res.json();
    console.log(`health: ${res.ok ? 'OK' : 'FAIL'} (${res.status}) —`, JSON.stringify(body));
    return res.ok ? 0 : 1;
  } catch (e) {
    console.error(`health: UNREACHABLE on :${port} — ${e.message}`);
    return 1;
  }
}

async function plugins(action, id) {
  const port = process.env.CONDUCTOR_PORT || 8799;
  const base = `http://127.0.0.1:${port}/api/plugins`;
  try {
    if (action === 'enable' || action === 'disable') {
      if (!id) { console.error('plugins: --enable/--disable requires a plugin id'); return 1; }
      const res = await fetch(`${base}/${id}/enabled`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: action === 'enable' }),
      });
      if (!res.ok) { console.error(`plugins: ${res.status} ${await res.text()}`); return 1; }
      console.log(`plugins: ${id} ${action}d`);
      return 0;
    }
    const res = await fetch(base);
    const data = await res.json();
    for (const p of data.plugins || []) {
      console.log(`${p.enabled ? '✓' : '✗'} ${p.id.padEnd(16)} v${p.version}  ${p.name || ''}`);
    }
    return 0;
  } catch (e) {
    console.error(`plugins: backend unreachable on :${port} — ${e.message} (start the app first)`);
    return 1;
  }
}

function doctor() {
  let ok = true;
  const check = (label, pass, detail = '') => {
    console.log(`${pass ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`);
    if (!pass) ok = false;
  };

  const venvPy = join(ROOT, '.venv', 'Scripts', 'python.exe');
  check('dev venv exists', existsSync(venvPy), venvPy);
  if (existsSync(venvPy)) {
    for (const dep of ['fastapi', 'uvicorn', 'multipart', 'requests']) {
      try {
        execSync(`"${venvPy}" -c "import ${dep}"`, { stdio: 'pipe' });
        check(`dep ${dep}`, true);
      } catch {
        check(`dep ${dep}`, false, 'missing — run pip install fastapi uvicorn python-multipart requests');
      }
    }
  }
  check('models dir present', existsSync(join(ROOT, 'models')));
  const keyFile = join(DATA, 'provider-keys.json');
  if (existsSync(keyFile)) {
    try {
      const keys = JSON.parse(readFileSync(keyFile, 'utf-8'));
      const encrypted = Object.entries(keys).filter(([, v]) => v.encrypted);
      check('provider keys', true, `${Object.keys(keys).length} stored, ${encrypted.length} encrypted`);
    } catch { check('provider keys', false, 'unparseable provider-keys.json'); }
  }
  const distExes = readdirSync(DIST).filter((f) => f.endsWith('.exe'));
  check('dist artifacts', distExes.length > 0, distExes.join(', ') || 'run npm run dist');
  return ok ? 0 : 1;
}

function version() {
  console.log(`conductor ${PKG.version} (productName=${PKG.productName})`);
  console.log(`electron ^${PKG.devDependencies.electron.replace('^', '')}`);
  console.log(`electron-builder ^${PKG.devDependencies['electron-builder'].replace('^', '')}`);
  return 0;
}

function checksums() {
  if (!existsSync(DIST)) { console.error('checksums: dist/ missing — run the build first'); return 1; }
  const exes = readdirSync(DIST).filter((f) => f.endsWith('.exe')).sort();
  if (!exes.length) { console.error('checksums: no .exe artifacts in dist/'); return 1; }
  console.log('SHA-256 checksums:');
  for (const f of exes) {
    const p = join(DIST, f);
    console.log(`${sha256(p)}  ${f}  (${(statSync(p).size / 1048576).toFixed(1)} MB)`);
  }
  return 0;
}

function release() {
  const { execSync: run } = { execSync };
  try {
    console.log('release: building nsis + portable…');
    run('npx electron-builder --win nsis portable', { cwd: join(ROOT, 'desktop'), stdio: 'inherit' });
  } catch (e) {
    console.error(`release: build failed — ${e.message}`);
    return 1;
  }
  const cs = checksums();
  console.log('release: staged under dist/ — upload Setup + Portable + checksums above.');
  return cs;
}

const [cmd, flag, id] = process.argv.slice(2);
switch (cmd) {
  case 'health': process.exit(await health()); break;
  case 'plugins': process.exit(await plugins(flag?.replace('--', ''), id)); break;
  case 'doctor': process.exit(doctor()); break;
  case 'version': process.exit(version()); break;
  case 'checksums': process.exit(checksums()); break;
  case 'release': process.exit(release()); break;
  default:
    console.log(`conductor CLI — usage:
  health                check the running backend (CONDUCTOR_PORT to override)
  plugins               list plugins (--enable <id> / --disable <id>)
  doctor                venv/deps/dist pre-flight checks
  version               app + toolchain versions
  checksums             SHA-256 of dist artifacts
  release               build nsis+portable, then print checksums`);
    process.exit(cmd ? 2 : 0);
}
