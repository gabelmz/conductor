/**
 * electron-builder afterPack hook — refuse to package an app with no Python.
 *
 * The backend is a FastAPI app run by the venv interpreter that `extraResources`
 * copies from ../.venv to resources/venv. That directory is gitignored, so on a
 * clean checkout (CI) it simply does not exist — and electron-builder skips a
 * missing extraResources source without failing. The result is an installer that
 * looks fine, installs fine, and then dies on launch in findBackend() with
 * "Could not locate the backend Python environment" (shipped as v2.4.0).
 *
 * Fail the build here instead, where the cause is still obvious.
 */
const path = require("node:path");
const fs = require("node:fs");

exports.default = async function verifyPythonBundled(context) {
  const resources = path.join(context.appOutDir, "resources");
  const python = path.join(resources, "venv", "Scripts", "python.exe");

  if (!fs.existsSync(python)) {
    throw new Error(
      [
        "",
        "Packaged app has no bundled Python environment.",
        `  expected: ${python}`,
        "",
        "extraResources copies ../.venv -> resources/venv, but ../.venv is",
        "gitignored and does not exist in this working tree. Create it before",
        "packaging:",
        "",
        "  python -m venv .venv",
        "  .venv/Scripts/python.exe -m pip install -r requirements.txt",
        "",
        "Shipping without it produces an installer that cannot start its backend.",
        "",
      ].join("\n"),
    );
  }

  // A venv is only a launcher plus site-packages; it resolves its stdlib through
  // the base interpreter named in pyvenv.cfg. If that path does not exist on the
  // target machine, python.exe cannot start. Surface it rather than shipping blind.
  const cfg = path.join(resources, "venv", "pyvenv.cfg");
  const home = fs
    .readFileSync(cfg, "utf8")
    .split(/\r?\n/)
    .map((l) => /^\s*home\s*=\s*(.+?)\s*$/.exec(l))
    .find(Boolean)?.[1];
  if (home && !fs.existsSync(path.join(home, "python.exe"))) {
    throw new Error(
      `Bundled venv points at a base interpreter that is missing: ${home}\n` +
        "The packaged python.exe would fail to find its stdlib on any machine\n" +
        "without that exact path. Bundle a self-contained Python instead.",
    );
  }
  console.log(`  • bundled python verified (base: ${home || "unknown"})`);
};
