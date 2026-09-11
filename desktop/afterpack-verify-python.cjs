/**
 * electron-builder afterPack hook — refuse to package an app with no Python,
 * or with a Python that cannot possibly run on another machine.
 *
 * The backend is a FastAPI app run by the interpreter `extraResources` copies
 * from ../.venv-portable to resources/venv (see scripts/build-portable-
 * python.mjs). That directory is gitignored, so on a clean checkout (CI) it
 * simply does not exist unless the build step created it first — and
 * electron-builder skips a missing extraResources source without failing.
 * The result is an installer that looks fine, installs fine, and then dies
 * on launch in findBackend() with "Could not locate the backend Python
 * environment" (shipped as v2.4.0).
 *
 * A plain `venv` is a second, subtler way to ship a broken backend: its
 * python.exe is a launcher shim whose pyvenv.cfg names an absolute `home`
 * path to the base interpreter it was created from, and it refuses to start
 * if that path is missing on the machine that runs it. That path is
 * guaranteed absent on any machine other than the one that built it —
 * including a CI runner, whose base Python lives in an ephemeral per-job
 * toolcache directory that is gone before the installer is even uploaded.
 * Every CI-built release through v2.5.4 shipped exactly this, silently
 * broken for every real user, because it only ever got tested against the
 * build machine's own now-still-present base Python. The portable-python
 * build script avoids this entirely (no pyvenv.cfg, no external `home`
 * reference) — this hook fails the build if that ever regresses.
 *
 * Fail the build here instead, where the cause is still obvious.
 */
const path = require("node:path");
const fs = require("node:fs");

exports.default = async function verifyPythonBundled(context) {
  const resources = path.join(context.appOutDir, "resources");
  const python = path.join(resources, "venv", "python.exe");

  if (!fs.existsSync(python)) {
    throw new Error(
      [
        "",
        "Packaged app has no bundled Python environment.",
        `  expected: ${python}`,
        "",
        "extraResources copies ../.venv-portable -> resources/venv, but",
        "../.venv-portable is gitignored and does not exist in this working",
        "tree. Build it before packaging:",
        "",
        "  node scripts/build-portable-python.mjs",
        "",
        "Shipping without it produces an installer that cannot start its backend.",
        "",
      ].join("\n"),
    );
  }

  // A plain venv is not portable — see the module docstring. If one ever
  // shows up here (e.g. someone reverts extraResources to ../.venv), fail
  // loudly instead of shipping a backend that only works on the build machine.
  const pyvenvCfg = path.join(resources, "venv", "pyvenv.cfg");
  if (fs.existsSync(pyvenvCfg)) {
    const home = fs
      .readFileSync(pyvenvCfg, "utf8")
      .split(/\r?\n/)
      .map((l) => /^\s*home\s*=\s*(.+?)\s*$/.exec(l))
      .find(Boolean)?.[1];
    throw new Error(
      [
        "",
        "Bundled Python is a venv, not the portable distribution.",
        `  found: ${pyvenvCfg}`,
        home ? `  home = ${home}` : "",
        "",
        "A venv's python.exe needs that exact base-interpreter path to exist",
        "on the machine that runs it — guaranteed false on any machine other",
        "than the one that built it (and often false there too, once a CI",
        "runner's ephemeral toolcache is gone). Bundle scripts/build-portable-",
        "python.mjs's output instead.",
        "",
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }

  // Sanity-check it can actually start and see its own stdlib/packages,
  // rather than only checking the file exists.
  const { spawnSync } = require("node:child_process");
  const probe = spawnSync(python, ["-c", "import fastapi, uvicorn"], { windowsHide: true });
  if (probe.status !== 0) {
    const detail = (probe.stderr?.toString("utf-8") || "").trim();
    throw new Error(
      `Bundled Python cannot import fastapi/uvicorn — packaging produced a broken bundle.\n${detail}`,
    );
  }
  console.log("  • bundled portable python verified (self-contained, no pyvenv.cfg, imports OK)");
};
