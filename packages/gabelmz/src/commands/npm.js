/**
 * NPM Wrapper, Pre-Publish Health Checker & Publisher
 * Inspects package.json, verifies auth, dry-runs publish, and provides quick scripts runner
 */

import { execSync, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import {
  bold,
  dim,
  fireAmber,
  fireCrimson,
  fireOrange,
  fireRed,
  fireWhite,
  fireYellow,
  gray,
  green,
  cyan,
  badge,
  box,
  bgBlack,
} from '../ui/colors.js';
import { printCompactBanner } from '../ui/skull.js';

// Get npm whoami
export function getNpmUser() {
  try {
    const res = execSync('npm whoami', { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
    return { user: res, ok: true };
  } catch (e) {
    return { user: null, ok: false, error: e.message };
  }
}

// Check remote registry status for package & version
export function checkNpmRegistry(packageName, version) {
  try {
    const res = execSync(`npm view ${packageName} version --json`, {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const remoteVersion = JSON.parse(res.trim());
    return {
      exists: true,
      latestVersion: remoteVersion,
      versionConflict: remoteVersion === version,
    };
  } catch (e) {
    if (e.message && e.message.includes('E404')) {
      return { exists: false, latestVersion: null, versionConflict: false };
    }
    return { exists: false, error: e.message };
  }
}

// Pre-publish validation check
export function auditPackageForPublish(pkgDir = process.cwd()) {
  const pkgPath = join(pkgDir, 'package.json');
  const issues = [];
  const warnings = [];
  const passes = [];

  if (!existsSync(pkgPath)) {
    return {
      ok: false,
      pkg: null,
      issues: [`package.json not found in ${pkgDir}`],
      warnings: [],
      passes: [],
    };
  }

  let pkg = null;
  try {
    pkg = JSON.parse(readFileSync(pkgPath, 'utf-8'));
  } catch (e) {
    return {
      ok: false,
      pkg: null,
      issues: [`Unparseable package.json: ${e.message}`],
      warnings: [],
      passes: [],
    };
  }

  // Check 1: Private flag
  if (pkg.private === true) {
    issues.push(`"private": true is set in package.json. npm publish will FAIL with EPRIVATE.`);
  } else {
    passes.push(`"private" is false/unset (publicly publishable)`);
  }

  // Check 2: Package name
  if (!pkg.name || typeof pkg.name !== 'string') {
    issues.push(`Missing or invalid "name" field in package.json.`);
  } else {
    passes.push(`Package name: ${bold(pkg.name)}`);
  }

  // Check 3: Version
  if (!pkg.version || !/^\d+\.\d+\.\d+/.test(pkg.version)) {
    issues.push(`Missing or invalid semver "version" field (current: "${pkg.version}").`);
  } else {
    passes.push(`Version: ${bold(`v${pkg.version}`)}`);
  }

  // Check 4: Bin entry points exist
  if (pkg.bin) {
    if (typeof pkg.bin === 'string') {
      const binPath = join(pkgDir, pkg.bin);
      if (!existsSync(binPath)) {
        issues.push(`Binary entry point missing on disk: ${pkg.bin}`);
      } else {
        passes.push(`Binary entry point verified: ${pkg.bin}`);
      }
    } else if (typeof pkg.bin === 'object') {
      for (const [cmd, p] of Object.entries(pkg.bin)) {
        const binPath = join(pkgDir, p);
        if (!existsSync(binPath)) {
          issues.push(`Binary command "${cmd}" path missing: ${p}`);
        } else {
          passes.push(`Binary command "${cmd}" verified: ${p}`);
        }
      }
    }
  }

  // Check 5: Main entry
  if (pkg.main) {
    const mainPath = join(pkgDir, pkg.main);
    if (!existsSync(mainPath)) {
      warnings.push(`"main" entry file does not exist: ${pkg.main}`);
    } else {
      passes.push(`Main entry verified: ${pkg.main}`);
    }
  }

  // Check 6: License & Description
  if (!pkg.license) warnings.push(`Missing "license" field in package.json (e.g. "MIT")`);
  if (!pkg.description) warnings.push(`Missing "description" field in package.json`);

  // Check 7: NPM Auth
  const auth = getNpmUser();
  if (!auth.ok) {
    issues.push(`NPM auth failed: Not logged in. Run ${bold('npm login')} or configure ~/.npmrc`);
  } else {
    passes.push(`NPM authenticated as: ${bold(cyan(auth.user))}`);
  }

  // Check 8: Remote registry version conflict
  if (pkg.name && pkg.version && auth.ok) {
    const reg = checkNpmRegistry(pkg.name, pkg.version);
    if (reg.exists && reg.versionConflict) {
      issues.push(`Version v${pkg.version} is ALREADY published on npm registry. Bump version before publishing.`);
    } else if (reg.exists) {
      passes.push(`Registry package exists (latest remote: v${reg.latestVersion})`);
    } else {
      passes.push(`Package name "${pkg.name}" is available on npm!`);
    }
  }

  return {
    ok: issues.length === 0,
    pkg,
    pkgPath,
    issues,
    warnings,
    passes,
  };
}

// Dry-run publish and get package manifest stats
export function runDryRun(pkgDir = process.cwd()) {
  try {
    const res = execSync('npm publish --dry-run --json', {
      cwd: pkgDir,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const parsed = JSON.parse(res);
    return { ok: true, data: parsed };
  } catch (e) {
    // If json fails, try plain text
    try {
      const txt = execSync('npm publish --dry-run', {
        cwd: pkgDir,
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      return { ok: true, raw: txt };
    } catch (err2) {
      return { ok: false, error: err2.stderr || err2.message };
    }
  }
}

// Version bumper
export function bumpVersion(type = 'patch', pkgDir = process.cwd()) {
  const pkgPath = join(pkgDir, 'package.json');
  if (!existsSync(pkgPath)) {
    throw new Error(`package.json not found in ${pkgDir}`);
  }
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf-8'));
  const current = pkg.version || '0.0.0';
  const parts = current.split('.').map((n) => parseInt(n, 10) || 0);

  if (type === 'major') {
    parts[0] += 1;
    parts[1] = 0;
    parts[2] = 0;
  } else if (type === 'minor') {
    parts[1] += 1;
    parts[2] = 0;
  } else {
    parts[2] += 1;
  }

  const next = parts.join('.');
  pkg.version = next;
  writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf-8');
  return { previous: current, current: next };
}

// CLI handler for `gabelmz npm`
export async function runNpmCommand(args = []) {
  printCompactBanner('NPM Wrapper & Publisher');

  const subcmd = args[0] || 'check';
  const rest = args.slice(1);

  if (subcmd === 'whoami' || subcmd === 'status' || subcmd === 'auth') {
    const { user, ok, error } = getNpmUser();
    console.log(`\n${bold('NPM Authentication Status:')}`);
    if (ok) {
      console.log(`  ${green('✓')} Logged in as: ${bold(cyan(user))}`);
      console.log(`  ${green('✓')} Registry:   https://registry.npmjs.org/\n`);
    } else {
      console.log(`  ${fireRed('✗')} Not authenticated: ${error || 'Unknown error'}`);
      console.log(`  ${dim('Run')} ${fireYellow('npm login')} ${dim('to authenticate.')}\n`);
    }
    return ok ? 0 : 1;
  }

  if (subcmd === 'check' || subcmd === 'audit' || subcmd === 'dry-run') {
    const audit = auditPackageForPublish(process.cwd());

    console.log(`\n${bold(fireOrange('📦 Pre-Publish Health Check'))} ${dim(`(${process.cwd()})`)}\n`);

    for (const p of audit.passes) {
      console.log(`  ${green('✓')} ${p}`);
    }
    for (const w of audit.warnings) {
      console.log(`  ${fireAmber('!')} ${w}`);
    }
    for (const i of audit.issues) {
      console.log(`  ${fireRed('✗')} ${bold(i)}`);
    }

    console.log('');

    if (!audit.ok) {
      console.log(` ${fireRed('Publish Readiness: BLOCKED')}`);
      console.log(` ${dim('Resolve the issues above before running npm publish.')}\n`);
      return 1;
    }

    console.log(` ${green('Publish Readiness: READY TO PUBLISH')} ${bold(fireYellow('🔥'))}`);

    // Run dry run
    console.log(`\n ${dim('Running npm publish --dry-run...')}`);
    const dry = runDryRun(process.cwd());
    if (dry.ok && dry.data) {
      const d = dry.data;
      console.log(`  • Package:       ${bold(d.name || audit.pkg.name)}@${d.version || audit.pkg.version}`);
      console.log(`  • Total Files:   ${d.files?.length || 'N/A'}`);
      console.log(`  • Unpacked Size: ${(d.unpackedSize ? (d.unpackedSize / 1024).toFixed(1) + ' kB' : 'N/A')}`);
      console.log(`  • Shasum:        ${d.shasum || 'N/A'}`);
    } else if (dry.ok && dry.raw) {
      console.log(dim(dry.raw));
    }
    console.log('');
    return 0;
  }

  if (subcmd === 'bump') {
    const type = rest[0] || 'patch';
    try {
      const res = bumpVersion(type, process.cwd());
      console.log(`\n ${green('✓')} Bumped version: ${dim(res.previous)} ➔ ${bold(fireYellow(res.current))}\n`);
      return 0;
    } catch (e) {
      console.error(`\n ${fireRed('Failed to bump version:')} ${e.message}\n`);
      return 1;
    }
  }

  if (subcmd === 'scripts') {
    const pkgPath = join(process.cwd(), 'package.json');
    if (!existsSync(pkgPath)) {
      console.log(`\n ${fireRed('No package.json found in')} ${process.cwd()}\n`);
      return 1;
    }
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf-8'));
    const scripts = pkg.scripts || {};
    console.log(`\n${bold(fireOrange('Available Package Scripts:'))}\n`);
    for (const [name, script] of Object.entries(scripts)) {
      console.log(`  ${fireAmber('●')} ${bold(fireWhite(name.padEnd(18)))} ${dim(script)}`);
    }
    console.log(`\n ${dim('Run any script with:')} ${fireYellow('npm run <script-name>')}\n`);
    return 0;
  }

  if (subcmd === 'publish' || subcmd === 'pub') {
    const audit = auditPackageForPublish(process.cwd());
    if (!audit.ok) {
      console.log(`\n ${fireRed('Cannot publish: Pre-flight checks failed!')}`);
      audit.issues.forEach((i) => console.log(`  ${fireRed('✗')} ${i}`));
      console.log('');
      return 1;
    }

    console.log(`\n ${bold(fireYellow('Publishing package to npm registry...'))}`);
    const isScoped = audit.pkg.name.startsWith('@');
    const pubArgs = isScoped ? ['publish', '--access', 'public'] : ['publish'];

    const proc = spawnSync('npm', pubArgs, {
      cwd: process.cwd(),
      stdio: 'inherit',
      shell: true,
    });

    if (proc.status === 0) {
      console.log(`\n ${bold(green('🎉 Successfully published'))} ${bold(fireWhite(audit.pkg.name))}@${audit.pkg.version} to npm!\n`);
      return 0;
    } else {
      console.log(`\n ${fireRed(`npm publish exited with code ${proc.status}`)}\n`);
      return proc.status || 1;
    }
  }

  // Passthrough to native npm
  console.log(` ${dim('Running:')} npm ${args.join(' ')}\n`);
  const proc = spawnSync('npm', args, {
    cwd: process.cwd(),
    stdio: 'inherit',
    shell: true,
  });
  return proc.status || 0;
}
