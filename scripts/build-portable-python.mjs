#!/usr/bin/env node
/**
 * Builds a genuinely self-contained Python environment for bundling into the
 * Electron installer, replacing a plain `venv`.
 *
 * A `venv` is not portable: its python.exe is a launcher shim whose
 * pyvenv.cfg names an absolute `home` path to the base interpreter it was
 * created from, and it refuses to start if that path is missing. That is
 * fine on the machine that created it and fatal everywhere else — including
 * a CI runner, whose base Python lives in an ephemeral per-job toolcache
 * directory (e.g. C:\hostedtoolcache\windows\Python\3.11.9\x64) that no
 * longer exists once the job ends, let alone on an end user's machine.
 *
 * Python's official "embeddable package" has no such dependency: python.exe,
 * python311.dll, the zipped stdlib, and every extension module ship
 * together in one flat, relocatable directory. This script downloads it,
 * enables site-packages, bootstraps pip, and installs requirements.txt into
 * it — producing a directory that can be copied anywhere and just run.
 *
 * Usage: node scripts/build-portable-python.mjs [outDir]
 *   outDir defaults to ../.venv-portable (relative to this script).
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, "..");

const PYTHON_VERSION = "3.11.9"; // last 3.11.x with an embeddable build published on python.org
const EMBED_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
const GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py";

const outDir = path.resolve(process.argv[2] || path.join(REPO_ROOT, ".venv-portable"));
const requirementsPath = path.join(REPO_ROOT, "requirements.txt");

function log(msg) {
  console.log(`[build-portable-python] ${msg}`);
}

async function download(url, destPath) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to download ${url}: HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  writeFileSync(destPath, buf);
}

async function main() {
  if (!existsSync(requirementsPath)) {
    throw new Error(`requirements.txt not found at ${requirementsPath}`);
  }

  if (existsSync(outDir)) {
    log(`removing existing ${outDir}`);
    rmSync(outDir, { recursive: true, force: true });
  }
  mkdirSync(outDir, { recursive: true });

  const tmpDir = path.join(REPO_ROOT, ".portable-python-tmp");
  if (existsSync(tmpDir)) rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });

  const zipPath = path.join(tmpDir, "python-embed.zip");
  log(`downloading ${EMBED_URL}`);
  await download(EMBED_URL, zipPath);

  log(`extracting to ${outDir}`);
  // Explicitly the native Windows tar.exe (bundled since Windows 10, handles
  // zip extraction with no extra deps) — invoking bare `tar` can resolve to
  // MSYS/Git-Bash's tar instead when this script runs from a bash shell,
  // which mishandles an absolute Windows drive path (tries to treat `C:` as
  // a remote host). The System32 copy always exists on both a local Windows
  // dev machine and the windows-latest CI runner this also builds on.
  const systemTar = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "tar.exe");
  execFileSync(systemTar, ["-xf", zipPath, "-C", outDir], { stdio: "inherit" });

  const pythonExe = path.join(outDir, "python.exe");
  if (!existsSync(pythonExe)) {
    throw new Error(`Extraction did not produce ${pythonExe} — embeddable zip layout may have changed.`);
  }

  // Enable site-packages: uncomment `import site` and explicitly add
  // Lib\site-packages as its own sys.path entry (more reliable than relying
  // on site.py's own directory auto-discovery for a non-standard layout).
  const pthPath = path.join(outDir, "python311._pth");
  let pth = readFileSync(pthPath, "utf-8");
  pth = pth.replace("#import site", "import site");
  if (!pth.includes("Lib\\site-packages") && !pth.includes("Lib/site-packages")) {
    pth += "\nLib\\site-packages\n";
  }
  writeFileSync(pthPath, pth);
  mkdirSync(path.join(outDir, "Lib", "site-packages"), { recursive: true });

  const getPipPath = path.join(tmpDir, "get-pip.py");
  log(`downloading ${GET_PIP_URL}`);
  await download(GET_PIP_URL, getPipPath);

  log("bootstrapping pip");
  execFileSync(pythonExe, [getPipPath, "--no-warn-script-location"], { stdio: "inherit" });

  log(`installing requirements from ${requirementsPath}`);
  execFileSync(
    pythonExe,
    ["-m", "pip", "install", "-r", requirementsPath, "--no-warn-script-location", "--disable-pip-version-check"],
    { stdio: "inherit" },
  );

  rmSync(tmpDir, { recursive: true, force: true });

  log("verifying the bundle is genuinely self-contained (no pyvenv.cfg / external home path)");
  if (existsSync(path.join(outDir, "pyvenv.cfg"))) {
    throw new Error("Unexpected pyvenv.cfg in an embeddable build — this would reintroduce the non-portable dependency.");
  }
  execFileSync(pythonExe, ["-c", "import fastapi, uvicorn, requests, openpyxl, mcp, docx, pdfplumber, pyxlsb, multipart; print('all required imports OK')"], {
    stdio: "inherit",
  });

  log(`done: ${outDir}`);
}

main().catch((err) => {
  console.error(`[build-portable-python] FAILED: ${err.message}`);
  process.exit(1);
});
